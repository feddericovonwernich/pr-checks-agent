"""
State schemas for PR Check Agent workflows
Defines the data structures used by LangGraph workflows
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from typing_extensions import TypedDict

from pydantic import BaseModel, Field


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
    conclusion: Optional[str] = None
    details_url: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failure_logs: Optional[str] = None
    error_message: Optional[str] = None
    
    class Config:
        use_enum_values = True


class FixAttempt(BaseModel):
    """Record of a Claude Code fix attempt."""
    id: str
    timestamp: datetime
    check_name: str
    context: str
    prompt: str
    result: Optional[str] = None
    status: FixAttemptStatus
    error_message: Optional[str] = None
    duration_seconds: Optional[float] = None
    
    class Config:
        use_enum_values = True


class EscalationRecord(BaseModel):
    """Record of human escalation."""
    id: str
    timestamp: datetime
    check_name: str
    reason: str
    telegram_message_id: Optional[str] = None
    status: EscalationStatus
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    
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
    mergeable: Optional[bool] = None


class RepositoryConfig(BaseModel):
    """Configuration for a monitored repository."""
    owner: str
    repo: str
    branch_filter: List[str] = Field(default_factory=lambda: ["main"])
    check_types: List[str] = Field(default_factory=list)
    claude_context: Dict[str, str] = Field(default_factory=dict)
    fix_limits: Dict[str, Any] = Field(default_factory=dict)
    priorities: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    notifications: Dict[str, Any] = Field(default_factory=dict)


# LangGraph State Schemas (TypedDict format required by LangGraph)

class PRState(TypedDict):
    """State for a single PR workflow."""
    # PR Information
    pr_number: int
    repository: str
    pr_info: Optional[PRInfo]
    
    # Check Status
    checks: Dict[str, CheckInfo]
    failed_checks: List[str]
    
    # Fix Attempts
    fix_attempts: Dict[str, List[FixAttempt]]
    current_fix_attempt: Optional[str]
    
    # Escalation
    escalations: List[EscalationRecord]
    escalation_status: EscalationStatus
    
    # Workflow State
    last_updated: datetime
    workflow_step: str
    retry_count: int
    error_message: Optional[str]


class MonitorState(TypedDict):
    """State for the main monitoring workflow."""
    # Repository Information
    repository: str
    config: RepositoryConfig
    
    # PR Tracking
    active_prs: Dict[int, PRState]
    last_poll_time: Optional[datetime]
    
    # Workflow Control
    polling_interval: int
    max_concurrent: int
    workflow_semaphore: Any  # asyncio.Semaphore
    
    # Error Tracking
    consecutive_errors: int
    last_error: Optional[str]
    
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
    fix_result: Optional[str]
    success: bool
    error_message: Optional[str]
    
    # Timing
    started_at: datetime
    completed_at: Optional[datetime]


class EscalationWorkflowState(TypedDict):
    """State for escalation workflow."""
    # Context
    repository: str
    pr_number: int
    check_name: str
    
    # Escalation Information
    escalation_id: str
    reason: str
    fix_attempts: List[FixAttempt]
    
    # Notification
    telegram_message: Optional[str]
    telegram_message_id: Optional[str]
    
    # Resolution
    acknowledged: bool
    acknowledged_by: Optional[str]
    resolution_notes: Optional[str]