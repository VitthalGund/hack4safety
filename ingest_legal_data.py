import logging
import pymongo
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.core.config import settings
from app.core.embedding import embeddings_client, EMBEDDING_DIMENSIONS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# --- Configuration ---
CORPUS_PATH = "./legal_corpus"
DB_NAME = settings.MONGO_DB_NAME
COLLECTION_NAME = "legal_vectors"
ATLAS_VECTOR_SEARCH_INDEX_NAME = "legal_vector_index"


def ingest_data():
    """
    Reads PDFs, splits them, and stores their embeddings in MongoDB Atlas.
    """
    if not embeddings_client:
        log.error("Embedding client not loaded. Aborting ingestion.")
        return

    try:
        # 1. Connect to MongoDB Atlas
        log.info(f"Connecting to MongoDB Atlas at {settings.MONGO_URL}...")
        client = pymongo.MongoClient(settings.MONGO_URL)
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
        log.info(f"Connected to DB: {DB_NAME}, Collection: {COLLECTION_NAME}")

        # 2. Clear old collection
        log.warning(f"Deleting existing collection '{COLLECTION_NAME}'...")
        db.drop_collection(COLLECTION_NAME)
        log.info("Old collection dropped.")

        # 3. Load documents
        log.info(f"Loading documents from {CORPUS_PATH}...")
        loader = PyPDFDirectoryLoader(CORPUS_PATH, recursive=True)
        documents = loader.load()
        if not documents:
            log.error(f"No PDF documents found in {CORPUS_PATH}. Aborting.")
            return
        log.info(f"Loaded {len(documents)} document pages.")

        # 4. Split documents
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=150
        )
        chunks = text_splitter.split_documents(documents)
        log.info(f"Created {len(chunks)} text chunks.")

        # 5. Ingest data into MongoDB Atlas
        log.info("Embedding and ingesting chunks into MongoDB Atlas...")
        MongoDBAtlasVectorSearch.from_documents(
            documents=chunks,
            embedding=embeddings_client,
            collection=collection,
            index_name=ATLAS_VECTOR_SEARCH_INDEX_NAME,
        )
        log.info(f"Successfully ingested {len(chunks)} chunks.")

        # 6. MANUAL STEP INSTRUCTION
        log.info("\n" + "=" * 50)
        log.info("  ACTION REQUIRED: Create a Vector Search Index in MongoDB Atlas!")
        log.info(
            f"  1. Go to your MongoDB Atlas dashboard for the '{DB_NAME}' database."
        )
        log.info(f"  2. Select the '{COLLECTION_NAME}' collection.")
        log.info("  3. Go to the 'Search' tab.")
        log.info("  4. Click 'Create Search Index' -> 'Atlas Vector Search'.")
        log.info("  5. Use the JSON editor and paste the following configuration:")
        log.info(
            f"""
        {{
          "fields": [
            {{
              "type": "vector",
              "path": "embedding",
              "numDimensions": {EMBEDDING_DIMENSIONS},
              "similarity": "cosine"
            }}
          ]
        }}
        """
        )
        log.info(f"  6. Set the index name to: {ATLAS_VECTOR_SEARCH_INDEX_NAME}")
        log.info("=" * 50)

    except Exception as e:
        log.error(f"An error occurred during ingestion: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    ingest_data()
