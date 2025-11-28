import asyncio
import logging
from notifications.utils import make_rest_request

# Configure logging
logging.basicConfig(level=logging.INFO)

async def test():
    print("Testing connection to google.com...")
    response = await make_rest_request({}, "https://www.google.com", "GET")
    if response:
        print(f"Success! Status: {response.status_code}")
    else:
        print("Failed to connect.")

if __name__ == "__main__":
    asyncio.run(test())
