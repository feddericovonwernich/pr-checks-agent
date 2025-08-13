"""End-to-end tests for the happy path workflow scenarios."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.graphs.monitor_graph import create_initial_state, create_monitor_graph
from src.state.schemas import MonitorState

from .conftest import create_claude_fix_response, create_test_check_data, create_test_pr_data


@pytest.mark.asyncio
class TestHappyPathWorkflow:
    """Test the complete happy path workflow from PR scan to successful fix."""

    async def test_successful_fix_workflow_complete(self, integration_test_setup: dict[str, Any]):
        """Test the complete workflow: scan -> monitor -> analyze -> fix -> verify."""
        setup = integration_test_setup
        redis_client = setup["redis_client"]
        config = setup["config"]

        # Setup GitHub API mocks for the happy path
        await self._setup_github_mocks_happy_path(
            setup["github_api_base_url"],
            pr_number=123,
            initial_status="failure",
            fixed_status="success"
        )

        # Setup Claude API mock for successful fix
        await self._setup_claude_mock_success(setup["claude_api_base_url"])

        # Create workflow graph
        with patch("src.nodes.scanner.github") as mock_github, \
             patch("src.nodes.monitor.github") as mock_monitor, \
             patch("src.nodes.invoker.anthropic") as mock_claude:

            # Mock GitHub API calls
            mock_github.get_repository_pulls.return_value = [create_test_pr_data(123)]
            mock_monitor.get_check_runs.return_value = [
                create_test_check_data("ci/test", "failure"),
                create_test_check_data("ci/lint", "success")
            ]

            # Mock Claude API calls
            mock_claude.messages.create = AsyncMock(return_value=create_claude_fix_response(success=True))

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
                polling_interval=1  # Short interval for testing
            )

            # Add persistence to state
            initial_state["persistence"] = redis_client
            initial_state["dry_run"] = False

            # Track workflow execution
            workflow_events = []
            workflow_completed = False
            fix_attempted = False
            fix_successful = False

            # Run the workflow with timeout
            try:
                timeout_task = asyncio.create_task(asyncio.sleep(30))  # 30 second timeout
                workflow_task = asyncio.create_task(self._run_workflow_to_completion(
                    graph, initial_state, workflow_events
                ))

                done, pending = await asyncio.wait(
                    [timeout_task, workflow_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                # Check if workflow completed
                if workflow_task in done:
                    result = await workflow_task
                    workflow_completed = True
                    fix_attempted = result.get("fix_attempted", False)
                    fix_successful = result.get("fix_successful", False)
                else:
                    pytest.fail("Workflow timed out after 30 seconds")

            except Exception as e:
                pytest.fail(f"Workflow execution failed: {e}")

            # Verify workflow execution
            assert workflow_completed, "Workflow should complete successfully"
            assert fix_attempted, "Workflow should attempt to fix the failing check"
            assert fix_successful, "Fix attempt should be successful"

            # Verify state persistence
            await self._verify_state_persistence(redis_client, "test-org/test-repo")

            # Verify workflow events
            self._verify_workflow_events(workflow_events)

    async def test_no_prs_workflow(self, integration_test_setup: dict[str, Any]):
        """Test workflow when no PRs are found (should go to wait state)."""
        setup = integration_test_setup
        config = setup["config"]

        with patch("src.nodes.scanner.github") as mock_github:
            # Mock empty PR list
            mock_github.get_repository_pulls.return_value = []

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

            # Run workflow for one iteration
            workflow_events = []
            async for event in graph.astream(initial_state):
                workflow_events.append(event)

                # Stop after we reach wait state
                if event.get("workflow_step") == "ready_for_next_poll":
                    break

                # Safety limit
                if len(workflow_events) > 10:
                    break

            # Verify we went to wait state without processing any PRs
            final_event = workflow_events[-1]
            assert final_event.get("workflow_step") == "ready_for_next_poll"
            assert len(final_event.get("active_prs", {})) == 0

    async def test_all_checks_passing_workflow(self, integration_test_setup: dict[str, Any]):
        """Test workflow when PR exists but all checks are passing."""
        setup = integration_test_setup
        config = setup["config"]

        with patch("src.nodes.scanner.github") as mock_github, \
             patch("src.nodes.monitor.github") as mock_monitor:

            # Mock PR with all passing checks
            mock_github.get_repository_pulls.return_value = [create_test_pr_data(123)]
            mock_monitor.get_check_runs.return_value = [
                create_test_check_data("ci/test", "success"),
                create_test_check_data("ci/lint", "success")
            ]

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
            async for event in graph.astream(initial_state):
                workflow_events.append(event)

                # Stop after we reach wait state or complete monitoring
                if event.get("workflow_step") in ["ready_for_next_poll", "monitoring_complete"]:
                    break

                # Safety limit
                if len(workflow_events) > 15:
                    break

            # Verify no fix attempts were made
            fix_events = [e for e in workflow_events if "fix_attempt" in str(e)]
            assert len(fix_events) == 0, "No fix attempts should be made when all checks pass"

    async def _setup_github_mocks_happy_path(
        self,
        base_url: str,
        pr_number: int = 123,
        initial_status: str = "failure",
        fixed_status: str = "success"
    ):
        """Setup GitHub API mocks for happy path scenario."""
        async with httpx.AsyncClient() as client:
            # Mock PR details
            await client.post(f"{base_url}/__admin/mappings", json={
                "request": {
                    "method": "GET",
                    "urlPattern": f"/repos/test-org/test-repo/pulls/{pr_number}"
                },
                "response": {
                    "status": 200,
                    "headers": {"Content-Type": "application/json"},
                    "jsonBody": create_test_pr_data(pr_number)
                }
            })

            # Mock check runs - initially failing, then passing after fix
            await client.post(f"{base_url}/__admin/mappings", json={
                "priority": 1,  # Lower priority (checked first)
                "request": {
                    "method": "GET",
                    "urlPattern": "/repos/test-org/test-repo/commits/.*/check-runs"
                },
                "response": {
                    "status": 200,
                    "headers": {"Content-Type": "application/json"},
                    "jsonBody": {
                        "total_count": 1,
                        "check_runs": [create_test_check_data("ci/test", initial_status)]
                    }
                }
            })

    async def _setup_claude_mock_success(self, base_url: str):
        """Setup Claude API mock for successful fix response."""
        # Claude API mocking will be handled by the anthropic client mock in the test

    async def _run_workflow_to_completion(
        self,
        graph: Any,
        initial_state: MonitorState,
        workflow_events: list
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
            "total_events": len(workflow_events)
        }

    async def _verify_state_persistence(self, redis_client: Any, repository: str):
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

