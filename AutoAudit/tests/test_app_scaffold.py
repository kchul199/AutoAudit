"""CP4~CP6 및 FastAPI 스캐폴드 회귀 테스트."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.cp4_evaluator import ClaudeJudge, ConsensusEvaluator, GPTJudge, GeminiJudge
from app.cp5_aggregator import StatsAggregator
from app.cp6_reporter import ConfluenceReporter
from app.server import create_app


def test_consensus_evaluator_runs_without_live_api_keys():
    evaluator = ConsensusEvaluator(
        judges=[
            ClaudeJudge(model="claude-opus-4-6", api_key=""),
            GPTJudge(model="gpt-4o", api_key=""),
            GeminiJudge(model="gemini-1.5-pro", api_key=""),
        ]
    )

    result = asyncio.run(
        evaluator.evaluate(
            {
                "user_query": "요금제를 변경하고 싶어요.",
                "bot_answer": "앱의 마이페이지에서 요금제 변경 메뉴를 선택하시면 됩니다.",
                "context_text": "요금제 변경은 앱 > 마이페이지 > 요금제 관리 > 요금제 변경 메뉴에서 가능합니다.",
            }
        )
    )

    assert 0.0 <= result.accuracy_mean <= 5.0
    assert 0.0 <= result.fluency_mean <= 5.0
    assert len(result.scores_detail) == 3
    assert all(score.source == "heuristic" for score in result.scores_detail)


def test_cp5_and_cp6_generate_local_artifacts(tmp_path):
    subscriber = "테스트사"
    evaluator = ConsensusEvaluator(
        judges=[
            ClaudeJudge(model="claude-opus-4-6", api_key=""),
            GPTJudge(model="gpt-4o", api_key=""),
            GeminiJudge(model="gemini-1.5-pro", api_key=""),
        ]
    )
    consensus = asyncio.run(
        evaluator.evaluate(
            {
                "user_query": "인터넷이 끊겨요.",
                "bot_answer": "모뎀 전원을 30초 정도 껐다가 다시 켜 보신 뒤에도 문제가 있으면 원격 점검을 신청해 주세요.",
                "context_text": "인터넷 장애 시 1. 모뎀 재부팅 2. 지속 시 기술 상담사 원격 점검 신청",
            }
        )
    )
    turn_results = [
        {
            "conv_id": "conv-001",
            "source_file": "sample_log.txt",
            "turn_index": 1,
            "user_query": "인터넷이 끊겨요.",
            "bot_answer": "모뎀 전원을 30초 정도 껐다가 다시 켜 보신 뒤에도 문제가 있으면 원격 점검을 신청해 주세요.",
            "context": {"top_chunks": []},
            "consensus": consensus.to_dict(),
        }
    ]

    aggregator = StatsAggregator(results_dir=str(tmp_path))
    report = aggregator.aggregate(subscriber, turn_results)

    summary_path = tmp_path / subscriber / "cp5_summary.json"
    assert summary_path.exists()
    assert report["summary"]["total_conversations"] == 1

    reporter = ConfluenceReporter(
        config={
            "confluence_url": "",
            "confluence_email": "",
            "confluence_token": "",
            "confluence_space_key": "CALLBOT",
            "confluence_parent_page_id": "",
        },
        results_dir=str(tmp_path),
    )
    publish_result = reporter.publish(
        subscriber,
        report,
        chart_paths=[str(tmp_path / subscriber / name) for name in report["chart_paths"]],
    )

    assert publish_result["status"] == "local_only"
    assert (tmp_path / subscriber / "cp6_report.html").exists()
    assert (tmp_path / subscriber / "cp6_publish_result.json").exists()


def test_fastapi_server_scaffold_endpoints(tmp_path, monkeypatch):
    config = {
        "results_dir": str(tmp_path / "results"),
        "doc_dir": str(tmp_path / "docs"),
        "log_dir": str(tmp_path / "logs"),
        "chroma_persist_dir": str(tmp_path / "chroma"),
        "openai_api_key": "",
        "openai_model": "gpt-4o",
        "anthropic_api_key": "",
        "claude_model": "claude-opus-4-6",
        "google_api_key": "",
        "gemini_model": "gemini-1.5-pro",
        "embedding_model": "text-embedding-3-large",
        "local_embedding_model": "all-MiniLM-L6-v2",
        "child_chunk_size": 200,
        "parent_chunk_size": 800,
        "top_k_first_stage": 20,
        "top_k_final": 5,
        "num_query_variants": 3,
        "hyde_enabled": True,
        "cross_encoder_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "uncertainty_threshold": 1.5,
        "confluence_url": "",
        "confluence_email": "",
        "confluence_token": "",
        "confluence_space_key": "CALLBOT",
        "confluence_parent_page_id": "",
    }

    import run_pipeline

    monkeypatch.setattr(
        run_pipeline,
        "run_subscriber",
        lambda subscriber, cfg, args: {
            "subscriber": subscriber,
            "status": "completed",
            "checkpoints": {"cp6": {"status": "local_only"}},
        },
    )

    app = create_app(config)
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    created = client.post(
        "/api/subscribers",
        json={
            "name": "테스트사",
            "industry": "통신",
            "contact": "qa@example.com",
            "desc": "회귀 테스트",
        },
    )
    assert created.status_code == 200

    doc_upload = client.post(
        "/api/subscribers/%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%82%AC/documents/upload",
        files=[("files", ("faq.txt", "Q: 요금제 변경?\nA: 앱에서 가능합니다.".encode("utf-8"), "text/plain"))],
    )
    assert doc_upload.status_code == 200
    assert doc_upload.json()["count"] == 1

    log_upload = client.post(
        "/api/subscribers/%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%82%AC/logs/upload",
        files=[("files", ("log.txt", "고객: 문의\n콜봇: 안내".encode("utf-8"), "text/plain"))],
    )
    assert log_upload.status_code == 200
    assert log_upload.json()["count"] == 1

    subscribers = client.get("/api/subscribers")
    assert subscribers.status_code == 200
    body = subscribers.json()
    assert body[0]["docsCount"] == 1
    assert body[0]["logsCount"] == 1

    run_response = client.post(
        "/api/pipeline/run",
        json={
            "subscriber": "테스트사",
            "until": "cp6",
            "reindex": False,
            "allow_sample_data": False,
        },
    )
    assert run_response.status_code == 200
    assert run_response.json()["status"] == "completed"

    results_dir = Path(config["results_dir"]) / "테스트사"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "cp5_summary.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-04-19T01:00:00",
                "summary": {
                    "avg_accuracy": 4.2,
                    "avg_fluency": 4.1,
                    "avg_overall": 4.15,
                    "uncertain_count": 0,
                },
                "conversations": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (results_dir / "cp6_publish_result.json").write_text(
        json.dumps({"status": "local_only"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (results_dir / "cp6_report.html").write_text("<html>ok</html>", encoding="utf-8")

    latest = client.get("/api/subscribers/%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%82%AC/results/latest")
    assert latest.status_code == 200
    latest_body = latest.json()
    assert latest_body["summary"]["summary"]["avg_overall"] == 4.15
    assert latest_body["report_url"] == "/artifacts/테스트사/cp6_report.html"
