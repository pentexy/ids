import os
from typing import Optional
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    """Application configuration."""
    
    # Telegram
    API_ID: int = int(os.getenv("API_ID", "0"))
    API_HASH: str = os.getenv("API_HASH", "")
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))
    
    # MongoDB
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    DB_NAME: str = os.getenv("DB_NAME", "usdt_bot")
    
    # API
    API_KEY: str = os.getenv("API_KEY", "")
    API_BASE_URL: str = os.getenv("API_BASE_URL", "http://195.35.21.153:3000/api")
    
    # Bot Settings
    DEPOSIT_EXPIRY_MINUTES: int = 30
    CHECK_INTERVAL_SECONDS: int = 20
    
    def validate(self) -> bool:
        """Validate required configuration."""
        required_vars = [
            self.API_ID, self.API_HASH, self.BOT_TOKEN,
            self.OWNER_ID, self.MONGO_URI, self.API_KEY
        ]
        return all(required_vars)


config = Config()
