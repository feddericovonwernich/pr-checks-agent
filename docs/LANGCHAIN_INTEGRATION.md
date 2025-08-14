# LangChain Integration Guide

This guide covers the LangChain-based LLM provider system in PR Check Agent, which replaces direct API integrations with a unified, standards-based approach.

## Overview

The PR Check Agent now uses **LangChain** for all LLM interactions, providing:

- **Unified Interface**: Consistent API across all providers (OpenAI, Anthropic, Ollama)
- **Better Error Handling**: Standardized error handling and retries
- **Structured Outputs**: Pydantic-based output parsing for reliable data extraction
- **Rich Ecosystem**: Access to LangChain's prompt templates, output parsers, and tools
- **Future-Proof**: Easy addition of new providers supported by LangChain

## Architecture

### Core Components

1. **LangChainLLMService** (`src/services/langchain_llm_service.py`)
   - Main service for failure analysis and escalation decisions
   - Supports structured output parsing with Pydantic models
   - Handles multiple LLM providers through LangChain

2. **LangChainClaudeTool** (`src/tools/langchain_claude_tool.py`)
   - Replaces subprocess-based Claude CLI with direct API integration
   - Structured code analysis and fix suggestions
   - Better error handling and response parsing

### Migration Benefits

| Aspect | Before (Direct APIs) | After (LangChain) |
|--------|---------------------|-------------------|
| **Provider Support** | Manual integration for each | Unified LangChain interface |
| **Message Handling** | Custom format conversion | Standard LangChain messages |
| **Output Parsing** | Manual JSON parsing | Pydantic structured outputs |
| **Error Handling** | Provider-specific | Standardized across providers |
| **Ecosystem Access** | Limited | Full LangChain ecosystem |

## Configuration

### Environment Variables

The LangChain integration uses the same environment variables as before:

```bash
# LLM Provider Selection
LLM_PROVIDER=openai          # openai, anthropic, or ollama
LLM_MODEL=gpt-4             # Provider-specific model name
LLM_TEMPERATURE=0.1         # Temperature for responses
LLM_BASE_URL=               # Optional: Custom endpoint URL

# API Keys (same as before)
OPENAI_API_KEY=sk-...       # For OpenAI provider
ANTHROPIC_API_KEY=sk-ant-...# For Anthropic provider
# Ollama requires no API key
```

### Configuration File (`config/repos.json`)

The repository configuration remains unchanged:

```json
{
  "repositories": [
    {
      "owner": "your-org",
      "repo": "your-repo",
      "llm": {
        "provider": "anthropic",
        "model": "claude-3-5-sonnet-20241022",
        "temperature": 0.1
      }
    }
  ]
}
```

## Supported Providers

### 1. OpenAI

**Models**: `gpt-4`, `gpt-4-turbo`, `gpt-3.5-turbo`

**Configuration**:
```json
{
  "provider": "openai",
  "model": "gpt-4",
  "api_key": "sk-...",
  "base_url": "https://api.openai.com/v1"  // Optional
}
```

**Package**: `langchain-openai`

### 2. Anthropic (Claude)

**Models**: `claude-3-5-sonnet-20241022`, `claude-3-haiku-20240307`, `claude-3-opus-20240229`

**Configuration**:
```json
{
  "provider": "anthropic",
  "model": "claude-3-5-sonnet-20241022",
  "api_key": "sk-ant-..."
}
```

**Package**: `langchain-anthropic`

### 3. Ollama (Local Models)

**Models**: `llama3.2`, `codellama`, `mistral`, etc.

**Configuration**:
```json
{
  "provider": "ollama",
  "model": "llama3.2",
  "base_url": "http://localhost:11434"
}
```

**Package**: `langchain-community`

## Structured Outputs

### Failure Analysis

The `analyze_failure` method now returns structured data:

```python
class FailureAnalysis(BaseModel):
    fixable: bool                    # Can be automatically fixed
    severity: str                    # low, medium, high, critical
    category: str                    # test_failure, build_error, etc.
    analysis: str                    # Detailed explanation
    suggested_fix: str               # What should be done
    confidence: float                # 0.0 to 1.0
```

**Example Output**:
```json
{
  "fixable": true,
  "severity": "medium", 
  "category": "test_failure",
  "analysis": "Test is failing due to incorrect assertion comparing expected vs actual values",
  "suggested_fix": "Update test assertion to match the corrected expected value",
  "confidence": 0.85
}
```

### Escalation Decisions

The `should_escalate` method returns structured decisions:

```python
class EscalationDecision(BaseModel):
    should_escalate: bool            # Needs human attention
    urgency: str                     # low, medium, high, critical
    reason: str                      # Why escalation is/isn't needed
    suggested_actions: List[str]     # Actions for humans
    escalation_message: str          # Brief notification message
```

## Advanced Features

### Custom Prompts

LangChain integration uses structured prompts with templates:

```python
from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an expert software engineer..."),
    ("human", "Analyze this failure: {failure_context}")
])
```

