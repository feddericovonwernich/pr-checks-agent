"""Tests for state schemas"""

from datetime import datetime

import pytest

from src.state.schemas import (
    CheckInfo,
    CheckStatus,
    EscalationRecord,
    EscalationStatus,
    FixAttempt,
    FixAttemptStatus,
    PRInfo,
    RepositoryConfig,
)


class TestCheckStatus:
    """Test CheckStatus enum."""

    def test_check_status_values(self):
        """Test CheckStatus enum values."""
        assert CheckStatus.PENDING == "pending"
        assert CheckStatus.SUCCESS == "success"
        assert CheckStatus.FAILURE == "failure"
        assert CheckStatus.ERROR == "error"
        assert CheckStatus.CANCELLED == "cancelled"

    def test_check_status_iteration(self):
        """Test CheckStatus can be iterated."""
        statuses = list(CheckStatus)
        assert len(statuses) == 5
        assert CheckStatus.PENDING in statuses


class TestFixAttemptStatus:
    """Test FixAttemptStatus enum."""

    def test_fix_attempt_status_values(self):
        """Test FixAttemptStatus enum values."""
        assert FixAttemptStatus.PENDING == "pending"
        assert FixAttemptStatus.IN_PROGRESS == "in_progress"
        assert FixAttemptStatus.SUCCESS == "success"
        assert FixAttemptStatus.FAILURE == "failure"
        assert FixAttemptStatus.TIMEOUT == "timeout"


class TestEscalationStatus:
    """Test EscalationStatus enum."""

    def test_escalation_status_values(self):
        """Test EscalationStatus enum values."""
        assert EscalationStatus.NONE == "none"
        assert EscalationStatus.PENDING == "pending"
        assert EscalationStatus.NOTIFIED == "notified"
        assert EscalationStatus.ACKNOWLEDGED == "acknowledged"
        assert EscalationStatus.RESOLVED == "resolved"


class TestCheckInfo:
    """Test CheckInfo model."""

    def test_check_info_minimal(self):
        """Test CheckInfo with minimal required fields."""
        now = datetime.now()
        check = CheckInfo(name="CI", status=CheckStatus.FAILURE, details_url="https://github.com/test/repo/runs/123")

        assert check.name == "CI"
        assert check.status == CheckStatus.FAILURE
        assert check.conclusion is None
        assert check.details_url == "https://github.com/test/repo/runs/123"
        assert check.started_at is None
        assert check.completed_at is None
        assert check.failure_logs is None
        assert check.error_message is None

    def test_check_info_full(self):
        """Test CheckInfo with all fields."""
        started_at = datetime.now()
        completed_at = datetime.now()

        check = CheckInfo(
            name="Tests",
            status=CheckStatus.FAILURE,
            conclusion="failure",
            details_url="https://github.com/test/repo/runs/456",
            started_at=started_at,
            completed_at=completed_at,
            failure_logs="Test failed: assertion error",
            error_message="AssertionError on line 42",
        )

        assert check.name == "Tests"
        assert check.status == CheckStatus.FAILURE
        assert check.conclusion == "failure"
        assert check.started_at == started_at
        assert check.completed_at == completed_at
        assert check.failure_logs == "Test failed: assertion error"
        assert check.error_message == "AssertionError on line 42"

    def test_check_info_enum_values_used(self):
        """Test that enum values are used in serialization."""
        check = CheckInfo(name="Lint", status=CheckStatus.SUCCESS, details_url="https://github.com/test/repo/runs/789")

        # Test dict() conversion uses enum values
        check_dict = check.dict()
        assert check_dict["status"] == "success"


