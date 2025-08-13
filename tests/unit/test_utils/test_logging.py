"""Tests for logging configuration and utilities"""

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from src.utils.logging import (
    ContextualLogger,
    _json_formatter,
    get_tool_logger,
    get_workflow_logger,
    log_api_call,
    log_escalation,
    log_fix_attempt,
    log_workflow_event,
    setup_logging,
)


class TestSetupLogging:
    """Test logging setup functionality."""

    @patch("src.utils.logging.logger")
    def test_setup_logging_default(self, mock_logger):
        """Test setup logging with default parameters."""
        setup_logging()

        # Verify logger.remove() was called to clear default handlers
        mock_logger.remove.assert_called_once()

        # Verify logger.add() was called for console and file handlers
        assert mock_logger.add.call_count >= 2  # Console + file handlers

        # Verify info messages were logged
        info_calls = [call for call in mock_logger.info.call_args_list if call[0]]
        assert len(info_calls) >= 3  # "Logging initialized", level, dev mode

    @patch("src.utils.logging.logger")
    def test_setup_logging_dev_mode(self, mock_logger):
        """Test setup logging in development mode."""
        setup_logging(level="DEBUG", dev_mode=True)

        # Verify logger calls
        mock_logger.remove.assert_called_once()
        assert mock_logger.add.call_count >= 2

        # Check that backtrace and diagnose are enabled in dev mode
        add_calls = mock_logger.add.call_args_list
        console_call = add_calls[0]  # First call should be console handler
        assert console_call[1]["backtrace"] is True
        assert console_call[1]["diagnose"] is True

    @patch("src.utils.logging.logger")
    def test_setup_logging_custom_log_file(self, mock_logger):
        """Test setup logging with custom log file."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as temp_file:
            temp_path = temp_file.name

        try:
            setup_logging(log_file=temp_path)

            # Should have console, general file, JSON file, and custom file handlers
            assert mock_logger.add.call_count >= 4
        finally:
            Path(temp_path).unlink(missing_ok=True)

    @patch("src.utils.logging.logger")
    def test_setup_logging_no_json(self, mock_logger):
        """Test setup logging without JSON handler."""
        setup_logging(enable_json=False)

        # Should have console and general file handlers only (no JSON)
        assert mock_logger.add.call_count == 2

    @patch("src.utils.logging.Path.mkdir")
    @patch("src.utils.logging.logger")
    def test_setup_logging_creates_log_directory(self, mock_logger, mock_mkdir):
        """Test that setup_logging creates logs directory."""
        setup_logging()

        # Verify logs directory creation was attempted
        mock_mkdir.assert_called_once_with(exist_ok=True)


class TestJsonFormatter:
    """Test JSON log formatter functionality."""

    def create_mock_record(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Create a mock log record for testing."""
        from datetime import datetime

        mock_level = Mock()
        mock_level.name = "INFO"
        mock_thread = Mock()
        mock_thread.name = "MainThread"
        mock_process = Mock()
        mock_process.name = "MainProcess"

        default_record = {
            "time": datetime(2024, 1, 1, 12, 0, 0),
            "level": mock_level,
            "name": "test.logger",
            "module": "test_module",
            "function": "test_function",
            "line": 123,
            "message": "Test log message",
            "thread": mock_thread,
            "process": mock_process,
            "exception": None,
            "extra": {},
        }

        default_record.update(kwargs)
        return default_record

    def test_json_formatter_basic(self):
        """Test JSON formatter with basic log record."""
        record = self.create_mock_record()

        result = _json_formatter(record)

        # Parse the JSON output
        log_data = json.loads(result.strip())

        assert log_data["timestamp"] == "2024-01-01T12:00:00"
        assert log_data["level"] == "INFO"
        assert log_data["logger"] == "test.logger"
        assert log_data["module"] == "test_module"
        assert log_data["function"] == "test_function"
        assert log_data["line"] == 123
        assert log_data["message"] == "Test log message"
        assert log_data["thread"] == "MainThread"
        assert log_data["process"] == "MainProcess"

    def test_json_formatter_with_exception(self):
        """Test JSON formatter with exception information."""
        mock_exception = Mock()
        mock_exception.type = ValueError
        mock_exception.value = "Test error"
        mock_exception.traceback = "Traceback info"

        record = self.create_mock_record(exception=mock_exception)

        result = _json_formatter(record)
        log_data = json.loads(result.strip())

        assert "exception" in log_data
        exc_info = log_data["exception"]
        assert exc_info["type"] == "ValueError"
        assert exc_info["value"] == "Test error"
        assert exc_info["traceback"] == "Traceback info"

    def test_json_formatter_with_extra_fields(self):
        """Test JSON formatter with extra fields."""
        extra_data = {"request_id": "req-123", "user_id": "user-456", "custom_field": "value"}

        record = self.create_mock_record(extra=extra_data)

        result = _json_formatter(record)
        log_data = json.loads(result.strip())

        assert "extra" in log_data
        assert log_data["extra"]["request_id"] == "req-123"
        assert log_data["extra"]["user_id"] == "user-456"
        assert log_data["extra"]["custom_field"] == "value"

    def test_json_formatter_none_values(self):
        """Test JSON formatter handles None values gracefully."""
        record = self.create_mock_record(thread=None, process=None, exception=None, extra=None)

        result = _json_formatter(record)
        log_data = json.loads(result.strip())

        assert log_data["thread"] is None
        assert log_data["process"] is None
        assert "exception" not in log_data  # Should not include None exception
        assert "extra" not in log_data  # Should not include None extra

    def test_json_formatter_output_format(self):
        """Test JSON formatter output format."""
        record = self.create_mock_record()

        result = _json_formatter(record)

        # Should end with newline
        assert result.endswith("\n")

        # Should be valid JSON
        log_data = json.loads(result.strip())
        assert isinstance(log_data, dict)


