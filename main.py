#!/usr/bin/env python3
"""
USDT Deposit Bot - Main Entry Point
Production-ready Telegram bot for USDT (BEP20) deposits
"""

import asyncio
import sys
from typing import Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from loguru import logger

from config import config
from db.mongo import mongodb
from db.users import user_manager
from db.deposits import deposit_manager
from services.deposit_checker import deposit_checker
from handlers.start import start_handler
from handlers.deposit import deposit_handler
from handlers.owner import owner_notifier
from utils.logger import logger


class USDTDepositBot:
    """Main bot class."""
    
    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self.is_running = False
        
        # Validate configuration
        if not config.validate():
            logger.error("Invalid configuration. Please check your .env file.")
            sys.exit(1)
    
    async def start(self):
        """Start the bot."""
        try:
            # Initialize Telegram client
            self.client = TelegramClient(
                StringSession(),
                config.API_ID,
                config.API_HASH
            )
            
            # Connect to Telegram
            await self.client.start(bot_token=config.BOT_TOKEN)
            logger.info(f"Bot started as @{(await self.client.get_me()).username}")
            
            # Connect to MongoDB
            await mongodb.connect()
            
            # Register event handlers
            self._register_handlers()
            
            # Start background tasks
            await deposit_checker.start()
            
            self.is_running = True
            logger.info("Bot is running. Press Ctrl+C to stop.")
            
            # Keep the bot running
            await self.client.run_until_disconnected()
            
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            await self.stop()
            sys.exit(1)
    
    def _register_handlers(self):
        """Register all event handlers."""
        if not self.client:
            return
        
        # /start command
        @self.client.on(events.NewMessage(pattern=r'^/start$'))
        async def start_handler_func(event):
            await start_handler.handle(event)
        
        # Handle callback queries (inline buttons)
        @self.client.on(events.CallbackQuery)
        async def callback_handler(event):
            data = event.data.decode()
            
            if data == "deposit":
                await start_handler.handle_deposit_button(event)
            elif data.startswith("check_"):
                await deposit_handler.handle_check_status(event)
        
        # Handle regular messages (amount input)
        @self.client.on(events.NewMessage)
        async def message_handler(event):
            # Ignore commands
            if event.message.text and event.message.text.startswith('/'):
                return
            
            # Try to handle as deposit amount
            if await deposit_handler.handle_amount(event):
                return
            
            # Check if it's a reply from owner
            if event.sender_id == config.OWNER_ID:
                await owner_notifier.handle_withdraw_reply(event)
        
        # Handle owner-only commands (optional)
        @self.client.on(events.NewMessage(pattern=r'^/stats$'))
        async def stats_handler(event):
            if event.sender_id != config.OWNER_ID:
                return
            
            try:
                # Get stats
                db = mongodb.db
                users_count = await db["users"].count_documents({})
                deposits_count = await db["deposits"].count_documents({})
                pending_count = await db["deposits"].count_documents({
                    "status": "pending"
                })
                
                # Calculate total volume
                pipeline = [
                    {"$match": {"status": "confirmed"}},
                    {"$group": {"_id": None, "total": {"$sum": "$received_amount"}}}
                ]
                result = await db["deposits"].aggregate(pipeline).to_list(1)
                total_volume = result[0]["total"] if result else 0
                
                stats_message = (
                    "<b>📊 Bot Statistics</b>\n\n"
                    f"<b>Users:</b> <code>{users_count}</code>\n"
                    f"<b>Total Deposits:</b> <code>{deposits_count}</code>\n"
                    f"<b>Pending Deposits:</b> <code>{pending_count}</code>\n"
                    f"<b>Total Volume:</b> <code>{total_volume:.2f} USDT</code>"
                )
                
                await event.respond(stats_message, parse_mode="html")
                
            except Exception as e:
                logger.error(f"Error generating stats: {e}")
                await event.respond("❌ Error generating statistics")
        
        logger.info("Event handlers registered")
    
    async def stop(self):
        """Stop the bot and clean up."""
        logger.info("Stopping bot...")
        
        # Stop background tasks
        await deposit_checker.stop()
        
        # Close database connection
        await mongodb.close()
        
        # Disconnect Telegram client
        if self.client:
            await self.client.disconnect()
        
        self.is_running = False
        logger.info("Bot stopped")


async def main():
    """Main entry point."""
    bot = USDTDepositBot()
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
