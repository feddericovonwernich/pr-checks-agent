#!/usr/bin/env python3
"""PR Check Agent - Main entry point
LangGraph-powered GitHub PR monitoring and fixing agent
"""

import asyncio
import os
import sys
from typing import Any

import click
import uvloop
from dotenv import load_dotenv
from loguru import logger

from graphs.monitor_graph import create_monitor_graph, create_initial_state
from utils.config import Config
from utils.logging import setup_logging
from utils.monitoring import start_monitoring_server


@click.command()
@click.option(
    "--config",
    "-c",
    default="config/repos.json",
    help="Path to repository configuration file",
    type=click.Path(exists=True),
)
@click.option(
    "--log-level",
    default="INFO",
    help="Logging level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
)
@click.option(
    "--max-concurrent-workflows",
    default=10,
    help="Maximum number of concurrent PR workflows",
    type=int,
)
@click.option("--trace", is_flag=True, help="Enable workflow tracing")
@click.option("--dashboard", is_flag=True, help="Enable web dashboard")
@click.option("--metrics-port", default=8080, help="Port for metrics and dashboard", type=int)
@click.option("--dry-run", is_flag=True, help="Run in dry-run mode (no actual fixes)")
@click.option("--dev", is_flag=True, help="Development mode with additional logging")
@click.version_option(version="0.1.0")
def main(
    config: str,
    log_level: str,
    max_concurrent_workflows: int,
    trace: bool,
    dashboard: bool,
    metrics_port: int,
    dry_run: bool,
    dev: bool,
) -> None:
    """PR Check Agent - Automated GitHub PR monitoring and fixing."""
    # Load environment variables
    load_dotenv()

    # Read log level from environment variable, default to INFO
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    # Setup logging
    setup_logging(level=log_level, dev_mode=dev)

    logger.info("Starting PR Check Agent v0.1.0")
    logger.info(f"Configuration: {config}")
    logger.info(f"Log level: {log_level}")
    logger.info(f"Max concurrent workflows: {max_concurrent_workflows}")

    if dry_run:
        logger.warning("Running in DRY-RUN mode - no actual fixes will be applied")

    # Load configuration
    try:
        app_config = Config.load(config)
        logger.info(f"Loaded configuration for {len(app_config.repositories)} repositories")
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Set event loop policy for better performance
    if sys.platform != "win32":
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

    # Start the async main loop
    try:
        asyncio.run(
            async_main(
                app_config,
                max_concurrent_workflows,
                trace,
                dashboard,
                metrics_port,
                dry_run,
                dev,
            )
        )
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down gracefully...")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


async def async_main(
    config: Config,
    max_concurrent_workflows: int,
    trace: bool,
    dashboard: bool,
    metrics_port: int,
    dry_run: bool,
    dev: bool,
) -> None:
    """Async main function that runs the agent."""
    # Start monitoring server (metrics, health, dashboard)
    monitoring_task = None
    if dashboard or metrics_port:
        logger.info(f"Starting monitoring server on port {metrics_port}")
        monitoring_task = asyncio.create_task(start_monitoring_server(port=metrics_port, dashboard=dashboard))

    # Create the main monitoring graph
    logger.info("Creating LangGraph monitoring workflow...")
    graph = create_monitor_graph(
        config=config,
        max_concurrent=max_concurrent_workflows,
        enable_tracing=trace,
        dry_run=dry_run,
    )

    logger.info("Starting repository monitoring...")

    # Create semaphore for concurrent workflow limiting
    workflow_semaphore = asyncio.Semaphore(max_concurrent_workflows)

    # Start monitoring workflows for each repository
    tasks = []

    for repo_config in config.repositories:
        logger.info(f"Starting monitoring for {repo_config.owner}/{repo_config.repo}")

        # Create initial workflow state using the proper initialization function
        initial_state = create_initial_state(
            repository=f"{repo_config.owner}/{repo_config.repo}",
            config=repo_config,
            polling_interval=300,  # 5 minutes default
            workflow_semaphore=workflow_semaphore,
        )
        # Add dry_run flag
        initial_state["dry_run"] = dry_run

        # Start monitoring workflow for this repository
        task = asyncio.create_task(run_repository_workflow(graph, initial_state, repo_config))
        tasks.append(task)

    logger.info(f"Started monitoring for {len(tasks)} repositories")

    try:
        # Wait for all tasks to complete (they should run indefinitely)
        tasks_to_wait = [task for task in tasks if task is not None]
        if monitoring_task is not None:
            tasks_to_wait.append(monitoring_task)
        await asyncio.gather(*tasks_to_wait, return_exceptions=True)
    except Exception as e:
        logger.error(f"Error in main workflow: {e}")
        raise
    finally:
        # Cleanup
        logger.info("Shutting down workflows...")
        for task in tasks:
            if not task.done():
                task.cancel()

        if monitoring_task and not monitoring_task.done():
            monitoring_task.cancel()

        # Wait for tasks to finish
        cleanup_tasks = [task for task in tasks if task is not None]
        if monitoring_task is not None:
            cleanup_tasks.append(monitoring_task)
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        logger.info("Shutdown complete")


async def run_repository_workflow(graph: Any, initial_state: dict[str, Any], repo_config: Any) -> None:
    """Run the monitoring workflow for a specific repository."""
    repository = f"{repo_config.owner}/{repo_config.repo}"
    logger.info(f"Starting workflow for repository: {repository}")

    try:
        # Run the graph workflow
        async for event in graph.astream(initial_state):
            # Log workflow events
            if "error" in event:
                logger.error(f"Workflow error in {repository}: {event['error']}")
            elif "status" in event:
                logger.debug(f"Workflow status for {repository}: {event['status']}")

            # Handle workflow completion or errors
            if event.get("completed"):
                logger.info(f"Workflow completed for {repository}")
                break

    except Exception as e:
        logger.error(f"Repository workflow failed for {repository}: {e}")
        # In production, you might want to restart the workflow
        # For now, we'll let it exit
        raise


if __name__ == "__main__":
    main()
