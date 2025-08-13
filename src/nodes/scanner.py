"""Repository Scanner Node for PR Check Agent
Polls GitHub for repository changes and PR updates
"""

from datetime import datetime
from typing import Any

from loguru import logger

from state.schemas import MonitorState
from tools.github_tool import GitHubTool


async def repository_scanner_node(state: MonitorState) -> dict[str, Any]:
    """LangGraph node that scans a repository for PR changes.

    This node:
    1. Polls GitHub API for open PRs
    2. Compares with current state
    3. Identifies new, updated, or closed PRs
    4. Updates the monitoring state
    """
    repository = state["repository"]
    config = state["config"]
    logger.info(f"Scanning repository: {repository}")

    # Initialize GitHub tool
    github_tool = GitHubTool()

    try:
        # Get current open PRs
        result = await github_tool._arun(operation="get_prs", repository=repository, branch_filter=config.branch_filter)

        if not result.get("success", False):
            error_msg = result.get("error", "Unknown GitHub API error")
            logger.error(f"Failed to get PRs for {repository}: {error_msg}")
            return {
                **state,
                "consecutive_errors": state.get("consecutive_errors", 0) + 1,
                "last_error": error_msg,
                "last_poll_time": datetime.now(),
            }

        current_prs = {pr["number"]: pr for pr in result.get("prs", [])}
        existing_prs = state.get("active_prs", {})

        # Find new PRs
        new_pr_numbers = set(current_prs.keys()) - set(existing_prs.keys())
        updated_prs = []
        closed_prs = []

        # Find updated PRs
        for pr_num in current_prs:
            if pr_num in existing_prs:
                current_updated = current_prs[pr_num]["updated_at"]
                existing_updated = existing_prs[pr_num].get("pr_info", {}).get("updated_at")

                if current_updated != existing_updated:
                    updated_prs.append(pr_num)

        # Find closed PRs
        closed_prs = [pr_num for pr_num in existing_prs if pr_num not in current_prs]

        logger.info(
            f"Repository scan results: {len(new_pr_numbers)} new, {len(updated_prs)} updated, {len(closed_prs)} closed PRs"
        )

        # Update active PRs state
        updated_active_prs = {}

        # Keep existing PRs that are still open and add updated info
        for pr_num, current_pr in current_prs.items():
            if pr_num in existing_prs:
                # Preserve existing PR state but update PR info
                updated_active_prs[pr_num] = {**existing_prs[pr_num], "pr_info": current_pr, "last_updated": datetime.now()}
            else:
                # New PR - create initial state
                updated_active_prs[pr_num] = {
                    "pr_number": pr_num,
                    "repository": repository,
                    "pr_info": current_pr,
                    "checks": {},
                    "failed_checks": [],
                    "fix_attempts": {},
                    "current_fix_attempt": None,
                    "escalations": [],
                    "escalation_status": "none",
                    "last_updated": datetime.now(),
                    "workflow_step": "discovered",
                    "retry_count": 0,
                    "error_message": None,
                }

        # Return updated state
        return {
            **state,
            "active_prs": updated_active_prs,
            "last_poll_time": datetime.now(),
            "consecutive_errors": 0,  # Reset error count on success
            "last_error": None,
            "total_prs_processed": state.get("total_prs_processed", 0) + len(new_pr_numbers),
            # Add metadata about changes
            "scan_results": {
                "new_prs": list(new_pr_numbers),
                "updated_prs": updated_prs,
                "closed_prs": closed_prs,
                "total_active": len(updated_active_prs),
            },
        }

    except Exception as e:
        logger.error(f"Unexpected error in repository scanner: {e}")
        return {
            **state,
            "consecutive_errors": state.get("consecutive_errors", 0) + 1,
            "last_error": str(e),
            "last_poll_time": datetime.now(),
        }


def should_continue_scanning(state: MonitorState) -> str:
    """LangGraph edge function to determine next step after scanning."""
    scan_results = state.get("scan_results", {})
    consecutive_errors = state.get("consecutive_errors", 0)

    # If too many consecutive errors, go to error handling
    if consecutive_errors >= 5:
        logger.warning(f"Too many consecutive errors ({consecutive_errors}), entering error handling")
        return "handle_errors"

    # If we have new or updated PRs, process them
    new_prs = scan_results.get("new_prs", [])
    updated_prs = scan_results.get("updated_prs", [])

    if new_prs or updated_prs:
        logger.info("Found changes, proceeding to check monitoring")
        return "monitor_checks"

    # Otherwise, wait for next polling cycle
    return "wait_for_next_poll"
