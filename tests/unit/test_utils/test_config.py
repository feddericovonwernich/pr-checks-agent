"""Tests for configuration management utilities"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.utils.config import (
    Config,
    GlobalLimits,
    create_default_config,
    load_environment_config,
    validate_config_file,
)


class TestGlobalLimits:
    """Test GlobalLimits configuration model."""

    def test_global_limits_default_values(self):
        """Test GlobalLimits with default values."""
        limits = GlobalLimits()

        assert limits.max_daily_fixes == 50
        assert limits.max_concurrent_fixes == 5
        assert limits.rate_limits == {}
        assert limits.resource_limits == {}

    def test_global_limits_custom_values(self):
        """Test GlobalLimits with custom values."""
        limits = GlobalLimits(
            max_daily_fixes=100,
            max_concurrent_fixes=10,
            rate_limits={"github": 1000, "claude": 50},
            resource_limits={"memory_mb": 1024, "timeout_s": 120},
        )

        assert limits.max_daily_fixes == 100
        assert limits.max_concurrent_fixes == 10
        assert limits.rate_limits == {"github": 1000, "claude": 50}
        assert limits.resource_limits == {"memory_mb": 1024, "timeout_s": 120}

    def test_global_limits_validation_errors(self):
        """Test GlobalLimits validation constraints."""
        # Test minimum values
        with pytest.raises(ValidationError):
            GlobalLimits(max_daily_fixes=0)

        with pytest.raises(ValidationError):
            GlobalLimits(max_concurrent_fixes=0)

        # Test maximum values
        with pytest.raises(ValidationError):
            GlobalLimits(max_daily_fixes=2000)

        with pytest.raises(ValidationError):
            GlobalLimits(max_concurrent_fixes=50)


class TestConfig:
    """Test Config configuration model."""

    @pytest.fixture
    def sample_config_data(self):
        """Sample configuration data for testing."""
        return {
            "repositories": [
                {
                    "owner": "test-org",
                    "repo": "test-repo",
                    "branch_filter": ["main", "develop"],
                    "check_types": ["ci", "tests"],
                    "claude_context": {"language": "python", "framework": "fastapi"},
                    "fix_limits": {"max_attempts": 3, "escalation_enabled": True},
                    "priorities": {
                        "check_types": {"security": 1, "ci": 2},
                        "branch_priority": {"main": 0, "develop": 5},
                    },
                    "notifications": {"escalation_mentions": ["@dev-team"]},
                }
            ],
            "global_limits": {
                "max_daily_fixes": 100,
                "max_concurrent_fixes": 8,
                "rate_limits": {"github_api_calls_per_hour": 3000},
                "resource_limits": {"max_workflow_memory_mb": 256},
            },
        }

    @pytest.fixture
    def temp_config_file(self, sample_config_data):
        """Create temporary configuration file for testing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sample_config_data, f, indent=2)
            temp_path = f.name

        yield temp_path

        # Cleanup
        Path(temp_path).unlink(missing_ok=True)

    def test_config_default_creation(self):
        """Test Config creation with default values."""
        config = Config()

        assert config.repositories == []
        assert isinstance(config.global_limits, GlobalLimits)
        assert config.global_limits.max_daily_fixes == 50

    def test_config_load_valid_file(self, temp_config_file):
        """Test loading valid configuration file."""
        config = Config.load(temp_config_file)

        assert len(config.repositories) == 1
        repo = config.repositories[0]
        assert repo.owner == "test-org"
        assert repo.repo == "test-repo"
        assert repo.branch_filter == ["main", "develop"]

        assert config.global_limits.max_daily_fixes == 100
        assert config.global_limits.max_concurrent_fixes == 8

    def test_config_load_nonexistent_file(self):
        """Test loading nonexistent configuration file."""
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            Config.load("/nonexistent/config.json")

    def test_config_load_invalid_json(self):
        """Test loading configuration file with invalid JSON."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json }")
            temp_path = f.name

        try:
            with pytest.raises(ValueError, match="Invalid JSON in configuration file"):
                Config.load(temp_path)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_config_load_validation_error(self):
        """Test loading configuration with validation errors."""
        invalid_data = {"repositories": [{"owner": "test", "invalid_field": "value"}]}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(invalid_data, f)
            temp_path = f.name

        try:
            with pytest.raises(ValueError, match="Configuration validation error"):
                Config.load(temp_path)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_config_save(self, sample_config_data):
        """Test saving configuration to file."""
        config = Config(**sample_config_data)

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"
            config.save(str(config_path))

            assert config_path.exists()

            # Verify saved content
            saved_data = json.loads(config_path.read_text())

            assert len(saved_data["repositories"]) == 1
            assert saved_data["repositories"][0]["owner"] == "test-org"

    def test_config_save_create_directory(self, sample_config_data):
        """Test saving configuration creates parent directories."""
        config = Config(**sample_config_data)

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "nested" / "path" / "config.json"
            config.save(str(config_path))

            assert config_path.exists()
            assert config_path.parent.exists()

    @patch.dict(os.environ, {"GITHUB_TOKEN": "token", "ANTHROPIC_API_KEY": "key"}, clear=True)
    def test_validate_environment_partial_success(self, sample_config_data):
        """Test environment validation with some missing variables."""
        config = Config(**sample_config_data)

        result = config.validate_environment()

        assert result["valid"] is False
        assert "TELEGRAM_BOT_TOKEN" in result["missing_vars"]
        assert "TELEGRAM_CHAT_ID" in result["missing_vars"]

        # Check for REDIS_URL warning (full warning text includes "using defaults")
        redis_warnings = [w for w in result["warnings"] if "REDIS_URL not set" in w]
        assert len(redis_warnings) >= 1

    @patch.dict(
        os.environ,
        {
            "GITHUB_TOKEN": "token",
            "ANTHROPIC_API_KEY": "key",
            "TELEGRAM_BOT_TOKEN": "bot_token",
            "TELEGRAM_CHAT_ID": "chat_id",
        },
        clear=True,
    )
    def test_validate_environment_success(self, sample_config_data):
        """Test successful environment validation."""
        config = Config(**sample_config_data)

        result = config.validate_environment()

        assert result["valid"] is True
        assert result["missing_vars"] == []
        assert len(result["warnings"]) >= 1  # Should have warnings for optional vars

    def test_validate_environment_escalation_warning(self):
        """Test environment validation warns about escalation without Telegram."""
        config_data = {
            "repositories": [
                {
                    "owner": "test",
                    "repo": "test",
                    "fix_limits": {"escalation_enabled": True},
                }
            ]
        }
        config = Config(**config_data)

        with patch.dict(os.environ, {}, clear=True):
            result = config.validate_environment()

            escalation_warnings = [w for w in result["warnings"] if "escalation enabled" in w]
            assert len(escalation_warnings) >= 1

    def test_get_repository_config_success(self, sample_config_data):
        """Test successful repository config retrieval."""
        config = Config(**sample_config_data)

        repo_config = config.get_repository_config("test-org", "test-repo")

        assert repo_config.owner == "test-org"
        assert repo_config.repo == "test-repo"
        assert repo_config.branch_filter == ["main", "develop"]

    def test_get_repository_config_not_found(self, sample_config_data):
        """Test repository config retrieval for nonexistent repo."""
        config = Config(**sample_config_data)

        with pytest.raises(ValueError, match="No configuration found for repository"):
            config.get_repository_config("nonexistent", "repo")

    def test_get_effective_limits_repo_override(self, sample_config_data):
        """Test effective limits calculation with repository override."""
        config = Config(**sample_config_data)
        repo_config = config.repositories[0]
        repo_config.fix_limits = {"max_attempts": 5, "custom_limit": 123}

        effective_limits = config.get_effective_limits(repo_config)

        # Should combine global limits with repo-specific overrides
        assert effective_limits["max_daily_fixes"] == 100  # From global
        assert effective_limits["max_attempts"] == 5  # From repo override
        assert effective_limits["custom_limit"] == 123  # From repo only

    def test_get_effective_limits_global_only(self, sample_config_data):
        """Test effective limits with only global limits."""
        config = Config(**sample_config_data)
        repo_config = config.repositories[0]
        repo_config.fix_limits = {}

        effective_limits = config.get_effective_limits(repo_config)

        # Should only have global limits
        assert effective_limits["max_daily_fixes"] == 100
        assert effective_limits["max_concurrent_fixes"] == 8


class TestLoadEnvironmentConfig:
    """Test environment configuration loading."""

    @patch.dict(
        os.environ,
        {
            "GITHUB_TOKEN": "test_token",
            "ANTHROPIC_API_KEY": "test_key",
            "TELEGRAM_BOT_TOKEN": "test_bot",
            "TELEGRAM_CHAT_ID": "123456",
            "REDIS_URL": "redis://custom:6379/1",
            "LOG_LEVEL": "DEBUG",
            "WEBHOOK_SECRET": "secret123",
            "METRICS_PORT": "9090",
            "POLLING_INTERVAL": "600",
            "MAX_CONCURRENT_WORKFLOWS": "15",
            "MAX_FIX_ATTEMPTS": "5",
            "ESCALATION_COOLDOWN": "48",
            "WORKFLOW_TIMEOUT": "120",
        },
        clear=True,
    )
    def test_load_environment_config_all_set(self):
        """Test loading environment config with all variables set."""
        config = load_environment_config()

        assert config["github_token"] == "test_token"
        assert config["anthropic_api_key"] == "test_key"
        assert config["telegram_bot_token"] == "test_bot"
        assert config["telegram_chat_id"] == "123456"
        assert config["redis_url"] == "redis://custom:6379/1"
        assert config["log_level"] == "DEBUG"
        assert config["webhook_secret"] == "secret123"
        assert config["metrics_port"] == 9090
        assert config["polling_interval"] == 600
        assert config["max_concurrent_workflows"] == 15
        assert config["max_fix_attempts"] == 5
        assert config["escalation_cooldown"] == 48
        assert config["workflow_timeout"] == 120

    @patch.dict(os.environ, {}, clear=True)
    def test_load_environment_config_defaults(self):
        """Test loading environment config with default values."""
        config = load_environment_config()

        assert config["github_token"] is None
        assert config["anthropic_api_key"] is None
        assert config["redis_url"] == "redis://localhost:6379/0"
        assert config["log_level"] == "INFO"
        assert config["webhook_secret"] is None
        assert config["metrics_port"] == 8080
        assert config["polling_interval"] == 300
        assert config["max_concurrent_workflows"] == 10

    @patch.dict(os.environ, {"METRICS_PORT": "invalid"}, clear=True)
    def test_load_environment_config_invalid_int(self):
        """Test loading environment config with invalid integer values."""
        with pytest.raises(ValueError):
            load_environment_config()


class TestCreateDefaultConfig:
    """Test default configuration creation."""

    def test_create_default_config_structure(self):
        """Test default configuration structure."""
        config = create_default_config()

        assert len(config.repositories) == 1
        repo = config.repositories[0]
        assert repo.owner == "example-org"
        assert repo.repo == "example-repo"
        assert repo.branch_filter == ["main", "develop"]
        assert repo.check_types == ["ci", "tests", "linting"]

        assert config.global_limits.max_daily_fixes == 50
        assert config.global_limits.max_concurrent_fixes == 5

    def test_create_default_config_claude_context(self):
        """Test default Claude context configuration."""
        config = create_default_config()
        repo = config.repositories[0]

        assert repo.claude_context["project_type"] == "python"
        assert repo.claude_context["test_framework"] == "pytest"
        assert repo.claude_context["linting"] == "ruff"

    def test_create_default_config_priorities(self):
        """Test default priority configuration."""
        config = create_default_config()
        repo = config.repositories[0]

        assert repo.priorities["check_types"]["security"] == 1
        assert repo.priorities["check_types"]["tests"] == 2
        assert repo.priorities["branch_priority"]["main"] == 1


class TestValidateConfigFile:
    """Test configuration file validation."""

    @pytest.fixture
    def valid_config_file(self):
        """Create valid config file for testing."""
        config_data = {
            "repositories": [
                {
                    "owner": "test-org",
                    "repo": "test-repo",
                    "branch_filter": ["main"],
                    "fix_limits": {"max_attempts": 3},
                }
            ],
            "global_limits": {"max_daily_fixes": 25},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        yield temp_path
        Path(temp_path).unlink(missing_ok=True)

    def test_validate_config_file_success(self, valid_config_file):
        """Test successful configuration file validation."""
        result = validate_config_file(valid_config_file)

        assert result["valid"] is True
        assert result["errors"] == []
        assert result["stats"]["repositories_count"] == 1
        assert result["stats"]["total_branches_monitored"] == 1

    def test_validate_config_file_duplicate_repos(self):
        """Test validation catches duplicate repositories."""
        config_data = {
            "repositories": [
                {"owner": "test", "repo": "duplicate"},
                {"owner": "test", "repo": "duplicate"},  # Duplicate
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            result = validate_config_file(temp_path)

            assert result["valid"] is False
            assert any("Duplicate repository: test/duplicate" in error for error in result["errors"])
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_validate_config_file_high_attempts_warning(self):
        """Test validation warns about high max attempts."""
        config_data = {"repositories": [{"owner": "test", "repo": "test", "fix_limits": {"max_attempts": 15}}]}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            result = validate_config_file(temp_path)

            assert result["valid"] is True
            assert any("high max_attempts" in warning for warning in result["warnings"])
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_validate_config_file_high_daily_limit_warning(self):
        """Test validation warns about high daily fix limit."""
        config_data = {
            "repositories": [{"owner": "test", "repo": "test"}],
            "global_limits": {"max_daily_fixes": 300},
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            result = validate_config_file(temp_path)

            assert result["valid"] is True
            assert any("High daily fix limit" in warning for warning in result["warnings"])
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_validate_config_file_invalid(self):
        """Test validation of invalid configuration file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("invalid json")
            temp_path = f.name

        try:
            result = validate_config_file(temp_path)

            assert result["valid"] is False
            assert len(result["errors"]) > 0
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_validate_config_file_escalation_stats(self):
        """Test validation calculates escalation statistics."""
        config_data = {
            "repositories": [
                {"owner": "test1", "repo": "test1", "fix_limits": {"escalation_enabled": True}},
                {"owner": "test2", "repo": "test2", "fix_limits": {"escalation_enabled": False}},
                {"owner": "test3", "repo": "test3"},  # Default escalation_enabled = True
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            result = validate_config_file(temp_path)

            assert result["stats"]["escalation_enabled_repos"] == 2  # test1 and test3
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestConfigIntegration:
    """Integration tests for configuration management."""

    def test_complete_config_workflow(self):
        """Test complete configuration workflow."""
        # Step 1: Create default config
        config = create_default_config()
        assert len(config.repositories) == 1

        # Step 2: Modify config
        config.repositories[0].owner = "real-org"
        config.repositories[0].repo = "real-repo"
        config.global_limits.max_daily_fixes = 75

        # Step 3: Save config
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "integration_test.json"
            config.save(str(config_path))

            # Step 4: Load config
            loaded_config = Config.load(str(config_path))

            # Step 5: Verify loaded config matches
            assert loaded_config.repositories[0].owner == "real-org"
            assert loaded_config.repositories[0].repo == "real-repo"
            assert loaded_config.global_limits.max_daily_fixes == 75

            # Step 6: Validate config
            validation_result = validate_config_file(str(config_path))
            assert validation_result["valid"] is True

            # Step 7: Test repository lookup
            repo_config = loaded_config.get_repository_config("real-org", "real-repo")
            assert repo_config.owner == "real-org"

    @patch.dict(
        os.environ,
        {
            "GITHUB_TOKEN": "integration_token",
            "ANTHROPIC_API_KEY": "integration_key",
            "TELEGRAM_BOT_TOKEN": "integration_bot",
            "TELEGRAM_CHAT_ID": "integration_chat",
        },
        clear=True,
    )
    def test_config_environment_integration(self):
        """Test configuration with environment variable integration."""
        # Create config with escalation enabled
        config_data = {
            "repositories": [
                {
                    "owner": "test-org",
                    "repo": "test-repo",
                    "fix_limits": {"escalation_enabled": True},
                }
            ]
        }
        config = Config(**config_data)

        # Test environment validation
        env_result = config.validate_environment()
        assert env_result["valid"] is True
        assert env_result["missing_vars"] == []

        # Test environment config loading
        env_config = load_environment_config()
        assert env_config["github_token"] == "integration_token"
        assert env_config["anthropic_api_key"] == "integration_key"

        # Test effective limits
        repo_config = config.repositories[0]
        effective_limits = config.get_effective_limits(repo_config)
        assert "max_daily_fixes" in effective_limits