### Output Parsers

Structured parsing with automatic retry and validation:

```python
from langchain_core.output_parsers import PydanticOutputParser

parser = PydanticOutputParser(pydantic_object=FailureAnalysis)
# Automatically validates and converts to Pydantic model
```

### Error Handling

Standardized error handling with fallbacks:

```python
try:
    # Try structured parsing
    result = parser.parse(response.content)
except Exception:
    # Fallback to heuristic parsing
    result = fallback_parse(response.content)
```

## Migration Guide

### For Developers

If you were using the old `LLMService`, update your imports:

```python
# Before
from services.llm_provider import LLMService

# After  
from services.langchain_llm_service import LangChainLLMService
```

The API remains largely the same:

```python
# Same usage pattern
llm_service = LangChainLLMService(config)
result = await llm_service.analyze_failure(
    failure_context="...",
    check_name="CI",
    pr_info={...}
)
```

### For Claude Tool Users

```python
# Before
from tools.claude_tool import ClaudeCodeTool

# After
from tools.langchain_claude_tool import LangChainClaudeTool
```

## Installation

### Required Packages

Add to your `requirements.txt`:

```text
# Core LangChain
langchain>=0.2.0
langchain-core>=0.2.0

# Provider-specific packages (install as needed)
langchain-openai>=0.1.0        # For OpenAI
langchain-anthropic>=0.1.0     # For Anthropic
langchain-community>=0.2.0     # For Ollama and others
```

### Install Command

```bash
pip install langchain langchain-core langchain-openai langchain-anthropic langchain-community
```

## Testing

### Unit Tests

The new services have comprehensive test coverage:

```bash
# Test LangChain LLM Service
python -m pytest tests/unit/test_services/test_langchain_llm_service.py -v

# Test LangChain Claude Tool
python -m pytest tests/unit/test_tools/test_langchain_claude_tool.py -v
```

### Integration Tests

Test with real providers using environment variables:

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...

python -m pytest tests/integration/ -v
```

## Performance Considerations

### Token Usage

LangChain integration includes better token tracking:

```python
result = await llm_service.generate_response(messages)
print(f"Used {result.usage['total_tokens']} tokens")
```

### Caching

Consider implementing caching for repeated analyses:

```python
from langchain.cache import InMemoryCache
from langchain.globals import set_llm_cache

set_llm_cache(InMemoryCache())
```

### Rate Limiting

Use LangChain's built-in rate limiting:

```python
from langchain.callbacks import get_callback_manager

# Configure callbacks for rate limiting
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure provider-specific packages are installed
   ```bash
   pip install langchain-openai  # For OpenAI
   ```

2. **API Key Issues**: Verify environment variables are set correctly
   ```bash
   echo $OPENAI_API_KEY
   ```

3. **Model Not Found**: Check if the model name is correct for your provider
   ```python
   # Valid OpenAI models: gpt-4, gpt-3.5-turbo
   # Valid Anthropic models: claude-3-5-sonnet-20241022
   ```

4. **Parsing Errors**: The system includes fallback parsing for robustness

### Debug Logging

Enable debug logging to see LangChain internals:

```bash
export LOG_LEVEL=DEBUG
python src/main.py --log-level DEBUG
```

### Health Checks

Test provider availability:

```python
service = LangChainLLMService(config)
print(f"Provider available: {service.is_available()}")

tool = LangChainClaudeTool()
health = await tool.health_check()
print(f"Tool status: {health['status']}")
```

## Best Practices

### 1. Provider Selection

- **OpenAI**: Good general performance, fastest responses
- **Anthropic**: Excellent for code analysis, more thoughtful responses  
- **Ollama**: Local/private deployments, no API costs

### 2. Model Selection

- **Development**: Use faster, cheaper models (`gpt-3.5-turbo`, `claude-3-haiku`)
- **Production**: Use more capable models (`gpt-4`, `claude-3-5-sonnet`)

### 3. Error Handling

Always handle both structured and fallback parsing:

```python
try:
    # Primary structured approach
    result = parser.parse(response.content)
except Exception:
    # Fallback heuristic approach
    result = fallback_parse(response.content)
```

### 4. Monitoring

Monitor token usage and costs:

```python
total_tokens = sum(result.usage.get('total_tokens', 0) for result in results)
logger.info(f"Total tokens used: {total_tokens}")
```

## Future Enhancements

The LangChain integration enables:

- **Streaming Responses**: For real-time feedback
- **Advanced Callbacks**: For monitoring and debugging
- **Custom Chains**: For complex multi-step reasoning
- **Vector Stores**: For context-aware analysis using embeddings
- **Tool Calling**: For more sophisticated agent behaviors

## Support

For issues with the LangChain integration:

1. Check the logs for detailed error messages
2. Verify your provider configuration and API keys
3. Test with a minimal example to isolate the issue
4. Review the test files for usage examples

The migration maintains backward compatibility while providing a foundation for future AI/ML improvements.