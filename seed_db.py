import json
import os
import sys
import pymongo
import logging
import ollama
from dotenv import load_dotenv
from app.core.config import settings  # Assumes this path is correct

# --- Configuration ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)

# Load .env variables
load_dotenv()

# --- Seeder/Generation Configuration ---
COLLECTION_NAME = "conviction_cases"
CASE_DATA_FILE = "input.json"
BOUNDARY_DATA_FILE = "odisha.geojson"
OLLAMA_MODEL = "gemma:2b"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================


def load_boundary_data(boundary_path: str) -> dict:
    """
    Loads the GeoJSON boundary file and converts it into a fast lookup dictionary.
    """
    if not os.path.exists(boundary_path):
        log.error(f"Error: {BOUNDARY_DATA_FILE} not found at {boundary_path}")
        return {}

    try:
        with open(boundary_path, "r", encoding="utf-8") as f:
            boundary_data = json.load(f)

        boundary_lookup = {}
        for feature in boundary_data.get("features", []):
            properties = feature.get("properties", {})
            district_name = properties.get("district")  # Key from your odisha.geojson
            if district_name:
                boundary_lookup[district_name.upper()] = feature.get("geometry")

        log.info(
            f"Loaded {len(boundary_lookup)} district boundaries from {BOUNDARY_DATA_FILE}."
        )
        return boundary_lookup
    except Exception as e:
        log.error(f"Error processing boundary file: {e}")
        return {}


def format_prompt_for_judgment(case_data: dict) -> str:
    """
    Constructs the prompt for the LLM using comprehensive case data.
    """
    final_result = case_data.get("Result", "N/A").upper()
    if final_result not in ["ACQUITTED", "CONVICTED"]:
        final_result = "N/A (Verdict Unclear)"

    prompt_lines = [
        "You are a meticulous and professional judge writing a final court judgment.",
        "Your task is to generate a formal, well-reasoned judgment based ONLY on the case data provided.",
        "You must adopt the persona of the presiding judge. Do not invent facts.",
        "\n" + "=" * 30 + "\n**CASE PRELIMINARIES**\n" + "=" * 30,
        f"* **Court:** {case_data.get('Court_Name', 'N/A')}",
        f"* **Presiding Judge:** {case_data.get('Judge_Name', 'N/A')}",
        f"* **Case Number:** {case_data.get('Case_Number', 'N/A')}",
        f"* **Police Station:** {case_data.get('Police_Station', 'N/A')}",
        "\n" + "=" * 30 + "\n**PARTIES INVOLVED**\n" + "=" * 30,
        f"* **Accused Name:** {case_data.get('Accused_Name', 'N/A')}",
        f"* **Accused Details:** {case_data.get('Accused_Details', 'N/A')}",
        f"* **Complainant/Informant:** {case_data.get('Complainant_Informant', 'N/A')}",
        f"* **Investigating Officer (IO):** {case_data.get('Investigating_Officer', 'N/A')} ({case_data.get('Rank', 'N/A')})",
        "\n" + "=" * 30 + "\n**CASE TIMELINE & CHARGES**\n" + "=" * 30,
        f"* **Date of Registration (FIR):** {case_data.get('Date_of_Registration', 'N/A')}",
        f"* **Date of Judgment:** {case_data.get('Date_of_Judgement', 'N/A')}",
        f"* **Sections at Final Chargesheet:** {case_data.get('Sections_at_Final', 'N/A')}",
        "\n" + "=" * 30 + "\n**PROSECUTION CASE & EVIDENCE**\n" + "=" * 30,
        f"* **Place of Occurrence:** {case_data.get('Place_of_Occurrence', 'N/A')}",
        f"* **FIR Contents / Prosecution Summary:** {case_data.get('FIR_Contents', 'No summary available.')}",
        f"* **Action Taken by IO:** {case_data.get('Action_Taken', 'No action log available.')}",
        "\n" + "=" * 30 + "\n**JUDGMENT INSTRUCTION**\n" + "=" * 30,
        f"**THE FINAL VERDICT IS PREDETERMINED: {final_result}**",
        "\nYour judgment *must* logically and legally justify this specific verdict.",
        "Analyze the available facts to build your reasoning.",
        f"Conclude with the final order, stating the verdict ({final_result}) and the legal reasoning for it.",
        "\nGenerate the full text of the judgment now.",
    ]

    return "\n".join(prompt_lines)


# =========================================================================
# MAIN SEEDER FUNCTION (Steps 1-4)
# =========================================================================


