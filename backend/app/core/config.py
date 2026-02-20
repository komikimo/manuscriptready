"""
ManuscriptReady — Central Configuration
"""
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    APP_NAME: str = "ManuscriptReady"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "change-in-production"
    API_PREFIX: str = "/api/v1"

    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173", "https://*.vercel.app"]

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./manuscriptready.db"

    # Auth
    JWT_SECRET: str = "change-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_MINUTES: int = 10080  # 7 days

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_TEMPERATURE: float = 0.2
    OPENAI_MAX_TOKENS: int = 4096

    # DeepL
    DEEPL_API_KEY: str = ""
    DEEPL_API_URL: str = "https://api-free.deepl.com/v2"

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_STARTER: str = ""
    STRIPE_PRICE_PRO: str = ""
    STRIPE_PRICE_TEAM: str = ""

    # Processing
    MAX_INPUT_CHARS: int = 100_000
    CHUNK_SIZE: int = 2_000
    MAX_CONCURRENT_CHUNKS: int = 5

    # Quotas (words/month)
    QUOTA_FREE: int = 1_000
    QUOTA_STARTER: int = 50_000
    QUOTA_PRO: int = 200_000
    QUOTA_TEAM: int = 1_000_000

    class Config:
        env_file = ".env"


settings = Settings()
