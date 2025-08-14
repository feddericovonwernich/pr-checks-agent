"""LangChain-based Claude tool for PR Check Agent

Hybrid approach:
- Uses LangChain for failure analysis (structured outputs, better error handling)
- Uses Claude Code CLI for actual repository fixes (real file modifications)
"""

import asyncio
import os
import subprocess  # nosec B404 - subprocess is used to invoke trusted Claude CLI only
import tempfile
import uuid
from datetime import datetime
from typing import Any

from langchain.tools import BaseTool
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
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
    fix_steps: list[str] = Field(description="Specific steps to resolve the issue")
    side_effects: list[str] = Field(description="Potential side effects of the fix", default_factory=list)
    confidence: float = Field(description="Confidence in the analysis (0.0-1.0)", ge=0.0, le=1.0)


class FixResult(BaseModel):
    """Structured output for fix attempts."""

    success: bool = Field(description="Whether the fix was successful")
    description: str = Field(description="Description of changes made")
    files_affected: list[str] = Field(description="List of files that would be modified")
    additional_steps: list[str] = Field(description="Additional steps needed", default_factory=list)
    verification_commands: list[str] = Field(description="Commands to verify the fix", default_factory=list)


class LangChainClaudeInput(BaseModel):
    """Input schema for LangChain Claude operations."""

    operation: str = Field(description="Operation: 'analyze_failure' or 'fix_issue'")
    failure_context: str = Field(description="Context about the failure (logs, error messages)")
    check_name: str = Field(description="Name of the failing check")
    pr_info: dict[str, Any] = Field(description="PR information for context")
    project_context: dict[str, str] = Field(default={}, description="Project-specific context")
    repository_path: str | None = Field(default=None, description="Path to repository (for context)")


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
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")

        if not self.anthropic_api_key and not dry_run:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")

        # Initialize Claude LLM for analysis
        if not dry_run:
            self.claude_llm = self._create_claude_llm()
        else:
            self.claude_llm = None

        # Check Claude Code CLI availability
        self._check_claude_cli()

        # Initialize parsers
        self.analysis_parser = PydanticOutputParser(pydantic_object=AnalysisResult)
        self.fix_parser = PydanticOutputParser(pydantic_object=FixResult)

        logger.info(f"LangChain Claude tool initialized (dry_run={dry_run}, model={model})")

    def _check_claude_cli(self) -> None:
        """Check if claude-code CLI is available."""
        try:
            result = subprocess.run(["claude", "--version"], check=False, capture_output=True, text=True, timeout=10)  # nosec B603 B607 - trusted Claude CLI invocation

            if result.returncode == 0:
                logger.info(f"Claude CLI available: {result.stdout.strip()}")
            else:
                logger.warning("Claude CLI not found, fix operations will use API fallback")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("Claude CLI not available, fix operations will use API fallback")

    def _create_claude_llm(self) -> "ChatAnthropic":
        """Create Claude LangChain LLM."""
        if ChatAnthropic is None:
            raise ImportError("langchain-anthropic package required. Install with: pip install langchain-anthropic")

        return ChatAnthropic(model=self.model, api_key=self.anthropic_api_key, temperature=0.1, max_tokens=4096)

    def _run(self, operation: str, **kwargs) -> dict[str, Any]:
        """Synchronous wrapper - not implemented for async tool."""
        raise NotImplementedError("Use _arun for async operation")

    async def _arun(
        self,
        operation: str,
        failure_context: str,
        check_name: str,
        pr_info: dict[str, Any],
        project_context: dict[str, str] | None = None,
        repository_path: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
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
            if operation == "fix_issue":
                return await self._fix_issue_structured(
                    attempt_id, failure_context, check_name, pr_info, project_context, repository_path
                )
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
        self, attempt_id: str, failure_context: str, check_name: str, pr_info: dict[str, Any], project_context: dict[str, str]
    ) -> dict[str, Any]:
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
                failure_context=failure_context,
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
        pr_info: dict[str, Any],
        project_context: dict[str, str],
        repository_path: str | None,
    ) -> dict[str, Any]:
        """Fix issues using Claude Code CLI for actual file modifications."""
        logger.info(f"Attempting fix for {check_name} using Claude Code CLI (attempt {attempt_id})")

        if self.dry_run:
            return self._mock_fix_response(attempt_id, check_name)

        if not repository_path:
            return {
                "success": False,
                "error": "Repository path required for fix operations",
                "attempt_id": attempt_id,
                "duration_seconds": 0,
            }

        try:
            # Create fix prompt for Claude Code CLI
            prompt = self._create_fix_prompt(failure_context, check_name, pr_info, project_context)

            # Execute Claude Code CLI with repository context
            result = await self._execute_claude_cli(prompt, working_directory=repository_path)

            return {
                "success": result["success"],
                "fix_description": result.get("output", ""),
                "files_modified": result.get("files_modified", []),
                "git_diff": result.get("git_diff", ""),
                "additional_steps": result.get("additional_steps", []),
                "verification_commands": result.get("verification_commands", []),
                "attempt_id": attempt_id,
                "duration_seconds": result.get("duration_seconds", 0),
                "error": result.get("error"),
            }

        except Exception as e:
            logger.error(f"Claude Code CLI fix error: {e}")
            return {
                "success": False,
                "error": str(e),
                "attempt_id": attempt_id,
                "duration_seconds": 0,
            }

    def _create_fix_prompt(
        self, failure_context: str, check_name: str, pr_info: dict[str, Any], project_context: dict[str, str]
    ) -> str:
        """Create prompt for automated fixing using Claude Code CLI."""
        prompt = f"""Fix this CI/CD check failure:

**Check Name**: {check_name}
**PR**: #{pr_info.get("number")} - {pr_info.get("title", "")}
**Branch**: {pr_info.get("branch", "unknown")}

**Project Context**:
"""

        for key, value in project_context.items():
            prompt += f"- {key}: {value}\n"

        prompt += f"""
**Failure Details**:
```
{failure_context}
```

Please complete the following workflow:

1. **Fix the Issue**:
   - Make the necessary code changes to resolve the failure
   - Ensure the fix is minimal and targeted
   - Follow project conventions and best practices

2. **Verify the Fix**:
   - Run relevant tests to confirm the fix works
   - For Python: run `pytest` or appropriate test command
   - For Node.js: run `npm test` or appropriate test command
   - If tests fail, attempt to fix them as well

3. **Commit the Changes**:
   - Stage all modified files: `git add -A`
   - Commit with descriptive message: `git commit -m "Fix {check_name}: <brief description of what was fixed>"`
   - Include details about what was causing the issue and how it was resolved

4. **Push to PR Branch**:
   - Push the changes: `git push origin {pr_info.get("branch", "HEAD")}`
   - Ensure the push is successful

5. **Add PR Comment** (if possible):
   - Use `gh pr comment {pr_info.get("number", "")} --body "..."` to add a comment explaining:
     - What was broken
     - What was fixed
     - Test results
     - Any additional steps needed

**Important**:
- Complete ALL steps, not just the code changes
- If any step fails, document why and what manual intervention is needed
- Ensure all changes are properly committed and pushed
"""

        return prompt

    async def _execute_claude_cli(self, prompt: str, working_directory: str) -> dict[str, Any]:
        """Execute Claude Code CLI with the given prompt."""
        start_time = datetime.now()

        try:
            # Create temporary file for prompt
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write(prompt)
                prompt_file = f.name

            # Build Claude Code command
            cmd = ["claude", "--prompt-file", prompt_file, "--output-format", "json"]

            # Set environment with API key
            env = os.environ.copy()
            if self.anthropic_api_key:
                env["ANTHROPIC_API_KEY"] = self.anthropic_api_key

            logger.info(f"Executing Claude Code CLI in {working_directory}")

            # Execute command
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=working_directory, env=env
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)

            # Clean up temp file
            os.unlink(prompt_file)

            duration = (datetime.now() - start_time).total_seconds()

            if process.returncode == 0:
                output = stdout.decode().strip()
                logger.info(f"Claude Code CLI completed successfully in {duration:.2f}s")

                # Try to extract additional info (files modified, git diff)
                files_modified = await self._get_modified_files(working_directory)
                git_diff = await self._get_git_diff(working_directory)

                return {
                    "success": True,
                    "output": output,
                    "files_modified": files_modified,
                    "git_diff": git_diff,
                    "duration_seconds": duration,
                }
            error_msg = stderr.decode().strip()
            logger.error(f"Claude Code CLI failed: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "duration_seconds": duration,
            }

        except TimeoutError:
            logger.error("Claude Code CLI execution timed out")
            return {
                "success": False,
                "error": "Claude Code execution timed out (5 minutes)",
                "duration_seconds": 300,
            }
        except Exception as e:
            logger.error(f"Error executing Claude Code CLI: {e}")
            return {
                "success": False,
                "error": str(e),
                "duration_seconds": (datetime.now() - start_time).total_seconds(),
            }

    async def _get_modified_files(self, working_directory: str) -> list[str]:
        """Get list of files modified by Claude Code CLI."""
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "diff",
                "--name-only",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_directory,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)

            if process.returncode == 0:
                files = stdout.decode().strip().split("\n")
                return [f for f in files if f.strip()]
            return []
        except Exception:
            return []

    async def _get_git_diff(self, working_directory: str) -> str:
        """Get git diff of changes made by Claude Code CLI."""
        try:
            process = await asyncio.create_subprocess_exec(
                "git", "diff", "HEAD", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=working_directory
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)

            if process.returncode == 0:
                return stdout.decode().strip()
            return ""
        except Exception:
            return ""

    def _format_project_context(self, project_context: dict[str, str]) -> str:
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
            "can be fixed",
            "automatically fixable",
            "simple fix",
            "syntax error",
            "missing import",
            "typo",
            "formatting",
            "dependency",
            "version",
            "configuration",
        ]

        unfixable_indicators = [
            "cannot be fixed",
            "not fixable",
            "manual intervention",
            "complex logic",
            "architecture",
            "design issue",
        ]

        fixable_score = sum(1 for indicator in fixable_indicators if indicator in content_lower)
        unfixable_score = sum(1 for indicator in unfixable_indicators if indicator in content_lower)

        return fixable_score > unfixable_score

    def _extract_actions_heuristic(self, content: str) -> list[str]:
        """Extract action items using heuristics."""
        lines = content.split("\n")
        actions = []

        for line in lines:
            line = line.strip()
            if line.startswith(("- ", "* ")) or any(line.startswith(f"{i}.") for i in range(1, 10)):
                # Clean up the action text
                if line.startswith(("- ", "* ")):
                    action = line[2:].strip()
                else:
                    # Remove number prefix
                    action = line.split(".", 1)[1].strip() if "." in line else line

                if action and len(action) > 10:  # Filter out very short items
                    actions.append(action)

        return actions[:5]  # Limit to 5 actions

    def _mock_analyze_response(self, attempt_id: str, check_name: str) -> dict[str, Any]:
        """Mock response for analysis in dry-run mode."""
        return {
            "success": True,
            "analysis": f"Mock analysis for {check_name}: Root cause appears to be related to {check_name.lower()} configuration or dependencies.",
            "fixable": True,
            "suggested_actions": [
                f"Review {check_name.lower()} configuration",
                "Check dependency versions",
                "Verify environment setup",
                "Run local tests to reproduce",
            ],
            "side_effects": ["May affect related functionality"],
            "confidence": 0.8,
            "attempt_id": attempt_id,
            "duration_seconds": 2.5,
        }

    def _mock_fix_response(self, attempt_id: str, check_name: str) -> dict[str, Any]:
        """Mock response for fixes in dry-run mode."""
        return {
            "success": True,
            "fix_description": f"Mock fix for {check_name}: Applied fixes, ran tests, committed, and pushed changes.",
            "files_modified": ["src/example.py", "tests/test_example.py", "requirements.txt"],
            "git_diff": "Mock git diff showing the changes made",
            "additional_steps": [],  # All steps completed by Claude
            "verification_commands": ["pytest", "ruff check", "mypy"],  # Commands that were run
            "commit_sha": "abc123def456",  # Mock commit SHA
            "push_status": "Successfully pushed to origin/feature-branch",
            "test_results": "All tests passed (15 passed, 0 failed)",
            "attempt_id": attempt_id,
            "duration_seconds": 15.0,  # Longer due to test execution
        }

    async def health_check(self) -> dict[str, Any]:
        """Perform health check on hybrid Claude integration."""
        try:
            if self.dry_run:
                return {
                    "status": "healthy",
                    "mode": "dry_run",
                    "langchain_api": "available",
                    "claude_cli": "not_tested",
                    "model": self.model,
                }

            health_status = {"mode": "production", "model": self.model}

            # Test LangChain API for analysis
            if self.claude_llm:
                try:
                    test_message = HumanMessage(content="Hello, respond with 'OK' if you can hear me.")
                    response = await self.claude_llm.ainvoke([test_message])
                    health_status["langchain_api"] = "healthy"
                    health_status["langchain_test_response"] = (
                        response.content[:50] + "..." if len(response.content) > 50 else response.content
                    )
                except Exception as api_error:
                    health_status["langchain_api"] = f"unhealthy: {api_error}"
            else:
                health_status["langchain_api"] = "not_initialized"

            # Test Claude CLI for fixes
            try:
                process = await asyncio.create_subprocess_exec(
                    "claude", "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)

                if process.returncode == 0:
                    version = stdout.decode().strip()
                    health_status["claude_cli"] = "healthy"
                    health_status["claude_cli_version"] = version
                else:
                    health_status["claude_cli"] = f"unhealthy: {stderr.decode().strip()}"
            except Exception as cli_error:
                health_status["claude_cli"] = f"unavailable: {cli_error}"

            # Overall status
            if health_status.get("langchain_api") == "healthy" and health_status.get("claude_cli") == "healthy":
                health_status["status"] = "healthy"
            else:
                health_status["status"] = "partial"  # Can still do analysis even without CLI

            return health_status

        except Exception as e:
            return {"status": "unhealthy", "error": str(e), "mode": "production", "model": self.model}
