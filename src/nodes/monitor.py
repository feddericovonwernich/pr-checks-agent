"""Check Monitor Node for PR Check Agent
Monitors CI/CD check status changes for PRs
"""

from datetime import datetime
from typing import Any

from loguru import logger

from state.schemas import CheckStatus, MonitorState
from tools.github_tool import GitHubTool


async def check_monitor_node(state: MonitorState) -> dict[str, Any]:
    """LangGraph node that monitors CI/CD check status for all active PRs.

    This node:
    1. Gets check status for all active PRs
    2. Compares with previous state
    3. Identifies newly failed checks
    4. Updates PR states with current check information
    """
    repository = state["repository"]
    active_prs = state.get("active_prs", {})

    if not active_prs:
        logger.debug(f"No active PRs to monitor for {repository}")
        return state

    logger.info(f"Monitoring checks for {len(active_prs)} PRs in {repository}")

    github_tool = GitHubTool()
    updated_prs = {}
    newly_failed_checks = []

    # Monitor each PR
    for pr_number, pr_state in active_prs.items():
        try:
            # Get current check status
            result = await github_tool._arun(operation="get_checks", repository=repository, pr_number=pr_number)

            if not result.get("success", False):
                logger.error(f"Failed to get checks for PR #{pr_number}: {result.get('error')}")
                # Keep existing state if API call fails
                updated_prs[pr_number] = pr_state
                continue

            current_checks = result.get("checks", {})
            previous_checks = pr_state.get("checks", {})

            # Identify status changes
            failed_checks = []
            for check_name, check_info in current_checks.items():
                if check_info["status"] == CheckStatus.FAILURE.value:
                    failed_checks.append(check_name)

                    # Check if this is a newly failed check
                    previous_status = previous_checks.get(check_name, {}).get("status")
                    if previous_status != CheckStatus.FAILURE.value:
                        newly_failed_checks.append(
                            {"pr_number": pr_number, "check_name": check_name, "check_info": check_info}
                        )
                        logger.info(f"Newly failed check: {check_name} in PR #{pr_number}")

            # Update PR state
            updated_pr_state = {
                **pr_state,
                "checks": current_checks,
                "failed_checks": failed_checks,
                "last_updated": datetime.now(),
                "workflow_step": "checks_monitored",
            }

            # If there are failed checks, mark for analysis
            if failed_checks:
                updated_pr_state["workflow_step"] = "needs_analysis"

            updated_prs[pr_number] = updated_pr_state

        except Exception as e:
            logger.error(f"Error monitoring checks for PR #{pr_number}: {e}")
            # Keep existing state on error
            updated_prs[pr_number] = pr_state

    # Log summary
    total_failed = sum(len(pr["failed_checks"]) for pr in updated_prs.values())
    logger.info(f"Check monitoring complete: {total_failed} total failed checks, {len(newly_failed_checks)} newly failed")

    return {
        **state,
        "active_prs": updated_prs,
        "newly_failed_checks": newly_failed_checks,
        "last_poll_time": datetime.now(),
        "monitoring_stats": {
            "total_checks_monitored": sum(len(pr["checks"]) for pr in updated_prs.values()),
            "total_failed_checks": total_failed,
            "newly_failed_count": len(newly_failed_checks),
        },
    }


def should_analyze_failures(state: MonitorState) -> str:
    """LangGraph edge function to determine if we need to analyze failures."""
    newly_failed_checks = state.get("newly_failed_checks", [])

    if newly_failed_checks:
        logger.info(f"Found {len(newly_failed_checks)} newly failed checks, proceeding to analysis")
        return "analyze_failures"

    # Check if any PRs need analysis (have failed checks but haven't been analyzed yet)
    active_prs = state.get("active_prs", {})
    needs_analysis = [pr_num for pr_num, pr_state in active_prs.items() if pr_state.get("workflow_step") == "needs_analysis"]

    if needs_analysis:
        logger.info(f"Found {len(needs_analysis)} PRs needing analysis")
        return "analyze_failures"

    return "wait_for_next_poll"


async def prioritize_failures(state: MonitorState) -> dict[str, Any]:
    """Helper node to prioritize failed checks based on configuration."""
    config = state["config"]
    newly_failed_checks = state.get("newly_failed_checks", [])

    if not newly_failed_checks:
        return state

    # Get priority configuration
    check_priorities = config.priorities.get("check_types", {})
    branch_priorities = config.priorities.get("branch_priority", {})

    # Score each failed check
    prioritized_checks = []

    for failure in newly_failed_checks:
        pr_number = failure["pr_number"]
        check_name = failure["check_name"]
        pr_state = state["active_prs"][pr_number]
        pr_info = pr_state.get("pr_info", {})

        # Calculate priority score (lower = higher priority)
        score = 100  # Default score

        # Check type priority
        for check_type, priority in check_priorities.items():
            if check_type.lower() in check_name.lower():
                score = min(score, priority)
                break

        # Branch priority
        branch = pr_info.get("base_branch", "")
        if branch in branch_priorities:
            score += branch_priorities[branch]

        # Add PR number for consistency in sorting
        score += pr_number * 0.001

        prioritized_checks.append({**failure, "priority_score": score})

    # Sort by priority (lower score = higher priority)
    prioritized_checks.sort(key=lambda x: x["priority_score"])

    logger.info(f"Prioritized {len(prioritized_checks)} failed checks")

    # Clear newly_failed_checks after processing to prevent reprocessing
    return {**state, "prioritized_failures": prioritized_checks, "newly_failed_checks": []}
