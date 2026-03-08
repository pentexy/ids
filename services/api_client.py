from typing import Optional, Dict, Any, Tuple
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from loguru import logger
from config import config


class APIClientError(Exception):
    """API Client base exception."""
    pass


class APIRequestError(APIClientError):
    """API request failed."""
    pass


class APIResponseError(APIClientError):
    """API returned error response."""
    pass


class APIClient:
    """Async API client for deposit service."""
    
    def __init__(self):
        self.base_url = config.API_BASE_URL
        self.api_key = config.API_KEY
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        await self._ensure_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def _ensure_session(self):
        """Ensure aiohttp session exists."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json"
                },
                timeout=aiohttp.ClientTimeout(total=30)
            )
    
    async def close(self):
        """Close session."""
        if self.session and not self.session.closed:
            await self.session.close()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, TimeoutError)),
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying API call (attempt {retry_state.attempt_number})"
        )
    )
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Tuple[int, Dict[str, Any]]:
        """
        Make HTTP request with retry logic.
        
        Returns:
            Tuple of (status_code, response_data)
        """
        await self._ensure_session()
        url = f"{self.base_url}{endpoint}"
        
        try:
            async with self.session.request(method, url, **kwargs) as response:
                try:
                    data = await response.json()
                except:
                    data = await response.text()
                
                if response.status >= 400:
                    logger.error(f"API error {response.status}: {data}")
                    raise APIResponseError(f"API returned {response.status}: {data}")
                
                return response.status, data
                
        except aiohttp.ClientError as e:
            logger.error(f"Request failed: {e}")
            raise APIRequestError(f"Request failed: {e}")
    
    async def generate_wallet(self, amount: float) -> Dict[str, Any]:
        """
        Generate deposit wallet.
        
        Args:
            amount: Expected deposit amount
            
        Returns:
            API response with wallet details
        """
        try:
            status, data = await self._make_request(
                "GET",
                f"/generate?amount={amount}"
            )
            
            if not isinstance(data, dict):
                raise APIResponseError("Invalid response format")
            
            required_fields = ["wallet", "index", "qr"]
            if not all(field in data for field in required_fields):
                raise APIResponseError(f"Missing required fields: {required_fields}")
            
            logger.info(f"Generated wallet {data['wallet']} for amount {amount}")
            return data
            
        except Exception as e:
            logger.error(f"Failed to generate wallet: {e}")
            raise
    
    async def check_payment(self, wallet: str) -> Dict[str, Any]:
        """
        Check if payment received for wallet.
        
        Args:
            wallet: Deposit wallet address
            
        Returns:
            Payment status response
        """
        try:
            status, data = await self._make_request(
                "GET",
                f"/check/{wallet}"
            )
            
            if not isinstance(data, dict):
                raise APIResponseError("Invalid response format")
            
            return data
            
        except Exception as e:
            logger.error(f"Failed to check payment for {wallet}: {e}")
            raise
    
    async def withdraw(
        self,
        from_wallet: str,
        to_wallet: str,
        amount: float
    ) -> Dict[str, Any]:
        """
        Withdraw funds from deposit wallet.
        
        Args:
            from_wallet: Source wallet address
            to_wallet: Destination wallet address
            amount: Amount to withdraw
            
        Returns:
            Withdrawal response with transaction hash
        """
        try:
            payload = {
                "from": from_wallet,
                "to": to_wallet,
                "amount": amount
            }
            
            status, data = await self._make_request(
                "POST",
                "/withdraw",
                json=payload
            )
            
            if not isinstance(data, dict):
                raise APIResponseError("Invalid response format")
            
            if "txid" not in data and "transaction" not in data:
                raise APIResponseError("Missing transaction hash in response")
            
            logger.info(f"Withdrawal successful: {amount} USDT from {from_wallet}")
            return data
            
        except Exception as e:
            logger.error(f"Failed to process withdrawal: {e}")
            raise


# Singleton instance
api_client = APIClient()
