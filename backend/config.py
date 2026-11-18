"""Central environment-backed configuration."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
CHROMA_DIR = BASE_DIR / "chroma_db"
SQLITE_DB_PATH = BASE_DIR / "app_data.db"
UPLOAD_DIR.mkdir(exist_ok=True)
CHROMA_DIR.mkdir(exist_ok=True)

CHUNK_SIZE_TOKENS = int(os.getenv("CHUNK_SIZE_TOKENS", "200"))
CHUNK_OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", "40"))
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "documents")
TOP_K_RESULTS = int(os.getenv("TOP_K_RESULTS", "4"))
RETRIEVAL_CANDIDATES = int(os.getenv("RETRIEVAL_CANDIDATES", "20"))
MIN_SIMILARITY = float(os.getenv("MIN_SIMILARITY", "0.25"))
RERANK_ENABLED = os.getenv("RERANK_ENABLED", "false").lower() == "true"
HYBRID_SEARCH_ENABLED = os.getenv("HYBRID_SEARCH_ENABLED", "false").lower() == "true"
RERANKER_MODEL_NAME = os.getenv("RERANKER_MODEL_NAME", "BAAI/bge-reranker-base")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")
# Optional OpenAI-compatible endpoint (Groq, Together, OpenRouter, local vLLM...). Empty = official OpenAI.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").strip()
# Max characters of document context sent to the LLM per question (~4 chars per token).
CONTEXT_MAX_CHARS = int(os.getenv("CONTEXT_MAX_CHARS", "24000"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
CORS_ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500").split(",") if x.strip()]
API_KEY = os.getenv("API_KEY", "")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "30"))
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "500"))
