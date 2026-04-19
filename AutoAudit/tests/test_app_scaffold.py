"""CP4~CP6 및 FastAPI 스캐폴드 회귀 테스트."""
from __future__ import annotations

import asyncio
import json
import sys
import time
import types
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.eval_ops import evaluate_case_expectations, summarize_anchor_eval
from app.cp4_evaluator import ClaudeJudge, ConsensusEvaluator, GPTJudge, GeminiJudge, JudgeScore
from app.cp4_evaluator.judges import JudgeStructuredOutput
from app.cp4_evaluator.preflight import build_live_readiness
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

    assert result.state == "DEGRADED"
    assert result.accuracy_mean is None
    assert result.overall_mean is None
    assert 0.0 <= result.support_accuracy_mean <= 5.0
    assert 0.0 <= result.support_overall_mean <= 5.0
    assert len(result.scores_detail) == 3
    assert result.review_required is True
    assert all(score.source == "heuristic" for score in result.scores_detail)


def test_placeholder_keys_skip_live_calls(monkeypatch):
    judge = GPTJudge(model="gpt-4o", api_key="sk-proj-xxxxxxxxxxxxxxxx")

    def _unexpected_live_call(self, turn_data):
        raise AssertionError("placeholder key should not trigger live call")

    monkeypatch.setattr(GPTJudge, "_evaluate_live", _unexpected_live_call)

    result = asyncio.run(
        judge.evaluate_async(
            {
                "user_query": "요금제를 변경하고 싶어요.",
                "bot_answer": "앱의 마이페이지에서 변경하시면 됩니다.",
                "context_text": "요금제 변경은 앱의 마이페이지에서 가능합니다.",
            }
        )
    )

    assert result.is_live is False
    assert result.source == "heuristic"
    assert result.error_reason == "missing_or_placeholder_api_key"


def test_judge_parser_accepts_structured_payload_dict():
    parsed = GPTJudge._parse_response(
        {
            "accuracy": 4.4,
            "fluency": 4.1,
            "groundedness": 4.3,
            "policy_compliance": 4.9,
            "task_completion": 4.2,
            "evidence_alignment": 4.5,
            "acc_reason": "정확합니다.",
            "flu_reason": "자연스럽습니다.",
            "reason_summary": "전반적으로 우수합니다.",
            "key_issues": [],
            "flow_issues": [],
            "risk_flags": [],
        },
        "gpt4o",
    )

    assert parsed.is_live is True
    assert parsed.source == "live"
    assert parsed.accuracy == 4.4
    assert parsed.reason_summary == "전반적으로 우수합니다."


def test_openai_live_judge_uses_responses_parse(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(
                id="resp_123",
                output_parsed=JudgeStructuredOutput(
                    accuracy=4.4,
                    fluency=4.2,
                    groundedness=4.5,
                    policy_compliance=4.9,
                    task_completion=4.3,
                    evidence_alignment=4.6,
                    acc_reason="근거와 일치합니다.",
                    flu_reason="자연스럽습니다.",
                    reason_summary="전반적으로 우수합니다.",
                    key_issues=[],
                    flow_issues=[],
                    risk_flags=[],
                ),
            )

    class FakeOpenAI:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.responses = FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))

    result = GPTJudge(model="gpt-4o", api_key="sk-live")._evaluate_live(
        {
            "user_query": "요금제를 변경하고 싶어요.",
            "bot_answer": "앱의 마이페이지에서 요금제 변경 메뉴를 선택하시면 됩니다.",
            "context_text": "요금제 변경은 앱 > 마이페이지 > 요금제 관리에서 가능합니다.",
        }
    )

    assert captured["api_key"] == "sk-live"
    assert captured["text_format"] is JudgeStructuredOutput
    assert result.is_live is True
    assert result.source == "live"
    assert result.provider_response_id == "resp_123"


