"""LangChain-based LLM Provider Service for PR Check Agent

Unified LLM service using LangChain for multiple providers:
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude)
- Ollama (local models)
- Azure OpenAI

Benefits over direct API integration:
- Standardized interfaces and message formats
- Better error handling and retries
- Access to LangChain ecosystem (prompt templates, output parsers, etc.)
- Built-in streaming and callbacks support
"""

import os
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from loguru import logger
from pydantic import BaseModel, Field

# Import LangChain providers with optional handling
try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None  # type: ignore[assignment,misc]

try:
    from langchain_anthropic import ChatAnthropic
except ImportError:
    ChatAnthropic = None  # type: ignore[assignment,misc]

try:
    from langchain_community.chat_models import ChatOllama
    from langchain_community.llms import Ollama
except ImportError:
    Ollama = None  # type: ignore[assignment,misc]
    ChatOllama = None  # type: ignore[assignment,misc]


class LLMResponse(BaseModel):
    """Standard response format from LangChain LLM providers."""

    content: str = Field(description="Response content")
    provider: str = Field(description="LLM provider used")
    model: str = Field(description="Model name used")
    usage: dict[str, Any] = Field(default_factory=dict, description="Usage statistics")
    success: bool = Field(default=True, description="Whether the request succeeded")
    error: str | None = Field(default=None, description="Error message if failed")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class FailureAnalysis(BaseModel):
    """Structured output for failure analysis."""

    fixable: bool = Field(description="Whether this failure can be fixed automatically")
    severity: str = Field(description="Severity level: low, medium, high, critical")
    category: str = Field(description="Type of failure (test_failure, build_error, linting, etc.)")
    analysis: str = Field(description="Detailed explanation of the issue")
    suggested_fix: str = Field(description="Brief description of what should be done")
    confidence: float = Field(description="Confidence level (0.0 to 1.0) in the analysis", ge=0.0, le=1.0)


class EscalationDecision(BaseModel):
    """Structured output for escalation decisions."""

    should_escalate: bool = Field(description="Whether this needs human attention")
    urgency: str = Field(description="Urgency level: low, medium, high, critical")
    reason: str = Field(description="Explanation of why escalation is/isn't needed")
    suggested_actions: list[str] = Field(description="Specific actions for humans to take")
    escalation_message: str = Field(description="Brief message to include in escalation notification")


