"""Main monitoring graph for PR Check Agent
Defines the LangGraph workflow for repository monitoring
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from langgraph.graph import START, StateGraph
from loguru import logger

from nodes.analyzer import failure_analyzer_node, should_attempt_fixes
from nodes.escalation import escalation_node, should_continue_after_escalation
from nodes.invoker import claude_invoker_node, should_retry_or_escalate
from nodes.monitor import check_monitor_node, prioritize_failures, should_analyze_failures
from nodes.scanner import repository_scanner_node, should_continue_scanning
from state.schemas import MonitorState


def create_monitor_graph(config, max_concurrent: int = 10, enable_tracing: bool = False, dry_run: bool = False) -> StateGraph:
    """Create the main monitoring graph for a repository.

    This graph implements the core workflow:
    1. Scan repository for PR changes
    2. Monitor check status for active PRs
    3. Analyze failures and determine fixability
    4. Attempt automated fixes
    5. Escalate to humans when needed
    """
    logger.info("Creating main monitoring graph")

    # Create the state graph
    graph = StateGraph(MonitorState)

    # Add nodes
    graph.add_node("scan_repository", repository_scanner_node)
    graph.add_node("monitor_checks", check_monitor_node)
    graph.add_node("prioritize_failures", prioritize_failures)
    graph.add_node("analyze_failures", failure_analyzer_node)
    graph.add_node("attempt_fixes", claude_invoker_node)
    graph.add_node("escalate_issues", escalation_node)
    graph.add_node("wait_for_poll", _wait_for_next_poll)
    graph.add_node("handle_errors", _handle_errors)
    graph.add_node("cleanup_state", _cleanup_old_state)

    # Define the workflow edges
    graph.add_edge(START, "scan_repository")

    # After scanning, decide next steps
    graph.add_conditional_edges(
        "scan_repository",
        should_continue_scanning,
        {"monitor_checks": "monitor_checks", "handle_errors": "handle_errors", "wait_for_next_poll": "wait_for_poll"},
    )

    # After monitoring checks, decide if we need to analyze failures
    graph.add_conditional_edges(
        "monitor_checks",
        should_analyze_failures,
        {"analyze_failures": "prioritize_failures", "wait_for_next_poll": "wait_for_poll"},
    )

    # Prioritize failures then analyze
    graph.add_edge("prioritize_failures", "analyze_failures")

    # After analysis, decide if we should attempt fixes
    graph.add_conditional_edges(
        "analyze_failures",
        should_attempt_fixes,
        {"attempt_fixes": "attempt_fixes", "escalate_to_human": "escalate_issues", "wait_for_next_poll": "wait_for_poll"},
    )

    # After fix attempts, decide next steps
    graph.add_conditional_edges(
        "attempt_fixes",
        should_retry_or_escalate,
        {
            "retry_fixes": "attempt_fixes",  # Loop back for retries
            "escalate_to_human": "escalate_issues",
            "verify_fixes": "monitor_checks",  # Go back to monitoring
            "wait_for_next_poll": "wait_for_poll",
        },
    )

    # After escalation, wait for human response or continue
    graph.add_conditional_edges(
        "escalate_issues",
        should_continue_after_escalation,
        {"wait_for_human_response": "wait_for_poll", "wait_for_next_poll": "wait_for_poll"},
    )

    # Wait node goes back to scanning after polling interval
    graph.add_edge("wait_for_poll", "cleanup_state")
    graph.add_edge("cleanup_state", "scan_repository")

    # Error handling goes back to waiting
    graph.add_edge("handle_errors", "wait_for_poll")

    # Compile the graph
    compiled_graph = graph.compile()

    logger.info("Monitoring graph created successfully")
    return compiled_graph  # type: ignore[return-value]


async def _wait_for_next_poll(state: MonitorState) -> dict[str, Any]:
    """Node that waits for the next polling interval."""
    polling_interval = state.get("polling_interval", 300)  # Default 5 minutes
    repository = state.get("repository", "unknown")

    logger.debug(f"Waiting {polling_interval} seconds before next poll for {repository}")

    # In a real implementation, you might want to use a more sophisticated
    # scheduling mechanism, but for now we'll just sleep
    await asyncio.sleep(polling_interval)

    return {**state, "workflow_step": "ready_for_next_poll", "last_updated": datetime.now()}


async def _handle_errors(state: MonitorState) -> dict[str, Any]:
    """Node that handles error conditions."""
    repository = state.get("repository", "unknown")
    consecutive_errors = state.get("consecutive_errors", 0)
    last_error = state.get("last_error", "")

    logger.warning(f"Handling errors for {repository}: {consecutive_errors} consecutive errors")
    logger.warning(f"Last error: {last_error}")

    # Implement exponential backoff for errors
    base_interval = state.get("polling_interval", 300)
    error_multiplier = min(2**consecutive_errors, 8)  # Cap at 8x
    error_wait_time = base_interval * error_multiplier

    logger.info(f"Error backoff: waiting {error_wait_time} seconds")

    # In production, you might want to:
    # 1. Send error notifications
    # 2. Update health metrics
    # 3. Implement circuit breaker logic

    await asyncio.sleep(error_wait_time)

    return {**state, "workflow_step": "error_handled", "last_updated": datetime.now()}


async def _cleanup_old_state(state: MonitorState) -> dict[str, Any]:
    """Node that performs periodic cleanup of old state."""
    repository = state.get("repository", "unknown")
    active_prs = state.get("active_prs", {})

    # Clean up closed PRs (in a real implementation, you'd check with GitHub)
    # For now, we'll just remove PRs that haven't been updated in a while
    cutoff_time = datetime.now() - timedelta(days=7)

    cleaned_prs = {}
    removed_count = 0

    for pr_number, pr_state in active_prs.items():
        last_updated = pr_state.get("last_updated", datetime.now())
        if isinstance(last_updated, str):
            last_updated = datetime.fromisoformat(last_updated)

        if last_updated > cutoff_time:
            cleaned_prs[pr_number] = pr_state
        else:
            logger.debug(f"Removing stale PR #{pr_number} from {repository}")
            removed_count += 1

    if removed_count > 0:
        logger.info(f"Cleaned up {removed_count} stale PRs from {repository}")

    return {**state, "active_prs": cleaned_prs, "cleanup_stats": {"prs_removed": removed_count, "timestamp": datetime.now()}}


# Additional helper functions for the graph


def create_initial_state(repository: str, config, polling_interval: int = 300, workflow_semaphore=None) -> MonitorState:
    """Create initial state for the monitoring workflow."""
    return {
        "repository": repository,
        "config": config,
        "active_prs": {},
        "last_poll_time": None,
        "polling_interval": polling_interval,
        "max_concurrent": 10,
        "workflow_semaphore": workflow_semaphore,
        "consecutive_errors": 0,
        "last_error": None,
        "prioritized_failures": [],
        "total_prs_processed": 0,
        "total_fixes_attempted": 0,
        "total_fixes_successful": 0,
        "total_escalations": 0,
        "workflow_step": "initialized",
    }


async def run_monitoring_workflow(
    repository: str, config, max_concurrent: int = 10, enable_tracing: bool = False, dry_run: bool = False
) -> None:
    """Run the monitoring workflow for a single repository."""
    logger.info(f"Starting monitoring workflow for {repository}")

    # Create the graph
    graph = create_monitor_graph(config=config, max_concurrent=max_concurrent, enable_tracing=enable_tracing, dry_run=dry_run)

    # Create initial state
    initial_state = create_initial_state(
        repository=repository,
        config=config,
        polling_interval=300,  # 5 minutes
    )

    # Add dry_run flag to state
    initial_state["dry_run"] = dry_run

    try:
        # Run the workflow
        async for event in graph.astream(initial_state):  # type: ignore[attr-defined]
            # Log significant events
            if "error" in event:
                logger.error(f"Workflow error in {repository}: {event['error']}")
            elif "workflow_step" in event:
                step = event.get("workflow_step", "")
                if step in ["analyzed", "escalated", "fix_successful"]:
                    logger.info(f"Workflow milestone in {repository}: {step}")

            # Handle graceful shutdown signals here if needed

    except Exception as e:
        logger.error(f"Monitoring workflow failed for {repository}: {e}")
        raise
