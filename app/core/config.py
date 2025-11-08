import os
from pydantic_settings import BaseSettings
from pydantic import AnyUrl
from typing import List, Optional


class Settings(BaseSettings):
    """
    Global application settings. Reads from environment variables.
    """

    MONGO_URL: str
    MONGO_DB_NAME: str
    POSTGRES_URL: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    DEFAULT_ADMIN_USER: str = "admin"
    DEFAULT_ADMIN_PASS: str = "admin_password123"
    PROJECT_NAME: str = "Quantum-Safe Conviction Data Management"

    # --- FIX: Added Refresh Token settings ---
    JWT_SECRET_KEY: str = os.environ.get(
        "JWT_SECRET_KEY", "your_strong_secret_key_here"
    )
    JWT_REFRESH_SECRET_KEY: str = os.environ.get(
        "JWT_REFRESH_SECRET_KEY", "your_strong_refresh_secret_key_here"
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 130
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Default Admin
    DEFAULT_ADMIN_USER: str = os.environ.get("DEFAULT_ADMIN_USER", "admin")
    DEFAULT_ADMIN_PASS: str = os.environ.get("DEFAULT_ADMIN_PASS", "admin_password123")

    # CORS
    BACKEND_CORS_ORIGINS: List[AnyUrl] = [
        "http://localhost:3000",
        "http://localhost:8000",
    ]

    # RAG Service (example, adjust as needed)
    QDRANT_URL: str = os.environ.get("QDRANT_URL", "http://localhost:6333")
    QDRANT_API_KEY: Optional[str] = os.environ.get("QDRANT_API_KEY", None)
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"

    GOOGLE_GEMINI_API_KEY: Optional[str] = os.environ.get("GEMINI_API_KEY", None)

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
