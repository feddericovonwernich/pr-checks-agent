"""
Claude Code CLI tool for PR Check Agent
Handles Claude Code invocations as a LangGraph tool
"""

import asyncio
import os
import subprocess
import tempfile
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from langchain.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field


class ClaudeCodeInput(BaseModel):
    """Input schema for Claude Code operations."""
    operation: str = Field(description="Operation: 'analyze_failure' or 'fix_issue'")
    repository_path: Optional[str] = Field(default=None, description="Path to local repository clone")
    failure_context: str = Field(description="Context about the failure (logs, error messages)")
    check_name: str = Field(description="Name of the failing check")
    pr_info: Dict[str, Any] = Field(description="PR information for context")
    project_context: Dict[str, str] = Field(default={}, description="Project-specific context (language, frameworks)")


class ClaudeCodeTool(BaseTool):
    """LangGraph tool for Claude Code CLI operations."""
    
    name = "claude_code"
    description = "Invoke Claude Code CLI to analyze and fix code issues"
    args_schema = ClaudeCodeInput
    
    def __init__(self, dry_run: bool = False):
        super().__init__()
        
        self.dry_run = dry_run
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")
        
        # Check if claude-code CLI is available
        self._check_claude_cli()
        
        logger.info(f"Claude Code tool initialized (dry_run={dry_run})")
    
    def _check_claude_cli(self) -> None:
        """Check if claude-code CLI is available."""
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                logger.info(f"Claude CLI available: {result.stdout.strip()}")
            else:
                logger.warning("Claude CLI not found, using mock responses in development")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("Claude CLI not available, using mock responses")
    
    def _run(self, operation: str, **kwargs) -> Dict[str, Any]:
        """Synchronous wrapper for async operations."""
        return asyncio.run(self._arun(operation, **kwargs))
    
    async def _arun(
        self,
        operation: str,
        failure_context: str,
        check_name: str,
        pr_info: Dict[str, Any],
        repository_path: Optional[str] = None,
        project_context: Dict[str, str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute Claude Code operation."""
        
        if project_context is None:
            project_context = {}
        
        start_time = datetime.now()
        attempt_id = str(uuid.uuid4())
        
        try:
            if operation == "analyze_failure":
                return await self._analyze_failure(
                    attempt_id, failure_context, check_name, pr_info, project_context
                )
            elif operation == "fix_issue":
                return await self._fix_issue(
                    attempt_id, failure_context, check_name, pr_info, 
                    project_context, repository_path
                )
            else:
                raise ValueError(f"Unknown operation: {operation}")
                
        except Exception as e:
            logger.error(f"Claude Code error: {e}")
            return {
                "success": False,
                "error": str(e),
                "attempt_id": attempt_id,
                "duration_seconds": (datetime.now() - start_time).total_seconds()
            }
    
    async def _analyze_failure(
        self,
        attempt_id: str,
        failure_context: str,
        check_name: str,
        pr_info: Dict[str, Any],
        project_context: Dict[str, str]
    ) -> Dict[str, Any]:
        """Analyze a failure using Claude Code."""
        
        logger.info(f"Analyzing failure for {check_name} (attempt {attempt_id})")
        
        if self.dry_run:
            return self._mock_analyze_response(attempt_id, check_name)
        
        # Create analysis prompt
        prompt = self._create_analysis_prompt(
            failure_context, check_name, pr_info, project_context
        )
        
        # Execute Claude Code CLI
        result = await self._execute_claude_cli(prompt, "analyze")
        
        return {
            "success": result["success"],
            "analysis": result.get("output", ""),
            "fixable": self._is_fixable(result.get("output", "")),
            "suggested_actions": self._extract_actions(result.get("output", "")),
            "attempt_id": attempt_id,
            "duration_seconds": result.get("duration_seconds", 0),
            "error": result.get("error")
        }
    
    async def _fix_issue(
        self,
        attempt_id: str,
        failure_context: str,
        check_name: str,
        pr_info: Dict[str, Any],
        project_context: Dict[str, str],
        repository_path: Optional[str]
    ) -> Dict[str, Any]:
        """Attempt to fix an issue using Claude Code."""
        
        logger.info(f"Attempting fix for {check_name} (attempt {attempt_id})")
        
        if self.dry_run:
            return self._mock_fix_response(attempt_id, check_name)
        
        if not repository_path:
            return {
                "success": False,
                "error": "Repository path required for fix operations",
                "attempt_id": attempt_id
            }
        
        # Create fix prompt
        prompt = self._create_fix_prompt(
            failure_context, check_name, pr_info, project_context
        )
        
        # Execute Claude Code CLI with repository context
        result = await self._execute_claude_cli(
            prompt, "fix", working_directory=repository_path
        )
        
        return {
            "success": result["success"],
            "fix_description": result.get("output", ""),
            "files_modified": result.get("files_modified", []),
            "git_diff": result.get("git_diff", ""),
            "attempt_id": attempt_id,
            "duration_seconds": result.get("duration_seconds", 0),
            "error": result.get("error")
        }
    
    def _create_analysis_prompt(
        self,
        failure_context: str,
        check_name: str,
        pr_info: Dict[str, Any],
        project_context: Dict[str, str]
    ) -> str:
        """Create prompt for failure analysis."""
        
        prompt = f"""Analyze this CI/CD check failure:

**Check Name**: {check_name}
**PR**: #{pr_info.get('number')} - {pr_info.get('title', '')}
**Branch**: {pr_info.get('branch', '')} → {pr_info.get('base_branch', '')}

**Project Context**:
"""
        
        for key, value in project_context.items():
            prompt += f"- {key}: {value}\n"
        
        prompt += f"""
**Failure Context**:
```
{failure_context}
```

Please analyze this failure and provide:
1. Root cause analysis
2. Whether this is automatically fixable
3. Specific steps to resolve the issue
4. Any potential side effects of the fix

Focus on actionable solutions that can be implemented programmatically.
"""
        
        return prompt
    
    def _create_fix_prompt(
        self,
        failure_context: str,
        check_name: str,
        pr_info: Dict[str, Any],
        project_context: Dict[str, str]
    ) -> str:
        """Create prompt for automated fixing."""
        
        prompt = f"""Fix this CI/CD check failure:

**Check Name**: {check_name}
**PR**: #{pr_info.get('number')} - {pr_info.get('title', '')}

**Project Context**:
"""
        
        for key, value in project_context.items():
            prompt += f"- {key}: {value}\n"
        
        prompt += f"""
**Failure Details**:
```
{failure_context}
```

Please fix this issue by:
1. Making the necessary code changes
2. Ensuring the fix is minimal and targeted
3. Following project conventions and best practices
4. Adding appropriate tests if needed

Make only the changes necessary to fix this specific issue.
"""
        
        return prompt
    
    async def _execute_claude_cli(
        self,
        prompt: str,
        mode: str = "fix",
        working_directory: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute Claude Code CLI with the given prompt."""
        
        start_time = datetime.now()
        
        try:
            # Create temporary file for prompt
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write(prompt)
                prompt_file = f.name
            
            # Build command
            cmd = ["claude"]
            if mode == "analyze":
                cmd.extend(["--analyze"])
            
            cmd.extend([
                "--prompt-file", prompt_file,
                "--output-format", "json"
            ])
            
            # Set environment
            env = os.environ.copy()
            env["ANTHROPIC_API_KEY"] = self.anthropic_api_key
            
            # Execute command
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_directory,
                env=env
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
            
            # Clean up temp file
            os.unlink(prompt_file)
            
            duration = (datetime.now() - start_time).total_seconds()
            
            if process.returncode == 0:
                output = stdout.decode().strip()
                return {
                    "success": True,
                    "output": output,
                    "duration_seconds": duration
                }
            else:
                error_msg = stderr.decode().strip()
                logger.error(f"Claude CLI failed: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "duration_seconds": duration
                }
                
        except asyncio.TimeoutError:
            logger.error("Claude CLI execution timed out")
            return {
                "success": False,
                "error": "Claude Code execution timed out (5 minutes)",
                "duration_seconds": 300
            }
        except Exception as e:
            logger.error(f"Error executing Claude CLI: {e}")
            return {
                "success": False,
                "error": str(e),
                "duration_seconds": (datetime.now() - start_time).total_seconds()
            }
    
    def _is_fixable(self, analysis: str) -> bool:
        """Determine if the issue is automatically fixable based on analysis."""
        # Simple heuristic - in practice, you might want more sophisticated logic
        fixable_indicators = [
            "automatically fixable",
            "simple fix", 
            "syntax error",
            "missing import",
            "linting issue",
            "formatting"
        ]
        
        analysis_lower = analysis.lower()
        return any(indicator in analysis_lower for indicator in fixable_indicators)
    
    def _extract_actions(self, analysis: str) -> list:
        """Extract suggested actions from analysis."""
        # Simple extraction - in practice, you might want to parse structured output
        lines = analysis.split('\n')
        actions = []
        
        for line in lines:
            line = line.strip()
            if line.startswith('- ') or line.startswith('* '):
                actions.append(line[2:])
            elif line.startswith(('1.', '2.', '3.', '4.', '5.')):
                actions.append(line[3:].strip())
        
        return actions[:5]  # Limit to 5 actions
    
    def _mock_analyze_response(self, attempt_id: str, check_name: str) -> Dict[str, Any]:
        """Mock response for analysis in dry-run mode."""
        return {
            "success": True,
            "analysis": f"Mock analysis for {check_name}: This appears to be a {check_name.lower()} failure that could be automatically fixed.",
            "fixable": True,
            "suggested_actions": [
                f"Fix {check_name.lower()} issues",
                "Run tests to verify fix",
                "Update documentation if needed"
            ],
            "attempt_id": attempt_id,
            "duration_seconds": 2.5
        }
    
    def _mock_fix_response(self, attempt_id: str, check_name: str) -> Dict[str, Any]:
        """Mock response for fixes in dry-run mode."""
        return {
            "success": True,
            "fix_description": f"Mock fix applied for {check_name}: Fixed the underlying issue",
            "files_modified": ["src/example.py", "tests/test_example.py"],
            "git_diff": "Mock git diff showing the changes made",
            "attempt_id": attempt_id,
            "duration_seconds": 5.0
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on Claude Code CLI."""
        try:
            if self.dry_run:
                return {"status": "healthy", "mode": "dry_run"}
            
            # Test CLI availability
            process = await asyncio.create_subprocess_exec(
                "claude", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
            
            if process.returncode == 0:
                version = stdout.decode().strip()
                return {
                    "status": "healthy",
                    "version": version,
                    "mode": "production"
                }
            else:
                return {
                    "status": "unhealthy",
                    "error": stderr.decode().strip()
                }
                
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }