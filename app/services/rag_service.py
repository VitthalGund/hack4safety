import logging
from fastapi import HTTPException
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_community.llms import Ollama
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import PromptTemplate
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser
from googletrans import Translator, LANGUAGES
import pymongo

from app.core.config import settings
from app.core.embedding import embeddings_client  # Import our shared embedder

log = logging.getLogger(__name__)

# --- RAG Service Configuration ---
DB_NAME = settings.MONGO_DB_NAME
LEGAL_COLLECTION_NAME = "legal_vectors"
LEGAL_INDEX_NAME = "legal_vector_index"
CASE_COLLECTION_NAME = "conviction_cases"
CASE_INDEX_NAME = "case_vector_index"

OLLAMA_BASE_URL = "http://localhost:11434"  # Connects to your Docker container
PHI3_MODEL = "phi3:3.8b-mini-instruct-4k-q4_K_M"
GEMINI_MODEL = "gemini-1.5-flash-latest"


class RAGService:
    def __init__(self):
        try:
            # 1. Initialize DB Connection
            client = pymongo.MongoClient(settings.MONGO_URL)
            db = client[DB_NAME]

            if not embeddings_client:
                raise RuntimeError("Embedding client failed to load.")

            # 2. Initialize Legal Vector Store Retriever
            legal_collection = db[LEGAL_COLLECTION_NAME]
            self.legal_retriever = MongoDBAtlasVectorSearch(
                collection=legal_collection,
                embedding=embeddings_client,
                index_name=LEGAL_INDEX_NAME,
            ).as_retriever(
                search_kwargs={"k": 5}
            )  # Get top 5 legal chunks

            # 3. Initialize Case Vector Store Retriever
            case_collection = db[CASE_COLLECTION_NAME]
            self.case_retriever = MongoDBAtlasVectorSearch(
                collection=case_collection,
                embedding=embeddings_client,
                index_name=CASE_INDEX_NAME,
            ).as_retriever(
                search_kwargs={"k": 5}
            )  # Get top 5 case files

            # 4. Initialize LLM Clients (Plug-and-Play)
            self.llms = {
                "phi-3": Ollama(base_url=OLLAMA_BASE_URL, model=PHI3_MODEL),
                "gemini": ChatGoogleGenerativeAI(
                    model=GEMINI_MODEL, google_api_key=settings.GOOGLE_GEMINI_API_KEY
                ),
            }

            # 5. Initialize Translator
            self.translator = Translator()
            log.info("RAGService initialized successfully.")

        except Exception as e:
            log.error(f"Failed to initialize RAGService: {e}")
            raise RuntimeError(f"Could not initialize RAG components: {e}")

    def _translate(self, text: str, dest_lang: str) -> str:
        """Translates text to a destination language."""
        try:
            return self.translator.translate(text, dest=dest_lang).text
        except Exception:
            return text  # Fallback

    def _detect_language(self, text: str) -> (str, str):
        try:
            detected = self.translator.detect(text)
            lang_code = detected.lang
            lang_name = LANGUAGES.get(lang_code.lower(), lang_code)
            return lang_code, lang_name
        except Exception:
            return "en", "english"  # Fallback

    def _get_llm(self, model_provider: str):
        llm = self.llms.get(model_provider.lower())
        if not llm:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid model_provider. Available: {list(self.llms.keys())}",
            )
        return llm

    async def _run_rag_chain(
        self, query: str, model_provider: str, retriever, prompt_template: str
    ):
        """Generic RAG pipeline runner."""

        llm = self._get_llm(model_provider)
        original_lang_code, original_lang_name = self._detect_language(query)

        # Use original query for multilingual embedding model
        search_query = query

        prompt = PromptTemplate(
            template=prompt_template,
            input_variables=["context", "question", "language"],
        )

        def format_docs(docs):
            # Format for cases
            if retriever == self.case_retriever:
                return "\n\n---\n\n".join(f"Case: {doc.page_content}" for doc in docs)
            # Format for legal docs
            return "\n\n---\n\n".join(
                f"Source: {doc.metadata.get('source', 'N/A')}, Page: {doc.metadata.get('page', 'N/A')}\nContent: {doc.page_content}"
                for doc in docs
            )

        rag_chain = (
            {
                "context": retriever | format_docs,
                "question": RunnablePassthrough(),
                "language": lambda x: original_lang_name,
            }
            | prompt
            | llm
            | StrOutputParser()
        )

        log.info(f"Invoking RAG chain with model: {model_provider}...")

        retrieved_docs = await retriever.ainvoke(search_query)
        context = format_docs(retrieved_docs)

        final_prompt_str = prompt.format(
            context=context, question=query, language=original_lang_name
        )

        answer = await llm.ainvoke(final_prompt_str)

        return {
            "answer": answer.content,
            "original_query": query,
            "model_used": model_provider,
            "original_language": original_lang_name,
            "retrieved_context": [doc.page_content for doc in retrieved_docs],
        }

    async def ask_legal_bot(self, query: str, model_provider: str) -> dict:
        """Runs RAG against the Indian Laws vector store."""
        LEGAL_PROMPT = """
        **Task:** You are an expert legal assistant for Indian professionals (Police, Lawyers).
        Your answers must be accurate, neutral, and based *only* on the provided legal context.
        
        **CRITICAL INSTRUCTION:** You MUST respond in the user's original language, which is **{language}**.
        
        **Legal Context:**
        {context}
        
        **User's Original Query (in {language}):**
        {question}
        
        **Answer (in {language}):**
        """
        return await self._run_rag_chain(
            query, model_provider, self.legal_retriever, LEGAL_PROMPT
        )

    async def ask_case_bot(self, query: str, model_provider: str) -> dict:
        """Runs RAG against the MongoDB `conviction_cases` vector store."""
        CASE_PROMPT = """
        **Task:** You are an intelligent analyst for the Odisha Police.
        Your answers must be based *only* on the provided context of police case files.
        Summarize findings, identify patterns, or find specific case details.
        
        **CRITICAL INSTRUCTION:** You MUST respond in the user's original language, which is **{language}**.
        
        **Case File Context:**
        {context}
        
        **User's Original Query (in {language}):**
        {question}
        
        **Answer (in {language}):**
        """
        return await self._run_rag_chain(
            query, model_provider, self.case_retriever, CASE_PROMPT
        )


# --- Create a single, reusable service instance ---
try:
    rag_service = RAGService()
except Exception as e:
    log.error(
        f"FATAL: RAGService failed to initialize. RAG API will be disabled. Error: {e}"
    )
    rag_service = None
