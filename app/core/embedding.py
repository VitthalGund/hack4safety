from langchain_community.embeddings import HuggingFaceEmbeddings
import logging

log = logging.getLogger(__name__)

# This multilingual model understands Indian languages and maps them to a common space
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# This model outputs 384-dimension vectors
EMBEDDING_DIMENSIONS = 384

try:
    log.info(f"Loading multilingual embedding model: {EMBEDDING_MODEL}...")
    # We use 'cpu'. Change to 'cuda' if you have an NVIDIA GPU.
    embeddings_client = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={
            "normalize_embeddings": True
        },  # Atlas Vector Search requires this
    )
    log.info("Embedding client loaded successfully.")
except Exception as e:
    log.error(f"FATAL: Failed to load embedding model: {e}")
    embeddings_client = None
