from telethon import events, Button
from loguru import logger
from db.users import user_manager


class StartHandler:
    """Handle /start command and related interactions."""
    
    async def handle(self, event):
        """Handle /start command."""
        user_id = event.sender_id
        
        try:
            # Get or create user
            user = await user_manager.get_or_create_user(user_id)
            balance = user.get("balance", 0)
            
            # Create welcome message
            message = (
                "<b>💰 USDT Deposit Bot</b>\n\n"
                "Welcome to the secure USDT (BEP20) deposit bot!\n\n"
                f"<b>Your Balance:</b> <code>{balance:.2f} USDT</code>\n\n"
                "Press the button below to start a deposit."
            )
            
            # Create inline keyboard
            buttons = [
                [Button.inline("💳 Deposit", data="deposit")]
            ]
            
            await event.respond(message, buttons=buttons, parse_mode="html")
            logger.info(f"User {user_id} started the bot")
            
        except Exception as e:
            logger.error(f"Error in start handler for user {user_id}: {e}")
            await event.respond(
                "❌ An error occurred. Please try again later.",
                parse_mode="html"
            )
    
    async def handle_deposit_button(self, event):
        """Handle deposit button press."""
        # Forward to deposit handler
        from handlers.deposit import deposit_handler
        await deposit_handler.start_deposit(event)


# Singleton instance
start_handler = StartHandler()
