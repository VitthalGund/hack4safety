import json
import os
import sys
import logging
import ollama
import traceback
from dotenv import load_dotenv
from langchain_core.documents import Document
from qdrant_client import QdrantClient, models
from langchain_qdrant import Qdrant
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# --- Project Imports ---
# Ensure this script is run from the project root
# or that 'app' is in the Python path
try:
    from app.core.config import settings
    from app.core.embedding import embeddings_client, EMBEDDING_DIMENSIONS
except ImportError:
    logging.error(
        "Failed to import app modules. Ensure you are running this script from the project root."
    )
    sys.exit(1)

# --- Configuration ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)

# Load .env variables
load_dotenv()

# --- Qdrant Configuration ---
QDRANT_URL = settings.QDRANT_URL
QDRANT_API_KEY = settings.QDRANT_API_KEY

# --- Legal Corpus (Bot 1) ---
LEGAL_CORPUS_PATH = "./legal_corpus"
LEGAL_COLLECTION_NAME = "legal_vectors"  # For the legal bot

# --- Case Data (Bot 2) ---
CASE_DATA_FILE = "input.json"
BOUNDARY_DATA_FILE = "odisha.geojson"
CASE_COLLECTION_NAME = "conviction_cases"  # For the case bot
OLLAMA_MODEL = "gemma:2b"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


# =========================================================================
# HELPER FUNCTIONS (Copied from old seed_db.py)
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
            district_name = properties.get("district")
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
# PIPELINE 1: LEGAL CORPUS INGESTION (for Legal Bot)
# =========================================================================


def ingest_legal_corpus(client: QdrantClient):
    """
    Reads PDFs from legal_corpus, splits them, and stores embeddings in Qdrant.
    """
    try:
        # 1. (Re)create Qdrant collection
        log.info(f"--- Starting Legal Corpus Ingestion ---")
        log.info(f"Re-creating Qdrant collection: {LEGAL_COLLECTION_NAME}...")
        client.recreate_collection(
            collection_name=LEGAL_COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=EMBEDDING_DIMENSIONS,
                distance=models.Distance.COSINE,
            ),
        )
        log.info(f"Collection '{LEGAL_COLLECTION_NAME}' created.")

        # 2. Load documents
        log.info(f"Loading documents from {LEGAL_CORPUS_PATH}...")
        loader = PyPDFDirectoryLoader(LEGAL_CORPUS_PATH, recursive=True)
        documents = loader.load()
        if not documents:
            log.error(f"No PDF documents found in {LEGAL_CORPUS_PATH}. Skipping.")
            return
        log.info(f"Loaded {len(documents)} document pages.")

        # 3. Split documents
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=150
        )
        chunks = text_splitter.split_documents(documents)
        log.info(f"Created {len(chunks)} text chunks.")

        # 4. Ingest data into Qdrant
        log.info(f"Embedding and ingesting chunks into {LEGAL_COLLECTION_NAME}...")
        Qdrant.from_documents(
            documents=chunks,
            embedding=embeddings_client,
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY,
            collection_name=LEGAL_COLLECTION_NAME,
            prefer_grpc=True,
            batch_size=64,
        )
        log.info(f"--- Finished Legal Corpus Ingestion ---")

    except Exception as e:
        log.error(f"Error ingesting legal corpus: {e}")
        traceback.print_exc()


# =========================================================================
# PIPELINE 2: CASE DATA INGESTION (for Case Bot)
# =========================================================================


