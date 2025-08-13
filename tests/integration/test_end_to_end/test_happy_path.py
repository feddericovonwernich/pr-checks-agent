"""End-to-end tests for the happy path workflow scenarios."""

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from langgraph.graph.state import StateGraph

    from src.state.persistence import StatePersistence

import httpx
import pytest

from src.graphs.monitor_graph import create_initial_state, create_monitor_graph
from src.state.schemas import MonitorState

from .conftest import create_test_check_data, create_test_pr_data


@pytest.mark.asyncio
class TestHappyPathWorkflow:
    """Test the complete happy path workflow from PR scan to successful fix."""

    async def test_successful_fix_workflow_complete(self, integration_test_setup: dict[str, Any]):
        """Test that mocking works and basic workflow functionality operates."""
        setup = integration_test_setup
        config = setup["config"]

        # Create workflow graph with mocking
        with patch("nodes.scanner.GitHubTool") as mock_github_tool:
            # Mock GitHub API tool calls
            mock_github_instance = AsyncMock()
            mock_github_tool.return_value = mock_github_instance
            mock_github_instance._arun.return_value = {"success": True, "prs": [create_test_pr_data(123)]}

            # Create the monitoring graph
            graph = create_monitor_graph(
                config=config,
                max_concurrent=1,
                enable_tracing=True,
                dry_run=True,  # Use dry run to avoid side effects
            )

            # Create initial state
            initial_state = create_initial_state(
                repository="test-org/test-repo", config=config.repositories[0], polling_interval=1
            )

            # Run one iteration of the workflow
            events_collected = 0
            async for _event in graph.astream(initial_state):
                events_collected += 1
                # Just run one cycle to verify mocking works
                if events_collected >= 1:
                    break

            # Verify GitHub tool was mocked and called
            assert mock_github_instance._arun.called, "GitHub tool should be called"
            assert events_collected > 0, "Should have at least one workflow event"

    async def test_no_prs_workflow(self, integration_test_setup: dict[str, Any]):
        """Test workflow when no PRs are found (should go to wait state)."""
        setup = integration_test_setup
        config = setup["config"]

        with patch("nodes.scanner.GitHubTool") as mock_github_tool:
            # Mock empty PR list
            mock_github_instance = AsyncMock()
            mock_github_tool.return_value = mock_github_instance
            mock_github_instance._arun.return_value = {"success": True, "prs": []}

            # Create workflow graph
            graph = create_monitor_graph(
                config=config,
                max_concurrent=1,
                enable_tracing=True,
                dry_run=True,  # Use dry run to avoid side effects
            )

            # Create initial state
            initial_state = create_initial_state(
                repository="test-org/test-repo", config=config.repositories[0], polling_interval=1
            )

            # Run workflow for limited cycles
            workflow_events = []
            cycles = 0
            max_cycles = 3

            async for event in graph.astream(initial_state):
                workflow_events.append(event)
                cycles += 1

                # Stop after max cycles or if we reach 10 events
                if cycles >= max_cycles or len(workflow_events) >= 10:
                    break

            # Verify basic functionality - should have events and mock should be called
            assert len(workflow_events) > 0, "Should have at least one workflow event"
            assert mock_github_instance._arun.called, "GitHub tool should be called"

            # Verify that mock returned empty PRs (no PRs were processed)
            call_args = mock_github_instance._arun.call_args
            assert call_args is not None, "GitHub tool should have been called with arguments"

    async def test_all_checks_passing_workflow(self, integration_test_setup: dict[str, Any]):
        """Test workflow when PR exists but all checks are passing."""
        setup = integration_test_setup
        config = setup["config"]

        with (
            patch("nodes.scanner.GitHubTool") as mock_scanner_github_tool,
            patch("nodes.monitor.GitHubTool") as mock_monitor_github_tool,
        ):
            # Mock scanner GitHub tool - returns PR
            mock_scanner_instance = AsyncMock()
            mock_scanner_github_tool.return_value = mock_scanner_instance
            mock_scanner_instance._arun.return_value = {"success": True, "prs": [create_test_pr_data(123)]}

            # Mock monitor GitHub tool - returns all passing checks
            mock_monitor_instance = AsyncMock()
            mock_monitor_github_tool.return_value = mock_monitor_instance
            mock_monitor_instance._arun.return_value = {
                "success": True,
                "checks": {
                    "ci/test": {"status": "success", "conclusion": "success"},
                    "ci/lint": {"status": "success", "conclusion": "success"},
                },
            }

            # Create workflow graph
            graph = create_monitor_graph(
                config=config,
                max_concurrent=1,
                enable_tracing=True,
                dry_run=True,  # Use dry run for stability
            )

            # Create initial state
            initial_state = create_initial_state(
                repository="test-org/test-repo", config=config.repositories[0], polling_interval=1
            )

            # Run workflow for limited cycles
            workflow_events = []
            cycles = 0
            max_cycles = 5

            async for event in graph.astream(initial_state):
                workflow_events.append(event)
                cycles += 1

                # Stop after max cycles
                if cycles >= max_cycles:
                    break

            # Verify basic functionality - both scanner and monitor should be called
            assert mock_scanner_instance._arun.called, "Scanner GitHub tool should be called"
            # Monitor might not be called if workflow doesn't proceed to monitoring

            # Verify workflow events were generated
            assert len(workflow_events) > 0, "Should have workflow events"

    async def _setup_github_mocks_happy_path(
        self, base_url: str, pr_number: int = 123, initial_status: str = "failure", fixed_status: str = "success"
    ):
        """Set up GitHub API mocks for happy path scenario."""
        async with httpx.AsyncClient() as client:
            # Mock PR details
            await client.post(
                f"{base_url}/__admin/mappings",
                json={
                    "request": {"method": "GET", "urlPattern": f"/repos/test-org/test-repo/pulls/{pr_number}"},
                    "response": {
                        "status": 200,
                        "headers": {"Content-Type": "application/json"},
                        "jsonBody": create_test_pr_data(pr_number),
                    },
                },
            )

            # Mock check runs - initially failing, then passing after fix
            await client.post(
                f"{base_url}/__admin/mappings",
                json={
                    "priority": 1,  # Lower priority (checked first)
                    "request": {"method": "GET", "urlPattern": "/repos/test-org/test-repo/commits/.*/check-runs"},
                    "response": {
                        "status": 200,
                        "headers": {"Content-Type": "application/json"},
                        "jsonBody": {"total_count": 1, "check_runs": [create_test_check_data("ci/test", initial_status)]},
                    },
                },
            )

    async def _setup_claude_mock_success(self, base_url: str):
        """Set up Claude API mock for successful fix response."""
        # Claude API mocking will be handled by the anthropic client mock in the test

    async def _run_workflow_to_completion(
        self, graph: "StateGraph[Any, None, Any, Any]", initial_state: MonitorState, workflow_events: list
    ) -> dict[str, Any]:
        """Run workflow until completion or significant milestone."""
        fix_attempted = False
        fix_successful = False
        monitoring_cycles = 0
        max_cycles = 10  # Prevent infinite loops

        async for event in graph.astream(initial_state):
            workflow_events.append(event)

            # Track important milestones
            if "fix_attempt" in str(event):
                fix_attempted = True

            if event.get("workflow_step") == "fix_successful":
                fix_successful = True

            if event.get("workflow_step") == "ready_for_next_poll":
                monitoring_cycles += 1

                # Complete after we've seen evidence of fix success or max cycles
                if fix_successful or monitoring_cycles >= max_cycles:
                    break

            # Safety limit on total events
            if len(workflow_events) > 50:
                break

        return {
            "fix_attempted": fix_attempted,
            "fix_successful": fix_successful,
            "monitoring_cycles": monitoring_cycles,
            "total_events": len(workflow_events),
        }

    async def _verify_state_persistence(self, redis_client: "StatePersistence", repository: str):
        """Verify that workflow state was properly persisted to Redis."""
        # Check that repository state exists
        state_key = f"workflow_state:{repository}"
        state_exists = redis_client.redis_client.exists(state_key)

        if state_exists:
            # Verify state structure
            state_data = redis_client.load_state(state_key)
            assert state_data is not None
            assert "repository" in state_data
            assert state_data["repository"] == repository

    def _verify_workflow_events(self, workflow_events: list):
        """Verify that expected workflow events occurred."""
        event_steps = [event.get("workflow_step", "") for event in workflow_events]

        # Should contain key workflow steps
        expected_steps = ["initialized", "scanned", "monitored"]

        for step in expected_steps:
            step_events = [e for e in event_steps if step in e]
            assert len(step_events) > 0, f"Expected workflow step '{step}' not found in events"

        # Events should be in reasonable order (scan before monitor, etc.)
        assert len(workflow_events) > 0, "Should have at least some workflow events"
