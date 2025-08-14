"""LangChain-based Claude tool for PR Check Agent

Replaces subprocess-based Claude CLI with direct LangChain integration.
Provides better error handling, structured outputs, and LangChain ecosystem benefits.
"""

import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from langchain.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field

try:
    from langchain_anthropic import ChatAnthropic
except ImportError:
    ChatAnthropic = None  # type: ignore[assignment,misc]


class AnalysisResult(BaseModel):
    """Structured output for code analysis."""
    
    root_cause: str = Field(description="Root cause analysis of the failure")
    is_fixable: bool = Field(description="Whether this is automatically fixable")
    fix_steps: List[str] = Field(description="Specific steps to resolve the issue")
    side_effects: List[str] = Field(description="Potential side effects of the fix", default_factory=list)
    confidence: float = Field(description="Confidence in the analysis (0.0-1.0)", ge=0.0, le=1.0)


class FixResult(BaseModel):
    """Structured output for fix attempts."""
    
    success: bool = Field(description="Whether the fix was successful")
    description: str = Field(description="Description of changes made")
    files_affected: List[str] = Field(description="List of files that would be modified")
    additional_steps: List[str] = Field(description="Additional steps needed", default_factory=list)
    verification_commands: List[str] = Field(description="Commands to verify the fix", default_factory=list)


class LangChainClaudeInput(BaseModel):
    """Input schema for LangChain Claude operations."""

    operation: str = Field(description="Operation: 'analyze_failure' or 'fix_issue'")
    failure_context: str = Field(description="Context about the failure (logs, error messages)")
    check_name: str = Field(description="Name of the failing check")
    pr_info: Dict[str, Any] = Field(description="PR information for context")
    project_context: Dict[str, str] = Field(default={}, description="Project-specific context")
    repository_path: Optional[str] = Field(default=None, description="Path to repository (for context)")