class LangChainLLMService:
    """Main LLM service using LangChain for provider abstraction."""

    def __init__(self, provider_config: dict[str, Any], strict_validation: bool = True):
        """Initialize LangChain LLM service with provider configuration.

        Args:
            provider_config: Configuration dict with provider, model, and other settings
            strict_validation: If True, require valid API keys during initialization

        """
        self.config = provider_config
        self.provider_name = self.config.get("provider", "openai").lower()
        self.model_name = self._get_model_name()
        self.strict_validation = strict_validation
        self.llm = self._create_llm()

        # Initialize output parsers
        self.failure_analysis_parser = PydanticOutputParser(pydantic_object=FailureAnalysis)
        self.escalation_parser = PydanticOutputParser(pydantic_object=EscalationDecision)

        logger.info(f"LangChain LLM service initialized with {self.provider_name}:{self.model_name}")

    def _get_model_name(self) -> str:
        """Get model name with provider-specific defaults."""
        model = self.config.get("model")
        if model:
            return model

        # Provider-specific defaults
        defaults = {"openai": "gpt-4", "anthropic": "claude-3-5-sonnet-20241022", "ollama": "llama3.2"}
        return defaults.get(self.provider_name, "gpt-4")

    def _create_llm(self) -> BaseChatModel:
        """Create the appropriate LangChain LLM based on configuration."""
        if self.provider_name == "openai":
            return self._create_openai_llm()
        if self.provider_name == "anthropic":
            return self._create_anthropic_llm()
        if self.provider_name == "ollama":
            return self._create_ollama_llm()
        raise ValueError(f"Unsupported LLM provider: {self.provider_name}")

    def _create_openai_llm(self) -> BaseChatModel:
        """Create OpenAI LangChain LLM."""
        if ChatOpenAI is None:
            raise ImportError("langchain-openai package required. Install with: pip install langchain-openai")

        kwargs = {
            "model": self.model_name,
            "temperature": self.config.get("temperature", 0.1),
            "max_tokens": self.config.get("max_tokens", 4096),
        }

        # Optional API key override
        if "api_key" in self.config:
            kwargs["api_key"] = self.config["api_key"]
        elif os.getenv("OPENAI_API_KEY"):
            kwargs["api_key"] = os.getenv("OPENAI_API_KEY")
        elif self.strict_validation:
            raise ValueError("OPENAI_API_KEY environment variable or config api_key required")
        else:
            # For testing purposes, allow creation without API key (will fail at runtime)
            kwargs["api_key"] = "dummy-key"

        # Optional base URL for custom endpoints
        if "base_url" in self.config:
            kwargs["base_url"] = self.config["base_url"]

        return ChatOpenAI(**kwargs)

    def _create_anthropic_llm(self) -> BaseChatModel:
        """Create Anthropic LangChain LLM."""
        if ChatAnthropic is None:
            raise ImportError("langchain-anthropic package required. Install with: pip install langchain-anthropic")

        kwargs = {
            "model": self.model_name,
            "temperature": self.config.get("temperature", 0.1),
            "max_tokens": self.config.get("max_tokens", 4096),
        }

        # Optional API key override
        if "api_key" in self.config:
            kwargs["api_key"] = self.config["api_key"]
        elif os.getenv("ANTHROPIC_API_KEY"):
            kwargs["api_key"] = os.getenv("ANTHROPIC_API_KEY")
        elif self.strict_validation:
            raise ValueError("ANTHROPIC_API_KEY environment variable or config api_key required")
        else:
            # For testing purposes, allow creation without API key (will fail at runtime)
            kwargs["api_key"] = "dummy-key"

        return ChatAnthropic(**kwargs)

    def _create_ollama_llm(self) -> BaseChatModel:
        """Create Ollama LangChain LLM."""
        if ChatOllama is None:
            raise ImportError("langchain-community package required. Install with: pip install langchain-community")

        kwargs = {
            "model": self.model_name,
            "temperature": self.config.get("temperature", 0.1),
        }

        # Optional base URL override
        if "base_url" in self.config:
            kwargs["base_url"] = self.config["base_url"]
        else:
            kwargs["base_url"] = "http://localhost:11434"

        return ChatOllama(**kwargs)

    async def analyze_failure(
        self, failure_context: str, check_name: str, pr_info: dict[str, Any], project_context: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Analyze a CI/CD failure and determine next steps using structured output."""
        if project_context is None:
            project_context = {}

        try:
            # Create structured prompt with format instructions
            system_template = SystemMessagePromptTemplate.from_template(
                """You are an expert software engineer analyzing CI/CD failures.
Your job is to understand what went wrong and determine if the issue is fixable automatically.

Focus on common CI/CD issues that can be automatically resolved such as:
- Test failures with clear error messages
- Build errors (missing dependencies, syntax errors)
- Linting issues (formatting, code style)
- Simple configuration problems

{format_instructions}"""
            )

            human_template = HumanMessagePromptTemplate.from_template(
                """**Check Name:** {check_name}

**PR Information:**
- Title: {pr_title}
- Author: {pr_author}
- Files Changed: {files_changed} files

**Project Context:**
{project_context}

**Failure Details:**
{failure_context}

Please analyze this failure and provide your assessment."""
            )

            prompt = ChatPromptTemplate.from_messages([system_template, human_template])

            # Format the prompt with data
            formatted_prompt = prompt.format_prompt(
                format_instructions=self.failure_analysis_parser.get_format_instructions(),
                check_name=check_name,
                pr_title=pr_info.get("title", "N/A"),
                pr_author=pr_info.get("user", {}).get("login", "N/A"),
                files_changed=len(pr_info.get("changed_files", [])),
                project_context=self._format_project_context(project_context),
                failure_context=failure_context,
            )

            # Get LLM response
            response = await self.llm.ainvoke(formatted_prompt.to_messages())

            # Parse structured output
            try:
                content = response.content if isinstance(response.content, str) else str(response.content)
                analysis_data = self.failure_analysis_parser.parse(content)
                result = analysis_data.dict()
                result.update(
                    {
                        "success": True,
                        "llm_provider": self.provider_name,
                        "llm_model": self.model_name,
                    }
                )
                return result

            except Exception as parse_error:
                logger.warning(f"Failed to parse structured output, falling back to raw content: {parse_error}")
                # Fallback to unstructured parsing
                content = response.content if isinstance(response.content, str) else str(response.content)
                return self._parse_analysis_fallback(content)

        except Exception as e:
            logger.error(f"LangChain LLM error during failure analysis: {e}")
            return {
                "success": False,
                "error": str(e),
                "fixable": False,
                "analysis": "Failed to analyze due to LLM error",
                "llm_provider": self.provider_name,
                "llm_model": self.model_name,
            }

    async def should_escalate(
        self, failure_info: dict[str, Any], fix_attempts: int, max_attempts: int, project_context: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Determine if an issue should be escalated to humans using structured output."""
        if project_context is None:
            project_context = {}

        try:
            # Create structured prompt
            system_template = SystemMessagePromptTemplate.from_template(
                """You are an expert at triaging software issues and deciding when human intervention is needed.

Consider factors like:
- Number of failed fix attempts
- Severity and type of issue
- Security implications
- Project criticality
- Whether the issue is automatically fixable

{format_instructions}"""
            )

            human_template = HumanMessagePromptTemplate.from_template(
                """**Fix Attempts:** {fix_attempts} out of {max_attempts} maximum

**Failure Information:**
- Category: {category}
- Severity: {severity}
- Fixable: {fixable}
- Analysis: {analysis}

**Project Context:**
{project_context}

Should this issue be escalated to human developers? Provide your decision."""
            )

            prompt = ChatPromptTemplate.from_messages([system_template, human_template])

            # Format the prompt
            formatted_prompt = prompt.format_prompt(
                format_instructions=self.escalation_parser.get_format_instructions(),
                fix_attempts=fix_attempts,
                max_attempts=max_attempts,
                category=failure_info.get("category", "unknown"),
                severity=failure_info.get("severity", "unknown"),
                fixable=failure_info.get("fixable", False),
                analysis=failure_info.get("analysis", "No analysis available"),
                project_context=self._format_project_context(project_context),
            )

            # Get LLM response
            response = await self.llm.ainvoke(formatted_prompt.to_messages())

            # Parse structured output
            try:
                content = response.content if isinstance(response.content, str) else str(response.content)
                escalation_data = self.escalation_parser.parse(content)
                result = escalation_data.dict()
                result.update(
                    {
                        "llm_provider": self.provider_name,
                        "llm_model": self.model_name,
                    }
                )
                return result

            except Exception as parse_error:
                logger.warning(f"Failed to parse escalation output, falling back: {parse_error}")
                content = response.content if isinstance(response.content, str) else str(response.content)
                return self._parse_escalation_fallback(content)

        except Exception as e:
            logger.error(f"LangChain LLM error during escalation decision: {e}")
            # Default to escalation if LLM fails
            return {
                "should_escalate": True,
                "urgency": "medium",
                "reason": f"LLM analysis failed: {e}",
                "suggested_actions": ["Manual investigation required"],
                "escalation_message": "Automated analysis unavailable",
                "llm_provider": self.provider_name,
                "llm_model": self.model_name,
            }

    async def generate_response(self, messages: list[BaseMessage], **kwargs) -> LLMResponse:
        """Generic method to generate responses using LangChain."""
        try:
            response = await self.llm.ainvoke(messages, **kwargs)

            # Extract usage information if available
            usage = {}
            if hasattr(response, "response_metadata") and response.response_metadata:
                token_usage = response.response_metadata.get("token_usage", {})
                if token_usage:
                    usage = {
                        "prompt_tokens": token_usage.get("prompt_tokens", 0),
                        "completion_tokens": token_usage.get("completion_tokens", 0),
                        "total_tokens": token_usage.get("total_tokens", 0),
                    }

            content = response.content if isinstance(response.content, str) else str(response.content)
            return LLMResponse(content=content, provider=self.provider_name, model=self.model_name, usage=usage, success=True)

        except Exception as e:
            logger.error(f"LangChain LLM generation error: {e}")
            return LLMResponse(content="", provider=self.provider_name, model=self.model_name, success=False, error=str(e))

    def _format_project_context(self, project_context: dict[str, str]) -> str:
        """Format project context for prompt inclusion."""
        if not project_context:
            return "No additional context provided."

        formatted = []
        for key, value in project_context.items():
            formatted.append(f"- {key}: {value}")
        return "\n".join(formatted)

    def _parse_analysis_fallback(self, content: str) -> dict[str, Any]:
        """Fallback parsing for analysis when structured parsing fails."""
        # Simple heuristic parsing as fallback
        content_lower = content.lower()

        return {
            "success": True,
            "fixable": any(
                indicator in content_lower for indicator in ["fixable", "can be fixed", "automatically", "simple fix"]
            ),
            "severity": "medium",  # Default
            "category": "unknown",
            "analysis": content,
            "suggested_fix": "Manual review required",
            "confidence": 0.5,
            "llm_provider": self.provider_name,
            "llm_model": self.model_name,
        }

    def _parse_escalation_fallback(self, content: str) -> dict[str, Any]:
        """Fallback parsing for escalation when structured parsing fails."""
        content_lower = content.lower()

        should_escalate = any(indicator in content_lower for indicator in ["escalate", "human", "manual", "intervention"])

        return {
            "should_escalate": should_escalate,
            "urgency": "medium",
            "reason": "Fallback parsing - manual review recommended",
            "suggested_actions": ["Manual investigation required"],
            "escalation_message": content[:200] + "..." if len(content) > 200 else content,
            "llm_provider": self.provider_name,
            "llm_model": self.model_name,
        }

    def is_available(self) -> bool:
        """Check if the configured LLM provider is available."""
        try:
            # Basic availability check - more sophisticated checks could be added
            if self.provider_name == "openai":
                has_api_key = self.config.get("api_key") is not None or os.getenv("OPENAI_API_KEY") is not None
                return ChatOpenAI is not None and has_api_key
            if self.provider_name == "anthropic":
                has_api_key = self.config.get("api_key") is not None or os.getenv("ANTHROPIC_API_KEY") is not None
                return ChatAnthropic is not None and has_api_key
            if self.provider_name == "ollama":
                return ChatOllama is not None
            return False
        except Exception:
            return False

    def get_provider_info(self) -> dict[str, Any]:
        """Get information about the current provider configuration."""
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "available": self.is_available(),
            "config": {k: v for k, v in self.config.items() if k != "api_key"},  # Exclude sensitive data
        }
