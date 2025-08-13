"""Tests for check monitor node"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.nodes.monitor import (
    check_monitor_node,
    prioritize_failures,
    should_analyze_failures,
)
from src.state.schemas import CheckStatus, RepositoryConfig


class TestCheckMonitorNode:
    """Test CheckMonitor node functionality."""

    @pytest.fixture
    def base_state(self):
        """Create base monitor state for testing."""
        config = RepositoryConfig(
            owner="test-org",
            repo="test-repo",
            priorities={
                "check_types": {"security": 1, "tests": 2, "ci": 3},
                "branch_priority": {"main": 0, "develop": 5}
            }
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
    def sample_pr_state(self):
        """Sample PR state for testing."""
        return {
            "pr_number": 123,
            "repository": "test-org/test-repo",
            "pr_info": {
                "number": 123,
                "title": "Test PR",
                "author": "developer",
                "branch": "feature-branch",
                "base_branch": "main",
                "url": "https://github.com/test-org/test-repo/pull/123",
            },
            "checks": {},
            "failed_checks": [],
            "fix_attempts": {},
            "current_fix_attempt": None,
            "escalations": [],
            "escalation_status": "none",
            "last_updated": datetime(2024, 1, 1, 12, 0, 0),
            "workflow_step": "discovered",
            "retry_count": 0,
            "error_message": None,
        }

    @pytest.mark.asyncio
    async def test_check_monitor_node_no_active_prs(self, base_state):
        """Test check monitor when there are no active PRs."""
        result = await check_monitor_node(base_state)

        # Should return state unchanged
        assert result == base_state

    @patch("src.nodes.monitor.GitHubTool")
    @pytest.mark.asyncio
    async def test_check_monitor_node_successful_monitoring(self, mock_github_tool, base_state, sample_pr_state):
        """Test successful check monitoring with no failures."""
        base_state["active_prs"] = {123: sample_pr_state}

        # Mock successful check response
        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.return_value = {
            "success": True,
            "checks": {
                "CI": {
                    "status": CheckStatus.SUCCESS.value,
                    "conclusion": "success",
                    "details_url": "https://github.com/test-org/test-repo/runs/123",
                },
                "Tests": {
                    "status": CheckStatus.SUCCESS.value,
                    "conclusion": "success",
                    "details_url": "https://github.com/test-org/test-repo/runs/124",
                }
            }
        }

        result = await check_monitor_node(base_state)

        # Verify GitHub tool was called
        mock_tool_instance._arun.assert_called_once_with(
            operation="get_checks",
            repository="test-org/test-repo",
            pr_number=123
        )

        # Verify result
        assert "active_prs" in result
        assert "newly_failed_checks" in result
        assert "last_poll_time" in result
        assert "monitoring_stats" in result

        # Verify PR state was updated
        updated_pr = result["active_prs"][123]
        assert updated_pr["workflow_step"] == "checks_monitored"
        assert len(updated_pr["checks"]) == 2
        assert updated_pr["failed_checks"] == []

        # Verify no newly failed checks
        assert result["newly_failed_checks"] == []

        # Verify monitoring stats
        stats = result["monitoring_stats"]
        assert stats["total_checks_monitored"] == 2
        assert stats["total_failed_checks"] == 0
        assert stats["newly_failed_count"] == 0

    @patch("src.nodes.monitor.GitHubTool")
    @pytest.mark.asyncio
    async def test_check_monitor_node_newly_failed_check(self, mock_github_tool, base_state, sample_pr_state):
        """Test check monitoring with newly failed check."""
        # Setup previous state with successful check
        sample_pr_state["checks"] = {
            "CI": {
                "status": CheckStatus.SUCCESS.value,
                "conclusion": "success",
            }
        }
        base_state["active_prs"] = {123: sample_pr_state}

        # Mock failed check response
        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.return_value = {
            "success": True,
            "checks": {
                "CI": {
                    "status": CheckStatus.FAILURE.value,
                    "conclusion": "failure",
                    "details_url": "https://github.com/test-org/test-repo/runs/123",
                    "failure_logs": "Build failed: syntax error",
                    "error_message": "SyntaxError: unexpected token",
                }
            }
        }

        result = await check_monitor_node(base_state)

        # Verify newly failed check was detected
        newly_failed = result["newly_failed_checks"]
        assert len(newly_failed) == 1
        assert newly_failed[0]["pr_number"] == 123
        assert newly_failed[0]["check_name"] == "CI"

        # Verify PR state updated for analysis
        updated_pr = result["active_prs"][123]
        assert updated_pr["workflow_step"] == "needs_analysis"
        assert "CI" in updated_pr["failed_checks"]

        # Verify monitoring stats
        stats = result["monitoring_stats"]
        assert stats["total_failed_checks"] == 1
        assert stats["newly_failed_count"] == 1

    @patch("src.nodes.monitor.GitHubTool")
    @pytest.mark.asyncio
    async def test_check_monitor_node_still_failed_check(self, mock_github_tool, base_state, sample_pr_state):
        """Test check monitoring with check that was already failed."""
        # Setup previous state with already failed check
        sample_pr_state["checks"] = {
            "CI": {
                "status": CheckStatus.FAILURE.value,
                "conclusion": "failure",
            }
        }
        sample_pr_state["failed_checks"] = ["CI"]
        base_state["active_prs"] = {123: sample_pr_state}

        # Mock same failed check response
        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.return_value = {
            "success": True,
            "checks": {
                "CI": {
                    "status": CheckStatus.FAILURE.value,
                    "conclusion": "failure",
                    "details_url": "https://github.com/test-org/test-repo/runs/123",
                }
            }
        }

        result = await check_monitor_node(base_state)

        # Verify no newly failed checks (was already failed)
        assert result["newly_failed_checks"] == []

        # Verify PR still marked as needing analysis
        updated_pr = result["active_prs"][123]
        assert updated_pr["workflow_step"] == "needs_analysis"

    @patch("src.nodes.monitor.GitHubTool")
    @pytest.mark.asyncio
    async def test_check_monitor_node_github_api_failure(self, mock_github_tool, base_state, sample_pr_state):
        """Test check monitoring when GitHub API fails."""
        base_state["active_prs"] = {123: sample_pr_state}

        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.return_value = {
            "success": False,
            "error": "API rate limit exceeded"
        }

        result = await check_monitor_node(base_state)

        # Verify original PR state is preserved on API failure
        assert result["active_prs"][123] == sample_pr_state
        assert result["newly_failed_checks"] == []

    @patch("src.nodes.monitor.GitHubTool")
    @pytest.mark.asyncio
    async def test_check_monitor_node_unexpected_exception(self, mock_github_tool, base_state, sample_pr_state):
        """Test check monitoring with unexpected exception."""
        base_state["active_prs"] = {123: sample_pr_state}

        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.side_effect = Exception("Network timeout")

        result = await check_monitor_node(base_state)

        # Verify original PR state is preserved on exception
        assert result["active_prs"][123] == sample_pr_state

    @patch("src.nodes.monitor.GitHubTool")
    @pytest.mark.asyncio
    async def test_check_monitor_node_multiple_prs(self, mock_github_tool, base_state):
        """Test check monitoring with multiple PRs."""
        pr_state_1 = {
            "pr_number": 123,
            "repository": "test-org/test-repo",
            "checks": {},
            "failed_checks": [],
            "workflow_step": "discovered",
        }
        pr_state_2 = {
            "pr_number": 456,
            "repository": "test-org/test-repo",
            "checks": {},
            "failed_checks": [],
            "workflow_step": "discovered",
        }

        base_state["active_prs"] = {123: pr_state_1, 456: pr_state_2}

        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance

        # Different responses for each PR
        mock_responses = [
            {
                "success": True,
                "checks": {"CI": {"status": CheckStatus.SUCCESS.value}}
            },
            {
                "success": True,
                "checks": {"Tests": {"status": CheckStatus.FAILURE.value}}
            }
        ]
        mock_tool_instance._arun.side_effect = mock_responses

        result = await check_monitor_node(base_state)

        # Verify both PRs were monitored
        assert mock_tool_instance._arun.call_count == 2

        # Verify PR states
        assert len(result["active_prs"]) == 2
        assert result["active_prs"][123]["workflow_step"] == "checks_monitored"
        assert result["active_prs"][456]["workflow_step"] == "needs_analysis"

        # Verify newly failed checks from PR 456
        assert len(result["newly_failed_checks"]) == 1
        assert result["newly_failed_checks"][0]["pr_number"] == 456


class TestShouldAnalyzeFailures:
    """Test edge function for determining if failures should be analyzed."""

    def test_should_analyze_failures_with_newly_failed(self):
        """Test analyze decision with newly failed checks."""
        state = {
            "newly_failed_checks": [
                {"pr_number": 123, "check_name": "CI"},
                {"pr_number": 456, "check_name": "Tests"},
            ]
        }

        result = should_analyze_failures(state)
        assert result == "analyze_failures"

    def test_should_analyze_failures_with_needs_analysis(self):
        """Test analyze decision with PRs needing analysis."""
        state = {
            "newly_failed_checks": [],
            "active_prs": {
                123: {"workflow_step": "needs_analysis"},
                456: {"workflow_step": "analyzed"},
                789: {"workflow_step": "needs_analysis"},
            }
        }

        result = should_analyze_failures(state)
        assert result == "analyze_failures"

    def test_should_analyze_failures_no_work_needed(self):
        """Test analyze decision when no work is needed."""
        state = {
            "newly_failed_checks": [],
            "active_prs": {
                123: {"workflow_step": "analyzed"},
                456: {"workflow_step": "fixing"},
                789: {"workflow_step": "escalated"},
            }
        }

        result = should_analyze_failures(state)
        assert result == "wait_for_next_poll"

    def test_should_analyze_failures_empty_state(self):
        """Test analyze decision with empty state."""
        state = {
            "newly_failed_checks": [],
            "active_prs": {}
        }

        result = should_analyze_failures(state)
        assert result == "wait_for_next_poll"

    def test_should_analyze_failures_missing_data(self):
        """Test analyze decision with missing data."""
        state = {}

        result = should_analyze_failures(state)
        assert result == "wait_for_next_poll"


class TestPrioritizeFailures:
    """Test failure prioritization helper node."""

    @pytest.fixture
    def state_with_config(self):
        """State with priority configuration."""
        config = RepositoryConfig(
            owner="test-org",
            repo="test-repo",
            priorities={
                "check_types": {
                    "security": 1,
                    "tests": 2,
                    "ci": 3,
                    "lint": 4,
                },
                "branch_priority": {
                    "main": 0,
                    "develop": 5,
                    "feature": 10,
                }
            }
        )

        return {
            "config": config,
            "newly_failed_checks": [
                {
                    "pr_number": 123,
                    "check_name": "Security Scan",
                    "check_info": {"status": "failure"}
                },
                {
                    "pr_number": 456,
                    "check_name": "CI Build",
                    "check_info": {"status": "failure"}
                },
                {
                    "pr_number": 789,
                    "check_name": "Unit Tests",
                    "check_info": {"status": "failure"}
                }
            ],
            "active_prs": {
                123: {
                    "pr_info": {"base_branch": "main"}
                },
                456: {
                    "pr_info": {"base_branch": "develop"}
                },
                789: {
                    "pr_info": {"base_branch": "feature"}
                }
            }
        }

    @pytest.mark.asyncio
    async def test_prioritize_failures_with_priorities(self, state_with_config):
        """Test failure prioritization with configured priorities."""
        result = await prioritize_failures(state_with_config)

        # Verify prioritized_failures were added
        assert "prioritized_failures" in result
        prioritized = result["prioritized_failures"]
        assert len(prioritized) == 3

        # Verify sorting by priority (security should be first, higher priority)
        assert prioritized[0]["check_name"] == "Security Scan"
        assert prioritized[0]["pr_number"] == 123
        assert prioritized[0]["priority_score"] == 1.123  # 1 + 0 (main branch) + 0.123

        # CI Build on develop should be next (3 + 5 + 0.456 = 8.456)
        assert prioritized[1]["check_name"] == "CI Build"
        assert prioritized[1]["pr_number"] == 456

        # Unit Tests on feature should be last (2 + 10 + 0.789 = 12.789)
        assert prioritized[2]["check_name"] == "Unit Tests"
        assert prioritized[2]["pr_number"] == 789

    @pytest.mark.asyncio
    async def test_prioritize_failures_no_newly_failed(self):
        """Test prioritization with no newly failed checks."""
        state = {
            "config": RepositoryConfig(owner="test", repo="test"),
            "newly_failed_checks": []
        }

        result = await prioritize_failures(state)
        # Should return state unchanged
        assert result == state

    @pytest.mark.asyncio
    async def test_prioritize_failures_default_scoring(self):
        """Test prioritization with default scoring."""
        config = RepositoryConfig(
            owner="test-org",
            repo="test-repo",
            priorities={}  # No specific priorities
        )

        state = {
            "config": config,
            "newly_failed_checks": [
                {
                    "pr_number": 100,
                    "check_name": "Unknown Check",
                    "check_info": {"status": "failure"}
                },
                {
                    "pr_number": 200,
                    "check_name": "Another Check",
                    "check_info": {"status": "failure"}
                }
            ],
            "active_prs": {
                100: {"pr_info": {"base_branch": "unknown"}},
                200: {"pr_info": {"base_branch": "unknown"}}
            }
        }

        result = await prioritize_failures(state)

        prioritized = result["prioritized_failures"]
        # Should be sorted by PR number (lower first) since all have default score
        assert prioritized[0]["pr_number"] == 100
        assert prioritized[1]["pr_number"] == 200

    @pytest.mark.asyncio
    async def test_prioritize_failures_partial_priorities(self):
        """Test prioritization with partial priority configuration."""
        config = RepositoryConfig(
            owner="test-org",
            repo="test-repo",
            priorities={
                "check_types": {"security": 1},  # Only one type configured
                # No branch priorities
            }
        )

        state = {
            "config": config,
            "newly_failed_checks": [
                {
                    "pr_number": 123,
                    "check_name": "Security Check",  # Should get priority 1
                    "check_info": {"status": "failure"}
                },
                {
                    "pr_number": 456,
                    "check_name": "Regular Check",  # Should get default priority 100
                    "check_info": {"status": "failure"}
                }
            ],
            "active_prs": {
                123: {"pr_info": {"base_branch": "main"}},
                456: {"pr_info": {"base_branch": "main"}}
            }
        }

        result = await prioritize_failures(state)

        prioritized = result["prioritized_failures"]
        # Security check should be first
        assert prioritized[0]["check_name"] == "Security Check"
        assert prioritized[0]["priority_score"] == 1.123

        # Regular check should be second with default score
        assert prioritized[1]["check_name"] == "Regular Check"
        assert prioritized[1]["priority_score"] == 100.456


class TestMonitorIntegration:
    """Integration tests for monitor node."""

    @patch("src.nodes.monitor.GitHubTool")
    @pytest.mark.asyncio
    async def test_full_monitoring_workflow(self, mock_github_tool):
        """Test complete monitoring workflow from scanning to prioritization."""
        # Setup complex state
        config = RepositoryConfig(
            owner="test-org",
            repo="test-repo",
            priorities={
                "check_types": {"security": 1, "ci": 3},
                "branch_priority": {"main": 0}
            }
        )

        state = {
            "repository": "test-org/test-repo",
            "config": config,
            "active_prs": {
                123: {
                    "pr_number": 123,
                    "repository": "test-org/test-repo",
                    "pr_info": {"base_branch": "main"},
                    "checks": {
                        "CI": {"status": CheckStatus.SUCCESS.value}  # Was passing
                    },
                    "failed_checks": [],
                    "workflow_step": "discovered",
                }
            },
            "newly_failed_checks": [],
            "last_poll_time": None,
        }

        # Mock GitHub API to return failed checks
        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance
        mock_tool_instance._arun.return_value = {
            "success": True,
            "checks": {
                "CI": {
                    "status": CheckStatus.FAILURE.value,
                    "conclusion": "failure",
                    "details_url": "https://github.com/test-org/test-repo/runs/123",
                },
                "Security": {
                    "status": CheckStatus.FAILURE.value,
                    "conclusion": "failure",
                    "details_url": "https://github.com/test-org/test-repo/runs/124",
                }
            }
        }

        # Step 1: Monitor checks
        monitored_state = await check_monitor_node(state)

        # Verify newly failed checks were detected
        assert len(monitored_state["newly_failed_checks"]) == 2
        newly_failed_names = {check["check_name"] for check in monitored_state["newly_failed_checks"]}
        assert newly_failed_names == {"CI", "Security"}

        # Step 2: Test analysis decision
        decision = should_analyze_failures(monitored_state)
        assert decision == "analyze_failures"

        # Step 3: Prioritize failures
        prioritized_state = await prioritize_failures(monitored_state)

        # Verify prioritization (Security should be first due to priority 1)
        prioritized = prioritized_state["prioritized_failures"]
        assert len(prioritized) == 2
        assert prioritized[0]["check_name"] == "Security"
        assert prioritized[1]["check_name"] == "CI"
