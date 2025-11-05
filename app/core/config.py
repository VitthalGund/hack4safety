import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Global application settings. Reads from environment variables.
    """

    MONGO_URL: str = (
        "mongodb+srv://FS21CO044:ChS71cr4i2ufjtUf@clustervitthal.xgo6tok.mongodb.net/"
    )
    MONGO_DB_NAME: str = "conviction_db"

    POSTGRES_URL: str = (
        "postgresql://fs21co044.vitthal:cN74hXgdIbMo@ep-black-tree-05689440-pooler.ap-southeast-1.aws.neon.tech/neondb"
    )

    JWT_SECRET_KEY: str = (
        "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    class Config:
        # This allows reading from a .env file if you create one
        env_file = ".env"
        env_file_encoding = "utf-8"


# Create a single, importable settings instance
settings = Settings()
