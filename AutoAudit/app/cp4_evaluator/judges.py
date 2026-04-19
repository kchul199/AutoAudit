"""CP4 — 개별 Judge 구현."""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.utils.logger import get_logger

logger = get_logger(__name__)

TOKEN_RE = re.compile(r"[가-힣]{2,}|[a-zA-Z]{2,}|\d+")
POLICY_RISK_RE = re.compile(r"(무조건|반드시|절대|확실히|100%)")
PROMPT_VERSION = "cp4_v4_live_consensus"
OUTPUT_SCHEMA_NAME = "callbot_quality_judge"
ANTHROPIC_TOOL_NAME = "record_judge_score"
PLACEHOLDER_MARKERS = (
    "xxxxxxxx",
    "xxxxxx",
    "your-",
    "your_",
    "replace",
    "example",
    "changeme",
    "<api",
    "<your",
)


class JudgeStructuredOutput(BaseModel):
    accuracy: float = Field(ge=0, le=5)
    fluency: float = Field(ge=0, le=5)
    groundedness: float = Field(ge=0, le=5)
    policy_compliance: float = Field(ge=0, le=5)
    task_completion: float = Field(ge=0, le=5)
    evidence_alignment: float = Field(ge=0, le=5)
    acc_reason: str = Field(min_length=1)
    flu_reason: str = Field(min_length=1)
    reason_summary: str = Field(min_length=1)
    key_issues: list[str] = Field(default_factory=list)
    flow_issues: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)

    model_config = {
        "extra": "forbid",
    }


@dataclass
class JudgeScore:
    model: str
    accuracy: float
    fluency: float
    groundedness: float
    policy_compliance: float
    task_completion: float
    evidence_alignment: float
    acc_reason: str
    flu_reason: str
    reason_summary: str
    key_issues: list[str] = field(default_factory=list)
    flow_issues: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    source: str = "heuristic"
    is_live: bool = False
    prompt_version: str = PROMPT_VERSION
    provider_response_id: str | None = None
    error_reason: str | None = None
    latency_ms: float | None = None

    @property
    def overall_score(self) -> float:
        total = (
            0.35 * self.accuracy
            + 0.30 * self.groundedness
            + 0.20 * self.task_completion
            + 0.10 * self.policy_compliance
            + 0.05 * self.fluency
        )
        return round(total, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "accuracy": round(self.accuracy, 2),
            "fluency": round(self.fluency, 2),
            "groundedness": round(self.groundedness, 2),
            "policy_compliance": round(self.policy_compliance, 2),
            "task_completion": round(self.task_completion, 2),
            "evidence_alignment": round(self.evidence_alignment, 2),
            "overall_score": self.overall_score,
            "acc_reason": self.acc_reason,
            "flu_reason": self.flu_reason,
            "reason_summary": self.reason_summary,
            "key_issues": self.key_issues,
            "flow_issues": self.flow_issues,
            "risk_flags": self.risk_flags,
            "source": self.source,
            "is_live": self.is_live,
            "prompt_version": self.prompt_version,
            "provider_response_id": self.provider_response_id,
            "error_reason": self.error_reason,
            "latency_ms": self.latency_ms,
        }


