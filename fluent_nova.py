from dotenv import load_dotenv
from mcp import os

load_dotenv()  # Load environment variables from .env file


headers = {
    "Authorization": f"Bearer {os.getenv('XAI_API_KEY')}",
    "Content-Type": "application/json",
}


