"""
CP3 — HyDE + Multi-Query 확장 모듈
────────────────────────────────────────────────────
HyDE (Hypothetical Document Embeddings):
  사용자 질의 → LLM이 이상적인 답변 생성 → 답변을 임베딩하여 검색
  → 질의-답변 공간 정렬로 검색 정확도 향상

Multi-Query Expansion:
  원본 쿼리에서 N개의 변형 쿼리 생성 → 모든 쿼리로 검색 후 RRF 병합
  → 쿼리 표현 방식의 다양성 확보
"""
from __future__ import annotations

import os
from typing import List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── HyDE 검색기 ─────────────────────────────────────────────────

class HyDERetriever:
    """
    Hypothetical Document Embeddings 기반 검색.

    사용 예:
        hyde = HyDERetriever(
            embedder=dual_embedder,
            anthropic_api_key="sk-ant-..."
        )
        results = hyde.search("인터넷 요금 변경 방법", top_k=20)
    """

    HYDE_PROMPT = """당신은 {subscriber} 콜봇 서비스의 전문 상담사입니다.
다음 고객 질문에 대해 정확하고 상세한 답변을 작성해주세요.
이 답변은 지식 베이스에서 관련 문서를 검색하는 데 사용됩니다.

[고객 질문]
{query}

[답변 작성 지침]
- 구체적인 절차나 방법을 포함하세요
- 관련 용어나 키워드를 자연스럽게 포함하세요
- 200자 내외로 작성하세요
- 한국어로 작성하세요

답변:"""

    def __init__(
        self,
        embedder,                        # DualEmbedder 인스턴스
        anthropic_api_key: str = None,
        claude_model: str = None,
        subscriber: str = "",
        max_tokens: int = 512,
    ):
        self.embedder    = embedder
        self.api_key     = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model       = claude_model or os.getenv("CLAUDE_MODEL", "claude-opus-4-6")
        self.subscriber  = subscriber or embedder.subscriber
        self.max_tokens  = max_tokens

    def search(self, query: str, top_k: int = 20) -> list:
        """
        HyDE 기반 Dense 검색.
        1) LLM으로 가상 답변 생성
        2) 가상 답변으로 Dense 검색
        3) 가상 답변 생성 실패 시 원본 쿼리로 fallback
        """
        hypothetical = self._generate_hypothetical(query)

        if hypothetical:
            logger.debug(f"[CP3] HyDE 가상 답변: {hypothetical[:80]}...")
            results = self.embedder.dense_search(hypothetical, top_k=top_k)
        else:
            logger.debug("[CP3] HyDE fallback — 원본 쿼리로 Dense 검색")
            results = self.embedder.dense_search(query, top_k=top_k)

        return results

    def get_hypothetical_answer(self, query: str) -> Optional[str]:
        """가상 답변 텍스트 반환 (UI 시각화용)"""
        return self._generate_hypothetical(query)

    # ── 내부 ────────────────────────────────────────────────────

    def _generate_hypothetical(self, query: str) -> Optional[str]:
        """LLM으로 가상 답변 생성"""
        prompt = self.HYDE_PROMPT.format(
            subscriber=self.subscriber,
            query=query,
        )
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
            logger.warning("[CP3] anthropic 미설치 — HyDE 스킵")
            return None
        except Exception as e:
            logger.error(f"[CP3] HyDE 생성 오류: {e}")
            return None


# ── Multi-Query 확장기 ────────────────────────────────────────────

class MultiQueryExpander:
    """
    원본 쿼리에서 N개의 변형 쿼리를 생성하여 검색 커버리지 확장.

    사용 예:
        expander = MultiQueryExpander(
            embedder=dual_embedder,
            num_variants=3,
        )
        results = expander.search("요금 변경 방법", top_k=20)
    """

    MULTI_QUERY_PROMPT = """다음 질문을 {n}가지 다른 방식으로 표현해주세요.
각 표현은 같은 의도를 가지되 다른 단어나 문장 구조를 사용해야 합니다.
번호 없이 각 표현을 줄바꿈으로 구분하여 출력하세요.

[원본 질문]
{query}

[변형된 질문들]:"""

    def __init__(
        self,
        embedder,                        # DualEmbedder 인스턴스
        anthropic_api_key: str = None,
        claude_model: str = None,
        num_variants: int = 3,
        max_tokens: int = 512,
    ):
        self.embedder     = embedder
        self.api_key      = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model        = claude_model or os.getenv("CLAUDE_MODEL", "claude-opus-4-6")
        self.num_variants = num_variants
        self.max_tokens   = max_tokens

    def generate_variants(self, query: str) -> List[str]:
        """원본 쿼리 포함 변형 쿼리 목록 반환"""
        prompt = self.MULTI_QUERY_PROMPT.format(n=self.num_variants, query=query)
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            variants = [line.strip() for line in raw.split("\n") if line.strip()]
            variants = variants[:self.num_variants]
            logger.debug(f"[CP3] 쿼리 변형 {len(variants)}개 생성")
            return [query] + variants  # 원본 포함
        except ImportError:
            logger.warning("[CP3] anthropic 미설치 — 원본 쿼리만 사용")
            return [query]
        except Exception as e:
            logger.error(f"[CP3] Multi-Query 생성 오류: {e}")
            return [query]

    def search(self, query: str, top_k: int = 20) -> list:
        """
        모든 변형 쿼리로 앙상블 검색 후 RRF 병합.
        """
        variants = self.generate_variants(query)
        all_results: dict[str, list] = {}  # chunk_id → [ranks]

        chunk_map: dict = {}
        for variant in variants:
            results = self.embedder.ensemble_search(variant, top_k=top_k)
            for rank, res in enumerate(results):
                if res.chunk_id not in all_results:
                    all_results[res.chunk_id] = []
                    chunk_map[res.chunk_id] = res
                all_results[res.chunk_id].append(rank)

        # RRF 집계
        rrf_k = 60
        rrf_scores: dict[str, float] = {}
        for cid, ranks in all_results.items():
            rrf_scores[cid] = sum(1 / (rrf_k + r + 1) for r in ranks)

        top_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)[:top_k]
        results_out = []
        for cid in top_ids:
            res = chunk_map[cid]
            res.score = round(rrf_scores[cid], 6)
            results_out.append(res)

        return results_out
