"""Shared fixtures for end-to-end integration tests."""

import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from testcontainers.core.container import DockerContainer
from testcontainers.redis import RedisContainer

from src.state.persistence import StatePersistence

from src.utils.config import Config, create_default_config


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop]:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def redis_container() -> AsyncGenerator[RedisContainer]:
    """Start a Redis container for state persistence testing."""
    with RedisContainer("redis:7-alpine") as redis:
        redis.start()
        yield redis


@pytest_asyncio.fixture(scope="session")
async def wiremock_container() -> AsyncGenerator[DockerContainer]:
    """Start a WireMock container for GitHub API mocking."""
    with DockerContainer("wiremock/wiremock:latest") as wiremock:
        wiremock.with_exposed_ports(8080)
        wiremock.start()
        yield wiremock


@pytest_asyncio.fixture(scope="session")
async def claude_mock_server() -> AsyncGenerator[DockerContainer]:
    """Start a simple HTTP server for Claude API mocking."""
    # Use httpbin for simple HTTP mocking
    with DockerContainer("kennethreitz/httpbin") as httpbin:
        httpbin.with_exposed_ports(80)
        httpbin.start()
        yield httpbin


@pytest_asyncio.fixture(scope="session")
async def telegram_mock_server() -> AsyncGenerator[DockerContainer]:
    """Start a simple HTTP server for Telegram Bot API mocking."""
    # Use httpbin for simple HTTP mocking
    with DockerContainer("kennethreitz/httpbin") as httpbin:
        httpbin.with_exposed_ports(80)
        httpbin.start()
        yield httpbin


@pytest_asyncio.fixture
async def redis_client(redis_container: RedisContainer) -> AsyncGenerator[StatePersistence]:
    """Create a Redis client connected to the test container."""
    # Construct Redis URL from container details
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    redis_url = f"redis://{host}:{port}/0"
    
    persistence = StatePersistence(redis_url=redis_url)
    yield persistence
    # Cleanup: flush the database
    persistence.redis_client.flushdb()
    persistence.redis_client.close()


@pytest_asyncio.fixture
async def github_api_mock(wiremock_container: DockerContainer) -> AsyncGenerator[str]:
    """Setup GitHub API mocking with WireMock."""
    base_url = f"http://{wiremock_container.get_container_host_ip()}:{wiremock_container.get_exposed_port(8080)}"

    # Setup common GitHub API responses
    async with httpx.AsyncClient() as client:
        # Mock the API root endpoint
        await client.post(f"{base_url}/__admin/mappings", json={
            "request": {"method": "GET", "url": "/"},
            "response": {"status": 200, "body": "GitHub API Mock"}
        })

        # Mock repository API
        await client.post(f"{base_url}/__admin/mappings", json={
            "request": {
                "method": "GET",
                "urlPattern": "/repos/([^/]+)/([^/]+)"
            },
            "response": {
                "status": 200,
                "headers": {"Content-Type": "application/json"},
                "jsonBody": {
                    "id": 12345,
                    "name": "test-repo",
                    "full_name": "test-org/test-repo",
                    "owner": {"login": "test-org"},
                    "default_branch": "main"
                }
            }
        })

        # Mock pulls API
        await client.post(f"{base_url}/__admin/mappings", json={
            "request": {
                "method": "GET",
                "urlPattern": "/repos/([^/]+)/([^/]+)/pulls.*"
            },
            "response": {
                "status": 200,
                "headers": {"Content-Type": "application/json"},
                "jsonBody": []
            }
        })

    yield base_url


@pytest_asyncio.fixture
async def claude_api_mock(claude_mock_server: DockerContainer) -> AsyncGenerator[str]:
    """Setup Claude API mocking."""
    base_url = f"http://{claude_mock_server.get_container_host_ip()}:{claude_mock_server.get_exposed_port(80)}"

    # Mock successful Claude response
    async with httpx.AsyncClient() as client:
        # Test that the mock server is working
        response = await client.get(f"{base_url}/status/200")
        assert response.status_code == 200

    yield base_url


