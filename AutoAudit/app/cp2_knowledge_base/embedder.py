"""
CP2 — 이중 임베딩 모듈 (Dense + BM25 Sparse)
────────────────────────────────────────────────────
Dense 임베딩 : OpenAI text-embedding-3-large → ChromaDB
Sparse 검색  : BM25 (rank_bm25)
인덱스 저장  : chroma_db/{subscriber}/ (영속 저장)

주요 기능:
  - build_index(chunks)    : 청크 임베딩 & 인덱스 저장
  - dense_search(query, k) : Dense 벡터 검색
  - bm25_search(query, k)  : BM25 키워드 검색
  - ensemble_search(query) : RRF 앙상블 (Dense + BM25)
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── 검색 결과 ─────────────────────────────────────────────────────

@dataclass
class SearchResult:
    chunk_id: str
    text: str
    score: float
    doc_id: str
    doc_type: str
    parent_id: Optional[str]
    is_child: bool
    metadata: dict

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "text":     self.text[:300] + "..." if len(self.text) > 300 else self.text,
            "score":    round(self.score, 4),
            "doc_id":   self.doc_id,
            "doc_type": self.doc_type,
            "is_child": self.is_child,
        }


# ── 이중 임베딩 클래스 ───────────────────────────────────────────

class DualEmbedder:
    """
    Dense (ChromaDB + OpenAI) + Sparse (BM25) 이중 임베딩.

    사용 예:
        emb = DualEmbedder(subscriber="한국통신",
                           persist_dir="./data/chroma_db",
                           openai_api_key="sk-...")
        emb.build_index(chunks)
        results = emb.ensemble_search("요금 조회 방법", top_k=5)
    """

    COLLECTION_SUFFIX = "_children"   # 자식 청크 컬렉션 (검색용)
    PARENT_SUFFIX     = "_parents"    # 부모 청크 컬렉션 (컨텍스트용)

    def __init__(
        self,
        subscriber: str,
        persist_dir: str = "./data/chroma_db",
        openai_api_key: str = None,
        embedding_model: str = "text-embedding-3-large",
        batch_size: int = 100,
    ):
        self.subscriber      = subscriber
        self.persist_dir     = Path(persist_dir) / subscriber
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.api_key         = openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self.embedding_model = embedding_model
        self.batch_size      = batch_size

        # BM25 내부 상태
        self._bm25_index = None
        self._bm25_chunks: List[dict] = []

        # ChromaDB 클라이언트 (lazy init)
        self._chroma_client = None
        self._child_col     = None
        self._parent_col    = None

        # BM25 인덱스 파일 경로
        self._bm25_path = self.persist_dir / "bm25_index.json"

    # ── 인덱스 구축 ──────────────────────────────────────────────

    def build_index(self, chunks: list, force_rebuild: bool = False) -> None:
        """
        청크 목록으로 Dense + BM25 인덱스 구축 및 저장.
        force_rebuild=False 이면 기존 인덱스가 있을 때 스킵.
        """
        child_chunks  = [c for c in chunks if c.is_child]
        parent_chunks = [c for c in chunks if not c.is_child]

        logger.info(
            f"[CP2] 인덱스 구축 시작: {self.subscriber} | "
            f"자식={len(child_chunks)}, 부모={len(parent_chunks)}"
        )

        self._build_dense_index(child_chunks, parent_chunks, force_rebuild)
        self._build_bm25_index(child_chunks)

        logger.info(f"[CP2] 인덱스 구축 완료: {self.subscriber}")

    # ── 검색 ────────────────────────────────────────────────────

    def dense_search(self, query: str, top_k: int = 20) -> List[SearchResult]:
        """Dense 벡터 검색 (자식 청크 대상)"""
        try:
            col = self._get_child_collection()
            query_emb = self._embed_texts([query])[0]
            results = col.query(
                query_embeddings=[query_emb],
                n_results=min(top_k, col.count()),
                include=["documents", "metadatas", "distances"],
            )
            return self._chroma_to_results(results)
        except Exception as e:
            logger.error(f"[CP2] Dense 검색 오류: {e}")
            return []

    def bm25_search(self, query: str, top_k: int = 20) -> List[SearchResult]:
        """BM25 희소 검색 (자식 청크 대상)"""
        try:
            self._load_bm25_if_needed()
            if not self._bm25_index or not self._bm25_chunks:
                return []

            from rank_bm25 import BM25Okapi
            tokenized_query = self._tokenize(query)
            scores = self._bm25_index.get_scores(tokenized_query)

            # 상위 k개 인덱스
            top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

            results = []
            for idx in top_indices:
                if scores[idx] <= 0:
                    continue
                c = self._bm25_chunks[idx]
                results.append(SearchResult(
                    chunk_id=c["chunk_id"],
                    text=c["text"],
                    score=float(scores[idx]),
                    doc_id=c.get("doc_id", ""),
                    doc_type=c.get("doc_type", ""),
                    parent_id=c.get("parent_id"),
                    is_child=c.get("is_child", True),
                    metadata=c.get("metadata", {}),
                ))
            return results
        except ImportError:
            logger.error("[CP2] rank_bm25 미설치: pip install rank-bm25")
            return []
        except Exception as e:
            logger.error(f"[CP2] BM25 검색 오류: {e}")
            return []

    def ensemble_search(
        self,
        query: str,
        top_k: int = 20,
        dense_weight: float = 0.6,
        bm25_weight: float = 0.4,
    ) -> List[SearchResult]:
        """
        RRF (Reciprocal Rank Fusion) 앙상블.
        Dense + BM25 결과를 순위 기반으로 병합.
        """
        dense_results = self.dense_search(query, top_k=top_k * 2)
        bm25_results  = self.bm25_search(query, top_k=top_k * 2)

        if not dense_results and not bm25_results:
            return []

        # RRF 점수 계산 (k=60 표준값)
        rrf_k = 60
        scores: dict[str, float] = {}
        chunk_map: dict[str, SearchResult] = {}

        for rank, res in enumerate(dense_results):
            scores[res.chunk_id] = scores.get(res.chunk_id, 0) + dense_weight / (rrf_k + rank + 1)
            chunk_map[res.chunk_id] = res

        for rank, res in enumerate(bm25_results):
            scores[res.chunk_id] = scores.get(res.chunk_id, 0) + bm25_weight / (rrf_k + rank + 1)
            chunk_map[res.chunk_id] = res

        # 상위 top_k 정렬
        top_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:top_k]
        results = []
        for cid in top_ids:
            res = chunk_map[cid]
            res.score = round(scores[cid], 6)
            results.append(res)

        return results

    def get_parent_chunk(self, parent_id: str) -> Optional[SearchResult]:
        """자식 청크의 부모 청크 텍스트 조회"""
        try:
            col = self._get_parent_collection()
            result = col.get(ids=[parent_id], include=["documents", "metadatas"])
            if result["ids"]:
                meta = result["metadatas"][0] if result["metadatas"] else {}
                return SearchResult(
                    chunk_id=parent_id,
                    text=result["documents"][0],
                    score=1.0,
                    doc_id=meta.get("doc_id", ""),
                    doc_type=meta.get("doc_type", ""),
                    parent_id=None,
                    is_child=False,
                    metadata=meta,
                )
        except Exception as e:
            logger.error(f"[CP2] 부모 청크 조회 오류: {e}")
        return None

    def index_stats(self) -> dict:
        """인덱스 통계 반환"""
        try:
            child_count  = self._get_child_collection().count()
            parent_count = self._get_parent_collection().count()
            bm25_count   = len(self._bm25_chunks) if self._bm25_chunks else 0
            return {
                "subscriber": self.subscriber,
                "child_chunks": child_count,
                "parent_chunks": parent_count,
                "bm25_chunks": bm25_count,
            }
        except Exception:
            return {"subscriber": self.subscriber, "child_chunks": 0, "parent_chunks": 0}

    # ── Dense 인덱스 내부 구현 ───────────────────────────────────

    def _build_dense_index(self, child_chunks: list, parent_chunks: list,
                           force_rebuild: bool) -> None:
        """ChromaDB Dense 인덱스 구축"""
        try:
            child_col  = self._get_child_collection(force_rebuild)
            parent_col = self._get_parent_collection(force_rebuild)

            # 이미 인덱스가 있고 force_rebuild=False이면 스킵
            if not force_rebuild and child_col.count() > 0:
                logger.info(f"[CP2] 기존 Dense 인덱스 사용: {self.subscriber} ({child_col.count()}개 자식)")
                return

            # 자식 청크 임베딩
            self._upsert_chunks(child_col, child_chunks)
            # 부모 청크 (텍스트만 저장, 임베딩 불필요)
            self._upsert_chunks_no_embed(parent_col, parent_chunks)

        except ImportError:
            logger.error("[CP2] chromadb 미설치: pip install chromadb")

    def _upsert_chunks(self, collection, chunks: list) -> None:
        """청크를 임베딩하여 ChromaDB에 저장"""
        if not chunks:
            return
        texts = [c.text for c in chunks]
        ids   = [c.chunk_id for c in chunks]
        metas = [{"doc_id": c.doc_id, "doc_type": c.doc_type,
                  "parent_id": c.parent_id or "", "is_child": c.is_child,
                  **c.metadata} for c in chunks]

        # 배치 임베딩
        all_embeddings = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            embs  = self._embed_texts(batch)
            all_embeddings.extend(embs)
            logger.info(f"[CP2] 임베딩 진행: {min(i + self.batch_size, len(texts))}/{len(texts)}")

        collection.upsert(
            ids=ids,
            embeddings=all_embeddings,
            documents=texts,
            metadatas=metas,
        )

    def _upsert_chunks_no_embed(self, collection, chunks: list) -> None:
        """부모 청크 — 임베딩 없이 텍스트만 저장 (검색용 아님)"""
        if not chunks:
            return
        collection.upsert(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            metadatas=[{"doc_id": c.doc_id, "doc_type": c.doc_type, **c.metadata} for c in chunks],
        )

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        """OpenAI 임베딩 API 호출"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            response = client.embeddings.create(
                model=self.embedding_model,
                input=texts,
            )
            return [item.embedding for item in response.data]
        except ImportError:
            logger.error("[CP2] openai 미설치: pip install openai")
            # 더미 임베딩 (개발/테스트용)
            import random
            return [[random.gauss(0, 0.1) for _ in range(1536)] for _ in texts]
        except Exception as e:
            logger.error(f"[CP2] 임베딩 오류: {e}")
            import random
            return [[random.gauss(0, 0.1) for _ in range(1536)] for _ in texts]

    def _get_child_collection(self, reset: bool = False):
        """자식 청크 컬렉션 반환 (lazy init)"""
        return self._get_collection(self.subscriber + self.COLLECTION_SUFFIX, reset)

    def _get_parent_collection(self, reset: bool = False):
        """부모 청크 컬렉션 반환 (lazy init)"""
        return self._get_collection(self.subscriber + self.PARENT_SUFFIX, reset)

    def _get_collection(self, name: str, reset: bool = False):
        """ChromaDB 컬렉션 가져오기"""
        import chromadb
        if self._chroma_client is None:
            self._chroma_client = chromadb.PersistentClient(path=str(self.persist_dir))
        if reset:
            try:
                self._chroma_client.delete_collection(name)
            except Exception:
                pass
        return self._chroma_client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def _chroma_to_results(self, chroma_result: dict) -> List[SearchResult]:
        """ChromaDB 결과 → SearchResult 변환"""
        results = []
        ids       = chroma_result.get("ids", [[]])[0]
        docs      = chroma_result.get("documents", [[]])[0]
        metas     = chroma_result.get("metadatas", [[]])[0]
        distances = chroma_result.get("distances", [[]])[0]

        for cid, doc, meta, dist in zip(ids, docs, metas, distances):
            # cosine distance → similarity score (1 - dist)
            score = max(0.0, 1.0 - dist)
            results.append(SearchResult(
                chunk_id=cid,
                text=doc,
                score=score,
                doc_id=meta.get("doc_id", ""),
                doc_type=meta.get("doc_type", ""),
                parent_id=meta.get("parent_id") or None,
                is_child=bool(meta.get("is_child", True)),
                metadata={k: v for k, v in meta.items()
                          if k not in ("doc_id", "doc_type", "parent_id", "is_child")},
            ))
        return results

    # ── BM25 인덱스 내부 구현 ────────────────────────────────────

    def _build_bm25_index(self, child_chunks: list) -> None:
        """BM25 인덱스 구축 및 JSON 저장"""
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.error("[CP2] rank_bm25 미설치: pip install rank-bm25")
            return

        if not child_chunks:
            return

        self._bm25_chunks = [c.to_dict() for c in child_chunks]
        tokenized = [self._tokenize(c.text) for c in child_chunks]
        self._bm25_index = BM25Okapi(tokenized)

        # JSON으로 저장 (토크나이즈된 결과 + 청크 메타)
        save_data = {"chunks": self._bm25_chunks}
        with open(self._bm25_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False)
        logger.info(f"[CP2] BM25 인덱스 저장: {self._bm25_path} ({len(child_chunks)}개)")

    def _load_bm25_if_needed(self) -> None:
        """BM25 인덱스가 메모리에 없으면 파일에서 복원"""
        if self._bm25_index is not None:
            return
        if not self._bm25_path.exists():
            return
        try:
            from rank_bm25 import BM25Okapi
            with open(self._bm25_path, encoding="utf-8") as f:
                data = json.load(f)
            self._bm25_chunks = data["chunks"]
            tokenized = [self._tokenize(c["text"]) for c in self._bm25_chunks]
            self._bm25_index = BM25Okapi(tokenized)
            logger.info(f"[CP2] BM25 인덱스 로드: {len(self._bm25_chunks)}개")
        except Exception as e:
            logger.error(f"[CP2] BM25 로드 오류: {e}")

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """한국어 + 영어 간단 토크나이저"""
        # 공백/특수문자 분리, 2글자 이상만 유지
        tokens = re.findall(r"[가-힣]{2,}|[a-zA-Z]{2,}|\d+", text.lower())
        return tokens if tokens else ["<empty>"]

    def __repr__(self) -> str:
        return f"DualEmbedder(subscriber={self.subscriber!r}, model={self.embedding_model!r})"
