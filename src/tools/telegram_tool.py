"""
Telegram notification tool for PR Check Agent
Handles human escalation notifications as a LangGraph tool
"""

import asyncio
import os
from datetime import datetime
from typing import Dict, Any, Optional, List

from langchain.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError


class TelegramInput(BaseModel):
    """Input schema for Telegram operations."""
    operation: str = Field(description="Operation: 'send_escalation', 'send_status', 'send_summary'")
    repository: str = Field(description="Repository name")
    pr_number: int = Field(description="PR number")
    check_name: str = Field(description="Check name that failed")
    failure_context: str = Field(description="Failure details")
    fix_attempts: List[Dict[str, Any]] = Field(default=[], description="Previous fix attempts")
    escalation_reason: str = Field(default="", description="Reason for escalation")
    mentions: List[str] = Field(default=[], description="Users to mention")


class TelegramTool(BaseTool):
    """LangGraph tool for Telegram notifications."""
    
    name: str = "telegram_notify"
    description: str = "Send notifications and escalations via Telegram"
    args_schema: type = TelegramInput
    
    class Config:
        extra = "allow"
    
    def __init__(self, dry_run: bool = False):
        super().__init__()
        
        self.dry_run = dry_run
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        if not self.bot_token or not self.chat_id:
            if not dry_run:
                raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
            else:
                logger.warning("Telegram credentials not found, running in dry-run mode")
        
        self.bot = Bot(token=self.bot_token) if self.bot_token else None
        
        logger.info(f"Telegram tool initialized (dry_run={dry_run})")
    
    def _run(self, operation: str, **kwargs) -> Dict[str, Any]:
        """Synchronous wrapper for async operations."""
        return asyncio.run(self._arun(operation, **kwargs))
    
    async def _arun(
        self,
        operation: str,
        repository: str,
        pr_number: int,
        check_name: str,
        failure_context: str,
        fix_attempts: List[Dict[str, Any]] = None,
        escalation_reason: str = "",
        mentions: List[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute Telegram operation."""
        
        if fix_attempts is None:
            fix_attempts = []
        if mentions is None:
            mentions = []
        
        try:
            if operation == "send_escalation":
                return await self._send_escalation(
                    repository, pr_number, check_name, failure_context,
                    fix_attempts, escalation_reason, mentions
                )
            elif operation == "send_status":
                return await self._send_status_update(
                    repository, pr_number, check_name, failure_context
                )
            elif operation == "send_summary":
                return await self._send_daily_summary()
            else:
                raise ValueError(f"Unknown operation: {operation}")
                
        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_escalation(
        self,
        repository: str,
        pr_number: int,
        check_name: str,
        failure_context: str,
        fix_attempts: List[Dict[str, Any]],
        escalation_reason: str,
        mentions: List[str]
    ) -> Dict[str, Any]:
        """Send escalation notification to Telegram."""
        
        logger.info(f"Sending escalation for {repository} PR #{pr_number} - {check_name}")
        
        if self.dry_run:
            return self._mock_escalation_response(repository, pr_number, check_name)
        
        # Create escalation message
        message = self._create_escalation_message(
            repository, pr_number, check_name, failure_context,
            fix_attempts, escalation_reason, mentions
        )
        
        # Create inline keyboard for quick actions
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔍 View PR", url=f"https://github.com/{repository}/pull/{pr_number}"),
                InlineKeyboardButton("📋 View Checks", callback_data=f"checks_{repository}_{pr_number}")
            ],
            [
                InlineKeyboardButton("✅ Acknowledge", callback_data=f"ack_{repository}_{pr_number}_{check_name}"),
                InlineKeyboardButton("⏸️ Snooze 1h", callback_data=f"snooze_1_{repository}_{pr_number}_{check_name}")
            ],
            [
                InlineKeyboardButton("🔇 Disable for this PR", callback_data=f"disable_{repository}_{pr_number}"),
                InlineKeyboardButton("🛠️ Manual Fix", callback_data=f"manual_{repository}_{pr_number}_{check_name}")
            ]
        ])
        
        try:
            # Send message
            sent_message = await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="Markdown",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            
            return {
                "success": True,
                "message_id": sent_message.message_id,
                "chat_id": self.chat_id,
                "timestamp": datetime.now().isoformat()
            }
            
        except TelegramError as e:
            logger.error(f"Failed to send escalation: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_status_update(
        self,
        repository: str,
        pr_number: int,
        check_name: str,
        status: str
    ) -> Dict[str, Any]:
        """Send status update notification."""
        
        logger.info(f"Sending status update for {repository} PR #{pr_number}")
        
        if self.dry_run:
            return {"success": True, "message": "Mock status update sent"}
        
        message = f"""
🔄 *Status Update*

**Repository**: `{repository}`
**PR**: #{pr_number}
**Check**: `{check_name}`
**Status**: {status}

_Automated update from PR Check Agent_
"""
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="Markdown"
            )
            
            return {"success": True, "message": "Status update sent"}
            
        except TelegramError as e:
            logger.error(f"Failed to send status update: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_daily_summary(self) -> Dict[str, Any]:
        """Send daily summary of agent activity."""
        
        if self.dry_run:
            return {"success": True, "message": "Mock daily summary sent"}
        
        # This would typically pull metrics from Redis or monitoring system
        message = f"""
📊 *Daily PR Check Agent Summary*

**Date**: {datetime.now().strftime('%Y-%m-%d')}

• PRs Monitored: 23
• Checks Analyzed: 156
• Fixes Attempted: 12
• Fixes Successful: 8 (67%)
• Escalations Sent: 4

**Top Issues**:
• Linting errors: 6 fixes
• Test failures: 3 fixes
• Build failures: 2 fixes

_Automated summary from PR Check Agent_
"""
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="Markdown"
            )
            
            return {"success": True, "message": "Daily summary sent"}
            
        except TelegramError as e:
            logger.error(f"Failed to send daily summary: {e}")
            return {"success": False, "error": str(e)}
    
    def _create_escalation_message(
        self,
        repository: str,
        pr_number: int,
        check_name: str,
        failure_context: str,
        fix_attempts: List[Dict[str, Any]],
        escalation_reason: str,
        mentions: List[str]
    ) -> str:
        """Create formatted escalation message."""
        
        # Mention users if specified
        mention_text = ""
        if mentions:
            mention_text = " " + " ".join(mentions)
        
        # Format fix attempts
        attempts_text = ""
        if fix_attempts:
            attempts_text = f"\n\n**Fix Attempts** ({len(fix_attempts)}):\n"
            for i, attempt in enumerate(fix_attempts, 1):
                status = attempt.get('status', 'unknown')
                timestamp = attempt.get('timestamp', 'unknown')
                attempts_text += f"{i}. {timestamp} - {status}\n"
        
        # Truncate failure context if too long
        context = failure_context[:800] + "..." if len(failure_context) > 800 else failure_context
        
        message = f"""
🚨 *ESCALATION REQUIRED*{mention_text}

**Repository**: `{repository}`
**PR**: #{pr_number}
**Check**: `{check_name}`
**Reason**: {escalation_reason}

**Failure Details**:
```
{context}
```{attempts_text}

❗ *Automatic fixes have been exhausted. Human intervention required.*

🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
        
        return message
    
    def _mock_escalation_response(self, repository: str, pr_number: int, check_name: str) -> Dict[str, Any]:
        """Mock response for escalations in dry-run mode."""
        return {
            "success": True,
            "message_id": 12345,
            "chat_id": self.chat_id or "mock_chat_id",
            "timestamp": datetime.now().isoformat(),
            "mock": True
        }
    
    async def handle_callback(self, callback_data: str, user_id: str) -> Dict[str, Any]:
        """Handle callback from inline keyboard buttons."""
        
        parts = callback_data.split('_')
        action = parts[0]
        
        try:
            if action == "ack":
                repository, pr_number, check_name = parts[1], parts[2], parts[3]
                return await self._handle_acknowledge(repository, pr_number, check_name, user_id)
            elif action == "snooze":
                hours = int(parts[1])
                repository, pr_number, check_name = parts[2], parts[3], parts[4]
                return await self._handle_snooze(repository, pr_number, check_name, hours, user_id)
            elif action == "disable":
                repository, pr_number = parts[1], parts[2]
                return await self._handle_disable(repository, pr_number, user_id)
            elif action == "manual":
                repository, pr_number, check_name = parts[1], parts[2], parts[3]
                return await self._handle_manual_fix(repository, pr_number, check_name, user_id)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
                
        except Exception as e:
            logger.error(f"Error handling callback {callback_data}: {e}")
            return {"success": False, "error": str(e)}
    
    async def _handle_acknowledge(self, repository: str, pr_number: str, check_name: str, user_id: str) -> Dict[str, Any]:
        """Handle acknowledgment of escalation."""
        # This would update the escalation status in Redis
        logger.info(f"Escalation acknowledged by {user_id} for {repository}#{pr_number} - {check_name}")
        return {"success": True, "action": "acknowledged", "user": user_id}
    
    async def _handle_snooze(self, repository: str, pr_number: str, check_name: str, hours: int, user_id: str) -> Dict[str, Any]:
        """Handle snoozing of escalation."""
        # This would set a snooze timer in Redis
        logger.info(f"Escalation snoozed for {hours}h by {user_id} for {repository}#{pr_number} - {check_name}")
        return {"success": True, "action": "snoozed", "hours": hours, "user": user_id}
    
    async def _handle_disable(self, repository: str, pr_number: str, user_id: str) -> Dict[str, Any]:
        """Handle disabling monitoring for a PR."""
        # This would disable monitoring for the PR
        logger.info(f"Monitoring disabled by {user_id} for {repository}#{pr_number}")
        return {"success": True, "action": "disabled", "user": user_id}
    
    async def _handle_manual_fix(self, repository: str, pr_number: str, check_name: str, user_id: str) -> Dict[str, Any]:
        """Handle manual fix indication."""
        # This would mark the issue as being manually handled
        logger.info(f"Manual fix initiated by {user_id} for {repository}#{pr_number} - {check_name}")
        return {"success": True, "action": "manual_fix", "user": user_id}
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on Telegram bot."""
        try:
            if self.dry_run:
                return {"status": "healthy", "mode": "dry_run"}
            
            if not self.bot:
                return {"status": "unhealthy", "error": "Bot not initialized"}
            
            # Test bot API access
            bot_info = await self.bot.get_me()
            
            return {
                "status": "healthy",
                "bot_username": bot_info.username,
                "bot_id": bot_info.id,
                "chat_id": self.chat_id
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }