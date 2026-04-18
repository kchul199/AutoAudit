"""FastAPI backend for AutoAudit."""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.cp1_preprocessing.doc_loader import detect_doc_type
from app.cp1_preprocessing.log_parser import Turn
from app.cp2_knowledge_base.chunker import ParentChildChunker
from app.cp2_knowledge_base.embedder import DualEmbedder
from app.cp3_retrieval.reranker import RetrievalPipeline
from app.cp4_evaluator import ClaudeJudge, ConsensusEvaluator, GPTJudge, GeminiJudge
from app.utils.config import load_config


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

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "stages": ["cp1", "cp2", "cp3", "cp4", "cp5", "cp6"],
            "frontend_hint": "Run the Vite app in ../frontend",
        }

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

    @app.get("/api/subscribers/{subscriber}/results/latest")
    def latest_results(subscriber: str) -> dict[str, Any]:
        output_dir = Path(config["results_dir"]) / subscriber
        summary = _load_json(output_dir / "cp5_summary.json") or {}
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
            names.update(path.name for path in root.iterdir() if path.is_dir())
    return sorted(names)


def _subscriber_snapshot(
    subscriber: str,
    config: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    meta = registry.get(subscriber, {})
    docs_count = len(_list_files(Path(config["doc_dir"]) / subscriber, {"pdf", "txt", "html", "htm", "docx", "doc", "md"}))
    logs_count = len(_list_files(Path(config["log_dir"]) / subscriber, {"txt", "json", "csv", "log"}))
    summary = _load_json(Path(config["results_dir"]) / subscriber / "cp5_summary.json") or {}
    summary_info = summary.get("summary", {})
    return {
        "id": subscriber,
        "name": subscriber,
        "industry": meta.get("industry", "미분류"),
        "contact": meta.get("contact", ""),
        "desc": meta.get("desc", ""),
        "docsCount": docs_count,
        "logsCount": logs_count,
        "avgAccuracy": summary_info.get("avg_accuracy", 0.0),
        "avgFluency": summary_info.get("avg_fluency", 0.0),
        "avgOverall": summary_info.get("avg_overall", 0.0),
        "uncertainCount": summary_info.get("uncertain_count", 0),
        "lastEval": summary.get("generated_at"),
        "status": "active" if docs_count > 0 else "pending",
    }


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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
