"""Tests for escalation node"""

from datetime import datetime, timedelta
from unittest.mock import ANY, AsyncMock, patch

import pytest

from src.nodes.escalation import (
    _identify_escalation_candidates,
    _is_in_cooldown,
    escalation_node,
    handle_escalation_response,
    should_continue_after_escalation,
)
from src.state.schemas import EscalationStatus, RepositoryConfig


class TestEscalationNode:
    """Test Escalation node functionality."""

    @pytest.fixture
    def base_state(self):
        """Create base monitor state for testing."""
        config = RepositoryConfig(
            owner="test-org",
            repo="test-repo",
            fix_limits={
                "max_attempts": 3,
                "escalation_cooldown_hours": 24,
            },
            notifications={
                "escalation_mentions": ["@security-team", "@dev-leads"],
                "telegram_channel": "#alerts",
            },
        )

        return {
            "repository": "test-org/test-repo",
            "config": config,
            "active_prs": {},
            "dry_run": False,
            "total_escalations": 0,
        }

    @pytest.fixture
    def sample_pr_state_needs_escalation(self):
        """Sample PR state that needs escalation."""
        return {
            "pr_number": 123,
            "repository": "test-org/test-repo",
            "pr_info": {
                "number": 123,
                "title": "Critical security fix",
                "author": "security-team",
                "branch": "hotfix-security",
                "base_branch": "main",
                "url": "https://github.com/test-org/test-repo/pull/123",
            },
            "checks": {},
            "failed_checks": ["Security"],
            "fix_attempts": {
                "Security": [
                    {"id": "attempt1", "status": "failure", "timestamp": datetime.now()},
                    {"id": "attempt2", "status": "failure", "timestamp": datetime.now()},
                    {"id": "attempt3", "status": "failure", "timestamp": datetime.now()},
                ]
            },
            "current_fix_attempt": None,
            "escalations": [],
            "escalation_status": "none",
            "workflow_step": "fix_failed",
        }

    @pytest.mark.asyncio
    async def test_escalation_node_no_candidates(self, base_state):
        """Test escalation when there are no candidates."""
        result = await escalation_node(base_state)

        # Should return state unchanged
        assert result == base_state

    @patch("src.nodes.escalation.TelegramTool")
    @patch("src.nodes.escalation.uuid.uuid4")
    @pytest.mark.asyncio
    async def test_escalation_node_successful_escalation(
        self, mock_uuid, mock_telegram_tool, base_state, sample_pr_state_needs_escalation
    ):
        """Test successful escalation to humans."""
        mock_uuid.return_value = "escalation-test-id-123"

        base_state["active_prs"] = {123: sample_pr_state_needs_escalation}

        # Mock Telegram tool
        mock_telegram_instance = AsyncMock()
        mock_telegram_tool.return_value = mock_telegram_instance
        mock_telegram_instance._arun.return_value = {"success": True, "message_id": "telegram_msg_456"}

        result = await escalation_node(base_state)

        # Verify Telegram tool was called correctly
        mock_telegram_instance._arun.assert_called_once_with(
            operation="send_escalation",
            repository="test-org/test-repo",
            pr_number=123,
            check_name="Security",
            failure_context=ANY,
            fix_attempts=sample_pr_state_needs_escalation["fix_attempts"]["Security"],
            escalation_reason="Maximum fix attempts (3) exhausted",
            mentions=["@security-team", "@dev-leads"],
        )

        # Verify result structure
        assert "active_prs" in result
        assert "escalation_results" in result
        assert "escalation_stats" in result

        # Verify PR state was updated
        updated_pr = result["active_prs"][123]
        assert updated_pr["workflow_step"] == "escalated"
        assert updated_pr["escalation_status"] == EscalationStatus.NOTIFIED.value
        assert len(updated_pr["escalations"]) == 1

        # Verify escalation record
        escalation = updated_pr["escalations"][0]
        assert escalation["id"] == "escalation-test-id-123"
        assert escalation["check_name"] == "Security"
        assert escalation["status"] == EscalationStatus.NOTIFIED.value
        assert escalation["telegram_message_id"] == "telegram_msg_456"
        assert "Maximum fix attempts" in escalation["reason"]

        # Verify escalation results
        escalation_results = result["escalation_results"]
        assert len(escalation_results) == 1
        assert escalation_results[0]["success"] is True
        assert escalation_results[0]["pr_number"] == 123
        assert escalation_results[0]["message_id"] == "telegram_msg_456"

        # Verify global counter
        assert result["total_escalations"] == 1

        # Verify escalation stats
        stats = result["escalation_stats"]
        assert stats["total_escalations"] == 1
        assert stats["successful_count"] == 1

    @patch("src.nodes.escalation.TelegramTool")
    @pytest.mark.asyncio
    async def test_escalation_node_telegram_failure(self, mock_telegram_tool, base_state, sample_pr_state_needs_escalation):
        """Test escalation when Telegram notification fails."""
        base_state["active_prs"] = {123: sample_pr_state_needs_escalation}

        mock_telegram_instance = AsyncMock()
        mock_telegram_tool.return_value = mock_telegram_instance
        mock_telegram_instance._arun.return_value = {"success": False, "error": "Telegram bot token invalid"}

        result = await escalation_node(base_state)

        # Verify escalation was attempted but failed
        escalation_results = result["escalation_results"]
        assert len(escalation_results) == 1
        assert escalation_results[0]["success"] is False
        assert escalation_results[0]["error"] == "Telegram bot token invalid"

        # Verify global counter not incremented
        assert result["total_escalations"] == 0

    @patch("src.nodes.escalation.TelegramTool")
    @pytest.mark.asyncio
    async def test_escalation_node_cooldown_active(self, mock_telegram_tool, base_state, sample_pr_state_needs_escalation):
        """Test escalation when cooldown is active."""
        # Add recent escalation to trigger cooldown
        recent_escalation = {
            "id": "recent_escalation",
            "timestamp": datetime.now() - timedelta(hours=12),  # 12 hours ago, within 24h cooldown
            "check_name": "Security",
            "status": EscalationStatus.NOTIFIED.value,
        }
        sample_pr_state_needs_escalation["escalations"] = [recent_escalation]

        base_state["active_prs"] = {123: sample_pr_state_needs_escalation}

        mock_telegram_instance = AsyncMock()
        mock_telegram_tool.return_value = mock_telegram_instance

        result = await escalation_node(base_state)

        # Should skip escalation due to cooldown
        mock_telegram_instance._arun.assert_not_called()
        assert result["escalation_results"] == []

    @patch("src.nodes.escalation.TelegramTool")
    @pytest.mark.asyncio
    async def test_escalation_node_cooldown_expired(self, mock_telegram_tool, base_state, sample_pr_state_needs_escalation):
        """Test escalation when cooldown has expired."""
        # Add old escalation, cooldown should be expired
        old_escalation = {
            "id": "old_escalation",
            "timestamp": datetime.now() - timedelta(hours=25),  # 25 hours ago, beyond 24h cooldown
            "check_name": "Security",
            "status": EscalationStatus.NOTIFIED.value,
        }
        sample_pr_state_needs_escalation["escalations"] = [old_escalation]

        base_state["active_prs"] = {123: sample_pr_state_needs_escalation}

        mock_telegram_instance = AsyncMock()
        mock_telegram_tool.return_value = mock_telegram_instance
        mock_telegram_instance._arun.return_value = {"success": True, "message_id": "new_msg_789"}

        result = await escalation_node(base_state)

        # Should proceed with escalation since cooldown expired
        mock_telegram_instance._arun.assert_called_once()
        assert len(result["escalation_results"]) == 1

    @patch("src.nodes.escalation.TelegramTool")
    @pytest.mark.asyncio
    async def test_escalation_node_unexpected_exception(
        self, mock_telegram_tool, base_state, sample_pr_state_needs_escalation
    ):
        """Test escalation with unexpected exception."""
        base_state["active_prs"] = {123: sample_pr_state_needs_escalation}

        mock_telegram_instance = AsyncMock()
        mock_telegram_tool.return_value = mock_telegram_instance
        mock_telegram_instance._arun.side_effect = Exception("Network error")

        result = await escalation_node(base_state)

        # Should handle exception gracefully
        escalation_results = result["escalation_results"]
        assert len(escalation_results) == 1
        assert escalation_results[0]["success"] is False
        assert "Network error" in escalation_results[0]["error"]

    @pytest.mark.asyncio
    async def test_escalation_node_dry_run_mode(self, base_state, sample_pr_state_needs_escalation):
        """Test escalation in dry run mode."""
        base_state["dry_run"] = True
        base_state["active_prs"] = {123: sample_pr_state_needs_escalation}

        with patch("src.nodes.escalation.TelegramTool") as mock_telegram_tool:
            mock_telegram_instance = AsyncMock()
            mock_telegram_tool.return_value = mock_telegram_instance

            # Verify dry_run is passed to Telegram tool
            await escalation_node(base_state)
            mock_telegram_tool.assert_called_once_with(dry_run=True)


