"""
CP3 — 2단계 리랭킹 + 통합 검색 파이프라인
────────────────────────────────────────────────────
2단계 검색:
  1단계: Dense(HyDE) + BM25 → RRF → Top-20 후보 (Recall 최대화)
  2단계: Cross-Encoder 재점수 → Top-5 최종 (Precision 최대화)

Parent 청크 교체:
  검색은 자식(Child) 청크 단위로 수행하되,
  LLM에는 부모(Parent) 청크 텍스트를 컨텍스트로 제공.

RetrievalPipeline:
  CP3 전체 흐름을 단일 호출로 실행하는 통합 클래스.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from app.cp2_knowledge_base.embedder import SearchResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── 최종 컨텍스트 결과 ────────────────────────────────────────────

@dataclass
class ContextResult:
    """CP3 최종 출력 — LLM 평가에 사용되는 컨텍스트"""
    query: str                          # 검색에 사용된 쿼리 (재작성된 쿼리)
    original_query: str                 # 원본 사용자 발화
    ranked_chunks: List[SearchResult]   # 자식 청크 (순위 포함)
    parent_texts: List[str]            # 대응하는 부모 청크 텍스트
    hypothetical_answer: Optional[str] = None  # HyDE 가상 답변
    query_variants: List[str] = field(default_factory=list)

    @property
    def context_text(self) -> str:
        """LLM 프롬프트에 삽입할 컨텍스트 텍스트 (부모 청크 기준)"""
        parts = []
        for i, (chunk, parent_text) in enumerate(
            zip(self.ranked_chunks, self.parent_texts), 1
        ):
            text = parent_text if parent_text else chunk.text
            parts.append(f"[참조 {i}] {text}")
        return "\n\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "query":              self.query,
            "original_query":     self.original_query,
            "hypothetical_answer": self.hypothetical_answer,
            "query_variants":     self.query_variants,
            "top_chunks": [
                {**c.to_dict(), "parent_text": pt[:200] + "..." if pt and len(pt) > 200 else pt}
                for c, pt in zip(self.ranked_chunks, self.parent_texts)
            ],
        }


# ── Cross-Encoder 리랭커 ──────────────────────────────────────────

class TwoStageReranker:
    """
    1단계 후보군(Top-K)을 Cross-Encoder로 재점수 매겨 Top-N으로 압축.

    사용 예:
        reranker = TwoStageReranker(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
        final_top5 = reranker.rerank(query, top20_candidates, top_n=5)
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        batch_size: int = 32,
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None   # lazy load

    def rerank(
        self,
        query: str,
        candidates: List[SearchResult],
        top_n: int = 5,
    ) -> List[SearchResult]:
        """
        Cross-Encoder로 후보군 재랭킹.
        sentence-transformers 미설치 시 원본 순서 반환.
        """
        if not candidates:
            return []

        model = self._get_model()
        if model is None:
            logger.warning("[CP3] Cross-Encoder 미사용 — 1단계 순서 그대로 반환")
            return candidates[:top_n]

        try:
            # (query, doc) 쌍 구성
            pairs = [(query, c.text) for c in candidates]

            # 배치 점수 계산
            scores = model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)

            # 점수 반영 및 정렬
            for candidate, score in zip(candidates, scores):
                candidate.score = float(score)

            reranked = sorted(candidates, key=lambda c: c.score, reverse=True)
            logger.debug(
                f"[CP3] Cross-Encoder 리랭킹 완료: {len(candidates)}개 → Top-{top_n}"
            )
            return reranked[:top_n]

        except Exception as e:
            logger.error(f"[CP3] Cross-Encoder 오류: {e}")
            return candidates[:top_n]

    def _get_model(self):
        """Cross-Encoder 모델 lazy 로드"""
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)
            logger.info(f"[CP3] Cross-Encoder 로드: {self.model_name}")
            return self._model
        except ImportError:
            logger.error("[CP3] sentence-transformers 미설치: pip install sentence-transformers")
            return None
        except Exception as e:
            logger.error(f"[CP3] Cross-Encoder 로드 오류: {e}")
            return None


# ── 통합 검색 파이프라인 ──────────────────────────────────────────

