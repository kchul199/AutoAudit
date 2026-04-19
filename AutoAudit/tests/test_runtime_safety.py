"""런타임 안전장치 회귀 테스트."""
import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.cp2_knowledge_base.embedder import DualEmbedder
from app.cp3_retrieval.hyde_retriever import HyDERetriever
from app.cp3_retrieval.query_builder import ConversationAwareQueryBuilder
from app.cp3_retrieval.reranker import RetrievalPipeline
from app.utils.config import load_config


def _import_run_pipeline():
    logger = logging.getLogger("run_pipeline")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    sys.modules.pop("run_pipeline", None)
    import run_pipeline

    return run_pipeline


def test_collection_base_is_chroma_safe_for_korean_names():
    base = DualEmbedder._sanitize_collection_base("한국통신")
    assert re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9._-]{1,498}[a-zA-Z0-9])?", base)


def test_tokenize_works_after_import_fix():
    tokens = DualEmbedder._tokenize("요금제 변경 방법 test 123")
    assert tokens == ["요금제", "변경", "방법", "test", "123"]


def test_run_cp1_requires_real_inputs_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_pipeline = _import_run_pipeline()

    config = {
        "log_dir": str(tmp_path / "logs"),
        "doc_dir": str(tmp_path / "docs"),
        "results_dir": str(tmp_path / "results"),
    }

    with pytest.raises(FileNotFoundError):
        run_pipeline.run_cp1("테스트사", config, config["log_dir"])


def test_run_subscriber_marks_partial_runs_completed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_pipeline = _import_run_pipeline()

    config = {
        "log_dir": str(tmp_path / "logs"),
        "doc_dir": str(tmp_path / "docs"),
        "results_dir": str(tmp_path / "results"),
        "chroma_persist_dir": str(tmp_path / "chroma"),
        "openai_api_key": "",
        "embedding_model": "text-embedding-3-large",
        "child_chunk_size": 200,
        "parent_chunk_size": 800,
        "top_k_first_stage": 20,
        "top_k_final": 5,
        "anthropic_api_key": "",
        "claude_model": "claude-opus-4-6",
        "cross_encoder_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "hyde_enabled": True,
        "num_query_variants": 3,
    }
    args = SimpleNamespace(until="cp1", reindex=False, allow_sample_data=True)

    result = run_pipeline.run_subscriber("테스트사", config, args)

    assert result["status"] == "completed"
    assert result["checkpoints"]["cp1"]["status"] == "done"
    assert "elapsed_sec" in result


def test_load_config_normalizes_placeholder_secrets(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxx",
                "ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxx",
                "GOOGLE_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxx",
                "CONFLUENCE_TOKEN=xxxxxxxxxxxxxxxx",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("CONFLUENCE_TOKEN", raising=False)

    config = load_config(str(env_file))

    assert config["openai_api_key"] == ""
    assert config["anthropic_api_key"] == ""
    assert config["google_api_key"] == ""
    assert config["confluence_token"] == ""


def test_explicit_blank_keys_do_not_fall_back_to_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-real")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-live")

    embedder = DualEmbedder(
        subscriber="테스트사",
        persist_dir=str(tmp_path / "chroma"),
        openai_api_key="",
    )
    hyde = HyDERetriever(
        embedder=SimpleNamespace(subscriber="테스트사"),
        anthropic_api_key="",
    )
    builder = ConversationAwareQueryBuilder(anthropic_api_key="")

    assert embedder.api_key == ""
    assert hyde.api_key == ""
    assert builder.api_key == ""


def test_retrieval_pipeline_explicit_blank_key_stays_blank(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-live")

    pipeline = RetrievalPipeline(
        embedder=SimpleNamespace(subscriber="테스트사"),
        anthropic_api_key="",
    )

    assert pipeline.query_builder.api_key == ""
    assert pipeline.hyde_retriever.api_key == ""
    assert pipeline.multi_query_expander.api_key == ""
