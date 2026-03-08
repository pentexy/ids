import asyncio
from typing import Optional
from loguru import logger
from db.deposits import deposit_manager, DepositStatus
from db.users import user_manager
from services.api_client import api_client, APIRequestError, APIResponseError
from config import config
from handlers.owner import owner_notifier


class DepositChecker:
    """Background task to check for confirmed deposits."""
    
    def __init__(self):
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the deposit checker background task."""
        if self.is_running:
            return
        
        self.is_running = True
        self.task = asyncio.create_task(self._check_loop())
        logger.info("Deposit checker started")
    
    async def stop(self):
        """Stop the deposit checker background task."""
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Deposit checker stopped")
    
    async def _check_loop(self):
        """Main checking loop."""
        while self.is_running:
            try:
                await self._check_pending_deposits()
                await asyncio.sleep(config.CHECK_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in deposit checker loop: {e}")
                await asyncio.sleep(5)  # Short delay on error
    
    async def _check_pending_deposits(self):
        """Check all pending deposits."""
        try:
            # First, expire old deposits
            await deposit_manager.expire_old_deposits()
            
            # Get pending deposits
            deposits = await deposit_manager.get_pending_deposits()
            
            if not deposits:
                return
            
            logger.debug(f"Checking {len(deposits)} pending deposits")
            
            for deposit in deposits:
                await self._check_single_deposit(deposit)
                
        except Exception as e:
            logger.error(f"Failed to check pending deposits: {e}")
    
    async def _check_single_deposit(self, deposit: dict):
        """Check a single deposit for payment."""
        wallet = deposit["wallet"]
        user_id = deposit["user_id"]
        
        try:
            # Check payment status via API
            payment_data = await api_client.check_payment(wallet)
            
            # Check if payment received
            if payment_data.get("funded", False):
                received_amount = payment_data.get("amount", deposit["expected_amount"])
                
                logger.info(f"Payment confirmed for wallet {wallet}: {received_amount} USDT")
                
                # Update deposit status
                await deposit_manager.update_deposit_status(
                    wallet,
                    DepositStatus.CONFIRMED,
                    received_amount
                )
                
                # Update user balance
                new_balance = await user_manager.update_balance(user_id, received_amount)
                
                # Notify user and owner
                from handlers.deposit import deposit_handler
                await deposit_handler.notify_deposit_confirmed(
                    user_id,
                    received_amount,
                    new_balance
                )
                
                await owner_notifier.notify_new_deposit(
                    user_id,
                    wallet,
                    received_amount
                )
                
        except (APIRequestError, APIResponseError) as e:
            logger.error(f"API error checking deposit {wallet}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error checking deposit {wallet}: {e}")


# Singleton instance
deposit_checker = DepositChecker()
