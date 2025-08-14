"""Tests for LangChain LLM Service"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.langchain_llm_service import LangChainLLMService


class TestLangChainLLMService:
    """Test LangChain LLM Service functionality."""

    def test_service_initialization_openai(self):
        """Test service initialization with OpenAI provider."""
        config = {"provider": "openai", "model": "gpt-4", "temperature": 0.2, "api_key": "test-key"}

        with patch("services.langchain_llm_service.ChatOpenAI") as mock_chat_openai:
            mock_chat_openai.return_value = MagicMock()

            service = LangChainLLMService(config)

            assert service.provider_name == "openai"
            assert service.model_name == "gpt-4"
            mock_chat_openai.assert_called_once()
            call_kwargs = mock_chat_openai.call_args[1]
            assert call_kwargs["model"] == "gpt-4"
            assert call_kwargs["temperature"] == 0.2
            assert call_kwargs["api_key"] == "test-key"

    def test_service_initialization_anthropic(self):
        """Test service initialization with Anthropic provider."""
        config = {"provider": "anthropic", "model": "claude-3-5-sonnet-20241022", "api_key": "test-anthropic-key"}

        with patch("services.langchain_llm_service.ChatAnthropic") as mock_chat_anthropic:
            mock_chat_anthropic.return_value = MagicMock()

            service = LangChainLLMService(config)

            assert service.provider_name == "anthropic"
            assert service.model_name == "claude-3-5-sonnet-20241022"
            mock_chat_anthropic.assert_called_once()

    def test_service_initialization_ollama(self):
        """Test service initialization with Ollama provider."""
        config = {"provider": "ollama", "model": "llama3.2", "base_url": "http://localhost:11434"}

        with patch("services.langchain_llm_service.ChatOllama") as mock_chat_ollama:
            mock_chat_ollama.return_value = MagicMock()

            service = LangChainLLMService(config)

            assert service.provider_name == "ollama"
            assert service.model_name == "llama3.2"
            mock_chat_ollama.assert_called_once()

    def test_unsupported_provider_raises_error(self):
        """Test that unsupported provider raises ValueError."""
        config = {"provider": "unsupported_provider"}

        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            LangChainLLMService(config)

    def test_model_name_defaults(self):
        """Test model name defaults for each provider."""
        # OpenAI default
        with patch("services.langchain_llm_service.ChatOpenAI"):
            service = LangChainLLMService({"provider": "openai", "api_key": "test"})
            assert service.model_name == "gpt-4"

        # Anthropic default
        with patch("services.langchain_llm_service.ChatAnthropic"):
            service = LangChainLLMService({"provider": "anthropic", "api_key": "test"})
            assert service.model_name == "claude-3-5-sonnet-20241022"

        # Ollama default
        with patch("services.langchain_llm_service.ChatOllama"):
            service = LangChainLLMService({"provider": "ollama"})
            assert service.model_name == "llama3.2"

    @pytest.mark.asyncio
    async def test_analyze_failure_structured_success(self):
        """Test successful failure analysis with structured output."""
        config = {"provider": "openai", "api_key": "test"}

        # Mock the ChatOpenAI and response
        mock_response = MagicMock()
        mock_response.content = """{
            "fixable": true,
            "severity": "medium",
            "category": "test_failure",
            "analysis": "Test is failing due to assertion error",
            "suggested_fix": "Update test expectations",
            "confidence": 0.85
        }"""

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response

        with patch("services.langchain_llm_service.ChatOpenAI", return_value=mock_llm):
            service = LangChainLLMService(config)

            result = await service.analyze_failure(
                failure_context="Test assertion failed",
                check_name="Unit Tests",
                pr_info={"title": "Test PR", "user": {"login": "testuser"}},
                project_context={"framework": "pytest"},
            )

            assert result["success"] is True
            assert result["fixable"] is True
            assert result["severity"] == "medium"
            assert result["category"] == "test_failure"
            assert result["llm_provider"] == "openai"

    @pytest.mark.asyncio
    async def test_analyze_failure_structured_parse_error_fallback(self):
        """Test failure analysis fallback when structured parsing fails."""
        config = {"provider": "openai", "api_key": "test"}

        # Mock response with invalid JSON
        mock_response = MagicMock()
        mock_response.content = "This is a regular text response about the failure being fixable"

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response

        with patch("services.langchain_llm_service.ChatOpenAI", return_value=mock_llm):
            service = LangChainLLMService(config)

            result = await service.analyze_failure(
                failure_context="Test failure", check_name="CI", pr_info={}, project_context={}
            )

            # Should fall back to unstructured parsing
            assert result["success"] is True
            assert result["fixable"] is True  # "fixable" is in the response
            assert result["analysis"] == mock_response.content

    @pytest.mark.asyncio
    async def test_analyze_failure_llm_error(self):
        """Test failure analysis error handling."""
        config = {"provider": "openai", "api_key": "test"}

        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = Exception("API Error")

        with patch("services.langchain_llm_service.ChatOpenAI", return_value=mock_llm):
            service = LangChainLLMService(config)

            result = await service.analyze_failure(
                failure_context="Test failure", check_name="CI", pr_info={}, project_context={}
            )

            assert result["success"] is False
            assert "API Error" in result["error"]
            assert result["fixable"] is False

    @pytest.mark.asyncio
    async def test_should_escalate_structured_success(self):
        """Test successful escalation decision with structured output."""
        config = {"provider": "anthropic", "api_key": "test"}

        mock_response = MagicMock()
        mock_response.content = """{
            "should_escalate": true,
            "urgency": "high",
            "reason": "Max attempts reached with security implications",
            "suggested_actions": ["Review security policies", "Manual code review"],
            "escalation_message": "Security-related failure needs immediate attention"
        }"""

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response

        with patch("services.langchain_llm_service.ChatAnthropic", return_value=mock_llm):
            service = LangChainLLMService(config)

            result = await service.should_escalate(
                failure_info={"category": "security", "severity": "high"},
                fix_attempts=3,
                max_attempts=3,
                project_context={"criticality": "high"},
            )

            assert result["should_escalate"] is True
            assert result["urgency"] == "high"
            assert result["llm_provider"] == "anthropic"
            assert len(result["suggested_actions"]) == 2

    @pytest.mark.asyncio
    async def test_should_escalate_llm_error_defaults_to_escalate(self):
        """Test escalation decision defaults to escalate on LLM error."""
        config = {"provider": "openai", "api_key": "test"}

        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = Exception("API Error")

        with patch("services.langchain_llm_service.ChatOpenAI", return_value=mock_llm):
            service = LangChainLLMService(config)

            result = await service.should_escalate(failure_info={}, fix_attempts=2, max_attempts=3, project_context={})

            # Should default to escalation on error
            assert result["should_escalate"] is True
            assert result["urgency"] == "medium"
            assert "API Error" in result["reason"]

    @pytest.mark.asyncio
    async def test_generate_response_success(self):
        """Test generic response generation."""
        config = {"provider": "openai", "api_key": "test"}

        mock_response = MagicMock()
        mock_response.content = "This is a test response"
        mock_response.response_metadata = {"token_usage": {"prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75}}

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response

        with patch("services.langchain_llm_service.ChatOpenAI", return_value=mock_llm):
            service = LangChainLLMService(config)

            from langchain_core.messages import HumanMessage

            messages = [HumanMessage(content="Test message")]

            result = await service.generate_response(messages)

            assert result.success is True
            assert result.content == "This is a test response"
            assert result.provider == "openai"
            assert result.usage["total_tokens"] == 75

    def test_is_available_openai_with_api_key(self):
        """Test availability check for OpenAI with API key."""
        config = {"provider": "openai", "api_key": "test-key"}

        with patch("services.langchain_llm_service.ChatOpenAI"):
            service = LangChainLLMService(config)
            assert service.is_available() is True

    def test_is_available_openai_without_api_key(self):
        """Test availability check for OpenAI without API key."""
        config = {"provider": "openai"}

        with patch("services.langchain_llm_service.ChatOpenAI"), patch("os.getenv", return_value=None):
            service = LangChainLLMService(config, strict_validation=False)
            assert service.is_available() is False

    def test_is_available_anthropic_with_env_key(self):
        """Test availability check for Anthropic with environment key."""
        config = {"provider": "anthropic"}

        with patch("services.langchain_llm_service.ChatAnthropic"), patch("os.getenv", return_value="env-key"):
            service = LangChainLLMService(config)
            assert service.is_available() is True

    def test_is_available_ollama(self):
        """Test availability check for Ollama."""
        config = {"provider": "ollama"}

        with patch("services.langchain_llm_service.ChatOllama"):
            service = LangChainLLMService(config)
            assert service.is_available() is True

    def test_get_provider_info(self):
        """Test provider info extraction."""
        config = {"provider": "openai", "model": "gpt-4", "api_key": "secret-key", "temperature": 0.2}

        with patch("services.langchain_llm_service.ChatOpenAI"):
            service = LangChainLLMService(config)
            info = service.get_provider_info()

            assert info["provider"] == "openai"
            assert info["model"] == "gpt-4"
            assert info["available"] is True
            # API key should be excluded for security
            assert "api_key" not in info["config"]
            assert info["config"]["temperature"] == 0.2

    def test_format_project_context_empty(self):
        """Test project context formatting with empty context."""
        with patch("services.langchain_llm_service.ChatOpenAI"):
            service = LangChainLLMService({"provider": "openai", "api_key": "test"})
            result = service._format_project_context({})
            assert result == "No additional context provided."

    def test_format_project_context_with_data(self):
        """Test project context formatting with data."""
        with patch("services.langchain_llm_service.ChatOpenAI"):
            service = LangChainLLMService({"provider": "openai", "api_key": "test"})
            context = {"language": "Python", "framework": "FastAPI", "testing": "pytest"}
            result = service._format_project_context(context)

            assert "- language: Python" in result
            assert "- framework: FastAPI" in result
            assert "- testing: pytest" in result

    def test_parse_analysis_fallback(self):
        """Test fallback analysis parsing."""
        with patch("services.langchain_llm_service.ChatOpenAI"):
            service = LangChainLLMService({"provider": "openai", "api_key": "test"})

            # Test fixable content
            result = service._parse_analysis_fallback("This issue can be fixed automatically")
            assert result["fixable"] is True
            assert result["confidence"] == 0.5

            # Test non-fixable content
            result = service._parse_analysis_fallback("This requires manual intervention")
            assert result["fixable"] is False

    def test_parse_escalation_fallback(self):
        """Test fallback escalation parsing."""
        with patch("services.langchain_llm_service.ChatOpenAI"):
            service = LangChainLLMService({"provider": "openai", "api_key": "test"})

            # Test escalation needed
            result = service._parse_escalation_fallback("This needs human intervention")
            assert result["should_escalate"] is True

            # Test no escalation needed
            result = service._parse_escalation_fallback("This can be handled automatically")
            assert result["should_escalate"] is False


class TestProviderErrors:
    """Test error handling for missing provider packages."""

    def test_openai_not_installed_error(self):
        """Test error when OpenAI package is not installed."""
        config = {"provider": "openai", "api_key": "test"}

        with patch("services.langchain_llm_service.ChatOpenAI", None):
            with pytest.raises(ImportError, match="langchain-openai package required"):
                LangChainLLMService(config)

    def test_anthropic_not_installed_error(self):
        """Test error when Anthropic package is not installed."""
        config = {"provider": "anthropic", "api_key": "test"}

        with patch("services.langchain_llm_service.ChatAnthropic", None):
            with pytest.raises(ImportError, match="langchain-anthropic package required"):
                LangChainLLMService(config)

    def test_ollama_not_installed_error(self):
        """Test error when Ollama package is not installed."""
        config = {"provider": "ollama"}

        with patch("services.langchain_llm_service.ChatOllama", None):
            with pytest.raises(ImportError, match="langchain-community package required"):
                LangChainLLMService(config)

    def test_openai_missing_api_key_error(self):
        """Test error when OpenAI API key is missing."""
        config = {"provider": "openai"}

        with patch("services.langchain_llm_service.ChatOpenAI"), patch("os.getenv", return_value=None):
            with pytest.raises(ValueError, match="OPENAI_API_KEY environment variable"):
                LangChainLLMService(config)

    def test_anthropic_missing_api_key_error(self):
        """Test error when Anthropic API key is missing."""
        config = {"provider": "anthropic"}

        with patch("services.langchain_llm_service.ChatAnthropic"), patch("os.getenv", return_value=None):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY environment variable"):
                LangChainLLMService(config)
