"""FastAPI backend for AutoAudit."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.cp1_preprocessing.doc_loader import detect_doc_type
from app.cp1_preprocessing.log_parser import Turn
from app.cp2_knowledge_base.chunker import ParentChildChunker
from app.cp2_knowledge_base.embedder import DualEmbedder
from app.cp3_retrieval.reranker import RetrievalPipeline
from app.cp4_evaluator import ClaudeJudge, ConsensusEvaluator, GPTJudge, GeminiJudge, build_live_readiness
from app.ops import JobManager
from app.utils.config import load_config

REVIEW_STATE_PRIORITY = {
    "INCOMPLETE": 0,
    "DEGRADED": 1,
    "UNCERTAIN": 2,
    "TRUSTED": 3,
}


class SubscriberCreate(BaseModel):
    name: str
    industry: str = ""
    contact: str = ""
    desc: str = ""


class PipelineRunRequest(BaseModel):
    subscriber: str
    until: str = "cp6"
    reindex: bool = False
    allow_sample_data: bool = False


class AnchorEvalJobRequest(BaseModel):
    subscriber: str
    dataset_path: str


class ReviewActionRequest(BaseModel):
    conv_id: str
    turn_index: int
    action: Literal["approve", "hold", "recheck", "assign"]
    note: str = ""
    assignee: str = ""


class ChatTurn(BaseModel):
    role: str
    text: str


class SimulatorRequest(BaseModel):
    subscriber: str
    user_query: str
    bot_answer: str
    conversation_history: list[ChatTurn] = Field(default_factory=list)


def create_app(config: dict[str, Any] | None = None) -> FastAPI:
    config = config or load_config(".env")
    results_dir = Path(config["results_dir"])
    doc_dir = Path(config["doc_dir"])
    log_dir = Path(config["log_dir"])

    results_dir.mkdir(parents=True, exist_ok=True)
    doc_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="AutoAudit API",
        version="1.0.0",
        description="RAG 기반 콜봇 품질 자동 검증 백엔드",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/artifacts", StaticFiles(directory=str(results_dir), html=True), name="artifacts")

    app.state.config = config
    app.state.registry_path = results_dir / "subscriber_registry.json"
    app.state.job_manager = JobManager(results_dir / "_jobs")
    app.state.live_probe_result = None

    @app.get("/health")
    def health() -> dict[str, Any]:
        live_readiness = build_live_readiness(config, probe_live=False)
        return {
            "status": "ok",
            "stages": ["cp1", "cp2", "cp3", "cp4", "cp5", "cp6"],
            "frontend_hint": "Run the Vite app in ../frontend",
            "background_jobs": True,
            "live_consensus_ready": live_readiness["summary"]["trusted_possible"],
        }

    @app.get("/api/live-consensus/readiness")
    def get_live_consensus_readiness(request: Request) -> dict[str, Any]:
        passive = build_live_readiness(config, probe_live=False)
        passive["last_probe"] = request.app.state.live_probe_result
        return passive

    @app.post("/api/live-consensus/probe")
    async def probe_live_consensus(request: Request) -> dict[str, Any]:
        result = await asyncio.to_thread(build_live_readiness, config, True)
        request.app.state.live_probe_result = result
        return result

    @app.get("/api/subscribers")
    def list_subscribers(request: Request) -> list[dict[str, Any]]:
        registry = _read_registry(request.app.state.registry_path)
        names = _discover_subscribers(config, registry)
        return [_subscriber_snapshot(name, config, registry) for name in names]

    @app.post("/api/subscribers")
    def create_subscriber(payload: SubscriberCreate, request: Request) -> dict[str, Any]:
        registry = _read_registry(request.app.state.registry_path)
        registry[payload.name] = {
            "industry": payload.industry,
            "contact": payload.contact,
            "desc": payload.desc,
        }
        _write_registry(request.app.state.registry_path, registry)

        (Path(config["doc_dir"]) / payload.name).mkdir(parents=True, exist_ok=True)
        (Path(config["log_dir"]) / payload.name).mkdir(parents=True, exist_ok=True)
        (Path(config["results_dir"]) / payload.name).mkdir(parents=True, exist_ok=True)
        return _subscriber_snapshot(payload.name, config, registry)

    @app.get("/api/subscribers/{subscriber}")
    def get_subscriber(subscriber: str, request: Request) -> dict[str, Any]:
        registry = _read_registry(request.app.state.registry_path)
        if subscriber not in _discover_subscribers(config, registry):
            raise HTTPException(status_code=404, detail="가입자를 찾을 수 없습니다.")
        return _subscriber_snapshot(subscriber, config, registry)

    @app.get("/api/subscribers/{subscriber}/documents")
    def list_documents(subscriber: str) -> list[dict[str, Any]]:
        folder = Path(config["doc_dir"]) / subscriber
        return _list_files(folder, {"pdf", "txt", "html", "htm", "docx", "doc", "md"}, classify_docs=True)

    @app.post("/api/subscribers/{subscriber}/documents/upload")
    async def upload_documents(subscriber: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
        target_dir = Path(config["doc_dir"]) / subscriber
        uploaded = await _save_uploads(files, target_dir)
        return {"uploaded": uploaded, "count": len(uploaded)}

    @app.get("/api/subscribers/{subscriber}/logs")
    def list_logs(subscriber: str) -> list[dict[str, Any]]:
        folder = Path(config["log_dir"]) / subscriber
        return _list_files(folder, {"txt", "json", "csv", "log"})

    @app.post("/api/subscribers/{subscriber}/logs/upload")
    async def upload_logs(subscriber: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
        target_dir = Path(config["log_dir"]) / subscriber
        uploaded = await _save_uploads(files, target_dir)
        return {"uploaded": uploaded, "count": len(uploaded)}

    @app.post("/api/pipeline/run")
    async def run_pipeline_endpoint(payload: PipelineRunRequest) -> dict[str, Any]:
        import run_pipeline

        args = SimpleNamespace(
            until=payload.until,
            reindex=payload.reindex,
            allow_sample_data=payload.allow_sample_data,
        )
        result = await asyncio.to_thread(
            run_pipeline.run_subscriber,
            payload.subscriber,
            config,
            args,
        )
        return result

    @app.post("/api/pipeline/jobs")
    def create_pipeline_job(payload: PipelineRunRequest, request: Request) -> dict[str, Any]:
        job = request.app.state.job_manager.create_pipeline_job(
            subscriber=payload.subscriber,
            config=config,
            payload=payload.model_dump(),
        )
        return job

    @app.get("/api/pipeline/jobs")
    def list_pipeline_jobs(request: Request, subscriber: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return request.app.state.job_manager.list_jobs(
            kind="pipeline",
            subscriber=subscriber,
            limit=limit,
        )

    @app.get("/api/pipeline/jobs/{job_id}")
    def get_pipeline_job(job_id: str, request: Request) -> dict[str, Any]:
        job = request.app.state.job_manager.get_job(job_id)
        if not job or job.get("kind") != "pipeline":
            raise HTTPException(status_code=404, detail="파이프라인 job을 찾을 수 없습니다.")
        return job

    @app.get("/api/pipeline/jobs/{job_id}/events")
    async def stream_pipeline_job(job_id: str, request: Request) -> StreamingResponse:
        job = request.app.state.job_manager.get_job(job_id)
        if not job or job.get("kind") != "pipeline":
            raise HTTPException(status_code=404, detail="파이프라인 job을 찾을 수 없습니다.")
        return _job_event_response(request.app.state.job_manager, job_id, "pipeline")

    @app.post("/api/evals/anchor/jobs")
    def create_anchor_eval_job(payload: AnchorEvalJobRequest, request: Request) -> dict[str, Any]:
        job = request.app.state.job_manager.create_anchor_eval_job(
            subscriber=payload.subscriber,
            config=config,
            payload=payload.model_dump(),
        )
        return job

    @app.get("/api/evals/anchor/jobs")
    def list_anchor_eval_jobs(request: Request, subscriber: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return request.app.state.job_manager.list_jobs(
            kind="anchor_eval",
            subscriber=subscriber,
            limit=limit,
        )

    @app.get("/api/evals/anchor/jobs/{job_id}")
    def get_anchor_eval_job(job_id: str, request: Request) -> dict[str, Any]:
        job = request.app.state.job_manager.get_job(job_id)
        if not job or job.get("kind") != "anchor_eval":
            raise HTTPException(status_code=404, detail="앵커 eval job을 찾을 수 없습니다.")
        return job

    @app.get("/api/evals/anchor/jobs/{job_id}/events")
    async def stream_anchor_eval_job(job_id: str, request: Request) -> StreamingResponse:
        job = request.app.state.job_manager.get_job(job_id)
        if not job or job.get("kind") != "anchor_eval":
            raise HTTPException(status_code=404, detail="앵커 eval job을 찾을 수 없습니다.")
        return _job_event_response(request.app.state.job_manager, job_id, "anchor_eval")

    @app.get("/api/subscribers/{subscriber}/results/latest")
    def latest_results(subscriber: str) -> dict[str, Any]:
        output_dir = Path(config["results_dir"]) / subscriber
        summary = _load_json(output_dir / "cp5_summary.json") or {}
        review_actions = _load_review_actions(output_dir)
        summary = _merge_review_actions(summary, review_actions, results_dir / "_jobs")
        publish = _load_json(output_dir / "cp6_publish_result.json") or {}
        cp4 = _load_json(output_dir / "cp4_evaluation_results.json") or []

        return {
            "subscriber": subscriber,
            "summary": summary,
            "report": publish,
            "cp4_turns": len(cp4),
            "report_url": f"/artifacts/{subscriber}/cp6_report.html"
            if (output_dir / "cp6_report.html").exists()
            else None,
        }

    @app.get("/api/subscribers/{subscriber}/evals/anchor/latest")
    def latest_anchor_eval(subscriber: str) -> dict[str, Any]:
        output_dir = Path(config["results_dir"]) / subscriber
        report = _load_json(output_dir / "anchor_eval_report.json")
        if report is None:
            raise HTTPException(status_code=404, detail="앵커 eval 결과가 없습니다.")
        return report

    @app.get("/api/subscribers/{subscriber}/results/turn-detail")
    def turn_detail(subscriber: str, conv_id: str, turn_index: int) -> dict[str, Any]:
        output_dir = Path(config["results_dir"]) / subscriber
        cp4 = _load_json(output_dir / "cp4_evaluation_results.json") or []
        item = _find_turn_result(cp4, conv_id=conv_id, turn_index=turn_index)
        if item is None:
            raise HTTPException(status_code=404, detail="평가 턴 상세를 찾을 수 없습니다.")
        review_actions = _load_review_actions(output_dir)
        action_entry = review_actions.get(_review_action_key(conv_id, turn_index))
        return _build_turn_detail(
            item,
            review_action=_latest_review_action(action_entry),
            review_history=_review_history(action_entry),
            review_status=_review_status(action_entry),
            assignee=_review_assignee(action_entry),
            recheck_job=_recheck_job_snapshot(action_entry, results_dir / "_jobs"),
        )

    @app.get("/api/dashboard/review-ops")
    def dashboard_review_ops() -> dict[str, Any]:
        registry = _read_registry(app.state.registry_path)
        jobs_dir = results_dir / "_jobs"
        overview = {
            "total_pending_reviews": 0,
            "assigned_review_count": 0,
            "pending_unassigned_count": 0,
            "completed_recheck_count": 0,
            "running_recheck_count": 0,
        }
        assignee_map: dict[str, dict[str, Any]] = {}
        recent_rechecks: list[dict[str, Any]] = []

        for subscriber in _discover_subscribers(config, registry):
            output_dir = results_dir / subscriber
            report = _merge_review_actions(
                _load_json(output_dir / "cp5_summary.json") or {},
                _load_review_actions(output_dir),
                jobs_dir,
            )
            summary = report.get("summary", {}) or {}
            overview["total_pending_reviews"] += int(summary.get("review_queue_size", 0) or 0)
            overview["assigned_review_count"] += int(summary.get("assigned_review_count", 0) or 0)
            overview["pending_unassigned_count"] += int(summary.get("pending_unassigned_count", 0) or 0)
            overview["completed_recheck_count"] += int(summary.get("completed_recheck_count", 0) or 0)
            overview["running_recheck_count"] += int(summary.get("running_recheck_count", 0) or 0)

            for item in report.get("review_queue", []) or []:
                assignee = item.get("assignee") or "미할당"
                stats = assignee_map.setdefault(
                    assignee,
                    {
                        "assignee": assignee,
                        "assigned_count": 0,
                        "pending_count": 0,
                        "hold_count": 0,
                        "recheck_count": 0,
                        "completed_recheck_count": 0,
                        "subscribers": set(),
                    },
                )
                stats["assigned_count"] += 1
                stats["subscribers"].add(subscriber)
                if item.get("review_status") == "pending":
                    stats["pending_count"] += 1
                if item.get("review_status") == "hold":
                    stats["hold_count"] += 1
                if item.get("review_status") == "recheck":
                    stats["recheck_count"] += 1
                if (item.get("recheck_job") or {}).get("status") == "completed":
                    stats["completed_recheck_count"] += 1
                    recent_rechecks.append(
                        {
                            "subscriber": subscriber,
                            "assignee": item.get("assignee") or "",
                            "source_file": item.get("source_file", ""),
                            "conv_id": item.get("conv_id"),
                            "turn_index": item.get("turn_index"),
                            "user_query": item.get("user_query", ""),
                            "review_status": item.get("review_status"),
                            "finished_at": (item.get("recheck_job") or {}).get("finished_at"),
                            "job_id": (item.get("recheck_job") or {}).get("id"),
                        }
                    )

        assignees = []
        for stats in assignee_map.values():
            assignees.append(
                {
                    **stats,
                    "subscribers": sorted(stats["subscribers"]),
                }
            )
        assignees.sort(
            key=lambda item: (
                -(item.get("pending_count", 0) + item.get("recheck_count", 0) + item.get("hold_count", 0)),
                item.get("assignee") == "미할당",
                item.get("assignee"),
            )
        )
        recent_rechecks.sort(key=lambda item: str(item.get("finished_at") or ""), reverse=True)

        return {
            "overview": overview,
            "assignees": assignees,
            "recent_rechecks": recent_rechecks[:8],
        }

    @app.post("/api/subscribers/{subscriber}/results/review-actions")
    def submit_review_action(
        subscriber: str,
        payload: ReviewActionRequest,
        request: Request,
    ) -> dict[str, Any]:
        output_dir = Path(config["results_dir"]) / subscriber
        cp4 = _load_json(output_dir / "cp4_evaluation_results.json") or []
        item = _find_turn_result(cp4, conv_id=payload.conv_id, turn_index=payload.turn_index)
        if item is None:
            raise HTTPException(status_code=404, detail="평가 턴 상세를 찾을 수 없습니다.")

        review_actions = _load_review_actions(output_dir)
        action_entry = review_actions.get(_review_action_key(payload.conv_id, payload.turn_index), {})
        history = _review_history(action_entry)
        assignee = payload.assignee.strip() or _review_assignee(action_entry)
        action_record = {
            "conv_id": payload.conv_id,
            "turn_index": int(payload.turn_index),
            "action": payload.action,
            "note": payload.note.strip(),
            "updated_at": _now_iso(),
            "assignee": assignee,
        }
        if payload.action != "assign":
            action_record["snapshot_before"] = _build_result_snapshot(item)

        pipeline_job = None
        if payload.action == "recheck":
            pipeline_job = request.app.state.job_manager.create_pipeline_job(
                subscriber=subscriber,
                config=config,
                payload={
                    "subscriber": subscriber,
                    "until": "cp6",
                    "reindex": False,
                    "allow_sample_data": False,
                    "trigger": "review_action",
                    "review_target": {
                        "conv_id": payload.conv_id,
                        "turn_index": int(payload.turn_index),
                    },
                },
            )
            action_record["pipeline_job_id"] = pipeline_job["id"]

        review_actions[_review_action_key(payload.conv_id, payload.turn_index)] = {
            "latest": action_record,
            "history": [*history, action_record],
            "assignee": assignee,
        }
        _save_review_actions(output_dir, review_actions)
        return {
            "ok": True,
            "review_action": action_record,
            "pipeline_job": pipeline_job,
            "review_status": _review_status(review_actions[_review_action_key(payload.conv_id, payload.turn_index)]),
            "assignee": assignee,
        }

    @app.post("/api/simulator/evaluate")
    async def simulator_evaluate(payload: SimulatorRequest) -> dict[str, Any]:
        docs = _load_docs_for_subscriber(payload.subscriber, config)
        if not docs:
            raise HTTPException(status_code=400, detail="시뮬레이터 평가에 사용할 문서가 없습니다.")

        embedder = _build_embedder(payload.subscriber, docs, config)
        pipeline = RetrievalPipeline(
            embedder=embedder,
            anthropic_api_key=config["anthropic_api_key"],
            claude_model=config["claude_model"],
            cross_encoder_model=config["cross_encoder_model"],
            use_hyde=config["hyde_enabled"],
            use_multi_query=True,
            num_query_variants=config["num_query_variants"],
        )

        history_turns = [Turn(role=item.role, text=item.text) for item in payload.conversation_history]
        history_turns.append(Turn(role="user", text=payload.user_query))
        context = pipeline.retrieve(
            query=payload.user_query,
            conversation_history=history_turns,
            top_k_first=config["top_k_first_stage"],
            top_k_final=config["top_k_final"],
        )
        evaluator = ConsensusEvaluator(
            judges=[
                ClaudeJudge(model=config["claude_model"], api_key=config["anthropic_api_key"]),
                GPTJudge(model=config["openai_model"], api_key=config["openai_api_key"]),
                GeminiJudge(model=config["gemini_model"], api_key=config["google_api_key"]),
            ],
            uncertainty_threshold=config["uncertainty_threshold"],
        )
        consensus = await evaluator.evaluate(
            {
                "user_query": payload.user_query,
                "bot_answer": payload.bot_answer,
                "context_text": context.context_text,
                "retrieval": context.to_dict(),
            }
        )
        return {"context": context.to_dict(), "consensus": consensus.to_dict()}

    return app


def _read_registry(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_registry(path: Path, registry: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")


def _discover_subscribers(config: dict[str, Any], registry: dict[str, dict[str, Any]]) -> list[str]:
    names = set(registry.keys())
    for root_key in ("doc_dir", "log_dir", "results_dir"):
        root = Path(config[root_key])
        if root.exists():
            names.update(
                path.name
                for path in root.iterdir()
                if path.is_dir() and not path.name.startswith("_")
            )
    return sorted(names)


def _subscriber_snapshot(
    subscriber: str,
    config: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    meta = registry.get(subscriber, {})
    docs_count = len(_list_files(Path(config["doc_dir"]) / subscriber, {"pdf", "txt", "html", "htm", "docx", "doc", "md"}))
    logs_count = len(_list_files(Path(config["log_dir"]) / subscriber, {"txt", "json", "csv", "log"}))
    output_dir = Path(config["results_dir"]) / subscriber
    summary = _load_json(output_dir / "cp5_summary.json") or {}
    summary = _merge_review_actions(summary, _load_review_actions(output_dir), Path(config["results_dir"]) / "_jobs")
    summary_info = summary.get("summary", {})
    return {
        "id": subscriber,
        "name": subscriber,
        "industry": meta.get("industry", "미분류"),
        "contact": meta.get("contact", ""),
        "desc": meta.get("desc", ""),
        "docsCount": docs_count,
        "logsCount": logs_count,
        "avgAccuracy": summary_info.get("trusted_avg_accuracy") or summary_info.get("avg_accuracy") or 0.0,
        "avgFluency": summary_info.get("trusted_avg_fluency") or summary_info.get("avg_fluency") or 0.0,
        "avgOverall": summary_info.get("trusted_avg_overall") or summary_info.get("avg_overall") or 0.0,
        "uncertainCount": summary_info.get("uncertain_turns", summary_info.get("uncertain_count", 0)),
        "trustedRate": summary_info.get("trusted_rate", 0.0),
        "reviewQueueSize": summary_info.get("review_queue_size", 0),
        "degradedRatio": summary_info.get("degraded_ratio", 0.0),
        "incompleteRatio": summary_info.get("incomplete_ratio", 0.0),
        "lastEval": summary.get("generated_at"),
        "status": (
            "review"
            if summary_info.get("review_queue_size", 0) > 0
            else "active" if docs_count > 0 else "pending"
        ),
    }


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _review_action_key(conv_id: str, turn_index: int) -> str:
    return f"{conv_id}::{int(turn_index)}"


def _load_review_actions(output_dir: Path) -> dict[str, dict[str, Any]]:
    raw = _load_json(output_dir / "review_actions.json") or {}
    return _normalize_review_actions(raw)


def _save_review_actions(output_dir: Path, actions: dict[str, dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "review_actions.json").write_text(
        json.dumps(_normalize_review_actions(actions), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _review_status(action: dict[str, Any] | None) -> str:
    if not action:
        return "pending"
    if "history" in action:
        for item in reversed(_review_history(action)):
            derived = _review_status(item)
            if derived != "pending":
                return derived
        return "pending"
    return {
        "approve": "approved",
        "hold": "hold",
        "recheck": "recheck",
    }.get(action.get("action", ""), "pending")


def _review_assignee(entry: dict[str, Any] | None) -> str:
    if not entry:
        return ""
    if isinstance(entry, dict) and entry.get("assignee"):
        return str(entry.get("assignee") or "")
    latest = _latest_review_action(entry)
    if isinstance(latest, dict) and latest.get("assignee"):
        return str(latest.get("assignee") or "")
    for item in reversed(_review_history(entry)):
        if item.get("assignee"):
            return str(item.get("assignee") or "")
    return ""


def _merge_review_actions(
    report: dict[str, Any],
    review_actions: dict[str, dict[str, Any]],
    jobs_dir: Path | None = None,
) -> dict[str, Any]:
    if not report:
        return report

    merged = deepcopy(report)
    queue = merged.get("review_queue")
    if not isinstance(queue, list):
        return merged

    status_order = {"pending": 0, "recheck": 1, "hold": 2, "approved": 3}
    counts = {"pending": 0, "approved": 0, "hold": 0, "recheck": 0}

    for item in queue:
        entry = review_actions.get(_review_action_key(item.get("conv_id", ""), item.get("turn_index", -1)))
        action = _latest_review_action(entry)
        history = _review_history(entry)
        status = _review_status(entry)
        assignee = _review_assignee(entry)
        recheck_job = _recheck_job_snapshot(entry, jobs_dir)
        item["review_action"] = action
        item["review_status"] = status
        item["assignee"] = assignee
        item["review_history_count"] = len(history)
        item["recheck_job"] = recheck_job
        item["recheck_comparison"] = _build_recheck_comparison(item, history)
        counts[status] = counts.get(status, 0) + 1

    queue.sort(
        key=lambda item: (
            status_order.get(item.get("review_status", "pending"), 9),
            REVIEW_STATE_PRIORITY.get(item.get("state"), 9),
            item.get("overall_mean") if item.get("overall_mean") is not None else item.get("support_overall_mean") or 0.0,
        )
    )

    summary = merged.get("summary")
    if isinstance(summary, dict):
        summary["total_review_queue_size"] = len(queue)
        summary["review_queue_size"] = counts["pending"]
        summary["approved_review_count"] = counts["approved"]
        summary["hold_review_count"] = counts["hold"]
        summary["recheck_review_count"] = counts["recheck"]
        summary["assigned_review_count"] = sum(1 for item in queue if item.get("assignee"))
        summary["pending_unassigned_count"] = sum(
            1 for item in queue if item.get("review_status") == "pending" and not item.get("assignee")
        )
        summary["completed_recheck_count"] = sum(
            1 for item in queue if (item.get("recheck_job") or {}).get("status") == "completed"
        )
        summary["running_recheck_count"] = sum(
            1 for item in queue if (item.get("recheck_job") or {}).get("status") in {"queued", "running"}
        )

    return merged


def _job_event_response(job_manager: JobManager, job_id: str, expected_kind: str) -> StreamingResponse:
    async def event_generator():
        last_payload = None
        while True:
            job = job_manager.get_job(job_id)
            if job is None or job.get("kind") != expected_kind:
                yield "event: error\ndata: {\"detail\":\"job not found\"}\n\n"
                break

            payload = json.dumps(job, ensure_ascii=False)
            if payload != last_payload:
                yield f"event: job\ndata: {payload}\n\n"
                last_payload = payload
            else:
                yield ": ping\n\n"

            if job.get("status") in JobManager.TERMINAL_STATUSES:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


def _find_turn_result(cp4_results: list[dict[str, Any]], conv_id: str, turn_index: int) -> dict[str, Any] | None:
    for item in cp4_results:
        if item.get("conv_id") == conv_id and int(item.get("turn_index", -1)) == int(turn_index):
            return item
    return None


def _build_turn_detail(
    item: dict[str, Any],
    review_action: dict[str, Any] | None = None,
    review_history: list[dict[str, Any]] | None = None,
    review_status: str | None = None,
    assignee: str = "",
    recheck_job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    consensus = item.get("consensus", {}) or {}
    context = item.get("context", {}) or {}
    history = review_history or []
    top_chunks = []
    for chunk in context.get("top_chunks", [])[:5]:
        top_chunks.append(
            {
                "chunk_id": chunk.get("chunk_id"),
                "doc_id": chunk.get("doc_id"),
                "doc_type": chunk.get("doc_type"),
                "score": chunk.get("score"),
                "text": chunk.get("text"),
                "parent_text": chunk.get("parent_text"),
            }
        )

    return {
        "conv_id": item.get("conv_id"),
        "source_file": item.get("source_file", ""),
        "turn_index": item.get("turn_index"),
        "user_query": item.get("user_query", ""),
        "bot_answer": item.get("bot_answer", ""),
        "state": consensus.get("state"),
        "state_reason": consensus.get("state_reason", ""),
        "review_required": consensus.get("review_required", False),
        "overall_mean": consensus.get("overall_mean"),
        "support_overall_mean": consensus.get("support_overall_mean"),
        "live_judge_count": consensus.get("live_judge_count", 0),
        "fallback_judge_count": consensus.get("fallback_judge_count", 0),
        "grounding_signals": context.get("grounding_signals", {}),
        "context_text": context.get("context_text", ""),
        "query_variants": context.get("query_variants", []),
        "hypothetical_answer": context.get("hypothetical_answer"),
        "top_chunks": top_chunks,
        "judges": consensus.get("scores_detail", []),
        "review_action": review_action,
        "review_status": review_status or _review_status(review_action),
        "assignee": assignee,
        "review_history": list(reversed(history)),
        "recheck_job": recheck_job,
        "recheck_comparison": _build_recheck_comparison(item, history),
    }


def _normalize_review_actions(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return normalized

    for key, value in raw.items():
        if not isinstance(value, dict):
            continue

        if "latest" in value or "history" in value:
            latest = value.get("latest")
            history = [item for item in value.get("history", []) if isinstance(item, dict)]
        else:
            latest = deepcopy(value)
            history = [deepcopy(value)]

        if latest is None and history:
            latest = history[-1]
        normalized[key] = {
            "latest": latest,
            "history": history,
            "assignee": value.get("assignee", "") if isinstance(value, dict) else "",
        }
    return normalized


def _latest_review_action(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not entry:
        return None
    if "latest" in entry:
        return entry.get("latest")
    return entry


def _review_history(entry: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not entry:
        return []
    if "history" in entry:
        return [item for item in entry.get("history", []) if isinstance(item, dict)]
    return [entry]


def _latest_recheck_action(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    for item in reversed(_review_history(entry)):
        if item.get("action") == "recheck" and item.get("pipeline_job_id"):
            return item
    return None


def _load_job_snapshot(jobs_dir: Path | None, job_id: str | None) -> dict[str, Any] | None:
    if jobs_dir is None or not job_id:
        return None
    path = Path(jobs_dir) / f"{job_id}.json"
    if not path.exists():
        return None
    job = _load_json(path)
    if not isinstance(job, dict):
        return None
    return {
        "id": job.get("id"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "finished_at": job.get("finished_at"),
        "current_checkpoint": job.get("current_checkpoint"),
        "error": job.get("error"),
    }


def _recheck_job_snapshot(entry: dict[str, Any] | None, jobs_dir: Path | None) -> dict[str, Any] | None:
    action = _latest_recheck_action(entry)
    if not action:
        return None
    return _load_job_snapshot(jobs_dir, action.get("pipeline_job_id"))


def _build_result_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    consensus = item.get("consensus", {}) or {}
    context = item.get("context", {}) or {}
    grounding = context.get("grounding_signals", {}) or {}
    top_chunks = context.get("top_chunks") or item.get("top_chunks") or []
    chunk_ids = None
    if top_chunks:
        chunk_ids = [
            chunk.get("doc_id") or chunk.get("chunk_id")
            for chunk in top_chunks[:3]
            if chunk.get("doc_id") or chunk.get("chunk_id")
        ]

    return {
        "state": consensus.get("state", item.get("state")),
        "overall_mean": consensus.get("overall_mean", item.get("overall_mean")),
        "support_overall_mean": consensus.get("support_overall_mean", item.get("support_overall_mean")),
        "grounding_risk": grounding.get("grounding_risk", item.get("grounding_risk")),
        "top1_score": grounding.get("top1_score", item.get("top1_score")),
        "top_chunk_ids": chunk_ids,
        "top_chunks": [
            {
                "id": chunk.get("doc_id") or chunk.get("chunk_id"),
                "doc_type": chunk.get("doc_type"),
                "score": chunk.get("score"),
                "text": (chunk.get("parent_text") or chunk.get("text") or "")[:180],
            }
            for chunk in top_chunks[:3]
        ],
        "live_judge_count": consensus.get("live_judge_count", item.get("live_judge_count", 0)),
        "fallback_judge_count": consensus.get("fallback_judge_count", item.get("fallback_judge_count", 0)),
        "judges": [
            {
                "model": judge.get("model"),
                "source": judge.get("source"),
                "overall_score": judge.get("overall_score"),
                "accuracy": judge.get("accuracy"),
                "groundedness": judge.get("groundedness"),
                "reason_summary": judge.get("reason_summary"),
                "risk_flags": judge.get("risk_flags", []),
            }
            for judge in consensus.get("scores_detail", item.get("judges", []))[:3]
        ],
    }


def _build_recheck_comparison(
    current_item: dict[str, Any],
    review_history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    recheck_entry = None
    for action in reversed(review_history):
        if action.get("action") == "recheck" and isinstance(action.get("snapshot_before"), dict):
            recheck_entry = action
            break

    if recheck_entry is None:
        return None

    before = recheck_entry["snapshot_before"]
    after = _build_result_snapshot(current_item)
    overall_delta = _safe_delta(after.get("overall_mean"), before.get("overall_mean"))
    support_delta = _safe_delta(after.get("support_overall_mean"), before.get("support_overall_mean"))
    top1_delta = _safe_delta(after.get("top1_score"), before.get("top1_score"))
    changed_fields = []

    if before.get("state") != after.get("state"):
        changed_fields.append("state")
    if overall_delta not in (None, 0):
        changed_fields.append("overall_mean")
    if support_delta not in (None, 0):
        changed_fields.append("support_overall_mean")
    if before.get("grounding_risk") != after.get("grounding_risk"):
        changed_fields.append("grounding_risk")
    if top1_delta not in (None, 0):
        changed_fields.append("top1_score")
    if (
        before.get("top_chunk_ids") is not None
        and after.get("top_chunk_ids") is not None
        and before.get("top_chunk_ids") != after.get("top_chunk_ids")
    ):
        changed_fields.append("top_chunks")

    return {
        "action_at": recheck_entry.get("updated_at"),
        "before": before,
        "after": after,
        "overall_delta": overall_delta,
        "support_overall_delta": support_delta,
        "top1_score_delta": top1_delta,
        "state_changed": before.get("state") != after.get("state"),
        "grounding_changed": before.get("grounding_risk") != after.get("grounding_risk"),
        "top_chunk_changed": (
            before.get("top_chunk_ids") is not None
            and after.get("top_chunk_ids") is not None
            and before.get("top_chunk_ids") != after.get("top_chunk_ids")
        ),
        "changed_fields": changed_fields,
    }


def _safe_delta(current: Any, previous: Any) -> float | None:
    if current is None or previous is None:
        return None
    try:
        return round(float(current) - float(previous), 2)
    except (TypeError, ValueError):
        return None


def _list_files(folder: Path, suffixes: set[str], classify_docs: bool = False) -> list[dict[str, Any]]:
    if not folder.exists():
        return []

    items = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower().lstrip(".")
        if suffix not in suffixes:
            continue
        item = {
            "name": path.name,
            "path": str(path),
            "size": path.stat().st_size,
            "updatedAt": path.stat().st_mtime,
            "ext": suffix,
        }
        if classify_docs:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:3000]
            except Exception:
                text = path.name
            item["docType"] = detect_doc_type(text, path.name)
        items.append(item)
    return items


async def _save_uploads(files: list[UploadFile], target_dir: Path) -> list[dict[str, Any]]:
    target_dir.mkdir(parents=True, exist_ok=True)
    uploaded = []
    for file in files:
        destination = target_dir / file.filename
        with open(destination, "wb") as f:
            shutil.copyfileobj(file.file, f)
        uploaded.append({"name": file.filename, "path": str(destination), "size": destination.stat().st_size})
    return uploaded


def _load_docs_for_subscriber(subscriber: str, config: dict[str, Any]) -> list:
    from app.cp1_preprocessing.doc_loader import DocLoader

    folder = Path(config["doc_dir"]) / subscriber
    if not folder.exists():
        return []
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


app = create_app()
