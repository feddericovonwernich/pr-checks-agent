"""
Tests for Claude Code CLI tool
"""

import asyncio
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from src.tools.claude_tool import ClaudeCodeTool, ClaudeCodeInput


class TestClaudeCodeInput:
    """Test cases for Claude Code input validation."""
    
    def test_claude_code_input_minimal(self):
        """Test minimal valid input."""
        input_data = ClaudeCodeInput(
            operation="analyze_failure",
            failure_context="Test failure context",
            check_name="CI",
            pr_info={"number": 123, "title": "Test PR"}
        )
        
        assert input_data.operation == "analyze_failure"
        assert input_data.failure_context == "Test failure context"
        assert input_data.check_name == "CI"
        assert input_data.pr_info == {"number": 123, "title": "Test PR"}
        assert input_data.repository_path is None
        assert input_data.project_context == {}
    
    def test_claude_code_input_full(self):
        """Test input with all fields."""
        input_data = ClaudeCodeInput(
            operation="fix_issue",
            repository_path="/path/to/repo",
            failure_context="Detailed failure context",
            check_name="Tests",
            pr_info={"number": 456, "title": "Fix PR"},
            project_context={"language": "python", "framework": "pytest"}
        )
        
        assert input_data.operation == "fix_issue"
        assert input_data.repository_path == "/path/to/repo"
        assert input_data.failure_context == "Detailed failure context"
        assert input_data.check_name == "Tests"
        assert input_data.pr_info == {"number": 456, "title": "Fix PR"}
        assert input_data.project_context == {"language": "python", "framework": "pytest"}


