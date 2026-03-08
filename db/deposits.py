from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from enum import Enum
from loguru import logger
from db.mongo import mongodb
from config import config


class DepositStatus(str, Enum):
    """Deposit status enum."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    FAILED = "failed"


class DepositManager:
    """Manage deposit operations."""
    
    @staticmethod
    async def create_deposit(
        user_id: int,
        wallet: str,
        index: int,
        expected_amount: float,
        qr_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new deposit record.
        
        Args:
            user_id: Telegram user ID
            wallet: Deposit wallet address
            index: Wallet index
            expected_amount: Expected deposit amount
            qr_code: Optional QR code image URL
            
        Returns:
            Created deposit document
        """
        db = mongodb.db
        deposits_collection = db["deposits"]
        
        expiry_time = datetime.utcnow() + timedelta(minutes=config.DEPOSIT_EXPIRY_MINUTES)
        
        deposit = {
            "user_id": user_id,
            "wallet": wallet,
            "index": index,
            "expected_amount": expected_amount,
            "received_amount": 0.0,
            "status": DepositStatus.PENDING,
            "qr_code": qr_code,
            "created_at": datetime.utcnow(),
            "expires_at": expiry_time,
            "updated_at": datetime.utcnow()
        }
        
        await deposits_collection.insert_one(deposit)
        logger.info(f"Created deposit for user {user_id}: {wallet} ({expected_amount} USDT)")
        
        return deposit
    
    @staticmethod
    async def get_pending_deposits() -> List[Dict[str, Any]]:
        """Get all pending deposits."""
        db = mongodb.db
        deposits_collection = db["deposits"]
        
        cursor = deposits_collection.find({
            "status": DepositStatus.PENDING,
            "expires_at": {"$gt": datetime.utcnow()}
        })
        
        return await cursor.to_list(length=None)
    
    @staticmethod
    async def get_user_pending_deposit(user_id: int) -> Optional[Dict[str, Any]]:
        """Get user's pending deposit."""
        db = mongodb.db
        deposits_collection = db["deposits"]
        
        return await deposits_collection.find_one({
            "user_id": user_id,
            "status": DepositStatus.PENDING,
            "expires_at": {"$gt": datetime.utcnow()}
        })
    
    @staticmethod
    async def update_deposit_status(
        wallet: str,
        status: DepositStatus,
        received_amount: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Update deposit status.
        
        Args:
            wallet: Deposit wallet address
            status: New status
            received_amount: Optional received amount
            
        Returns:
            Updated deposit document
        """
        db = mongodb.db
        deposits_collection = db["deposits"]
        
        update_data = {
            "status": status,
            "updated_at": datetime.utcnow()
        }
        
        if received_amount is not None:
            update_data["received_amount"] = received_amount
        
        deposit = await deposits_collection.find_one_and_update(
            {"wallet": wallet},
            {"$set": update_data},
            return_document=True
        )
        
        if deposit:
            logger.info(f"Updated deposit {wallet} status to {status}")
        
        return deposit
    
    @staticmethod
    async def expire_old_deposits():
        """Mark expired deposits."""
        db = mongodb.db
        deposits_collection = db["deposits"]
        
        result = await deposits_collection.update_many(
            {
                "status": DepositStatus.PENDING,
                "expires_at": {"$lte": datetime.utcnow()}
            },
            {
                "$set": {
                    "status": DepositStatus.EXPIRED,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        if result.modified_count > 0:
            logger.info(f"Expired {result.modified_count} deposits")
        
        return result.modified_count


# Singleton instance
deposit_manager = DepositManager()