class TestFixAttempt:
    """Test FixAttempt model."""

    def test_fix_attempt_minimal(self):
        """Test FixAttempt with minimal required fields."""
        now = datetime.now()

        fix = FixAttempt(
            id="fix_123",
            timestamp=now,
            check_name="CI",
            context="Build failed with error X",
            prompt="Fix the build error",
            status=FixAttemptStatus.PENDING,
        )

        assert fix.id == "fix_123"
        assert fix.timestamp == now
        assert fix.check_name == "CI"
        assert fix.context == "Build failed with error X"
        assert fix.prompt == "Fix the build error"
        assert fix.status == FixAttemptStatus.PENDING
        assert fix.result is None
        assert fix.error_message is None
        assert fix.duration_seconds is None

    def test_fix_attempt_full(self):
        """Test FixAttempt with all fields."""
        now = datetime.now()

        fix = FixAttempt(
            id="fix_456",
            timestamp=now,
            check_name="Tests",
            context="Test failure in module X",
            prompt="Fix the failing test",
            result="Fixed import statement",
            status=FixAttemptStatus.SUCCESS,
            error_message=None,
            duration_seconds=45.2,
        )

        assert fix.result == "Fixed import statement"
        assert fix.status == FixAttemptStatus.SUCCESS
        assert fix.duration_seconds == 45.2


class TestEscalationRecord:
    """Test EscalationRecord model."""

    def test_escalation_record_minimal(self):
        """Test EscalationRecord with minimal required fields."""
        now = datetime.now()

        escalation = EscalationRecord(
            id="esc_123",
            timestamp=now,
            check_name="Security",
            reason="Unfixable security issue",
            status=EscalationStatus.PENDING,
        )

        assert escalation.id == "esc_123"
        assert escalation.timestamp == now
        assert escalation.check_name == "Security"
        assert escalation.reason == "Unfixable security issue"
        assert escalation.status == EscalationStatus.PENDING
        assert escalation.telegram_message_id is None
        assert escalation.acknowledged_by is None
        assert escalation.acknowledged_at is None
        assert escalation.resolution_notes is None

    def test_escalation_record_full(self):
        """Test EscalationRecord with all fields."""
        now = datetime.now()
        acked_at = datetime.now()

        escalation = EscalationRecord(
            id="esc_456",
            timestamp=now,
            check_name="Tests",
            reason="Complex test failure",
            telegram_message_id="msg_789",
            status=EscalationStatus.RESOLVED,
            acknowledged_by="@dev-lead",
            acknowledged_at=acked_at,
            resolution_notes="Fixed by updating test data",
        )

        assert escalation.telegram_message_id == "msg_789"
        assert escalation.status == EscalationStatus.RESOLVED
        assert escalation.acknowledged_by == "@dev-lead"
        assert escalation.acknowledged_at == acked_at
        assert escalation.resolution_notes == "Fixed by updating test data"


class TestPRInfo:
    """Test PRInfo model."""

    def test_pr_info_minimal(self):
        """Test PRInfo with minimal required fields."""
        created_at = datetime.now()
        updated_at = datetime.now()

        pr = PRInfo(
            number=123,
            title="Add new feature",
            author="developer",
            branch="feature-branch",
            base_branch="main",
            url="https://github.com/test/repo/pull/123",
            created_at=created_at,
            updated_at=updated_at,
        )

        assert pr.number == 123
        assert pr.title == "Add new feature"
        assert pr.author == "developer"
        assert pr.branch == "feature-branch"
        assert pr.base_branch == "main"
        assert pr.url == "https://github.com/test/repo/pull/123"
        assert pr.created_at == created_at
        assert pr.updated_at == updated_at
        assert pr.draft is False  # Default value
        assert pr.mergeable is None  # Default value

    def test_pr_info_full(self):
        """Test PRInfo with all fields."""
        created_at = datetime.now()
        updated_at = datetime.now()

        pr = PRInfo(
            number=456,
            title="Draft: WIP feature",
            author="contributor",
            branch="wip-feature",
            base_branch="develop",
            url="https://github.com/test/repo/pull/456",
            created_at=created_at,
            updated_at=updated_at,
            draft=True,
            mergeable=False,
        )

        assert pr.draft is True
        assert pr.mergeable is False