class TestContextualLogger:
    """Test ContextualLogger functionality."""

    @patch("src.utils.logging.logger")
    def test_contextual_logger_creation(self, mock_logger):
        """Test ContextualLogger creation with context."""
        context = {"repository": "test/repo", "pr_number": 123}

        contextual_logger = ContextualLogger(context)

        assert contextual_logger.context == context
        mock_logger.bind.assert_called_once_with(**context)

    @patch("src.utils.logging.logger")
    def test_contextual_logger_log_methods(self, mock_logger):
        """Test ContextualLogger logging methods."""
        mock_bound_logger = Mock()
        mock_logger.bind.return_value = mock_bound_logger

        context = {"component": "test"}
        contextual_logger = ContextualLogger(context)

        # Test all log methods
        contextual_logger.debug("Debug message", extra_param="debug_value")
        contextual_logger.info("Info message", extra_param="info_value")
        contextual_logger.warning("Warning message", extra_param="warning_value")
        contextual_logger.error("Error message", extra_param="error_value")
        contextual_logger.exception("Exception message", extra_param="exception_value")

        # Verify all methods were called on the bound logger
        mock_bound_logger.debug.assert_called_once_with("Debug message", extra_param="debug_value")
        mock_bound_logger.info.assert_called_once_with("Info message", extra_param="info_value")
        mock_bound_logger.warning.assert_called_once_with("Warning message", extra_param="warning_value")
        mock_bound_logger.error.assert_called_once_with("Error message", extra_param="error_value")
        mock_bound_logger.exception.assert_called_once_with("Exception message", extra_param="exception_value")

    def test_contextual_logger_with_context(self):
        """Test ContextualLogger.with_context() method."""
        initial_context = {"repository": "test/repo", "component": "scanner"}
        contextual_logger = ContextualLogger(initial_context)

        # Create new logger with additional context
        new_logger = contextual_logger.with_context(pr_number=456, check_name="CI")

        # Verify new logger has combined context
        expected_context = {
            "repository": "test/repo",
            "component": "scanner",
            "pr_number": 456,
            "check_name": "CI",
        }
        assert new_logger.context == expected_context

    def test_contextual_logger_context_override(self):
        """Test ContextualLogger context override in with_context()."""
        initial_context = {"repository": "test/repo", "component": "scanner"}
        contextual_logger = ContextualLogger(initial_context)

        # Override existing field
        new_logger = contextual_logger.with_context(component="monitor", new_field="value")

        expected_context = {
            "repository": "test/repo",
            "component": "monitor",  # Overridden
            "new_field": "value",
        }
        assert new_logger.context == expected_context


