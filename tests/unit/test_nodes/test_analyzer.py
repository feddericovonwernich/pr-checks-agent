"""Tests for failure analyzer node"""

from unittest.mock import ANY, AsyncMock, patch

import pytest

from src.nodes.analyzer import (
    _get_failure_context,
    failure_analyzer_node,
    should_attempt_fixes,
)
from src.state.schemas import RepositoryConfig


class TestFailureAnalyzerNode:
    """Test FailureAnalyzer node functionality."""

    @pytest.fixture
    def base_state(self):
        """Create base monitor state for testing."""
        config = RepositoryConfig(
            owner="test-org",
            repo="test-repo",
            claude_context={
                "language": "python",
                "framework": "fastapi",
                "test_framework": "pytest",
            },
        )

        return {
            "repository": "test-org/test-repo",
            "config": config,
            "active_prs": {},
            "prioritized_failures": [],
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
                "title": "Add new feature",
                "author": "developer",
                "branch": "feature-branch",
                "base_branch": "main",
                "url": "https://github.com/test-org/test-repo/pull/123",
            },
            "checks": {},
            "failed_checks": ["CI"],
            "workflow_step": "needs_analysis",
        }

    @pytest.fixture
    def sample_prioritized_failure(self):
        """Sample prioritized failure for testing."""
        return {
            "pr_number": 123,
            "check_name": "CI",
            "check_info": {
                "status": "failure",
                "conclusion": "failure",
                "details_url": "https://github.com/test-org/test-repo/runs/123",
                "started_at": "2024-01-01T12:00:00Z",
                "completed_at": "2024-01-01T12:05:00Z",
                "failure_logs": "Build failed: syntax error in main.py",
                "error_message": "SyntaxError: unexpected token at line 42",
            },
            "priority_score": 10.0,
        }

    @pytest.mark.asyncio
    async def test_failure_analyzer_node_no_failures(self, base_state):
        """Test analyzer when there are no failures to analyze."""
        result = await failure_analyzer_node(base_state)

        # Should return state unchanged
        assert result == base_state

    @patch("src.nodes.analyzer.GitHubTool")
    @patch("src.nodes.analyzer.LLMService")
    @pytest.mark.asyncio
    async def test_failure_analyzer_node_successful_analysis(
        self, mock_llm_service, mock_github_tool, base_state, sample_pr_state, sample_prioritized_failure
    ):
        """Test successful failure analysis."""
        # Add LLM config to the base state's config
        base_state["config"].llm = type(
            "LLMConfig", (), {"provider": "openai", "model": "gpt-4", "effective_api_key": "test-key", "base_url": None}
        )()

        base_state["active_prs"] = {123: sample_pr_state}
        base_state["prioritized_failures"] = [sample_prioritized_failure]

        # Mock GitHub tool
        mock_github_instance = AsyncMock()
        mock_github_tool.return_value = mock_github_instance

        # Mock LLM service
        mock_llm_instance = AsyncMock()
        mock_llm_service.return_value = mock_llm_instance
        mock_llm_instance.analyze_failure.return_value = {
            "success": True,
            "analysis": "The build failed due to a syntax error in main.py at line 42. Missing colon after if statement.",
            "fixable": True,
            "suggested_fix": "Add missing colon after if statement on line 42",
            "confidence": 0.9,
            "severity": "medium",
            "category": "syntax_error",
            "llm_provider": "openai",
            "llm_model": "gpt-4",
        }

        result = await failure_analyzer_node(base_state)

        # Verify LLM service was called correctly
        mock_llm_instance.analyze_failure.assert_called_once_with(
            failure_context=ANY,  # Will be built by _get_failure_context
            check_name="CI",
            pr_info=sample_pr_state["pr_info"],
            project_context=base_state["config"].claude_context,
        )

        # Verify result structure
        assert "active_prs" in result
        assert "analysis_results" in result
        assert "analysis_stats" in result

        # Verify PR state was updated
        updated_pr = result["active_prs"][123]
        assert updated_pr["workflow_step"] == "analyzed"
        assert "analysis_CI" in updated_pr

        analysis_data = updated_pr["analysis_CI"]
        assert analysis_data["check_name"] == "CI"
        assert analysis_data["fixable"] is True
        assert "suggested_actions" in analysis_data
        assert len(analysis_data["suggested_actions"]) == 2

        # Verify analysis results
        analysis_results = result["analysis_results"]
        assert len(analysis_results) == 1
        assert analysis_results[0]["pr_number"] == 123
        assert analysis_results[0]["check_name"] == "CI"
        assert analysis_results[0]["fixable"] is True

        # Verify analysis stats
        stats = result["analysis_stats"]
        assert stats["total_analyzed"] == 1
        assert stats["fixable_count"] == 1

    @patch("src.nodes.analyzer.GitHubTool")
    @patch("src.nodes.analyzer.ClaudeCodeTool")
    @pytest.mark.asyncio
    async def test_failure_analyzer_node_unfixable_analysis(
        self, mock_claude_tool, mock_github_tool, base_state, sample_pr_state, sample_prioritized_failure
    ):
        """Test analysis that determines issue is not fixable."""
        base_state["active_prs"] = {123: sample_pr_state}
        base_state["prioritized_failures"] = [sample_prioritized_failure]

        # Mock tools
        mock_github_instance = AsyncMock()
        mock_github_tool.return_value = mock_github_instance

        mock_claude_instance = AsyncMock()
        mock_claude_tool.return_value = mock_claude_instance
        mock_claude_instance._arun.return_value = {
            "success": True,
            "analysis": "The failure is due to external service dependency being unavailable. "
            "This requires manual intervention.",
            "fixable": False,
            "suggested_actions": ["Contact external service provider", "Check service status page"],
            "attempt_id": "attempt_124",
        }

        result = await failure_analyzer_node(base_state)

        # Verify analysis marked as not fixable
        analysis_results = result["analysis_results"]
        assert len(analysis_results) == 1
        assert analysis_results[0]["fixable"] is False

        # Verify stats
        stats = result["analysis_stats"]
        assert stats["total_analyzed"] == 1
        assert stats["fixable_count"] == 0

    @patch("src.nodes.analyzer.GitHubTool")
    @patch("src.nodes.analyzer.ClaudeCodeTool")
    @pytest.mark.asyncio
    async def test_failure_analyzer_node_claude_analysis_failure(
        self, mock_claude_tool, mock_github_tool, base_state, sample_pr_state, sample_prioritized_failure
    ):
        """Test when Claude analysis fails."""
        base_state["active_prs"] = {123: sample_pr_state}
        base_state["prioritized_failures"] = [sample_prioritized_failure]

        # Mock tools
        mock_github_instance = AsyncMock()
        mock_github_tool.return_value = mock_github_instance

        mock_claude_instance = AsyncMock()
        mock_claude_tool.return_value = mock_claude_instance
        mock_claude_instance._arun.return_value = {"success": False, "error": "Claude Code CLI not available"}

        result = await failure_analyzer_node(base_state)

        # Verify PR state shows analysis failure
        updated_pr = result["active_prs"][123]
        assert updated_pr["workflow_step"] == "analysis_failed"
        assert updated_pr["error_message"] == "Claude Code CLI not available"

        # Verify no analysis results
        assert result["analysis_results"] == []

    @patch("src.nodes.analyzer.GitHubTool")
    @patch("src.nodes.analyzer.ClaudeCodeTool")
    @pytest.mark.asyncio
    async def test_failure_analyzer_node_unexpected_exception(
        self, mock_claude_tool, mock_github_tool, base_state, sample_pr_state, sample_prioritized_failure
    ):
        """Test analyzer with unexpected exception."""
        base_state["active_prs"] = {123: sample_pr_state}
        base_state["prioritized_failures"] = [sample_prioritized_failure]

        # Mock tools to raise exception
        mock_github_instance = AsyncMock()
        mock_github_tool.return_value = mock_github_instance

        mock_claude_instance = AsyncMock()
        mock_claude_tool.return_value = mock_claude_instance
        mock_claude_instance._arun.side_effect = Exception("Network timeout")

        result = await failure_analyzer_node(base_state)

        # Verify error handling
        updated_pr = result["active_prs"][123]
        assert updated_pr["workflow_step"] == "analysis_error"
        assert "Network timeout" in updated_pr["error_message"]

    @patch("src.nodes.analyzer.GitHubTool")
    @patch("src.nodes.analyzer.ClaudeCodeTool")
    @pytest.mark.asyncio
    async def test_failure_analyzer_node_multiple_failures(self, mock_claude_tool, mock_github_tool, base_state):
        """Test analyzer with multiple failures."""
        # Setup multiple PR states
        pr_state_1 = {
            "pr_number": 123,
            "pr_info": {"title": "PR 1", "author": "dev1"},
            "workflow_step": "needs_analysis",
        }
        pr_state_2 = {
            "pr_number": 456,
            "pr_info": {"title": "PR 2", "author": "dev2"},
            "workflow_step": "needs_analysis",
        }

        base_state["active_prs"] = {123: pr_state_1, 456: pr_state_2}
        base_state["prioritized_failures"] = [
            {
                "pr_number": 123,
                "check_name": "CI",
                "check_info": {"status": "failure", "details_url": "url1"},
                "priority_score": 1.0,
            },
            {
                "pr_number": 456,
                "check_name": "Tests",
                "check_info": {"status": "failure", "details_url": "url2"},
                "priority_score": 2.0,
            },
        ]

        # Mock tools
        mock_github_instance = AsyncMock()
        mock_github_tool.return_value = mock_github_instance

        mock_claude_instance = AsyncMock()
        mock_claude_tool.return_value = mock_claude_instance

        # Return different results for each call
        mock_responses = [
            {
                "success": True,
                "analysis": "CI build issue",
                "fixable": True,
                "suggested_actions": ["Fix CI"],
                "attempt_id": "attempt_1",
            },
            {
                "success": True,
                "analysis": "Test failure",
                "fixable": False,
                "suggested_actions": ["Manual review needed"],
                "attempt_id": "attempt_2",
            },
        ]
        mock_claude_instance._arun.side_effect = mock_responses

        result = await failure_analyzer_node(base_state)

        # Verify both failures were analyzed
        assert len(result["analysis_results"]) == 2
        assert mock_claude_instance._arun.call_count == 2

        # Verify analysis stats
        stats = result["analysis_stats"]
        assert stats["total_analyzed"] == 2
        assert stats["fixable_count"] == 1

    @patch("src.nodes.analyzer.GitHubTool")
    @patch("src.nodes.analyzer.ClaudeCodeTool")
    @pytest.mark.asyncio
    async def test_failure_analyzer_node_dry_run_mode(
        self, mock_claude_tool, mock_github_tool, base_state, sample_pr_state, sample_prioritized_failure
    ):
        """Test analyzer in dry run mode."""
        base_state["dry_run"] = True
        base_state["active_prs"] = {123: sample_pr_state}
        base_state["prioritized_failures"] = [sample_prioritized_failure]

        # Mock GitHub tool
        mock_github_instance = AsyncMock()
        mock_github_tool.return_value = mock_github_instance

        # Mock Claude tool
        mock_claude_instance = AsyncMock()
        mock_claude_tool.return_value = mock_claude_instance
        mock_claude_instance._arun.return_value = {
            "success": True,
            "analysis": "Test analysis",
            "fixable": True,
            "suggested_actions": [],
            "attempt_id": "test_id",
        }

        # Verify dry_run is passed to Claude tool
        await failure_analyzer_node(base_state)
        mock_claude_tool.assert_called_once_with(dry_run=True)