class TestRepositoryConfig:
    """Test RepositoryConfig model."""

    def test_repository_config_minimal(self):
        """Test RepositoryConfig with minimal required fields."""
        config = RepositoryConfig(owner="test-org", repo="test-repo")

        assert config.owner == "test-org"
        assert config.repo == "test-repo"
        assert config.branch_filter == ["main"]  # Default value
        assert config.check_types == []  # Default value
        assert config.claude_context == {}  # Default value
        assert config.fix_limits == {}  # Default value
        assert config.priorities == {}  # Default value
        assert config.notifications == {}  # Default value

    def test_repository_config_full(self):
        """Test RepositoryConfig with all fields."""
        config = RepositoryConfig(
            owner="test-org",
            repo="test-repo",
            branch_filter=["main", "develop"],
            check_types=["ci", "tests", "security"],
            claude_context={"language": "python", "framework": "fastapi"},
            fix_limits={"max_attempts": 3, "timeout": 300},
            priorities={"check_types": {"security": 1, "tests": 2}},
            notifications={"telegram_channel": "@alerts"},
        )

        assert config.branch_filter == ["main", "develop"]
        assert config.check_types == ["ci", "tests", "security"]
        assert config.claude_context == {"language": "python", "framework": "fastapi"}
        assert config.fix_limits == {"max_attempts": 3, "timeout": 300}
        assert config.priorities == {"check_types": {"security": 1, "tests": 2}}
        assert config.notifications == {"telegram_channel": "@alerts"}


class TestPRState:
    """Test PRState TypedDict."""

    def test_pr_state_creation(self):
        """Test PRState can be created and accessed."""
        now = datetime.now()

        # Create sample data
        pr_info = PRInfo(
            number=123,
            title="Test PR",
            author="developer",
            branch="feature",
            base_branch="main",
            url="https://github.com/test/repo/pull/123",
            created_at=now,
            updated_at=now,
        )

        check_info = CheckInfo(name="CI", status=CheckStatus.FAILURE, details_url="https://github.com/test/repo/runs/123")

        fix_attempt = FixAttempt(
            id="fix_123",
            timestamp=now,
            check_name="CI",
            context="Build error",
            prompt="Fix build",
            status=FixAttemptStatus.PENDING,
        )

        escalation = EscalationRecord(
            id="esc_123", timestamp=now, check_name="CI", reason="Complex error", status=EscalationStatus.PENDING
        )

        # Create PRState
        pr_state = {
            "pr_number": 123,
            "repository": "test/repo",
            "pr_info": pr_info,
            "checks": {"CI": check_info},
            "failed_checks": ["CI"],
            "fix_attempts": {"CI": [fix_attempt]},
            "current_fix_attempt": "fix_123",
            "escalations": [escalation],
            "escalation_status": EscalationStatus.PENDING,
            "last_updated": now,
            "workflow_step": "analyzing",
            "retry_count": 0,
            "error_message": None,
        }

        # Test access
        assert pr_state["pr_number"] == 123
        assert pr_state["repository"] == "test/repo"
        assert pr_state["pr_info"] == pr_info
        assert pr_state["checks"]["CI"] == check_info
        assert pr_state["failed_checks"] == ["CI"]
        assert pr_state["fix_attempts"]["CI"] == [fix_attempt]
        assert pr_state["escalations"] == [escalation]
        assert pr_state["escalation_status"] == EscalationStatus.PENDING


class TestMonitorState:
    """Test MonitorState TypedDict."""

    def test_monitor_state_creation(self):
        """Test MonitorState can be created and accessed."""
        now = datetime.now()

        config = RepositoryConfig(owner="test-org", repo="test-repo")

        # Create MonitorState
        monitor_state = {
            "repository": "test-org/test-repo",
            "config": config,
            "active_prs": {},
            "last_poll_time": now,
            "polling_interval": 300,
            "max_concurrent": 10,
            "workflow_semaphore": None,  # Would be asyncio.Semaphore in real use
            "consecutive_errors": 0,
            "last_error": None,
            "total_prs_processed": 42,
            "total_fixes_attempted": 15,
            "total_fixes_successful": 12,
            "total_escalations": 3,
        }

        # Test access
        assert monitor_state["repository"] == "test-org/test-repo"
        assert monitor_state["config"] == config
        assert monitor_state["active_prs"] == {}
        assert monitor_state["last_poll_time"] == now
        assert monitor_state["polling_interval"] == 300
        assert monitor_state["max_concurrent"] == 10
        assert monitor_state["consecutive_errors"] == 0
        assert monitor_state["total_prs_processed"] == 42
        assert monitor_state["total_fixes_attempted"] == 15
        assert monitor_state["total_fixes_successful"] == 12
        assert monitor_state["total_escalations"] == 3