class BaseJudge:
    """공통 Judge 베이스 클래스."""

    provider_name = "judge"

    def __init__(
        self,
        model: str,
        api_key: str = "",
        max_tokens: int = 1000,
    ):
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens

    async def evaluate_async(self, turn_data: dict[str, Any]) -> JudgeScore:
        started_at = time.perf_counter()

        if not _api_key_is_usable(self.api_key):
            score = self._evaluate_heuristic(
                turn_data,
                error_reason="missing_or_placeholder_api_key",
            )
            score.latency_ms = _elapsed_ms(started_at)
            return score

        try:
            score = await asyncio.to_thread(self._evaluate_live, turn_data)
            score.is_live = True
            score.source = "live"
            score.latency_ms = _elapsed_ms(started_at)
            return score
        except Exception as exc:
            logger.warning(
                f"[CP4] {self.provider_name} live 평가 실패 — fallback으로 대체: {exc}"
            )
            score = self._evaluate_heuristic(
                turn_data,
                error_reason=_normalize_error(exc),
            )
            score.latency_ms = _elapsed_ms(started_at)
            return score

    def _evaluate_live(self, turn_data: dict[str, Any]) -> JudgeScore:
        raise NotImplementedError

    def _evaluate_heuristic(
        self,
        turn_data: dict[str, Any],
        error_reason: str | None = None,
    ) -> JudgeScore:
        user_query = turn_data.get("user_query", "")
        bot_answer = turn_data.get("bot_answer", "")
        context_text = turn_data.get("context_text", "")
        score = _heuristic_score(
            model=self.provider_name,
            user_query=user_query,
            bot_answer=bot_answer,
            context_text=context_text,
        )
        return JudgeScore(
            model=self.provider_name,
            accuracy=score["accuracy"],
            fluency=score["fluency"],
            groundedness=score["groundedness"],
            policy_compliance=score["policy_compliance"],
            task_completion=score["task_completion"],
            evidence_alignment=score["evidence_alignment"],
            acc_reason=score["acc_reason"],
            flu_reason=score["flu_reason"],
            reason_summary=score["reason_summary"],
            key_issues=score["key_issues"],
            flow_issues=score["flow_issues"],
            risk_flags=score["risk_flags"],
            source="heuristic",
            is_live=False,
            error_reason=error_reason,
        )

    @staticmethod
    def _response_schema() -> dict[str, Any]:
        schema = JudgeStructuredOutput.model_json_schema()
        schema["additionalProperties"] = False
        return schema

    @classmethod
    def _provider_response_schema(cls, provider_name: str) -> dict[str, Any]:
        schema = cls._response_schema()
        if provider_name == "gemini":
            return _sanitize_schema(
                schema,
                drop_keys={
                    "additionalProperties",
                    "default",
                    "examples",
                    "title",
                    "propertyOrdering",
                },
            )
        if provider_name == "claude":
            return _sanitize_schema(
                schema,
                drop_keys={"default", "examples", "title"},
            )
        return schema

    @staticmethod
    def _system_prompt() -> str:
        return (
            "당신은 콜봇 품질 평가 전문가입니다. "
            "제공된 근거 외에는 추정하지 말고, 근거가 약하면 낮은 점수를 주세요. "
            "출력은 반드시 구조화된 평가 결과만 반환하세요."
        )

    @staticmethod
    def _build_prompt(turn_data: dict[str, Any]) -> str:
        context_text = turn_data.get("context_text", "")
        return f"""당신은 콜봇 품질 평가 전문가입니다.
다음 고객 질문, 콜봇 답변, 참조 컨텍스트를 바탕으로 엄격하게 평가하세요.

[고객 질문]
{turn_data.get("user_query", "")}

[콜봇 답변]
{turn_data.get("bot_answer", "")}

[참조 컨텍스트]
{context_text[:5000] if context_text else "참조 없음"}

[평가 규칙]
- accuracy: 답변이 질문에 맞고 사실적으로 맞는가
- groundedness: 답변이 참조 컨텍스트에 근거하는가
- policy_compliance: 과도한 단정, 위험 안내, 정책 위반 가능성이 없는가
- task_completion: 고객이 바로 행동할 수 있을 정도로 안내가 충분한가
- fluency: 문장 흐름이 자연스러운가
- evidence_alignment: 참조 근거와 답변 핵심 문장이 얼마나 정렬되는가

[세부 지침]
- 모든 점수는 0~5 범위의 실수로 작성
- key_issues / flow_issues / risk_flags는 최대 3개 정도로 간결하게 작성
- 참조 없음 또는 근거 부족 시 groundedness / evidence_alignment를 낮게 평가
- risk_flags에는 예: MISSING_GROUNDING, LOW_QUERY_ALIGNMENT, POTENTIAL_POLICY_RISK 같은 짧은 식별자를 사용
"""

    @classmethod
    def _anthropic_tool_definition(cls) -> dict[str, Any]:
        return {
            "name": ANTHROPIC_TOOL_NAME,
            "description": (
                "Return the final callbot quality evaluation as strictly structured JSON."
            ),
            "input_schema": cls._provider_response_schema("claude"),
            "input_examples": [
                {
                    "accuracy": 4.4,
                    "fluency": 4.1,
                    "groundedness": 4.5,
                    "policy_compliance": 4.8,
                    "task_completion": 4.3,
                    "evidence_alignment": 4.6,
                    "acc_reason": "근거 문서와 답변이 잘 일치합니다.",
                    "flu_reason": "문장이 자연스럽습니다.",
                    "reason_summary": "근거성과 절차 안내가 전반적으로 우수합니다.",
                    "key_issues": [],
                    "flow_issues": [],
                    "risk_flags": [],
                }
            ],
            "strict": True,
        }

    @staticmethod
    def _parse_response(payload: Any, model_name: str) -> JudgeScore:
        data = _normalize_payload(payload)
        validated = JudgeStructuredOutput.model_validate(data)
        return JudgeScore(
            model=model_name,
            accuracy=_clamp_score(validated.accuracy),
            fluency=_clamp_score(validated.fluency),
            groundedness=_clamp_score(validated.groundedness),
            policy_compliance=_clamp_score(validated.policy_compliance),
            task_completion=_clamp_score(validated.task_completion),
            evidence_alignment=_clamp_score(validated.evidence_alignment),
            acc_reason=str(validated.acc_reason),
            flu_reason=str(validated.flu_reason),
            reason_summary=str(validated.reason_summary),
            key_issues=_ensure_list(validated.key_issues),
            flow_issues=_ensure_list(validated.flow_issues),
            risk_flags=_ensure_list(validated.risk_flags),
            source="live",
            is_live=True,
        )


