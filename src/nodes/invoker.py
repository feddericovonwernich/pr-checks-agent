"""Claude Code Invoker Node for PR Check Agent
Attempts to fix issues using Claude Code CLI
"""

import uuid
from datetime import datetime
from typing import Any

from loguru import logger

from services.langchain_llm_service import LangChainLLMService
from state.schemas import FixAttempt, FixAttemptStatus, MonitorState
from tools.langchain_claude_tool import LangChainClaudeTool


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
    workflow_step = state.get("workflow_step", "unknown")
    
    # CRITICAL DEBUG: Log the full incoming state
    logger.debug("🔍 INVOKER RECEIVED STATE:")
    logger.debug(f"🔍   Repository: {repository}")
    logger.debug(f"🔍   Workflow step: {workflow_step}")
    logger.debug(f"🔍   Analysis results count: {len(analysis_results)}")
    logger.debug(f"🔍   All state keys: {list(state.keys())}")
    logger.debug(f"🔍   Analysis results type: {type(analysis_results)}")
    logger.debug(f"🔍   Analysis results content: {analysis_results}")

    # Get fixable issues
    fixable_issues = [result for result in analysis_results if result.get("fixable", False)]

    logger.debug(f"🔍 Claude invoker analyzing {len(analysis_results)} analysis results for {repository}")
    logger.debug(f"⚙️ Current workflow step: {workflow_step}")
    logger.debug(f"🔧 Found {len(fixable_issues)} fixable issues")
    
    # Critical debugging: Check if analysis_results are missing for retries
    if len(analysis_results) == 0:
        logger.error(f"🚨 CRITICAL: No analysis_results found in Claude invoker for {repository}")
        logger.error("🚨 This likely means retry attempts are bypassing the analyze_failures node")
        logger.error(f"🚨 Workflow step: {workflow_step}")
        
        # Check if we have failed checks that should be analyzed first
        active_prs = state.get("active_prs", {})
        total_failed_checks = 0
        for pr_number, pr_state in active_prs.items():
            failed_checks = pr_state.get("failed_checks", [])
            total_failed_checks += len(failed_checks)
            if failed_checks:
                logger.error(f"🚨 PR #{pr_number} has {len(failed_checks)} failed checks but no analysis results: {failed_checks}")
        
        logger.error(f"🚨 Total failed checks across all PRs: {total_failed_checks}")
        logger.error("🚨 This indicates the workflow needs to run analysis before attempting fixes")
        
        returned_state = {
            **state,
            "error_message": "No analysis results available for fix attempts - need to analyze failures first",
            "workflow_step": "analysis_required"
        }
        
        logger.debug(f"🚨 Returning analysis_required state with workflow_step: {returned_state['workflow_step']}")
        return returned_state
    
    # Log each analysis result for debugging
    for i, result in enumerate(analysis_results, 1):
        check_name = result.get("check_name", "Unknown")
        pr_number = result.get("pr_number", "Unknown")
        fixable = result.get("fixable", False)
        logger.debug(f"  📋 Result #{i}: PR#{pr_number} - {check_name} - Fixable: {fixable}")
        
        # Log the analysis structure
        analysis_data = result.get("analysis", {})
        if isinstance(analysis_data, dict):
            logger.debug(f"    📝 Analysis keys: {list(analysis_data.keys())}")
            logger.debug(f"    📄 Analysis: {analysis_data.get('analysis', 'No analysis')[:100]}...")
        else:
            logger.debug(f"    ⚠️ Analysis data type: {type(analysis_data)} - {analysis_data}")

    if not fixable_issues:
        logger.debug(f"❌ No fixable issues for {repository}")
        logger.warning(f"⚠️ All {len(analysis_results)} analysis results were marked as unfixable - check LLM analysis")
        return state

    logger.info(f"Attempting fixes for {len(fixable_issues)} issues in {repository}")

    claude_tool = LangChainClaudeTool(dry_run=state.get("dry_run", False))
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

            # Attempt the fix using Claude Code CLI
            fix_result = await claude_tool._arun(
                operation="fix_issue",
                failure_context=analysis["failure_context"],
                check_name=check_name,
                pr_info=pr_info,
                project_context=config.claude_context,
                repository_path=config.repository_path,  # Local repository path for Claude CLI
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
    repository = state.get("repository", "unknown")
    workflow_step = state.get("workflow_step", "unknown")
    error_message = state.get("error_message", "")

    logger.debug(f"🔄 Evaluating retry/escalation decision for {repository}")
    logger.debug(f"📊 Fix results received: {len(fix_results)} results")
    logger.debug(f"⚙️ Max attempts configured: {max_attempts}")
    logger.debug(f"⚙️ Current workflow step: {workflow_step}")
    
    # Handle case where invoker detected missing analysis results
    if workflow_step == "analysis_required":
        logger.warning(f"🚨 Invoker requires analysis before attempting fixes: {error_message}")
        logger.info(f"🔄 Routing back to analysis phase for {repository}")
        logger.debug(f"🔄 should_retry_or_escalate state keys: {list(state.keys())}")
        logger.debug(f"🔄 should_retry_or_escalate workflow_step: {state.get('workflow_step')}")
        logger.debug(f"🔄 should_retry_or_escalate error_message: {state.get('error_message')}")
        return "retry_fixes"  # This will now route to prioritize_failures → analyze_failures

    # Check for successful fixes
    successful_fixes = [result for result in fix_results if result["success"]]
    if successful_fixes:
        logger.info(f"✅ {len(successful_fixes)} fixes were successful, monitoring for verification")
        logger.debug(f"🎯 Successful fixes: {[f['check_name'] for f in successful_fixes]}")
        return "verify_fixes"

    # Check for issues that need retrying
    active_prs = state.get("active_prs", {})
    need_retry = []
    need_escalation = []

    logger.debug(f"📝 Analyzing {len(active_prs)} active PRs for retry/escalation needs")

    for pr_number, pr_state in active_prs.items():
        failed_checks = pr_state.get("failed_checks", [])
        fix_attempts = pr_state.get("fix_attempts", {})
        workflow_step = pr_state.get("workflow_step", "unknown")
        
        logger.debug(f"🔍 PR #{pr_number}: {len(failed_checks)} failed checks, workflow_step: {workflow_step}")
        logger.debug(f"📋 Failed checks: {failed_checks}")
        logger.debug(f"🔧 Fix attempts keys: {list(fix_attempts.keys())}")

        for check_name in failed_checks:
            attempts = fix_attempts.get(check_name, [])
            logger.debug(f"  📌 Check '{check_name}': {len(attempts)}/{max_attempts} attempts")
            
            if len(attempts) < max_attempts:
                # Still have attempts remaining
                last_attempt = attempts[-1] if attempts else None
                last_status = last_attempt.get("status") if last_attempt else "no_attempts"
                
                logger.debug(f"    🔄 Can retry - Last attempt status: {last_status}")
                
                if not last_attempt or last_attempt.get("status") == FixAttemptStatus.FAILURE.value:
                    need_retry.append((pr_number, check_name))
                    logger.debug(f"    + Added to retry list: PR #{pr_number} - {check_name}")
            else:
                # Max attempts reached, needs escalation
                logger.debug("    🚨 Max attempts reached - needs escalation")
                need_escalation.append((pr_number, check_name))
                logger.debug(f"    + Added to escalation list: PR #{pr_number} - {check_name}")

    logger.debug("📊 Decision analysis results:")
    logger.debug(f"  🔄 Need retry: {len(need_retry)} checks")
    logger.debug(f"  🚨 Need escalation: {len(need_escalation)} checks")

    if need_retry:
        logger.info(f"🔄 Found {len(need_retry)} checks that need retry")
        logger.debug(f"🔄 Retry list: {need_retry}")
        return "retry_fixes"

    if need_escalation:
        logger.info(f"🚨 Found {len(need_escalation)} checks that need escalation")
        logger.debug(f"🚨 Escalation list: {need_escalation}")
        return "escalate_to_human"

    logger.debug("⏳ No retries or escalations needed - waiting for next poll")
    return "wait_for_next_poll"


async def should_escalate_with_llm(state: MonitorState) -> dict[str, Any]:
    """Use LLM to make sophisticated escalation decisions."""
    config = state["config"]
    fix_results = state.get("fix_results", [])
    active_prs = state.get("active_prs", {})

    # Initialize LLM service
    llm_config = {
        "provider": config.llm.provider,
        "model": config.llm.model,
        "api_key": config.llm.effective_api_key,
        "base_url": config.llm.base_url,
    }
    llm_service = LangChainLLMService(llm_config)

    escalation_decisions = []

    for pr_number, pr_state in active_prs.items():
        failed_checks = pr_state.get("failed_checks", [])
        fix_attempts = pr_state.get("fix_attempts", {})

        for check_name in failed_checks:
            attempts = fix_attempts.get(check_name, [])
            max_attempts = config.fix_limits.get("max_attempts", 3)

            if len(attempts) >= max_attempts:
                # Get failure analysis info
                analysis_key = f"analysis_{check_name}"
                failure_info = pr_state.get(analysis_key, {})

                # Use LLM to decide if escalation is needed
                escalation_result = await llm_service.should_escalate(
                    failure_info=failure_info,
                    fix_attempts=len(attempts),
                    max_attempts=max_attempts,
                    project_context=config.claude_context,
                )

                escalation_decisions.append(
                    {"pr_number": pr_number, "check_name": check_name, "escalation_decision": escalation_result}
                )

    return {**state, "escalation_decisions": escalation_decisions}
