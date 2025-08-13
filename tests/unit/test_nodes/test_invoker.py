"""Tests for Claude invoker node"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.nodes.invoker import (
    _create_fix_prompt,
    claude_invoker_node,
    should_retry_or_escalate,
)
from src.state.schemas import FixAttemptStatus, RepositoryConfig


class TestClaudeInvokerNode:
    """Test ClaudeInvoker node functionality."""

    @pytest.fixture
    def base_state(self):
        """Create base monitor state for testing."""
        config = RepositoryConfig(
            owner="test-org",
            repo="test-repo",
            fix_limits={
                "max_attempts": 3,
                "timeout": 300,
            },
            claude_context={
                "language": "python",
                "framework": "fastapi",
            },
        )

        return {
            "repository": "test-org/test-repo",
            "config": config,
            "active_prs": {},
            "analysis_results": [],
            "dry_run": False,
            "total_fixes_attempted": 0,
            "total_fixes_successful": 0,
        }

    @pytest.fixture
    def sample_pr_state(self):
        """Sample PR state for testing."""
        return {
            "pr_number": 123,
            "repository": "test-org/test-repo",
            "pr_info": {
                "number": 123,
                "title": "Fix authentication bug",
                "author": "developer",
                "branch": "feature-auth-fix",
                "base_branch": "main",
                "url": "https://github.com/test-org/test-repo/pull/123",
            },
            "checks": {},
            "failed_checks": ["CI"],
            "fix_attempts": {},
            "current_fix_attempt": None,
            "escalations": [],
            "escalation_status": "none",
            "workflow_step": "analyzed",
        }

    @pytest.fixture
    def sample_analysis_result(self):
        """Sample analysis result for testing."""
        return {
            "pr_number": 123,
            "check_name": "CI",
            "fixable": True,
            "analysis": {
                "timestamp": datetime.now(),
                "check_name": "CI",
                "analysis": "Build failed due to missing import statement. Need to add 'import requests' at top of main.py",
                "fixable": True,
                "suggested_actions": [
                    "Add missing import statement to main.py",
                    "Verify all dependencies are in requirements.txt",
                ],
                "failure_context": "Build failed: ModuleNotFoundError: No module named 'requests'",
                "attempt_id": "analysis_123",
            },
        }

    @pytest.mark.asyncio
    async def test_claude_invoker_node_no_fixable_issues(self, base_state):
        """Test invoker when there are no fixable issues."""
        result = await claude_invoker_node(base_state)

        # Should return state unchanged
        assert result == base_state

    @patch("src.nodes.invoker.ClaudeCodeTool")
    @patch("src.nodes.invoker.uuid.uuid4")
    @pytest.mark.asyncio
    async def test_claude_invoker_node_successful_fix(
        self, mock_uuid, mock_claude_tool, base_state, sample_pr_state, sample_analysis_result
    ):
        """Test successful fix attempt."""
        # Setup mocks
        mock_uuid.return_value = "test-attempt-id-123"

        base_state["active_prs"] = {123: sample_pr_state}
        base_state["analysis_results"] = [sample_analysis_result]

        mock_claude_instance = AsyncMock()
        mock_claude_tool.return_value = mock_claude_instance
        mock_claude_instance._arun.return_value = {
            "success": True,
            "fix_description": "Added missing 'import requests' statement to main.py line 1",
            "duration_seconds": 15.5,
        }

        result = await claude_invoker_node(base_state)

        # Verify Claude tool was called correctly
        mock_claude_instance._arun.assert_called_once_with(
            operation="fix_issue",
            failure_context="Build failed: ModuleNotFoundError: No module named 'requests'",
            check_name="CI",
            pr_info=sample_pr_state["pr_info"],
            project_context=base_state["config"].claude_context,
            repository_path=None,
        )

        # Verify result structure
        assert "active_prs" in result
        assert "fix_results" in result
        assert "fix_stats" in result

        # Verify PR state was updated
        updated_pr = result["active_prs"][123]
        assert updated_pr["workflow_step"] == "fix_successful"
        assert updated_pr["current_fix_attempt"] is None  # Cleared after completion
        assert "fix_attempts" in updated_pr
        assert "CI" in updated_pr["fix_attempts"]

        # Verify fix attempt record
        fix_attempts = updated_pr["fix_attempts"]["CI"]
        assert len(fix_attempts) == 1
        attempt = fix_attempts[0]
        assert attempt["id"] == "test-attempt-id-123"
        assert attempt["check_name"] == "CI"
        assert attempt["status"] == FixAttemptStatus.SUCCESS.value
        assert attempt["result"] == "Added missing 'import requests' statement to main.py line 1"
        assert attempt["duration_seconds"] == 15.5

        # Verify fix results
        fix_results = result["fix_results"]
        assert len(fix_results) == 1
        assert fix_results[0]["success"] is True
        assert fix_results[0]["pr_number"] == 123

        # Verify counters were updated
        assert result["total_fixes_attempted"] == 1
        assert result["total_fixes_successful"] == 1

        # Verify fix stats
        stats = result["fix_stats"]
        assert stats["total_attempted"] == 1
        assert stats["successful_count"] == 1

    @patch("src.nodes.invoker.ClaudeCodeTool")
    @patch("src.nodes.invoker.uuid.uuid4")
    @pytest.mark.asyncio
    async def test_claude_invoker_node_failed_fix(
        self, mock_uuid, mock_claude_tool, base_state, sample_pr_state, sample_analysis_result
    ):
        """Test failed fix attempt."""
        mock_uuid.return_value = "test-attempt-id-456"

        base_state["active_prs"] = {123: sample_pr_state}
        base_state["analysis_results"] = [sample_analysis_result]

        mock_claude_instance = AsyncMock()
        mock_claude_tool.return_value = mock_claude_instance
        mock_claude_instance._arun.return_value = {
            "success": False,
            "error": "Unable to locate main.py file in repository",
            "duration_seconds": 5.0,
        }

        result = await claude_invoker_node(base_state)

        # Verify PR state shows fix failure
        updated_pr = result["active_prs"][123]
        assert updated_pr["workflow_step"] == "fix_failed"

        # Verify fix attempt record shows failure
        fix_attempts = updated_pr["fix_attempts"]["CI"]
        attempt = fix_attempts[0]
        assert attempt["status"] == FixAttemptStatus.FAILURE.value
        assert attempt["error_message"] == "Unable to locate main.py file in repository"

        # Verify counters
        assert result["total_fixes_attempted"] == 1
        assert result["total_fixes_successful"] == 0

    @patch("src.nodes.invoker.ClaudeCodeTool")
    @pytest.mark.asyncio
    async def test_claude_invoker_node_max_attempts_reached(
        self, mock_claude_tool, base_state, sample_pr_state, sample_analysis_result
    ):
        """Test when max fix attempts have been reached."""
        # Setup PR state with existing fix attempts at limit
        sample_pr_state["fix_attempts"] = {
            "CI": [
                {"id": "attempt1", "status": FixAttemptStatus.FAILURE.value},
                {"id": "attempt2", "status": FixAttemptStatus.FAILURE.value},
                {"id": "attempt3", "status": FixAttemptStatus.FAILURE.value},
            ]
        }

        base_state["active_prs"] = {123: sample_pr_state}
        base_state["analysis_results"] = [sample_analysis_result]

        mock_claude_instance = AsyncMock()
        mock_claude_tool.return_value = mock_claude_instance

        result = await claude_invoker_node(base_state)

        # Should skip attempting fix
        mock_claude_instance._arun.assert_not_called()

        # Should return empty fix results
        assert result["fix_results"] == []

        # Counters should not increment
        assert result["total_fixes_attempted"] == 0
        assert result["total_fixes_successful"] == 0

    @patch("src.nodes.invoker.ClaudeCodeTool")
    @pytest.mark.asyncio
    async def test_claude_invoker_node_unexpected_exception(
        self, mock_claude_tool, base_state, sample_pr_state, sample_analysis_result
    ):
        """Test invoker with unexpected exception."""
        base_state["active_prs"] = {123: sample_pr_state}
        base_state["analysis_results"] = [sample_analysis_result]

        mock_claude_instance = AsyncMock()
        mock_claude_tool.return_value = mock_claude_instance
        mock_claude_instance._arun.side_effect = Exception("Network timeout")

        result = await claude_invoker_node(base_state)

        # Verify error handling
        updated_pr = result["active_prs"][123]
        assert updated_pr["workflow_step"] == "fix_error"
        assert "Network timeout" in updated_pr["error_message"]

        # Verify fix attempt shows error
        fix_attempts = updated_pr["fix_attempts"]["CI"]
        attempt = fix_attempts[0]
        assert attempt["status"] == FixAttemptStatus.FAILURE.value
        assert attempt["error_message"] == "Network timeout"

    @patch("src.nodes.invoker.ClaudeCodeTool")
    @pytest.mark.asyncio
    async def test_claude_invoker_node_multiple_fixes(self, mock_claude_tool, base_state):
        """Test invoker with multiple fixable issues."""
        # Setup multiple PR states
        pr_state_1 = {
            "pr_number": 123,
            "pr_info": {"title": "PR 1", "author": "dev1"},
            "fix_attempts": {},
            "workflow_step": "analyzed",
        }
        pr_state_2 = {
            "pr_number": 456,
            "pr_info": {"title": "PR 2", "author": "dev2"},
            "fix_attempts": {},
            "workflow_step": "analyzed",
        }

        base_state["active_prs"] = {123: pr_state_1, 456: pr_state_2}
        base_state["analysis_results"] = [
            {
                "pr_number": 123,
                "check_name": "CI",
                "fixable": True,
                "analysis": {"failure_context": "Build error 1", "suggested_actions": ["Fix 1"]},
            },
            {
                "pr_number": 456,
                "check_name": "Tests",
                "fixable": True,
                "analysis": {"failure_context": "Test error 2", "suggested_actions": ["Fix 2"]},
            },
        ]

        mock_claude_instance = AsyncMock()
        mock_claude_tool.return_value = mock_claude_instance

        # Mock different results for each fix
        mock_responses = [
            {"success": True, "fix_description": "Fixed CI issue"},
            {"success": False, "error": "Could not fix tests"},
        ]
        mock_claude_instance._arun.side_effect = mock_responses

        result = await claude_invoker_node(base_state)

        # Verify both fixes were attempted
        assert len(result["fix_results"]) == 2
        assert mock_claude_instance._arun.call_count == 2

        # Verify different outcomes
        assert result["fix_results"][0]["success"] is True
        assert result["fix_results"][1]["success"] is False

        # Verify counters
        assert result["total_fixes_attempted"] == 2
        assert result["total_fixes_successful"] == 1

    @pytest.mark.asyncio
    async def test_claude_invoker_node_dry_run_mode(self, base_state, sample_pr_state, sample_analysis_result):
        """Test invoker in dry run mode."""
        base_state["dry_run"] = True
        base_state["active_prs"] = {123: sample_pr_state}
        base_state["analysis_results"] = [sample_analysis_result]

        with patch("src.nodes.invoker.ClaudeCodeTool") as mock_claude_tool:
            mock_claude_instance = AsyncMock()
            mock_claude_tool.return_value = mock_claude_instance

            # Verify dry_run is passed to Claude tool
            await claude_invoker_node(base_state)
            mock_claude_tool.assert_called_once_with(dry_run=True)


class TestCreateFixPrompt:
    """Test fix prompt creation helper function."""

    def test_create_fix_prompt_complete_data(self):
        """Test fix prompt creation with complete analysis data."""
        analysis = {
            "analysis": "The build failed because of a missing import statement. The error occurs at line 42 in main.py.",
            "suggested_actions": [
                "Add 'import requests' at the top of main.py",
                "Verify requests is in requirements.txt",
                "Run tests to confirm fix",
            ],
            "failure_context": "ModuleNotFoundError: No module named 'requests'",
        }

        pr_info = {"title": "Add user authentication", "branch": "feature-auth", "author": "developer"}

        config = RepositoryConfig(owner="test", repo="test")

        prompt = _create_fix_prompt(analysis, pr_info, config)

        # Verify prompt structure
        assert "Analysis**: The build failed because of a missing import statement" in prompt
        assert "Suggested Actions**:" in prompt
        assert "1. Add 'import requests' at the top of main.py" in prompt
        assert "2. Verify requests is in requirements.txt" in prompt
        assert "3. Run tests to confirm fix" in prompt
        assert "PR Context**:" in prompt
        assert "Title: Add user authentication" in prompt
        assert "Branch: feature-auth" in prompt
        assert "Author: developer" in prompt
        assert "implement the minimal fix needed" in prompt

    def test_create_fix_prompt_minimal_data(self):
        """Test fix prompt creation with minimal data."""
        analysis = {
            "analysis": "Build failed",
            "suggested_actions": [],
        }

        pr_info = {"title": "", "branch": "", "author": ""}

        config = RepositoryConfig(owner="test", repo="test")

        prompt = _create_fix_prompt(analysis, pr_info, config)

        # Should handle empty data gracefully
        assert "Analysis**: Build failed" in prompt
        assert "Suggested Actions**:" in prompt
        assert "Title: " in prompt  # Empty but present
        assert "implement the minimal fix needed" in prompt

    def test_create_fix_prompt_no_analysis(self):
        """Test fix prompt with missing analysis text."""
        analysis = {"suggested_actions": ["Do something"]}

        pr_info = {"title": "Test PR"}
        config = RepositoryConfig(owner="test", repo="test")

        prompt = _create_fix_prompt(analysis, pr_info, config)

        # Should handle missing analysis gracefully
        assert "Analysis**: " in prompt  # Empty analysis
        assert "1. Do something" in prompt


class TestShouldRetryOrEscalate:
    """Test edge function for determining next steps after fix attempts."""

    def test_should_retry_or_escalate_successful_fixes(self):
        """Test decision with successful fixes."""
        config = RepositoryConfig(owner="test", repo="test")
        state = {
            "config": config,
            "fix_results": [
                {"pr_number": 123, "check_name": "CI", "success": True},
                {"pr_number": 456, "check_name": "Tests", "success": True},
            ],
        }

        result = should_retry_or_escalate(state)
        assert result == "verify_fixes"

    def test_should_retry_or_escalate_need_retry(self):
        """Test decision when some fixes need retry."""
        config = RepositoryConfig(owner="test-org", repo="test-repo", fix_limits={"max_attempts": 3})

        state = {
            "config": config,
            "fix_results": [{"pr_number": 123, "check_name": "CI", "success": False}],
            "active_prs": {
                123: {
                    "failed_checks": ["CI"],
                    "fix_attempts": {
                        "CI": [{"status": FixAttemptStatus.FAILURE.value}]  # Only 1 attempt, can retry
                    },
                }
            },
        }

        result = should_retry_or_escalate(state)
        assert result == "retry_fixes"

    def test_should_retry_or_escalate_need_escalation(self):
        """Test decision when issues need escalation."""
        config = RepositoryConfig(owner="test-org", repo="test-repo", fix_limits={"max_attempts": 2})

        state = {
            "config": config,
            "fix_results": [],
            "active_prs": {
                123: {
                    "failed_checks": ["CI"],
                    "fix_attempts": {
                        "CI": [
                            {"status": FixAttemptStatus.FAILURE.value},
                            {"status": FixAttemptStatus.FAILURE.value},
                        ]  # Max attempts reached
                    },
                }
            },
        }

        result = should_retry_or_escalate(state)
        assert result == "escalate_to_human"

    def test_should_retry_or_escalate_mixed_scenario(self):
        """Test decision with mixed retry/escalation needs."""
        config = RepositoryConfig(owner="test-org", repo="test-repo", fix_limits={"max_attempts": 2})

        state = {
            "config": config,
            "fix_results": [],
            "active_prs": {
                123: {
                    "failed_checks": ["CI"],
                    "fix_attempts": {
                        "CI": [{"status": FixAttemptStatus.FAILURE.value}]  # Can retry
                    },
                },
                456: {
                    "failed_checks": ["Tests"],
                    "fix_attempts": {
                        "Tests": [
                            {"status": FixAttemptStatus.FAILURE.value},
                            {"status": FixAttemptStatus.FAILURE.value},
                        ]  # Needs escalation
                    },
                },
            },
        }

        result = should_retry_or_escalate(state)
        # Retry takes precedence
        assert result == "retry_fixes"

    def test_should_retry_or_escalate_no_work_needed(self):
        """Test decision when no work is needed."""
        state = {
            "config": RepositoryConfig(owner="test", repo="test"),
            "fix_results": [],
            "active_prs": {123: {"failed_checks": [], "fix_attempts": {}}},
        }

        result = should_retry_or_escalate(state)
        assert result == "wait_for_next_poll"

    def test_should_retry_or_escalate_empty_state(self):
        """Test decision with empty state."""
        state = {"config": RepositoryConfig(owner="test", repo="test"), "fix_results": [], "active_prs": {}}

        result = should_retry_or_escalate(state)
        assert result == "wait_for_next_poll"

    def test_should_retry_or_escalate_successful_previous_attempt(self):
        """Test decision ignores failed checks with successful attempts."""
        config = RepositoryConfig(owner="test-org", repo="test-repo", fix_limits={"max_attempts": 3})

        state = {
            "config": config,
            "fix_results": [],
            "active_prs": {
                123: {
                    "failed_checks": ["CI"],
                    "fix_attempts": {
                        "CI": [
                            {"status": FixAttemptStatus.FAILURE.value},
                            {"status": FixAttemptStatus.SUCCESS.value},  # Last attempt successful
                        ]
                    },
                }
            },
        }

        result = should_retry_or_escalate(state)
        assert result == "wait_for_next_poll"


class TestInvokerIntegration:
    """Integration tests for invoker node."""

    @patch("src.nodes.invoker.ClaudeCodeTool")
    @patch("src.nodes.invoker.uuid.uuid4")
    @pytest.mark.asyncio
    async def test_complete_fix_workflow(self, mock_uuid, mock_claude_tool):
        """Test complete fix workflow from analysis to decision."""
        mock_uuid.return_value = "integration-test-id"

        # Setup complex state
        config = RepositoryConfig(
            owner="test-org", repo="test-repo", fix_limits={"max_attempts": 3}, claude_context={"language": "python"}
        )

        state = {
            "repository": "test-org/test-repo",
            "config": config,
            "active_prs": {
                123: {
                    "pr_number": 123,
                    "pr_info": {
                        "title": "Fix critical bug",
                        "author": "maintainer",
                        "branch": "hotfix-critical",
                        "base_branch": "main",
                    },
                    "failed_checks": ["CI", "Security"],
                    "fix_attempts": {},
                    "workflow_step": "analyzed",
                }
            },
            "analysis_results": [
                {
                    "pr_number": 123,
                    "check_name": "CI",
                    "fixable": True,
                    "analysis": {
                        "analysis": "Missing import causing build failure",
                        "suggested_actions": ["Add missing import"],
                        "failure_context": "ImportError: missing module",
                    },
                },
                {
                    "pr_number": 123,
                    "check_name": "Security",
                    "fixable": False,
                    "analysis": {
                        "analysis": "Potential SQL injection vulnerability",
                        "suggested_actions": ["Manual security review required"],
                        "failure_context": "SQL injection risk detected",
                    },
                },
            ],
            "total_fixes_attempted": 0,
            "total_fixes_successful": 0,
        }

        # Mock Claude tool
        mock_claude_instance = AsyncMock()
        mock_claude_tool.return_value = mock_claude_instance
        mock_claude_instance._arun.return_value = {
            "success": True,
            "fix_description": "Added missing 'import logging' statement",
            "duration_seconds": 12.3,
        }

        # Step 1: Attempt fixes
        fixed_state = await claude_invoker_node(state)

        # Verify only fixable issue was attempted
        assert mock_claude_instance._arun.call_count == 1
        assert len(fixed_state["fix_results"]) == 1

        # Verify fix result
        fix_result = fixed_state["fix_results"][0]
        assert fix_result["pr_number"] == 123
        assert fix_result["check_name"] == "CI"
        assert fix_result["success"] is True

        # Verify PR state update
        updated_pr = fixed_state["active_prs"][123]
        assert updated_pr["workflow_step"] == "fix_successful"
        assert len(updated_pr["fix_attempts"]["CI"]) == 1

        # Verify counters
        assert fixed_state["total_fixes_attempted"] == 1
        assert fixed_state["total_fixes_successful"] == 1

        # Step 2: Test decision making
        # Since we have successful fixes, should verify
        decision = should_retry_or_escalate(fixed_state)
        assert decision == "verify_fixes"

        # But we also have unfixable issues, so in a real workflow
        # the unfixable Security check would need separate escalation handling
