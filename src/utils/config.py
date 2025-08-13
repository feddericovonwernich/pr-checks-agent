"""
Configuration management for PR Check Agent
Handles loading and validation of configuration files
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from state.schemas import RepositoryConfig


class GlobalLimits(BaseModel):
    """Global limits configuration."""
    max_daily_fixes: int = Field(default=50, ge=1, le=1000)
    max_concurrent_fixes: int = Field(default=5, ge=1, le=20)
    rate_limits: Dict[str, int] = Field(default_factory=dict)
    resource_limits: Dict[str, int] = Field(default_factory=dict)


class Config(BaseModel):
    """Main configuration model."""
    repositories: List[RepositoryConfig] = Field(default_factory=list)
    global_limits: GlobalLimits = Field(default_factory=GlobalLimits)
    
    @classmethod
    def load(cls, config_path: str) -> "Config":
        """Load configuration from file."""
        config_file = Path(config_path)
        
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        logger.info(f"Loading configuration from: {config_path}")
        
        try:
            with open(config_file, 'r') as f:
                config_data = json.load(f)
            
            # Validate and create config object
            config = cls(**config_data)
            
            logger.info(f"Configuration loaded successfully: {len(config.repositories)} repositories")
            return config
            
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in configuration file: {e}")
        except ValidationError as e:
            raise ValueError(f"Configuration validation error: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to load configuration: {e}")
    
    def save(self, config_path: str) -> None:
        """Save configuration to file."""
        config_file = Path(config_path)
        
        # Ensure directory exists
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(config_file, 'w') as f:
                json.dump(self.dict(), f, indent=2, default=str)
            
            logger.info(f"Configuration saved to: {config_path}")
            
        except Exception as e:
            raise RuntimeError(f"Failed to save configuration: {e}")
    
    def validate_environment(self) -> Dict[str, Any]:
        """
        Validate that all required environment variables are set.
        Returns validation results.
        """
        
        validation_results = {
            "valid": True,
            "missing_vars": [],
            "warnings": []
        }
        
        # Required environment variables
        required_vars = [
            "GITHUB_TOKEN",
            "ANTHROPIC_API_KEY",
            "TELEGRAM_BOT_TOKEN", 
            "TELEGRAM_CHAT_ID"
        ]
        
        for var in required_vars:
            if not os.getenv(var):
                validation_results["missing_vars"].append(var)
                validation_results["valid"] = False
        
        # Optional but recommended variables
        optional_vars = [
            "REDIS_URL",
            "WEBHOOK_SECRET"
        ]
        
        for var in optional_vars:
            if not os.getenv(var):
                validation_results["warnings"].append(f"{var} not set, using defaults")
        
        # Validate configuration consistency
        for repo in self.repositories:
            if repo.fix_limits.get("escalation_enabled", True):
                if not os.getenv("TELEGRAM_BOT_TOKEN"):
                    validation_results["warnings"].append(
                        f"Repository {repo.owner}/{repo.repo} has escalation enabled "
                        "but TELEGRAM_BOT_TOKEN not set"
                    )
        
        return validation_results
    
    def get_repository_config(self, owner: str, repo: str) -> RepositoryConfig:
        """Get configuration for a specific repository."""
        for repo_config in self.repositories:
            if repo_config.owner == owner and repo_config.repo == repo:
                return repo_config
        
        raise ValueError(f"No configuration found for repository: {owner}/{repo}")
    
    def get_effective_limits(self, repo_config: RepositoryConfig) -> Dict[str, Any]:
        """Get effective limits for a repository (repo-specific + global)."""
        
        # Start with global limits
        effective = self.global_limits.dict()
        
        # Override with repository-specific limits
        if repo_config.fix_limits:
            effective.update(repo_config.fix_limits)
        
        return effective


def load_environment_config() -> Dict[str, Any]:
    """Load configuration from environment variables."""
    
    return {
        "github_token": os.getenv("GITHUB_TOKEN"),
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY"),
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN"),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID"),
        "redis_url": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "webhook_secret": os.getenv("WEBHOOK_SECRET"),
        "metrics_port": int(os.getenv("METRICS_PORT", "8080")),
        "polling_interval": int(os.getenv("POLLING_INTERVAL", "300")),
        "max_concurrent_workflows": int(os.getenv("MAX_CONCURRENT_WORKFLOWS", "10")),
        "max_fix_attempts": int(os.getenv("MAX_FIX_ATTEMPTS", "3")),
        "escalation_cooldown": int(os.getenv("ESCALATION_COOLDOWN", "24")),
        "workflow_timeout": int(os.getenv("WORKFLOW_TIMEOUT", "60"))
    }


def create_default_config() -> Config:
    """Create a default configuration for testing/development."""
    
    return Config(
        repositories=[
            RepositoryConfig(
                owner="example-org",
                repo="example-repo",
                branch_filter=["main", "develop"],
                check_types=["ci", "tests", "linting"],
                claude_context={
                    "project_type": "python",
                    "test_framework": "pytest",
                    "linting": "flake8"
                },
                fix_limits={
                    "max_attempts": 3,
                    "cooldown_hours": 6,
                    "escalation_enabled": True
                },
                priorities={
                    "check_types": {
                        "security": 1,
                        "tests": 2,
                        "linting": 3,
                        "ci": 4
                    },
                    "branch_priority": {
                        "main": 1,
                        "develop": 2,
                        "feature/*": 3
                    }
                },
                notifications={
                    "telegram_channel": "@dev-alerts",
                    "escalation_mentions": ["@dev-lead"]
                }
            )
        ],
        global_limits=GlobalLimits(
            max_daily_fixes=50,
            max_concurrent_fixes=5,
            rate_limits={
                "github_api_calls_per_hour": 4000,
                "claude_invocations_per_hour": 100
            },
            resource_limits={
                "max_workflow_memory_mb": 512,
                "max_log_retention_days": 30
            }
        )
    )


def validate_config_file(config_path: str) -> Dict[str, Any]:
    """
    Validate a configuration file without loading it into the application.
    Returns validation results.
    """
    
    validation_results = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "stats": {}
    }
    
    try:
        config = Config.load(config_path)
        
        # Basic validation stats
        validation_results["stats"] = {
            "repositories_count": len(config.repositories),
            "total_branches_monitored": sum(
                len(repo.branch_filter) for repo in config.repositories
            ),
            "escalation_enabled_repos": sum(
                1 for repo in config.repositories 
                if repo.fix_limits.get("escalation_enabled", True)
            )
        }
        
        # Validate repository configurations
        repo_keys = set()
        for repo in config.repositories:
            repo_key = f"{repo.owner}/{repo.repo}"
            if repo_key in repo_keys:
                validation_results["errors"].append(f"Duplicate repository: {repo_key}")
                validation_results["valid"] = False
            repo_keys.add(repo_key)
            
            # Check for reasonable limits
            max_attempts = repo.fix_limits.get("max_attempts", 3)
            if max_attempts > 10:
                validation_results["warnings"].append(
                    f"Repository {repo_key} has high max_attempts: {max_attempts}"
                )
        
        # Validate global limits
        if config.global_limits.max_daily_fixes > 200:
            validation_results["warnings"].append(
                f"High daily fix limit: {config.global_limits.max_daily_fixes}"
            )
        
    except Exception as e:
        validation_results["valid"] = False
        validation_results["errors"].append(str(e))
    
    return validation_results