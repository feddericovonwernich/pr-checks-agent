"""Failure Analyzer Node for PR Check Agent
Analyzes failed checks to determine if they can be automatically fixed
"""

import traceback
from datetime import datetime
from typing import Any

from loguru import logger

from services.langchain_llm_service import LangChainLLMService
from state.schemas import MonitorState
from tools.github_tool import GitHubTool
from utils.config import load_environment_config


async def failure_analyzer_node(state: MonitorState) -> dict[str, Any]:  # noqa: PLR0915
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

    # Initialize LangChain LLM service for decision-making
    env_config = load_environment_config()
    llm_config = env_config.get("llm", {})
    llm_service = LangChainLLMService(llm_config)

    updated_prs = dict(state.get("active_prs", {}))
    analysis_results = []

    # Analyze each failed check
    for failure in prioritized_failures:
        pr_number = failure["pr_number"]
        check_name = failure["check_name"]
        check_info = failure["check_info"]

        logger.info(f"Analyzing failure: {check_name} in PR #{pr_number}")
        logger.debug(f"🔍 Starting analysis for check '{check_name}' in repository '{repository}' PR #{pr_number}")
        logger.debug(f"📊 Check info received: {check_info}")

        try:
            # Get detailed failure logs if available
            logger.debug(f"📝 Fetching failure context for {check_name}...")
            failure_context = await _get_failure_context(github_tool, repository, check_info, check_name)
            logger.debug(f"📄 Failure context retrieved ({len(failure_context)} characters):")
            logger.debug(f"{'='*60}\n{failure_context}\n{'='*60}")

            # Get PR information for context
            pr_state = updated_prs[pr_number]
            pr_info = pr_state.get("pr_info", {})
            logger.debug(f"🔗 PR info for context: {pr_info}")
            logger.debug(f"⚙️ Project context: {config.claude_context}")

            # Use LLM service to analyze the failure
            logger.debug("🤖 Sending failure to LLM for analysis...")
            logger.debug("📤 LLM Analysis Input:")
            logger.debug(f"  - Check Name: {check_name}")
            logger.debug(f"  - Failure Context Length: {len(failure_context)} chars")
            logger.debug(f"  - PR Title: {pr_info.get('title', 'N/A')}")
            logger.debug(f"  - PR Author: {pr_info.get('author', 'N/A')}")
            
            analysis_result = await llm_service.analyze_failure(
                failure_context=failure_context,
                check_name=check_name,
                pr_info=pr_info,
                project_context=config.claude_context,
            )
            
            logger.debug(f"📥 LLM Analysis Result: {analysis_result}")

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
                logger.debug(f"✅ Analysis successful for {check_name}:")
                logger.debug(f"  🔧 Fixable: {analysis_data['fixable']}")
                logger.debug(f"  📋 Analysis: {analysis_data['analysis'][:200]}{'...' if len(analysis_data['analysis']) > 200 else ''}")
                logger.debug(f"  🎯 Suggested Actions ({len(analysis_data['suggested_actions'])}):")
                for i, action in enumerate(analysis_data["suggested_actions"], 1):
                    logger.debug(f"    {i}. {action}")
                logger.debug(f"  🆔 Attempt ID: {analysis_data['attempt_id']}")
                logger.debug(f"  📊 Confidence: {analysis_result.get('confidence', 'N/A')}")
                if analysis_result.get("side_effects"):
                    logger.debug(f"  ⚠️ Side Effects: {analysis_result.get('side_effects')}")

            else:
                error_msg = analysis_result.get("error", "Unknown analysis error")
                logger.error(f"Analysis failed for {check_name}: {error_msg}")
                logger.debug(f"❌ LLM Analysis failed for {check_name}:")
                logger.debug(f"  🚫 Error: {error_msg}")
                logger.debug(f"  📤 Input sent to LLM: {len(failure_context)} chars of failure context")
                logger.debug(f"  📥 Full LLM response: {analysis_result}")

                # Update PR state with error
                updated_prs[pr_number] = {
                    **pr_state,
                    "workflow_step": "analysis_failed",
                    "error_message": error_msg,
                    "last_updated": datetime.now(),
                }

        except Exception as e:
            logger.error(f"Unexpected error analyzing {check_name} in PR #{pr_number}: {e}")
            logger.debug(f"💥 Exception during analysis for {check_name}:")
            logger.debug(f"  🚨 Exception type: {type(e).__name__}")
            logger.debug(f"  📝 Exception message: {e!s}")
            logger.debug(f"  📊 Check info that caused error: {check_info}")
            logger.debug(f"  📋 Full traceback:\n{traceback.format_exc()}")

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

    # Make routing decision inside analyzer to preserve state
    fixable_issues = [result for result in analysis_results if result.get("fixable", False)]
    unfixable_issues = [result for result in analysis_results if not result.get("fixable", False)]
    
    if fixable_issues:
        next_step = "attempt_fixes"
        logger.info(f"✅ Found {len(fixable_issues)} fixable issues, proceeding to fix attempts")
    elif unfixable_issues:
        next_step = "escalate_to_human"
        logger.info(f"🚫 Found {len(unfixable_issues)} unfixable issues, proceeding to escalation")
    else:
        next_step = "wait_for_next_poll"
        logger.info("⏳ No issues found, waiting for next poll")

    # CRITICAL DEBUG: Log what we're returning from analyzer
    returned_state = {
        **state,
        "active_prs": updated_prs,
        "analysis_results": analysis_results,
        "analysis_stats": {
            "total_analyzed": len(analysis_results),
            "fixable_count": fixable_count,
            "timestamp": datetime.now(),
        },
        "workflow_step": "analyzed",
        "next_step": next_step  # Store routing decision in state!
    }
    
    logger.debug(f"🔄 Analyzer returning state with {len(analysis_results)} analysis_results")
    logger.debug(f"🔄 Returned analysis_results: {analysis_results}")
    logger.debug(f"🔄 Returned state keys: {list(returned_state.keys())}")
    logger.debug(f"🔄 Setting workflow_step to 'analyzed', next_step to '{next_step}'")

    return returned_state