def test_anthropic_live_judge_uses_forced_tool_schema(monkeypatch):
    captured: dict[str, object] = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(
                id="msg_123",
                content=[
                    types.SimpleNamespace(
                        type="tool_use",
                        input={
                            "accuracy": 4.3,
                            "fluency": 4.1,
                            "groundedness": 4.5,
                            "policy_compliance": 4.8,
                            "task_completion": 4.4,
                            "evidence_alignment": 4.6,
                            "acc_reason": "근거와 부합합니다.",
                            "flu_reason": "답변이 자연스럽습니다.",
                            "reason_summary": "전반적으로 우수합니다.",
                            "key_issues": [],
                            "flow_issues": [],
                            "risk_flags": [],
                        },
                    )
                ],
            )

    class FakeAnthropicClient:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropicClient))

    result = ClaudeJudge(model="claude-opus-4-6", api_key="sk-ant-live")._evaluate_live(
        {
            "user_query": "인터넷이 끊겨요.",
            "bot_answer": "모뎀 전원을 재부팅해 주세요.",
            "context_text": "인터넷 장애 시 모뎀 재부팅 후 원격 점검을 신청합니다.",
        }
    )

    assert captured["api_key"] == "sk-ant-live"
    assert captured["tool_choice"] == {"type": "tool", "name": "record_judge_score"}
    assert captured["tools"][0]["strict"] is True
    assert result.is_live is True
    assert result.provider_response_id == "msg_123"


def test_gemini_live_judge_uses_sanitized_schema(monkeypatch):
    captured: dict[str, object] = {}

    class FakeModels:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(
                response_id="gem_resp_123",
                parsed={
                    "accuracy": 4.2,
                    "fluency": 4.0,
                    "groundedness": 4.4,
                    "policy_compliance": 4.7,
                    "task_completion": 4.3,
                    "evidence_alignment": 4.5,
                    "acc_reason": "문서 근거와 일치합니다.",
                    "flu_reason": "표현이 자연스럽습니다.",
                    "reason_summary": "전반적으로 신뢰할 수 있습니다.",
                    "key_issues": [],
                    "flow_issues": [],
                    "risk_flags": [],
                },
            )

    class FakeClient:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.models = FakeModels()

    fake_genai_module = types.SimpleNamespace(Client=FakeClient)
    fake_google_module = types.ModuleType("google")
    fake_google_module.genai = fake_genai_module

    monkeypatch.setitem(sys.modules, "google", fake_google_module)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai_module)

    result = GeminiJudge(model="gemini-2.5-pro", api_key="AIza-live")._evaluate_live(
        {
            "user_query": "요금제 변경",
            "bot_answer": "앱에서 요금제 변경 메뉴를 선택해 주세요.",
            "context_text": "요금제 변경은 앱 > 마이페이지 > 요금제 관리 메뉴에서 가능합니다.",
        }
    )

    schema = captured["config"]["response_json_schema"]
    assert captured["api_key"] == "AIza-live"
    assert "additionalProperties" not in schema
    assert "title" not in schema
    assert result.is_live is True
    assert result.provider_response_id == "gem_resp_123"


def test_consensus_evaluator_produces_trusted_state_for_live_scores():
    class StubJudge:
        def __init__(self, model: str, accuracy: float):
            self.model = model
            self.accuracy = accuracy

        async def evaluate_async(self, turn_data):
            return JudgeScore(
                model=self.model,
                accuracy=self.accuracy,
                fluency=4.2,
                groundedness=4.4,
                policy_compliance=4.8,
                task_completion=4.3,
                evidence_alignment=4.5,
                acc_reason="근거 충분",
                flu_reason="자연스러움 양호",
                reason_summary="전반적으로 양호",
                source="live",
                is_live=True,
            )

    evaluator = ConsensusEvaluator(
        judges=[
            StubJudge("claude", 4.5),
            StubJudge("gpt4o", 4.3),
            StubJudge("gemini", 4.4),
        ]
    )

    result = asyncio.run(
        evaluator.evaluate(
            {
                "user_query": "요금제를 변경하고 싶어요.",
                "bot_answer": "앱에서 요금제 변경 메뉴를 선택해 주세요.",
                "context_text": "요금제 변경은 앱 > 마이페이지 > 요금제 관리 메뉴에서 가능합니다.",
                "retrieval": {
                    "top_chunks": [{"score": 0.95}],
                    "grounding_signals": {"grounding_risk": "low"},
                },
            }
        )
    )

    assert result.state == "TRUSTED"
    assert result.review_required is False
    assert result.all_judges_live is True
    assert result.overall_mean is not None
    assert result.accuracy_mean is not None


