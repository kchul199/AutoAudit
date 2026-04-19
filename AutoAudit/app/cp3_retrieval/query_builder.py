"""
CP3 — 대화 인식 쿼리 빌더 (Contextual Compression)
────────────────────────────────────────────────────
평가 턴의 고객 질의가 앞선 대화 맥락 없이는 모호할 때,
LLM을 사용하여 독립적으로 이해 가능한 쿼리로 재작성.

예)
  이전 대화: "인터넷 요금제를 변경하고 싶어요"
  현재 질의: "그 방법이 뭐예요?"
  → 재작성:  "인터넷 요금제 변경 방법은 무엇인가요?"
"""
from __future__ import annotations

import os
from typing import List, Optional

from app.cp1_preprocessing.log_parser import Turn
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ConversationAwareQueryBuilder:
    """
    N턴 이전 대화 이력을 참고하여 현재 사용자 질의를 독립적 쿼리로 재작성.

    사용 예:
        builder = ConversationAwareQueryBuilder(
            context_turns=3,
            anthropic_api_key="sk-ant-..."
        )
        standalone_query = builder.build(
            current_turn=turn,
            previous_turns=history,
        )
    """

    REWRITE_PROMPT = """당신은 콜봇 대화를 분석하는 전문가입니다.
다음 대화 이력과 현재 발화가 주어집니다.
현재 발화를 이전 대화 맥락 없이도 완전히 이해할 수 있는 독립적인 질문으로 재작성해주세요.

[이전 대화]
{history}

[현재 발화]
{current}

[지침]
- 재작성된 질문만 출력하세요 (설명 없이)
- 현재 발화의 의미를 완전히 유지하세요
- 질문 형태로 작성하세요
- 한국어로 작성하세요

재작성된 질문:"""

    def __init__(
        self,
        context_turns: int = 3,
        anthropic_api_key: str = None,
        claude_model: str = "claude-opus-4-6",
        max_tokens: int = 256,
    ):
        self.context_turns = context_turns
        self.api_key       = os.getenv("ANTHROPIC_API_KEY", "") if anthropic_api_key is None else anthropic_api_key
        self.model         = claude_model or os.getenv("CLAUDE_MODEL", "claude-opus-4-6")
        self.max_tokens    = max_tokens

    def build(
        self,
        current_turn: Turn,
        previous_turns: List[Turn],
        force_rewrite: bool = False,
    ) -> str:
        """
        현재 턴의 쿼리를 대화 맥락 기반으로 재작성.
        이전 대화가 없거나 현재 발화가 충분히 독립적이면 원본 반환.

        Returns:
            str: 재작성된 쿼리 (또는 원본 텍스트)
        """
        if not previous_turns and not force_rewrite:
            return current_turn.text

        # 최근 N턴만 사용
        recent = previous_turns[-self.context_turns:]

        # 현재 발화가 독립적인지 간단 판단
        if not force_rewrite and self._is_standalone(current_turn.text):
            return current_turn.text

        history_text = self._format_history(recent)
        prompt = self.REWRITE_PROMPT.format(
            history=history_text,
            current=current_turn.text,
        )

        rewritten = self._call_llm(prompt)
        if rewritten:
            logger.debug(f"[CP3] 쿼리 재작성: '{current_turn.text[:50]}' → '{rewritten[:50]}'")
            return rewritten.strip()

        return current_turn.text

    def build_search_query(
        self,
        turns: List[Turn],
        eval_turn_index: int,
    ) -> str:
        """
        평가 대상 턴(eval_turn_index)의 검색 쿼리 생성.
        해당 턴 이전의 대화를 컨텍스트로 사용.
        """
        if eval_turn_index >= len(turns):
            raise IndexError(f"턴 인덱스 범위 초과: {eval_turn_index}")

        current = turns[eval_turn_index]
        # 콜봇 답변이면 바로 직전 고객 질문 기준
        if current.role == "bot":
            user_turns_before = [t for t in turns[:eval_turn_index] if t.role == "user"]
            if user_turns_before:
                current = user_turns_before[-1]
            else:
                return current.text

        previous = turns[:turns.index(current)]
        return self.build(current, previous)

    # ── 내부 유틸 ─────────────────────────────────────────────────

    @staticmethod
    def _is_standalone(text: str) -> bool:
        """발화가 독립적인지 간단 판단 (대명사 의존 여부)"""
        ambiguous_markers = ["그것", "그거", "그게", "그 방법", "그렇게", "이것", "저것",
                              "that", "it", "this", "there", "those"]
        text_lower = text.lower()
        return not any(m in text_lower for m in ambiguous_markers)

    @staticmethod
    def _format_history(turns: List[Turn]) -> str:
        """대화 이력을 프롬프트용 텍스트로 변환"""
        lines = []
        for t in turns:
            role_label = "콜봇" if t.role == "bot" else "고객"
            lines.append(f"{role_label}: {t.text}")
        return "\n".join(lines)

    def _call_llm(self, prompt: str) -> Optional[str]:
        """Claude API 호출"""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except ImportError:
            logger.warning("[CP3] anthropic 미설치 — 원본 쿼리 사용")
            return None
        except Exception as e:
            logger.error(f"[CP3] 쿼리 재작성 LLM 오류: {e}")
            return None
