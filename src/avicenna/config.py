import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Application configuration."""
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

    @classmethod
    def validate(cls):
        """Validate critical configuration."""
        if not cls.GOOGLE_API_KEY:
            raise ValueError(
                "GOOGLE_API_KEY not found. Please set it in the .env file."
            )