class TestWorkflowLogger:
    """Test workflow logger creation."""

    def test_get_workflow_logger_minimal(self):
        """Test workflow logger with minimal parameters."""
        logger = get_workflow_logger("test/repo")

        expected_context = {"repository": "test/repo", "component": "workflow"}
        assert logger.context == expected_context

    def test_get_workflow_logger_full_context(self):
        """Test workflow logger with all parameters."""
        logger = get_workflow_logger(
            repository="test/repo",
            pr_number=123,
            check_name="CI",
            workflow_id="wf-456",
        )

        expected_context = {
            "repository": "test/repo",
            "component": "workflow",
            "pr_number": 123,
            "check_name": "CI",
            "workflow_id": "wf-456",
        }
        assert logger.context == expected_context

    def test_get_workflow_logger_partial_context(self):
        """Test workflow logger with partial parameters."""
        logger = get_workflow_logger(repository="test/repo", pr_number=789)

        expected_context = {
            "repository": "test/repo",
            "component": "workflow",
            "pr_number": 789,
        }
        assert logger.context == expected_context
        assert "check_name" not in logger.context
        assert "workflow_id" not in logger.context


class TestToolLogger:
    """Test tool logger creation."""

    def test_get_tool_logger_basic(self):
        """Test tool logger with basic parameters."""
        logger = get_tool_logger("github")

        expected_context = {"component": "tool", "tool_name": "github"}
        assert logger.context == expected_context

    def test_get_tool_logger_with_context(self):
        """Test tool logger with additional context."""
        logger = get_tool_logger(
            "claude_code",
            repository="test/repo",
            operation="analyze",
            request_id="req-123",
        )

        expected_context = {
            "component": "tool",
            "tool_name": "claude_code",
            "repository": "test/repo",
            "operation": "analyze",
            "request_id": "req-123",
        }
        assert logger.context == expected_context


