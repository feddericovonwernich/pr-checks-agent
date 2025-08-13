"""Claude Code Invoker Node for PR Check Agent
Attempts to fix issues using Claude Code CLI
"""

import uuid
from datetime import datetime
from typing import Any

from loguru import logger

from state.schemas import FixAttempt, FixAttemptStatus, MonitorState
from tools.claude_tool import ClaudeCodeTool


async def claude_invoker_node(state: MonitorState) -> dict[str, Any]:
    """LangGraph node that attempts to fix issues using Claude Code.

    This node:
    1. Identifies fixable issues from analysis results
    2. Checks fix attempt limits
    3. Invokes Claude Code to attempt fixes
    4. Updates PR state with fix results
    """
    repository = state["repository"]
    config = state["config"]
    analysis_results = state.get("analysis_results", [])

    # Get fixable issues
    fixable_issues = [result for result in analysis_results if result.get("fixable", False)]

    if not fixable_issues:
        logger.debug(f"No fixable issues for {repository}")
        return state

    logger.info(f"Attempting fixes for {len(fixable_issues)} issues in {repository}")

    claude_tool = ClaudeCodeTool(dry_run=state.get("dry_run", False))
    updated_prs = dict(state.get("active_prs", {}))
    fix_results = []

    # Get fix limits from config
    max_attempts = config.fix_limits.get("max_attempts", 3)

    for issue in fixable_issues:
        pr_number = issue["pr_number"]
        check_name = issue["check_name"]
        analysis = issue["analysis"]

        pr_state = updated_prs[pr_number]
        pr_info = pr_state.get("pr_info", {})

        # Check if we've already exceeded fix attempts for this check
        fix_attempts = pr_state.get("fix_attempts", {})
        check_attempts = fix_attempts.get(check_name, [])

        if len(check_attempts) >= max_attempts:
            logger.warning(f"Max fix attempts ({max_attempts}) reached for {check_name} in PR #{pr_number}, skipping")
            continue

        logger.info(f"Attempting fix {len(check_attempts) + 1}/{max_attempts} for {check_name} in PR #{pr_number}")

        try:
            # Create fix attempt record
            attempt_id = str(uuid.uuid4())
            fix_attempt = FixAttempt(
                id=attempt_id,
                timestamp=datetime.now(),
                check_name=check_name,
                context=analysis["failure_context"],
                prompt=_create_fix_prompt(analysis, pr_info, config),
                status=FixAttemptStatus.IN_PROGRESS,
            )

            # Update PR state to track this attempt
            if check_name not in fix_attempts:
                fix_attempts[check_name] = []
            fix_attempts[check_name].append(fix_attempt.dict())

            updated_prs[pr_number] = {
                **pr_state,
                "fix_attempts": fix_attempts,
                "current_fix_attempt": attempt_id,
                "workflow_step": "fixing",
                "last_updated": datetime.now(),
            }

            # Attempt the fix
            fix_result = await claude_tool._arun(
                operation="fix_issue",
                failure_context=analysis["failure_context"],
                check_name=check_name,
                pr_info=pr_info,
                project_context=config.claude_context,
                # In a real implementation, you'd need to provide the repository path
                repository_path=None,  # This would be the local clone path
            )

            # Update fix attempt with results
            fix_attempt_dict = fix_attempts[check_name][-1]
            fix_attempt_dict.update(
                {
                    "result": fix_result.get("fix_description", ""),
                    "status": FixAttemptStatus.SUCCESS.value
                    if fix_result.get("success", False)
                    else FixAttemptStatus.FAILURE.value,
                    "error_message": fix_result.get("error"),
                    "duration_seconds": fix_result.get("duration_seconds", 0),
                }
            )

            fix_results.append(
                {
                    "pr_number": pr_number,
                    "check_name": check_name,
                    "attempt_id": attempt_id,
                    "success": fix_result.get("success", False),
                    "result": fix_result,
                }
            )

            # Update PR state with final results
            next_step = "fix_successful" if fix_result.get("success", False) else "fix_failed"
            updated_prs[pr_number] = {
                **updated_prs[pr_number],
                "fix_attempts": fix_attempts,
                "current_fix_attempt": None,
                "workflow_step": next_step,
                "last_updated": datetime.now(),
            }

            # Update global metrics
            if fix_result.get("success", False):
                state["total_fixes_successful"] = state.get("total_fixes_successful", 0) + 1
                logger.info(f"Fix successful for {check_name} in PR #{pr_number}")
            else:
                logger.warning(f"Fix failed for {check_name} in PR #{pr_number}")

            state["total_fixes_attempted"] = state.get("total_fixes_attempted", 0) + 1

        except Exception as e:
            logger.error(f"Unexpected error during fix attempt for {check_name}: {e}")

            # Update fix attempt with error
            if fix_attempts.get(check_name):
                fix_attempts[check_name][-1].update(
                    {"status": FixAttemptStatus.FAILURE.value, "error_message": str(e), "duration_seconds": 0}
                )

            # Update PR state
            updated_prs[pr_number] = {
                **updated_prs[pr_number],
                "fix_attempts": fix_attempts,
                "current_fix_attempt": None,
                "workflow_step": "fix_error",
                "error_message": str(e),
                "last_updated": datetime.now(),
            }

    # Summary logging
    successful_fixes = sum(1 for result in fix_results if result["success"])
    logger.info(f"Fix attempts complete: {successful_fixes}/{len(fix_results)} successful")

    return {
        **state,
        "active_prs": updated_prs,
        "fix_results": fix_results,
        "fix_stats": {"total_attempted": len(fix_results), "successful_count": successful_fixes, "timestamp": datetime.now()},
    }


