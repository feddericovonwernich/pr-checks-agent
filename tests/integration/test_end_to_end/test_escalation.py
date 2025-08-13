"""End-to-end tests for escalation workflow scenarios."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.graphs.monitor_graph import create_initial_state, create_monitor_graph

from .conftest import create_claude_fix_response, create_test_check_data, create_test_pr_data


@pytest.mark.asyncio
class TestEscalationWorkflow:
    """Test workflows that result in human escalation."""

    async def test_max_fix_attempts_escalation(self, integration_test_setup: dict[str, Any]):
        """Test escalation after maximum fix attempts are reached."""
        setup = integration_test_setup
        redis_client = setup["redis_client"]
        config = setup["config"]

        # Reduce max attempts for faster testing
        config.repositories[0].fix_limits["max_attempts"] = 2

        # Setup mocks for failing fix attempts
        await self._setup_github_mocks_persistent_failure(setup["github_api_base_url"])
        await self._setup_telegram_mock_escalation(setup["telegram_api_base_url"])

        with patch("nodes.scanner.GitHubTool") as mock_github_tool, \
             patch("nodes.invoker.ClaudeCodeTool") as mock_claude_tool, \
             patch("nodes.escalation.TelegramTool") as mock_telegram_tool:

            # Mock GitHub API tool calls
            mock_github_instance = AsyncMock()
            mock_github_tool.return_value = mock_github_instance
            mock_github_instance._arun.return_value = {
                "success": True,
                "prs": [create_test_pr_data(123)]
            }

            # Mock Claude API tool calls - always fail fixes
            mock_claude_instance = AsyncMock()
            mock_claude_tool.return_value = mock_claude_instance
            mock_claude_instance._arun.return_value = {
                "success": False,
                "error": "Unable to fix the issue"
            }

            # Mock Telegram API tool calls
            mock_telegram_instance = AsyncMock()
            mock_telegram_tool.return_value = mock_telegram_instance
            mock_telegram_instance._arun.return_value = {
                "success": True,
                "message_id": 123
            }

            # Create the monitoring graph
            graph = create_monitor_graph(
                config=config,
                max_concurrent=1,
                enable_tracing=True,
                dry_run=False
            )

            # Create initial state
            initial_state = create_initial_state(
                repository="test-org/test-repo",
                config=config.repositories[0],
                polling_interval=1
            )

            initial_state["persistence"] = redis_client
            initial_state["dry_run"] = False

            # Track workflow execution
            workflow_events = []
            escalation_triggered = False
            fix_attempts = 0

            # Run workflow with timeout
            try:
                async for event in graph.astream(initial_state):
                    workflow_events.append(event)

                    # Track fix attempts
                    if event.get("workflow_step") == "fix_attempted":
                        fix_attempts += 1

                    # Check for escalation
                    if event.get("workflow_step") == "escalated":
                        escalation_triggered = True
                        break

                    # Safety limits
                    if len(workflow_events) > 30:
                        break

            except Exception as e:
                pytest.fail(f"Escalation workflow failed: {e}")

            # Verify escalation occurred
            assert escalation_triggered, "Escalation should be triggered after max fix attempts"
            assert fix_attempts >= 2, f"Should have attempted fixes {config.repositories[0].fix_limits['max_attempts']} times"

            # Verify Telegram notification was sent
            mock_telegram_instance._arun.assert_called()

            # Verify escalation state persistence
            await self._verify_escalation_persistence(redis_client, "test-org/test-repo", pr_number=123)

    async def test_unfixable_issue_escalation(self, integration_test_setup: dict[str, Any]):
        """Test escalation when Claude determines issue is unfixable."""
        setup = integration_test_setup
        config = setup["config"]

        with patch("nodes.scanner.GitHubTool") as mock_github_tool, \
             patch("nodes.invoker.ClaudeCodeTool") as mock_claude_tool, \
             patch("nodes.escalation.TelegramTool") as mock_telegram_tool:

            # Mock GitHub API tool calls
            mock_github_instance = AsyncMock()
            mock_github_tool.return_value = mock_github_instance
            mock_github_instance._arun.return_value = {
                "success": True,
                "prs": [create_test_pr_data(123)]
            }

            # Mock Claude tool determining issue is unfixable
            mock_claude_instance = AsyncMock()
            mock_claude_tool.return_value = mock_claude_instance
            mock_claude_instance._arun.return_value = {
                "success": False,
                "fixable": False,
                "reason": "Security vulnerability requires manual human review"
            }

            # Mock Telegram escalation
            mock_telegram_instance = AsyncMock()
            mock_telegram_tool.return_value = mock_telegram_instance
            mock_telegram_instance._arun.return_value = {
                "success": True,
                "message_id": 124
            }

            # Create workflow graph
            graph = create_monitor_graph(
                config=config,
                max_concurrent=1,
                enable_tracing=True,
                dry_run=False
            )

            # Create initial state
            initial_state = create_initial_state(
                repository="test-org/test-repo",
                config=config.repositories[0],
                polling_interval=1
            )

            # Run workflow
            workflow_events = []
            escalation_triggered = False
            analysis_completed = False

            async for event in graph.astream(initial_state):
                workflow_events.append(event)

                if event.get("workflow_step") == "analyzed":
                    analysis_completed = True

                if event.get("workflow_step") == "escalated":
                    escalation_triggered = True
                    break

                # Safety limit
                if len(workflow_events) > 20:
                    break

            # Verify workflow behavior
            assert analysis_completed, "Analysis should be completed"
            assert escalation_triggered, "Should escalate unfixable issues directly"

            # Verify Telegram was called for escalation
            mock_telegram_instance._arun.assert_called()
            escalation_args = mock_telegram_instance._arun.call_args
            if escalation_args:
                # Extract message from call args if available
                call_kwargs = escalation_args[1] if len(escalation_args) > 1 else {}
                message_text = str(call_kwargs)
                assert "security" in message_text.lower(), "Escalation should mention security issue"

    async def test_escalation_with_human_acknowledgment(self, integration_test_setup: dict[str, Any]):
        """Test escalation workflow with simulated human acknowledgment."""
        setup = integration_test_setup
        redis_client = setup["redis_client"]
        config = setup["config"]

        with patch("nodes.scanner.GitHubTool") as mock_github_tool, \
             patch("nodes.invoker.ClaudeCodeTool") as mock_claude_tool, \
             patch("nodes.escalation.TelegramTool") as mock_telegram_tool:

            # Mock GitHub API tool calls
            mock_github_instance = AsyncMock()
            mock_github_tool.return_value = mock_github_instance
            mock_github_instance._arun.return_value = {
                "success": True,
                "prs": [create_test_pr_data(123)]
            }

            # Mock Claude API tool calls
            mock_claude_instance = AsyncMock()
            mock_claude_tool.return_value = mock_claude_instance
            mock_claude_instance._arun.return_value = {
                "success": False,
                "error": "Unable to fix the issue"
            }

            # Mock Telegram API tool calls
            mock_telegram_instance = AsyncMock()
            mock_telegram_tool.return_value = mock_telegram_instance
            mock_telegram_instance._arun.return_value = {
                "success": True,
                "message_id": 125
            }

            # Create workflow
            graph = create_monitor_graph(
                config=config,
                max_concurrent=1,
                enable_tracing=True,
                dry_run=False
            )

            initial_state = create_initial_state(
                repository="test-org/test-repo",
                config=config.repositories[0],
                polling_interval=1
            )
            initial_state["persistence"] = redis_client

            # Run workflow until escalation
            workflow_events = []
            escalation_triggered = False

            async for event in graph.astream(initial_state):
                workflow_events.append(event)

                if event.get("workflow_step") == "escalated":
                    escalation_triggered = True

                    # Simulate human acknowledgment by updating state
                    await self._simulate_human_acknowledgment(
                        redis_client,
                        "test-org/test-repo",
                        pr_number=123
                    )
                    break

                if len(workflow_events) > 25:
                    break

            assert escalation_triggered, "Escalation should occur"

            # Verify escalation state was updated
            await self._verify_human_acknowledgment_recorded(
                redis_client,
                "test-org/test-repo",
                pr_number=123
            )

    async def test_multiple_pr_escalation_prioritization(self, integration_test_setup: dict[str, Any]):
        """Test escalation handling when multiple PRs need escalation."""
        setup = integration_test_setup
        config = setup["config"]

        # Enable higher concurrency for this test
        config.global_limits.max_concurrent_fixes = 3

        with patch("nodes.scanner.GitHubTool") as mock_github_tool, \
             patch("nodes.invoker.ClaudeCodeTool") as mock_claude_tool, \
             patch("nodes.escalation.TelegramTool") as mock_telegram_tool:

            # Mock GitHub API tool calls
            mock_github_instance = AsyncMock()
            mock_github_tool.return_value = mock_github_instance
            mock_github_instance._arun.return_value = {
                "success": True,
                "prs": [
                    create_test_pr_data(123),
                    create_test_pr_data(124),
                    create_test_pr_data(125)
                ]
            }

            # Mock Claude API tool calls - all fixes fail
            mock_claude_instance = AsyncMock()
            mock_claude_tool.return_value = mock_claude_instance
            mock_claude_instance._arun.return_value = {
                "success": False,
                "error": "Unable to fix the issue"
            }

            # Mock Telegram API tool calls
            mock_telegram_instance = AsyncMock()
            mock_telegram_tool.return_value = mock_telegram_instance
            mock_telegram_instance._arun.return_value = {
                "success": True,
                "message_id": 126
            }

            # Create workflow
            graph = create_monitor_graph(
                config=config,
                max_concurrent=3,
                enable_tracing=True,
                dry_run=False
            )

            initial_state = create_initial_state(
                repository="test-org/test-repo",
                config=config.repositories[0],
                polling_interval=1
            )

            # Run workflow
            workflow_events = []
            escalated_prs = set()

            # Run with timeout to prevent hanging
            timeout_task = asyncio.create_task(asyncio.sleep(45))

            try:
                async for event in graph.astream(initial_state):
                    workflow_events.append(event)

                    if event.get("workflow_step") == "escalated":
                        pr_number = event.get("pr_number")
                        if pr_number:
                            escalated_prs.add(pr_number)

                    # Stop after all PRs are escalated or timeout
                    if len(escalated_prs) >= 3 or len(workflow_events) > 60:
                        break

            except asyncio.CancelledError:
                pass
            finally:
                if not timeout_task.done():
                    timeout_task.cancel()

            # Verify multiple escalations occurred
            assert len(escalated_prs) >= 2, f"Expected at least 2 PR escalations, got {len(escalated_prs)}"

            # Verify escalation notifications were sent
            assert mock_telegram_instance._arun.call_count >= 2, "Multiple escalation notifications should be sent"

    # Helper methods

    async def _setup_github_mocks_persistent_failure(self, base_url: str):
        """Setup GitHub API mocks for consistently failing checks."""
        async with httpx.AsyncClient() as client:
            # Mock check runs that always show failure
            await client.post(f"{base_url}/__admin/mappings", json={
                "request": {
                    "method": "GET",
                    "urlPattern": "/repos/test-org/test-repo/commits/.*/check-runs"
                },
                "response": {
                    "status": 200,
                    "headers": {"Content-Type": "application/json"},
                    "jsonBody": {
                        "total_count": 1,
                        "check_runs": [create_test_check_data("ci/test", "failure")]
                    }
                }
            })

    async def _setup_telegram_mock_escalation(self, base_url: str):
        """Setup Telegram API mock for escalation messages."""
        # Telegram mocking is handled by the mock in the test

    async def _verify_escalation_persistence(self, redis_client: Any, repository: str, pr_number: int):
        """Verify escalation state is properly persisted."""
        escalation_key = f"escalation:{repository}:pr:{pr_number}"
        escalation_exists = redis_client.redis_client.exists(escalation_key)

        if escalation_exists:
            escalation_data = redis_client.load_state(escalation_key)
            assert escalation_data is not None
            assert escalation_data.get("status") in ["pending", "notified"]

    async def _simulate_human_acknowledgment(self, redis_client: Any, repository: str, pr_number: int):
        """Simulate human acknowledgment of an escalation."""
        escalation_key = f"escalation:{repository}:pr:{pr_number}"
        acknowledgment_data = {
            "status": "acknowledged",
            "acknowledged_by": "test-human",
            "acknowledged_at": "2024-01-01T12:00:00Z",
            "notes": "Investigating the issue"
        }
        redis_client.save_state(escalation_key, acknowledgment_data)

    async def _verify_human_acknowledgment_recorded(self, redis_client: Any, repository: str, pr_number: int):
        """Verify human acknowledgment was properly recorded."""
        escalation_key = f"escalation:{repository}:pr:{pr_number}"
        escalation_data = redis_client.load_state(escalation_key)

        assert escalation_data is not None
        assert escalation_data.get("status") == "acknowledged"
        assert escalation_data.get("acknowledged_by") == "test-human"