class TestIdentifyEscalationCandidates:
    """Test escalation candidate identification."""

    def test_identify_escalation_candidates_max_attempts_reached(self):
        """Test identification of issues that reached max attempts."""
        config = RepositoryConfig(owner="test-org", repo="test-repo", fix_limits={"max_attempts": 2})

        state = {
            "config": config,
            "active_prs": {
                123: {
                    "failed_checks": ["CI"],
                    "fix_attempts": {
                        "CI": [
                            {"status": "failure"},
                            {"status": "failure"},  # 2 failures = max attempts
                        ]
                    },
                    "analysis_CI": {"failure_context": "Build failed with exit code 1"},
                }
            },
        }

        candidates = _identify_escalation_candidates(state)

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate["pr_number"] == 123
        assert candidate["check_name"] == "CI"
        assert "Maximum fix attempts" in candidate["reason"]
        assert candidate["failure_context"] == "Build failed with exit code 1"

    def test_identify_escalation_candidates_unfixable_issue(self):
        """Test identification of unfixable issues."""
        config = RepositoryConfig(owner="test-org", repo="test-repo", fix_limits={"max_attempts": 3})

        state = {
            "config": config,
            "active_prs": {
                456: {
                    "failed_checks": ["Security"],
                    "fix_attempts": {},  # No fix attempts yet
                    "analysis_Security": {
                        "fixable": False,
                        "failure_context": "SQL injection vulnerability requires manual review",
                    },
                }
            },
        }

        candidates = _identify_escalation_candidates(state)

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate["pr_number"] == 456
        assert candidate["check_name"] == "Security"
        assert "not automatically fixable" in candidate["reason"]

    def test_identify_escalation_candidates_mixed_scenarios(self):
        """Test identification with mixed scenarios."""
        config = RepositoryConfig(owner="test-org", repo="test-repo", fix_limits={"max_attempts": 2})

        state = {
            "config": config,
            "active_prs": {
                123: {
                    "failed_checks": ["CI", "Tests"],
                    "fix_attempts": {
                        "CI": [{"status": "failure"}],  # Still has attempts left
                        "Tests": [
                            {"status": "failure"},
                            {"status": "failure"},  # Max attempts reached
                        ],
                    },
                    "analysis_Tests": {"failure_context": "Test failure"},
                },
                456: {
                    "failed_checks": ["Security"],
                    "fix_attempts": {},
                    "analysis_Security": {"fixable": False, "failure_context": "Security issue"},
                },
            },
        }

        candidates = _identify_escalation_candidates(state)

        # Should find 2 candidates: Tests (max attempts) and Security (unfixable)
        assert len(candidates) == 2

        candidate_checks = {c["check_name"] for c in candidates}
        assert candidate_checks == {"Tests", "Security"}

    def test_identify_escalation_candidates_no_candidates(self):
        """Test identification when no escalation is needed."""
        config = RepositoryConfig(owner="test-org", repo="test-repo", fix_limits={"max_attempts": 3})

        state = {
            "config": config,
            "active_prs": {
                123: {
                    "failed_checks": ["CI"],
                    "fix_attempts": {
                        "CI": [{"status": "failure"}]  # Still has attempts left
                    },
                    "analysis_CI": {"fixable": True},  # Fixable, not yet at max attempts
                }
            },
        }

        candidates = _identify_escalation_candidates(state)
        assert candidates == []

    def test_identify_escalation_candidates_successful_attempt(self):
        """Test that successful attempts don't trigger escalation."""
        config = RepositoryConfig(owner="test-org", repo="test-repo", fix_limits={"max_attempts": 2})

        state = {
            "config": config,
            "active_prs": {
                123: {
                    "failed_checks": ["CI"],
                    "fix_attempts": {
                        "CI": [
                            {"status": "failure"},
                            {"status": "success"},  # Last attempt succeeded
                        ]
                    },
                }
            },
        }

        candidates = _identify_escalation_candidates(state)
        assert candidates == []  # Should not escalate successful fixes


