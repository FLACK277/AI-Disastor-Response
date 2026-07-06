"""
AI Disaster Response Coordinator — Configuration
Loads settings from .env file using pydantic-settings.
"""

import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "AI Disaster Response Coordinator"
    DEBUG: bool = True

    # Groq LLM
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # JWT Auth
    JWT_SECRET: str = "disaster-response-2026-super-secret-key-change-in-prod"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480

    # Database
    DATABASE_URL: str = "sqlite:///./disaster_response.db"

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000,http://localhost:8000"

    # Mock Feed (disabled by default so production-like runs only show real reports)
    MOCK_FEED_INTERVAL: int = 25
    MOCK_FEED_ENABLED: bool = False

    # Geocoding
    GEOCODER_USER_AGENT: str = "disaster-response-coordinator"

    # Live Data Feed Cache
    LIVE_CACHE_TTL_SECONDS: int = 60  # 1 minute between live-source re-fetches
    CUTOFF_HOURS: int = 36  # hard freshness cutoff for news RSS items
    NEWS_CACHE_TTL_SECONDS: int = 300  # 5 minutes between Google News RSS fetches
    DEBUG_FILTERS: bool = False  # opt-in verbose per-item source filter diagnostics

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
