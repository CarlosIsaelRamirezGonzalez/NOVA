import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    XAI_API_KEY = os.getenv("XAI_API_KEY")
    CHAT_API_URL = os.getenv("CHAT_API_URL")
    TTS_API_URL = os.getenv("TTS_API_URL")
