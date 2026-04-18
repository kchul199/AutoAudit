"""CP4 — 개별 Judge 구현."""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

TOKEN_RE = re.compile(r"[가-힣]{2,}|[a-zA-Z]{2,}|\d+")


@dataclass
class JudgeScore:
    model: str
    accuracy: float
    fluency: float
    acc_reason: str
    flu_reason: str
    key_issues: list[str] = field(default_factory=list)
    flow_issues: list[str] = field(default_factory=list)
    source: str = "heuristic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "accuracy": round(self.accuracy, 2),
            "fluency": round(self.fluency, 2),
            "acc_reason": self.acc_reason,
            "flu_reason": self.flu_reason,
            "key_issues": self.key_issues,
            "flow_issues": self.flow_issues,
            "source": self.source,
        }


class BaseJudge:
    """공통 Judge 베이스 클래스."""

    provider_name = "judge"

    def __init__(
        self,
        model: str,
        api_key: str = "",
        max_tokens: int = 800,
    ):
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens

    async def evaluate_async(self, turn_data: dict[str, Any]) -> JudgeScore:
        if self.api_key:
            try:
                return await asyncio.to_thread(self._evaluate_live, turn_data)
            except Exception as e:
                logger.warning(
                    f"[CP4] {self.provider_name} live 평가 실패 — 휴리스틱으로 대체: {e}"
                )
        return self._evaluate_heuristic(turn_data)

    def _evaluate_live(self, turn_data: dict[str, Any]) -> JudgeScore:
        raise NotImplementedError

    def _evaluate_heuristic(self, turn_data: dict[str, Any]) -> JudgeScore:
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
            acc_reason=score["acc_reason"],
            flu_reason=score["flu_reason"],
            key_issues=score["key_issues"],
            flow_issues=score["flow_issues"],
            source="heuristic",
        )

    @staticmethod
    def _build_prompt(turn_data: dict[str, Any]) -> str:
        context_text = turn_data.get("context_text", "")
        return f"""당신은 콜봇 품질 평가 전문가입니다.
아래 정보를 바탕으로 콜봇 답변을 평가하세요.

[고객 질문]
{turn_data.get("user_query", "")}

[콜봇 답변]
{turn_data.get("bot_answer", "")}

[참조 컨텍스트]
{context_text[:5000] if context_text else "참조 없음"}

[출력 형식]
아래 JSON만 출력하세요.
{{
  "accuracy": 0-5 사이 숫자,
  "fluency": 0-5 사이 숫자,
  "acc_reason": "정확성 근거 한 문장",
  "flu_reason": "자연스러움 근거 한 문장",
  "key_issues": ["정확성 문제"],
  "flow_issues": ["흐름 문제"]
}}
"""

    @staticmethod
    def _parse_response(payload: str, model_name: str) -> JudgeScore:
        data = _extract_json(payload)
        return JudgeScore(
            model=model_name,
            accuracy=_clamp_score(data.get("accuracy", 0)),
            fluency=_clamp_score(data.get("fluency", 0)),
            acc_reason=str(data.get("acc_reason", "근거 없음")),
            flu_reason=str(data.get("flu_reason", "근거 없음")),
            key_issues=_ensure_list(data.get("key_issues")),
            flow_issues=_ensure_list(data.get("flow_issues")),
            source="live",
        )


class ClaudeJudge(BaseJudge):
    provider_name = "claude"

    def _evaluate_live(self, turn_data: dict[str, Any]) -> JudgeScore:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": self._build_prompt(turn_data)}],
        )
        text = "".join(
            block.text for block in response.content
            if getattr(block, "type", "") == "text"
        )
        return self._parse_response(text, self.provider_name)


class GPTJudge(BaseJudge):
    provider_name = "gpt4o"

    def _evaluate_live(self, turn_data: dict[str, Any]) -> JudgeScore:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "당신은 JSON만 출력하는 콜봇 품질 평가 전문가입니다."},
                {"role": "user", "content": self._build_prompt(turn_data)},
            ],
        )
        text = response.choices[0].message.content or "{}"
        return self._parse_response(text, self.provider_name)


class GeminiJudge(BaseJudge):
    provider_name = "gemini"

    def _evaluate_live(self, turn_data: dict[str, Any]) -> JudgeScore:
        import google.generativeai as genai

        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model)
        response = model.generate_content(self._build_prompt(turn_data))
        text = getattr(response, "text", "") or "{}"
        return self._parse_response(text, self.provider_name)


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
    grounded_score = 0.7 * context_overlap + 0.3 * query_overlap

    accuracy = 1.2 + 3.4 * grounded_score
    fluency = 1.4 + 2.0 * query_overlap + 0.9 * length_score + 0.7 * polite_score

    if not context_text.strip():
        accuracy -= 0.5
    if len(answer_tokens) < 4:
        accuracy -= 0.3
        fluency -= 0.4

    if model == "gpt4o":
        accuracy += 0.1 if query_overlap >= 0.25 else -0.05
        fluency += 0.05
    elif model == "gemini":
        accuracy += 0.1 if len(context_tokens) > 30 else -0.05
        fluency += 0.1 if 40 <= length <= 300 else -0.1
    else:  # claude
        accuracy += 0.15 if context_overlap >= 0.22 else 0.0
        fluency += 0.05 if polite_score >= 1.0 else 0.0

    key_issues = []
    flow_issues = []
    if context_overlap < 0.18:
        key_issues.append("참조 문서와의 직접적 근거가 약함")
    if query_overlap < 0.15:
        flow_issues.append("고객 질문과의 연결성이 약함")
    if length < 18:
        flow_issues.append("답변이 너무 짧아 안내가 불충분함")
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

    return {
        "accuracy": _clamp_score(accuracy),
        "fluency": _clamp_score(fluency),
        "acc_reason": acc_reason,
        "flu_reason": flu_reason,
        "key_issues": key_issues[:3],
        "flow_issues": flow_issues[:3],
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


def _extract_json(payload: str) -> dict[str, Any]:
    text = payload.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise
