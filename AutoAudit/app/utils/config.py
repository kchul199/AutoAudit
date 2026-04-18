"""환경변수 기반 설정 로더"""
import os
from pathlib import Path
from dotenv import load_dotenv  # pip install python-dotenv


def load_config(env_file: str = ".env") -> dict:
    """
    .env 파일을 로드하여 설정 딕셔너리 반환.
    환경변수가 이미 있으면 .env 값으로 덮어쓰지 않음.
    """
    if Path(env_file).exists():
        load_dotenv(env_file, override=False)

    return {
        # LLM API
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "openai_api_key":    os.getenv("OPENAI_API_KEY", ""),
        "google_api_key":    os.getenv("GOOGLE_API_KEY", ""),

        # Models
        "claude_model":  os.getenv("CLAUDE_MODEL",  "claude-opus-4-6"),
        "openai_model":  os.getenv("OPENAI_MODEL",  "gpt-4o"),
        "gemini_model":  os.getenv("GEMINI_MODEL",  "gemini-1.5-pro"),

        # Paths
        "chroma_persist_dir": os.getenv("CHROMA_PERSIST_DIR", "./data/chroma_db"),
        "log_dir":            os.getenv("LOG_DIR",   "./data/logs"),
        "doc_dir":            os.getenv("DOC_DIR",   "./data/docs"),
        "results_dir":        os.getenv("RESULTS_DIR", "./data/results"),

        # Retrieval
        "child_chunk_size":    int(os.getenv("CHILD_CHUNK_SIZE",  "200")),
        "parent_chunk_size":   int(os.getenv("PARENT_CHUNK_SIZE", "800")),
        "top_k_first_stage":   int(os.getenv("TOP_K_FIRST_STAGE", "20")),
        "top_k_final":         int(os.getenv("TOP_K_FINAL",       "5")),
        "num_query_variants":  int(os.getenv("NUM_QUERY_VARIANTS", "3")),
        "hyde_enabled":        os.getenv("HYDE_ENABLED", "true").lower() == "true",
        "cross_encoder_model": os.getenv("CROSS_ENCODER_MODEL",
                                         "cross-encoder/ms-marco-MiniLM-L-6-v2"),
        "embedding_model":     os.getenv("EMBEDDING_MODEL", "text-embedding-3-large"),
        "local_embedding_model": os.getenv("LOCAL_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),

        # Thresholds
        "uncertainty_threshold": float(os.getenv("UNCERTAINTY_THRESHOLD", "1.5")),
        "min_accuracy_score":    float(os.getenv("MIN_ACCURACY_SCORE",    "3.0")),
        "min_fluency_score":     float(os.getenv("MIN_FLUENCY_SCORE",     "3.0")),
        "max_uncertain_ratio":   float(os.getenv("MAX_UNCERTAIN_RATIO",   "0.10")),

        # Confluence
        "confluence_url":            os.getenv("CONFLUENCE_URL", ""),
        "confluence_email":          os.getenv("CONFLUENCE_EMAIL", ""),
        "confluence_token":          os.getenv("CONFLUENCE_TOKEN", ""),
        "confluence_space_key":      os.getenv("CONFLUENCE_SPACE_KEY", "CALLBOT"),
        "confluence_parent_page_id": os.getenv("CONFLUENCE_PARENT_PAGE_ID", ""),
    }
