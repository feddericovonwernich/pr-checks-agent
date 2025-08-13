"""
Tests for configuration management
"""

import os
import json
import tempfile
import pytest
from unittest.mock import patch
from pathlib import Path

from src.utils.config import (
    Config, 
    RepositoryConfig, 
    GlobalLimits,
    load_environment_config,
    create_default_config,
    validate_config_file
)


class TestRepositoryConfig:
    """Test cases for RepositoryConfig model."""
    
    def test_repository_config_minimal(self):
        """Test RepositoryConfig with minimal required fields."""
        config = RepositoryConfig(
            owner="test-owner",
            repo="test-repo"
        )
        
        assert config.owner == "test-owner"
        assert config.repo == "test-repo"
        assert config.branch_filter == ["main"]  # Default value
        assert config.check_types == []  # Default empty list
        assert config.claude_context == {}  # Default empty dict
    
    def test_repository_config_full(self):
        """Test RepositoryConfig with all fields."""
        config = RepositoryConfig(
            owner="test-owner",
            repo="test-repo", 
            branch_filter=["main", "develop"],
            check_types=["ci", "tests"],
            claude_context={"language": "python"},
            fix_limits={"max_attempts": 5},
            priorities={"check_types": {"tests": 1}},
            notifications={"channel": "@alerts"}
        )
        
        assert config.owner == "test-owner"
        assert config.repo == "test-repo"
        assert config.branch_filter == ["main", "develop"]
        assert config.check_types == ["ci", "tests"]
        assert config.claude_context == {"language": "python"}
        assert config.fix_limits == {"max_attempts": 5}
        assert config.priorities == {"check_types": {"tests": 1}}
        assert config.notifications == {"channel": "@alerts"}


class TestGlobalLimits:
    """Test cases for GlobalLimits model."""
    
    def test_global_limits_defaults(self):
        """Test GlobalLimits with default values."""
        limits = GlobalLimits()
        
        assert limits.max_daily_fixes == 50
        assert limits.max_concurrent_fixes == 5
        assert limits.rate_limits == {}
        assert limits.resource_limits == {}
    
    def test_global_limits_validation(self):
        """Test GlobalLimits validation."""
        # Test valid limits
        limits = GlobalLimits(
            max_daily_fixes=100,
            max_concurrent_fixes=10
        )
        assert limits.max_daily_fixes == 100
        assert limits.max_concurrent_fixes == 10
        
        # Test invalid limits (should raise validation error)
        with pytest.raises(Exception):  # Pydantic ValidationError
            GlobalLimits(max_daily_fixes=0)  # Below minimum
        
        with pytest.raises(Exception):
            GlobalLimits(max_concurrent_fixes=0)  # Below minimum


class TestConfig:
    """Test cases for main Config class."""
    
    def test_config_empty(self):
        """Test Config with empty repositories."""
        config = Config()
        
        assert config.repositories == []
        assert isinstance(config.global_limits, GlobalLimits)
    
    def test_config_with_repositories(self):
        """Test Config with repositories."""
        repo_config = RepositoryConfig(owner="test", repo="repo")
        config = Config(repositories=[repo_config])
        
        assert len(config.repositories) == 1
        assert config.repositories[0].owner == "test"
    
    def test_config_load_valid_file(self, temp_config_file):
        """Test loading a valid configuration file."""
        config = Config.load(temp_config_file)
        
        assert isinstance(config, Config)
        assert len(config.repositories) > 0
        assert isinstance(config.global_limits, GlobalLimits)
    
    def test_config_load_nonexistent_file(self):
        """Test loading a non-existent configuration file."""
        with pytest.raises(FileNotFoundError):
            Config.load("nonexistent.json")
    
    def test_config_load_invalid_json(self):
        """Test loading invalid JSON file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{"invalid": json}')  # Invalid JSON
            f.flush()
            
            with pytest.raises(ValueError, match="Invalid JSON"):
                Config.load(f.name)
            
            os.unlink(f.name)
    
    def test_config_load_invalid_schema(self):
        """Test loading JSON that doesn't match schema."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"repositories": [{"invalid": "schema"}]}, f)
            f.flush()
            
            with pytest.raises(ValueError, match="Configuration validation error"):
                Config.load(f.name)
            
            os.unlink(f.name)
    
    def test_config_save(self):
        """Test saving configuration to file."""
        config = create_default_config()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config.save(f.name)
            
            # Verify file was created and can be loaded
            loaded_config = Config.load(f.name)
            assert len(loaded_config.repositories) == len(config.repositories)
            
            os.unlink(f.name)
    
    def test_config_validate_environment_valid(self, mock_env_vars):
        """Test environment validation with all required variables."""
        config = create_default_config()
        result = config.validate_environment()
        
        assert result["valid"] is True
        assert result["missing_vars"] == []
    
    def test_config_validate_environment_missing_vars(self):
        """Test environment validation with missing variables."""
        config = create_default_config()
        
        # Clear environment variables
        with patch.dict(os.environ, {}, clear=True):
            result = config.validate_environment()
        
        assert result["valid"] is False
        assert "GITHUB_TOKEN" in result["missing_vars"]
        assert "ANTHROPIC_API_KEY" in result["missing_vars"]
        assert "TELEGRAM_BOT_TOKEN" in result["missing_vars"]
    
    def test_config_get_repository_config(self):
        """Test getting configuration for specific repository."""
        config = create_default_config()
        repo_config = config.repositories[0]
        
        found_config = config.get_repository_config(repo_config.owner, repo_config.repo)
        
        assert found_config.owner == repo_config.owner
        assert found_config.repo == repo_config.repo
    
    def test_config_get_repository_config_not_found(self):
        """Test getting configuration for non-existent repository."""
        config = create_default_config()
        
        with pytest.raises(ValueError, match="No configuration found"):
            config.get_repository_config("nonexistent", "repo")
    
    def test_config_get_effective_limits(self):
        """Test getting effective limits for repository."""
        config = create_default_config()
        repo_config = config.repositories[0]
        
        limits = config.get_effective_limits(repo_config)
        
        # Should include global limits
        assert "max_daily_fixes" in limits
        assert "max_concurrent_fixes" in limits
        
        # Should include repo-specific limits
        if repo_config.fix_limits:
            for key in repo_config.fix_limits:
                assert key in limits


