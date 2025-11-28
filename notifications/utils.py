import httpx
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

async def make_rest_request(
    headers: Dict[str, str], 
    url: str, 
    method: str, 
    data: Optional[Dict[str, Any]] = None
) -> Optional[httpx.Response]:
    """
    Make an async HTTP request using httpx.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(method, url, headers=headers, json=data)
            return response
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return None
