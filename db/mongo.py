from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from loguru import logger
from config import config


class MongoDB:
    """MongoDB connection manager."""
    
    _instance: Optional["MongoDB"] = None
    _client: Optional[AsyncIOMotorClient] = None
    _db: Optional[AsyncIOMotorDatabase] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def connect(self):
        """Establish connection to MongoDB."""
        try:
            self._client = AsyncIOMotorClient(
                config.MONGO_URI,
                maxPoolSize=10,
                minPoolSize=1
            )
            self._db = self._client[config.DB_NAME]
            
            # Test connection
            await self._client.admin.command('ping')
            logger.info("Connected to MongoDB")
            
            # Create indexes
            await self._create_indexes()
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    
    async def _create_indexes(self):
        """Create necessary database indexes."""
        try:
            # Users collection indexes
            users = self._db["users"]
            await users.create_index("user_id", unique=True)
            await users.create_index("created_at")
            
            # Deposits collection indexes
            deposits = self._db["deposits"]
            await deposits.create_index("wallet", unique=True)
            await deposits.create_index([("user_id", 1), ("status", 1)])
            await deposits.create_index("created_at")
            await deposits.create_index("status")
            
            logger.info("Database indexes created successfully")
        except Exception as e:
            logger.error(f"Failed to create indexes: {e}")
    
    @property
    def db(self) -> AsyncIOMotorDatabase:
        """Get database instance."""
        if self._db is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db
    
    async def close(self):
        """Close database connection."""
        if self._client:
            self._client.close()
            logger.info("MongoDB connection closed")


# Singleton instance
mongodb = MongoDB()