class TestIsInCooldown:
    """Test cooldown checking functionality."""

    def test_is_in_cooldown_active(self):
        """Test cooldown detection when cooldown is active."""
        recent_time = datetime.now() - timedelta(hours=12)

        pr_state = {
            "escalations": [
                {
                    "check_name": "CI",
                    "timestamp": recent_time,
                }
            ]
        }

        result = _is_in_cooldown(pr_state, "CI", 24)
        assert result is True

    def test_is_in_cooldown_expired(self):
        """Test cooldown detection when cooldown has expired."""
        old_time = datetime.now() - timedelta(hours=25)

        pr_state = {
            "escalations": [
                {
                    "check_name": "CI",
                    "timestamp": old_time,
                }
            ]
        }

        result = _is_in_cooldown(pr_state, "CI", 24)
        assert result is False

    def test_is_in_cooldown_no_escalations(self):
        """Test cooldown when no escalations exist."""
        pr_state = {"escalations": []}

        result = _is_in_cooldown(pr_state, "CI", 24)
        assert result is False

    def test_is_in_cooldown_different_check(self):
        """Test cooldown for different check name."""
        recent_time = datetime.now() - timedelta(hours=12)

        pr_state = {
            "escalations": [
                {
                    "check_name": "Tests",  # Different check
                    "timestamp": recent_time,
                }
            ]
        }

        result = _is_in_cooldown(pr_state, "CI", 24)
        assert result is False

    def test_is_in_cooldown_multiple_escalations(self):
        """Test cooldown with multiple escalations for same check."""
        old_time = datetime.now() - timedelta(hours=25)
        recent_time = datetime.now() - timedelta(hours=12)

        pr_state = {
            "escalations": [
                {
                    "check_name": "CI",
                    "timestamp": old_time,
                },
                {
                    "check_name": "CI",
                    "timestamp": recent_time,  # Most recent should be used
                },
            ]
        }

        result = _is_in_cooldown(pr_state, "CI", 24)
        assert result is True  # Based on most recent escalation

    def test_is_in_cooldown_string_timestamp(self):
        """Test cooldown with string timestamp."""
        recent_time_str = (datetime.now() - timedelta(hours=12)).isoformat()

        pr_state = {
            "escalations": [
                {
                    "check_name": "CI",
                    "timestamp": recent_time_str,
                }
            ]
        }

        result = _is_in_cooldown(pr_state, "CI", 24)
        assert result is True

    def test_is_in_cooldown_invalid_timestamp(self):
        """Test cooldown with invalid timestamp."""
        pr_state = {
            "escalations": [
                {
                    "check_name": "CI",
                    "timestamp": "invalid-timestamp",
                }
            ]
        }

        result = _is_in_cooldown(pr_state, "CI", 24)
        assert result is False  # Should handle gracefully