def ingest_case_data(client: QdrantClient):
    """
    Loads raw case data, generates judgments, and ingests into Qdrant.
    """
    try:
        log.info(f"--- Starting Case Data Ingestion ---")

        # 1. Load Geospatial Boundary Data
        base_dir = os.path.dirname(os.path.abspath(__file__))
        boundary_path = os.path.join(base_dir, BOUNDARY_DATA_FILE)
        boundary_lookup = load_boundary_data(boundary_path)

        # 2. Load Case Data from JSON
        data_path = os.path.join(base_dir, CASE_DATA_FILE)
        if not os.path.exists(data_path):
            log.error(f"Error: {CASE_DATA_FILE} not found at {data_path}")
            return
        with open(data_path, "r", encoding="utf-8") as f:
            case_data_list = json.load(f)
        log.info(f"Loaded {len(case_data_list)} records from {CASE_DATA_FILE}.")

        # 3. Initialize Ollama Client
        try:
            ollama_client = ollama.Client(host=OLLAMA_HOST)
            ollama_client.list()
            log.info(f"Successfully connected to Ollama at {OLLAMA_HOST}")
        except Exception as e:
            log.error(f"Failed to connect to Ollama: {e}")
            log.error("Aborting case ingestion. Ollama must be running.")
            return

        # 4. (Re)create Qdrant collection
        log.info(f"Re-creating Qdrant collection: {CASE_COLLECTION_NAME}...")
        client.recreate_collection(
            collection_name=CASE_COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=EMBEDDING_DIMENSIONS,
                distance=models.Distance.COSINE,
            ),
        )
        log.info(f"Collection '{CASE_COLLECTION_NAME}' created.")

        # 5. Process Each Record and Prepare for Batch Ingestion
        log.info(f"Starting judgment generation for {len(case_data_list)} records...")
        documents_to_ingest = []
        missing_districts = set()

        for i, case in enumerate(case_data_list):
            case_num = case.get("Case_Number", f"Record {i+1}")
            log.info(f"Processing Case: {case_num} ({i+1}/{len(case_data_list)})")

            # 5a. Merge coordinates
            district_name_from_case = case.get("District", "").upper()
            if district_name_from_case in boundary_lookup:
                case["border_coordinates"] = boundary_lookup[district_name_from_case]
            else:
                case["border_coordinates"] = None
                if district_name_from_case:
                    missing_districts.add(case.get("District"))

            # 5b. Generate judgment
            try:
                prompt = format_prompt_for_judgment(case)
                response = ollama_client.chat(
                    model=OLLAMA_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    stream=False,
                )
                case["generated_judgment"] = response["message"]["content"]
            except Exception as e:
                log.error(f"Failed to generate judgment for {case_num}: {e}")
                case["generated_judgment"] = f"Error: Generation failed. {e}"

            # 5c. Create LangChain Document for Qdrant
            # The page_content is what will be vectorized and searched
            page_content = f"""
            Case Number: {case.get('Case_Number', 'N/A')}
            Police Station: {case.get('Police_Station', 'N/A')}
            Accused: {case.get('Accused_Name', 'N/A')}
            Sections: {case.get('Sections_at_Final', 'N/A')}
            Verdict: {case.get('Result', 'N/A')}
            
            FIR Summary:
            {case.get('FIR_Contents', 'N/A')}
            
            Generated Judgment:
            {case.get('generated_judgment', 'N/A')}
            """

            # Metadata contains all other fields for filtering
            metadata = case.copy()
            # Clean complex objects that Qdrant metadata cannot store
            metadata.pop("border_coordinates", None)
            metadata.pop("generated_judgment", None)  # Already in page_content
            metadata["has_geo_data"] = "border_coordinates" in case

            documents_to_ingest.append(
                Document(page_content=page_content, metadata=metadata)
            )

        if missing_districts:
            log.warning(f"No boundary data found for districts: {missing_districts}")

        # 6. Batch Ingest all processed cases into Qdrant
        log.info(
            f"All cases processed. Embedding and ingesting {len(documents_to_ingest)} documents..."
        )
        if documents_to_ingest:
            Qdrant.from_documents(
                documents=documents_to_ingest,
                embedding=embeddings_client,
                url=QDRANT_URL,
                api_key=QDRANT_API_KEY,
                collection_name=CASE_COLLECTION_NAME,
                prefer_grpc=True,
                batch_size=64,
            )
            log.info(f"Successfully ingested documents into {CASE_COLLECTION_NAME}.")
        else:
            log.warning("No case documents were prepared for ingestion.")

        log.info(f"--- Finished Case Data Ingestion ---")

    except Exception as e:
        log.error(f"An unexpected error occurred during case ingestion: {e}")
        traceback.print_exc()


# =========================================================================
# SCRIPT EXECUTION
# =========================================================================

if __name__ == "__main__":
    if not embeddings_client:
        log.error("FATAL: Embedding client not loaded. Aborting ingestion.")
        sys.exit(1)

    try:
        log.info(f"Connecting to Qdrant at {QDRANT_URL}...")
        qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        log.info("Qdrant connection successful.")

        # Run Pipeline 1
        ingest_legal_corpus(qdrant_client)

        # Run Pipeline 2
        ingest_case_data(qdrant_client)

        log.info("\n" + "=" * 50)
        log.info("  ALL DATA INGESTION COMPLETE")
        log.info(
            f"  Collections '{LEGAL_COLLECTION_NAME}' and '{CASE_COLLECTION_NAME}'"
        )
        log.info(f"  are now populated in Qdrant.")
        log.info("=" * 50)

    except Exception as e:
        log.error(f"Failed to connect to Qdrant at {QDRANT_URL}: {e}")
        traceback.print_exc()
        sys.exit(1)
