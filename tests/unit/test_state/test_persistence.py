"""Tests for state persistence layer"""

import pickle
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.state.persistence import StatePersistence
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


class TestStatePersistence:
    """Test StatePersistence class."""

    @patch("redis.Redis")
    def test_init_success(self, mock_redis_class):
        """Test successful initialization."""
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis_class.return_value = mock_client

        persistence = StatePersistence("redis://localhost:6379/0")

        # Verify Redis client was created with correct parameters
        mock_redis_class.assert_called_once_with(
            host="localhost", port=6379, db=0, decode_responses=False, socket_connect_timeout=5, socket_timeout=5
        )

        # Verify ping was called
        mock_client.ping.assert_called_once()
        assert persistence.redis_client == mock_client

    @patch("redis.Redis")
    def test_init_custom_url(self, mock_redis_class):
        """Test initialization with custom Redis URL."""
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis_class.return_value = mock_client

        persistence = StatePersistence("redis://user:pass@redis-host:6380/2")

        mock_redis_class.assert_called_once_with(
            host="redis-host", port=6380, db=2, decode_responses=False, socket_connect_timeout=5, socket_timeout=5
        )

    @patch("redis.Redis")
    def test_init_connection_failure(self, mock_redis_class):
        """Test initialization with connection failure."""
        mock_client = MagicMock()
        mock_client.ping.side_effect = Exception("Connection failed")
        mock_redis_class.return_value = mock_client

        with pytest.raises(Exception, match="Connection failed"):
            StatePersistence("redis://localhost:6379/0")

    def test_make_serializable_datetime(self):
        """Test datetime serialization."""
        persistence = StatePersistence.__new__(StatePersistence)  # Create without __init__

        now = datetime(2024, 1, 1, 12, 0, 0)
        result = persistence._make_serializable(now)

        assert result == "2024-01-01T12:00:00"

    def test_make_serializable_pydantic_model(self):
        """Test Pydantic model serialization."""
        persistence = StatePersistence.__new__(StatePersistence)

        pr_info = PRInfo(
            number=123,
            title="Test PR",
            author="developer",
            branch="feature",
            base_branch="main",
            url="https://github.com/test/repo/pull/123",
            created_at=datetime(2024, 1, 1, 12, 0, 0),
            updated_at=datetime(2024, 1, 1, 13, 0, 0),
        )

        result = persistence._make_serializable(pr_info)

        assert isinstance(result, dict)
        assert result["number"] == 123
        assert result["title"] == "Test PR"
        # The _make_serializable should recursively convert datetime objects
        assert result["created_at"] == "2024-01-01T12:00:00"

    def test_make_serializable_dict(self):
        """Test dictionary serialization."""
        persistence = StatePersistence.__new__(StatePersistence)

        test_dict = {
            "timestamp": datetime(2024, 1, 1, 12, 0, 0),
            "nested": {"date": datetime(2024, 1, 2, 13, 0, 0), "value": 42},
        }

        result = persistence._make_serializable(test_dict)

        assert result["timestamp"] == "2024-01-01T12:00:00"
        assert result["nested"]["date"] == "2024-01-02T13:00:00"
        assert result["nested"]["value"] == 42

    def test_make_serializable_list(self):
        """Test list serialization."""
        persistence = StatePersistence.__new__(StatePersistence)

        test_list = [datetime(2024, 1, 1, 12, 0, 0), "string", 42, {"date": datetime(2024, 1, 2, 13, 0, 0)}]

        result = persistence._make_serializable(test_list)

        assert result[0] == "2024-01-01T12:00:00"
        assert result[1] == "string"
        assert result[2] == 42
        assert result[3]["date"] == "2024-01-02T13:00:00"

    def test_serialize_deserialize_roundtrip(self):
        """Test serialization/deserialization roundtrip."""
        persistence = StatePersistence.__new__(StatePersistence)

        # Create complex state data
        now = datetime.now()
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

        original_data = {"pr_info": pr_info, "timestamp": now, "nested": {"value": 42}}

        # Serialize then deserialize
        serialized = persistence._serialize_state(original_data)
        assert isinstance(serialized, bytes)

        deserialized = persistence._deserialize_state(serialized)

        # Verify structure is preserved
        assert "pr_info" in deserialized
        assert "timestamp" in deserialized
        assert "nested" in deserialized
        assert deserialized["nested"]["value"] == 42