async def _get_failure_context(github_tool: GitHubTool, repository: str, check_info: dict[str, Any], check_name: str) -> str:  # noqa: PLR0915, PLR0912
    """Get detailed failure context from GitHub."""
    logger.debug(f"🔍 Building failure context for {check_name}")
    logger.debug(f"📦 Repository: {repository}")
    logger.debug(f"🔧 Available check_info keys: {list(check_info.keys())}")
    
    context_parts = []

    # Basic check information
    status = check_info.get("status", "unknown")
    conclusion = check_info.get("conclusion", "unknown")
    logger.debug(f"📊 Basic info - Status: {status}, Conclusion: {conclusion}")
    
    context_parts.append(f"Check: {check_name}")
    context_parts.append(f"Status: {status}")
    context_parts.append(f"Conclusion: {conclusion}")

    if check_info.get("started_at"):
        started_at = check_info["started_at"]
        logger.debug(f"⏰ Started at: {started_at}")
        context_parts.append(f"Started: {started_at}")

    if check_info.get("completed_at"):
        completed_at = check_info["completed_at"]
        logger.debug(f"⏰ Completed at: {completed_at}")
        context_parts.append(f"Completed: {completed_at}")

    # Try to get detailed logs from GitHub
    details_url = check_info.get("details_url", "")
    logger.debug(f"🔗 Details URL: {details_url}")
    
    # Handle different URL patterns
    if "check-runs" in details_url:
        try:
            # Extract check run ID from URL
            check_run_id = details_url.split("/")[-1]
            logger.debug(f"🆔 Extracted check run ID: {check_run_id}")
            
            if check_run_id.isdigit():
                logger.debug(f"📞 Fetching detailed logs for check run ID: {check_run_id}")
                logs_result = await github_tool._arun(
                    operation="get_check_logs", repository=repository, check_run_id=int(check_run_id)
                )
                
                logger.debug(f"📥 Check logs fetch result: {logs_result}")

                if logs_result.get("success", False):
                    logs = logs_result.get("logs", [])
                    logger.debug(f"📝 Retrieved {len(logs)} check log entries")
                    if logs:
                        context_parts.append("\nFailure Details:")
                        context_parts.extend(logs)
                        logger.debug(f"✅ Added detailed check logs to context ({len(logs)} entries)")
                    else:
                        logger.debug("⚠️ No check logs found in successful response")
                else:
                    logger.debug(f"❌ Failed to fetch check logs: {logs_result.get('error', 'Unknown error')}")
            else:
                logger.debug(f"⚠️ Check run ID is not numeric: {check_run_id}")
        except Exception as e:
            logger.debug(f"💥 Exception getting check run logs for {check_name}: {e}")
            logger.debug(f"📋 Check logs fetch traceback:\n{traceback.format_exc()}")
    
    elif "actions/runs" in details_url and "/job/" in details_url:
        try:
            # Extract job ID from GitHub Actions job URL
            # URL format: https://github.com/owner/repo/actions/runs/16926578302/job/47963305999
            url_parts = details_url.split("/")
            job_id = url_parts[-1]  # Last part is job ID
            logger.debug(f"🆔 Extracted GitHub Actions job ID: {job_id}")
            
            if job_id.isdigit():
                logger.debug(f"📞 Fetching GitHub Actions job logs for job ID: {job_id}")
                logs_result = await github_tool._arun(
                    operation="get_job_logs", repository=repository, job_id=int(job_id)
                )
                
                logger.debug(f"📥 Job logs fetch result: {logs_result}")

                if logs_result.get("success", False):
                    logs = logs_result.get("logs", [])
                    job_name = logs_result.get("job_name", "")
                    logger.debug(f"📝 Retrieved {len(logs)} GitHub Actions job log entries for '{job_name}'")
                    if logs:
                        context_parts.append(f"\nGitHub Actions Job Failure Details ({job_name}):")
                        context_parts.extend(logs)
                        logger.debug(f"✅ Added detailed GitHub Actions job logs to context ({len(logs)} entries)")
                        
                        # Add job metadata
                        if logs_result.get("started_at"):
                            context_parts.append(f"Job Started: {logs_result['started_at']}")
                        if logs_result.get("completed_at"):
                            context_parts.append(f"Job Completed: {logs_result['completed_at']}")
                        if logs_result.get("full_logs_length"):
                            context_parts.append(f"Full log length: {logs_result['full_logs_length']} lines")
                    else:
                        logger.debug("⚠️ No GitHub Actions job logs found in successful response")
                else:
                    logger.debug(f"❌ Failed to fetch GitHub Actions job logs: {logs_result.get('error', 'Unknown error')}")
                    # Still add available job info even if logs failed
                    if logs_result.get("job_name"):
                        context_parts.append(f"\nJob: {logs_result['job_name']} (logs unavailable)")
            else:
                logger.debug(f"⚠️ GitHub Actions job ID is not numeric: {job_id}")
        except Exception as e:
            logger.debug(f"💥 Exception getting GitHub Actions job logs for {check_name}: {e}")
            logger.debug(f"📋 Job logs fetch traceback:\n{traceback.format_exc()}")
    
    else:
        logger.debug(f"⚠️ Unrecognized details URL pattern: {details_url}")

    # Add any failure logs from the check info
    if check_info.get("failure_logs"):
        failure_logs = check_info["failure_logs"]
        logger.debug(f"📋 Found failure_logs in check_info ({len(failure_logs)} chars)")
        context_parts.append("\nFailure Logs:")
        context_parts.append(failure_logs)
    else:
        logger.debug("⚠️ No failure_logs found in check_info")

    if check_info.get("error_message"):
        error_message = check_info["error_message"]
        logger.debug(f"🚨 Found error_message in check_info: {error_message[:100]}{'...' if len(error_message) > 100 else ''}")
        context_parts.append(f"\nError Message: {error_message}")
    else:
        logger.debug("⚠️ No error_message found in check_info")

    final_context = "\n".join(context_parts)
    logger.debug(f"✅ Final failure context built ({len(final_context)} chars, {len(context_parts)} parts)")
    
    return final_context


def should_attempt_fixes(state: MonitorState) -> str:
    """LangGraph edge function that reads routing decision from analyzer state."""
    next_step = state.get("next_step", "wait_for_next_poll")
    analysis_results = state.get("analysis_results", [])
    repository = state.get("repository", "unknown")
    
    logger.debug("🔀 Edge function reading routing decision from analyzer")
    logger.debug(f"🔀 next_step from state: {next_step}")
    logger.debug(f"🔀 analysis_results count: {len(analysis_results)}")
    logger.debug(f"🔀 Available state keys: {list(state.keys())}")
    
    # Log that we're preserving the analyzer's decision
    logger.info(f"🔀 Following analyzer decision: {next_step} (with {len(analysis_results)} analysis_results)")
    
    return next_step
