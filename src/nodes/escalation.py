"""
Human Escalation Node for PR Check Agent
Handles escalation to humans when automatic fixes fail
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List

from loguru import logger

from state.schemas import MonitorState, EscalationRecord, EscalationStatus
from tools.telegram_tool import TelegramTool


async def escalation_node(state: MonitorState) -> Dict[str, Any]:
    """
    LangGraph node that escalates issues to humans via Telegram.
    
    This node:
    1. Identifies issues that need escalation
    2. Checks escalation cooldowns
    3. Sends Telegram notifications
    4. Updates PR state with escalation records
    """
    
    repository = state["repository"]
    config = state["config"]
    
    # Find issues that need escalation
    escalation_candidates = _identify_escalation_candidates(state)
    
    if not escalation_candidates:
        logger.debug(f"No issues need escalation for {repository}")
        return state
    
    logger.info(f"Escalating {len(escalation_candidates)} issues in {repository}")
    
    telegram_tool = TelegramTool(dry_run=state.get("dry_run", False))
    updated_prs = dict(state.get("active_prs", {}))
    escalation_results = []
    
    # Get escalation settings
    cooldown_hours = config.fix_limits.get("escalation_cooldown_hours", 24)
    mentions = config.notifications.get("escalation_mentions", [])
    
    for candidate in escalation_candidates:
        pr_number = candidate["pr_number"]
        check_name = candidate["check_name"]
        reason = candidate["reason"]
        
        pr_state = updated_prs[pr_number]
        pr_info = pr_state.get("pr_info", {})
        
        # Check if we're still in cooldown for this check
        if _is_in_cooldown(pr_state, check_name, cooldown_hours):
            logger.debug(f"Still in cooldown for {check_name} in PR #{pr_number}, skipping")
            continue
        
        try:
            # Get fix attempt history for context
            fix_attempts = pr_state.get("fix_attempts", {}).get(check_name, [])
            
            # Create escalation record
            escalation_id = str(uuid.uuid4())
            escalation = EscalationRecord(
                id=escalation_id,
                timestamp=datetime.now(),
                check_name=check_name,
                reason=reason,
                status=EscalationStatus.PENDING
            )
            
            # Send Telegram notification
            notification_result = await telegram_tool._arun(
                operation="send_escalation",
                repository=repository,
                pr_number=pr_number,
                check_name=check_name,
                failure_context=candidate.get("failure_context", ""),
                fix_attempts=[attempt for attempt in fix_attempts],
                escalation_reason=reason,
                mentions=mentions
            )
            
            if notification_result.get("success", False):
                # Update escalation record with message info
                escalation.telegram_message_id = notification_result.get("message_id")
                escalation.status = EscalationStatus.NOTIFIED
                
                # Update PR state
                pr_escalations = pr_state.get("escalations", [])
                pr_escalations.append(escalation.dict())
                
                updated_prs[pr_number] = {
                    **pr_state,
                    "escalations": pr_escalations,
                    "escalation_status": EscalationStatus.NOTIFIED.value,
                    "workflow_step": "escalated",
                    "last_updated": datetime.now()
                }
                
                escalation_results.append({
                    "pr_number": pr_number,
                    "check_name": check_name,
                    "escalation_id": escalation_id,
                    "success": True,
                    "message_id": notification_result.get("message_id")
                })
                
                logger.info(f"Escalated {check_name} in PR #{pr_number} to humans")
                
                # Update global escalation count
                state["total_escalations"] = state.get("total_escalations", 0) + 1
            
            else:
                error_msg = notification_result.get("error", "Unknown Telegram error")
                logger.error(f"Failed to send escalation for {check_name}: {error_msg}")
                
                # Update escalation record with error
                escalation.status = EscalationStatus.NONE
                escalation.error_message = error_msg
                
                escalation_results.append({
                    "pr_number": pr_number,
                    "check_name": check_name,
                    "escalation_id": escalation_id,
                    "success": False,
                    "error": error_msg
                })
        
        except Exception as e:
            logger.error(f"Unexpected error during escalation for {check_name}: {e}")
            escalation_results.append({
                "pr_number": pr_number,
                "check_name": check_name,
                "success": False,
                "error": str(e)
            })
    
    # Summary logging
    successful_escalations = sum(1 for result in escalation_results if result["success"])
    logger.info(
        f"Escalation complete: {successful_escalations}/{len(escalation_results)} successful"
    )
    
    return {
        **state,
        "active_prs": updated_prs,
        "escalation_results": escalation_results,
        "escalation_stats": {
            "total_escalations": len(escalation_results),
            "successful_count": successful_escalations,
            "timestamp": datetime.now()
        }
    }


def _identify_escalation_candidates(state: MonitorState) -> List[Dict[str, Any]]:
    """Identify issues that need escalation to humans."""
    
    active_prs = state.get("active_prs", {})
    config = state["config"]
    max_attempts = config.fix_limits.get("max_attempts", 3)
    
    candidates = []
    
    for pr_number, pr_state in active_prs.items():
        failed_checks = pr_state.get("failed_checks", [])
        fix_attempts = pr_state.get("fix_attempts", {})
        
        for check_name in failed_checks:
            attempts = fix_attempts.get(check_name, [])
            
            # Check if max attempts reached
            if len(attempts) >= max_attempts:
                # Verify all attempts failed
                all_failed = all(
                    attempt.get("status") == "failure" 
                    for attempt in attempts
                )
                
                if all_failed:
                    # Get failure context from latest analysis
                    analysis_key = f"analysis_{check_name}"
                    analysis = pr_state.get(analysis_key, {})
                    failure_context = analysis.get("failure_context", "No context available")
                    
                    candidates.append({
                        "pr_number": pr_number,
                        "check_name": check_name,
                        "reason": f"Maximum fix attempts ({max_attempts}) exhausted",
                        "failure_context": failure_context,
                        "fix_attempts": attempts
                    })
            
            # Also check for issues marked as unfixable
            analysis_key = f"analysis_{check_name}"
            analysis = pr_state.get(analysis_key, {})
            if not analysis.get("fixable", True) and len(attempts) == 0:
                candidates.append({
                    "pr_number": pr_number,
                    "check_name": check_name,
                    "reason": "Issue determined to be not automatically fixable",
                    "failure_context": analysis.get("failure_context", ""),
                    "fix_attempts": []
                })
    
    return candidates


def _is_in_cooldown(pr_state: Dict[str, Any], check_name: str, cooldown_hours: int) -> bool:
    """Check if a check is still in escalation cooldown."""
    
    escalations = pr_state.get("escalations", [])
    
    # Find the most recent escalation for this check
    check_escalations = [
        escalation for escalation in escalations
        if escalation.get("check_name") == check_name
    ]
    
    if not check_escalations:
        return False
    
    # Get the most recent escalation
    latest_escalation = max(
        check_escalations, 
        key=lambda x: x.get("timestamp", datetime.min)
    )
    
    # Parse timestamp and check if cooldown period has passed
    escalation_time = latest_escalation.get("timestamp")
    if isinstance(escalation_time, str):
        escalation_time = datetime.fromisoformat(escalation_time)
    elif not isinstance(escalation_time, datetime):
        return False
    
    cooldown_end = escalation_time + timedelta(hours=cooldown_hours)
    return datetime.now() < cooldown_end


async def handle_escalation_response(
    state: MonitorState, 
    escalation_id: str, 
    response_type: str, 
    user_id: str,
    notes: str = ""
) -> Dict[str, Any]:
    """
    Handle human response to escalation (acknowledgment, resolution, etc.).
    
    This would typically be called from a webhook or callback handler.
    """
    
    updated_prs = dict(state.get("active_prs", {}))
    
    # Find the escalation record
    escalation_found = False
    
    for pr_number, pr_state in updated_prs.items():
        escalations = pr_state.get("escalations", [])
        
        for i, escalation in enumerate(escalations):
            if escalation.get("id") == escalation_id:
                # Update escalation record
                escalations[i].update({
                    "status": response_type,
                    "acknowledged_by": user_id,
                    "acknowledged_at": datetime.now(),
                    "resolution_notes": notes
                })
                
                # Update PR state
                updated_prs[pr_number] = {
                    **pr_state,
                    "escalations": escalations,
                    "escalation_status": response_type,
                    "workflow_step": "human_acknowledged",
                    "last_updated": datetime.now()
                }
                
                escalation_found = True
                logger.info(f"Escalation {escalation_id} {response_type} by {user_id}")
                break
        
        if escalation_found:
            break
    
    if not escalation_found:
        logger.warning(f"Escalation {escalation_id} not found")
        return state
    
    return {
        **state,
        "active_prs": updated_prs
    }


def should_continue_after_escalation(state: MonitorState) -> str:
    """
    LangGraph edge function to determine next steps after escalation.
    """
    
    escalation_results = state.get("escalation_results", [])
    
    # Check if any escalations were successful
    successful_escalations = [result for result in escalation_results if result["success"]]
    
    if successful_escalations:
        logger.info(f"Successfully escalated {len(successful_escalations)} issues")
        return "wait_for_human_response"
    
    # If no escalations were successful, continue monitoring
    return "wait_for_next_poll"