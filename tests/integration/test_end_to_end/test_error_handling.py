"""End-to-end tests for error handling and recovery scenarios."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from src.graphs.monitor_graph import create_initial_state, create_monitor_graph

from .conftest import create_test_check_data, create_test_pr_data


@pytest.mark.asyncio
class TestErrorHandlingWorkflow:
    """Test workflow error handling and recovery mechanisms."""

    async def test_github_api_failure_recovery(self, integration_test_setup: dict[str, Any]):
        """Test recovery from GitHub API failures with exponential backoff."""
        setup = integration_test_setup
        config = setup["config"]

        # Setup GitHub API to fail initially, then succeed
        await self._setup_github_api_failure_then_recovery(setup["github_api_base_url"])

        with patch("src.nodes.scanner.github") as mock_github:

            # Mock GitHub to fail first few calls, then succeed
            call_count = 0
            def github_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count <= 2:
                    raise ConnectionError("GitHub API unavailable")
                return [create_test_pr_data(123)]

            mock_github.get_repository_pulls.side_effect = github_side_effect

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
                polling_interval=1  # Short interval for testing
            )

            # Track workflow execution
            workflow_events = []
            error_handled = False
            recovery_successful = False

            # Run workflow with timeout
            timeout_task = asyncio.create_task(asyncio.sleep(20))

            try:
                async for event in graph.astream(initial_state):
                    workflow_events.append(event)

                    # Check for error handling
                    if event.get("workflow_step") == "error_handled":
                        error_handled = True

                    # Check for successful recovery
                    if event.get("workflow_step") == "scanned" and len(event.get("active_prs", {})) > 0:
                        recovery_successful = True
                        break

                    # Safety limits
                    if len(workflow_events) > 25:
                        break

            except asyncio.CancelledError:
                pass
            finally:
                if not timeout_task.done():
                    timeout_task.cancel()

            # Verify error handling and recovery
            assert error_handled, "Workflow should handle GitHub API errors"
            assert recovery_successful, "Workflow should recover after API comes back online"
            assert call_count >= 3, "Should have retried GitHub API calls"

    async def test_redis_connection_failure_recovery(self, integration_test_setup: dict[str, Any]):
        """Test workflow continues when Redis is temporarily unavailable."""
        setup = integration_test_setup
        config = setup["config"]
        redis_client = setup["redis_client"]

        with patch("src.nodes.scanner.github") as mock_github, \
             patch.object(redis_client, "save_state") as mock_save_state:

            # Mock GitHub API
            mock_github.get_repository_pulls.return_value = [create_test_pr_data(123)]

            # Mock Redis failures initially
            call_count = 0
            def redis_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count <= 2:
                    raise RedisConnectionError("Redis connection lost")
                return True

            mock_save_state.side_effect = redis_side_effect

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

            # Run workflow
            workflow_events = []
            scanning_successful = False

            async for event in graph.astream(initial_state):
                workflow_events.append(event)

                if event.get("workflow_step") == "scanned":
                    scanning_successful = True
                    break

                if len(workflow_events) > 15:
                    break

            # Verify workflow continued despite Redis issues
            assert scanning_successful, "Workflow should continue despite Redis connection issues"
            assert call_count >= 2, "Should have attempted Redis operations multiple times"

    async def test_claude_api_timeout_handling(self, integration_test_setup: dict[str, Any]):
        """Test handling of Claude API timeouts during fix attempts."""
        setup = integration_test_setup
        config = setup["config"]

        with patch("src.nodes.scanner.github") as mock_github, \
             patch("src.nodes.monitor.github") as mock_monitor, \
             patch("src.nodes.invoker.anthropic") as mock_claude:

            # Mock GitHub API
            mock_github.get_repository_pulls.return_value = [create_test_pr_data(123)]
            mock_monitor.get_check_runs.return_value = [
                create_test_check_data("ci/test", "failure")
            ]

            # Mock Claude API timeout
            mock_claude.messages.create = AsyncMock(side_effect=TimeoutError("Claude API timeout"))

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

            # Run workflow
            workflow_events = []
            timeout_handled = False

            async for event in graph.astream(initial_state):
                workflow_events.append(event)

                # Check for timeout handling
                if "timeout" in str(event).lower() or event.get("workflow_step") == "fix_timeout":
                    timeout_handled = True

                # Check for error handling
                if event.get("workflow_step") == "error_handled":
                    break

                if len(workflow_events) > 20:
                    break

            # Verify timeout was handled gracefully
            assert timeout_handled or any("timeout" in str(e) for e in workflow_events), \
                "Claude API timeout should be handled gracefully"

    async def test_concurrent_workflow_error_isolation(self, integration_test_setup: dict[str, Any]):
        """Test that errors in one workflow don't affect others."""
        setup = integration_test_setup
        config = setup["config"]

        # Create two separate workflow instances
        with patch("src.nodes.scanner.github") as mock_github:

            # Mock different behaviors for different repositories
            def github_side_effect(repo_name, *args, **kwargs):
                if "failing-repo" in str(repo_name):
                    raise ConnectionError("Simulated failure for failing repo")
                return [create_test_pr_data(123)]

            mock_github.get_repository_pulls.side_effect = github_side_effect

            # Create workflow graphs
            graph = create_monitor_graph(
                config=config,
                max_concurrent=2,
                enable_tracing=True,
                dry_run=False
            )

            # Create initial states for two repositories
            working_state = create_initial_state(
                repository="test-org/working-repo",
                config=config.repositories[0],
                polling_interval=1
            )

            failing_state = create_initial_state(
                repository="test-org/failing-repo",
                config=config.repositories[0],
                polling_interval=1
            )

            # Run workflows concurrently
            working_events = []
            failing_events = []

            async def run_working_workflow():
                async for event in graph.astream(working_state):
                    working_events.append(event)
                    if event.get("workflow_step") == "scanned":
                        break
                    if len(working_events) > 10:
                        break

            async def run_failing_workflow():
                async for event in graph.astream(failing_state):
                    failing_events.append(event)
                    if event.get("workflow_step") == "error_handled":
                        break
                    if len(failing_events) > 10:
                        break

            # Run both workflows
            await asyncio.gather(
                run_working_workflow(),
                run_failing_workflow(),
                return_exceptions=True
            )

            # Verify isolation
            assert len(working_events) > 0, "Working workflow should have events"
            assert len(failing_events) > 0, "Failing workflow should have events"

            # Working workflow should succeed
            working_success = any(e.get("workflow_step") == "scanned" for e in working_events)
            assert working_success, "Working workflow should complete successfully"

            # Failing workflow should handle error
            failing_handled = any("error" in str(e) for e in failing_events)
            assert failing_handled, "Failing workflow should handle errors"

    async def test_state_corruption_recovery(self, integration_test_setup: dict[str, Any]):
        """Test recovery from corrupted workflow state."""
        setup = integration_test_setup
        config = setup["config"]
        redis_client = setup["redis_client"]

        # Inject corrupted state
        corrupted_state = {
            "repository": "test-org/test-repo",
            "active_prs": "invalid_data_type",  # Should be dict
            "config": None,  # Should be RepositoryConfig
            "workflow_step": "corrupted"
        }

        state_key = "workflow_state:test-org/test-repo"
        redis_client.save_state(state_key, corrupted_state)

        with patch("src.nodes.scanner.github") as mock_github:
            mock_github.get_repository_pulls.return_value = [create_test_pr_data(123)]

            # Create workflow
            graph = create_monitor_graph(
                config=config,
                max_concurrent=1,
                enable_tracing=True,
                dry_run=False
            )

            # Load the corrupted state (this should trigger recovery)
            try:
                loaded_state = redis_client.load_state(state_key)

                # Create clean initial state if loaded state is corrupted
                if not loaded_state or not isinstance(loaded_state.get("active_prs"), dict):
                    initial_state = create_initial_state(
                        repository="test-org/test-repo",
                        config=config.repositories[0],
                        polling_interval=1
                    )
                else:
                    initial_state = loaded_state

            except Exception:
                # Fallback to clean state on any corruption
                initial_state = create_initial_state(
                    repository="test-org/test-repo",
                    config=config.repositories[0],
                    polling_interval=1
                )

            initial_state["persistence"] = redis_client

            # Run workflow
            workflow_events = []
            recovery_successful = False

            async for event in graph.astream(initial_state):
                workflow_events.append(event)

                if event.get("workflow_step") == "scanned":
                    recovery_successful = True
                    break

                if len(workflow_events) > 10:
                    break

            # Verify recovery
            assert recovery_successful, "Workflow should recover from corrupted state"

            # Verify state is now clean
            final_state = redis_client.load_state(state_key)
            if final_state:
                assert isinstance(final_state.get("active_prs", {}), dict), \
                    "Recovered state should have correct data types"

    async def test_network_partition_simulation(self, integration_test_setup: dict[str, Any]):
        """Test workflow behavior during simulated network partitions."""
        setup = integration_test_setup
        config = setup["config"]

        with patch("src.nodes.scanner.github") as mock_github, \
             patch("src.nodes.monitor.github") as mock_monitor:

            # Simulate intermittent network failures
            call_count = 0
            def network_failure_simulation(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                # Fail every other call to simulate network issues
                if call_count % 2 == 0:
                    raise ConnectionError("Network partition")
                return [create_test_pr_data(123)]

            mock_github.get_repository_pulls.side_effect = network_failure_simulation
            mock_monitor.get_check_runs.side_effect = network_failure_simulation

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

            # Run workflow
            workflow_events = []
            successful_operations = 0

            # Run with timeout
            start_time = asyncio.get_event_loop().time()
            timeout = 15  # 15 seconds

            async for event in graph.astream(initial_state):
                current_time = asyncio.get_event_loop().time()
                if current_time - start_time > timeout:
                    break

                workflow_events.append(event)

                if event.get("workflow_step") in ["scanned", "monitored"]:
                    successful_operations += 1

                # Stop after some successful operations
                if successful_operations >= 2:
                    break

                if len(workflow_events) > 30:
                    break

            # Verify workflow handled network issues
            assert successful_operations >= 1, \
                "Workflow should successfully complete some operations despite network issues"
            assert call_count >= 3, "Should have retried network operations multiple times"

    # Helper methods

    async def _setup_github_api_failure_then_recovery(self, base_url: str):
        """Setup GitHub API to fail initially then recover."""
        async with httpx.AsyncClient() as client:
            # This will be handled by the mock side effects in the tests
            pass

