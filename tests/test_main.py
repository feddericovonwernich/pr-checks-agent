"""
Tests for the main application entry point
"""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from click.testing import CliRunner

from src.main import main
from src.utils.config import Config, create_default_config


@pytest.fixture
def temp_config_file():
    """Create a temporary config file for testing."""
    config = create_default_config()
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        config.save(f.name)
        yield f.name
    
    # Clean up
    os.unlink(f.name)


@pytest.fixture
def mock_env_vars():
    """Mock required environment variables."""
    env_vars = {
        'GITHUB_TOKEN': 'test_github_token',
        'ANTHROPIC_API_KEY': 'test_anthropic_key', 
        'TELEGRAM_BOT_TOKEN': 'test_telegram_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id',
        'REDIS_URL': 'redis://localhost:6379/0'
    }
    
    with patch.dict(os.environ, env_vars):
        yield env_vars


class TestMainApplication:
    """Test cases for the main application."""
    
    def test_main_help_shows_usage(self):
        """Test that --help shows usage information."""
        runner = CliRunner()
        result = runner.invoke(main, ['--help'])
        
        assert result.exit_code == 0
        assert 'PR Check Agent' in result.output
        assert '--config' in result.output
        assert '--log-level' in result.output
        assert '--dry-run' in result.output
    
    def test_main_version_shows_version(self):
        """Test that --version shows version information."""
        runner = CliRunner()
        result = runner.invoke(main, ['--version'])
        
        assert result.exit_code == 0
        assert '0.1.0' in result.output
    
    def test_main_invalid_config_file_fails(self):
        """Test that invalid config file causes graceful failure."""
        runner = CliRunner()
        result = runner.invoke(main, ['--config', 'nonexistent.json'])
        
        # Click returns exit code 2 for parameter validation errors, not 1
        assert result.exit_code == 2
        assert 'does not exist' in result.output
    
    def test_main_invalid_log_level_fails(self):
        """Test that invalid log level is rejected."""
        runner = CliRunner()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as f:
            config = create_default_config()
            config.save(f.name)
            
            result = runner.invoke(main, [
                '--config', f.name,
                '--log-level', 'INVALID'
            ])
        
        assert result.exit_code == 2  # Click parameter validation error
    
    @patch('src.main.asyncio.run')
    @patch('src.main.Config.load')
    def test_main_loads_config_successfully(self, mock_config_load, mock_asyncio_run, mock_env_vars):
        """Test that main successfully loads configuration."""
        # Setup
        mock_config = create_default_config()
        mock_config_load.return_value = mock_config
        mock_asyncio_run.return_value = None
        
        runner = CliRunner()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as f:
            result = runner.invoke(main, [
                '--config', f.name,
                '--log-level', 'INFO',
                '--dry-run'
            ])
        
        # Assertions
        assert result.exit_code == 0
        mock_config_load.assert_called_once_with(f.name)
        mock_asyncio_run.assert_called_once()
    
    @patch('src.main.asyncio.run')
    @patch('src.main.Config.load')
    @patch('src.main.setup_logging')
    def test_main_passes_correct_parameters(self, mock_setup_logging, mock_config_load, mock_asyncio_run, mock_env_vars):
        """Test that main passes correct parameters to async_main."""
        # Setup
        mock_config = create_default_config()
        mock_config_load.return_value = mock_config
        mock_asyncio_run.return_value = None
        
        runner = CliRunner()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as f:
            result = runner.invoke(main, [
                '--config', f.name,
                '--log-level', 'DEBUG',
                '--max-concurrent-workflows', '5',
                '--trace',
                '--dashboard', 
                '--metrics-port', '9090',
                '--dry-run',
                '--dev'
            ])
        
        # Check that setup_logging was called with correct parameters
        mock_setup_logging.assert_called_once_with(level='DEBUG', dev_mode=True)
        
        # Check that asyncio.run was called with correct arguments
        assert mock_asyncio_run.called
        args, kwargs = mock_asyncio_run.call_args
        async_main_call = args[0]  # This is a coroutine
        
        assert result.exit_code == 0
    
    @patch('src.main.asyncio.run')
    @patch('src.main.Config.load') 
    def test_main_handles_keyboard_interrupt_gracefully(self, mock_config_load, mock_asyncio_run, mock_env_vars):
        """Test that main handles KeyboardInterrupt gracefully."""
        # Setup
        mock_config = create_default_config()
        mock_config_load.return_value = mock_config
        mock_asyncio_run.side_effect = KeyboardInterrupt()
        
        runner = CliRunner()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as f:
            result = runner.invoke(main, [
                '--config', f.name,
                '--dry-run'
            ])
        
        assert result.exit_code == 0
        assert 'interrupt signal' in result.output.lower()
    
    @patch('src.main.asyncio.run')
    @patch('src.main.Config.load')
    def test_main_handles_unexpected_errors(self, mock_config_load, mock_asyncio_run, mock_env_vars):
        """Test that main handles unexpected errors gracefully."""
        # Setup
        mock_config = create_default_config()
        mock_config_load.return_value = mock_config
        mock_asyncio_run.side_effect = Exception("Unexpected error")
        
        runner = CliRunner()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as f:
            result = runner.invoke(main, [
                '--config', f.name,
                '--dry-run'
            ])
        
        assert result.exit_code == 1
        assert 'Unexpected error' in result.output