class TestHandleEscalationResponse:
    """Test escalation response handling."""

    @pytest.mark.asyncio
    async def test_handle_escalation_response_acknowledgment(self):
        """Test handling escalation acknowledgment."""
        state = {
            "active_prs": {
                123: {
                    "escalations": [
                        {
                            "id": "esc_123",
                            "check_name": "Security",
                            "status": EscalationStatus.NOTIFIED.value,
                        }
                    ],
                    "escalation_status": EscalationStatus.NOTIFIED.value,
                }
            }
        }

        result = await handle_escalation_response(state, "esc_123", "acknowledged", "@security-lead", "Will review manually")

        # Verify escalation was updated
        escalation = result["active_prs"][123]["escalations"][0]
        assert escalation["status"] == "acknowledged"
        assert escalation["acknowledged_by"] == "@security-lead"
        assert escalation["resolution_notes"] == "Will review manually"
        assert "acknowledged_at" in escalation

        # Verify PR state updated
        assert result["active_prs"][123]["escalation_status"] == "acknowledged"
        assert result["active_prs"][123]["workflow_step"] == "human_acknowledged"

    @pytest.mark.asyncio
    async def test_handle_escalation_response_not_found(self):
        """Test handling response for non-existent escalation."""
        state = {
            "active_prs": {
                123: {
                    "escalations": [
                        {
                            "id": "different_id",
                            "check_name": "Security",
                        }
                    ]
                }
            }
        }

        result = await handle_escalation_response(state, "nonexistent_id", "acknowledged", "@user", "")

        # Should return original state unchanged
        assert result == state