def test_live_readiness_passive_summary_marks_missing_keys():
    readiness = build_live_readiness(
        {
            "anthropic_api_key": "",
            "openai_api_key": "",
            "google_api_key": "",
            "claude_model": "claude-opus-4-6",
            "openai_model": "gpt-4o",
            "gemini_model": "gemini-1.5-pro",
        },
        probe_live=False,
    )

    assert readiness["summary"]["trusted_possible"] is False
    assert readiness["summary"]["providers_ready_count"] == 0
    assert all(item["status"] == "missing_key" for item in readiness["providers"])


def test_live_readiness_active_probe_reports_live_success(monkeypatch):
    monkeypatch.setattr(
        "app.cp4_evaluator.preflight.run_provider_probe",
        lambda judge_factory: {
            "status": "live_ok",
            "reason": "ok",
            "ready_for_live": True,
            "live_success": True,
            "latency_ms": 123.0,
            "provider_response_id": "resp_probe",
            "error_reason": None,
            "source": "live",
        },
    )

    readiness = build_live_readiness(
        {
            "anthropic_api_key": "sk-ant-live",
            "openai_api_key": "sk-live",
            "google_api_key": "AIza-live",
            "claude_model": "claude-opus-4-6",
            "openai_model": "gpt-4o",
            "gemini_model": "gemini-1.5-pro",
        },
        probe_live=True,
    )

    assert readiness["summary"]["trusted_possible"] is True
    assert readiness["summary"]["providers_ready_count"] == 3
    assert all(item["status"] == "live_ok" for item in readiness["providers"])


