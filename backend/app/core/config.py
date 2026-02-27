"""ManuscriptReady — Configuration"""
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    APP_NAME: str = "ManuscriptReady"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = ""  # Required: set in .env
    API_PREFIX: str = "/api/v1"
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]
    DATABASE_URL: str = "postgresql+asyncpg://localhost/manuscriptready"
    JWT_SECRET: str = ""  # Required: set in .env
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_MINUTES: int = 10080
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_TEMPERATURE: float = 0.2
    OPENAI_MAX_TOKENS: int = 4096
    DEEPL_API_KEY: str = ""
    DEEPL_API_URL: str = "https://api-free.deepl.com/v2"
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_STARTER: str = ""
    STRIPE_PRICE_PRO: str = ""
    STRIPE_PRICE_TEAM: str = ""
    S3_ENDPOINT: str = ""
    S3_REGION: str = "us-east-1"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_BUCKET: str = "manuscriptready"
    SIGNED_URL_TTL_SECONDS: int = 3600
    MAX_INPUT_CHARS: int = 100_000
    CHUNK_SIZE: int = 2_000
    MAX_CONCURRENT: int = 5
    QUOTA_FREE: int = 1_000
    QUOTA_STARTER: int = 50_000
    QUOTA_PRO: int = 200_000
    QUOTA_TEAM: int = 1_000_000

    class Config:
        env_file = ".env"


settings = Settings()