class ClaudeJudge(BaseJudge):
    provider_name = "claude"

    def _evaluate_live(self, turn_data: dict[str, Any]) -> JudgeScore:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0,
            system=self._system_prompt(),
            tools=[self._anthropic_tool_definition()],
            tool_choice={"type": "tool", "name": ANTHROPIC_TOOL_NAME},
            messages=[{"role": "user", "content": self._build_prompt(turn_data)}],
        )

        payload = _extract_anthropic_tool_input(response)
        score = self._parse_response(payload, self.provider_name)
        score.provider_response_id = getattr(response, "id", None)
        return score


class GPTJudge(BaseJudge):
    provider_name = "gpt4o"

    def _evaluate_live(self, turn_data: dict[str, Any]) -> JudgeScore:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.responses.parse(
            model=self.model,
            instructions=self._system_prompt(),
            input=self._build_prompt(turn_data),
            text_format=JudgeStructuredOutput,
            max_output_tokens=self.max_tokens,
            temperature=0,
            prompt_cache_key=f"{OUTPUT_SCHEMA_NAME}:{PROMPT_VERSION}:{self.provider_name}",
        )

        payload = getattr(response, "output_parsed", None)
        if payload is None:
            raise ValueError("OpenAI structured output이 비어 있습니다.")

        score = self._parse_response(payload, self.provider_name)
        score.provider_response_id = getattr(response, "id", None)
        return score


