import logging
from fastapi import HTTPException
from qdrant_client import QdrantClient  # <-- ADDED
from langchain_qdrant import Qdrant  # <-- ADDED
from langchain_ollama import OllamaLLM
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from googletrans import Translator, LANGUAGES

# import pymongo  # <-- REMOVED

from app.core.config import settings
from app.core.embedding import embeddings_client  # Import our shared embedder

log = logging.getLogger(__name__)

# --- RAG Service Configuration ---
DB_NAME = settings.MONGO_DB_NAME
LEGAL_COLLECTION_NAME = "legal_vectors"
LEGAL_INDEX_NAME = "legal_vector_index"
CASE_COLLECTION_NAME = "conviction_cases"
CASE_INDEX_NAME = "case_vector_index"

OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL
PHI3_MODEL = "phi3:3.8b-mini-instruct-4k-q4_K_M"
GEMINI_MODEL = "gemini-2.0-flash"


class RAGService:
    def __init__(self):
        try:
            # 1. Initialize Qdrant Connection
            log.info(f"Connecting to Qdrant at {settings.QDRANT_URL}...")
            client = QdrantClient(
                url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY
            )

            if not embeddings_client:
                raise RuntimeError("Embedding client failed to load.")

            # 2. Initialize Legal Vector Store Retriever
            self.legal_retriever = Qdrant(
                client=client,
                collection_name=LEGAL_COLLECTION_NAME,
                embeddings=embeddings_client,
            ).as_retriever(
                search_kwargs={"k": 5}
            )  # Get top 5 legal chunks

            # 3. Initialize Case Vector Store Retriever
            self.case_retriever = Qdrant(
                client=client,
                collection_name=CASE_COLLECTION_NAME,
                embeddings=embeddings_client,
            ).as_retriever(
                search_kwargs={"k": 5}
            )  # Get top 5 case files

            # 4. Initialize LLM Clients (Plug-and-Play)
            self.llms = {
                "phi-3": OllamaLLM(base_url=OLLAMA_BASE_URL, model=PHI3_MODEL),
                "gemini": ChatGoogleGenerativeAI(
                    model=GEMINI_MODEL, google_api_key=settings.GOOGLE_GEMINI_API_KEY
                ),
            }

            # 5. Initialize Translator
            self.translator = Translator()
            log.info("RAGService initialized successfully with Qdrant.")

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

        # Note: retriever.ainvoke is used here, which is supported by Qdrant retriever
        retrieved_docs = await retriever.ainvoke(search_query)
        context = format_docs(retrieved_docs)

        # Re-create the prompt string for LLM invocation
        final_prompt_str = prompt.format(
            context=context, question=query, language=original_lang_name
        )

        # Use ainovke for the LLM call
        answer = await llm.ainvoke(final_prompt_str)

        # Check if answer is a string or an object with 'content'
        final_answer = answer.content if hasattr(answer, "content") else str(answer)

        return {
            "answer": final_answer,
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

    async def ask_generic(self, prompt_string: str, model_provider: str) -> dict:
        """
        Runs a generic prompt directly against an LLM, bypassing RAG.
        Used for tasks like summarization where context is already provided.
        """
        try:
            log.info(f"Invoking generic LLM chain with model: {model_provider}...")
            llm = self._get_llm(model_provider)

            # Directly invoke the LLM with the provided prompt string
            answer = await llm.ainvoke(prompt_string)

            # The answer object from ChatGoogleGenerativeAI or OllamaLLM
            # has a 'content' attribute for the string response.
            response_content = (
                answer.content if hasattr(answer, "content") else str(answer)
            )

            return {
                "response": response_content,
                "model_used": model_provider,
            }
        except Exception as e:
            log.error(f"Error in ask_generic: {e}")
            raise HTTPException(
                status_code=500, detail=f"Error processing generic LLM request: {e}"
            )


# --- Create a single, reusable service instance ---
try:
    rag_service = RAGService()
except Exception as e:
    log.error(
        f"FATAL: RAGService failed to initialize. RAG API will be disabled. Error: {e}"
    )
    rag_service = None
