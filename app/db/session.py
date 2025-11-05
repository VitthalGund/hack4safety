from pymongo import MongoClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
import logging


class DBConnections:
    mongo_client: MongoClient | None = None
    mongo_db = None
    pg_engine = None
    pg_session_local = None


db = DBConnections()


def connect_to_mongo():
    """Establishes connection to MongoDB."""
    logging.info("Connecting to MongoDB...")
    try:
        db.mongo_client = MongoClient(settings.MONGO_URL)
        db.mongo_db = db.mongo_client[settings.MONGO_DB_NAME]
        # Ping the server to confirm connection
        db.mongo_client.server_info()
        logging.info("Successfully connected to MongoDB.")
    except Exception as e:
        logging.error(f"Failed to connect to MongoDB: {e}")
        raise


def close_mongo_connection():
    """Closes MongoDB connection."""
    logging.info("Closing MongoDB connection...")
    if db.mongo_client:
        db.mongo_client.close()
    logging.info("MongoDB connection closed.")


def connect_to_postgres():
    """Establishes connection to PostgreSQL."""
    logging.info("Connecting to PostgreSQL...")
    try:
        db.pg_engine = create_async_engine(
            settings.POSTGRES_URL,
            pool_pre_ping=True,
            echo=False,
            connect_args={"ssl": "require"},
        )
        db.pg_session_local = sessionmaker(
            bind=db.pg_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        logging.info("Successfully connected to PostgreSQL engine.")
    except Exception as e:
        logging.error(f"Failed to connect to PostgreSQL: {e}")
        raise


async def close_postgres_connection():
    """Closes PostgreSQL connection."""
    logging.info("Closing PostgreSQL connection...")
    if db.pg_engine:
        await db.pg_engine.dispose()
    logging.info("PostgreSQL connection closed.")


async def get_pg_session() -> AsyncSession:
    """Dependency to get a new PostgreSQL session."""
    if not db.pg_session_local:
        raise Exception("PostgreSQL session not initialized.")

    async with db.pg_session_local() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_mongo_db():
    """Dependency to get the MongoDB database instance."""
    if not db.mongo_db:
        raise Exception("MongoDB connection not initialized.")
    return db.mongo_db
