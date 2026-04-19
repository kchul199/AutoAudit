"""CP4 live Multi-LLM readiness / probe helpers."""
from __future__ import annotations

import asyncio
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from app.cp4_evaluator.judges import ClaudeJudge, GPTJudge, GeminiJudge

PROBE_TURN_DATA = {
    "user_query": "요금제 변경은 어떻게 하나요?",
    "bot_answer": "앱의 마이페이지에서 요금제 관리 메뉴를 선택하면 됩니다.",
    "context_text": (
        "요금제 변경은 고객센터 앱 > 마이페이지 > 요금제 관리 > 요금제 변경 메뉴에서 가능합니다. "
        "변경은 즉시 적용되며 당월 요금은 일할 계산됩니다."
    ),
}


def build_live_readiness(config: dict[str, Any], probe_live: bool = False) -> dict[str, Any]:
    providers = [
        {
            "provider": "claude",
            "label": "Anthropic Claude",
            "model": config.get("claude_model", "claude-opus-4-6"),
            "api_key": config.get("anthropic_api_key", ""),
            "sdk_package": "anthropic",
            "client_mode": "forced_tool_schema",
            "judge_factory": lambda: ClaudeJudge(
                model=config.get("claude_model", "claude-opus-4-6"),
                api_key=config.get("anthropic_api_key", ""),
            ),
        },
        {
            "provider": "gpt4o",
            "label": "OpenAI GPT",
            "model": config.get("openai_model", "gpt-4o"),
            "api_key": config.get("openai_api_key", ""),
            "sdk_package": "openai",
            "client_mode": "responses_parse",
            "judge_factory": lambda: GPTJudge(
                model=config.get("openai_model", "gpt-4o"),
                api_key=config.get("openai_api_key", ""),
            ),
        },
        {
            "provider": "gemini",
            "label": "Google Gemini",
            "model": config.get("gemini_model", "gemini-1.5-pro"),
            "api_key": config.get("google_api_key", ""),
            "sdk_package": "google-genai",
            "client_mode": "json_schema",
            "judge_factory": lambda: GeminiJudge(
                model=config.get("gemini_model", "gemini-1.5-pro"),
                api_key=config.get("google_api_key", ""),
            ),
        },
    ]

    snapshots = [_provider_snapshot(item, probe_live=probe_live) for item in providers]
    all_keys_configured = all(item["configured"] for item in snapshots)
    all_sdks_available = all(item["sdk_available"] for item in snapshots)
    all_providers_ready = all(item["ready_for_live"] for item in snapshots)

    return {
        "checked_at": _now_iso(),
        "probe_mode": "active" if probe_live else "passive",
        "summary": {
            "all_keys_configured": all_keys_configured,
            "all_sdks_available": all_sdks_available,
            "all_providers_ready": all_providers_ready,
            "providers_ready_count": sum(1 for item in snapshots if item["ready_for_live"]),
            "provider_count": len(snapshots),
            "trusted_possible": all_providers_ready,
            "status": "live_ready" if all_providers_ready else "attention_required",
        },
        "providers": snapshots,
    }


def _provider_snapshot(provider: dict[str, Any], probe_live: bool) -> dict[str, Any]:
    sdk_version = _package_version(provider["sdk_package"])
    configured = bool(provider["api_key"])
    sdk_available = sdk_version is not None
    base = {
        "provider": provider["provider"],
        "label": provider["label"],
        "model": provider["model"],
        "configured": configured,
        "sdk_package": provider["sdk_package"],
        "sdk_version": sdk_version,
        "sdk_available": sdk_available,
        "client_mode": provider["client_mode"],
        "checked_at": _now_iso(),
        "probe_attempted": probe_live,
        "ready_for_live": False,
        "status": "missing_key",
        "reason": "API 키가 없습니다.",
        "live_success": False,
        "latency_ms": None,
        "provider_response_id": None,
        "error_reason": None,
        "source": None,
    }

    if not configured:
        return base
    if not sdk_available:
        base.update(
            status="sdk_missing",
            reason=f"{provider['sdk_package']} 패키지가 설치되지 않았습니다.",
        )
        return base
    if not probe_live:
        base.update(
            status="ready_to_probe",
            reason="키와 SDK가 준비되었습니다. active probe로 live 경로를 검증할 수 있습니다.",
            ready_for_live=True,
        )
        return base

    probe = run_provider_probe(provider["judge_factory"])
    base.update(probe)
    return base


def run_provider_probe(judge_factory) -> dict[str, Any]:
    judge = judge_factory()
    result = asyncio.run(judge.evaluate_async(PROBE_TURN_DATA))
    if result.is_live:
        return {
            "status": "live_ok",
            "reason": "구조화 live 평가가 정상 동작했습니다.",
            "ready_for_live": True,
            "live_success": True,
            "latency_ms": result.latency_ms,
            "provider_response_id": result.provider_response_id,
            "error_reason": None,
            "source": result.source,
        }
    return {
        "status": "degraded",
        "reason": "live 평가가 fallback으로 대체되었습니다.",
        "ready_for_live": False,
        "live_success": False,
        "latency_ms": result.latency_ms,
        "provider_response_id": result.provider_response_id,
        "error_reason": result.error_reason,
        "source": result.source,
    }


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