class LangChainClaudeTool(BaseTool):
    """LangChain-based Claude tool for code analysis and fixing."""

    name: str = "langchain_claude"
    description: str = "Use LangChain Claude integration to analyze and suggest fixes for code issues"
    args_schema: type = LangChainClaudeInput

    class Config:
        extra = "allow"

    def __init__(self, dry_run: bool = False, model: str = "claude-3-5-sonnet-20241022"):
        super().__init__()
        
        self.dry_run = dry_run
        self.model = model
        
        # Initialize Claude LLM
        if not dry_run:
            self.claude_llm = self._create_claude_llm()
        else:
            self.claude_llm = None
            
        # Initialize parsers
        self.analysis_parser = PydanticOutputParser(pydantic_object=AnalysisResult)
        self.fix_parser = PydanticOutputParser(pydantic_object=FixResult)
        
        logger.info(f"LangChain Claude tool initialized (dry_run={dry_run}, model={model})")

    def _create_claude_llm(self) -> "ChatAnthropic":
        """Create Claude LangChain LLM."""
        if ChatAnthropic is None:
            raise ImportError("langchain-anthropic package required. Install with: pip install langchain-anthropic")
        
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")
        
        return ChatAnthropic(
            model=self.model,
            api_key=api_key,
            temperature=0.1,
            max_tokens=4096
        )

    def _run(self, operation: str, **kwargs) -> Dict[str, Any]:
        """Synchronous wrapper - not implemented for async tool."""
        raise NotImplementedError("Use _arun for async operation")

    async def _arun(
        self,
        operation: str,
        failure_context: str,
        check_name: str,
        pr_info: Dict[str, Any],
        project_context: Optional[Dict[str, str]] = None,
        repository_path: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute Claude operation using LangChain."""
        if project_context is None:
            project_context = {}

        start_time = datetime.now()
        attempt_id = str(uuid.uuid4())

        try:
            if operation == "analyze_failure":
                return await self._analyze_failure_structured(
                    attempt_id, failure_context, check_name, pr_info, project_context
                )
            elif operation == "fix_issue":
                return await self._fix_issue_structured(
                    attempt_id, failure_context, check_name, pr_info, project_context, repository_path
                )
            else:
                raise ValueError(f"Unknown operation: {operation}")

        except Exception as e:
            logger.error(f"LangChain Claude error: {e}")
            return {
                "success": False,
                "error": str(e),
                "attempt_id": attempt_id,
                "duration_seconds": (datetime.now() - start_time).total_seconds(),
            }

    async def _analyze_failure_structured(
        self, 
        attempt_id: str, 
        failure_context: str, 
        check_name: str, 
        pr_info: Dict[str, Any], 
        project_context: Dict[str, str]
    ) -> Dict[str, Any]:
        """Analyze failure using structured LangChain prompts."""
        logger.info(f"Analyzing failure for {check_name} (attempt {attempt_id})")

        if self.dry_run:
            return self._mock_analyze_response(attempt_id, check_name)

        try:
            # Create structured prompt
            system_template = SystemMessagePromptTemplate.from_template(
                """You are an expert software engineer specializing in CI/CD troubleshooting and automated fixes.

Your task is to analyze code failures and provide detailed, actionable insights.

Focus on:
- Identifying the exact root cause
- Determining if the issue can be automatically fixed
- Providing specific, implementable steps
- Considering potential side effects

{format_instructions}"""
            )
            
            human_template = HumanMessagePromptTemplate.from_template(
                """**Failure Analysis Request**

**Check Name:** {check_name}
**PR Info:** #{pr_number} - {pr_title} by {pr_author}
**Branch:** {pr_branch} → {pr_base_branch}

**Project Context:**
{project_context}

**Failure Details:**
```
{failure_context}
```

Please analyze this failure thoroughly and provide a structured response."""
            )
            
            prompt = ChatPromptTemplate.from_messages([system_template, human_template])
            
            # Format prompt
            formatted_prompt = prompt.format_prompt(
                format_instructions=self.analysis_parser.get_format_instructions(),
                check_name=check_name,
                pr_number=pr_info.get("number", "N/A"),
                pr_title=pr_info.get("title", "N/A"),
                pr_author=pr_info.get("user", {}).get("login", "N/A"),
                pr_branch=pr_info.get("branch", "N/A"),
                pr_base_branch=pr_info.get("base_branch", "N/A"),
                project_context=self._format_project_context(project_context),
                failure_context=failure_context
            )
            
            # Get response
            start_time = datetime.now()
            response = await self.claude_llm.ainvoke(formatted_prompt.to_messages())
            duration = (datetime.now() - start_time).total_seconds()
            
            # Parse structured output
            try:
                analysis_data = self.analysis_parser.parse(response.content)
                
                return {
                    "success": True,
                    "analysis": analysis_data.root_cause,
                    "fixable": analysis_data.is_fixable,
                    "suggested_actions": analysis_data.fix_steps,
                    "side_effects": analysis_data.side_effects,
                    "confidence": analysis_data.confidence,
                    "attempt_id": attempt_id,
                    "duration_seconds": duration,
                    "raw_response": response.content,
                }
                
            except Exception as parse_error:
                logger.warning(f"Failed to parse structured analysis output: {parse_error}")
                # Fallback to unstructured
                return {
                    "success": True,
                    "analysis": response.content,
                    "fixable": self._heuristic_is_fixable(response.content),
                    "suggested_actions": self._extract_actions_heuristic(response.content),
                    "side_effects": [],
                    "confidence": 0.7,
                    "attempt_id": attempt_id,
                    "duration_seconds": duration,
                    "raw_response": response.content,
                }
                
        except Exception as e:
            logger.error(f"Analysis error: {e}")
            return {
                "success": False,
                "error": str(e),
                "attempt_id": attempt_id,
                "duration_seconds": 0,
            }

    async def _fix_issue_structured(
        self,
        attempt_id: str,
        failure_context: str,
        check_name: str,
        pr_info: Dict[str, Any],
        project_context: Dict[str, str],
        repository_path: Optional[str]
    ) -> Dict[str, Any]:
        """Suggest fixes using structured LangChain prompts."""
        logger.info(f"Generating fix suggestions for {check_name} (attempt {attempt_id})")

        if self.dry_run:
            return self._mock_fix_response(attempt_id, check_name)

        try:
            # Create structured prompt for fixing
            system_template = SystemMessagePromptTemplate.from_template(
                """You are an expert software engineer who specializes in automatically fixing CI/CD issues.

Your task is to provide specific, implementable fixes for code failures.

Guidelines:
- Provide minimal, targeted changes
- Follow project conventions and best practices
- Include verification steps
- Consider the broader impact of changes
- Be specific about which files need modification

{format_instructions}"""
            )
            
            human_template = HumanMessagePromptTemplate.from_template(
                """**Fix Request**

**Check Name:** {check_name}
**PR Info:** #{pr_number} - {pr_title}

**Project Context:**
{project_context}

**Issue to Fix:**
```
{failure_context}
```

Please provide a structured fix plan that can be implemented programmatically."""
            )
            
            prompt = ChatPromptTemplate.from_messages([system_template, human_template])
            
            # Format prompt
            formatted_prompt = prompt.format_prompt(
                format_instructions=self.fix_parser.get_format_instructions(),
                check_name=check_name,
                pr_number=pr_info.get("number", "N/A"),
                pr_title=pr_info.get("title", "N/A"),
                project_context=self._format_project_context(project_context),
                failure_context=failure_context
            )
            
            # Get response
            start_time = datetime.now()
            response = await self.claude_llm.ainvoke(formatted_prompt.to_messages())
            duration = (datetime.now() - start_time).total_seconds()
            
            # Parse structured output
            try:
                fix_data = self.fix_parser.parse(response.content)
                
                return {
                    "success": fix_data.success,
                    "fix_description": fix_data.description,
                    "files_modified": fix_data.files_affected,
                    "additional_steps": fix_data.additional_steps,
                    "verification_commands": fix_data.verification_commands,
                    "attempt_id": attempt_id,
                    "duration_seconds": duration,
                    "raw_response": response.content,
                }
                
            except Exception as parse_error:
                logger.warning(f"Failed to parse structured fix output: {parse_error}")
                # Fallback to unstructured
                return {
                    "success": True,  # Assume success for fallback
                    "fix_description": response.content,
                    "files_modified": [],  # Cannot extract reliably
                    "additional_steps": [],
                    "verification_commands": [],
                    "attempt_id": attempt_id,
                    "duration_seconds": duration,
                    "raw_response": response.content,
                }
                
        except Exception as e:
            logger.error(f"Fix generation error: {e}")
            return {
                "success": False,
                "error": str(e),
                "attempt_id": attempt_id,
                "duration_seconds": 0,
            }

    def _format_project_context(self, project_context: Dict[str, str]) -> str:
        """Format project context for prompt inclusion."""
        if not project_context:
            return "No additional project context provided."
        
        formatted = []
        for key, value in project_context.items():
            formatted.append(f"- {key}: {value}")
        return "\n".join(formatted)

    def _heuristic_is_fixable(self, content: str) -> bool:
        """Heuristic determination of fixability."""
        content_lower = content.lower()
        
        fixable_indicators = [
            "can be fixed", "automatically fixable", "simple fix",
            "syntax error", "missing import", "typo", "formatting",
            "dependency", "version", "configuration"
        ]
        
        unfixable_indicators = [
            "cannot be fixed", "not fixable", "manual intervention",
            "complex logic", "architecture", "design issue"
        ]
        
        fixable_score = sum(1 for indicator in fixable_indicators if indicator in content_lower)
        unfixable_score = sum(1 for indicator in unfixable_indicators if indicator in content_lower)
        
        return fixable_score > unfixable_score

    def _extract_actions_heuristic(self, content: str) -> List[str]:
        """Extract action items using heuristics."""
        lines = content.split("\n")
        actions = []
        
        for line in lines:
            line = line.strip()
            if (line.startswith(("- ", "* ")) or 
                any(line.startswith(f"{i}.") for i in range(1, 10))):
                
                # Clean up the action text
                if line.startswith(("- ", "* ")):
                    action = line[2:].strip()
                else:
                    # Remove number prefix
                    action = line.split(".", 1)[1].strip() if "." in line else line
                
                if action and len(action) > 10:  # Filter out very short items
                    actions.append(action)
                    
        return actions[:5]  # Limit to 5 actions

    def _mock_analyze_response(self, attempt_id: str, check_name: str) -> Dict[str, Any]:
        """Mock response for analysis in dry-run mode."""
        return {
            "success": True,
            "analysis": f"Mock analysis for {check_name}: Root cause appears to be related to {check_name.lower()} configuration or dependencies.",
            "fixable": True,
            "suggested_actions": [
                f"Review {check_name.lower()} configuration",
                "Check dependency versions",
                "Verify environment setup",
                "Run local tests to reproduce"
            ],
            "side_effects": ["May affect related functionality"],
            "confidence": 0.8,
            "attempt_id": attempt_id,
            "duration_seconds": 2.5,
        }

    def _mock_fix_response(self, attempt_id: str, check_name: str) -> Dict[str, Any]:
        """Mock response for fixes in dry-run mode."""
        return {
            "success": True,
            "fix_description": f"Mock fix for {check_name}: Applied automated fixes to resolve the issue.",
            "files_modified": ["src/example.py", "tests/test_example.py", "requirements.txt"],
            "additional_steps": ["Run tests to verify fix"],
            "verification_commands": ["python -m pytest", "ruff check .", "mypy ."],
            "attempt_id": attempt_id,
            "duration_seconds": 5.0,
        }

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on LangChain Claude integration."""
        try:
            if self.dry_run:
                return {
                    "status": "healthy", 
                    "mode": "dry_run",
                    "provider": "langchain_anthropic",
                    "model": self.model
                }

            if not self.claude_llm:
                return {"status": "unhealthy", "error": "Claude LLM not initialized"}

            # Test with simple message
            test_message = HumanMessage(content="Hello, respond with 'OK' if you can hear me.")
            response = await self.claude_llm.ainvoke([test_message])
            
            return {
                "status": "healthy",
                "mode": "production", 
                "provider": "langchain_anthropic",
                "model": self.model,
                "test_response": response.content[:50] + "..." if len(response.content) > 50 else response.content
            }

        except Exception as e:
            return {
                "status": "unhealthy", 
                "error": str(e),
                "provider": "langchain_anthropic",
                "model": self.model
            }