class TestGetFailureContext:
    """Test failure context building helper function."""

    @pytest.fixture
    def sample_check_info(self):
        """Sample check info for context building."""
        return {
            "status": "failure",
            "conclusion": "failure",
            "started_at": "2024-01-01T12:00:00Z",
            "completed_at": "2024-01-01T12:05:00Z",
            "details_url": "https://github.com/test-org/test-repo/check-runs/123456",
            "failure_logs": "Build failed: missing dependency",
            "error_message": "ModuleNotFoundError: No module named 'requests'",
        }

    @patch("src.nodes.analyzer.GitHubTool")
    @pytest.mark.asyncio
    async def test_get_failure_context_basic_info(self, mock_github_tool, sample_check_info):
        """Test basic failure context building."""
        mock_tool_instance = AsyncMock()
        mock_github_tool.return_value = mock_tool_instance

        context = await _get_failure_context(mock_tool_instance, "test/repo", sample_check_info, "CI Build")

        # Verify basic information is included
        assert "Check: CI Build" in context
        assert "Status: failure" in context
        assert "Conclusion: failure" in context
        assert "Started: 2024-01-01T12:00:00Z" in context
        assert "Completed: 2024-01-01T12:05:00Z" in context
        assert "Failure Logs:" in context
        assert "Build failed: missing dependency" in context
        assert "Error Message: ModuleNotFoundError" in context

    @patch("src.nodes.analyzer.GitHubTool")
    @pytest.mark.asyncio
    async def test_get_failure_context_with_check_run_logs(self, mock_github_tool, sample_check_info):
        """Test failure context building with detailed check run logs."""
        mock_tool_instance = AsyncMock()
        mock_tool_instance._arun.return_value = {
            "success": True,
            "logs": [
                "Step 1: Install dependencies",
                "ERROR: Could not find module 'requests'",
                "Build failed with exit code 1",
            ],
        }

        context = await _get_failure_context(mock_tool_instance, "test/repo", sample_check_info, "CI Build")

        # Verify detailed logs were fetched and included
        mock_tool_instance._arun.assert_called_once_with(
            operation="get_check_logs", repository="test/repo", check_run_id=123456
        )

        assert "Failure Details:" in context
        assert "Step 1: Install dependencies" in context
        assert "ERROR: Could not find module 'requests'" in context

    @patch("src.nodes.analyzer.GitHubTool")
    @pytest.mark.asyncio
    async def test_get_failure_context_invalid_check_run_id(self, mock_github_tool, sample_check_info):
        """Test failure context with invalid check run ID."""
        # Modify details URL to have non-numeric ID
        sample_check_info["details_url"] = "https://github.com/test-org/test-repo/check-runs/invalid"

        mock_tool_instance = AsyncMock()

        context = await _get_failure_context(mock_tool_instance, "test/repo", sample_check_info, "CI Build")

        # Should not attempt to fetch detailed logs
        mock_tool_instance._arun.assert_not_called()

        # But should still include basic info
        assert "Check: CI Build" in context
        assert "Status: failure" in context

    @patch("src.nodes.analyzer.GitHubTool")
    @pytest.mark.asyncio
    async def test_get_failure_context_logs_fetch_failure(self, mock_github_tool, sample_check_info):
        """Test failure context when log fetching fails."""
        mock_tool_instance = AsyncMock()
        mock_tool_instance._arun.return_value = {"success": False, "error": "Access denied"}

        context = await _get_failure_context(mock_tool_instance, "test/repo", sample_check_info, "CI Build")

        # Should still include basic failure info
        assert "Check: CI Build" in context
        assert "Failure Logs:" in context
        assert "Build failed: missing dependency" in context

    @pytest.mark.asyncio
    async def test_get_failure_context_minimal_info(self):
        """Test failure context with minimal check info."""
        minimal_check_info = {
            "status": "failure",
        }

        context = await _get_failure_context(None, "test/repo", minimal_check_info, "Unknown Check")

        # Should handle missing fields gracefully
        assert "Check: Unknown Check" in context
        assert "Status: failure" in context
        assert "Conclusion: unknown" in context