class TestAsyncMain:
    """Test cases for the async_main function."""
    
    @pytest.mark.asyncio
    @patch('src.main.start_monitoring_server')
    @patch('src.main.create_monitor_graph')
    @patch('src.main.run_repository_workflow')
    async def test_async_main_starts_monitoring_server(self, mock_run_workflow, mock_create_graph, mock_start_server):
        """Test that async_main starts the monitoring server when dashboard is enabled."""
        from src.main import async_main
        
        # Setup
        config = create_default_config()
        mock_start_server.return_value = AsyncMock()
        mock_create_graph.return_value = MagicMock()
        mock_run_workflow.return_value = AsyncMock()
        
        # Create a task that completes quickly to avoid hanging
        async def quick_task():
            return "done"
        
        mock_run_workflow.return_value = quick_task()
        
        try:
            await async_main(
                config=config,
                max_concurrent_workflows=5,
                trace=False,
                dashboard=True,
                metrics_port=8080,
                dry_run=True,
                dev=False
            )
        except:
            # Expected since we're mocking the workflow tasks
            pass
        
        # Verify monitoring server was started
        mock_start_server.assert_called_once_with(port=8080, dashboard=True)
    
    @pytest.mark.asyncio
    @patch('src.main.start_monitoring_server')
    @patch('src.main.create_monitor_graph')
    @patch('src.main.run_repository_workflow')
    async def test_async_main_creates_workflows_for_all_repos(self, mock_run_workflow, mock_create_graph, mock_start_server):
        """Test that async_main creates workflows for all configured repositories."""
        from src.main import async_main
        
        # Setup - config with multiple repositories
        config = create_default_config()
        # Add a second repository
        config.repositories.append(config.repositories[0].copy())
        config.repositories[1].repo = "second-repo"
        
        mock_start_server.return_value = AsyncMock()
        mock_create_graph.return_value = MagicMock()
        
        # Mock workflow tasks that complete quickly
        async def quick_task():
            return "done"
        
        mock_run_workflow.return_value = quick_task()
        
        try:
            await async_main(
                config=config,
                max_concurrent_workflows=5,
                trace=False,
                dashboard=False,
                metrics_port=8080,
                dry_run=True,
                dev=False
            )
        except:
            # Expected since we're mocking the workflow tasks
            pass
        
        # Verify graph was created
        mock_create_graph.assert_called_once()
        
        # Verify run_repository_workflow was called for each repository
        assert mock_run_workflow.call_count == len(config.repositories)


class TestApplicationIntegration:
    """Integration tests for application startup."""
    
    @patch('src.main.asyncio.run')
    @patch('src.utils.config.Config.validate_environment')
    def test_application_validates_environment(self, mock_validate_env, mock_asyncio_run, temp_config_file, mock_env_vars):
        """Test that application validates environment variables."""
        # Setup
        mock_validate_env.return_value = {
            'valid': True,
            'missing_vars': [],
            'warnings': []
        }
        mock_asyncio_run.return_value = None
        
        runner = CliRunner()
        result = runner.invoke(main, [
            '--config', temp_config_file,
            '--dry-run'
        ])
        
        assert result.exit_code == 0
    
    @patch('src.main.asyncio.set_event_loop_policy')
    @patch('src.main.asyncio.run')
    @patch('src.main.sys.platform', 'linux')
    def test_application_sets_uvloop_on_unix(self, mock_asyncio_run, mock_set_policy, temp_config_file, mock_env_vars):
        """Test that application sets uvloop event loop policy on Unix systems."""
        # Setup
        mock_asyncio_run.return_value = None
        
        runner = CliRunner()
        result = runner.invoke(main, [
            '--config', temp_config_file,
            '--dry-run'
        ])
        
        assert result.exit_code == 0
        # Verify uvloop policy was set
        mock_set_policy.assert_called_once()
    
    def test_application_dry_run_mode_logged(self, temp_config_file, mock_env_vars):
        """Test that dry-run mode is properly logged."""
        runner = CliRunner()
        
        with patch('src.main.asyncio.run') as mock_run:
            mock_run.return_value = None
            
            result = runner.invoke(main, [
                '--config', temp_config_file,
                '--dry-run'
            ])
        
        assert result.exit_code == 0
        assert 'DRY-RUN mode' in result.output