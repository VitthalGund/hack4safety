import json
import os
import pymongo
import logging
from app.core.config import settings  # Import settings from your app

# Set up basic logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Define the collection name, same as in your cases.py
COLLECTION_NAME = "conviction_cases"
DATA_FILE = "data.json"  # Assumes data.json is in the same 'backend' directory


def seed_database():
    """
    Connects to MongoDB, clears the existing conviction data,
    and inserts all records from data.json.
    """
    try:
        # 1. Connect to MongoDB using settings from your config
        log.info(f"Connecting to MongoDB at {settings.MONGO_URL}...")
        client = pymongo.MongoClient(settings.MONGO_URL)
        db = client[settings.MONGO_DB_NAME]
        collection = db[COLLECTION_NAME]
        log.info(f"Successfully connected to DB: {settings.MONGO_DB_NAME}")

        # 2. Clear existing data to prevent duplicates
        log.warning(
            f"Clearing ALL existing data from '{COLLECTION_NAME}' collection..."
        )
        delete_result = collection.delete_many({})
        log.info(f"Cleared {delete_result.deleted_count} old records.")

        # 3. Load data from JSON file
        data_path = os.path.join(os.path.dirname(__file__), DATA_FILE)
        if not os.path.exists(data_path):
            log.error(f"Error: {DATA_FILE} not found at {data_path}")
            log.error("Please place data.json in the 'backend' directory.")
            return

        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            log.info(f"Loaded {len(data)} records from {DATA_FILE}.")

        # 4. Insert new data
        if isinstance(data, list) and len(data) > 0:
            insert_result = collection.insert_many(data)
            log.info(
                f"Successfully inserted {len(insert_result.inserted_ids)} new records."
            )
        else:
            log.error("Data is not a list or is empty. No records inserted.")

        log.info("Database seeding complete!")

    except pymongo.errors.ConfigurationError as e:
        log.error(f"MongoDB Configuration Error: {e}")
        log.error("Make sure your .env file is correct and MongoDB is running.")
    except Exception as e:
        log.error(f"An error occurred: {e}")
    finally:
        if "client" in locals():
            client.close()


if __name__ == "__main__":
    seed_database()