class TestFixWorkflowState:
    """Test FixWorkflowState TypedDict."""

    def test_fix_workflow_state_creation(self):
        """Test FixWorkflowState can be created and accessed."""
        started_at = datetime.now()
        completed_at = datetime.now()

        fix_state = {
            "repository": "test/repo",
            "pr_number": 123,
            "check_name": "Tests",
            "fix_attempt_id": "fix_456",
            "failure_context": "Test failure in module X",
            "claude_prompt": "Fix the failing test",
            "fix_result": "Updated test assertion",
            "success": True,
            "error_message": None,
            "started_at": started_at,
            "completed_at": completed_at,
        }

        assert fix_state["repository"] == "test/repo"
        assert fix_state["pr_number"] == 123
        assert fix_state["check_name"] == "Tests"
        assert fix_state["fix_attempt_id"] == "fix_456"
        assert fix_state["fix_result"] == "Updated test assertion"
        assert fix_state["success"] is True
        assert fix_state["started_at"] == started_at
        assert fix_state["completed_at"] == completed_at


class TestEscalationWorkflowState:
    """Test EscalationWorkflowState TypedDict."""

    def test_escalation_workflow_state_creation(self):
        """Test EscalationWorkflowState can be created and accessed."""
        now = datetime.now()

        fix_attempt = FixAttempt(
            id="fix_123",
            timestamp=now,
            check_name="Security",
            context="Security issue",
            prompt="Fix security issue",
            status=FixAttemptStatus.FAILURE,
        )

        escalation_state = {
            "repository": "test/repo",
            "pr_number": 123,
            "check_name": "Security",
            "escalation_id": "esc_789",
            "reason": "Unfixable security vulnerability",
            "fix_attempts": [fix_attempt],
            "telegram_message": "Security issue requires manual review",
            "telegram_message_id": "msg_456",
            "acknowledged": True,
            "acknowledged_by": "@security-team",
            "resolution_notes": "Fixed by security team",
        }

        assert escalation_state["repository"] == "test/repo"
        assert escalation_state["pr_number"] == 123
        assert escalation_state["check_name"] == "Security"
        assert escalation_state["escalation_id"] == "esc_789"
        assert escalation_state["reason"] == "Unfixable security vulnerability"
        assert escalation_state["fix_attempts"] == [fix_attempt]
        assert escalation_state["telegram_message"] == "Security issue requires manual review"
        assert escalation_state["acknowledged"] is True
        assert escalation_state["acknowledged_by"] == "@security-team"


class TestSchemaValidation:
    """Test schema validation and error handling."""

    def test_check_info_validation_errors(self):
        """Test CheckInfo validation with invalid data."""
        # Missing required fields
        with pytest.raises(Exception):  # Pydantic ValidationError
            CheckInfo()  # type: ignore[call-arg]

        # Invalid status
        with pytest.raises(Exception):
            CheckInfo(
                name="Test",
                status="invalid_status",  # type: ignore[arg-type]
                details_url="http://example.com",
            )

    def test_fix_attempt_validation_errors(self):
        """Test FixAttempt validation with invalid data."""
        now = datetime.now()

        # Missing required fields
        with pytest.raises(Exception):
            FixAttempt()  # type: ignore[call-arg]

        # Invalid status
        with pytest.raises(Exception):
            FixAttempt(
                id="fix_123",
                timestamp=now,
                check_name="Test",
                context="Context",
                prompt="Prompt",
                status="invalid_status",  # type: ignore[arg-type]
            )

    def test_repository_config_validation_errors(self):
        """Test RepositoryConfig validation with invalid data."""
        # Missing required fields
        with pytest.raises(Exception):
            RepositoryConfig()  # type: ignore[call-arg]

        with pytest.raises(Exception):
            RepositoryConfig(owner="test")  # Missing repo