class TestShouldAttemptFixes:
    """Test edge function for determining if fixes should be attempted."""

    def test_should_attempt_fixes_with_fixable_issues(self):
        """Test fix decision with fixable issues."""
        state = {
            "analysis_results": [
                {"pr_number": 123, "check_name": "CI", "fixable": True},
                {"pr_number": 456, "check_name": "Tests", "fixable": False},
                {"pr_number": 789, "check_name": "Lint", "fixable": True},
            ]
        }

        result = should_attempt_fixes(state)
        assert result == "attempt_fixes"

    def test_should_attempt_fixes_only_unfixable_issues(self):
        """Test fix decision with only unfixable issues."""
        state = {
            "analysis_results": [
                {"pr_number": 123, "check_name": "CI", "fixable": False},
                {"pr_number": 456, "check_name": "Tests", "fixable": False},
            ]
        }

        result = should_attempt_fixes(state)
        assert result == "escalate_to_human"

    def test_should_attempt_fixes_no_analysis_results(self):
        """Test fix decision with no analysis results."""
        state = {"analysis_results": []}

        result = should_attempt_fixes(state)
        assert result == "wait_for_next_poll"

    def test_should_attempt_fixes_missing_analysis_results(self):
        """Test fix decision with missing analysis results."""
        state = {}

        result = should_attempt_fixes(state)
        assert result == "wait_for_next_poll"

    def test_should_attempt_fixes_mixed_results(self):
        """Test fix decision prioritizes fixable over unfixable."""
        state = {
            "analysis_results": [
                {"pr_number": 123, "check_name": "CI", "fixable": False},
                {"pr_number": 456, "check_name": "Tests", "fixable": True},
                {"pr_number": 789, "check_name": "Security", "fixable": False},
            ]
        }

        result = should_attempt_fixes(state)
        assert result == "attempt_fixes"


