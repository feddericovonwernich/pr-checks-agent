"""Tests for repository scanner node"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.nodes.scanner import repository_scanner_node, should_continue_scanning
from src.state.schemas import RepositoryConfig


class TestRepositoryScannerNode:
    """Test RepositoryScanner node functionality."""

    @pytest.fixture
    def base_state(self):
        """Create base monitor state for testing."""
        config = RepositoryConfig(
            owner="test-org",
            repo="test-repo",
            branch_filter=["main", "develop"],
            check_types=["ci", "tests"],
        )

        return {
            "repository": "test-org/test-repo",
            "config": config,
            "active_prs": {},
            "last_poll_time": None,
            "polling_interval": 300,
            "max_concurrent": 10,
            "workflow_semaphore": None,
            "consecutive_errors": 0,
            "last_error": None,
            "total_prs_processed": 0,
            "total_fixes_attempted": 0,
            "total_fixes_successful": 0,
            "total_escalations": 0,
        }

    @pytest.fixture
    def sample_pr_data(self):
        """Sample PR data for testing."""
        return {
            "number": 123,
            "title": "Add new feature",
            "author": "developer",
            "branch": "feature-branch",
            "base_branch": "main",
            "url": "https://github.com/test-org/test-repo/pull/123",
            "created_at": "2024-01-01T12:00:00Z",
            "updated_at": "2024-01-01T13:00:00Z",
            "draft": False,
            "mergeable": True,
        }

    @patch("src.nodes.scanner.GitHubTool")
    @pytest.mark.asyncio
    async def test_repository_scanner_node_success_new_pr(self, mock_github_tool, base_state, sample_pr_data):
        """Test successful repository scan with new PR."""
        # Setup mock
        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.return_value = {"success": True, "prs": [sample_pr_data]}

        result = await repository_scanner_node(base_state)

        # Verify GitHub tool was called correctly
        mock_tool_instance._arun.assert_called_once_with(
            operation="get_prs", repository="test-org/test-repo", branch_filter=["main", "develop"]
        )

        # Verify result structure
        assert "active_prs" in result
        assert "last_poll_time" in result
        assert "scan_results" in result
        assert result["consecutive_errors"] == 0
        assert result["last_error"] is None

        # Verify new PR was added
        assert 123 in result["active_prs"]
        new_pr_state = result["active_prs"][123]
        assert new_pr_state["pr_number"] == 123
        assert new_pr_state["repository"] == "test-org/test-repo"
        assert new_pr_state["workflow_step"] == "discovered"
        assert new_pr_state["pr_info"] == sample_pr_data

        # Verify scan results
        scan_results = result["scan_results"]
        assert scan_results["new_prs"] == [123]
        assert scan_results["updated_prs"] == []
        assert scan_results["closed_prs"] == []
        assert scan_results["total_active"] == 1

        # Verify PR processing count increased
        assert result["total_prs_processed"] == 1

    @patch("src.nodes.scanner.GitHubTool")
    @pytest.mark.asyncio
    async def test_repository_scanner_node_updated_pr(self, mock_github_tool, base_state, sample_pr_data):
        """Test repository scan with updated existing PR."""
        # Setup existing PR in state
        existing_pr_info = sample_pr_data.copy()
        existing_pr_info["updated_at"] = "2024-01-01T12:30:00Z"

        base_state["active_prs"] = {
            123: {
                "pr_number": 123,
                "repository": "test-org/test-repo",
                "pr_info": existing_pr_info,
                "checks": {},
                "failed_checks": [],
                "fix_attempts": {},
                "current_fix_attempt": None,
                "escalations": [],
                "escalation_status": "none",
                "last_updated": datetime(2024, 1, 1, 12, 30, 0),
                "workflow_step": "analyzed",
                "retry_count": 0,
                "error_message": None,
            }
        }

        # Mock updated PR data
        updated_pr_data = sample_pr_data.copy()
        updated_pr_data["updated_at"] = "2024-01-01T14:00:00Z"

        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.return_value = {"success": True, "prs": [updated_pr_data]}

        result = await repository_scanner_node(base_state)

        # Verify PR was marked as updated
        scan_results = result["scan_results"]
        assert scan_results["new_prs"] == []
        assert scan_results["updated_prs"] == [123]
        assert scan_results["closed_prs"] == []

        # Verify PR state was preserved but PR info updated
        updated_pr_state = result["active_prs"][123]
        assert updated_pr_state["workflow_step"] == "analyzed"  # Preserved
        assert updated_pr_state["pr_info"]["updated_at"] == "2024-01-01T14:00:00Z"  # Updated

        # Verify no new PRs counted
        assert result["total_prs_processed"] == 0

    @patch("src.nodes.scanner.GitHubTool")
    @pytest.mark.asyncio
    async def test_repository_scanner_node_closed_pr(self, mock_github_tool, base_state, sample_pr_data):
        """Test repository scan with closed PR."""
        # Setup existing PR in state
        base_state["active_prs"] = {
            123: {
                "pr_number": 123,
                "repository": "test-org/test-repo",
                "pr_info": sample_pr_data,
                "workflow_step": "fixing",
            }
        }

        # Mock response with no PRs (PR was closed)
        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.return_value = {"success": True, "prs": []}

        result = await repository_scanner_node(base_state)

        # Verify PR was detected as closed
        scan_results = result["scan_results"]
        assert scan_results["new_prs"] == []
        assert scan_results["updated_prs"] == []
        assert scan_results["closed_prs"] == [123]
        assert scan_results["total_active"] == 0

        # Verify PR was removed from active PRs
        assert 123 not in result["active_prs"]

    @patch("src.nodes.scanner.GitHubTool")
    @pytest.mark.asyncio
    async def test_repository_scanner_node_github_api_failure(self, mock_github_tool, base_state):
        """Test repository scan when GitHub API fails."""
        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.return_value = {"success": False, "error": "API rate limit exceeded"}

        result = await repository_scanner_node(base_state)

        # Verify error handling
        assert result["consecutive_errors"] == 1
        assert result["last_error"] == "API rate limit exceeded"
        assert "last_poll_time" in result

        # Verify state preservation
        assert result["active_prs"] == {}
        assert result["total_prs_processed"] == 0

    @patch("src.nodes.scanner.GitHubTool")
    @pytest.mark.asyncio
    async def test_repository_scanner_node_unexpected_exception(self, mock_github_tool, base_state):
        """Test repository scan with unexpected exception."""
        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.side_effect = Exception("Network timeout")

        result = await repository_scanner_node(base_state)

        # Verify exception handling
        assert result["consecutive_errors"] == 1
        assert result["last_error"] == "Network timeout"
        assert "last_poll_time" in result

    @patch("src.nodes.scanner.GitHubTool")
    @pytest.mark.asyncio
    async def test_repository_scanner_node_multiple_prs(self, mock_github_tool, base_state):
        """Test repository scan with multiple PRs."""
        pr_data_1 = {
            "number": 123,
            "title": "Feature A",
            "author": "dev1",
            "branch": "feature-a",
            "base_branch": "main",
            "url": "https://github.com/test-org/test-repo/pull/123",
            "created_at": "2024-01-01T12:00:00Z",
            "updated_at": "2024-01-01T13:00:00Z",
            "draft": False,
            "mergeable": True,
        }

        pr_data_2 = {
            "number": 456,
            "title": "Feature B",
            "author": "dev2",
            "branch": "feature-b",
            "base_branch": "develop",
            "url": "https://github.com/test-org/test-repo/pull/456",
            "created_at": "2024-01-01T14:00:00Z",
            "updated_at": "2024-01-01T15:00:00Z",
            "draft": True,
            "mergeable": False,
        }

        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.return_value = {"success": True, "prs": [pr_data_1, pr_data_2]}

        result = await repository_scanner_node(base_state)

        # Verify both PRs were processed
        assert len(result["active_prs"]) == 2
        assert 123 in result["active_prs"]
        assert 456 in result["active_prs"]

        # Verify scan results
        scan_results = result["scan_results"]
        assert set(scan_results["new_prs"]) == {123, 456}
        assert scan_results["total_active"] == 2

        # Verify processing count
        assert result["total_prs_processed"] == 2

    @patch("src.nodes.scanner.GitHubTool")
    @pytest.mark.asyncio
    async def test_repository_scanner_node_error_recovery(self, mock_github_tool, base_state):
        """Test error recovery after consecutive errors."""
        # Start with some consecutive errors
        base_state["consecutive_errors"] = 3
        base_state["last_error"] = "Previous error"

        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.return_value = {"success": True, "prs": []}

        result = await repository_scanner_node(base_state)

        # Verify error recovery
        assert result["consecutive_errors"] == 0
        assert result["last_error"] is None


class TestShouldContinueScanning:
    """Test edge function for determining next steps after scanning."""

    def test_should_continue_scanning_with_new_prs(self):
        """Test continue scanning decision with new PRs."""
        state = {"consecutive_errors": 0, "scan_results": {"new_prs": [123, 456], "updated_prs": [], "closed_prs": []}}

        result = should_continue_scanning(state)
        assert result == "monitor_checks"

    def test_should_continue_scanning_with_updated_prs(self):
        """Test continue scanning decision with updated PRs."""
        state = {"consecutive_errors": 0, "scan_results": {"new_prs": [], "updated_prs": [123], "closed_prs": []}}

        result = should_continue_scanning(state)
        assert result == "monitor_checks"

    def test_should_continue_scanning_with_both(self):
        """Test continue scanning decision with both new and updated PRs."""
        state = {"consecutive_errors": 1, "scan_results": {"new_prs": [123], "updated_prs": [456], "closed_prs": [789]}}

        result = should_continue_scanning(state)
        assert result == "monitor_checks"

    def test_should_continue_scanning_no_changes(self):
        """Test continue scanning decision with no changes."""
        state = {
            "consecutive_errors": 0,
            "scan_results": {
                "new_prs": [],
                "updated_prs": [],
                "closed_prs": [789],  # Only closed PRs, no active changes
            },
        }

        result = should_continue_scanning(state)
        assert result == "wait_for_next_poll"

    def test_should_continue_scanning_too_many_errors(self):
        """Test continue scanning decision with too many consecutive errors."""
        state = {
            "consecutive_errors": 5,
            "scan_results": {
                "new_prs": [123],  # Even with changes, should handle errors first
                "updated_prs": [],
                "closed_prs": [],
            },
        }

        result = should_continue_scanning(state)
        assert result == "handle_errors"

    def test_should_continue_scanning_exactly_error_threshold(self):
        """Test continue scanning decision at error threshold."""
        state = {"consecutive_errors": 5, "scan_results": {"new_prs": [], "updated_prs": [], "closed_prs": []}}

        result = should_continue_scanning(state)
        assert result == "handle_errors"

    def test_should_continue_scanning_just_below_threshold(self):
        """Test continue scanning decision just below error threshold."""
        state = {"consecutive_errors": 4, "scan_results": {"new_prs": [], "updated_prs": [], "closed_prs": []}}

        result = should_continue_scanning(state)
        assert result == "wait_for_next_poll"

    def test_should_continue_scanning_missing_scan_results(self):
        """Test continue scanning decision with missing scan results."""
        state = {
            "consecutive_errors": 0,
            # No scan_results key
        }

        result = should_continue_scanning(state)
        assert result == "wait_for_next_poll"

    def test_should_continue_scanning_missing_consecutive_errors(self):
        """Test continue scanning decision with missing consecutive errors."""
        state = {
            # No consecutive_errors key
            "scan_results": {"new_prs": [], "updated_prs": [], "closed_prs": []}
        }

        result = should_continue_scanning(state)
        assert result == "wait_for_next_poll"


class TestScannerIntegration:
    """Integration-style tests for scanner node."""

    @pytest.fixture
    def complex_state(self):
        """Complex state with existing PRs and history."""
        config = RepositoryConfig(
            owner="test-org",
            repo="test-repo",
            branch_filter=["main", "develop", "staging"],
        )

        return {
            "repository": "test-org/test-repo",
            "config": config,
            "active_prs": {
                100: {
                    "pr_number": 100,
                    "repository": "test-org/test-repo",
                    "pr_info": {
                        "number": 100,
                        "title": "Old PR",
                        "updated_at": "2024-01-01T10:00:00Z",
                    },
                    "workflow_step": "fixing",
                    "fix_attempts": {"CI": []},
                },
                200: {
                    "pr_number": 200,
                    "repository": "test-org/test-repo",
                    "pr_info": {
                        "number": 200,
                        "title": "Another PR",
                        "updated_at": "2024-01-01T11:00:00Z",
                    },
                    "workflow_step": "escalated",
                },
            },
            "last_poll_time": datetime(2024, 1, 1, 12, 0, 0),
            "consecutive_errors": 0,
            "total_prs_processed": 10,
        }

    @patch("src.nodes.scanner.GitHubTool")
    @pytest.mark.asyncio
    async def test_complex_scanning_scenario(self, mock_github_tool, complex_state):
        """Test complex scanning scenario with mixed PR states."""
        # Mock data: PR 100 updated, PR 200 closed, PR 300 new
        current_prs = [
            {
                "number": 100,
                "title": "Old PR - Updated",
                "updated_at": "2024-01-01T14:00:00Z",  # Updated
            },
            {
                "number": 300,
                "title": "Brand New PR",
                "updated_at": "2024-01-01T13:00:00Z",
                "author": "new-contributor",
                "branch": "feature-new",
                "base_branch": "main",
                "url": "https://github.com/test-org/test-repo/pull/300",
                "created_at": "2024-01-01T13:00:00Z",
                "draft": False,
                "mergeable": True,
            },
            # PR 200 is missing (closed)
        ]

        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.return_value = {"success": True, "prs": current_prs}

        result = await repository_scanner_node(complex_state)

        # Verify scan results
        scan_results = result["scan_results"]
        assert scan_results["new_prs"] == [300]
        assert scan_results["updated_prs"] == [100]
        assert scan_results["closed_prs"] == [200]
        assert scan_results["total_active"] == 2

        # Verify PR 100 state preserved but info updated
        assert 100 in result["active_prs"]
        assert result["active_prs"][100]["workflow_step"] == "fixing"  # Preserved
        assert result["active_prs"][100]["pr_info"]["title"] == "Old PR - Updated"  # Updated

        # Verify PR 200 removed
        assert 200 not in result["active_prs"]

        # Verify PR 300 added with correct initial state
        assert 300 in result["active_prs"]
        new_pr = result["active_prs"][300]
        assert new_pr["workflow_step"] == "discovered"
        assert new_pr["pr_info"]["title"] == "Brand New PR"

        # Verify processing count updated
        assert result["total_prs_processed"] == 11  # 10 + 1 new PR
