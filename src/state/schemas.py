"""State schemas for PR Check Agent workflows
Defines the data structures used by LangGraph workflows
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class CheckStatus(str, Enum):
    """Status of a GitHub check."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"
    CANCELLED = "cancelled"


class FixAttemptStatus(str, Enum):
    """Status of a Claude Code fix attempt."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"


class EscalationStatus(str, Enum):
    """Status of human escalation."""

    NONE = "none"
    PENDING = "pending"
    NOTIFIED = "notified"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class CheckInfo(BaseModel):
    """Information about a GitHub check run."""

    name: str
    status: CheckStatus
    conclusion: str | None = None
    details_url: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_logs: str | None = None
    error_message: str | None = None

    class Config:
        use_enum_values = True


class FixAttempt(BaseModel):
    """Record of a Claude Code fix attempt."""

    id: str
    timestamp: datetime
    check_name: str
    context: str
    prompt: str
    result: str | None = None
    status: FixAttemptStatus
    error_message: str | None = None
    duration_seconds: float | None = None

    class Config:
        use_enum_values = True


class EscalationRecord(BaseModel):
    """Record of human escalation."""

    id: str
    timestamp: datetime
    check_name: str
    reason: str
    telegram_message_id: str | None = None
    status: EscalationStatus
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    resolution_notes: str | None = None

    class Config:
        use_enum_values = True


class PRInfo(BaseModel):
    """Information about a GitHub pull request."""

    number: int
    title: str
    author: str
    branch: str
    base_branch: str
    url: str
    created_at: datetime
    updated_at: datetime
    draft: bool = False
    mergeable: bool | None = None


class RepositoryConfig(BaseModel):
    """Configuration for a monitored repository."""

    owner: str
    repo: str
    branch_filter: list[str] = Field(default_factory=lambda: ["main"])
    check_types: list[str] = Field(default_factory=list)
    claude_context: dict[str, str] = Field(default_factory=dict)
    fix_limits: dict[str, Any] = Field(default_factory=dict)
    priorities: dict[str, dict[str, int]] = Field(default_factory=dict)
    notifications: dict[str, Any] = Field(default_factory=dict)


# LangGraph State Schemas (TypedDict format required by LangGraph)


class PRState(TypedDict):
    """State for a single PR workflow."""

    # PR Information
    pr_number: int
    repository: str
    pr_info: PRInfo | None

    # Check Status
    checks: dict[str, CheckInfo]
    failed_checks: list[str]

    # Fix Attempts
    fix_attempts: dict[str, list[FixAttempt]]
    current_fix_attempt: str | None

    # Escalation
    escalations: list[EscalationRecord]
    escalation_status: EscalationStatus

    # Workflow State
    last_updated: datetime
    workflow_step: str
    retry_count: int
    error_message: str | None


class MonitorState(TypedDict):
    """State for the main monitoring workflow."""

    # Repository Information
    repository: str
    config: RepositoryConfig

    # PR Tracking
    active_prs: dict[int, PRState]
    last_poll_time: datetime | None

    # Workflow Control
    polling_interval: int
    max_concurrent: int
    workflow_semaphore: Any  # asyncio.Semaphore

    # Error Tracking
    consecutive_errors: int
    last_error: str | None

    # Metrics
    total_prs_processed: int
    total_fixes_attempted: int
    total_fixes_successful: int
    total_escalations: int


class FixWorkflowState(TypedDict):
    """State for fix attempt workflow."""

    # Context
    repository: str
    pr_number: int
    check_name: str

    # Fix Information
    fix_attempt_id: str
    failure_context: str
    claude_prompt: str

    # Results
    fix_result: str | None
    success: bool
    error_message: str | None

    # Timing
    started_at: datetime
    completed_at: datetime | None


class EscalationWorkflowState(TypedDict):
    """State for escalation workflow."""

    # Context
    repository: str
    pr_number: int
    check_name: str

    # Escalation Information
    escalation_id: str
    reason: str
    fix_attempts: list[FixAttempt]

    # Notification
    telegram_message: str | None
    telegram_message_id: str | None

    # Resolution
    acknowledged: bool
    acknowledged_by: str | None
    resolution_notes: str | None
