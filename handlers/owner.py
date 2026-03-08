from telethon import events
from telethon.tl.custom import Message
from typing import Dict, Optional
from loguru import logger
import re

from db.users import user_manager
from db.deposits import deposit_manager, DepositStatus
from services.api_client import api_client, APIRequestError, APIResponseError
from config import config


class OwnerNotifier:
    """Handle owner notifications and commands."""
    
    # Store pending withdrawals (user_id, deposit_wallet, amount)
    _pending_withdrawals: Dict[str, tuple] = {}
    
    async def notify_new_deposit(self, user_id: int, wallet: str, amount: float):
        """Notify owner about new deposit."""
        try:
            from main import bot  # Import here to avoid circular import
            
            # Shorten wallet for display
            short_wallet = f"{wallet[:6]}...{wallet[-4:]}"
            
            message = (
                "<b>💰 New Deposit</b>\n\n"
                f"<b>User:</b> <code>{user_id}</code>\n"
                f"<b>Wallet:</b> <code>{short_wallet}</code>\n"
                f"<b>Amount:</b> <code>{amount:.2f} USDT</code>\n\n"
                "Reply with a BEP20 wallet address to withdraw these funds."
            )
            
            # Store withdrawal info for this message
            msg = await bot.send_message(config.OWNER_ID, message, parse_mode="html")
            self._pending_withdrawals[str(msg.id)] = (user_id, wallet, amount)
            
            logger.info(f"Notified owner about deposit from user {user_id}: {amount} USDT")
            
        except Exception as e:
            logger.error(f"Failed to notify owner about deposit: {e}")
    
    async def handle_withdraw_reply(self, event: Message):
        """Handle owner's reply with withdrawal address."""
        # Check if this is a reply to one of our notifications
        if not event.reply_to_msg_id:
            return False
        
        reply_id = str(event.reply_to_msg_id)
        
        if reply_id not in self._pending_withdrawals:
            return False
        
        user_id, from_wallet, amount = self._pending_withdrawals[reply_id]
        to_wallet = event.raw_text.strip()
        
        # Validate wallet address (basic BEP20 validation)
        if not self._validate_wallet(to_wallet):
            await event.reply(
                "❌ Invalid wallet address. Please provide a valid BEP20 address.",
                parse_mode="html"
            )
            return True
        
        try:
            # Process withdrawal
            await self._process_withdrawal(event, user_id, from_wallet, to_wallet, amount)
            
            # Remove from pending
            del self._pending_withdrawals[reply_id]
            
        except Exception as e:
            logger.error(f"Error processing withdrawal: {e}")
            await event.reply(
                "❌ Failed to process withdrawal. Please try again later.",
                parse_mode="html"
            )
        
        return True
    
    async def _process_withdrawal(self, event, user_id: int, from_wallet: str, to_wallet: str, amount: float):
        """Process withdrawal via API."""
        # Send processing message
        processing_msg = await event.reply(
            "<b>⏳ Processing withdrawal...</b>",
            parse_mode="html"
        )
        
        try:
            async with api_client as client:
                result = await client.withdraw(from_wallet, to_wallet, amount)
            
            # Get transaction hash
            tx_hash = result.get("txid") or result.get("transaction", "")
            
            # Format for display
            short_tx = f"{tx_hash[:10]}...{tx_hash[-8:]}" if len(tx_hash) > 20 else tx_hash
            
            success_message = (
                "<b>✅ Withdrawal Successful</b>\n\n"
                f"<b>Amount:</b> <code>{amount:.2f} USDT</code>\n"
                f"<b>From:</b> <code>{from_wallet[:6]}...{from_wallet[-4:]}</code>\n"
                f"<b>To:</b> <code>{to_wallet[:6]}...{to_wallet[-4:]}</code>\n\n"
                f"<b>Transaction:</b>\n"
                f"<code>{tx_hash}</code>"
            )
            
            await processing_msg.delete()
            await event.reply(success_message, parse_mode="html")
            
            logger.info(f"Withdrawal processed: {amount} USDT from {from_wallet} to {to_wallet}")
            
        except (APIRequestError, APIResponseError) as e:
            await processing_msg.delete()
            await event.reply(
                f"❌ Withdrawal failed: {str(e)}",
                parse_mode="html"
            )
        except Exception as e:
            await processing_msg.delete()
            await event.reply(
                "❌ An unexpected error occurred during withdrawal.",
                parse_mode="html"
            )
    
    def _validate_wallet(self, wallet: str) -> bool:
        """Basic BEP20 wallet validation."""
        # BEP20 addresses are 42 characters (0x + 40 hex)
        pattern = r'^0x[a-fA-F0-9]{40}$'
        return bool(re.match(pattern, wallet))


# Singleton instance
owner_notifier = OwnerNotifier()
