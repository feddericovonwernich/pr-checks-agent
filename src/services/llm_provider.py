"""LLM Provider Service for decision-making in PR Check Agent

Supports multiple LLM providers:
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude)
- Ollama (local models)
- Azure OpenAI
"""

import json
import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import anthropic
    import httpx
    import openai

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

try:
    import openai
except ImportError:
    openai = None  # type: ignore[assignment]

from loguru import logger
from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    """Standard message format for LLM interactions."""

    role: str = Field(description="Message role: system, user, or assistant")
    content: str = Field(description="Message content")


class LLMResponse(BaseModel):
    """Standard response format from LLM providers."""

    content: str = Field(description="Response content")
    provider: str = Field(description="LLM provider used")
    model: str = Field(description="Model name used")
    usage: dict[str, Any] = Field(default_factory=dict, description="Usage statistics")
    success: bool = Field(default=True, description="Whether the request succeeded")
    error: str | None = Field(default=None, description="Error message if failed")


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, model: str, **kwargs):
        self.model = model
        self.provider_name = self.__class__.__name__.replace("Provider", "").lower()

    @abstractmethod
    async def generate(
        self, messages: list[LLMMessage], temperature: float = 0.1, max_tokens: int | None = None, **kwargs
    ) -> LLMResponse:
        """Generate response from the LLM."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is properly configured and available."""


class OpenAIProvider(BaseLLMProvider):
    """OpenAI provider for GPT models."""

    def __init__(self, model: str = "gpt-4", api_key: str | None = None, **kwargs):
        super().__init__(model, **kwargs)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = kwargs.get("base_url")
        self._client = None

    def _get_client(self) -> "openai.AsyncOpenAI":  # type: ignore[return]
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            if openai is None:
                raise ImportError("openai package required for OpenAI provider. Install with: pip install openai")
            self._client = openai.AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)  # type: ignore[assignment]
        return self._client  # type: ignore[return-value]

    def is_available(self) -> bool:
        """Check if OpenAI is properly configured."""
        return openai is not None and self.api_key is not None

    async def generate(
        self, messages: list[LLMMessage], temperature: float = 0.1, max_tokens: int | None = None, **kwargs
    ) -> LLMResponse:
        """Generate response using OpenAI API."""
        if not self.is_available():
            return LLMResponse(
                content="",
                provider=self.provider_name,
                model=self.model,
                success=False,
                error="OpenAI not properly configured",
            )

        try:
            client = self._get_client()

            # Convert messages to OpenAI format
            openai_messages = [{"role": msg.role, "content": msg.content} for msg in messages]  # type: ignore[misc]

            response = await client.chat.completions.create(
                model=self.model, messages=openai_messages, temperature=temperature, max_tokens=max_tokens, **kwargs  # type: ignore[arg-type]
            )

            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            return LLMResponse(
                content=response.choices[0].message.content or "", provider=self.provider_name, model=self.model, usage=usage
            )

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return LLMResponse(content="", provider=self.provider_name, model=self.model, success=False, error=str(e))


class AnthropicProvider(BaseLLMProvider):
    """Anthropic provider for Claude models."""

    def __init__(self, model: str = "claude-3-5-sonnet-20241022", api_key: str | None = None, **kwargs):
        super().__init__(model, **kwargs)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = None

    def _get_client(self) -> "anthropic.AsyncAnthropic":
        """Lazy initialization of Anthropic client."""
        if self._client is None:
            if anthropic is None:
                raise ImportError("anthropic package required for Anthropic provider. Install with: pip install anthropic")
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)  # type: ignore[assignment]
        return self._client  # type: ignore[return-value]

    def is_available(self) -> bool:
        """Check if Anthropic is properly configured."""
        return anthropic is not None and self.api_key is not None

    async def generate(
        self, messages: list[LLMMessage], temperature: float = 0.1, max_tokens: int | None = None, **kwargs
    ) -> LLMResponse:
        """Generate response using Anthropic API."""
        if not self.is_available():
            return LLMResponse(
                content="",
                provider=self.provider_name,
                model=self.model,
                success=False,
                error="Anthropic not properly configured",
            )

        try:
            client = self._get_client()

            # Separate system message from conversation
            system_message = None
            conversation_messages = []

            for msg in messages:
                if msg.role == "system":
                    system_message = msg.content
                else:
                    conversation_messages.append({"role": msg.role, "content": msg.content})

            response = await client.messages.create(
                model=self.model,
                max_tokens=max_tokens or 4096,
                temperature=temperature,
                system=system_message,
                messages=conversation_messages,
                **kwargs,
            )

            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.input_tokens,
                    "completion_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
                }

            return LLMResponse(content=response.content[0].text, provider=self.provider_name, model=self.model, usage=usage)

        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return LLMResponse(content="", provider=self.provider_name, model=self.model, success=False, error=str(e))


