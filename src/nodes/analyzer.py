"""Failure Analyzer Node for PR Check Agent
Analyzes failed checks to determine if they can be automatically fixed
"""

from datetime import datetime
from typing import Any

from loguru import logger

from services.llm_provider import LLMService
from state.schemas import MonitorState
from tools.github_tool import GitHubTool


async def failure_analyzer_node(state: MonitorState) -> dict[str, Any]:
    """LangGraph node that analyzes failed checks to determine fixability.

    This node:
    1. Gets detailed failure information from GitHub
    2. Uses Claude Code to analyze the failure
    3. Determines if the issue is automatically fixable
    4. Updates PR state with analysis results
    """
    repository = state["repository"]
    config = state["config"]
    prioritized_failures = state.get("prioritized_failures", [])

    if not prioritized_failures:
        logger.debug(f"No failures to analyze for {repository}")
        return state

    logger.info(f"Analyzing {len(prioritized_failures)} failed checks in {repository}")

    github_tool = GitHubTool()

    # Initialize LLM service for decision-making
    llm_config = {
        "provider": config.llm.provider,
        "model": config.llm.model,
        "api_key": config.llm.effective_api_key,
        "base_url": config.llm.base_url,
    }
    llm_service = LLMService(llm_config)

    updated_prs = dict(state.get("active_prs", {}))
    analysis_results = []

    # Analyze each failed check
    for failure in prioritized_failures:
        pr_number = failure["pr_number"]
        check_name = failure["check_name"]
        check_info = failure["check_info"]

        logger.info(f"Analyzing failure: {check_name} in PR #{pr_number}")

        try:
            # Get detailed failure logs if available
            failure_context = await _get_failure_context(github_tool, repository, check_info, check_name)

            # Get PR information for context
            pr_state = updated_prs[pr_number]
            pr_info = pr_state.get("pr_info", {})

            # Use LLM service to analyze the failure
            analysis_result = await llm_service.analyze_failure(
                failure_context=failure_context,
                check_name=check_name,
                pr_info=pr_info,
                project_context=config.claude_context,
            )

            if analysis_result.get("success", False):
                # Store analysis results
                analysis_data = {
                    "timestamp": datetime.now(),
                    "check_name": check_name,
                    "analysis": analysis_result.get("analysis", ""),
                    "fixable": analysis_result.get("fixable", False),
                    "suggested_actions": analysis_result.get("suggested_actions", []),
                    "attempt_id": analysis_result.get("attempt_id"),
                    "failure_context": failure_context,
                }

                analysis_results.append(
                    {
                        "pr_number": pr_number,
                        "check_name": check_name,
                        "analysis": analysis_data,
                        "fixable": analysis_data["fixable"],
                    }
                )

                # Update PR state
                updated_prs[pr_number] = {
                    **pr_state,
                    "workflow_step": "analyzed",
                    "last_updated": datetime.now(),
                    f"analysis_{check_name}": analysis_data,
                }

                logger.info(f"Analysis complete for {check_name}: {'fixable' if analysis_data['fixable'] else 'not fixable'}")

            else:
                error_msg = analysis_result.get("error", "Unknown analysis error")
                logger.error(f"Analysis failed for {check_name}: {error_msg}")

                # Update PR state with error
                updated_prs[pr_number] = {
                    **pr_state,
                    "workflow_step": "analysis_failed",
                    "error_message": error_msg,
                    "last_updated": datetime.now(),
                }

        except Exception as e:
            logger.error(f"Unexpected error analyzing {check_name} in PR #{pr_number}: {e}")

            # Update PR state with error
            if pr_number in updated_prs:
                updated_prs[pr_number] = {
                    **updated_prs[pr_number],
                    "workflow_step": "analysis_error",
                    "error_message": str(e),
                    "last_updated": datetime.now(),
                }

    # Summary logging
    fixable_count = sum(1 for result in analysis_results if result["fixable"])
    logger.info(f"Analysis complete: {fixable_count}/{len(analysis_results)} issues are fixable")

    return {
        **state,
        "active_prs": updated_prs,
        "analysis_results": analysis_results,
        "analysis_stats": {
            "total_analyzed": len(analysis_results),
            "fixable_count": fixable_count,
            "timestamp": datetime.now(),
        },
    }


async def _get_failure_context(github_tool: GitHubTool, repository: str, check_info: dict[str, Any], check_name: str) -> str:
    """Get detailed failure context from GitHub."""
    context_parts = []

    # Basic check information
    context_parts.append(f"Check: {check_name}")
    context_parts.append(f"Status: {check_info.get('status', 'unknown')}")
    context_parts.append(f"Conclusion: {check_info.get('conclusion', 'unknown')}")

    if check_info.get("started_at"):
        context_parts.append(f"Started: {check_info['started_at']}")

    if check_info.get("completed_at"):
        context_parts.append(f"Completed: {check_info['completed_at']}")

    # Try to get detailed logs if check run ID is available
    details_url = check_info.get("details_url", "")
    if "check-runs" in details_url:
        try:
            # Extract check run ID from URL
            check_run_id = details_url.split("/")[-1]
            if check_run_id.isdigit():
                logs_result = await github_tool._arun(
                    operation="get_check_logs", repository=repository, check_run_id=int(check_run_id)
                )

                if logs_result.get("success", False):
                    logs = logs_result.get("logs", [])
                    if logs:
                        context_parts.append("\nFailure Details:")
                        context_parts.extend(logs)
        except Exception as e:
            logger.debug(f"Could not get detailed logs for {check_name}: {e}")

    # Add any failure logs from the check info
    if check_info.get("failure_logs"):
        context_parts.append("\nFailure Logs:")
        context_parts.append(check_info["failure_logs"])

    if check_info.get("error_message"):
        context_parts.append(f"\nError Message: {check_info['error_message']}")

    return "\n".join(context_parts)


def should_attempt_fixes(state: MonitorState) -> str:
    """LangGraph edge function to determine if we should attempt fixes."""
    analysis_results = state.get("analysis_results", [])

    # Check if any issues are fixable
    fixable_issues = [result for result in analysis_results if result.get("fixable", False)]

    if fixable_issues:
        logger.info(f"Found {len(fixable_issues)} fixable issues, proceeding to fix attempts")
        return "attempt_fixes"

    # Check if any issues need escalation
    unfixable_issues = [result for result in analysis_results if not result.get("fixable", False)]

    if unfixable_issues:
        logger.info(f"Found {len(unfixable_issues)} unfixable issues, proceeding to escalation")
        return "escalate_to_human"

    return "wait_for_next_poll"
