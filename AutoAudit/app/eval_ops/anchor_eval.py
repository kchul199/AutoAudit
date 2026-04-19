"""앵커 Eval 실행기."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

from app.cp1_preprocessing.doc_loader import DocLoader
from app.cp1_preprocessing.log_parser import Turn
from app.cp2_knowledge_base.chunker import ParentChildChunker
from app.cp2_knowledge_base.embedder import DualEmbedder
from app.cp3_retrieval.reranker import RetrievalPipeline
from app.cp4_evaluator import ClaudeJudge, ConsensusEvaluator, GPTJudge, GeminiJudge
from app.utils.logger import get_logger

logger = get_logger(__name__)


def run_anchor_eval(
    subscriber: str,
    config: dict[str, Any],
    dataset_path: str,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    dataset_file = Path(dataset_path)
    if not dataset_file.exists():
        raise FileNotFoundError(f"앵커 eval 데이터셋이 없습니다: {dataset_file}")

    cases = load_anchor_cases(dataset_file)
    if not cases:
        raise ValueError(f"앵커 eval 케이스가 비어 있습니다: {dataset_file}")

    docs = _load_docs_for_subscriber(subscriber, config)
    if not docs:
        raise FileNotFoundError(f"앵커 eval에 사용할 문서가 없습니다: {Path(config['doc_dir']) / subscriber}")

    embedder = _build_embedder(subscriber, docs, config)
    pipeline = RetrievalPipeline(
        embedder=embedder,
        anthropic_api_key=config["anthropic_api_key"],
        claude_model=config["claude_model"],
        cross_encoder_model=config["cross_encoder_model"],
        use_hyde=config["hyde_enabled"],
        use_multi_query=True,
        num_query_variants=config["num_query_variants"],
    )
    evaluator = ConsensusEvaluator(
        judges=[
            ClaudeJudge(model=config["claude_model"], api_key=config["anthropic_api_key"]),
            GPTJudge(model=config["openai_model"], api_key=config["openai_api_key"]),
            GeminiJudge(model=config["gemini_model"], api_key=config["google_api_key"]),
        ],
        uncertainty_threshold=config["uncertainty_threshold"],
    )

    case_results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        context = pipeline.retrieve(
            query=case["user_query"],
            conversation_history=[Turn(role="user", text=case["user_query"])],
            top_k_first=config["top_k_first_stage"],
            top_k_final=config["top_k_final"],
        )
        consensus = asyncio.run(
            evaluator.evaluate(
                {
                    "user_query": case["user_query"],
                    "bot_answer": case["bot_answer"],
                    "context_text": context.context_text,
                    "retrieval": context.to_dict(),
                }
            )
        )

        case_result = evaluate_case_expectations(case, context.to_dict(), consensus.to_dict())
        case_results.append(case_result)

        if progress_callback:
            progress_callback(
                {
                    "progress": round(index / len(cases), 2),
                    "current_case_id": case.get("case_id") or f"case-{index}",
                    "summary": summarize_anchor_eval(case_results),
                }
            )

    summary = summarize_anchor_eval(case_results)
    report = {
        "subscriber": subscriber,
        "dataset_path": str(dataset_file),
        "case_count": len(case_results),
        "summary": summary,
        "cases": case_results,
    }

    output_dir = Path(config["results_dir"]) / subscriber
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "anchor_eval_report.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[EvalOps] 앵커 eval 저장: %s", output_path)
    return report


def load_anchor_cases(path: str | Path) -> list[dict[str, Any]]:
    dataset_file = Path(path)
    cases = []
    for line in dataset_file.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        cases.append(json.loads(text))
    return cases


def evaluate_case_expectations(
    case: dict[str, Any],
    context: dict[str, Any],
    consensus: dict[str, Any],
) -> dict[str, Any]:
    retrieval_hit = _retrieval_hit(case, context)
    state_match = None
    if case.get("expected_state"):
        state_match = consensus.get("state") == case["expected_state"]

    score_match = None
    support_score = consensus.get("support_overall_mean")
    minimum = case.get("min_support_overall")
    maximum = case.get("max_support_overall")
    if minimum is not None or maximum is not None:
        score_match = True
        if minimum is not None:
            score_match = score_match and support_score is not None and support_score >= float(minimum)
        if maximum is not None:
            score_match = score_match and support_score is not None and support_score <= float(maximum)

    required_flags = set(case.get("expected_risk_flags", []))
    actual_flags = {
        flag
        for judge in consensus.get("scores_detail", [])
        for flag in judge.get("risk_flags", [])
    }
    risk_flag_match = None if not required_flags else required_flags.issubset(actual_flags)

    return {
        "case_id": case.get("case_id"),
        "user_query": case.get("user_query"),
        "bot_answer": case.get("bot_answer"),
        "expected_state": case.get("expected_state"),
        "expected_doc_type": case.get("expected_doc_type"),
        "expected_terms": case.get("expected_terms", []),
        "retrieval_hit": retrieval_hit,
        "state_match": state_match,
        "score_match": score_match,
        "risk_flag_match": risk_flag_match,
        "support_overall_mean": support_score,
        "actual_state": consensus.get("state"),
        "grounding_risk": (context.get("grounding_signals") or {}).get("grounding_risk"),
        "top_chunks": context.get("top_chunks", [])[:3],
        "consensus": consensus,
    }


def summarize_anchor_eval(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "retrieval_hit_rate": _ratio(
            sum(1 for item in case_results if item.get("retrieval_hit") is True),
            sum(1 for item in case_results if item.get("retrieval_hit") is not None),
        ),
        "state_match_rate": _ratio(
            sum(1 for item in case_results if item.get("state_match") is True),
            sum(1 for item in case_results if item.get("state_match") is not None),
        ),
        "score_match_rate": _ratio(
            sum(1 for item in case_results if item.get("score_match") is True),
            sum(1 for item in case_results if item.get("score_match") is not None),
        ),
        "risk_flag_match_rate": _ratio(
            sum(1 for item in case_results if item.get("risk_flag_match") is True),
            sum(1 for item in case_results if item.get("risk_flag_match") is not None),
        ),
        "avg_support_overall": _mean(
            [item["support_overall_mean"] for item in case_results if item.get("support_overall_mean") is not None]
        ),
    }


def _retrieval_hit(case: dict[str, Any], context: dict[str, Any]) -> bool | None:
    top_chunks = context.get("top_chunks", [])
    if not top_chunks:
        return False

    expected_doc_id = case.get("expected_doc_id")
    if expected_doc_id:
        return any(chunk.get("doc_id") == expected_doc_id for chunk in top_chunks)

    expected_doc_type = case.get("expected_doc_type")
    if expected_doc_type:
        return any(chunk.get("doc_type") == expected_doc_type for chunk in top_chunks)

    expected_terms = [str(term).lower() for term in case.get("expected_terms", []) if str(term).strip()]
    if expected_terms:
        combined = "\n".join(
            str(chunk.get("parent_text") or chunk.get("text") or "").lower()
            for chunk in top_chunks
        )
        return all(term in combined for term in expected_terms)
    return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 3)


def _load_docs_for_subscriber(subscriber: str, config: dict[str, Any]) -> list:
    folder = Path(config["doc_dir"]) / subscriber
    loader = DocLoader(subscriber=subscriber)
    return loader.load_directory(str(folder))


def _build_embedder(subscriber: str, docs: list, config: dict[str, Any]) -> DualEmbedder:
    chunker = ParentChildChunker(
        child_chunk_size=config["child_chunk_size"],
        parent_chunk_size=config["parent_chunk_size"],
    )
    chunks = chunker.chunk_all(docs)
    embedder = DualEmbedder(
        subscriber=subscriber,
        persist_dir=config["chroma_persist_dir"],
        openai_api_key=config["openai_api_key"],
        embedding_model=config["embedding_model"],
        local_embedding_model=config["local_embedding_model"],
    )
    embedder.build_index(chunks, force_rebuild=False)
    return embedder