class TestClaudeCodeTool:
    """Test cases for Claude Code CLI tool."""
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    def test_claude_tool_initialization_success(self, mock_subprocess):
        """Test successful tool initialization."""
        # Mock successful version check
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "claude 1.0.0"
        mock_subprocess.return_value = mock_result
        
        tool = ClaudeCodeTool()
        
        assert tool.name == "claude_code"
        assert tool.description == "Invoke Claude Code CLI to analyze and fix code issues"
        assert tool.args_schema == ClaudeCodeInput
        assert tool.anthropic_api_key == 'test_api_key'
        assert tool.dry_run is False
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    def test_claude_tool_initialization_dry_run(self):
        """Test initialization in dry run mode."""
        tool = ClaudeCodeTool(dry_run=True)
        
        assert tool.dry_run is True
    
    def test_claude_tool_initialization_no_api_key(self):
        """Test initialization fails without API key."""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY environment variable is required"):
                ClaudeCodeTool()
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    def test_claude_tool_unknown_operation(self, mock_subprocess):
        """Test handling of unknown operation."""
        tool = ClaudeCodeTool()
        
        result = tool._run(
            operation="unknown_operation",
            failure_context="test context",
            check_name="CI",
            pr_info={"number": 123}
        )
        
        assert result["success"] is False
        assert "Unknown operation" in result["error"]
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    def test_analyze_failure_dry_run(self, mock_subprocess):
        """Test analyze failure in dry run mode."""
        # Mock the version check subprocess call during initialization
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "claude 1.0.0"
        mock_subprocess.return_value = mock_result
        
        tool = ClaudeCodeTool(dry_run=True)
        
        result = tool._run(
            operation="analyze_failure",
            failure_context="Test failure logs",
            check_name="CI", 
            pr_info={"number": 123, "title": "Test PR"}
        )
        
        assert result["success"] is True
        assert "Mock analysis" in result["analysis"]
        assert result["fixable"] is True
        assert len(result["suggested_actions"]) > 0
        assert "attempt_id" in result
        assert "duration_seconds" in result
        
        # Should only call subprocess once during initialization for version check
        assert mock_subprocess.call_count == 1
        mock_subprocess.assert_called_with(['claude', '--version'], capture_output=True, text=True, timeout=10)
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    def test_fix_issue_dry_run(self, mock_subprocess):
        """Test fix issue in dry run mode."""
        # Mock the version check subprocess call during initialization
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "claude 1.0.0"
        mock_subprocess.return_value = mock_result
        
        tool = ClaudeCodeTool(dry_run=True)
        
        result = tool._run(
            operation="fix_issue",
            failure_context="Test failure context",
            check_name="Tests",
            pr_info={"number": 456, "title": "Fix PR"},
            repository_path="/path/to/repo"
        )
        
        assert result["success"] is True
        assert "Mock fix applied" in result["fix_description"]
        assert len(result["files_modified"]) > 0
        assert "git diff" in result["git_diff"]
        assert "attempt_id" in result
        
        # Should only call subprocess once during initialization for version check
        assert mock_subprocess.call_count == 1
        mock_subprocess.assert_called_with(['claude', '--version'], capture_output=True, text=True, timeout=10)
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    def test_fix_issue_no_repository_path(self, mock_subprocess):
        """Test fix issue without repository path."""
        tool = ClaudeCodeTool()
        
        result = tool._run(
            operation="fix_issue",
            failure_context="Test failure context",
            check_name="Tests",
            pr_info={"number": 456}
            # Missing repository_path
        )
        
        assert result["success"] is False
        assert "Repository path required" in result["error"]
        mock_subprocess.assert_not_called()
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    @patch('tempfile.NamedTemporaryFile')
    @patch('os.unlink')
    @pytest.mark.asyncio
    async def test_execute_claude_cli_success(self, mock_unlink, mock_temp_file, mock_subprocess):
        """Test successful Claude CLI execution."""
        # Setup temp file mock
        mock_file = MagicMock()
        mock_file.name = "/tmp/test_prompt.txt"
        mock_temp_file.return_value.__enter__.return_value = mock_file
        
        # Setup subprocess mock for successful execution
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b'{"analysis": "Test analysis"}', b'')
        
        with patch('asyncio.create_subprocess_exec', return_value=mock_process) as mock_create_subprocess:
            with patch('asyncio.wait_for', return_value=(b'{"analysis": "Test analysis"}', b'')):
                tool = ClaudeCodeTool()
                result = await tool._execute_claude_cli("Test prompt", "analyze")
        
        assert result["success"] is True
        assert result["output"] == '{"analysis": "Test analysis"}'
        assert "duration_seconds" in result
        
        # Verify subprocess was called correctly
        mock_create_subprocess.assert_called_once()
        args = mock_create_subprocess.call_args[0]
        assert "claude" in args
        assert "--prompt-file" in args
        assert "/tmp/test_prompt.txt" in args
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    @patch('tempfile.NamedTemporaryFile')
    @patch('os.unlink')
    @pytest.mark.asyncio
    async def test_execute_claude_cli_failure(self, mock_unlink, mock_temp_file, mock_subprocess):
        """Test Claude CLI execution failure."""
        # Setup temp file mock
        mock_file = MagicMock()
        mock_file.name = "/tmp/test_prompt.txt"
        mock_temp_file.return_value.__enter__.return_value = mock_file
        
        # Setup subprocess mock for failed execution
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate.return_value = (b'', b'Claude CLI error')
        
        with patch('asyncio.create_subprocess_exec', return_value=mock_process):
            with patch('asyncio.wait_for', return_value=(b'', b'Claude CLI error')):
                tool = ClaudeCodeTool()
                result = await tool._execute_claude_cli("Test prompt", "fix")
        
        assert result["success"] is False
        assert "Claude CLI error" in result["error"]
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    @patch('tempfile.NamedTemporaryFile')
    @patch('os.unlink')
    @pytest.mark.asyncio
    async def test_execute_claude_cli_timeout(self, mock_unlink, mock_temp_file, mock_subprocess):
        """Test Claude CLI execution timeout."""
        # Setup temp file mock
        mock_file = MagicMock()
        mock_file.name = "/tmp/test_prompt.txt"
        mock_temp_file.return_value.__enter__.return_value = mock_file
        
        with patch('asyncio.create_subprocess_exec') as mock_create_subprocess:
            with patch('asyncio.wait_for', side_effect=asyncio.TimeoutError()):
                tool = ClaudeCodeTool()
                result = await tool._execute_claude_cli("Test prompt", "analyze")
        
        assert result["success"] is False
        assert "timed out" in result["error"]
        assert result["duration_seconds"] == 300  # 5 minutes timeout
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    def test_create_analysis_prompt(self, mock_subprocess):
        """Test analysis prompt creation."""
        tool = ClaudeCodeTool()
        
        prompt = tool._create_analysis_prompt(
            failure_context="Test failed with assertion error",
            check_name="CI",
            pr_info={"number": 123, "title": "Fix tests", "branch": "feature-branch"},
            project_context={"project_type": "python", "test_framework": "pytest"}
        )
        
        assert "Analyze this CI/CD check failure" in prompt
        assert "CI" in prompt
        assert "PR: #123" in prompt
        assert "Fix tests" in prompt
        assert "feature-branch" in prompt
        assert "project_type: python" in prompt
        assert "test_framework: pytest" in prompt
        assert "Test failed with assertion error" in prompt
        assert "Root cause analysis" in prompt
        assert "automatically fixable" in prompt
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    def test_create_fix_prompt(self, mock_subprocess):
        """Test fix prompt creation."""
        tool = ClaudeCodeTool()
        
        prompt = tool._create_fix_prompt(
            failure_context="Syntax error on line 42",
            check_name="Linting",
            pr_info={"number": 456, "title": "Code cleanup", "branch": "cleanup"},
            project_context={"project_type": "javascript", "linting": "eslint"}
        )
        
        assert "Fix this CI/CD check failure" in prompt
        assert "Linting" in prompt
        assert "PR: #456" in prompt
        assert "Code cleanup" in prompt
        assert "project_type: javascript" in prompt
        assert "linting: eslint" in prompt
        assert "Syntax error on line 42" in prompt
        assert "Making the necessary code changes" in prompt
        assert "minimal and targeted" in prompt
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    def test_is_fixable_positive_indicators(self, mock_subprocess):
        """Test fixable detection with positive indicators."""
        tool = ClaudeCodeTool()
        
        analysis = "This is automatically fixable with a simple fix for the syntax error"
        assert tool._is_fixable(analysis) is True
        
        analysis = "Missing import can be resolved automatically"
        assert tool._is_fixable(analysis) is True
        
        analysis = "Linting issue that needs formatting"
        assert tool._is_fixable(analysis) is True
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    def test_is_fixable_negative_indicators(self, mock_subprocess):
        """Test fixable detection without positive indicators."""
        tool = ClaudeCodeTool()
        
        analysis = "This requires manual intervention and complex logic changes"
        assert tool._is_fixable(analysis) is False
        
        analysis = "The issue is very complex and cannot be resolved automatically"
        assert tool._is_fixable(analysis) is False
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    def test_extract_actions(self, mock_subprocess):
        """Test action extraction from analysis."""
        tool = ClaudeCodeTool()
        
        analysis = """
        Here are the suggested steps:
        - Fix the import statement
        - Update the test assertion
        - Run the tests again
        1. Check the configuration
        2. Restart the service
        * Add missing dependency
        """
        
        actions = tool._extract_actions(analysis)
        
        assert len(actions) == 5  # Limited to 5
        assert "Fix the import statement" in actions
        assert "Update the test assertion" in actions
        assert "Run the tests again" in actions
        assert "Check the configuration" in actions
        assert "Restart the service" in actions
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    @pytest.mark.asyncio
    async def test_health_check_dry_run(self, mock_subprocess):
        """Test health check in dry run mode."""
        tool = ClaudeCodeTool(dry_run=True)
        result = await tool.health_check()
        
        assert result["status"] == "healthy"
        assert result["mode"] == "dry_run"
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_subprocess):
        """Test successful health check."""
        # Setup subprocess mock for successful version check
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b'claude 1.0.0', b'')
        
        with patch('asyncio.create_subprocess_exec', return_value=mock_process):
            with patch('asyncio.wait_for', return_value=(b'claude 1.0.0', b'')):
                tool = ClaudeCodeTool()
                result = await tool.health_check()
        
        assert result["status"] == "healthy"
        assert result["version"] == "claude 1.0.0"
        assert result["mode"] == "production"
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_subprocess):
        """Test health check failure."""
        # Setup subprocess mock for failed version check
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate.return_value = (b'', b'Command not found')
        
        with patch('asyncio.create_subprocess_exec', return_value=mock_process):
            with patch('asyncio.wait_for', return_value=(b'', b'Command not found')):
                tool = ClaudeCodeTool()
                result = await tool.health_check()
        
        assert result["status"] == "unhealthy"
        assert "Command not found" in result["error"]
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    @pytest.mark.asyncio
    async def test_analyze_failure_with_context(self, mock_subprocess):
        """Test analyze failure with full context."""
        tool = ClaudeCodeTool(dry_run=True)  # Use dry run to avoid subprocess
        
        result = await tool._arun(
            operation="analyze_failure",
            failure_context="ImportError: No module named 'requests'",
            check_name="Dependencies",
            pr_info={
                "number": 789,
                "title": "Add new feature",
                "branch": "feature/new-functionality",
                "author": "developer"
            },
            project_context={
                "project_type": "python",
                "package_manager": "pip",
                "requirements_file": "requirements.txt"
            }
        )
        
        assert result["success"] is True
        assert "Dependencies" in result["analysis"]
        assert result["fixable"] is True
        assert len(result["suggested_actions"]) >= 1
        assert "attempt_id" in result
        assert result["duration_seconds"] > 0
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test_api_key'})
    @patch('subprocess.run')
    @pytest.mark.asyncio
    async def test_fix_issue_with_repository_path(self, mock_subprocess):
        """Test fix issue with repository path."""
        tool = ClaudeCodeTool(dry_run=True)  # Use dry run to avoid subprocess
        
        result = await tool._arun(
            operation="fix_issue",
            failure_context="Missing semicolon on line 25",
            check_name="ESLint",
            pr_info={
                "number": 101,
                "title": "JavaScript improvements",
                "branch": "feature/js-fixes"
            },
            repository_path="/tmp/test-repo",
            project_context={
                "project_type": "javascript",
                "linting": "eslint"
            }
        )
        
        assert result["success"] is True
        assert "ESLint" in result["fix_description"]
        assert len(result["files_modified"]) > 0
        assert "attempt_id" in result
        assert result["duration_seconds"] > 0