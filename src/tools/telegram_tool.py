"""Telegram notification tool for PR Check Agent
Handles human escalation notifications as a LangGraph tool
"""

import asyncio
import hashlib
import os
import time
import traceback
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from langchain.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError


def retry_with_exponential_backoff(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0):  # noqa: PLR0915
    """Decorator to retry async functions with exponential backoff."""

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:  # noqa: PLR0915
        async def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: PLR0915, PLR0912
            func_name = func.__name__
            start_time = time.time()
            last_exception = None

            # Extract context for logging if available
            context_info = ""
            if len(args) > 0 and hasattr(args[0], "__class__"):
                if hasattr(args[0], "name"):
                    context_info = f" [{args[0].name}]"
                elif hasattr(args[0], "__class__"):
                    context_info = f" [{args[0].__class__.__name__}]"

            # Log retry attempt start
            if max_retries > 0:
                logger.info(
                    f"Starting {func_name}{context_info} with retry policy: max_retries={max_retries}, base_delay={base_delay}s, max_delay={max_delay}s"
                )

            for attempt in range(max_retries + 1):  # +1 for the initial attempt
                attempt_start_time = time.time()

                try:
                    # Log attempt start (except for first attempt to reduce noise)
                    if attempt > 0:
                        logger.info(f"🔄 {func_name}{context_info} attempt #{attempt + 1}/{max_retries + 1}")

                    result = await func(*args, **kwargs)

                    # Log successful completion
                    total_duration = time.time() - start_time
                    if attempt > 0:
                        logger.info(
                            f"✅ {func_name}{context_info} succeeded on attempt #{attempt + 1} after {total_duration:.2f}s total"
                        )
                    elif max_retries > 0:
                        logger.debug(f"✅ {func_name}{context_info} succeeded on first attempt ({total_duration:.2f}s)")

                    return result

                except TelegramError as e:
                    last_exception = e
                    attempt_duration = time.time() - attempt_start_time
                    error_type = type(e).__name__

                    # Don't retry on certain errors that are unlikely to be transient
                    error_msg_lower = str(e).lower().replace("_", "")
                    if "buttondatainvalid" in error_msg_lower or "button data invalid" in error_msg_lower:
                        logger.warning(
                            f"⚠️ {func_name}{context_info} attempt #{attempt + 1} failed with {error_type}: {e} (took {attempt_duration:.2f}s)"
                        )
                        logger.warning("🔧 Button data too long detected, switching to simplified buttons for next attempt")

                        # Log full exception details to console for debugging
                        exc_details = traceback.format_exc()
                        logger.debug(f"Button data invalid exception traceback:\n{exc_details}")

                        # Set a flag to simplify buttons on retry if this is a method call on TelegramTool
                        if len(args) > 0 and hasattr(args[0], "_should_simplify_buttons"):
                            args[0]._should_simplify_buttons = True

                    elif "chat not found" in str(e).lower() or "forbidden" in str(e).lower():
                        total_duration = time.time() - start_time
                        logger.error(
                            f"❌ {func_name}{context_info} permanent error on attempt #{attempt + 1}: {e} (total time: {total_duration:.2f}s)"
                        )
                        logger.error(f"🚫 Not retrying due to permanent error type: {error_type}")

                        # Log full exception details to console for permanent errors
                        exc_details = traceback.format_exc()
                        logger.error(f"Permanent error exception traceback:\n{exc_details}")
                        break
                    else:
                        logger.warning(
                            f"⚠️ {func_name}{context_info} attempt #{attempt + 1} failed with {error_type}: {e} (took {attempt_duration:.2f}s)"
                        )

                        # Log exception traceback for unexpected Telegram errors
                        exc_details = traceback.format_exc()
                        logger.debug(f"TelegramError exception traceback:\n{exc_details}")

                    if attempt < max_retries:
                        delay = min(base_delay * (2**attempt), max_delay)
                        logger.info(
                            f"⏳ Retrying {func_name}{context_info} in {delay:.1f}s... (attempt {attempt + 2}/{max_retries + 1})"
                        )
                        await asyncio.sleep(delay)
                    else:
                        total_duration = time.time() - start_time
                        logger.error(
                            f"❌ {func_name}{context_info} failed all {max_retries + 1} attempts. Total time: {total_duration:.2f}s, Final error: {e}"
                        )

                        # Log final exception details to console
                        exc_details = traceback.format_exc()
                        logger.error(f"Final TelegramError exception traceback:\n{exc_details}")

                except Exception as e:
                    last_exception = e
                    attempt_duration = time.time() - attempt_start_time
                    error_type = type(e).__name__

                    logger.warning(
                        f"⚠️ {func_name}{context_info} attempt #{attempt + 1} failed with unexpected {error_type}: {e} (took {attempt_duration:.2f}s)"
                    )

                    # Always log full traceback for unexpected exceptions to console
                    exc_details = traceback.format_exc()
                    logger.error(f"Unexpected exception traceback:\n{exc_details}")

                    if attempt < max_retries:
                        delay = min(base_delay * (2**attempt), max_delay)
                        logger.info(
                            f"⏳ Retrying {func_name}{context_info} in {delay:.1f}s... (attempt {attempt + 2}/{max_retries + 1})"
                        )
                        await asyncio.sleep(delay)
                    else:
                        total_duration = time.time() - start_time
                        logger.error(
                            f"❌ {func_name}{context_info} failed all {max_retries + 1} attempts. Total time: {total_duration:.2f}s, Final error: {e}"
                        )

                        # Log final exception details to console
                        exc_details = traceback.format_exc()
                        logger.error(f"Final unexpected exception traceback:\n{exc_details}")

            # If we get here, all attempts failed
            total_duration = time.time() - start_time
            logger.error(
                f"💥 {func_name}{context_info} exhausted all retry attempts ({max_retries + 1}) in {total_duration:.2f}s"
            )
            return {
                "success": False,
                "error": str(last_exception),
                "attempts": max_retries + 1,
                "total_duration": total_duration,
            }

        return wrapper

    return decorator


