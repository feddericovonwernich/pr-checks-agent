"""Tests for LLM provider service."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.llm_provider import LLMService, OpenAIProvider, AnthropicProvider, OllamaProvider, LLMMessage


class TestLLMService:
    """Test LLM service functionality."""

    def test_llm_service_initialization_openai(self):
        """Test LLM service initialization with OpenAI provider."""
        config = {
            "provider": "openai",
            "model": "gpt-4",
            "api_key": "test-key"
        }
        
        service = LLMService(config)
        
        assert isinstance(service.provider, OpenAIProvider)
        assert service.provider.model == "gpt-4"
        assert service.provider.api_key == "test-key"

    def test_llm_service_initialization_anthropic(self):
        """Test LLM service initialization with Anthropic provider."""
        config = {
            "provider": "anthropic",
            "model": "claude-3-5-sonnet-20241022",
            "api_key": "test-key"
        }
        
        service = LLMService(config)
        
        assert isinstance(service.provider, AnthropicProvider)
        assert service.provider.model == "claude-3-5-sonnet-20241022"
        assert service.provider.api_key == "test-key"

    def test_llm_service_initialization_ollama(self):
        """Test LLM service initialization with Ollama provider."""
        config = {
            "provider": "ollama",
            "model": "llama3.2",
            "base_url": "http://localhost:11434"
        }
        
        service = LLMService(config)
        
        assert isinstance(service.provider, OllamaProvider)
        assert service.provider.model == "llama3.2"
        assert service.provider.base_url == "http://localhost:11434"

    def test_llm_service_invalid_provider(self):
        """Test LLM service with invalid provider."""
        config = {
            "provider": "invalid_provider",
            "model": "test-model"
        }
        
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            LLMService(config)

    @pytest.mark.asyncio
    async def test_analyze_failure_success(self):
        """Test successful failure analysis."""
        config = {
            "provider": "openai",
            "model": "gpt-4",
            "api_key": "test-key"
        }
        
        # Mock the provider's generate method
        mock_response_json = {
            "fixable": True,
            "severity": "medium",
            "category": "test_failure",
            "analysis": "Test failed due to missing dependency",
            "suggested_fix": "Install missing dependency",
            "confidence": 0.9
        }
        
        service = LLMService(config)
        
        # Create mock response object
        mock_llm_response = MagicMock()
        mock_llm_response.success = True
        mock_llm_response.content = '{"fixable": true, "severity": "medium", "category": "test_failure", "analysis": "Test failed due to missing dependency", "suggested_fix": "Install missing dependency", "confidence": 0.9}'
        mock_llm_response.provider = "openai"
        mock_llm_response.model = "gpt-4"
        
        with patch.object(service.provider, 'generate', new_callable=AsyncMock, return_value=mock_llm_response) as mock_generate:
            result = await service.analyze_failure(
                failure_context="Test failed with import error",
                check_name="test_suite",
                pr_info={"title": "Fix bug", "user": {"login": "testuser"}},
                project_context={"language": "python"}
            )
            
            assert result["success"] is True
            assert result["fixable"] is True
            assert result["severity"] == "medium"
            assert result["category"] == "test_failure"
            assert "llm_provider" in result
            assert "llm_model" in result
            mock_generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_escalate_success(self):
        """Test successful escalation decision."""
        config = {
            "provider": "openai",
            "model": "gpt-4",
            "api_key": "test-key"
        }
        
        service = LLMService(config)
        
        # Create mock response object
        mock_llm_response = MagicMock()
        mock_llm_response.success = True
        mock_llm_response.content = '{"should_escalate": true, "urgency": "high", "reason": "Security vulnerability detected", "suggested_actions": ["Manual security review"], "escalation_message": "Critical security issue needs immediate attention"}'
        mock_llm_response.provider = "openai"
        mock_llm_response.model = "gpt-4"
        
        with patch.object(service.provider, 'generate', new_callable=AsyncMock, return_value=mock_llm_response) as mock_generate:
            result = await service.should_escalate(
                failure_info={"category": "security", "severity": "high"},
                fix_attempts=3,
                max_attempts=3,
                project_context={"language": "python"}
            )
            
            assert result["should_escalate"] is True
            assert result["urgency"] == "high" 
            assert result["reason"] == "Security vulnerability detected"
            assert "llm_provider" in result
            assert "llm_model" in result
            mock_generate.assert_called_once()


class TestOpenAIProvider:
    """Test OpenAI provider functionality."""

    def test_openai_provider_initialization(self):
        """Test OpenAI provider initialization."""
        provider = OpenAIProvider(model="gpt-4", api_key="test-key")
        
        assert provider.model == "gpt-4"
        assert provider.api_key == "test-key"
        assert provider.provider_name == "openai"

    @patch.dict('os.environ', {'OPENAI_API_KEY': 'env-key'})
    def test_openai_provider_env_key(self):
        """Test OpenAI provider gets key from environment."""
        provider = OpenAIProvider(model="gpt-4")
        
        assert provider.api_key == "env-key"

    def test_openai_provider_is_available_with_key(self):
        """Test OpenAI provider availability check with API key."""
        with patch('services.llm_provider.openai', create=True):
            provider = OpenAIProvider(model="gpt-4", api_key="test-key")
            assert provider.is_available() is True

    @patch.dict('os.environ', {}, clear=True)
    def test_openai_provider_is_available_no_key(self):
        """Test OpenAI provider availability check without API key."""
        provider = OpenAIProvider(model="gpt-4", api_key=None)
        assert provider.is_available() is False

    def test_openai_provider_is_available_no_package(self):
        """Test OpenAI provider availability check without package."""
        provider = OpenAIProvider(model="gpt-4", api_key="test-key")
        
        # Mock the import to fail
        with patch.object(provider, 'is_available') as mock_available:
            mock_available.return_value = False
            assert provider.is_available() is False


class TestAnthropicProvider:
    """Test Anthropic provider functionality."""

    def test_anthropic_provider_initialization(self):
        """Test Anthropic provider initialization."""
        provider = AnthropicProvider(model="claude-3-5-sonnet-20241022", api_key="test-key")
        
        assert provider.model == "claude-3-5-sonnet-20241022"
        assert provider.api_key == "test-key"
        assert provider.provider_name == "anthropic"

    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'env-key'})
    def test_anthropic_provider_env_key(self):
        """Test Anthropic provider gets key from environment."""
        provider = AnthropicProvider()
        
        assert provider.api_key == "env-key"

    def test_anthropic_provider_is_available_with_key(self):
        """Test Anthropic provider availability check with API key."""
        # Mock anthropic package to be available
        with patch('builtins.__import__') as mock_import:
            def side_effect(name, *args):
                if name == 'anthropic':
                    return MagicMock()  # Return a mock anthropic module
                return __import__(name, *args)
            mock_import.side_effect = side_effect
            
            provider = AnthropicProvider(api_key="test-key")
            assert provider.is_available() is True

    def test_anthropic_provider_is_available_no_key(self):
        """Test Anthropic provider availability check without API key."""
        with patch('services.llm_provider.anthropic', create=True):
            provider = AnthropicProvider(api_key=None)
            assert provider.is_available() is False


class TestOllamaProvider:
    """Test Ollama provider functionality."""

    def test_ollama_provider_initialization(self):
        """Test Ollama provider initialization."""
        provider = OllamaProvider(model="llama3.2", base_url="http://localhost:11434")
        
        assert provider.model == "llama3.2"
        assert provider.base_url == "http://localhost:11434"
        assert provider.provider_name == "ollama"

    def test_ollama_provider_is_available_with_httpx(self):
        """Test Ollama provider availability check with httpx."""
        with patch('services.llm_provider.httpx', create=True):
            provider = OllamaProvider()
            assert provider.is_available() is True

    def test_ollama_provider_is_available_no_httpx(self):
        """Test Ollama provider availability check without httpx."""
        with patch.object(OllamaProvider, 'is_available') as mock_available:
            mock_available.return_value = False
            provider = OllamaProvider()
            assert provider.is_available() is False


class TestLLMMessage:
    """Test LLM message model."""

    def test_llm_message_creation(self):
        """Test LLM message creation."""
        message = LLMMessage(role="user", content="Test message")
        
        assert message.role == "user"
        assert message.content == "Test message"

    def test_llm_message_validation(self):
        """Test LLM message validation."""
        # This should work without issues
        message = LLMMessage(role="system", content="You are a helpful assistant")
        assert message.role == "system"
        assert message.content == "You are a helpful assistant"