class OllamaProvider(BaseLLMProvider):
    """Ollama provider for local models."""

    def __init__(self, model: str = "llama3.2", base_url: str = "http://localhost:11434", **kwargs):
        super().__init__(model, **kwargs)
        self.base_url = base_url
        self._client = None

    def _get_client(self) -> "httpx.AsyncClient":
        """Lazy initialization of HTTP client for Ollama."""
        if self._client is None:
            if httpx is None:
                raise ImportError("httpx package required for Ollama provider. Install with: pip install httpx")
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=60.0)  # type: ignore[assignment]
        return self._client  # type: ignore[return-value]

    def is_available(self) -> bool:
        """Check if Ollama is available."""
        # Could add a ping to Ollama server here
        return httpx is not None

    async def generate(
        self, messages: list[LLMMessage], temperature: float = 0.1, max_tokens: int | None = None, **kwargs
    ) -> LLMResponse:
        """Generate response using Ollama API."""
        if not self.is_available():
            return LLMResponse(
                content="", provider=self.provider_name, model=self.model, success=False, error="Ollama not available"
            )

        try:
            client = self._get_client()

            # Convert messages to Ollama format
            ollama_messages = [{"role": msg.role, "content": msg.content} for msg in messages]

            payload = {
                "model": self.model,
                "messages": ollama_messages,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens or -1},
            }

            response = await client.post("/api/chat", json=payload)
            response.raise_for_status()

            result = response.json()

            usage = {}
            if "prompt_eval_count" in result:
                usage = {
                    "prompt_tokens": result.get("prompt_eval_count", 0),
                    "completion_tokens": result.get("eval_count", 0),
                    "total_tokens": result.get("prompt_eval_count", 0) + result.get("eval_count", 0),
                }

            return LLMResponse(
                content=result["message"]["content"], provider=self.provider_name, model=self.model, usage=usage
            )

        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            return LLMResponse(content="", provider=self.provider_name, model=self.model, success=False, error=str(e))