class RetrievalPipeline:
    """
    CP3 전체 5단계 검색 파이프라인 통합 클래스.

    흐름:
      대화 인식 쿼리 재작성 (ConversationAwareQueryBuilder)
        → HyDE 가상 답변 생성 (HyDERetriever)
        → Multi-Query 변형 생성 (MultiQueryExpander)
        → 1단계: Dense + BM25 RRF → Top-20 (DualEmbedder)
        → 2단계: Cross-Encoder → Top-5 (TwoStageReranker)
        → Parent 청크 교체 (DualEmbedder.get_parent_chunk)

    사용 예:
        pipeline = RetrievalPipeline(
            embedder=dual_embedder,
            anthropic_api_key="sk-ant-...",
            use_hyde=True,
            use_multi_query=True,
        )
        context = pipeline.retrieve(
            query="요금제 변경 방법",
            conversation_history=turns,
            top_k_first=20,
            top_k_final=5,
        )
        print(context.context_text)  # LLM에 전달할 참조 텍스트
    """

    def __init__(
        self,
        embedder,                           # DualEmbedder
        anthropic_api_key: str = None,
        claude_model: str = None,
        cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        use_hyde: bool = True,
        use_multi_query: bool = True,
        context_turns: int = 3,
        num_query_variants: int = 3,
    ):
        from app.cp3_retrieval.query_builder import ConversationAwareQueryBuilder
        from app.cp3_retrieval.hyde_retriever import HyDERetriever, MultiQueryExpander

        api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "")
        model   = claude_model or os.getenv("CLAUDE_MODEL", "claude-opus-4-6")

        self.embedder        = embedder
        self.use_hyde        = use_hyde
        self.use_multi_query = use_multi_query

        self.query_builder = ConversationAwareQueryBuilder(
            context_turns=context_turns,
            anthropic_api_key=api_key,
            claude_model=model,
        )
        self.hyde_retriever = HyDERetriever(
            embedder=embedder,
            anthropic_api_key=api_key,
            claude_model=model,
        )
        self.multi_query_expander = MultiQueryExpander(
            embedder=embedder,
            anthropic_api_key=api_key,
            claude_model=model,
            num_variants=num_query_variants,
        )
        self.reranker = TwoStageReranker(model_name=cross_encoder_model)

    def retrieve(
        self,
        query: str,
        conversation_history: list = None,
        top_k_first: int = 20,
        top_k_final: int = 5,
    ) -> ContextResult:
        """
        5단계 검색 파이프라인 실행.

        Args:
            query: 현재 발화 또는 평가 대상 쿼리
            conversation_history: List[Turn] 이전 대화 이력
            top_k_first: 1단계 후보 수 (기본 20)
            top_k_final: 2단계 최종 수 (기본 5)

        Returns:
            ContextResult: 최종 참조 청크 + 컨텍스트 텍스트
        """
        original_query = query
        hypothetical_answer = None
        query_variants: List[str] = []

        # ── 단계 1: 대화 인식 쿼리 재작성 ────────────────────────
        if conversation_history:
            from app.cp1_preprocessing.log_parser import Turn
            turns = conversation_history if isinstance(conversation_history[0], Turn) else []
            if turns:
                # 마지막 user 턴을 기준으로 재작성
                user_turns = [t for t in turns if t.role == "user"]
                if user_turns:
                    fake_turn = user_turns[-1]
                    fake_turn_text = fake_turn.text
                    query = self.query_builder.build(fake_turn, turns[:-1])
        logger.info(f"[CP3] 검색 쿼리: '{query[:60]}'")

        # ── 단계 2: 1단계 검색 (Dense + BM25 RRF) ───────────────
        if self.use_hyde:
            # HyDE 가상 답변 생성
            hypothetical_answer = self.hyde_retriever.get_hypothetical_answer(query)
            if hypothetical_answer:
                candidates = self.embedder.ensemble_search(hypothetical_answer, top_k=top_k_first)
            else:
                candidates = self.embedder.ensemble_search(query, top_k=top_k_first)
        else:
            candidates = self.embedder.ensemble_search(query, top_k=top_k_first)

        # ── 단계 3: Multi-Query 확장 병합 ────────────────────────
        if self.use_multi_query and candidates:
            variants_result = self.multi_query_expander.search(query, top_k=top_k_first)
            query_variants = self.multi_query_expander.generate_variants(query)[1:]  # 원본 제외

            # 1단계 결과 + Multi-Query 결과 RRF 병합
            candidates = self._merge_results(candidates, variants_result, top_k_first)

        if not candidates:
            logger.warning(f"[CP3] 검색 결과 없음: '{query}'")
            return ContextResult(
                query=query,
                original_query=original_query,
                ranked_chunks=[],
                parent_texts=[],
                hypothetical_answer=hypothetical_answer,
                query_variants=query_variants,
            )

        # ── 단계 4: 2단계 Cross-Encoder 리랭킹 ───────────────────
        final_chunks = self.reranker.rerank(query, candidates, top_n=top_k_final)
        logger.info(f"[CP3] 최종 청크 {len(final_chunks)}개 선정")

        # ── 단계 5: Parent 청크 교체 ─────────────────────────────
        parent_texts = []
        for chunk in final_chunks:
            if chunk.parent_id:
                parent = self.embedder.get_parent_chunk(chunk.parent_id)
                parent_texts.append(parent.text if parent else chunk.text)
            else:
                parent_texts.append(chunk.text)

        return ContextResult(
            query=query,
            original_query=original_query,
            ranked_chunks=final_chunks,
            parent_texts=parent_texts,
            hypothetical_answer=hypothetical_answer,
            query_variants=query_variants,
        )

    @staticmethod
    def _merge_results(
        results_a: List[SearchResult],
        results_b: List[SearchResult],
        top_k: int,
    ) -> List[SearchResult]:
        """두 검색 결과를 RRF로 병합"""
        rrf_k = 60
        scores: dict[str, float] = {}
        chunk_map: dict[str, SearchResult] = {}

        for rank, res in enumerate(results_a):
            scores[res.chunk_id] = scores.get(res.chunk_id, 0) + 1 / (rrf_k + rank + 1)
            chunk_map[res.chunk_id] = res

        for rank, res in enumerate(results_b):
            scores[res.chunk_id] = scores.get(res.chunk_id, 0) + 1 / (rrf_k + rank + 1)
            chunk_map[res.chunk_id] = res

        top_ids = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_k]
        merged = []
        for cid in top_ids:
            res = chunk_map[cid]
            res.score = round(scores[cid], 6)
            merged.append(res)
        return merged
