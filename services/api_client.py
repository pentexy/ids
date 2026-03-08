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
    ) -> Tuple[int, Any]:
        """
        Make HTTP request with retry logic.
        
        Returns:
            Tuple of (status_code, response_data)
        """
        await self._ensure_session()
        url = f"{self.base_url}{endpoint}"
        
        try:
            logger.debug(f"Making {method} request to {url}")
            async with self.session.request(method, url, **kwargs) as response:
                try:
                    data = await response.json()
                except:
                    data = await response.text()
                
                if response.status >= 400:
                    logger.error(f"API error {response.status}: {data}")
                    raise APIResponseError(f"API returned {response.status}: {data}")
                
                logger.debug(f"API response: {data}")
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
            API response with wallet details (normalized format)
        """
        try:
            status, data = await self._make_request(
                "GET",
                f"/generate?amount={amount}"
            )
            
            logger.info(f"Generate wallet raw response: {data}")
            
            # Normalize the response to our expected format
            normalized_data = self._normalize_wallet_response(data)
            
            logger.info(f"Generated wallet {normalized_data['wallet']} for amount {amount}")
            return normalized_data
            
        except Exception as e:
            logger.error(f"Failed to generate wallet: {e}")
            raise
    
    async def check_payment(self, wallet: str) -> Dict[str, Any]:
        """
        Check if payment received for wallet.
        
        Args:
            wallet: Deposit wallet address
            
        Returns:
            Payment status response (normalized format)
        """
        try:
            status, data = await self._make_request(
                "GET",
                f"/check/{wallet}"
            )
            
            logger.debug(f"Check payment raw response for {wallet}: {data}")
            
            # Normalize the response
            normalized_data = self._normalize_check_response(data)
            
            return normalized_data
            
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
            
            logger.info(f"Withdraw raw response: {data}")
            
            # Normalize the response
            normalized_data = self._normalize_withdraw_response(data)
            
            logger.info(f"Withdrawal successful: {amount} USDT from {from_wallet}")
            return normalized_data
            
        except Exception as e:
            logger.error(f"Failed to process withdrawal: {e}")
            raise
    
    def _normalize_wallet_response(self, data: Any) -> Dict[str, Any]:
        """
        Normalize wallet generation response to expected format.
        
        Expected format: { "wallet": "...", "index": 123, "qr": "..." }
        """
        if isinstance(data, dict):
            # Check if the response has the fields we need
            result = {}
            
            # Try to find wallet address (could be 'wallet', 'address', 'wallet_address', etc.)
            wallet = (
                data.get("wallet") or 
                data.get("address") or 
                data.get("wallet_address") or 
                data.get("deposit_address")
            )
            if not wallet:
                # If it's a nested structure, try to find it
                for key in ["data", "result", "response"]:
                    if key in data and isinstance(data[key], dict):
                        wallet = (
                            data[key].get("wallet") or 
                            data[key].get("address") or 
                            data[key].get("wallet_address")
                        )
                        if wallet:
                            result.update(data[key])
                            break
            
            if not wallet:
                raise APIResponseError("Could not find wallet address in response")
            
            result["wallet"] = wallet
            
            # Try to find index
            result["index"] = data.get("index") or result.get("index") or 0
            
            # Try to find QR code
            result["qr"] = data.get("qr") or result.get("qr") or data.get("qrcode") or data.get("qr_code")
            
            return result
        
        elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            # If response is an array, take first item
            return self._normalize_wallet_response(data[0])
        
        else:
            raise APIResponseError(f"Unexpected response format: {type(data)}")
    
    def _normalize_check_response(self, data: Any) -> Dict[str, Any]:
        """
        Normalize payment check response to expected format.
        
        Expected format: { "funded": bool, "amount": float }
        """
        if isinstance(data, dict):
            result = {}
            
            # Check for funded status (could be 'funded', 'paid', 'confirmed', 'status')
            funded = (
                data.get("funded") or 
                data.get("paid") or 
                data.get("confirmed") or 
                data.get("status") == "confirmed" or
                data.get("status") == "paid"
            )
            result["funded"] = bool(funded)
            
            # Try to find amount
            amount = (
                data.get("amount") or 
                data.get("received_amount") or 
                data.get("value") or
                0
            )
            
            # Try to convert to float
            try:
                result["amount"] = float(amount) if amount else 0
            except (ValueError, TypeError):
                result["amount"] = 0
            
            return result
        
        elif isinstance(data, list) and len(data) > 0:
            return self._normalize_check_response(data[0])
        
        elif isinstance(data, bool):
            # If API returns just a boolean
            return {"funded": data, "amount": 0}
        
        elif isinstance(data, str):
            # If API returns a status string
            return {"funded": data.lower() in ["confirmed", "paid", "true", "yes"], "amount": 0}
        
        else:
            logger.warning(f"Unexpected check response format: {data}")
            return {"funded": False, "amount": 0}
    
    def _normalize_withdraw_response(self, data: Any) -> Dict[str, Any]:
        """
        Normalize withdraw response to expected format.
        
        Expected format: { "txid": "..." } or { "transaction": "..." }
        """
        if isinstance(data, dict):
            result = {}
            
            # Try to find transaction hash
            txid = (
                data.get("txid") or 
                data.get("transaction") or 
                data.get("tx") or 
                data.get("hash") or
                data.get("transaction_hash")
            )
            
            if txid:
                result["txid"] = txid
                result["transaction"] = txid
            else:
                # If no transaction hash, maybe it's in a nested structure
                for key in ["data", "result"]:
                    if key in data and isinstance(data[key], dict):
                        txid = (
                            data[key].get("txid") or 
                            data[key].get("transaction") or 
                            data[key].get("hash")
                        )
                        if txid:
                            result["txid"] = txid
                            result["transaction"] = txid
                            break
            
            return result
        
        elif isinstance(data, str):
            # If API returns just the transaction hash
            return {"txid": data, "transaction": data}
        
        else:
            logger.warning(f"Unexpected withdraw response format: {data}")
            return {"txid": "unknown", "transaction": "unknown"}


# Singleton instance
api_client = APIClient()
