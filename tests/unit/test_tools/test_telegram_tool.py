"""
Tests for Telegram notification tool
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from src.tools.telegram_tool import TelegramTool, TelegramInput


class TestTelegramInput:
    """Test cases for Telegram input validation."""
    
    def test_telegram_input_minimal(self):
        """Test minimal valid input."""
        input_data = TelegramInput(
            operation="send_escalation",
            repository="owner/repo",
            pr_number=123,
            check_name="CI",
            failure_context="Test failure"
        )
        
        assert input_data.operation == "send_escalation"
        assert input_data.repository == "owner/repo"
        assert input_data.pr_number == 123
        assert input_data.check_name == "CI"
        assert input_data.failure_context == "Test failure"
        assert input_data.fix_attempts == []
        assert input_data.escalation_reason == ""
        assert input_data.mentions == []
    
    def test_telegram_input_full(self):
        """Test input with all fields."""
        fix_attempts = [
            {"timestamp": "2023-01-01T12:00:00", "status": "failed"},
            {"timestamp": "2023-01-01T13:00:00", "status": "failed"}
        ]
        
        input_data = TelegramInput(
            operation="send_escalation",
            repository="owner/repo",
            pr_number=456,
            check_name="Tests",
            failure_context="Multiple test failures",
            fix_attempts=fix_attempts,
            escalation_reason="Max attempts exceeded",
            mentions=["@dev-lead", "@oncall"]
        )
        
        assert input_data.operation == "send_escalation"
        assert input_data.repository == "owner/repo"
        assert input_data.pr_number == 456
        assert input_data.check_name == "Tests"
        assert input_data.failure_context == "Multiple test failures"
        assert len(input_data.fix_attempts) == 2
        assert input_data.escalation_reason == "Max attempts exceeded"
        assert input_data.mentions == ["@dev-lead", "@oncall"]


class TestTelegramTool:
    """Test cases for Telegram notification tool."""
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    def test_telegram_tool_initialization_success(self, mock_bot_class):
        """Test successful tool initialization."""
        mock_bot = MagicMock()
        mock_bot_class.return_value = mock_bot
        
        tool = TelegramTool()
        
        assert tool.name == "telegram_notify"
        assert tool.description == "Send notifications and escalations via Telegram"
        assert tool.args_schema == TelegramInput
        assert tool.bot_token == 'test_bot_token'
        assert tool.chat_id == 'test_chat_id'
        assert tool.bot == mock_bot
        assert tool.dry_run is False
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    def test_telegram_tool_initialization_dry_run(self):
        """Test initialization in dry run mode."""
        tool = TelegramTool(dry_run=True)
        
        assert tool.dry_run is True
        assert tool.bot is None
    
    def test_telegram_tool_initialization_no_credentials(self):
        """Test initialization without credentials in production mode."""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required"):
                TelegramTool()
    
    def test_telegram_tool_initialization_dry_run_no_credentials(self):
        """Test initialization without credentials in dry run mode."""
        with patch.dict('os.environ', {}, clear=True):
            tool = TelegramTool(dry_run=True)
            assert tool.dry_run is True
            assert tool.bot is None
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    def test_telegram_tool_unknown_operation(self, mock_bot_class):
        """Test handling of unknown operation."""
        tool = TelegramTool()
        
        result = tool._run(
            operation="unknown_operation",
            repository="owner/repo",
            pr_number=123,
            check_name="CI",
            failure_context="test failure"
        )
        
        assert result["success"] is False
        assert "Unknown operation" in result["error"]
    
    def test_send_escalation_dry_run(self):
        """Test send escalation in dry run mode."""
        tool = TelegramTool(dry_run=True)
        
        result = tool._run(
            operation="send_escalation",
            repository="owner/repo",
            pr_number=123,
            check_name="CI",
            failure_context="Test failure context",
            fix_attempts=[],
            escalation_reason="Test escalation",
            mentions=["@dev-lead"]
        )
        
        assert result["success"] is True
        assert result["message_id"] == 12345
        assert "mock_chat_id" in result["chat_id"]
        assert "timestamp" in result
        assert result["mock"] is True
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    @pytest.mark.asyncio
    async def test_send_escalation_success(self, mock_bot_class):
        """Test successful escalation sending."""
        # Setup mock bot
        mock_bot = AsyncMock()
        mock_message = MagicMock()
        mock_message.message_id = 54321
        mock_bot.send_message.return_value = mock_message
        mock_bot_class.return_value = mock_bot
        
        tool = TelegramTool()
        tool.bot = mock_bot  # Override with async mock
        
        result = await tool._arun(
            operation="send_escalation",
            repository="owner/repo",
            pr_number=456,
            check_name="Tests",
            failure_context="Multiple test failures detected",
            fix_attempts=[
                {"timestamp": "2023-01-01T12:00:00", "status": "failed"},
                {"timestamp": "2023-01-01T13:00:00", "status": "failed"}
            ],
            escalation_reason="Maximum fix attempts reached",
            mentions=["@dev-team"]
        )
        
        assert result["success"] is True
        assert result["message_id"] == 54321
        assert result["chat_id"] == "test_chat_id"
        assert "timestamp" in result
        
        # Verify bot was called correctly
        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        assert call_args.kwargs["chat_id"] == "test_chat_id"
        assert "ESCALATION REQUIRED" in call_args.kwargs["text"]
        assert "owner/repo" in call_args.kwargs["text"]
        assert "#456" in call_args.kwargs["text"]
        assert "Tests" in call_args.kwargs["text"]
        assert "@dev-team" in call_args.kwargs["text"]
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    @pytest.mark.asyncio
    async def test_send_escalation_telegram_error(self, mock_bot_class):
        """Test escalation sending with Telegram API error."""
        # Setup mock bot that raises an error
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = Exception("Telegram API Error")
        mock_bot_class.return_value = mock_bot
        
        tool = TelegramTool()
        tool.bot = mock_bot
        
        result = await tool._arun(
            operation="send_escalation",
            repository="owner/repo",
            pr_number=123,
            check_name="CI",
            failure_context="Test failure",
            escalation_reason="Test error handling"
        )
        
        assert result["success"] is False
        assert "Telegram API Error" in result["error"]
    
    def test_send_status_update_dry_run(self):
        """Test status update in dry run mode."""
        tool = TelegramTool(dry_run=True)
        
        result = tool._run(
            operation="send_status",
            repository="owner/repo",
            pr_number=123,
            check_name="CI",
            failure_context="success"
        )
        
        assert result["success"] is True
        assert result["message"] == "Mock status update sent"
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    @pytest.mark.asyncio
    async def test_send_status_update_success(self, mock_bot_class):
        """Test successful status update sending."""
        mock_bot = AsyncMock()
        mock_bot.send_message.return_value = MagicMock()
        mock_bot_class.return_value = mock_bot
        
        tool = TelegramTool()
        tool.bot = mock_bot
        
        result = await tool._arun(
            operation="send_status",
            repository="owner/repo",
            pr_number=789,
            check_name="Linting",
            failure_context="Fixed successfully"
        )
        
        assert result["success"] is True
        assert result["message"] == "Status update sent"
        
        # Verify message content
        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        message_text = call_args.kwargs["text"]
        assert "Status Update" in message_text
        assert "owner/repo" in message_text
        assert "#789" in message_text
        assert "Linting" in message_text
    
    def test_send_daily_summary_dry_run(self):
        """Test daily summary in dry run mode."""
        tool = TelegramTool(dry_run=True)
        
        result = tool._run(
            operation="send_summary",
            repository="owner/repo",
            pr_number=0,  # Not used for summary
            check_name="",  # Not used for summary
            failure_context=""  # Not used for summary
        )
        
        assert result["success"] is True
        assert result["message"] == "Mock daily summary sent"
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    @pytest.mark.asyncio
    async def test_send_daily_summary_success(self, mock_bot_class):
        """Test successful daily summary sending."""
        mock_bot = AsyncMock()
        mock_bot.send_message.return_value = MagicMock()
        mock_bot_class.return_value = mock_bot
        
        tool = TelegramTool()
        tool.bot = mock_bot
        
        result = await tool._arun(
            operation="send_summary",
            repository="owner/repo",
            pr_number=0,
            check_name="",
            failure_context=""
        )
        
        assert result["success"] is True
        assert result["message"] == "Daily summary sent"
        
        # Verify summary content
        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        message_text = call_args.kwargs["text"]
        assert "Daily PR Check Agent Summary" in message_text
        assert "PRs Monitored" in message_text
        assert "Fixes Attempted" in message_text
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    def test_create_escalation_message_basic(self, mock_bot_class):
        """Test escalation message creation with basic data."""
        tool = TelegramTool()
        
        message = tool._create_escalation_message(
            repository="test/repo",
            pr_number=123,
            check_name="CI",
            failure_context="Build failed with exit code 1",
            fix_attempts=[],
            escalation_reason="Manual intervention required",
            mentions=[]
        )
        
        assert "ESCALATION REQUIRED" in message
        assert "test/repo" in message
        assert "#123" in message
        assert "CI" in message
        assert "Build failed with exit code 1" in message
        assert "Manual intervention required" in message
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    def test_create_escalation_message_with_attempts(self, mock_bot_class):
        """Test escalation message creation with fix attempts."""
        tool = TelegramTool()
        
        fix_attempts = [
            {"timestamp": "2023-01-01T12:00:00", "status": "failed"},
            {"timestamp": "2023-01-01T13:00:00", "status": "failed"}
        ]
        
        message = tool._create_escalation_message(
            repository="test/repo",
            pr_number=456,
            check_name="Tests",
            failure_context="Multiple test failures",
            fix_attempts=fix_attempts,
            escalation_reason="Max attempts exceeded",
            mentions=["@dev-lead", "@oncall"]
        )
        
        assert "ESCALATION REQUIRED @dev-lead @oncall" in message
        assert "Fix Attempts (2)" in message
        assert "2023-01-01T12:00:00" in message
        assert "failed" in message
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    def test_create_escalation_message_long_context(self, mock_bot_class):
        """Test escalation message creation with long failure context."""
        tool = TelegramTool()
        
        # Create a very long failure context
        long_context = "Error: " + "A" * 1000  # 1000+ characters
        
        message = tool._create_escalation_message(
            repository="test/repo",
            pr_number=789,
            check_name="Build",
            failure_context=long_context,
            fix_attempts=[],
            escalation_reason="Context truncation test",
            mentions=[]
        )
        
        assert "ESCALATION REQUIRED" in message
        assert "..." in message  # Should be truncated
        assert len(message) < len(long_context)  # Should be shorter than original
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    @pytest.mark.asyncio
    async def test_handle_callback_acknowledge(self, mock_bot_class):
        """Test handling acknowledge callback."""
        tool = TelegramTool()
        
        result = await tool.handle_callback("ack_test/repo_123_CI", "user123")
        
        assert result["success"] is True
        assert result["action"] == "acknowledged"
        assert result["user"] == "user123"
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    @pytest.mark.asyncio
    async def test_handle_callback_snooze(self, mock_bot_class):
        """Test handling snooze callback."""
        tool = TelegramTool()
        
        result = await tool.handle_callback("snooze_2_test/repo_456_Tests", "user456")
        
        assert result["success"] is True
        assert result["action"] == "snoozed"
        assert result["hours"] == 2
        assert result["user"] == "user456"
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    @pytest.mark.asyncio
    async def test_handle_callback_disable(self, mock_bot_class):
        """Test handling disable callback."""
        tool = TelegramTool()
        
        result = await tool.handle_callback("disable_test/repo_789", "user789")
        
        assert result["success"] is True
        assert result["action"] == "disabled"
        assert result["user"] == "user789"
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    @pytest.mark.asyncio
    async def test_handle_callback_manual_fix(self, mock_bot_class):
        """Test handling manual fix callback."""
        tool = TelegramTool()
        
        result = await tool.handle_callback("manual_test/repo_101_Linting", "user101")
        
        assert result["success"] is True
        assert result["action"] == "manual_fix"
        assert result["user"] == "user101"
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    @pytest.mark.asyncio
    async def test_handle_callback_unknown_action(self, mock_bot_class):
        """Test handling unknown callback action."""
        tool = TelegramTool()
        
        result = await tool.handle_callback("unknown_action_data", "user123")
        
        assert result["success"] is False
        assert "Unknown action" in result["error"]
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    @pytest.mark.asyncio
    async def test_health_check_dry_run(self, mock_bot_class):
        """Test health check in dry run mode."""
        tool = TelegramTool(dry_run=True)
        result = await tool.health_check()
        
        assert result["status"] == "healthy"
        assert result["mode"] == "dry_run"
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_bot_class):
        """Test successful health check."""
        # Setup mock bot
        mock_bot = AsyncMock()
        mock_bot_info = MagicMock()
        mock_bot_info.username = "test_bot"
        mock_bot_info.id = 123456789
        mock_bot.get_me.return_value = mock_bot_info
        mock_bot_class.return_value = mock_bot
        
        tool = TelegramTool()
        tool.bot = mock_bot
        
        result = await tool.health_check()
        
        assert result["status"] == "healthy"
        assert result["bot_username"] == "test_bot"
        assert result["bot_id"] == 123456789
        assert result["chat_id"] == "test_chat_id"
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    @pytest.mark.asyncio
    async def test_health_check_no_bot(self, mock_bot_class):
        """Test health check with no bot initialized."""
        tool = TelegramTool()
        tool.bot = None  # Simulate bot not initialized
        
        result = await tool.health_check()
        
        assert result["status"] == "unhealthy"
        assert "Bot not initialized" in result["error"]
    
    @patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_bot_token',
        'TELEGRAM_CHAT_ID': 'test_chat_id'
    })
    @patch('telegram.Bot')
    @pytest.mark.asyncio
    async def test_health_check_api_error(self, mock_bot_class):
        """Test health check with Telegram API error."""
        # Setup mock bot that raises an error
        mock_bot = AsyncMock()
        mock_bot.get_me.side_effect = Exception("API Error")
        mock_bot_class.return_value = mock_bot
        
        tool = TelegramTool()
        tool.bot = mock_bot
        
        result = await tool.health_check()
        
        assert result["status"] == "unhealthy"
        assert "API Error" in result["error"]