@pytest_asyncio.fixture
async def telegram_api_mock(telegram_mock_server: DockerContainer) -> AsyncGenerator[str]:
    """Setup Telegram Bot API mocking."""
    base_url = f"http://{telegram_mock_server.get_container_host_ip()}:{telegram_mock_server.get_exposed_port(80)}"

    # Mock successful Telegram response
    async with httpx.AsyncClient() as client:
        # Test that the mock server is working
        response = await client.get(f"{base_url}/status/200")
        assert response.status_code == 200

    yield base_url


@pytest.fixture
def test_config() -> Config:
    """Create a test configuration for integration tests."""
    config = create_default_config()

    # Update with test-specific values
    config.repositories[0].owner = "test-org"
    config.repositories[0].repo = "test-repo"
    config.repositories[0].branch_filter = ["main", "develop"]
    config.repositories[0].check_types = ["ci", "tests", "linting"]

    return config


@pytest.fixture
def mock_environment_vars():
    """Mock environment variables for testing."""
    env_vars = {
        "GITHUB_TOKEN": "test-github-token",
        "ANTHROPIC_API_KEY": "test-anthropic-key",
        "TELEGRAM_BOT_TOKEN": "test-telegram-token",
        "TELEGRAM_CHAT_ID": "test-chat-id",
        "REDIS_URL": "redis://localhost:6379/0",  # Will be overridden by test
        "WEBHOOK_SECRET": "test-webhook-secret"
    }

    with patch.dict(os.environ, env_vars, clear=True):
        yield env_vars


@pytest_asyncio.fixture
async def integration_test_setup(
    redis_client: StatePersistence,
    github_api_mock: str,
    claude_api_mock: str,
    telegram_api_mock: str,
    test_config: Config,
    mock_environment_vars: dict[str, str]
) -> dict[str, any]:
    """Complete integration test setup with all mocked services."""
    return {
        "redis_client": redis_client,
        "github_api_base_url": github_api_mock,
        "claude_api_base_url": claude_api_mock,
        "telegram_api_base_url": telegram_api_mock,
        "config": test_config,
        "env_vars": mock_environment_vars
    }


# Helper functions for creating test data

def create_test_pr_data(pr_number: int = 123, status: str = "open") -> dict[str, any]:
    """Create test PR data structure."""
    return {
        "id": 12345,
        "number": pr_number,
        "state": status,
        "title": f"Test PR #{pr_number}",
        "body": "Test PR description",
        "head": {
            "ref": "feature-branch",
            "sha": "abc123def456"
        },
        "base": {
            "ref": "main",
            "sha": "def456abc123"
        },
        "user": {
            "login": "test-user"
        },
        "created_at": "2024-01-01T10:00:00Z",
        "updated_at": "2024-01-01T11:00:00Z"
    }


def create_test_check_data(name: str = "ci/test", status: str = "failure") -> dict[str, any]:
    """Create test check run data structure."""
    return {
        "id": 54321,
        "name": name,
        "status": "completed",
        "conclusion": status,
        "started_at": "2024-01-01T10:05:00Z",
        "completed_at": "2024-01-01T10:10:00Z",
        "details_url": "https://github.com/test-org/test-repo/runs/54321",
        "output": {
            "title": f"{name} failed",
            "summary": "Test failure summary",
            "text": "Detailed test failure output..."
        }
    }


def create_claude_fix_response(*, success: bool = True) -> dict[str, any]:
    """Create test Claude API response for fix attempts."""
    if success:
        return {
            "type": "message",
            "content": [
                {
                    "type": "text",
                    "text": "I've successfully fixed the failing tests by updating the test assertions."
                }
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50
            }
        }
    return {
        "type": "error",
        "error": {
            "type": "api_error",
            "message": "Unable to process the fix request"
        }
    }