def test_anchor_eval_helper_summary():
    case_result = evaluate_case_expectations(
        case={
            "case_id": "anchor-1",
            "user_query": "요금제 변경",
            "bot_answer": "앱에서 가능합니다.",
            "expected_state": "TRUSTED",
            "expected_doc_type": "faq",
            "expected_terms": ["요금제", "변경"],
            "expected_risk_flags": ["MISSING_GROUNDING"],
            "min_support_overall": 2.0,
            "max_support_overall": 4.0,
        },
        context={
            "grounding_signals": {"grounding_risk": "medium"},
            "top_chunks": [
                {"doc_id": "faq-1", "doc_type": "faq", "text": "요금제 변경은 앱에서 가능합니다."}
            ],
        },
        consensus={
            "state": "TRUSTED",
            "support_overall_mean": 3.2,
            "scores_detail": [
                {"risk_flags": ["MISSING_GROUNDING"]},
            ],
        },
    )

    summary = summarize_anchor_eval([case_result])
    assert case_result["retrieval_hit"] is True
    assert case_result["state_match"] is True
    assert case_result["score_match"] is True
    assert case_result["risk_flag_match"] is True
    assert summary["retrieval_hit_rate"] == 1.0
    assert summary["state_match_rate"] == 1.0
    assert summary["avg_support_overall"] == 3.2


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
    assert report["summary"]["review_queue_size"] == 1
    assert report["summary"]["degraded_turns"] == 1

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
        lambda subscriber, cfg, args, progress_callback=None: {
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
    assert health.json()["live_consensus_ready"] is False

    readiness = client.get("/api/live-consensus/readiness")
    assert readiness.status_code == 200
    readiness_body = readiness.json()
    assert readiness_body["summary"]["trusted_possible"] is False
    assert readiness_body["providers"][0]["status"] == "missing_key"

    monkeypatch.setattr(
        "app.server.build_live_readiness",
        lambda cfg, probe_live=False: {
            "checked_at": "2026-04-19T19:00:00",
            "probe_mode": "active" if probe_live else "passive",
            "summary": {
                "trusted_possible": probe_live,
                "providers_ready_count": 3 if probe_live else 0,
                "provider_count": 3,
                "status": "live_ready" if probe_live else "attention_required",
            },
            "providers": [
                {
                    "provider": "claude",
                    "label": "Anthropic Claude",
                    "model": "claude-opus-4-6",
                    "configured": probe_live,
                    "sdk_package": "anthropic",
                    "sdk_version": "1.0.0",
                    "sdk_available": True,
                    "client_mode": "forced_tool_schema",
                    "checked_at": "2026-04-19T19:00:00",
                    "probe_attempted": probe_live,
                    "ready_for_live": probe_live,
                    "status": "live_ok" if probe_live else "missing_key",
                    "reason": "ok",
                    "live_success": probe_live,
                    "latency_ms": 120.0 if probe_live else None,
                    "provider_response_id": "resp_probe" if probe_live else None,
                    "error_reason": None,
                    "source": "live" if probe_live else None,
                }
            ],
        },
    )

    probe = client.post("/api/live-consensus/probe")
    assert probe.status_code == 200
    assert probe.json()["summary"]["trusted_possible"] is True

    readiness_after_probe = client.get("/api/live-consensus/readiness")
    assert readiness_after_probe.status_code == 200
    assert readiness_after_probe.json()["last_probe"]["summary"]["trusted_possible"] is True

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
                    "trusted_avg_accuracy": 4.2,
                    "trusted_avg_fluency": 4.1,
                    "trusted_avg_overall": 4.15,
                    "avg_accuracy": 4.2,
                    "avg_fluency": 4.1,
                    "avg_overall": 4.15,
                    "trusted_rate": 0.9,
                    "review_queue_size": 1,
                    "degraded_ratio": 0.05,
                    "incomplete_ratio": 0.0,
                    "uncertain_turns": 0,
                },
                "conversations": [],
                "review_queue": [
                    {
                        "conv_id": "conv-001",
                        "source_file": "sample_log.txt",
                        "turn_index": 1,
                        "user_query": "인터넷이 끊겨요.",
                        "bot_answer": "모뎀 재부팅 후 원격 점검을 신청해 주세요.",
                        "state": "DEGRADED",
                        "state_reason": "fallback 개입",
                        "overall_mean": None,
                        "support_overall_mean": 2.7,
                        "grounding_risk": "medium",
                        "top1_score": 0.82,
                        "live_judge_count": 0,
                        "fallback_judge_count": 3,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (results_dir / "cp4_evaluation_results.json").write_text(
        json.dumps(
            [
                {
                    "conv_id": "conv-001",
                    "source_file": "sample_log.txt",
                    "turn_index": 1,
                    "user_query": "인터넷이 끊겨요.",
                    "bot_answer": "모뎀 재부팅 후 원격 점검을 신청해 주세요.",
                    "context": {
                        "context_text": "[참조 1] 장애 시 모뎀 재부팅 후 원격 점검 신청",
                        "grounding_signals": {
                            "grounding_risk": "medium",
                            "top1_score": 0.82,
                            "score_gap": 0.03,
                        },
                        "top_chunks": [
                            {
                                "chunk_id": "chunk-1",
                                "doc_id": "faq-1",
                                "doc_type": "faq",
                                "score": 0.82,
                                "text": "장애 시 모뎀 재부팅 후 원격 점검 신청",
                                "parent_text": "장애 시 모뎀 재부팅 후 원격 점검 신청",
                            }
                        ],
                    },
                    "consensus": {
                        "state": "DEGRADED",
                        "state_reason": "fallback 개입",
                        "review_required": True,
                        "overall_mean": None,
                        "support_overall_mean": 2.7,
                        "live_judge_count": 0,
                        "fallback_judge_count": 3,
                        "scores_detail": [
                            {
                                "model": "claude",
                                "accuracy": 2.3,
                                "fluency": 3.1,
                                "groundedness": 2.0,
                                "policy_compliance": 4.7,
                                "task_completion": 2.8,
                                "evidence_alignment": 2.2,
                                "overall_score": 2.6,
                                "reason_summary": "근거가 약합니다.",
                                "key_issues": ["참조 문서와의 직접적 근거가 약함"],
                                "flow_issues": [],
                                "risk_flags": ["MISSING_GROUNDING"],
                                "source": "heuristic",
                            }
                        ],
                    },
                }
            ],
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
    assert latest_body["summary"]["summary"]["trusted_rate"] == 0.9
    assert latest_body["report_url"] == "/artifacts/테스트사/cp6_report.html"

    detail = client.get(
        "/api/subscribers/%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%82%AC/results/turn-detail",
        params={"conv_id": "conv-001", "turn_index": 1},
    )
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["state"] == "DEGRADED"
    assert detail_body["grounding_signals"]["grounding_risk"] == "medium"
    assert detail_body["top_chunks"][0]["doc_id"] == "faq-1"
    assert detail_body["judges"][0]["model"] == "claude"

    approve = client.post(
        "/api/subscribers/%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%82%AC/results/review-actions",
        json={
            "conv_id": "conv-001",
            "turn_index": 1,
            "action": "approve",
            "note": "운영자가 수동 확인 완료",
        },
    )
    assert approve.status_code == 200
    assert approve.json()["review_action"]["action"] == "approve"

    latest_after_approve = client.get("/api/subscribers/%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%82%AC/results/latest")
    assert latest_after_approve.status_code == 200
    latest_after_approve_body = latest_after_approve.json()
    assert latest_after_approve_body["summary"]["summary"]["review_queue_size"] == 0
    assert latest_after_approve_body["summary"]["summary"]["approved_review_count"] == 1
    assert latest_after_approve_body["summary"]["review_queue"][0]["review_status"] == "approved"

    detail_after_approve = client.get(
        "/api/subscribers/%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%82%AC/results/turn-detail",
        params={"conv_id": "conv-001", "turn_index": 1},
    )
    assert detail_after_approve.status_code == 200
    assert detail_after_approve.json()["review_action"]["action"] == "approve"
    assert len(detail_after_approve.json()["review_history"]) == 1

    assign = client.post(
        "/api/subscribers/%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%82%AC/results/review-actions",
        json={
            "conv_id": "conv-001",
            "turn_index": 1,
            "action": "assign",
            "assignee": "qa-owner@example.com",
            "note": "담당자 지정",
        },
    )
    assert assign.status_code == 200
    assert assign.json()["assignee"] == "qa-owner@example.com"
    assert assign.json()["review_status"] == "approved"

    recheck = client.post(
        "/api/subscribers/%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%82%AC/results/review-actions",
        json={
            "conv_id": "conv-001",
            "turn_index": 1,
            "action": "recheck",
            "note": "정책 변경 후 재평가",
            "assignee": "qa-owner@example.com",
        },
    )
    assert recheck.status_code == 200
    assert recheck.json()["pipeline_job"] is not None
    assert recheck.json()["review_action"]["pipeline_job_id"] == recheck.json()["pipeline_job"]["id"]
    recheck_job_id = recheck.json()["pipeline_job"]["id"]

    recheck_job_status = None
    for _ in range(20):
        recheck_job_status = client.get(f"/api/pipeline/jobs/{recheck_job_id}")
        assert recheck_job_status.status_code == 200
        if recheck_job_status.json()["status"] == "completed":
            break
        time.sleep(0.05)
    assert recheck_job_status.json()["status"] == "completed"

    latest_after_recheck = client.get("/api/subscribers/%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%82%AC/results/latest")
    assert latest_after_recheck.status_code == 200
    assert latest_after_recheck.json()["summary"]["summary"]["recheck_review_count"] == 1
    assert latest_after_recheck.json()["summary"]["summary"]["assigned_review_count"] == 1
    assert latest_after_recheck.json()["summary"]["summary"]["completed_recheck_count"] == 1
    assert latest_after_recheck.json()["summary"]["review_queue"][0]["review_history_count"] == 3
    assert latest_after_recheck.json()["summary"]["review_queue"][0]["assignee"] == "qa-owner@example.com"
    assert latest_after_recheck.json()["summary"]["review_queue"][0]["recheck_comparison"] is not None
    assert latest_after_recheck.json()["summary"]["review_queue"][0]["recheck_job"]["status"] == "completed"

    detail_after_recheck = client.get(
        "/api/subscribers/%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%82%AC/results/turn-detail",
        params={"conv_id": "conv-001", "turn_index": 1},
    )
    assert detail_after_recheck.status_code == 200
    detail_after_recheck_body = detail_after_recheck.json()
    assert len(detail_after_recheck_body["review_history"]) == 3
    assert detail_after_recheck_body["review_status"] == "recheck"
    assert detail_after_recheck_body["assignee"] == "qa-owner@example.com"
    assert detail_after_recheck_body["recheck_job"]["status"] == "completed"
    assert detail_after_recheck_body["recheck_comparison"]["before"]["state"] == "DEGRADED"
    assert detail_after_recheck_body["recheck_comparison"]["before"]["judges"][0]["model"] == "claude"
    assert detail_after_recheck_body["recheck_comparison"]["before"]["top_chunks"][0]["id"] == "faq-1"

    review_ops = client.get("/api/dashboard/review-ops")
    assert review_ops.status_code == 200
    review_ops_body = review_ops.json()
    assert review_ops_body["overview"]["completed_recheck_count"] == 1
    assert review_ops_body["assignees"][0]["assignee"] == "qa-owner@example.com"
    assert review_ops_body["recent_rechecks"][0]["job_id"] == recheck_job_id


def test_async_pipeline_and_anchor_jobs(tmp_path, monkeypatch):
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
    import app.eval_ops.anchor_eval as anchor_eval_module

    def fake_run_subscriber(subscriber, cfg, args, progress_callback=None):
        if progress_callback:
            progress_callback(
                {
                    "subscriber": subscriber,
                    "status": "running",
                    "checkpoints": {"cp1": {"status": "done"}},
                }
            )
        return {
            "subscriber": subscriber,
            "status": "completed",
            "checkpoints": {"cp1": {"status": "done"}, "cp2": {"status": "done"}},
            "elapsed_sec": 0.1,
        }

    def fake_run_anchor_eval(subscriber, config, dataset_path, progress_callback=None):
        if progress_callback:
            progress_callback(
                {
                    "progress": 0.5,
                    "current_case_id": "anchor-1",
                    "summary": {"retrieval_hit_rate": 1.0},
                }
            )
        result = {
            "subscriber": subscriber,
            "dataset_path": dataset_path,
            "case_count": 1,
            "summary": {"retrieval_hit_rate": 1.0, "state_match_rate": 0.5},
            "cases": [],
        }
        output_dir = Path(config["results_dir"]) / subscriber
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "anchor_eval_report.json").write_text(
            json.dumps(result, ensure_ascii=False),
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(run_pipeline, "run_subscriber", fake_run_subscriber)
    monkeypatch.setattr(anchor_eval_module, "run_anchor_eval", fake_run_anchor_eval)

    app = create_app(config)
    client = TestClient(app)

    pipeline_job = client.post(
        "/api/pipeline/jobs",
        json={
            "subscriber": "테스트사",
            "until": "cp3",
            "reindex": False,
            "allow_sample_data": False,
        },
    )
    assert pipeline_job.status_code == 200
    job_id = pipeline_job.json()["id"]

    pipeline_status = None
    for _ in range(20):
        pipeline_status = client.get(f"/api/pipeline/jobs/{job_id}")
        assert pipeline_status.status_code == 200
        body = pipeline_status.json()
        if body["status"] == "completed":
            break
        time.sleep(0.05)
    assert pipeline_status.json()["status"] == "completed"
    assert pipeline_status.json()["checkpoints"]["cp2"]["status"] == "done"

    pipeline_events = client.get(f"/api/pipeline/jobs/{job_id}/events")
    assert pipeline_events.status_code == 200
    assert "event: job" in pipeline_events.text
    assert '"status": "completed"' in pipeline_events.text

    listed_jobs = client.get("/api/pipeline/jobs", params={"subscriber": "테스트사"})
    assert listed_jobs.status_code == 200
    assert listed_jobs.json()[0]["id"] == job_id

    anchor_job = client.post(
        "/api/evals/anchor/jobs",
        json={
            "subscriber": "테스트사",
            "dataset_path": "AutoAudit/examples/anchor_eval.sample.jsonl",
        },
    )
    assert anchor_job.status_code == 200
    anchor_job_id = anchor_job.json()["id"]

    anchor_status = None
    for _ in range(20):
        anchor_status = client.get(f"/api/evals/anchor/jobs/{anchor_job_id}")
        assert anchor_status.status_code == 200
        body = anchor_status.json()
        if body["status"] == "completed":
            break
        time.sleep(0.05)
    assert anchor_status.json()["status"] == "completed"
    assert anchor_status.json()["result"]["summary"]["retrieval_hit_rate"] == 1.0

    anchor_events = client.get(f"/api/evals/anchor/jobs/{anchor_job_id}/events")
    assert anchor_events.status_code == 200
    assert "event: job" in anchor_events.text
    assert '"status": "completed"' in anchor_events.text

    latest_anchor = client.get("/api/subscribers/%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%82%AC/evals/anchor/latest")
    assert latest_anchor.status_code == 200
    assert latest_anchor.json()["summary"]["retrieval_hit_rate"] == 1.0
