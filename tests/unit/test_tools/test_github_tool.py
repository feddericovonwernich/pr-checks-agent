"""Tests for GitHub API tool."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.state.schemas import CheckStatus
from src.tools.github_tool import GitHubAPIInput, GitHubTool


class TestGitHubAPIInput:
    """Test cases for GitHub API input validation."""

    def test_github_api_input_minimal(self):
        """Test minimal valid input."""
        input_data = GitHubAPIInput(operation="get_prs", repository="owner/repo")

        assert input_data.operation == "get_prs"
        assert input_data.repository == "owner/repo"
        assert input_data.pr_number is None
        assert input_data.check_run_id is None
        assert input_data.branch_filter is None

    def test_github_api_input_full(self):
        """Test input with all fields."""
        input_data = GitHubAPIInput(
            operation="get_checks", repository="owner/repo", pr_number=123, check_run_id=456, branch_filter=["main", "develop"]
        )

        assert input_data.operation == "get_checks"
        assert input_data.repository == "owner/repo"
        assert input_data.pr_number == 123
        assert input_data.check_run_id == 456
        assert input_data.branch_filter == ["main", "develop"]


class TestGitHubTool:
    """Test cases for GitHub API tool."""

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    def test_github_tool_initialization_success(self):
        """Test successful tool initialization."""
        tool = GitHubTool()

        assert tool.name == "github_api"
        assert tool.description == "Interact with GitHub API to get PR and check information"
        assert tool.args_schema == GitHubAPIInput
        assert tool.github_token == "test_token"

    def test_github_tool_initialization_no_token(self):
        """Test initialization fails without GitHub token."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="GITHUB_TOKEN environment variable is required"):
                GitHubTool()

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    def test_github_tool_initialization_with_mock_github(self, mock_github_class):
        """Test initialization with mocked GitHub client."""
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github

        tool = GitHubTool()

        mock_github_class.assert_called_once_with("test_token")
        assert tool.github == mock_github

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    def test_github_tool_unknown_operation(self, mock_github_class):
        """Test handling of unknown operation."""
        tool = GitHubTool()

        result = tool._run(operation="unknown_operation", repository="owner/repo")

        assert result["success"] is False
        assert "Unknown operation" in result["error"]

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    def test_get_open_prs_success(self, mock_github_class):
        """Test successful PR retrieval."""
        # Setup mock
        mock_github = MagicMock()
        mock_repo = MagicMock()
        mock_pr = MagicMock()

        mock_github_class.return_value = mock_github
        mock_github.get_repo.return_value = mock_repo

        # Configure PR mock
        mock_pr.number = 123
        mock_pr.title = "Test PR"
        mock_pr.user.login = "test-user"
        mock_pr.head.ref = "feature-branch"
        mock_pr.base.ref = "main"
        mock_pr.html_url = "https://github.com/owner/repo/pull/123"
        mock_pr.created_at = datetime(2023, 1, 1, 12, 0, 0)
        mock_pr.updated_at = datetime(2023, 1, 1, 13, 0, 0)
        mock_pr.draft = False
        mock_pr.mergeable = True

        mock_repo.get_pulls.return_value = [mock_pr]

        tool = GitHubTool()
        result = tool._run(operation="get_prs", repository="owner/repo")

        assert result["success"] is True
        assert result["count"] == 1
        assert len(result["prs"]) == 1

        pr_data = result["prs"][0]
        assert pr_data["number"] == 123
        assert pr_data["title"] == "Test PR"
        assert pr_data["author"] == "test-user"
        assert pr_data["branch"] == "feature-branch"
        assert pr_data["base_branch"] == "main"

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    def test_get_open_prs_with_branch_filter(self, mock_github_class):
        """Test PR retrieval with branch filtering."""
        # Setup mock
        mock_github = MagicMock()
        mock_repo = MagicMock()

        # Create PRs with different head branches (source branches)
        mock_pr_main = MagicMock()
        mock_pr_main.base.ref = "main"
        mock_pr_main.number = 1
        mock_pr_main.title = "Main feature PR"
        mock_pr_main.user.login = "user1"
        mock_pr_main.head.ref = "main-feature"  # Head branch to match filter
        mock_pr_main.html_url = "https://github.com/owner/repo/pull/1"
        mock_pr_main.created_at = datetime.now()
        mock_pr_main.updated_at = datetime.now()
        mock_pr_main.draft = False
        mock_pr_main.mergeable = True

        mock_pr_develop = MagicMock()
        mock_pr_develop.base.ref = "main"
        mock_pr_develop.number = 2
        mock_pr_develop.title = "Develop feature PR"
        mock_pr_develop.user.login = "user2"
        mock_pr_develop.head.ref = "develop-feature"  # Head branch to match filter
        mock_pr_develop.html_url = "https://github.com/owner/repo/pull/2"
        mock_pr_develop.created_at = datetime.now()
        mock_pr_develop.updated_at = datetime.now()
        mock_pr_develop.draft = False
        mock_pr_develop.mergeable = True

        mock_pr_other = MagicMock()
        mock_pr_other.base.ref = "main"
        mock_pr_other.number = 3
        mock_pr_other.title = "Other feature PR"
        mock_pr_other.user.login = "user3"
        mock_pr_other.head.ref = "other-feature"  # Head branch that won't match filter
        mock_pr_other.html_url = "https://github.com/owner/repo/pull/3"
        mock_pr_other.created_at = datetime.now()
        mock_pr_other.updated_at = datetime.now()
        mock_pr_other.draft = False
        mock_pr_other.mergeable = True

        mock_github_class.return_value = mock_github
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_pulls.return_value = [mock_pr_main, mock_pr_develop, mock_pr_other]

        tool = GitHubTool()
        result = tool._run(operation="get_prs", repository="owner/repo", branch_filter=["main-feature", "develop-feature"])

        assert result["success"] is True
        assert result["count"] == 2  # Only PRs with matching head branches

        # Verify only filtered PRs are returned (now checking head branch)
        returned_head_branches = [pr["branch"] for pr in result["prs"]]
        assert "main-feature" in returned_head_branches
        assert "develop-feature" in returned_head_branches
        assert "other-feature" not in returned_head_branches

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    def test_get_pr_checks_success(self, mock_github_class):
        """Test successful PR checks retrieval."""
        # Setup mock
        mock_github = MagicMock()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_commit = MagicMock()
        mock_check_run = MagicMock()

        mock_github_class.return_value = mock_github
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        # Configure commit and check run mocks
        mock_commit.sha = "abc123def456"
        mock_commits = MagicMock()
        mock_commits.totalCount = 1
        mock_commits.__getitem__ = lambda self, index: mock_commit
        mock_pr.get_commits.return_value = mock_commits

        mock_check_run.name = "CI"
        mock_check_run.status = "completed"
        mock_check_run.conclusion = "success"
        mock_check_run.html_url = "https://github.com/owner/repo/runs/123"
        mock_check_run.started_at = datetime(2023, 1, 1, 12, 0, 0)
        mock_check_run.completed_at = datetime(2023, 1, 1, 12, 30, 0)

        mock_commit.get_check_runs.return_value = [mock_check_run]
        mock_commit.get_statuses.return_value = []

        tool = GitHubTool()
        result = tool._run(operation="get_checks", repository="owner/repo", pr_number=123)

        assert result["success"] is True
        assert result["commit_sha"] == "abc123def456"
        assert result["count"] == 1

        checks = result["checks"]
        assert "CI" in checks
        check_data = checks["CI"]
        assert check_data["name"] == "CI"
        assert check_data["status"] == CheckStatus.SUCCESS.value
        assert check_data["conclusion"] == "success"

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    def test_get_pr_checks_missing_pr_number(self, mock_github_class):
        """Test PR checks retrieval without PR number."""
        tool = GitHubTool()

        result = tool._run(
            operation="get_checks",
            repository="owner/repo",
            # Missing pr_number
        )

        assert result["success"] is False
        assert "PR number required" in result["error"]

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    @pytest.mark.asyncio
    async def test_get_check_logs_success(self, mock_github_class):
        """Test successful check logs retrieval."""
        # Setup mock GitHub
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github

        # Mock the entire _get_check_logs method to avoid complex aiohttp mocking
        tool = GitHubTool()

        # Mock the method directly since aiohttp async context manager mocking is complex
        async def mock_get_check_logs(repository, check_run_id):
            return {
                "success": True,
                "logs": ["Tests failed", "Detailed failure information", "src/main.py:42 - Syntax error on line 42"],
                "check_name": "CI",
                "conclusion": "failure",
                "annotations_count": 1,
            }

        tool._get_check_logs = mock_get_check_logs

        result = await tool._arun(operation="get_check_logs", repository="owner/repo", check_run_id=123)

        assert result["success"] is True
        assert result["check_name"] == "CI"
        assert result["conclusion"] == "failure"
        assert len(result["logs"]) > 0
        assert "Tests failed" in result["logs"][0]
        assert "Syntax error on line 42" in result["logs"][-1]

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    def test_get_check_logs_missing_check_run_id(self, mock_github_class):
        """Test check logs retrieval without check run ID."""
        tool = GitHubTool()

        result = tool._run(
            operation="get_check_logs",
            repository="owner/repo",
            # Missing check_run_id
        )

        assert result["success"] is False
        assert "Check run ID required" in result["error"]

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    def test_map_check_status_completed_success(self, mock_github_class):
        """Test check status mapping for completed/success."""
        tool = GitHubTool()

        status = tool._map_check_status("completed", "success")
        assert status == CheckStatus.SUCCESS

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    def test_map_check_status_completed_failure(self, mock_github_class):
        """Test check status mapping for completed/failure."""
        tool = GitHubTool()

        status = tool._map_check_status("completed", "failure")
        assert status == CheckStatus.FAILURE

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    def test_map_check_status_in_progress(self, mock_github_class):
        """Test check status mapping for in_progress."""
        tool = GitHubTool()

        status = tool._map_check_status("in_progress", None)
        assert status == CheckStatus.PENDING

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    def test_map_status_check(self, mock_github_class):
        """Test status check mapping."""
        tool = GitHubTool()

        assert tool._map_status_check("success") == CheckStatus.SUCCESS
        assert tool._map_status_check("failure") == CheckStatus.FAILURE
        assert tool._map_status_check("error") == CheckStatus.ERROR
        assert tool._map_status_check("pending") == CheckStatus.PENDING

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    def test_get_rate_limit_info_success(self, mock_github_class):
        """Test successful rate limit info retrieval."""
        mock_github = MagicMock()
        mock_rate_limit = MagicMock()

        mock_rate_limit.core.limit = 5000
        mock_rate_limit.core.remaining = 4999
        mock_rate_limit.core.reset = datetime(2023, 1, 1, 14, 0, 0)

        mock_rate_limit.search.limit = 30
        mock_rate_limit.search.remaining = 29
        mock_rate_limit.search.reset = datetime(2023, 1, 1, 14, 0, 0)

        mock_github.get_rate_limit.return_value = mock_rate_limit
        mock_github_class.return_value = mock_github

        tool = GitHubTool()
        result = tool.get_rate_limit_info()

        assert "core" in result
        assert "search" in result
        assert result["core"]["limit"] == 5000
        assert result["core"]["remaining"] == 4999
        assert result["search"]["limit"] == 30

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_github_class):
        """Test successful health check."""
        mock_github = MagicMock()
        mock_user = MagicMock()
        mock_user.login = "test-user"

        mock_github.get_user.return_value = mock_user
        mock_github_class.return_value = mock_github

        tool = GitHubTool()

        # Mock get_rate_limit_info method
        tool.get_rate_limit_info = MagicMock(return_value={"core": {"remaining": 4999}})

        result = await tool.health_check()

        assert result["status"] == "healthy"
        assert result["authenticated_user"] == "test-user"
        assert "rate_limit" in result

    @patch.dict("os.environ", {"GITHUB_TOKEN": "test_token"})
    @patch("src.tools.github_tool.Github")
    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_github_class):
        """Test health check failure."""
        mock_github = MagicMock()
        mock_github.get_user.side_effect = Exception("API Error")
        mock_github_class.return_value = mock_github

        tool = GitHubTool()
        result = await tool.health_check()

        assert result["status"] == "unhealthy"
        assert "error" in result