class TestAnalyzerIntegration:
    """Integration tests for analyzer node."""

    @patch("src.nodes.analyzer.GitHubTool")
    @patch("src.nodes.analyzer.ClaudeCodeTool")
    @pytest.mark.asyncio
    async def test_complete_analysis_workflow(self, mock_claude_tool, mock_github_tool):
        """Test complete analysis workflow from failure to decision."""
        # Setup complex state with multiple failures
        config = RepositoryConfig(
            owner="test-org", repo="test-repo", claude_context={"language": "python", "framework": "django"}
        )

        state = {
            "repository": "test-org/test-repo",
            "config": config,
            "active_prs": {
                123: {
                    "pr_number": 123,
                    "pr_info": {
                        "title": "Fix authentication bug",
                        "author": "security-team",
                        "base_branch": "main",
                    },
                    "workflow_step": "needs_analysis",
                },
                456: {
                    "pr_number": 456,
                    "pr_info": {
                        "title": "Add new feature",
                        "author": "feature-team",
                        "base_branch": "develop",
                    },
                    "workflow_step": "needs_analysis",
                },
            },
            "prioritized_failures": [
                {
                    "pr_number": 123,
                    "check_name": "Security",
                    "check_info": {
                        "status": "failure",
                        "details_url": "https://github.com/test-org/test-repo/check-runs/111",
                        "failure_logs": "SQL injection vulnerability detected",
                    },
                    "priority_score": 1.0,
                },
                {
                    "pr_number": 456,
                    "check_name": "Tests",
                    "check_info": {
                        "status": "failure",
                        "details_url": "https://github.com/test-org/test-repo/check-runs/222",
                        "failure_logs": "3 unit tests failed",
                    },
                    "priority_score": 2.0,
                },
            ],
        }

        # Mock tools
        mock_github_instance = AsyncMock()
        mock_github_tool.return_value = mock_github_instance

        mock_claude_instance = AsyncMock()
        mock_claude_tool.return_value = mock_claude_instance

        # Mock different analysis results
        mock_responses = [
            {
                "success": True,
                "analysis": "SQL injection vulnerability in user input handling. Needs parameterized queries.",
                "fixable": False,  # Security issue needs human review
                "suggested_actions": ["Review SQL queries", "Implement parameterized queries"],
                "attempt_id": "security_analysis_1",
            },
            {
                "success": True,
                "analysis": "Unit test failures due to missing mock data. Can be fixed by updating test fixtures.",
                "fixable": True,  # Test issue is fixable
                "suggested_actions": ["Update test fixtures", "Add missing mock data"],
                "attempt_id": "test_analysis_1",
            },
        ]
        mock_claude_instance._arun.side_effect = mock_responses

        # Step 1: Analyze failures
        analyzed_state = await failure_analyzer_node(state)

        # Verify analysis results
        analysis_results = analyzed_state["analysis_results"]
        assert len(analysis_results) == 2

        # Security issue should be marked as unfixable
        security_result = next(r for r in analysis_results if r["check_name"] == "Security")
        assert security_result["fixable"] is False

        # Test issue should be marked as fixable
        test_result = next(r for r in analysis_results if r["check_name"] == "Tests")
        assert test_result["fixable"] is True

        # Step 2: Test decision making
        decision = should_attempt_fixes(analyzed_state)
        assert decision == "attempt_fixes"  # Should attempt fixes since some are fixable

        # Verify PR states were updated correctly
        assert analyzed_state["active_prs"][123]["workflow_step"] == "analyzed"
        assert analyzed_state["active_prs"][456]["workflow_step"] == "analyzed"

        # Verify analysis data was stored
        assert "analysis_Security" in analyzed_state["active_prs"][123]
        assert "analysis_Tests" in analyzed_state["active_prs"][456]