class LLMService:
    """Main LLM service that manages different providers."""

    def __init__(self, provider_config: dict[str, Any]):
        """Initialize LLM service with provider configuration.

        Args:
            provider_config: Configuration dict with provider, model, and other settings

        """
        self.config = provider_config
        self.provider = self._create_provider()

    def _create_provider(self) -> BaseLLMProvider:
        """Create the appropriate provider based on configuration."""
        provider_name = self.config.get("provider", "openai").lower()
        model = self.config.get("model")

        if provider_name == "openai":
            return OpenAIProvider(
                model=model or "gpt-4", api_key=self.config.get("api_key"), base_url=self.config.get("base_url")
            )
        if provider_name == "anthropic":
            return AnthropicProvider(model=model or "claude-3-5-sonnet-20241022", api_key=self.config.get("api_key"))
        if provider_name == "ollama":
            return OllamaProvider(model=model or "llama3.2", base_url=self.config.get("base_url", "http://localhost:11434"))
        raise ValueError(f"Unsupported LLM provider: {provider_name}")

    async def analyze_failure(
        self, failure_context: str, check_name: str, pr_info: dict[str, Any], project_context: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Analyze a CI/CD failure and determine next steps."""
        if project_context is None:
            project_context = {}

        system_prompt = """You are an expert software engineer analyzing CI/CD failures.
Your job is to understand what went wrong and determine if the issue is fixable automatically.

Respond with a JSON object containing:
- "fixable": boolean indicating if this can be fixed automatically
- "severity": "low", "medium", "high", or "critical"
- "category": type of failure (e.g., "test_failure", "build_error", "linting", "dependency")
- "analysis": detailed explanation of the issue
- "suggested_fix": brief description of what should be done
- "confidence": confidence level (0.0 to 1.0) in the analysis

Focus on common CI/CD issues that can be automatically resolved."""

        user_prompt = f"""
**Check Name:** {check_name}

**PR Information:**
- Title: {pr_info.get("title", "N/A")}
- Author: {pr_info.get("user", {}).get("login", "N/A")}
- Files Changed: {len(pr_info.get("changed_files", []))} files

**Project Context:**
{project_context}

**Failure Details:**
{failure_context}

Please analyze this failure and provide your assessment in JSON format.
"""

        messages = [LLMMessage(role="system", content=system_prompt), LLMMessage(role="user", content=user_prompt)]

        response = await self.provider.generate(messages, temperature=0.1, max_tokens=2048)

        if not response.success:
            return {
                "success": False,
                "error": response.error,
                "fixable": False,
                "analysis": "Failed to analyze due to LLM error",
            }

        try:
            analysis = json.loads(response.content)
            analysis["success"] = True
            analysis["llm_provider"] = response.provider
            analysis["llm_model"] = response.model
            return analysis
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": "Invalid JSON response from LLM",
                "fixable": False,
                "analysis": response.content,
            }

    async def should_escalate(
        self, failure_info: dict[str, Any], fix_attempts: int, max_attempts: int, project_context: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Determine if an issue should be escalated to humans."""
        if project_context is None:
            project_context = {}

        system_prompt = """You are an expert at triaging software issues and deciding when human intervention is needed.

Respond with a JSON object containing:
- "should_escalate": boolean indicating if this needs human attention
- "urgency": "low", "medium", "high", or "critical"
- "reason": explanation of why escalation is/isn't needed
- "suggested_actions": array of specific actions for humans to take
- "escalation_message": brief message to include in escalation notification

Consider factors like:
- Number of failed fix attempts
- Severity and type of issue
- Security implications
- Project criticality
"""

        user_prompt = f"""
**Fix Attempts:** {fix_attempts} out of {max_attempts} maximum

**Failure Information:**
- Category: {failure_info.get("category", "unknown")}
- Severity: {failure_info.get("severity", "unknown")}
- Fixable: {failure_info.get("fixable", False)}
- Analysis: {failure_info.get("analysis", "No analysis available")}

**Project Context:**
{project_context}

Should this issue be escalated to human developers? Provide your decision in JSON format.
"""

        messages = [LLMMessage(role="system", content=system_prompt), LLMMessage(role="user", content=user_prompt)]

        response = await self.provider.generate(messages, temperature=0.1, max_tokens=1024)

        if not response.success:
            # Default to escalation if LLM fails
            return {
                "should_escalate": True,
                "urgency": "medium",
                "reason": f"LLM analysis failed: {response.error}",
                "suggested_actions": ["Manual investigation required"],
                "escalation_message": "Automated analysis unavailable",
            }

        try:
            escalation = json.loads(response.content)
            escalation["llm_provider"] = response.provider
            escalation["llm_model"] = response.model
            return escalation
        except json.JSONDecodeError:
            return {
                "should_escalate": True,
                "urgency": "medium",
                "reason": "Invalid LLM response format",
                "suggested_actions": ["Manual investigation required"],
                "escalation_message": "Automated analysis failed",
            }

    def is_available(self) -> bool:
        """Check if the configured LLM provider is available."""
        return self.provider.is_available()
