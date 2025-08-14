"""GitHub API tool for PR Check Agent
Handles all GitHub API interactions as a LangGraph tool
"""

import asyncio
import fnmatch
import os
from typing import Any

import aiohttp
from github import Github
from github.GithubException import GithubException
from langchain.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field

from src.state.schemas import CheckInfo, CheckStatus, PRInfo


class GitHubAPIInput(BaseModel):
    """Input schema for GitHub API operations."""

    operation: str = Field(description="Operation to perform: 'get_prs', 'get_checks', 'get_check_logs'")
    repository: str = Field(description="Repository in format 'owner/repo'")
    pr_number: int | None = Field(default=None, description="PR number for PR-specific operations")
    check_run_id: int | None = Field(default=None, description="Check run ID for log retrieval")
    branch_filter: list[str] | None = Field(default=None, description="Filter PRs by branches")


class GitHubTool(BaseTool):
    """LangGraph tool for GitHub API operations."""

    name: str = "github_api"
    description: str = "Interact with GitHub API to get PR and check information"
    args_schema: type = GitHubAPIInput

    class Config:
        extra = "allow"

    def __init__(self):
        super().__init__()
        self.github_token = os.getenv("GITHUB_TOKEN")
        if not self.github_token:
            raise ValueError("GITHUB_TOKEN environment variable is required")

        self.github = Github(self.github_token)
        self._rate_limit_remaining = 5000
        self._rate_limit_reset = None

        logger.info("GitHub API tool initialized")

    def _run(self, operation: str, repository: str, **kwargs) -> dict[str, Any]:
        """Synchronous wrapper for async operations."""
        return asyncio.run(self._arun(operation, repository, **kwargs))

    async def _arun(
        self,
        operation: str,
        repository: str,
        pr_number: int | None = None,
        check_run_id: int | None = None,
        branch_filter: list[str] | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Execute GitHub API operation."""
        try:
            if operation == "get_prs":
                return await self._get_open_prs(repository, branch_filter)
            if operation == "get_checks":
                if not pr_number:
                    raise ValueError("PR number required for get_checks operation")
                return await self._get_pr_checks(repository, pr_number)
            if operation == "get_check_logs":
                if not check_run_id:
                    raise ValueError("Check run ID required for get_check_logs operation")
                return await self._get_check_logs(repository, check_run_id)
            raise ValueError(f"Unknown operation: {operation}")

        except Exception as e:
            logger.error(f"GitHub API error: {e}")
            return {"error": str(e), "success": False}

    async def _get_open_prs(self, repository: str, branch_filter: list[str] | None = None) -> dict[str, Any]:
        """Get open pull requests for a repository."""
        try:
            repo = self.github.get_repo(repository)
            pulls = repo.get_pulls(state="open")

            logger.debug(f"Fetching PRs for {repository} with branch filter: {branch_filter}")

            pr_list = []
            total_prs = 0
            for pr in pulls:
                total_prs += 1
                logger.debug(f"Found PR #{pr.number}: '{pr.title}' (base: {pr.base.ref}, head: {pr.head.ref})")

                # Apply branch filter if specified
                if branch_filter:
                    # Check if the head branch (source branch) matches any filter pattern
                    branch_matches = False
                    for pattern in branch_filter:
                        if "*" in pattern:
                            # Handle wildcard patterns
                            if fnmatch.fnmatch(pr.head.ref, pattern):
                                branch_matches = True
                                break
                        elif pr.head.ref == pattern:
                            # Exact match
                            branch_matches = True
                            break

                    if not branch_matches:
                        logger.debug(f"Skipping PR #{pr.number} - head branch '{pr.head.ref}' doesn't match filters")
                        continue

                pr_info = PRInfo(
                    number=pr.number,
                    title=pr.title,
                    author=pr.user.login,
                    branch=pr.head.ref,
                    base_branch=pr.base.ref,
                    url=pr.html_url,
                    created_at=pr.created_at,
                    updated_at=pr.updated_at,
                    draft=pr.draft,
                    mergeable=pr.mergeable,
                )
                pr_list.append(pr_info.dict())

            logger.info(f"Retrieved {len(pr_list)} open PRs for {repository}")
            return {"success": True, "prs": pr_list, "count": len(pr_list)}

        except GithubException as e:
            logger.error(f"GitHub API error getting PRs for {repository}: {e}")
            return {"error": str(e), "success": False}

    async def _get_pr_checks(self, repository: str, pr_number: int) -> dict[str, Any]:
        """Get check runs for a specific PR."""
        try:
            repo = self.github.get_repo(repository)
            pr = repo.get_pull(pr_number)

            # Get the latest commit
            commits = pr.get_commits()
            latest_commit = commits[commits.totalCount - 1]

            # Get check runs for the latest commit
            check_runs = latest_commit.get_check_runs()

            checks = {}
            for check_run in check_runs:
                # Map GitHub status to our CheckStatus enum
                status = self._map_check_status(check_run.status, check_run.conclusion)

                check_info = CheckInfo(
                    name=check_run.name,
                    status=status,
                    conclusion=check_run.conclusion,
                    details_url=check_run.html_url,
                    started_at=check_run.started_at,
                    completed_at=check_run.completed_at,
                )

                checks[check_run.name] = check_info.dict()

            # Also get status checks (different API)
            statuses = latest_commit.get_statuses()
            for status in statuses:
                if status.context not in checks:  # Don't duplicate
                    check_status = self._map_status_check(status.state)

                    check_info = CheckInfo(
                        name=status.context,
                        status=check_status,
                        conclusion=status.state,
                        details_url=status.target_url or "",
                        started_at=status.created_at,
                        completed_at=status.updated_at,
                    )

                    checks[status.context] = check_info.dict()

            logger.info(f"Retrieved {len(checks)} checks for PR #{pr_number} in {repository}")
            return {"success": True, "checks": checks, "commit_sha": latest_commit.sha, "count": len(checks)}

        except GithubException as e:
            logger.error(f"GitHub API error getting checks for PR #{pr_number}: {e}")
            return {"error": str(e), "success": False}

    async def _get_check_logs(self, repository: str, check_run_id: int) -> dict[str, Any]:
        """Get logs/annotations for a specific check run."""
        try:
            # Use direct API call for check run details and logs
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"token {self.github_token}", "Accept": "application/vnd.github.v3+json"}

                # Get check run details
                url = f"https://api.github.com/repos/{repository}/check-runs/{check_run_id}"
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        check_data = await response.json()
                    else:
                        raise Exception(f"Failed to get check run: {response.status}")

                # Get annotations (error messages)
                annotations_url = f"{url}/annotations"
                async with session.get(annotations_url, headers=headers) as response:
                    annotations = []
                    if response.status == 200:
                        annotations = await response.json()

                # Extract useful information
                logs = []
                if check_data.get("output"):
                    output = check_data["output"]
                    if output.get("summary"):
                        logs.append(f"Summary: {output['summary']}")
                    if output.get("text"):
                        logs.append(f"Details: {output['text']}")

                for annotation in annotations:
                    message = annotation.get("message", "")
                    filename = annotation.get("path", "")
                    line = annotation.get("start_line", "")
                    logs.append(f"{filename}:{line} - {message}")

                return {
                    "success": True,
                    "logs": logs,
                    "check_name": check_data.get("name", ""),
                    "conclusion": check_data.get("conclusion", ""),
                    "annotations_count": len(annotations),
                }

        except Exception as e:
            logger.error(f"Error getting check logs for {check_run_id}: {e}")
            return {"error": str(e), "success": False}

    def _map_check_status(self, status: str, conclusion: str | None) -> CheckStatus:
        """Map GitHub check run status to our CheckStatus enum."""
        if status == "completed":
            if conclusion == "success":
                return CheckStatus.SUCCESS
            if conclusion == "failure":
                return CheckStatus.FAILURE
            if conclusion == "cancelled":
                return CheckStatus.CANCELLED
            return CheckStatus.ERROR
        if status in ["queued", "in_progress"]:
            return CheckStatus.PENDING
        return CheckStatus.ERROR

    def _map_status_check(self, state: str) -> CheckStatus:
        """Map GitHub status check state to our CheckStatus enum."""
        if state == "success":
            return CheckStatus.SUCCESS
        if state == "failure":
            return CheckStatus.FAILURE
        if state == "error":
            return CheckStatus.ERROR
        if state == "pending":
            return CheckStatus.PENDING
        return CheckStatus.ERROR

    def get_rate_limit_info(self) -> dict[str, Any]:
        """Get current rate limit information."""
        try:
            rate_limit = self.github.get_rate_limit()
            return {
                "core": {
                    "limit": rate_limit.core.limit,
                    "remaining": rate_limit.core.remaining,
                    "reset": rate_limit.core.reset.isoformat(),
                },
                "search": {
                    "limit": rate_limit.search.limit,
                    "remaining": rate_limit.search.remaining,
                    "reset": rate_limit.search.reset.isoformat(),
                },
            }
        except Exception as e:
            logger.error(f"Error getting rate limit info: {e}")
            return {"error": str(e)}

    async def health_check(self) -> dict[str, Any]:
        """Perform health check on GitHub API connection."""
        try:
            # Test API access with a simple call
            user = self.github.get_user()
            rate_limit = self.get_rate_limit_info()

            return {
                "status": "healthy",
                "authenticated_user": user.login,
                "rate_limit": rate_limit,
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