class TestSpecializedLogFunctions:
    """Test specialized logging functions."""

    @patch("src.utils.logging.logger")
    def test_log_api_call_success(self, mock_logger):
        """Test logging successful API call."""
        mock_bound_logger = Mock()
        mock_logger.bind.return_value = mock_bound_logger

        log_api_call(
            service="github",
            operation="get_pr",
            duration_ms=150.5,
            success=True,
            status_code=200,
            request_id="req-123",
        )

        # Verify logger.bind was called with correct data
        mock_logger.bind.assert_called_once()
        bind_args = mock_logger.bind.call_args[1]

        assert bind_args["service"] == "github"
        assert bind_args["operation"] == "get_pr"
        assert bind_args["duration_ms"] == 150.5
        assert bind_args["success"] is True
        assert bind_args["status_code"] == 200
        assert bind_args["request_id"] == "req-123"
        assert bind_args["component"] == "api_call"

        # Verify info log was called for success
        mock_bound_logger.info.assert_called_once()
        log_message = mock_bound_logger.info.call_args[0][0]
        assert "github.get_pr succeeded" in log_message
        assert "150.5ms" in log_message

    @patch("src.utils.logging.logger")
    def test_log_api_call_failure(self, mock_logger):
        """Test logging failed API call."""
        mock_bound_logger = Mock()
        mock_logger.bind.return_value = mock_bound_logger

        log_api_call(
            service="claude",
            operation="analyze",
            duration_ms=5000.0,
            success=False,
            error="Connection timeout",
        )

        # Verify error log was called for failure
        mock_bound_logger.error.assert_called_once()
        log_message = mock_bound_logger.error.call_args[0][0]
        assert "claude.analyze failed" in log_message
        assert "5000.0ms" in log_message

    @patch("src.utils.logging.logger")
    def test_log_workflow_event(self, mock_logger):
        """Test workflow event logging."""
        mock_bound_logger = Mock()
        mock_logger.bind.return_value = mock_bound_logger

        log_workflow_event(
            event_type="pr_discovered",
            repository="test/repo",
            pr_number=456,
            details={"branch": "main", "author": "developer"},
            workflow_id="wf-789",
        )

        # Verify logger.bind was called with correct data
        bind_args = mock_logger.bind.call_args[1]
        assert bind_args["event_type"] == "pr_discovered"
        assert bind_args["repository"] == "test/repo"
        assert bind_args["pr_number"] == 456
        assert bind_args["details"] == {"branch": "main", "author": "developer"}
        assert bind_args["workflow_id"] == "wf-789"
        assert bind_args["component"] == "workflow_event"

        # Verify log message includes all relevant info
        mock_bound_logger.info.assert_called_once()
        log_message = mock_bound_logger.info.call_args[0][0]
        assert "Workflow event: pr_discovered" in log_message
        assert "test/repo" in log_message
        assert "PR #456" in log_message

    @patch("src.utils.logging.logger")
    def test_log_workflow_event_no_pr(self, mock_logger):
        """Test workflow event logging without PR number."""
        mock_bound_logger = Mock()
        mock_logger.bind.return_value = mock_bound_logger

        log_workflow_event(
            event_type="scan_completed",
            repository="test/repo",
        )

        # Verify log message doesn't include PR info
        mock_bound_logger.info.assert_called_once()
        log_message = mock_bound_logger.info.call_args[0][0]
        assert "Workflow event: scan_completed" in log_message
        assert "test/repo" in log_message
        assert "PR #" not in log_message

    @patch("src.utils.logging.logger")
    def test_log_fix_attempt_success(self, mock_logger):
        """Test logging successful fix attempt."""
        mock_bound_logger = Mock()
        mock_logger.bind.return_value = mock_bound_logger

        log_fix_attempt(
            repository="test/repo",
            pr_number=123,
            check_name="CI",
            attempt_number=2,
            success=True,
            duration_seconds=45.7,
        )

        # Verify logger.bind was called with correct data
        bind_args = mock_logger.bind.call_args[1]
        assert bind_args["repository"] == "test/repo"
        assert bind_args["pr_number"] == 123
        assert bind_args["check_name"] == "CI"
        assert bind_args["attempt_number"] == 2
        assert bind_args["success"] is True
        assert bind_args["duration_seconds"] == 45.7
        assert bind_args["component"] == "fix_attempt"

        # Verify info log for success
        mock_bound_logger.info.assert_called_once()
        log_message = mock_bound_logger.info.call_args[0][0]
        assert "Fix attempt #2 for CI" in log_message
        assert "test/repo PR #123" in log_message
        assert "SUCCESS" in log_message
        assert "45.7s" in log_message

    @patch("src.utils.logging.logger")
    def test_log_fix_attempt_failure(self, mock_logger):
        """Test logging failed fix attempt."""
        mock_bound_logger = Mock()
        mock_logger.bind.return_value = mock_bound_logger

        log_fix_attempt(
            repository="test/repo",
            pr_number=123,
            check_name="Tests",
            attempt_number=3,
            success=False,
            duration_seconds=15.2,
            error="Claude Code timeout",
        )

        # Verify error field was included
        bind_args = mock_logger.bind.call_args[1]
        assert bind_args["error"] == "Claude Code timeout"

        # Verify warning log for failure
        mock_bound_logger.warning.assert_called_once()
        log_message = mock_bound_logger.warning.call_args[0][0]
        assert "Fix attempt #3 for Tests" in log_message
        assert "FAILED" in log_message

    @patch("src.utils.logging.logger")
    def test_log_escalation_success(self, mock_logger):
        """Test logging successful escalation."""
        mock_bound_logger = Mock()
        mock_logger.bind.return_value = mock_bound_logger

        log_escalation(
            repository="test/repo",
            pr_number=789,
            check_name="Security",
            reason="Max attempts exceeded",
            escalation_id="esc-456",
            success=True,
        )

        # Verify logger.bind was called with correct data
        bind_args = mock_logger.bind.call_args[1]
        assert bind_args["repository"] == "test/repo"
        assert bind_args["pr_number"] == 789
        assert bind_args["check_name"] == "Security"
        assert bind_args["reason"] == "Max attempts exceeded"
        assert bind_args["escalation_id"] == "esc-456"
        assert bind_args["success"] is True
        assert bind_args["component"] == "escalation"

        # Verify info log for success
        mock_bound_logger.info.assert_called_once()
        log_message = mock_bound_logger.info.call_args[0][0]
        assert "Escalation for Security" in log_message
        assert "test/repo PR #789" in log_message
        assert "SENT" in log_message
        assert "ID: esc-456" in log_message

    @patch("src.utils.logging.logger")
    def test_log_escalation_failure(self, mock_logger):
        """Test logging failed escalation."""
        mock_bound_logger = Mock()
        mock_logger.bind.return_value = mock_bound_logger

        log_escalation(
            repository="test/repo",
            pr_number=789,
            check_name="CI",
            reason="Unfixable issue",
            escalation_id="esc-789",
            success=False,
        )

        # Verify error log for failure
        mock_bound_logger.error.assert_called_once()
        log_message = mock_bound_logger.error.call_args[0][0]
        assert "Escalation for CI" in log_message
        assert "FAILED" in log_message


