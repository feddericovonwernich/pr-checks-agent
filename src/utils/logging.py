"""Logging configuration for PR Check Agent
Sets up structured logging with JSON output and correlation IDs
"""

import json
import sys
from pathlib import Path
from typing import Any

import loguru
from loguru import logger


def setup_logging(level: str = "INFO", dev_mode: bool = False, log_file: str | None = None, enable_json: bool = True) -> None:
    """Set up logging configuration for the PR Check Agent.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        dev_mode: Enable development mode with more verbose output
        log_file: Optional log file path
        enable_json: Enable JSON structured logging

    """
    # Remove default handler
    logger.remove()

    # Console logging format
    if dev_mode:
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )
    else:
        console_format = "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"

    # Add console handler
    logger.add(sys.stdout, format=console_format, level=level, colorize=True, backtrace=dev_mode, diagnose=dev_mode)

    # Ensure logs directory exists
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Add file handler for general logs
    logger.add(
        "logs/pr-agent.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        level=level,
        rotation="10 MB",
        retention="30 days",
        compression="gz",
        backtrace=True,
        diagnose=True,
    )

    # Add JSON file handler for structured logs
    if enable_json:
        logger.add(
            "logs/pr-agent.json",
            format=_json_formatter,
            level=level,
            rotation="10 MB",
            retention="30 days",
            compression="gz",
            serialize=False,  # We handle serialization in _json_formatter
        )

    # Add custom log file if specified
    if log_file:
        logger.add(
            log_file,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
            level=level,
            rotation="10 MB",
            retention="7 days",
        )

    logger.info("Logging initialized")
    logger.info(f"Log level: {level}")
    logger.info(f"Development mode: {dev_mode}")


def _json_formatter(record: loguru.Record) -> str:
    """Custom JSON formatter for structured logging."""
    # Extract basic record information
    log_entry: dict[str, Any] = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": record["name"],
        "module": record["module"],
        "function": record["function"],
        "line": record["line"],
        "message": record["message"],
        "thread": record["thread"].name if record["thread"] else None,
        "process": record["process"].name if record["process"] else None,
    }

    # Add exception information if present
    if record["exception"]:
        exc_info = {
            "type": record["exception"].type.__name__ if record["exception"].type else None,
            "value": str(record["exception"].value) if record["exception"].value else None,
            "traceback": record["exception"].traceback if record["exception"].traceback else None,
        }
        log_entry["exception"] = exc_info

    # Add extra fields from record["extra"]
    if record["extra"]:
        log_entry["extra"] = record["extra"]

    return json.dumps(log_entry, default=str) + "\n"


class ContextualLogger:
    """Logger wrapper that adds contextual information to all log messages."""

    def __init__(self, context: dict[str, Any]):
        self.context = context
        self.logger = logger.bind(**context)

    def debug(self, message: str, **kwargs: Any) -> None:
        self.logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self.logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self.logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self.logger.error(message, **kwargs)

    def exception(self, message: str, **kwargs: Any) -> None:
        self.logger.exception(message, **kwargs)

    def with_context(self, **additional_context) -> "ContextualLogger":
        """Create a new logger with additional context."""
        new_context = {**self.context, **additional_context}
        return ContextualLogger(new_context)


def get_workflow_logger(
    repository: str, pr_number: int | None = None, check_name: str | None = None, workflow_id: str | None = None
) -> ContextualLogger:
    """Get a contextual logger for workflow operations."""
    context: dict[str, Any] = {"repository": repository, "component": "workflow"}

    if pr_number is not None:
        context["pr_number"] = pr_number

    if check_name:
        context["check_name"] = check_name

    if workflow_id:
        context["workflow_id"] = workflow_id

    return ContextualLogger(context)


def get_tool_logger(tool_name: str, **context: Any) -> ContextualLogger:
    """Get a contextual logger for tool operations."""
    base_context = {"component": "tool", "tool_name": tool_name}
    base_context.update(context)

    return ContextualLogger(base_context)


def log_api_call(
    service: str,
    operation: str,
    duration_ms: float,
    success: bool,
    status_code: int | None = None,
    error: str | None = None,
    **context: Any,
) -> None:
    """Log API call with standardized format."""
    log_data = {
        "service": service,
        "operation": operation,
        "duration_ms": duration_ms,
        "success": success,
        "component": "api_call",
        **context,
    }

    if status_code:
        log_data["status_code"] = status_code

    if error:
        log_data["error"] = error

    log_level = "info" if success else "error"
    message = f"{service}.{operation} {'succeeded' if success else 'failed'} in {duration_ms:.1f}ms"

    getattr(logger.bind(**log_data), log_level)(message)


def log_workflow_event(
    event_type: str, repository: str, pr_number: int | None = None, details: dict[str, Any] | None = None, **context: Any
) -> None:
    """Log workflow event with standardized format."""
    log_data = {"event_type": event_type, "repository": repository, "component": "workflow_event", **context}

    if pr_number:
        log_data["pr_number"] = pr_number

    if details:
        log_data["details"] = details

    message = f"Workflow event: {event_type} for {repository}"
    if pr_number:
        message += f" PR #{pr_number}"

    logger.bind(**log_data).info(message)


def log_fix_attempt(
    repository: str,
    pr_number: int,
    check_name: str,
    attempt_number: int,
    success: bool,
    duration_seconds: float,
    error: str | None = None,
) -> None:
    """Log fix attempt with standardized format."""
    log_data = {
        "repository": repository,
        "pr_number": pr_number,
        "check_name": check_name,
        "attempt_number": attempt_number,
        "success": success,
        "duration_seconds": duration_seconds,
        "component": "fix_attempt",
    }

    if error:
        log_data["error"] = error

    message = (
        f"Fix attempt #{attempt_number} for {check_name} in {repository} PR #{pr_number}: "
        f"{'SUCCESS' if success else 'FAILED'} ({duration_seconds:.1f}s)"
    )

    log_level = "info" if success else "warning"
    getattr(logger.bind(**log_data), log_level)(message)


def log_escalation(repository: str, pr_number: int, check_name: str, reason: str, escalation_id: str, success: bool) -> None:
    """Log escalation event with standardized format."""
    log_data = {
        "repository": repository,
        "pr_number": pr_number,
        "check_name": check_name,
        "reason": reason,
        "escalation_id": escalation_id,
        "success": success,
        "component": "escalation",
    }

    message = (
        f"Escalation for {check_name} in {repository} PR #{pr_number}: {'SENT' if success else 'FAILED'} (ID: {escalation_id})"
    )

    log_level = "info" if success else "error"
    getattr(logger.bind(**log_data), log_level)(message)
