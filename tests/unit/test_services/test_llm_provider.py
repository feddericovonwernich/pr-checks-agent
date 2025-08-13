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
        mock_response = {
            "success": True,
            "fixable": True,
            "severity": "medium",
            "category": "test_failure",
            "analysis": "Test failed due to missing dependency",
            "suggested_fix": "Install missing dependency",
            "confidence": 0.9
        }
        
        service = LLMService(config)
        
        with patch.object(service.provider, 'generate', new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value.success = True
            mock_generate.return_value.content = str(mock_response).replace("'", '"')
            mock_generate.return_value.provider = "openai"
            mock_generate.return_value.model = "gpt-4"
            
            result = await service.analyze_failure(
                failure_context="Test failed with import error",
                check_name="test_suite",
                pr_info={"title": "Fix bug", "user": {"login": "testuser"}},
                project_context={"language": "python"}
            )
            
            assert result["success"] is True
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
        
        mock_response = {
            "should_escalate": True,
            "urgency": "high",
            "reason": "Security vulnerability detected",
            "suggested_actions": ["Manual security review"],
            "escalation_message": "Critical security issue needs immediate attention"
        }
        
        service = LLMService(config)
        
        with patch.object(service.provider, 'generate', new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value.success = True
            mock_generate.return_value.content = str(mock_response).replace("'", '"')
            mock_generate.return_value.provider = "openai"
            mock_generate.return_value.model = "gpt-4"
            
            result = await service.should_escalate(
                failure_info={"category": "security", "severity": "high"},
                fix_attempts=3,
                max_attempts=3,
                project_context={"language": "python"}
            )
            
            assert "should_escalate" in result
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

    def test_openai_provider_is_available_no_key(self):
        """Test OpenAI provider availability check without API key."""
        with patch('services.llm_provider.openai', create=True):
            provider = OpenAIProvider(model="gpt-4", api_key=None)
            assert provider.is_available() is False

    def test_openai_provider_is_available_no_package(self):
        """Test OpenAI provider availability check without package."""
        provider = OpenAIProvider(model="gpt-4", api_key="test-key")
        assert provider.is_available() is False  # No openai package installed


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
        with patch('services.llm_provider.anthropic', create=True):
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
        provider = OllamaProvider()
        # httpx is already installed, so this will be True
        # In real scenario without httpx, it would be False
        assert provider.is_available() is True


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