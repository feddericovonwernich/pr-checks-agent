"""Tests for LangChain Claude Tool"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tools.langchain_claude_tool import LangChainClaudeTool, LangChainClaudeInput


class TestLangChainClaudeTool:
    """Test LangChain Claude Tool functionality."""

    def test_tool_initialization_production(self):
        """Test tool initialization in production mode."""
        with patch("tools.langchain_claude_tool.ChatAnthropic") as mock_anthropic:
            mock_anthropic.return_value = MagicMock()
            
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                tool = LangChainClaudeTool(dry_run=False)
                
                assert tool.dry_run is False
                assert tool.claude_llm is not None
                mock_anthropic.assert_called_once()

    def test_tool_initialization_dry_run(self):
        """Test tool initialization in dry run mode."""
        tool = LangChainClaudeTool(dry_run=True)
        
        assert tool.dry_run is True
        assert tool.claude_llm is None

    def test_tool_initialization_missing_api_key(self):
        """Test tool initialization fails without API key."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY environment variable"):
                LangChainClaudeTool(dry_run=False)

    def test_tool_initialization_missing_anthropic_package(self):
        """Test tool initialization fails without langchain-anthropic package."""
        with patch("tools.langchain_claude_tool.ChatAnthropic", None):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                with pytest.raises(ImportError, match="langchain-anthropic package required"):
                    LangChainClaudeTool(dry_run=False)

    def test_custom_model_initialization(self):
        """Test tool initialization with custom model."""
        with patch("tools.langchain_claude_tool.ChatAnthropic") as mock_anthropic:
            mock_anthropic.return_value = MagicMock()
            
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                tool = LangChainClaudeTool(dry_run=False, model="claude-3-haiku-20240307")
                
                assert tool.model == "claude-3-haiku-20240307"
                # Verify ChatAnthropic was called with correct model
                call_kwargs = mock_anthropic.call_args[1]
                assert call_kwargs["model"] == "claude-3-haiku-20240307"

    @pytest.mark.asyncio
    async def test_analyze_failure_dry_run(self):
        """Test failure analysis in dry run mode."""
        tool = LangChainClaudeTool(dry_run=True)
        
        result = await tool._arun(
            operation="analyze_failure",
            failure_context="Test failure",
            check_name="Unit Tests",
            pr_info={"title": "Test PR"},
            project_context={}
        )
        
        assert result["success"] is True
        assert "Mock analysis" in result["analysis"]
        assert result["fixable"] is True
        assert len(result["suggested_actions"]) > 0

    @pytest.mark.asyncio
    async def test_fix_issue_dry_run(self):
        """Test fix issue in dry run mode."""
        tool = LangChainClaudeTool(dry_run=True)
        
        result = await tool._arun(
            operation="fix_issue",
            failure_context="Test failure",
            check_name="Linting",
            pr_info={"title": "Test PR"},
            project_context={},
            repository_path="/tmp/test"
        )
        
        assert result["success"] is True
        assert "Mock fix" in result["fix_description"]
        assert len(result["files_modified"]) > 0
        assert len(result["verification_commands"]) > 0

    @pytest.mark.asyncio
    async def test_analyze_failure_structured_success(self):
        """Test successful structured failure analysis."""
        mock_response = MagicMock()
        mock_response.content = """{
            "root_cause": "Test assertion failed due to incorrect expectation",
            "is_fixable": true,
            "fix_steps": ["Update test assertion", "Verify test data"],
            "side_effects": ["May affect related tests"],
            "confidence": 0.9
        }"""
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response
        
        with patch("tools.langchain_claude_tool.ChatAnthropic", return_value=mock_llm):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                tool = LangChainClaudeTool(dry_run=False)
                
                result = await tool._arun(
                    operation="analyze_failure",
                    failure_context="AssertionError: expected 5 but got 3",
                    check_name="Unit Tests",
                    pr_info={
                        "number": 123,
                        "title": "Fix calculation bug",
                        "user": {"login": "developer"},
                        "branch": "fix-bug",
                        "base_branch": "main"
                    },
                    project_context={"framework": "pytest", "language": "Python"}
                )
                
                assert result["success"] is True
                assert result["fixable"] is True
                assert result["confidence"] == 0.9
                assert len(result["suggested_actions"]) == 2
                assert len(result["side_effects"]) == 1

    @pytest.mark.asyncio
    async def test_analyze_failure_parse_error_fallback(self):
        """Test analysis fallback when structured parsing fails."""
        mock_response = MagicMock()
        mock_response.content = "The issue can be fixed automatically by updating the test assertion"
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response
        
        with patch("tools.langchain_claude_tool.ChatAnthropic", return_value=mock_llm):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                tool = LangChainClaudeTool(dry_run=False)
                
                result = await tool._arun(
                    operation="analyze_failure",
                    failure_context="Test failure",
                    check_name="CI",
                    pr_info={},
                    project_context={}
                )
                
                # Should fallback to heuristic parsing
                assert result["success"] is True
                assert result["fixable"] is True  # "can be fixed" is in the response
                assert result["confidence"] == 0.7
                assert result["analysis"] == mock_response.content

    @pytest.mark.asyncio
    async def test_fix_issue_structured_success(self):
        """Test successful structured fix generation."""
        mock_response = MagicMock()
        mock_response.content = """{
            "success": true,
            "description": "Updated test assertion to match expected behavior",
            "files_affected": ["tests/test_calculation.py", "src/calculator.py"],
            "additional_steps": ["Run full test suite"],
            "verification_commands": ["python -m pytest tests/", "ruff check ."]
        }"""
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response
        
        with patch("tools.langchain_claude_tool.ChatAnthropic", return_value=mock_llm):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                tool = LangChainClaudeTool(dry_run=False)
                
                result = await tool._arun(
                    operation="fix_issue",
                    failure_context="AssertionError in test_add",
                    check_name="Unit Tests",
                    pr_info={"number": 123, "title": "Fix calculator"},
                    project_context={"language": "Python"},
                    repository_path="/tmp/repo"
                )
                
                assert result["success"] is True
                assert "Updated test assertion" in result["fix_description"]
                assert len(result["files_modified"]) == 2
                assert len(result["verification_commands"]) == 2

    @pytest.mark.asyncio
    async def test_fix_issue_parse_error_fallback(self):
        """Test fix generation fallback when structured parsing fails."""
        mock_response = MagicMock()
        mock_response.content = "Fix the test by updating the assertion to expect the correct value"
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response
        
        with patch("tools.langchain_claude_tool.ChatAnthropic", return_value=mock_llm):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                tool = LangChainClaudeTool(dry_run=False)
                
                result = await tool._arun(
                    operation="fix_issue",
                    failure_context="Test failure",
                    check_name="CI",
                    pr_info={},
                    project_context={},
                    repository_path="/tmp"
                )
                
                # Should fallback to unstructured
                assert result["success"] is True  # Assumes success for fallback
                assert result["fix_description"] == mock_response.content
                assert len(result["files_modified"]) == 0  # Cannot extract reliably

    @pytest.mark.asyncio
    async def test_unknown_operation_error(self):
        """Test error handling for unknown operation."""
        tool = LangChainClaudeTool(dry_run=True)
        
        result = await tool._arun(
            operation="unknown_operation",
            failure_context="Test",
            check_name="Test",
            pr_info={},
            project_context={}
        )
        
        assert result["success"] is False
        assert "Unknown operation" in result["error"]

    @pytest.mark.asyncio
    async def test_llm_error_handling(self):
        """Test error handling when LLM call fails."""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = Exception("API Error")
        
        with patch("tools.langchain_claude_tool.ChatAnthropic", return_value=mock_llm):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                tool = LangChainClaudeTool(dry_run=False)
                
                result = await tool._arun(
                    operation="analyze_failure",
                    failure_context="Test failure",
                    check_name="CI",
                    pr_info={},
                    project_context={}
                )
                
                assert result["success"] is False
                assert "API Error" in result["error"]

    def test_heuristic_is_fixable_positive(self):
        """Test heuristic fixability detection - positive cases."""
        tool = LangChainClaudeTool(dry_run=True)
        
        # Test positive indicators
        positive_cases = [
            "This can be fixed automatically",
            "Simple syntax error that is fixable",
            "Missing import can be resolved",
            "Formatting issue that needs correction"
        ]
        
        for content in positive_cases:
            assert tool._heuristic_is_fixable(content) is True

    def test_heuristic_is_fixable_negative(self):
        """Test heuristic fixability detection - negative cases."""
        tool = LangChainClaudeTool(dry_run=True)
        
        # Test negative indicators
        negative_cases = [
            "This cannot be fixed automatically",
            "Not fixable due to architectural issues",
            "Requires manual intervention and design changes",
            "Complex logic problems need human review"
        ]
        
        for content in negative_cases:
            assert tool._heuristic_is_fixable(content) is False

    def test_extract_actions_heuristic(self):
        """Test heuristic action extraction."""
        tool = LangChainClaudeTool(dry_run=True)
        
        content = """
        To fix this issue:
        - Update the test assertion
        - Check the input data
        * Verify the calculation logic
        1. Run the test suite
        2. Review the implementation
        
        Some other text that should be ignored.
        """
        
        actions = tool._extract_actions_heuristic(content)
        
        assert len(actions) == 5
        assert "Update the test assertion" in actions
        assert "Check the input data" in actions
        assert "Verify the calculation logic" in actions
        assert "Run the test suite" in actions
        assert "Review the implementation" in actions

    def test_format_project_context_empty(self):
        """Test project context formatting with empty context."""
        tool = LangChainClaudeTool(dry_run=True)
        result = tool._format_project_context({})
        assert result == "No additional project context provided."

    def test_format_project_context_with_data(self):
        """Test project context formatting with data."""
        tool = LangChainClaudeTool(dry_run=True)
        context = {"language": "Python", "framework": "Django", "testing": "pytest"}
        result = tool._format_project_context(context)
        
        assert "- language: Python" in result
        assert "- framework: Django" in result
        assert "- testing: pytest" in result

    @pytest.mark.asyncio
    async def test_health_check_dry_run(self):
        """Test health check in dry run mode."""
        tool = LangChainClaudeTool(dry_run=True)
        
        result = await tool.health_check()
        
        assert result["status"] == "healthy"
        assert result["mode"] == "dry_run"
        assert result["provider"] == "langchain_anthropic"

    @pytest.mark.asyncio
    async def test_health_check_production_success(self):
        """Test successful health check in production mode."""
        mock_response = MagicMock()
        mock_response.content = "OK - Claude is working"
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response
        
        with patch("tools.langchain_claude_tool.ChatAnthropic", return_value=mock_llm):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                tool = LangChainClaudeTool(dry_run=False)
                
                result = await tool.health_check()
                
                assert result["status"] == "healthy"
                assert result["mode"] == "production"
                assert result["provider"] == "langchain_anthropic"
                assert "OK - Claude" in result["test_response"]

    @pytest.mark.asyncio
    async def test_health_check_production_error(self):
        """Test health check error in production mode."""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = Exception("Connection failed")
        
        with patch("tools.langchain_claude_tool.ChatAnthropic", return_value=mock_llm):
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                tool = LangChainClaudeTool(dry_run=False)
                
                result = await tool.health_check()
                
                assert result["status"] == "unhealthy"
                assert "Connection failed" in result["error"]

    @pytest.mark.asyncio
    async def test_health_check_no_llm_initialized(self):
        """Test health check when LLM is not initialized."""
        # Create tool in dry run mode, then manually set dry_run to False
        tool = LangChainClaudeTool(dry_run=True)
        tool.dry_run = False  # Simulate state where LLM wasn't initialized
        
        result = await tool.health_check()
        
        assert result["status"] == "unhealthy"
        assert "Claude LLM not initialized" in result["error"]


class TestLangChainClaudeInput:
    """Test input schema validation."""

    def test_valid_input_analyze_failure(self):
        """Test valid input for analyze failure operation."""
        input_data = LangChainClaudeInput(
            operation="analyze_failure",
            failure_context="Test failed with assertion error",
            check_name="Unit Tests",
            pr_info={"number": 123, "title": "Fix bug"},
            project_context={"language": "Python"}
        )
        
        assert input_data.operation == "analyze_failure"
        assert input_data.check_name == "Unit Tests"
        assert input_data.project_context["language"] == "Python"

    def test_valid_input_fix_issue(self):
        """Test valid input for fix issue operation."""
        input_data = LangChainClaudeInput(
            operation="fix_issue",
            failure_context="Linting error in code",
            check_name="Linting",
            pr_info={"number": 456},
            repository_path="/path/to/repo"
        )
        
        assert input_data.operation == "fix_issue"
        assert input_data.repository_path == "/path/to/repo"

    def test_default_values(self):
        """Test input schema default values."""
        input_data = LangChainClaudeInput(
            operation="analyze_failure",
            failure_context="Test",
            check_name="Test",
            pr_info={}
        )
        
        assert input_data.project_context == {}
        assert input_data.repository_path is None