class TestStatePersistenceRedisOperations:
    """Test Redis operations with mocked Redis client."""

    @pytest.fixture
    def persistence(self):
        """Create StatePersistence with mocked Redis client."""
        with patch("redis.Redis") as mock_redis_class:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_redis_class.return_value = mock_client

            persistence = StatePersistence()
            persistence.redis_client = mock_client  # Ensure we have the mock
            return persistence

    def test_save_monitor_state_success(self, persistence):
        """Test successful monitor state save."""
        config = RepositoryConfig(owner="test", repo="repo")
        state = {
            "repository": "test/repo",
            "config": config,
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
            "total_escalations": 0,
        }

        persistence.redis_client.set.return_value = True

        result = persistence.save_monitor_state("test/repo", state)

        assert result is True
        persistence.redis_client.set.assert_called_once()
        call_args = persistence.redis_client.set.call_args
        assert call_args[0][0] == "monitor_state:test/repo"  # key
        assert isinstance(call_args[0][1], bytes)  # serialized data
        assert call_args[1]["ex"] == 86400  # TTL

    def test_save_monitor_state_failure(self, persistence):
        """Test monitor state save failure."""
        config = RepositoryConfig(owner="test", repo="repo")
        state = {
            "repository": "test/repo",
            "config": config,
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
            "total_escalations": 0,
        }

        persistence.redis_client.set.side_effect = Exception("Redis error")

        result = persistence.save_monitor_state("test/repo", state)

        assert result is False

    def test_load_monitor_state_success(self, persistence):
        """Test successful monitor state load."""
        # Create sample state data to return
        config = RepositoryConfig(owner="test", repo="repo")
        original_state = {
            "repository": "test/repo",
            "config": config.dict(),  # Config will be serialized
            "active_prs": {},
            "polling_interval": 300,
        }

        serialized_data = pickle.dumps(original_state)
        persistence.redis_client.get.return_value = serialized_data

        result = persistence.load_monitor_state("test/repo")

        assert result is not None
        assert result["repository"] == "test/repo"  # type: ignore[index]
        assert result["polling_interval"] == 300  # type: ignore[index]

        persistence.redis_client.get.assert_called_once_with("monitor_state:test/repo")

    def test_load_monitor_state_not_found(self, persistence):
        """Test monitor state load when key doesn't exist."""
        persistence.redis_client.get.return_value = None

        result = persistence.load_monitor_state("test/repo")

        assert result is None

    def test_load_monitor_state_failure(self, persistence):
        """Test monitor state load failure."""
        persistence.redis_client.get.side_effect = Exception("Redis error")

        result = persistence.load_monitor_state("test/repo")

        assert result is None

    def test_save_pr_state_success(self, persistence):
        """Test successful PR state save."""
        now = datetime.now()
        pr_info = PRInfo(
            number=123,
            title="Test PR",
            author="dev",
            branch="feature",
            base_branch="main",
            url="https://github.com/test/repo/pull/123",
            created_at=now,
            updated_at=now,
        )

        state = {
            "pr_number": 123,
            "repository": "test/repo",
            "pr_info": pr_info,
            "checks": {},
            "failed_checks": [],
            "fix_attempts": {},
            "current_fix_attempt": None,
            "escalations": [],
            "escalation_status": EscalationStatus.NONE,
            "last_updated": now,
            "workflow_step": "discovered",
            "retry_count": 0,
            "error_message": None,
        }

        persistence.redis_client.set.return_value = True

        result = persistence.save_pr_state("test/repo", 123, state)

        assert result is True
        persistence.redis_client.set.assert_called_once()
        call_args = persistence.redis_client.set.call_args
        assert call_args[0][0] == "pr_state:test/repo:123"
        assert call_args[1]["ex"] == 604800  # 7 day TTL

    def test_load_pr_state_success(self, persistence):
        """Test successful PR state load."""
        # Create sample PR state data
        sample_state = {"pr_number": 123, "repository": "test/repo", "workflow_step": "analyzing"}

        serialized_data = pickle.dumps(sample_state)
        persistence.redis_client.get.return_value = serialized_data

        result = persistence.load_pr_state("test/repo", 123)

        assert result is not None
        assert result["pr_number"] == 123  # type: ignore[index]
        assert result["repository"] == "test/repo"  # type: ignore[index]

        persistence.redis_client.get.assert_called_once_with("pr_state:test/repo:123")

    def test_delete_pr_state_success(self, persistence):
        """Test successful PR state deletion."""
        persistence.redis_client.delete.return_value = 1  # 1 key deleted

        result = persistence.delete_pr_state("test/repo", 123)

        assert result is True
        persistence.redis_client.delete.assert_called_once_with("pr_state:test/repo:123")

    def test_delete_pr_state_not_found(self, persistence):
        """Test PR state deletion when key doesn't exist."""
        persistence.redis_client.delete.return_value = 0  # No keys deleted

        result = persistence.delete_pr_state("test/repo", 123)

        assert result is False

    def test_get_active_prs_success(self, persistence):
        """Test successful retrieval of active PRs."""
        # Mock Redis keys() to return PR keys
        pr_keys = [b"pr_state:test/repo:123", b"pr_state:test/repo:456"]
        persistence.redis_client.keys.return_value = pr_keys

        # Mock Redis get() for each key
        sample_states = {
            b"pr_state:test/repo:123": pickle.dumps({"pr_number": 123, "workflow_step": "analyzing"}),
            b"pr_state:test/repo:456": pickle.dumps({"pr_number": 456, "workflow_step": "fixing"}),
        }

        def mock_get(key):
            return sample_states.get(key)

        persistence.redis_client.get.side_effect = mock_get

        result = persistence.get_active_prs("test/repo")

        assert len(result) == 2
        assert 123 in result
        assert 456 in result
        assert result[123]["workflow_step"] == "analyzing"  # type: ignore[index]
        assert result[456]["workflow_step"] == "fixing"  # type: ignore[index]

        persistence.redis_client.keys.assert_called_once_with("pr_state:test/repo:*")

    def test_get_active_prs_empty(self, persistence):
        """Test get_active_prs with no active PRs."""
        persistence.redis_client.keys.return_value = []

        result = persistence.get_active_prs("test/repo")

        assert result == {}

    def test_get_active_prs_failure(self, persistence):
        """Test get_active_prs with Redis failure."""
        persistence.redis_client.keys.side_effect = Exception("Redis error")

        result = persistence.get_active_prs("test/repo")

        assert result == {}

    def test_increment_counter_success(self, persistence):
        """Test successful counter increment."""
        persistence.redis_client.incr.return_value = 5

        result = persistence.increment_counter("test_counter", 2)

        assert result == 5
        persistence.redis_client.incr.assert_called_once_with("test_counter", 2)

    def test_increment_counter_failure(self, persistence):
        """Test counter increment failure."""
        persistence.redis_client.incr.side_effect = Exception("Redis error")

        result = persistence.increment_counter("test_counter")

        assert result == 0

    def test_set_counter_success(self, persistence):
        """Test successful counter set."""
        persistence.redis_client.set.return_value = True

        result = persistence.set_counter("test_counter", 42, ttl=3600)

        assert result is True
        persistence.redis_client.set.assert_called_once_with("test_counter", 42, ex=3600)

    def test_set_counter_no_ttl(self, persistence):
        """Test counter set without TTL."""
        persistence.redis_client.set.return_value = True

        result = persistence.set_counter("test_counter", 42)

        assert result is True
        persistence.redis_client.set.assert_called_once_with("test_counter", 42)

    def test_get_counter_success(self, persistence):
        """Test successful counter get."""
        persistence.redis_client.get.return_value = b"42"

        result = persistence.get_counter("test_counter")

        assert result == 42

    def test_get_counter_not_found(self, persistence):
        """Test counter get when key doesn't exist."""
        persistence.redis_client.get.return_value = None

        result = persistence.get_counter("test_counter")

        assert result == 0

    def test_cleanup_old_states(self, persistence):
        """Test cleanup of old states."""
        # Mock keys to return some PR state keys
        pr_keys = [b"pr_state:test/repo:123", b"pr_state:test/repo:456"]
        persistence.redis_client.keys.return_value = pr_keys

        # Mock TTL responses (in seconds)
        ttl_responses = {
            b"pr_state:test/repo:123": 172800,  # 2 days remaining
            b"pr_state:test/repo:456": 3600,  # 1 hour remaining
        }

        def mock_ttl(key):
            return ttl_responses.get(key, -1)

        persistence.redis_client.ttl.side_effect = mock_ttl

        result = persistence.cleanup_old_states()

        # Should not delete anything (relies on Redis TTL)
        assert result == 0
        persistence.redis_client.keys.assert_called_once_with("pr_state:*")

    def test_health_check_success(self, persistence):
        """Test successful health check."""
        # Mock Redis operations
        persistence.redis_client.set.return_value = True
        persistence.redis_client.get.return_value = b"test"
        persistence.redis_client.delete.return_value = 1

        # Mock Redis info
        mock_info = {
            "redis_version": "7.0.0",
            "connected_clients": 2,
            "used_memory_human": "1.5M",
            "db0": {"keys": 100, "expires": 10},
        }
        persistence.redis_client.info.return_value = mock_info

        result = persistence.health_check()

        assert result["status"] == "healthy"
        assert result["redis_version"] == "7.0.0"
        assert result["connected_clients"] == 2
        assert result["used_memory_human"] == "1.5M"
        assert result["keyspace"] == {"keys": 100, "expires": 10}

    def test_health_check_failure(self, persistence):
        """Test health check failure."""
        persistence.redis_client.set.side_effect = Exception("Connection lost")

        result = persistence.health_check()

        assert result["status"] == "unhealthy"
        assert "error" in result
        assert "Connection lost" in result["error"]


