"""State persistence layer for PR Check Agent
Handles saving and loading workflow state to/from Redis
"""

import pickle  # nosec B403 - pickle is used for trusted Redis data serialization only
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import redis
from loguru import logger
from pydantic import BaseModel

from .schemas import MonitorState, PRState


class StatePersistence:
    """Handles state persistence using Redis."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """Initialize Redis connection."""
        self.redis_url = redis_url
        parsed_url = urlparse(redis_url)

        self.redis_client = redis.Redis(
            host=parsed_url.hostname or "localhost",
            port=parsed_url.port or 6379,
            db=int(parsed_url.path.lstrip("/")) if parsed_url.path else 0,
            decode_responses=False,  # We'll handle encoding ourselves
            socket_connect_timeout=5,
            socket_timeout=5,
        )

        # Test connection
        try:
            self.redis_client.ping()
            logger.info(f"Connected to Redis at {redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def _serialize_state(self, state: Any) -> bytes:
        """Serialize state for storage."""
        # Convert datetime objects and other non-JSON types
        serializable_state = self._make_serializable(state)
        return pickle.dumps(serializable_state)

    def _deserialize_state(self, data: bytes) -> Any:
        """Deserialize state from storage."""
        return pickle.loads(data)  # nosec B301 - data comes from trusted Redis storage only

    def _make_serializable(self, obj: Any) -> Any:
        """Convert object to JSON-serializable format."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, BaseModel):
            # Recursively apply serialization to the model's dict representation
            return self._make_serializable(obj.dict())
        if isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._make_serializable(item) for item in obj]
        return obj

    def save_monitor_state(self, repository: str, state: MonitorState) -> bool:
        """Save monitoring state for a repository."""
        try:
            key = f"monitor_state:{repository}"
            data = self._serialize_state(state)
            self.redis_client.set(key, data, ex=86400)  # 24 hour TTL
            logger.debug(f"Saved monitor state for {repository}")
            return True
        except Exception as e:
            logger.error(f"Failed to save monitor state for {repository}: {e}")
            return False

    def load_monitor_state(self, repository: str) -> MonitorState | None:
        """Load monitoring state for a repository."""
        try:
            key = f"monitor_state:{repository}"
            data = self.redis_client.get(key)
            if data:
                # Cast to bytes since redis-py returns bytes for binary data
                state = self._deserialize_state(bytes(data))  # type: ignore[arg-type]
                logger.debug(f"Loaded monitor state for {repository}")
                return state  # type: ignore[return-value]
            return None
        except Exception as e:
            logger.error(f"Failed to load monitor state for {repository}: {e}")
            return None

    def save_pr_state(self, repository: str, pr_number: int, state: PRState) -> bool:
        """Save PR state."""
        try:
            key = f"pr_state:{repository}:{pr_number}"
            data = self._serialize_state(state)
            self.redis_client.set(key, data, ex=604800)  # 7 day TTL
            logger.debug(f"Saved PR state for {repository}#{pr_number}")
            return True
        except Exception as e:
            logger.error(f"Failed to save PR state for {repository}#{pr_number}: {e}")
            return False

    def load_pr_state(self, repository: str, pr_number: int) -> PRState | None:
        """Load PR state."""
        try:
            key = f"pr_state:{repository}:{pr_number}"
            data = self.redis_client.get(key)
            if data:
                state = self._deserialize_state(bytes(data))  # type: ignore[arg-type]
                logger.debug(f"Loaded PR state for {repository}#{pr_number}")
                return state  # type: ignore[return-value]
            return None
        except Exception as e:
            logger.error(f"Failed to load PR state for {repository}#{pr_number}: {e}")
            return None

    def delete_pr_state(self, repository: str, pr_number: int) -> bool:
        """Delete PR state (when PR is closed/merged)."""
        try:
            key = f"pr_state:{repository}:{pr_number}"
            deleted = self.redis_client.delete(key)
            if deleted:
                logger.debug(f"Deleted PR state for {repository}#{pr_number}")
            return bool(deleted)
        except Exception as e:
            logger.error(f"Failed to delete PR state for {repository}#{pr_number}: {e}")
            return False

    def get_active_prs(self, repository: str) -> dict[int, PRState]:
        """Get all active PR states for a repository."""
        try:
            pattern = f"pr_state:{repository}:*"
            keys = self.redis_client.keys(pattern)  # type: ignore[misc]
            active_prs: dict[int, PRState] = {}

            for key in keys:  # type: ignore[union-attr]
                # Extract PR number from key
                key_str = key.decode() if hasattr(key, "decode") else str(key)  # type: ignore[misc]
                pr_number = int(key_str.split(":")[-1])
                data = self.redis_client.get(key)
                if data:
                    state = self._deserialize_state(bytes(data))  # type: ignore[arg-type]
                    active_prs[pr_number] = state  # type: ignore[assignment]

            logger.debug(f"Loaded {len(active_prs)} active PRs for {repository}")
            return active_prs
        except Exception as e:
            logger.error(f"Failed to get active PRs for {repository}: {e}")
            return {}

    def increment_counter(self, key: str, amount: int = 1) -> int:
        """Increment a counter and return new value."""
        try:
            result = self.redis_client.incr(key, amount)
            return int(result) if result is not None else 0  # type: ignore[arg-type]
        except Exception as e:
            logger.error(f"Failed to increment counter {key}: {e}")
            return 0

    def set_counter(self, key: str, value: int, ttl: int | None = None) -> bool:
        """Set a counter value."""
        try:
            if ttl:
                self.redis_client.set(key, value, ex=ttl)
            else:
                self.redis_client.set(key, value)
            return True
        except Exception as e:
            logger.error(f"Failed to set counter {key}: {e}")
            return False

    def get_counter(self, key: str) -> int:
        """Get counter value."""
        try:
            value = self.redis_client.get(key)
            return int(value) if value is not None else 0  # type: ignore[arg-type]
        except Exception as e:
            logger.error(f"Failed to get counter {key}: {e}")
            return 0

    def cleanup_old_states(self, max_age_days: int = 30) -> int:
        """Clean up old state entries."""
        try:
            # This is a simple cleanup - in production you might want more sophisticated logic
            pattern = "pr_state:*"
            keys = self.redis_client.keys(pattern)  # type: ignore[misc]
            deleted = 0

            for key in keys:  # type: ignore[union-attr]
                # Check TTL - if it's close to expiring, let Redis handle it
                ttl = self.redis_client.ttl(key)  # type: ignore[misc]
                ttl_int = int(ttl) if ttl is not None else 0  # type: ignore[arg-type]
                if ttl_int < 86400:  # Less than 1 day remaining
                    continue

                # Additional cleanup logic could go here
                # For now, we rely on Redis TTL

            logger.info(f"Cleanup completed, processed {len(keys)} keys")  # type: ignore[arg-type]
            return deleted
        except Exception as e:
            logger.error(f"Failed to cleanup old states: {e}")
            return 0

    def health_check(self) -> dict[str, Any]:
        """Perform health check on Redis connection."""
        try:
            # Test basic operations
            test_key = "health_check_test"
            self.redis_client.set(test_key, "test", ex=10)
            value = self.redis_client.get(test_key)
            self.redis_client.delete(test_key)

            # Get Redis info
            info = self.redis_client.info()  # type: ignore[misc]

            return {
                "status": "healthy",
                "redis_version": info.get("redis_version"),  # type: ignore[union-attr]
                "connected_clients": info.get("connected_clients"),  # type: ignore[union-attr]
                "used_memory_human": info.get("used_memory_human"),  # type: ignore[union-attr]
                "keyspace": info.get("db0", {}),  # type: ignore[union-attr]
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
