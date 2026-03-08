from telethon import events, Button
from telethon.tl.custom import Message
from typing import Optional, Dict, Any
from loguru import logger
import re
import base64
import io

from db.users import user_manager
from db.deposits import deposit_manager, DepositStatus
from db.mongo import mongodb
from services.api_client import api_client, APIRequestError, APIResponseError
from config import config


class DepositHandler:
    """Handle deposit flow."""
    
    # Store user states (simple in-memory, could use Redis for production)
    _user_states: Dict[int, str] = {}
    _user_amounts: Dict[int, float] = {}
    
    async def start_deposit(self, event):
        """Start deposit flow - ask for amount."""
        user_id = event.sender_id
        
        # Set user state
        self._user_states[user_id] = "awaiting_amount"
        
        message = (
            "<b>💰 Enter Deposit Amount</b>\n\n"
            "Send the amount of USDT you want to deposit.\n\n"
            "Example: <code>100</code>\n\n"
            "<b>Minimum:</b> <code>1 USDT</code>\n"  # Changed from 10 to 1
            "<b>Maximum:</b> <code>10000 USDT</code>"
        )
        
        await event.edit(message, buttons=None, parse_mode="html")
        logger.info(f"User {user_id} started deposit flow")
    
    async def handle_amount(self, event: Message):
        """Handle amount input from user."""
        user_id = event.sender_id
        
        # Check if user is in correct state
        if self._user_states.get(user_id) != "awaiting_amount":
            return False
        
        try:
            # Parse amount
            text = event.raw_text.strip()
            amount = float(text)
            
            # Validate amount - Changed minimum from 10 to 1
            if amount < 1:  # Changed from 10 to 1
                await event.respond(
                    "❌ Minimum deposit amount is <code>1 USDT</code>.\n"  # Changed message
                    "Please send a valid amount:",
                    parse_mode="html"
                )
                return True
            
            if amount > 10000:
                await event.respond(
                    "❌ Maximum deposit amount is <code>10000 USDT</code>.\n"
                    "Please send a valid amount:",
                    parse_mode="html"
                )
                return True
            
            # Validate decimal places (optional - prevent too many decimals)
            if len(text.split('.')[-1]) > 6 if '.' in text else False:
                await event.respond(
                    "❌ Too many decimal places. Maximum 6 decimal places allowed.\n"
                    "Example: <code>1.5</code> or <code>100</code>",
                    parse_mode="html"
                )
                return True
            
            # Store amount and proceed
            self._user_amounts[user_id] = amount
            self._user_states[user_id] = "processing"
            
            # Show processing message
            processing_msg = await event.respond(
                "<b>⏳ Processing your deposit request...</b>",
                parse_mode="html"
            )
            
            # Generate wallet via API
            await self._create_deposit(event, user_id, amount, processing_msg)
            
            return True
            
        except ValueError:
            await event.respond(
                "❌ Invalid amount. Please send a valid number.\n"
                "Example: <code>1</code> or <code>100.50</code>",  # Updated example
                parse_mode="html"
            )
            return True
        except Exception as e:
            logger.error(f"Error processing amount for user {user_id}: {e}")
            await event.respond(
                "❌ An error occurred. Please try again later.",
                parse_mode="html"
            )
            # Clear user state
            self._clear_user_state(user_id)
            return True
    
    async def _create_deposit(self, event, user_id: int, amount: float, processing_msg: Message):
        """Create deposit via API and show instructions."""
        try:
            # Call API to generate wallet
            async with api_client as client:
                wallet_data = await client.generate_wallet(amount)
            
            # Save deposit to database
            deposit = await deposit_manager.create_deposit(
                user_id=user_id,
                wallet=wallet_data["wallet"],
                index=wallet_data["index"],
                expected_amount=amount,
                qr_code=wallet_data.get("qr")
            )
            
            # Delete processing message
            await processing_msg.delete()
            
            # Send deposit instructions
            await self._send_deposit_instructions(event, deposit, wallet_data)
            
        except (APIRequestError, APIResponseError) as e:
            logger.error(f"API error for user {user_id}: {e}")
            await processing_msg.delete()
            await event.respond(
                "❌ Failed to create deposit. Our service might be temporarily unavailable.\n"
                "Please try again later.",
                parse_mode="html"
            )
        except Exception as e:
            logger.error(f"Unexpected error for user {user_id}: {e}")
            await processing_msg.delete()
            await event.respond(
                "❌ An unexpected error occurred. Please try again later.",
                parse_mode="html"
            )
        finally:
            # Clear user state
            self._clear_user_state(user_id)
    
    async def _send_deposit_instructions(self, event, deposit: dict, wallet_data: dict):
        """Send deposit instructions to user."""
        wallet = deposit["wallet"]
        amount = deposit["expected_amount"]
        
        # Format wallet for display (shorten for better UX)
        short_wallet = f"{wallet[:6]}...{wallet[-4:]}"
        
        # Format amount based on decimal places
        if amount.is_integer():
            amount_str = f"{int(amount)}"
        else:
            amount_str = f"{amount:.2f}".rstrip('0').rstrip('.') if amount % 1 == 0 else f"{amount:.6f}".rstrip('0').rstrip('.')
        
        message = (
            "<b>💰 Deposit Created</b>\n\n"
            f"<b>Amount:</b> <code>{amount_str} USDT</code>\n"
            f"<b>Network:</b> BEP20 (Binance Smart Chain)\n\n"
            f"<b>Deposit Address:</b>\n"
            f"<code>{wallet}</code>\n\n"
            f"<b>⚠️ Important:</b>\n"
            f"• Send the <b>exact amount</b> shown above\n"
            f"• Only send <b>USDT (BEP20)</b> to this address\n"
            f"• Deposits from other networks will be lost\n"
            f"• The address expires in <b>{config.DEPOSIT_EXPIRY_MINUTES} minutes</b>\n\n"
            f"<b>⏳ Status:</b> Waiting for payment..."
        )
        
        # Create copy address button
        buttons = [
            [Button.url("📋 Copy Address", url=f"https://t.me/share/url?url={wallet}")],
            [Button.inline("🔄 Check Status", data=f"check_{wallet}")]
        ]
        
        # Handle QR code (could be URL or base64)
        qr_code = wallet_data.get("qr")
        
        if qr_code:
            try:
                # Check if it's a base64 string
                if isinstance(qr_code, str) and qr_code.startswith('data:image'):
                    # Extract base64 data
                    base64_data = qr_code.split(',')[1] if ',' in qr_code else qr_code
                    
                    # Decode base64 to bytes
                    image_bytes = base64.b64decode(base64_data)
                    
                    # Create a file-like object
                    image_file = io.BytesIO(image_bytes)
                    image_file.name = 'qrcode.png'
                    
                    # Send as photo
                    await event.client.send_file(
                        event.chat_id,
                        image_file,
                        caption=message,
                        buttons=buttons,
                        parse_mode="html"
                    )
                    logger.info(f"Sent QR code as base64 image to user")
                    
                elif isinstance(qr_code, str) and qr_code.startswith(('http://', 'https://')):
                    # It's a URL - send as photo from URL
                    await event.client.send_file(
                        event.chat_id,
                        qr_code,
                        caption=message,
                        buttons=buttons,
                        parse_mode="html",
                        force_document=False  # Send as photo, not document
                    )
                    logger.info(f"Sent QR code from URL to user")
                else:
                    # Assume it's a file path or file ID
                    await event.client.send_file(
                        event.chat_id,
                        qr_code,
                        caption=message,
                        buttons=buttons,
                        parse_mode="html"
                    )
                    
            except Exception as e:
                logger.error(f"Failed to send QR code: {e}")
                # Fallback to text-only message
                await event.respond(message, buttons=buttons, parse_mode="html")
        else:
            # No QR code, send text only
            await event.respond(message, buttons=buttons, parse_mode="html")
    
    async def handle_check_status(self, event):
        """Handle check status button press."""
        data = event.data.decode()
        wallet = data.replace("check_", "")
        
        user_id = event.sender_id
        
        try:
            # Find deposit by wallet
            db = mongodb.db
            deposits_collection = db["deposits"]
            deposit = await deposits_collection.find_one({"wallet": wallet})
            
            if not deposit:
                await event.answer("Deposit not found", alert=True)
                return
            
            if deposit["status"] == DepositStatus.CONFIRMED:
                await event.answer(
                    f"✅ Deposit confirmed! Received: {deposit['received_amount']} USDT",
                    alert=True
                )
            elif deposit["status"] == DepositStatus.EXPIRED:
                await event.answer("⏰ This deposit has expired", alert=True)
            else:
                await event.answer("⏳ Still waiting for payment...", alert=True)
                
        except Exception as e:
            logger.error(f"Error checking status for wallet {wallet}: {e}")
            await event.answer("Error checking status", alert=True)
    
    async def notify_deposit_confirmed(self, user_id: int, amount: float, new_balance: float):
        """Notify user that deposit was confirmed."""
        try:
            from main import bot  # Import here to avoid circular import
            
            # Format amount based on decimal places
            if amount.is_integer():
                amount_str = f"{int(amount)}"
            else:
                amount_str = f"{amount:.2f}".rstrip('0').rstrip('.')
            
            if new_balance.is_integer():
                balance_str = f"{int(new_balance)}"
            else:
                balance_str = f"{new_balance:.2f}".rstrip('0').rstrip('.')
            
            message = (
                "<b>✅ Deposit Confirmed</b>\n\n"
                f"<b>Amount Received:</b> <code>{amount_str} USDT</code>\n\n"
                f"<b>Your new balance:</b>\n"
                f"<code>{balance_str} USDT</code>"
            )
            
            await bot.send_message(user_id, message, parse_mode="html")
            logger.info(f"Notified user {user_id} of confirmed deposit: {amount} USDT")
            
        except Exception as e:
            logger.error(f"Failed to notify user {user_id} about deposit: {e}")
    
    def _clear_user_state(self, user_id: int):
        """Clear user state data."""
        self._user_states.pop(user_id, None)
        self._user_amounts.pop(user_id, None)


# Singleton instance
deposit_handler = DepositHandler()