def _create_fix_prompt(analysis: dict[str, Any], pr_info: dict[str, Any], config) -> str:
    """Create a detailed fix prompt based on analysis results."""
    suggested_actions = analysis.get("suggested_actions", [])
    analysis_text = analysis.get("analysis", "")

    prompt = f"""
Based on the following analysis, please fix the issue:

**Analysis**: {analysis_text}

**Suggested Actions**:
"""

    for i, action in enumerate(suggested_actions, 1):
        prompt += f"{i}. {action}\n"

    prompt += f"""
**PR Context**:
- Title: {pr_info.get("title", "")}
- Branch: {pr_info.get("branch", "")}
- Author: {pr_info.get("author", "")}

Please implement the minimal fix needed to resolve this specific issue.
"""

    return prompt


def should_retry_or_escalate(state: MonitorState) -> str:
    """LangGraph edge function to determine next steps after fix attempts."""
    fix_results = state.get("fix_results", [])
    config = state["config"]
    max_attempts = config.fix_limits.get("max_attempts", 3)

    # Check for successful fixes
    successful_fixes = [result for result in fix_results if result["success"]]
    if successful_fixes:
        logger.info(f"{len(successful_fixes)} fixes were successful, monitoring for verification")
        return "verify_fixes"

    # Check for issues that need retrying
    active_prs = state.get("active_prs", {})
    need_retry = []
    need_escalation = []

    for pr_number, pr_state in active_prs.items():
        failed_checks = pr_state.get("failed_checks", [])
        fix_attempts = pr_state.get("fix_attempts", {})

        for check_name in failed_checks:
            attempts = fix_attempts.get(check_name, [])
            if len(attempts) < max_attempts:
                # Still have attempts remaining
                last_attempt = attempts[-1] if attempts else None
                if not last_attempt or last_attempt.get("status") == FixAttemptStatus.FAILURE.value:
                    need_retry.append((pr_number, check_name))
            else:
                # Max attempts reached, needs escalation
                need_escalation.append((pr_number, check_name))

    if need_retry:
        logger.info(f"Found {len(need_retry)} checks that need retry")
        return "retry_fixes"

    if need_escalation:
        logger.info(f"Found {len(need_escalation)} checks that need escalation")
        return "escalate_to_human"

    return "wait_for_next_poll"
