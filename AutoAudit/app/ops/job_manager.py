"""백그라운드 파이프라인/평가 Job 관리."""
from __future__ import annotations

import json
import threading
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


class JobManager:
    TERMINAL_STATUSES = {"completed", "failed", "error"}

    def __init__(self, storage_dir: str | Path):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._load_existing_jobs()

    def list_jobs(
        self,
        kind: str | None = None,
        subscriber: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [deepcopy(job) for job in self._jobs.values()]

        if kind:
            jobs = [job for job in jobs if job.get("kind") == kind]
        if subscriber:
            jobs = [job for job in jobs if job.get("subscriber") == subscriber]
        jobs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return jobs[:limit]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return deepcopy(job) if job else None

    def create_pipeline_job(
        self,
        subscriber: str,
        config: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        job = self._create_job(
            kind="pipeline",
            subscriber=subscriber,
            payload=payload,
        )
        thread = threading.Thread(
            target=self._run_pipeline_job,
            args=(job["id"], subscriber, config, payload),
            daemon=True,
        )
        thread.start()
        return job

    def create_anchor_eval_job(
        self,
        subscriber: str,
        config: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        job = self._create_job(
            kind="anchor_eval",
            subscriber=subscriber,
            payload=payload,
        )
        thread = threading.Thread(
            target=self._run_anchor_eval_job,
            args=(job["id"], subscriber, config, payload),
            daemon=True,
        )
        thread.start()
        return job

    def _create_job(self, kind: str, subscriber: str, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = f"{kind}_{uuid.uuid4().hex[:12]}"
        now = _now()
        job = {
            "id": job_id,
            "kind": kind,
            "subscriber": subscriber,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
            "progress": 0.0,
            "current_checkpoint": None,
            "payload": payload,
            "checkpoints": {},
            "result": None,
            "error": None,
        }
        self._save_job(job)
        return job

    def _run_pipeline_job(
        self,
        job_id: str,
        subscriber: str,
        config: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        import run_pipeline

        args = SimpleNamespace(
            until=payload.get("until", "cp6"),
            reindex=payload.get("reindex", False),
            allow_sample_data=payload.get("allow_sample_data", False),
        )
        self._update_job(
            job_id,
            status="running",
            started_at=_now(),
            updated_at=_now(),
        )

        def progress_callback(snapshot: dict[str, Any]) -> None:
            checkpoints = snapshot.get("checkpoints", {})
            self._update_job(
                job_id,
                status="running",
                updated_at=_now(),
                checkpoints=checkpoints,
                current_checkpoint=_last_checkpoint_name(checkpoints),
                progress=_checkpoint_progress(args.until, checkpoints),
            )

        try:
            result = run_pipeline.run_subscriber(
                subscriber,
                config,
                args,
                progress_callback=progress_callback,
            )
            final_status = "completed" if result.get("status") == "completed" else "failed"
            self._update_job(
                job_id,
                status=final_status,
                updated_at=_now(),
                finished_at=_now(),
                progress=1.0,
                checkpoints=result.get("checkpoints", {}),
                current_checkpoint=_last_checkpoint_name(result.get("checkpoints", {})),
                result=result,
                error=result.get("error"),
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.error("[Jobs] pipeline job failed: %s", exc, exc_info=True)
            self._update_job(
                job_id,
                status="error",
                updated_at=_now(),
                finished_at=_now(),
                error=str(exc),
            )

    def _run_anchor_eval_job(
        self,
        job_id: str,
        subscriber: str,
        config: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        from app.eval_ops.anchor_eval import run_anchor_eval

        self._update_job(
            job_id,
            status="running",
            started_at=_now(),
            updated_at=_now(),
        )

        def progress_callback(snapshot: dict[str, Any]) -> None:
            self._update_job(
                job_id,
                status="running",
                updated_at=_now(),
                progress=snapshot.get("progress", 0.0),
                current_checkpoint=snapshot.get("current_case_id"),
                result={"summary": snapshot.get("summary", {}), "current_case_id": snapshot.get("current_case_id")},
            )

        try:
            result = run_anchor_eval(
                subscriber=subscriber,
                config=config,
                dataset_path=payload["dataset_path"],
                progress_callback=progress_callback,
            )
            self._update_job(
                job_id,
                status="completed",
                updated_at=_now(),
                finished_at=_now(),
                progress=1.0,
                result=result,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.error("[Jobs] anchor eval job failed: %s", exc, exc_info=True)
            self._update_job(
                job_id,
                status="error",
                updated_at=_now(),
                finished_at=_now(),
                error=str(exc),
            )

    def _load_existing_jobs(self) -> None:
        for path in self.storage_dir.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            self._jobs[job["id"]] = job

    def _save_job(self, job: dict[str, Any]) -> None:
        with self._lock:
            self._jobs[job["id"]] = deepcopy(job)
            path = self.storage_dir / f"{job['id']}.json"
            path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    def _update_job(self, job_id: str, **updates: Any) -> dict[str, Any]:
        with self._lock:
            job = deepcopy(self._jobs[job_id])
            job.update(updates)
            path = self.storage_dir / f"{job['id']}.json"
            path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
            self._jobs[job_id] = deepcopy(job)
            return deepcopy(job)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _last_checkpoint_name(checkpoints: dict[str, Any]) -> str | None:
    if not checkpoints:
        return None
    return list(checkpoints.keys())[-1]


def _checkpoint_progress(until: str, checkpoints: dict[str, Any]) -> float:
    from run_pipeline import CHECKPOINT_ORDER

    target_total = CHECKPOINT_ORDER.index(until) + 1
    completed = len(checkpoints)
    if target_total <= 0:
        return 0.0
    return round(min(1.0, completed / target_total), 2)