def seed_database_and_generate_judgments():
    """
    Connects to MongoDB, clears data, loads case data, merges coordinates,
    generates judgments for all entries, and inserts the complete records.
    CRITIQUE: This is a highly inefficient, unstable, and slow process.
    """
    client = None
    try:
        # 1. Connect to MongoDB
        log.info(f"Connecting to MongoDB at {settings.MONGO_URL}...")
        client = pymongo.MongoClient(settings.MONGO_URL)
        db = client[settings.MONGO_DB_NAME]
        collection = db[COLLECTION_NAME]
        client.server_info()
        log.info(f"Successfully connected to DB: {settings.MONGO_DB_NAME}")

        # 2. Clear existing data
        log.warning(f"Clearing ALL existing data from '{COLLECTION_NAME}'...")
        delete_result = collection.delete_many({})
        log.info(f"Cleared {delete_result.deleted_count} old records.")

        # 3. Load Geospatial Boundary Data
        base_dir = os.path.dirname(__file__)
        boundary_path = os.path.join(base_dir, BOUNDARY_DATA_FILE)
        boundary_lookup = load_boundary_data(boundary_path)

        # 4. Load Case Data from JSON
        data_path = os.path.join(base_dir, CASE_DATA_FILE)
        if not os.path.exists(data_path):
            log.error(f"Error: {CASE_DATA_FILE} not found at {data_path}")
            return
        with open(data_path, "r", encoding="utf-8") as f:
            case_data_list = json.load(f)
        log.info(f"Loaded {len(case_data_list)} records from {CASE_DATA_FILE}.")

        # 5. Initialize Ollama Client
        try:
            ollama_client = ollama.Client(host=OLLAMA_HOST)
            ollama_client.list()  # Test connection
            log.info(f"Successfully connected to Ollama at {OLLAMA_HOST}")
        except Exception as e:
            log.error(f"Failed to connect to Ollama: {e}")
            log.error("Aborting seed. Ollama must be running to generate judgments.")
            return

        # 6. Process Each Record (Merge, Generate, Store)
        data_to_insert = []
        missing_districts = set()

        log.info(f"Starting processing for {len(case_data_list)} records...")

        for i, case in enumerate(case_data_list):
            case_num = case.get("Case_Number", f"Record {i+1}")
            log.info(
                f"--- Processing Case: {case_num} ({i+1}/{len(case_data_list)}) ---"
            )

            # STEP 1 & 2: Get data and find coordinates
            district_name_from_case = case.get("District", "").upper()
            if district_name_from_case in boundary_lookup:
                case["border_coordinates"] = boundary_lookup[district_name_from_case]
            else:
                case["border_coordinates"] = None
                if district_name_from_case:
                    missing_districts.add(case.get("District"))

            # STEP 3: Generate judgment
            try:
                log.info(f"Generating judgment for {case_num}...")
                prompt = format_prompt_for_judgment(case)

                response = ollama_client.chat(
                    model=OLLAMA_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    stream=False,  # Must be False for a synchronous loop
                )

                judgment_text = response["message"]["content"]
                case["generated_judgment"] = judgment_text
                log.info(f"Successfully generated judgment for {case_num}.")

            except Exception as e:
                log.error(f"Failed to generate judgment for {case_num}: {e}")
                case["generated_judgment"] = f"Error: Generation failed. {e}"

            # Add the fully processed case to the insertion list
            data_to_insert.append(case)

        if missing_districts:
            log.warning(f"No boundary data found for districts: {missing_districts}")

        # STEP 4: Store all processed records in DB
        log.info(
            f"All records processed. Inserting {len(data_to_insert)} records into database..."
        )
        if data_to_insert:
            insert_result = collection.insert_many(data_to_insert)
            log.info(
                f"Successfully inserted {len(insert_result.inserted_ids)} new records."
            )
        else:
            log.error("No data to insert.")

        # 7. Create Geospatial Index
        log.info("Creating 2dsphere index on 'border_coordinates'...")
        collection.create_index([("border_coordinates", pymongo.GEOSPHERE)])
        log.info("Index created successfully.")

        log.info("Database seeding and judgment generation complete!")

    except pymongo.errors.ConfigurationError as e:
        log.error(f"MongoDB Configuration Error: {e}")
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}")
    finally:
        if client:
            client.close()
            log.info("Seeder: MongoDB connection closed.")


# =========================================================================
# SCRIPT EXECUTION
# =========================================================================

if __name__ == "__main__":
    """
    When this file is run, it will execute the entire
    seeding and generation process from start to finish.
    """
    log.info("Executing seeder and generation script...")
    seed_database_and_generate_judgments()
    log.info("Script finished.")