class TestStatePersistenceIntegration:
    """Integration-style tests with real serialization."""

    @pytest.fixture
    def persistence(self):
        """Create StatePersistence with mocked Redis client but real serialization."""
        with patch("redis.Redis") as mock_redis_class:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_redis_class.return_value = mock_client

            return StatePersistence()

    def test_full_state_serialization_roundtrip(self, persistence):
        """Test complete state serialization and deserialization."""
        now = datetime.now()

        # Create complex state with all model types
        pr_info = PRInfo(
            number=123,
            title="Test PR with complex data",
            author="developer",
            branch="feature-branch",
            base_branch="main",
            url="https://github.com/test/repo/pull/123",
            created_at=now,
            updated_at=now,
            draft=False,
            mergeable=True,
        )

        check_info = CheckInfo(
            name="CI Build",
            status=CheckStatus.FAILURE,
            conclusion="failure",
            details_url="https://github.com/test/repo/runs/123",
            started_at=now,
            completed_at=now,
            failure_logs="Build failed: missing dependency",
            error_message="ModuleNotFoundError: No module named 'missing_lib'",
        )

        fix_attempt = FixAttempt(
            id="fix_123",
            timestamp=now,
            check_name="CI Build",
            context="Build failure due to missing dependency",
            prompt="Add missing dependency to requirements",
            result="Added 'missing_lib==1.0.0' to requirements.txt",
            status=FixAttemptStatus.SUCCESS,
            duration_seconds=45.7,
        )

        escalation = EscalationRecord(
            id="esc_456",
            timestamp=now,
            check_name="Security Scan",
            reason="High severity vulnerability",
            telegram_message_id="msg_789",
            status=EscalationStatus.ACKNOWLEDGED,
            acknowledged_by="@security-team",
            acknowledged_at=now,
            resolution_notes="Patched vulnerability in dependency",
        )

        # Create PR state with all components
        pr_state = {
            "pr_number": 123,
            "repository": "test/repo",
            "pr_info": pr_info,
            "checks": {"CI Build": check_info, "Tests": check_info},
            "failed_checks": ["CI Build"],
            "fix_attempts": {"CI Build": [fix_attempt]},
            "current_fix_attempt": "fix_123",
            "escalations": [escalation],
            "escalation_status": EscalationStatus.ACKNOWLEDGED,
            "last_updated": now,
            "workflow_step": "fixing",
            "retry_count": 2,
            "error_message": "Temporary API rate limit exceeded",
        }

        # Test serialization
        serialized = persistence._serialize_state(pr_state)
        assert isinstance(serialized, bytes)
        assert len(serialized) > 0

        # Test deserialization
        deserialized = persistence._deserialize_state(serialized)

        # Verify structure
        assert deserialized["pr_number"] == 123
        assert deserialized["repository"] == "test/repo"
        assert "pr_info" in deserialized
        assert "checks" in deserialized
        assert len(deserialized["checks"]) == 2
        assert "CI Build" in deserialized["checks"]
        assert deserialized["failed_checks"] == ["CI Build"]
        assert len(deserialized["fix_attempts"]["CI Build"]) == 1
        assert deserialized["escalation_status"] == "acknowledged"  # Enum value
        assert deserialized["workflow_step"] == "fixing"
        assert deserialized["retry_count"] == 2
