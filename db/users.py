from datetime import datetime
from typing import Optional, Dict, Any
from loguru import logger
from db.mongo import mongodb


class UserManager:
    """Manage user operations."""
    
    @staticmethod
    async def get_or_create_user(user_id: int) -> Dict[str, Any]:
        """
        Get existing user or create new one.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            User document
        """
        db = mongodb.db
        users_collection = db["users"]
        
        user = await users_collection.find_one({"user_id": user_id})
        
        if not user:
            user = {
                "user_id": user_id,
                "balance": 0.0,
                "created_at": datetime.utcnow(),
                "total_deposits": 0,
                "total_withdrawals": 0
            }
            
            await users_collection.insert_one(user)
            logger.info(f"Created new user: {user_id}")
        
        return user
    
    @staticmethod
    async def get_balance(user_id: int) -> float:
        """Get user balance."""
        db = mongodb.db
        users_collection = db["users"]
        
        user = await users_collection.find_one(
            {"user_id": user_id},
            projection={"balance": 1}
        )
        
        return user.get("balance", 0.0) if user else 0.0
    
    @staticmethod
    async def update_balance(user_id: int, amount: float) -> float:
        """
        Update user balance.
        
        Args:
            user_id: Telegram user ID
            amount: Amount to add (positive) or subtract (negative)
            
        Returns:
            New balance
        """
        db = mongodb.db
        users_collection = db["users"]
        
        result = await users_collection.find_one_and_update(
            {"user_id": user_id},
            {"$inc": {"balance": amount}},
            projection={"balance": 1},
            return_document=True
        )
        
        if not result:
            raise ValueError(f"User {user_id} not found")
        
        logger.info(f"Updated balance for user {user_id}: +{amount} = {result['balance']}")
        return result["balance"]
    
    @staticmethod
    async def get_all_users() -> list:
        """Get all users."""
        db = mongodb.db
        users_collection = db["users"]
        
        cursor = users_collection.find({})
        return await cursor.to_list(length=None)


user_manager = UserManager()