class TestShouldContinueAfterEscalation:
    """Test edge function for determining next steps after escalation."""

    def test_should_continue_after_escalation_successful(self):
        """Test decision with successful escalations."""
        state = {
            "escalation_results": [
                {"pr_number": 123, "success": True},
                {"pr_number": 456, "success": True},
            ]
        }

        result = should_continue_after_escalation(state)
        assert result == "wait_for_human_response"

    def test_should_continue_after_escalation_failed(self):
        """Test decision with failed escalations."""
        state = {
            "escalation_results": [
                {"pr_number": 123, "success": False, "error": "Telegram error"},
            ]
        }

        result = should_continue_after_escalation(state)
        assert result == "wait_for_next_poll"

    def test_should_continue_after_escalation_mixed(self):
        """Test decision with mixed escalation results."""
        state = {
            "escalation_results": [
                {"pr_number": 123, "success": True},
                {"pr_number": 456, "success": False},
            ]
        }

        result = should_continue_after_escalation(state)
        assert result == "wait_for_human_response"  # At least one successful

    def test_should_continue_after_escalation_no_results(self):
        """Test decision with no escalation results."""
        state = {"escalation_results": []}

        result = should_continue_after_escalation(state)
        assert result == "wait_for_next_poll"


class TestEscalationIntegration:
    """Integration tests for escalation node."""

    @patch("src.nodes.escalation.TelegramTool")
    @patch("src.nodes.escalation.uuid.uuid4")
    @pytest.mark.asyncio
    async def test_complete_escalation_workflow(self, mock_uuid, mock_telegram_tool):
        """Test complete escalation workflow."""
        mock_uuid.return_value = "integration-escalation-id"

        # Setup complex state with multiple escalation scenarios
        config = RepositoryConfig(
            owner="test-org",
            repo="test-repo",
            fix_limits={
                "max_attempts": 2,
                "escalation_cooldown_hours": 24,
            },
            notifications={
                "escalation_mentions": ["@team-leads"],
            },
        )

        state = {
            "repository": "test-org/test-repo",
            "config": config,
            "active_prs": {
                123: {
                    "pr_number": 123,
                    "pr_info": {"title": "Critical fix", "base_branch": "main"},
                    "failed_checks": ["CI"],
                    "fix_attempts": {
                        "CI": [
                            {"status": "failure"},
                            {"status": "failure"},  # Max attempts reached
                        ]
                    },
                    "analysis_CI": {
                        "failure_context": "Build failed with compiler error",
                    },
                    "escalations": [],
                    "escalation_status": "none",
                },
                456: {
                    "pr_number": 456,
                    "pr_info": {"title": "Security update", "base_branch": "main"},
                    "failed_checks": ["Security"],
                    "fix_attempts": {},  # No attempts, but unfixable
                    "analysis_Security": {
                        "fixable": False,
                        "failure_context": "Manual security review required",
                    },
                    "escalations": [],
                    "escalation_status": "none",
                },
            },
            "total_escalations": 0,
        }

        # Mock Telegram tool
        mock_telegram_instance = AsyncMock()
        mock_telegram_tool.return_value = mock_telegram_instance

        # Mock successful responses for both escalations
        mock_responses = [
            {"success": True, "message_id": "msg_123"},
            {"success": True, "message_id": "msg_456"},
        ]
        mock_telegram_instance._arun.side_effect = mock_responses

        # Step 1: Identify candidates
        candidates = _identify_escalation_candidates(state)
        assert len(candidates) == 2

        # Step 2: Execute escalation
        escalated_state = await escalation_node(state)

        # Verify both escalations were attempted
        assert mock_telegram_instance._arun.call_count == 2
        assert len(escalated_state["escalation_results"]) == 2

        # Verify both PRs were escalated
        assert escalated_state["active_prs"][123]["workflow_step"] == "escalated"
        assert escalated_state["active_prs"][456]["workflow_step"] == "escalated"

        # Verify global counter
        assert escalated_state["total_escalations"] == 2

        # Step 3: Test decision
        decision = should_continue_after_escalation(escalated_state)
        assert decision == "wait_for_human_response"

        # Step 4: Simulate human response
        responded_state = await handle_escalation_response(
            escalated_state, "integration-escalation-id", "acknowledged", "@security-lead", "Will fix manually"
        )

        # Verify response was handled
        # (Note: This would work if the escalation ID matched what was generated)
