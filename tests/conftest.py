"""
Pytest configuration and fixtures for PR Check Agent tests
"""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add src to Python path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.config import Config, create_default_config


@pytest.fixture
def mock_env_vars():
    """Mock all required environment variables."""
    env_vars = {
        'GITHUB_TOKEN': 'test_github_token_123',
        'ANTHROPIC_API_KEY': 'test_anthropic_key_456',
        'TELEGRAM_BOT_TOKEN': 'test_telegram_bot_789',
        'TELEGRAM_CHAT_ID': 'test_chat_id_101112',
        'REDIS_URL': 'redis://localhost:6379/0',
        'LOG_LEVEL': 'INFO',
        'METRICS_PORT': '8080',
        'POLLING_INTERVAL': '300',
        'MAX_CONCURRENT_WORKFLOWS': '10',
        'MAX_FIX_ATTEMPTS': '3',
        'ESCALATION_COOLDOWN': '24',
        'WORKFLOW_TIMEOUT': '60'
    }
    
    with patch.dict(os.environ, env_vars, clear=False):
        yield env_vars


@pytest.fixture
def sample_config():
    """Provide a sample configuration for testing."""
    return create_default_config()


@pytest.fixture
def temp_config_file(sample_config):
    """Create a temporary configuration file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        sample_config.save(f.name)
        yield f.name
    
    # Clean up
    if os.path.exists(f.name):
        os.unlink(f.name)


@pytest.fixture
def temp_logs_dir():
    """Create a temporary logs directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        logs_dir = Path(temp_dir) / "logs"
        logs_dir.mkdir()
        
        # Change to temp directory so logs are created there
        original_cwd = os.getcwd()
        os.chdir(temp_dir)
        
        yield logs_dir
        
        # Restore original directory
        os.chdir(original_cwd)


@pytest.fixture
def mock_redis():
    """Mock Redis client for testing."""
    with patch('redis.Redis') as mock_redis_class:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.get.return_value = None
        mock_client.set.return_value = True
        mock_client.delete.return_value = 1
        mock_client.keys.return_value = []
        mock_client.incr.return_value = 1
        mock_client.ttl.return_value = -1
        mock_client.info.return_value = {
            'redis_version': '6.0.0',
            'connected_clients': 1,
            'used_memory_human': '1M'
        }
        
        mock_redis_class.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_github_api():
    """Mock GitHub API responses."""
    with patch('github.Github') as mock_github_class:
        mock_github = MagicMock()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        
        # Mock GitHub user
        mock_user = MagicMock()
        mock_user.login = "test-user"
        mock_github.get_user.return_value = mock_user
        
        # Mock repository
        mock_github.get_repo.return_value = mock_repo
        
        # Mock pull request
        mock_pr.number = 1
        mock_pr.title = "Test PR"
        mock_pr.user.login = "test-author"
        mock_pr.head.ref = "feature-branch"
        mock_pr.base.ref = "main"
        mock_pr.html_url = "https://github.com/test/repo/pull/1"
        mock_pr.created_at = "2023-01-01T00:00:00Z"
        mock_pr.updated_at = "2023-01-01T01:00:00Z"
        mock_pr.draft = False
        mock_pr.mergeable = True
        
        mock_repo.get_pulls.return_value = [mock_pr]
        
        # Mock commits and checks
        mock_commit = MagicMock()
        mock_commit.sha = "abc123def456"
        mock_pr.get_commits.return_value = [mock_commit]
        mock_pr.get_commits.return_value.totalCount = 1
        
        mock_check_run = MagicMock()
        mock_check_run.name = "CI"
        mock_check_run.status = "completed"
        mock_check_run.conclusion = "success"
        mock_check_run.html_url = "https://github.com/test/repo/runs/123"
        mock_check_run.started_at = "2023-01-01T00:30:00Z"
        mock_check_run.completed_at = "2023-01-01T00:45:00Z"
        
        mock_commit.get_check_runs.return_value = [mock_check_run]
        mock_commit.get_statuses.return_value = []
        
        # Mock rate limit
        mock_rate_limit = MagicMock()
        mock_rate_limit.core.limit = 5000
        mock_rate_limit.core.remaining = 4999
        mock_rate_limit.core.reset = "2023-01-01T02:00:00Z"
        mock_github.get_rate_limit.return_value = mock_rate_limit
        
        mock_github_class.return_value = mock_github
        yield mock_github


@pytest.fixture
def mock_telegram_bot():
    """Mock Telegram Bot API."""
    with patch('telegram.Bot') as mock_bot_class:
        mock_bot = MagicMock()
        
        # Mock bot info
        mock_bot_user = MagicMock()
        mock_bot_user.username = "test_bot"
        mock_bot_user.id = 123456789
        mock_bot.get_me.return_value = mock_bot_user
        
        # Mock message sending
        mock_message = MagicMock()
        mock_message.message_id = 12345
        mock_bot.send_message.return_value = mock_message
        
        mock_bot_class.return_value = mock_bot
        yield mock_bot


@pytest.fixture
def mock_claude_cli():
    """Mock Claude Code CLI subprocess calls."""
    with patch('subprocess.run') as mock_run:
        # Mock successful Claude CLI response
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"analysis": "Test analysis", "fixable": true}'
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        yield mock_run


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Set up test environment before each test."""
    # Ensure logs directory exists
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    yield
    
    # Clean up any test artifacts
    # Note: Don't remove logs directory as it might be used by other processes


@pytest.fixture
def sample_pr_state():
    """Sample PR state for testing."""
    from state.schemas import PRState
    from datetime import datetime
    
    return {
        "pr_number": 1,
        "repository": "test/repo",
        "pr_info": {
            "number": 1,
            "title": "Test PR",
            "author": "test-user",
            "branch": "feature-branch",
            "base_branch": "main",
            "url": "https://github.com/test/repo/pull/1",
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "draft": False,
            "mergeable": True
        },
        "checks": {
            "CI": {
                "name": "CI",
                "status": "failure",
                "conclusion": "failure",
                "details_url": "https://github.com/test/repo/runs/123",
                "started_at": datetime.now(),
                "completed_at": datetime.now(),
                "failure_logs": "Test failed: assertion error"
            }
        },
        "failed_checks": ["CI"],
        "fix_attempts": {},
        "current_fix_attempt": None,
        "escalations": [],
        "escalation_status": "none",
        "last_updated": datetime.now(),
        "workflow_step": "discovered",
        "retry_count": 0,
        "error_message": None
    }


@pytest.fixture
def sample_monitor_state(sample_config):
    """Sample monitoring state for testing."""
    from state.schemas import MonitorState
    from datetime import datetime
    
    return {
        "repository": "test/repo",
        "config": sample_config.repositories[0],
        "active_prs": {},
        "last_poll_time": None,
        "polling_interval": 300,
        "max_concurrent": 10,
        "workflow_semaphore": None,
        "consecutive_errors": 0,
        "last_error": None,
        "total_prs_processed": 0,
        "total_fixes_attempted": 0,
        "total_fixes_successful": 0,
        "total_escalations": 0
    }