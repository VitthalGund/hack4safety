import logging
from fastapi import HTTPException
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.llms import Ollama
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import PromptTemplate
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser
from googletrans import Translator, LANGUAGES
import pymongo

from app.core.config import settings

log = logging.getLogger(__name__)

DB_NAME = settings.MONGO_DB_NAME
COLLECTION_NAME = "legal_vectors"
ATLAS_VECTOR_SEARCH_INDEX_NAME = "vector_index"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

OLLAMA_BASE_URL = "http://localhost:11434"  # Connects to your Docker container
PHI3_MODEL = "phi3:3.8b-mini-instruct-4k-q4_K_M"
GEMINI_MODEL = "gemini-1.5-flash-latest"


class RAGService:
    def __init__(self):
        try:
            # 1. Initialize DB Connection
            client = pymongo.MongoClient(settings.MONGO_URL)
            db = client[DB_NAME]
            collection = db[COLLECTION_NAME]

            # 2. Initialize Embedding Model (for querying)
            self.embeddings_client = HuggingFaceEmbeddings(
                model_name=EMBEDDING_MODEL, model_kwargs={"device": "cpu"}
            )

            # 3. Initialize Vector Store Retriever
            self.vector_store = MongoDBAtlasVectorSearch(
                collection=collection,
                embedding=self.embeddings_client,
                index_name=ATLAS_VECTOR_SEARCH_INDEX_NAME,
            )
            self.retriever = self.vector_store.as_retriever(
                search_type="similarity",
                search_kwargs={"k": 5},  # Retrieve top 5 legal chunks
            )

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
            raise RuntimeError("Could not initialize RAG components.")

    def _translate(self, text: str, dest_lang: str) -> str:
        """Translates text to a destination language."""
        try:
            translated = self.translator.translate(text, dest=dest_lang)
            return translated.text
        except Exception as e:
            log.error(f"Translation to {dest_lang} failed: {e}")
            return text  # Fallback

    def _detect_language(self, text: str) -> (str, str):
        """Detects language and returns its code (e.g., 'hi') and name (e.g., 'hindi')."""
        try:
            detected = self.translator.detect(text)
            lang_code = detected.lang
            lang_name = LANGUAGES.get(lang_code.lower(), lang_code)
            return lang_code, lang_name
        except Exception as e:
            log.error(f"Language detection failed: {e}")
            return "en", "english"  # Fallback to English

    def _get_llm(self, model_provider: str):
        """Plug-and-play model selector."""
        llm = self.llms.get(model_provider.lower())
        if not llm:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid model_provider. Available: {list(self.llms.keys())}",
            )
        return llm

    async def ask(self, query: str, model_provider: str) -> dict:
        """
        Main RAG pipeline logic.
        """
        # 1. Select the LLM
        llm = self._get_llm(model_provider)

        # 2. Detect original language
        original_lang_code, original_lang_name = self._detect_language(query)

        # 3. Translate query to English for better vector search
        # (Our embedding model is multilingual, but search is often
        # more robust if the query and context are in the same language)
        if original_lang_code != "en":
            search_query = self._translate(query, "en")
        else:
            search_query = query

        # 4. Define the RAG Prompt Template
        template = """
        **Task:** You are an expert legal assistant for Indian professionals (Police, Lawyers).
        Your answers must be accurate, neutral, and based *only* on the provided legal context.
        You must understand the user's query and the context, then formulate a helpful answer.
        
        **CRITICAL INSTRUCTION:** You MUST respond in the user's original language, which is **{language}**.
        
        **Legal Context:**
        {context}
        
        **User's Original Query (in {language}):**
        {question}
        
        **Answer (in {language}):**
        """

        prompt = PromptTemplate(
            template=template,
            input_variables=["context", "question", "language"],
        )

        # 5. Define the RAG Chain
        def format_docs(docs):
            return "\n\n---\n\n".join(doc.page_content for doc in docs)

        rag_chain = (
            {
                "context": self.retriever | format_docs,
                "question": RunnablePassthrough(),
                "language": lambda x: original_lang_name,  # Pass language to prompt
            }
            | prompt
            | llm
            | StrOutputParser()
        )

        # 6. Invoke the Chain
        log.info(f"Invoking RAG chain with model: {model_provider}...")

        # Retrieve context first to provide it in the response
        retrieved_docs = await self.retriever.ainvoke(search_query)
        context = format_docs(retrieved_docs)

        final_prompt_str = prompt.format(
            context=context, question=query, language=original_lang_name
        )

        # Use the correct async method for LangChain
        answer = await llm.ainvoke(final_prompt_str)

        # 7. Format the response
        return {
            "answer": answer.content,  # .content is used for Chat models
            "original_query": query,
            "model_used": model_provider,
            "original_language": original_lang_name,
            "retrieved_context": [doc.page_content for doc in retrieved_docs],
        }


# --- Create a single, reusable service instance ---
try:
    rag_service = RAGService()
except Exception as e:
    log.error(
        f"FATAL: RAGService failed to initialize. RAG API will be disabled. Error: {e}"
    )
    rag_service = None