class GeminiJudge(BaseJudge):
    provider_name = "gemini"

    def _evaluate_live(self, turn_data: dict[str, Any]) -> JudgeScore:
        try:
            from google import genai
        except ImportError:
            return self._evaluate_live_legacy(turn_data)

        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model,
            contents=self._build_prompt(turn_data),
            config={
                "system_instruction": self._system_prompt(),
                "temperature": 0,
                "max_output_tokens": self.max_tokens,
                "response_mime_type": "application/json",
                "response_json_schema": self._provider_response_schema("gemini"),
            },
        )
        payload = getattr(response, "parsed", None) or getattr(response, "text", "{}")
        score = self._parse_response(payload, self.provider_name)
        score.provider_response_id = getattr(response, "response_id", None)
        return score

    def _evaluate_live_legacy(self, turn_data: dict[str, Any]) -> JudgeScore:
        import google.generativeai as legacy_genai

        legacy_genai.configure(api_key=self.api_key)
        model = legacy_genai.GenerativeModel(
            self.model,
            system_instruction=self._system_prompt(),
        )
        response = model.generate_content(
            self._build_prompt(turn_data),
            generation_config=legacy_genai.types.GenerationConfig(
                temperature=0,
                max_output_tokens=self.max_tokens,
                response_mime_type="application/json",
                response_schema=self._provider_response_schema("gemini"),
            ),
        )
        payload = getattr(response, "text", "") or "{}"
        return self._parse_response(payload, self.provider_name)


def _heuristic_score(
    model: str,
    user_query: str,
    bot_answer: str,
    context_text: str,
) -> dict[str, Any]:
    answer_tokens = _tokenize(bot_answer)
    query_tokens = _tokenize(user_query)
    context_tokens = _tokenize(context_text)

    answer_set = set(answer_tokens)
    query_set = set(query_tokens)
    context_set = set(context_tokens)

    query_overlap = _overlap_ratio(answer_set, query_set)
    context_overlap = _overlap_ratio(answer_set, context_set)
    length = len(bot_answer.strip())
    length_score = 1.0 if 24 <= length <= 420 else 0.75 if 12 <= length <= 520 else 0.45
    polite_score = 1.0 if re.search(r"(습니다|세요|입니다|드립니다|해드리)", bot_answer) else 0.7
    step_score = 1.0 if re.search(r"(1\.|1단계|메뉴|신청|문의|확인)", bot_answer) else 0.72
    risk_penalty = 0.5 if POLICY_RISK_RE.search(bot_answer) else 0.0

    grounded_score = 0.72 * context_overlap + 0.28 * query_overlap
    accuracy = 1.1 + 3.5 * grounded_score - risk_penalty
    groundedness = 1.0 + 3.8 * context_overlap - risk_penalty
    task_completion = 1.2 + 2.0 * query_overlap + 1.0 * step_score + 0.5 * length_score
    policy_compliance = 4.6 - 1.4 * risk_penalty - (0.4 if not context_text.strip() else 0.0)
    evidence_alignment = 1.0 + 3.9 * context_overlap
    fluency = 1.3 + 1.9 * query_overlap + 0.9 * length_score + 0.7 * polite_score

    if len(answer_tokens) < 4:
        accuracy -= 0.3
        groundedness -= 0.3
        task_completion -= 0.5
        fluency -= 0.4

    if model == "gpt4o":
        accuracy += 0.08 if query_overlap >= 0.25 else -0.05
        policy_compliance += 0.05
    elif model == "gemini":
        groundedness += 0.08 if len(context_tokens) > 30 else -0.05
        fluency += 0.08 if 40 <= length <= 300 else -0.08
    else:  # claude
        evidence_alignment += 0.10 if context_overlap >= 0.22 else 0.0
        task_completion += 0.05 if step_score >= 1.0 else 0.0

    key_issues = []
    flow_issues = []
    risk_flags = []

    if context_overlap < 0.18:
        key_issues.append("참조 문서와의 직접적 근거가 약함")
        risk_flags.append("MISSING_GROUNDING")
    if query_overlap < 0.15:
        flow_issues.append("고객 질문과의 연결성이 약함")
        risk_flags.append("LOW_QUERY_ALIGNMENT")
    if length < 18:
        flow_issues.append("답변이 너무 짧아 안내가 불충분함")
        risk_flags.append("LOW_TASK_COMPLETION")
    if POLICY_RISK_RE.search(bot_answer):
        key_issues.append("과도하게 단정적인 표현이 포함될 수 있음")
        risk_flags.append("POTENTIAL_POLICY_RISK")
    if not re.search(r"[.!?]|[다요까]\s*$", bot_answer):
        flow_issues.append("문장 마무리가 다소 어색함")

    acc_reason = (
        "참조 컨텍스트와 핵심 키워드가 충분히 겹쳐 사실 근거가 비교적 뚜렷합니다."
        if context_overlap >= 0.3
        else "질문과 일부 관련은 있지만 참조 컨텍스트와의 직접적 일치가 제한적입니다."
    )
    flu_reason = (
        "질문과의 연결이 자연스럽고 답변 길이도 적절합니다."
        if query_overlap >= 0.25 and 24 <= length <= 420
        else "질문과의 연결 또는 답변 구성에서 다소 어색한 부분이 있습니다."
    )
    reason_summary = (
        "근거성과 절차 안내가 전반적으로 양호합니다."
        if context_overlap >= 0.3 and step_score >= 1.0
        else "근거성 또는 안내 완결성에서 보완이 필요한 답변입니다."
    )

    return {
        "accuracy": _clamp_score(accuracy),
        "fluency": _clamp_score(fluency),
        "groundedness": _clamp_score(groundedness),
        "policy_compliance": _clamp_score(policy_compliance),
        "task_completion": _clamp_score(task_completion),
        "evidence_alignment": _clamp_score(evidence_alignment),
        "acc_reason": acc_reason,
        "flu_reason": flu_reason,
        "reason_summary": reason_summary,
        "key_issues": key_issues[:3],
        "flow_issues": flow_issues[:3],
        "risk_flags": list(dict.fromkeys(risk_flags))[:4],
    }


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