class TestEnvironmentConfig:
    """Test cases for environment configuration loading."""
    
    def test_load_environment_config_defaults(self):
        """Test loading environment config with defaults."""
        with patch.dict(os.environ, {}, clear=True):
            config = load_environment_config()
        
        # Should return defaults for optional variables
        assert config["redis_url"] == "redis://localhost:6379/0"
        assert config["log_level"] == "INFO"
        assert config["metrics_port"] == 8080
        assert config["polling_interval"] == 300
    
    def test_load_environment_config_custom(self, mock_env_vars):
        """Test loading environment config with custom values."""
        config = load_environment_config()
        
        assert config["github_token"] == "test_github_token_123"
        assert config["anthropic_api_key"] == "test_anthropic_key_456"
        assert config["telegram_bot_token"] == "test_telegram_bot_789"
        assert config["telegram_chat_id"] == "test_chat_id_101112"
        assert config["redis_url"] == "redis://localhost:6379/0"


class TestConfigValidation:
    """Test cases for configuration validation."""
    
    def test_validate_config_file_valid(self, temp_config_file):
        """Test validating a valid configuration file."""
        result = validate_config_file(temp_config_file)
        
        assert result["valid"] is True
        assert result["errors"] == []
        assert "repositories_count" in result["stats"]
    
    def test_validate_config_file_invalid(self):
        """Test validating an invalid configuration file."""
        result = validate_config_file("nonexistent.json")
        
        assert result["valid"] is False
        assert len(result["errors"]) > 0
    
    def test_validate_config_file_duplicate_repos(self):
        """Test validation catches duplicate repositories."""
        # Create config with duplicate repos
        duplicate_config = {
            "repositories": [
                {"owner": "test", "repo": "repo"},
                {"owner": "test", "repo": "repo"}  # Duplicate
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(duplicate_config, f)
            f.flush()
            
            result = validate_config_file(f.name)
            
            assert result["valid"] is False
            assert any("Duplicate repository" in error for error in result["errors"])
            
            os.unlink(f.name)
    
    def test_validate_config_file_warnings(self):
        """Test validation produces warnings for high limits."""
        high_limits_config = {
            "repositories": [
                {
                    "owner": "test",
                    "repo": "repo",
                    "fix_limits": {"max_attempts": 15}  # High limit
                }
            ],
            "global_limits": {
                "max_daily_fixes": 250  # High limit
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(high_limits_config, f)
            f.flush()
            
            result = validate_config_file(f.name)
            
            assert result["valid"] is True  # Still valid, just warnings
            assert len(result["warnings"]) > 0
            
            os.unlink(f.name)


class TestDefaultConfig:
    """Test cases for default configuration creation."""
    
    def test_create_default_config(self):
        """Test creating default configuration."""
        config = create_default_config()
        
        assert isinstance(config, Config)
        assert len(config.repositories) > 0
        assert isinstance(config.global_limits, GlobalLimits)
        
        # Check default repository has expected values
        repo = config.repositories[0]
        assert repo.owner == "example-org"
        assert repo.repo == "example-repo"
        assert "main" in repo.branch_filter
        assert "develop" in repo.branch_filter