class TestLoggingIntegration:
    """Integration tests for logging functionality."""

    def test_contextual_logger_workflow(self):
        """Test complete contextual logging workflow."""
        # Step 1: Get workflow logger
        workflow_logger = get_workflow_logger("test/repo", pr_number=123)

        # Step 2: Add more context
        check_logger = workflow_logger.with_context(check_name="CI", attempt=1)

        # Step 3: Add even more context
        detailed_logger = check_logger.with_context(operation="analyze", request_id="req-456")

        # Verify final context includes all fields
        expected_context = {
            "repository": "test/repo",
            "component": "workflow",
            "pr_number": 123,
            "check_name": "CI",
            "attempt": 1,
            "operation": "analyze",
            "request_id": "req-456",
        }
        assert detailed_logger.context == expected_context

    def test_tool_logger_workflow(self):
        """Test tool logger workflow."""
        # Step 1: Get tool logger
        base_logger = get_tool_logger("github", repository="test/repo")

        # Step 2: Add operation context
        operation_logger = base_logger.with_context(operation="get_checks", pr_number=456)

        # Verify context accumulation
        expected_context = {
            "component": "tool",
            "tool_name": "github",
            "repository": "test/repo",
            "operation": "get_checks",
            "pr_number": 456,
        }
        assert operation_logger.context == expected_context

    @patch("src.utils.logging.logger")
    def test_specialized_logging_integration(self, mock_logger):
        """Test integration of specialized logging functions."""
        mock_bound_logger = Mock()
        mock_logger.bind.return_value = mock_bound_logger

        # Simulate a complete workflow event sequence
        log_workflow_event("pr_discovered", "test/repo", pr_number=123)
        log_api_call("github", "get_checks", 200.0, success=True, status_code=200)
        log_fix_attempt("test/repo", 123, "CI", 1, success=False, duration_seconds=30.0, error="Build failed")
        log_escalation("test/repo", 123, "CI", "Max attempts", "esc-123", success=True)

        # Verify all logging functions were called
        assert mock_logger.bind.call_count == 4
        assert mock_bound_logger.info.call_count == 3  # workflow_event, api_call, escalation
        assert mock_bound_logger.warning.call_count == 1  # fix_attempt failure