def _overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left))


def _clamp_score(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return round(max(0.0, min(5.0, numeric)), 2)


def _ensure_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None:
        return []
    return [str(value)]


def _normalize_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, BaseModel):
        data = payload.model_dump()
    elif hasattr(payload, "model_dump"):
        data = payload.model_dump()
    elif isinstance(payload, dict):
        data = payload
    elif isinstance(payload, str):
        data = _extract_json(payload)
    else:
        raise TypeError(f"지원하지 않는 Judge payload 타입입니다: {type(payload)!r}")

    try:
        return JudgeStructuredOutput.model_validate(data).model_dump()
    except ValidationError as exc:
        raise ValueError(f"Judge 응답 검증 실패: {exc}") from exc


def _extract_json(payload: str) -> dict[str, Any]:
    text = payload.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _extract_anthropic_tool_input(message: Any) -> dict[str, Any]:
    content_blocks = getattr(message, "content", None)
    if content_blocks is None and isinstance(message, dict):
        content_blocks = message.get("content", [])

    for block in content_blocks or []:
        block_type = getattr(block, "type", None)
        if block_type is None and isinstance(block, dict):
            block_type = block.get("type")
        if block_type == "tool_use":
            if hasattr(block, "input"):
                return dict(block.input)
            return dict(block.get("input", {}))

    raise ValueError("Anthropic 응답에서 tool_use payload를 찾지 못했습니다.")


def _sanitize_schema(value: Any, drop_keys: set[str]) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key in drop_keys:
                continue
            sanitized[key] = _sanitize_schema(item, drop_keys)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_schema(item, drop_keys) for item in value]
    return value


def _api_key_is_usable(api_key: str) -> bool:
    stripped = (api_key or "").strip()
    if not stripped:
        return False

    lowered = stripped.lower()
    if lowered in {"none", "null", "changeme"}:
        return False
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return False
    if stripped.endswith("..."):
        return False
    return True


def _normalize_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    if len(message) > 240:
        return f"{message[:237]}..."
    return message


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 1)
