import os
from pydantic_settings import BaseSettings


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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Instantiate the settings
settings = Settings()