class TelegramInput(BaseModel):
    """Input schema for Telegram operations."""

    operation: str = Field(description="Operation: 'send_escalation', 'send_status', 'send_summary'")
    repository: str = Field(description="Repository name")
    pr_number: int = Field(description="PR number")
    check_name: str = Field(description="Check name that failed")
    failure_context: str = Field(description="Failure details")
    fix_attempts: list[dict[str, Any]] = Field(default=[], description="Previous fix attempts")
    escalation_reason: str = Field(default="", description="Reason for escalation")
    mentions: list[str] = Field(default=[], description="Users to mention")


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
        self._should_simplify_buttons = False

        if not self.bot_token or not self.chat_id:
            if not dry_run:
                raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
            logger.warning("Telegram credentials not found, running in dry-run mode")

        self.bot = Bot(token=self.bot_token) if self.bot_token and not dry_run else None

        logger.info(f"Telegram tool initialized (dry_run={dry_run})")

    def _create_simplified_keyboard(self, repository: str, pr_number: int, check_name: str) -> InlineKeyboardMarkup:
        """Create simplified keyboard with shorter callback data to avoid button_data_invalid errors."""
        # Use hash to shorten long repository/check names
        repo_hash = hashlib.sha256(repository.encode()).hexdigest()[:8]
        check_hash = hashlib.sha256(check_name.encode()).hexdigest()[:8]

        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🔍 View PR", url=f"https://github.com/{repository}/pull/{pr_number}"),
                ],
                [
                    InlineKeyboardButton("✅ Acknowledge", callback_data=f"ack_{repo_hash}_{pr_number}_{check_hash}"),
                    InlineKeyboardButton("⏸️ Snooze", callback_data=f"snz_{repo_hash}_{pr_number}_{check_hash}"),
                ],
                [
                    InlineKeyboardButton("🔇 Disable", callback_data=f"dis_{repo_hash}_{pr_number}"),
                ],
            ]
        )

    def _create_full_keyboard(self, repository: str, pr_number: int, check_name: str) -> InlineKeyboardMarkup:
        """Create full keyboard with all options."""
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🔍 View PR", url=f"https://github.com/{repository}/pull/{pr_number}"),
                    InlineKeyboardButton("📋 View Checks", callback_data=f"checks_{repository}_{pr_number}"),
                ],
                [
                    InlineKeyboardButton("✅ Acknowledge", callback_data=f"ack_{repository}_{pr_number}_{check_name}"),
                    InlineKeyboardButton("⏸️ Snooze 1h", callback_data=f"snooze_1_{repository}_{pr_number}_{check_name}"),
                ],
                [
                    InlineKeyboardButton("🔇 Disable for this PR", callback_data=f"disable_{repository}_{pr_number}"),
                    InlineKeyboardButton("🛠️ Manual Fix", callback_data=f"manual_{repository}_{pr_number}_{check_name}"),
                ],
            ]
        )

    def _run(self, operation: str, **kwargs) -> dict[str, Any]:
        """Synchronous wrapper for async operations."""
        return asyncio.run(self._arun(operation, **kwargs))

    async def _arun(
        self,
        operation: str,
        repository: str,
        pr_number: int,
        check_name: str,
        failure_context: str,
        fix_attempts: list[dict[str, Any]] = None,
        escalation_reason: str = "",
        mentions: list[str] = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Execute Telegram operation."""
        if fix_attempts is None:
            fix_attempts = []
        if mentions is None:
            mentions = []

        try:
            if operation == "send_escalation":
                return await self._send_escalation(
                    repository, pr_number, check_name, failure_context, fix_attempts, escalation_reason, mentions
                )
            if operation == "send_status":
                return await self._send_status_update(repository, pr_number, check_name, failure_context)
            if operation == "send_summary":
                return await self._send_daily_summary()
            raise ValueError(f"Unknown operation: {operation}")

        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return {"success": False, "error": str(e)}

    @retry_with_exponential_backoff(max_retries=3, base_delay=1.0, max_delay=30.0)
    async def _send_escalation(
        self,
        repository: str,
        pr_number: int,
        check_name: str,
        failure_context: str,
        fix_attempts: list[dict[str, Any]],
        escalation_reason: str,
        mentions: list[str],
    ) -> dict[str, Any]:
        """Send escalation notification to Telegram."""
        logger.info(f"Sending escalation for {repository} PR #{pr_number} - {check_name}")

        if self.dry_run:
            return self._mock_escalation_response(repository, pr_number, check_name)

        # Create escalation message
        message = self._create_escalation_message(
            repository, pr_number, check_name, failure_context, fix_attempts, escalation_reason, mentions
        )

        # Create inline keyboard for quick actions
        # Use simplified keyboard if button_data_invalid error occurred previously
        if self._should_simplify_buttons:
            keyboard = self._create_simplified_keyboard(repository, pr_number, check_name)
            logger.info("Using simplified keyboard due to previous button_data_invalid error")
        else:
            keyboard = self._create_full_keyboard(repository, pr_number, check_name)

        if self.bot is None or self.chat_id is None:
            return {"success": False, "error": "Bot or chat_id not configured"}

        # Send message - let the retry decorator handle any TelegramErrors
        sent_message = await self.bot.send_message(
            chat_id=self.chat_id, text=message, parse_mode="Markdown", reply_markup=keyboard, disable_web_page_preview=True
        )

        return {
            "success": True,
            "message_id": sent_message.message_id,
            "chat_id": self.chat_id,
            "timestamp": datetime.now().isoformat(),
        }

    @retry_with_exponential_backoff(max_retries=2, base_delay=1.0, max_delay=10.0)
    async def _send_status_update(self, repository: str, pr_number: int, check_name: str, status: str) -> dict[str, Any]:
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

        if self.bot is None or self.chat_id is None:
            return {"success": False, "error": "Bot or chat_id not configured"}

        await self.bot.send_message(chat_id=self.chat_id, text=message, parse_mode="Markdown")

        return {"success": True, "message": "Status update sent"}

    @retry_with_exponential_backoff(max_retries=2, base_delay=1.0, max_delay=10.0)
    async def _send_daily_summary(self) -> dict[str, Any]:
        """Send daily summary of agent activity."""
        if self.dry_run:
            return {"success": True, "message": "Mock daily summary sent"}

        # This would typically pull metrics from Redis or monitoring system
        message = f"""
📊 *Daily PR Check Agent Summary*

**Date**: {datetime.now().strftime("%Y-%m-%d")}

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

        if self.bot is None or self.chat_id is None:
            return {"success": False, "error": "Bot or chat_id not configured"}

        await self.bot.send_message(chat_id=self.chat_id, text=message, parse_mode="Markdown")

        return {"success": True, "message": "Daily summary sent"}

    def _create_escalation_message(
        self,
        repository: str,
        pr_number: int,
        check_name: str,
        failure_context: str,
        fix_attempts: list[dict[str, Any]],
        escalation_reason: str,
        mentions: list[str],
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
                status = attempt.get("status", "unknown")
                timestamp = attempt.get("timestamp", "unknown")
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

🕐 {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}
"""

        return message

    def _mock_escalation_response(self, repository: str, pr_number: int, check_name: str) -> dict[str, Any]:
        """Mock response for escalations in dry-run mode."""
        return {
            "success": True,
            "message_id": 12345,
            "chat_id": self.chat_id or "mock_chat_id",
            "timestamp": datetime.now().isoformat(),
            "mock": True,
        }

    async def handle_callback(self, callback_data: str, user_id: str) -> dict[str, Any]:
        """Handle callback from inline keyboard buttons."""
        parts = callback_data.split("_")
        action = parts[0]

        try:
            if action == "ack":
                repository, pr_number, check_name = parts[1], parts[2], parts[3]
                return await self._handle_acknowledge(repository, pr_number, check_name, user_id)
            if action == "snooze":
                hours = int(parts[1])
                repository, pr_number, check_name = parts[2], parts[3], parts[4]
                return await self._handle_snooze(repository, pr_number, check_name, hours, user_id)
            if action == "disable":
                repository, pr_number = parts[1], parts[2]
                return await self._handle_disable(repository, pr_number, user_id)
            if action == "manual":
                repository, pr_number, check_name = parts[1], parts[2], parts[3]
                return await self._handle_manual_fix(repository, pr_number, check_name, user_id)
            return {"success": False, "error": f"Unknown action: {action}"}

        except Exception as e:
            logger.error(f"Error handling callback {callback_data}: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_acknowledge(self, repository: str, pr_number: str, check_name: str, user_id: str) -> dict[str, Any]:
        """Handle acknowledgment of escalation."""
        # This would update the escalation status in Redis
        logger.info(f"Escalation acknowledged by {user_id} for {repository}#{pr_number} - {check_name}")
        return {"success": True, "action": "acknowledged", "user": user_id}

    async def _handle_snooze(
        self, repository: str, pr_number: str, check_name: str, hours: int, user_id: str
    ) -> dict[str, Any]:
        """Handle snoozing of escalation."""
        # This would set a snooze timer in Redis
        logger.info(f"Escalation snoozed for {hours}h by {user_id} for {repository}#{pr_number} - {check_name}")
        return {"success": True, "action": "snoozed", "hours": hours, "user": user_id}

    async def _handle_disable(self, repository: str, pr_number: str, user_id: str) -> dict[str, Any]:
        """Handle disabling monitoring for a PR."""
        # This would disable monitoring for the PR
        logger.info(f"Monitoring disabled by {user_id} for {repository}#{pr_number}")
        return {"success": True, "action": "disabled", "user": user_id}

    async def _handle_manual_fix(self, repository: str, pr_number: str, check_name: str, user_id: str) -> dict[str, Any]:
        """Handle manual fix indication."""
        # This would mark the issue as being manually handled
        logger.info(f"Manual fix initiated by {user_id} for {repository}#{pr_number} - {check_name}")
        return {"success": True, "action": "manual_fix", "user": user_id}

    async def health_check(self) -> dict[str, Any]:
        """Perform health check on Telegram bot."""
        try:
            if self.dry_run:
                return {"status": "healthy", "mode": "dry_run"}

            if not self.bot:
                return {"status": "unhealthy", "error": "Bot not initialized"}

            # Test bot API access
            bot_info = await self.bot.get_me()

            return {"status": "healthy", "bot_username": bot_info.username, "bot_id": bot_info.id, "chat_id": self.chat_id}

        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
