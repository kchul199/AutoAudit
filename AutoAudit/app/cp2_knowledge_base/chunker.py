"""
CP2 — Parent-Child 청킹 모듈
────────────────────────────────────────────────────
문서 타입별 청킹 전략:
  FAQ     → Q&A 쌍 단위 분리
  매뉴얼   → 3단계 계층(챕터 → 섹션 → 단락) 분리
  웹사이트 → 의미 단위(문단/제목 기준) 분리

Parent-Child 구조:
  - Child 청크 (128~256 token): 정밀 검색용 임베딩
  - Parent 청크 (512~1024 token): LLM 컨텍스트 제공용
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 대략적 토큰 수 추정 (한국어: 2~3자 ≈ 1 token, 여기선 자수/2 사용)
def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 2)


# ── 데이터 클래스 ─────────────────────────────────────────────────

@dataclass
class Chunk:
    chunk_id: str
    parent_id: Optional[str]         # None이면 자신이 Parent
    subscriber: str
    doc_id: str
    doc_type: str                     # "faq" | "manual" | "website"
    text: str
    is_child: bool = False
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "chunk_id":  self.chunk_id,
            "parent_id": self.parent_id,
            "subscriber": self.subscriber,
            "doc_id":    self.doc_id,
            "doc_type":  self.doc_type,
            "is_child":  self.is_child,
            "text":      self.text,
            "token_approx": _approx_tokens(self.text),
            "metadata":  self.metadata,
        }


# ── 청커 클래스 ───────────────────────────────────────────────────

class ParentChildChunker:
    """
    문서 타입별 Parent-Child 청킹 전략 적용.

    사용 예:
        chunker = ParentChildChunker(
            child_chunk_size=200,
            parent_chunk_size=800
        )
        chunks = chunker.chunk(raw_doc)  # parent + child 모두 반환
    """

    # FAQ Q/A 패턴
    _FAQ_Q_RE = re.compile(
        r"(?:^|\n)(?:Q\s*[\.:]|질문\s*[\.:]|Q\d+[\.\):])\s*(.+?)(?=\n(?:A\s*[\.:]|답변\s*[\.:]|Q\s*[\.:]|질문\s*[\.:]|$))",
        re.DOTALL | re.IGNORECASE,
    )
    _FAQ_A_RE = re.compile(
        r"(?:A\s*[\.:]|답변\s*[\.:])\s*(.+?)(?=\n(?:Q\s*[\.:]|질문\s*[\.:]|A\s*[\.:]|답변\s*[\.:]|$))",
        re.DOTALL | re.IGNORECASE,
    )
    # 매뉴얼 제목 패턴
    _HEADING_RE = re.compile(
        r"^(#{1,3}\s+.+|제?\d+\s*[장절항]\s*.+|\d+\.\d*\s+.+|[A-Z][^a-z\n]{3,40})$",
        re.MULTILINE,
    )
    # 문단 구분
    _PARA_SEP = re.compile(r"\n{2,}")

    def __init__(
        self,
        child_chunk_size: int = 200,   # 목표 자식 청크 토큰 수
        parent_chunk_size: int = 800,  # 목표 부모 청크 토큰 수
        overlap_tokens: int = 20,      # 청크 간 overlap
    ):
        self.child_size  = child_chunk_size
        self.parent_size = parent_chunk_size
        self.overlap     = overlap_tokens

    def chunk(self, doc, subscriber: str = None) -> List[Chunk]:
        """
        RawDocument → List[Chunk] (Parent + Child 포함)
        doc: RawDocument (or any object with .doc_id, .doc_type, .content, .subscriber, .title)
        """
        sub = subscriber or doc.subscriber
        doc_type = doc.doc_type

        if doc_type == "faq":
            chunks = self._chunk_faq(doc, sub)
        elif doc_type == "manual":
            chunks = self._chunk_manual(doc, sub)
        else:  # website / default
            chunks = self._chunk_website(doc, sub)

        logger.info(
            f"[CP2] 청킹 완료: {doc.title} | 타입={doc_type} | "
            f"부모={sum(1 for c in chunks if not c.is_child)} | "
            f"자식={sum(1 for c in chunks if c.is_child)}"
        )
        return chunks

    def chunk_all(self, docs: list) -> List[Chunk]:
        """여러 문서 일괄 청킹"""
        all_chunks: List[Chunk] = []
        for doc in docs:
            all_chunks.extend(self.chunk(doc))
        return all_chunks

    # ── FAQ 청킹 ────────────────────────────────────────────────────
    def _chunk_faq(self, doc, subscriber: str) -> List[Chunk]:
        """
        Q&A 쌍 단위로 분리.
        부모: Q+A 전체, 자식: Q 단독 / A 단독 (긴 경우 추가 분할)
        """
        chunks: List[Chunk] = []
        text = doc.content

        # Q/A 쌍 추출 (간단 패턴 매칭)
        qa_pairs = self._extract_qa_pairs(text)

        if not qa_pairs:
            # 패턴 매칭 실패 시 문단 기반 fallback
            return self._chunk_website(doc, subscriber)

        for i, (question, answer) in enumerate(qa_pairs):
            parent_text = f"Q: {question.strip()}\nA: {answer.strip()}"
            parent_id = self._gen_id(doc.doc_id, f"faq_parent_{i}")

            # 부모 청크
            chunks.append(Chunk(
                chunk_id=parent_id,
                parent_id=None,
                subscriber=subscriber,
                doc_id=doc.doc_id,
                doc_type="faq",
                text=parent_text,
                is_child=False,
                metadata={"index": i, "title": doc.title, "qa_pair": True},
            ))

            # 자식 청크: Q 단독
            q_child_id = self._gen_id(doc.doc_id, f"faq_q_{i}")
            chunks.append(Chunk(
                chunk_id=q_child_id,
                parent_id=parent_id,
                subscriber=subscriber,
                doc_id=doc.doc_id,
                doc_type="faq",
                text=f"Q: {question.strip()}",
                is_child=True,
                metadata={"index": i, "part": "question", "title": doc.title},
            ))

            # 자식 청크: A (길면 추가 분할)
            answer_chunks = self._split_to_child_size(answer.strip())
            for j, a_part in enumerate(answer_chunks):
                a_child_id = self._gen_id(doc.doc_id, f"faq_a_{i}_{j}")
                chunks.append(Chunk(
                    chunk_id=a_child_id,
                    parent_id=parent_id,
                    subscriber=subscriber,
                    doc_id=doc.doc_id,
                    doc_type="faq",
                    text=f"A: {a_part}",
                    is_child=True,
                    metadata={"index": i, "part": "answer", "sub_index": j, "title": doc.title},
                ))

        return chunks

    def _extract_qa_pairs(self, text: str) -> List[tuple]:
        """텍스트에서 Q/A 쌍 추출"""
        pairs = []
        # 패턴 1: 줄 단위 Q: / A: 구조
        lines = text.split("\n")
        current_q = current_a = ""
        state = None  # "q" | "a"

        q_markers = re.compile(r"^(?:Q\s*[\.:]|질문\s*[\.:]|Q\d+[\.\):]\s*)", re.IGNORECASE)
        a_markers = re.compile(r"^(?:A\s*[\.:]|답변\s*[\.:]|A\d+[\.\):]\s*)", re.IGNORECASE)

        for line in lines:
            stripped = line.strip()
            if q_markers.match(stripped):
                if current_q and current_a:
                    pairs.append((current_q, current_a))
                current_q = q_markers.sub("", stripped).strip()
                current_a = ""
                state = "q"
            elif a_markers.match(stripped):
                current_a = a_markers.sub("", stripped).strip()
                state = "a"
            elif state == "q" and stripped:
                current_q += " " + stripped
            elif state == "a" and stripped:
                current_a += " " + stripped

        if current_q and current_a:
            pairs.append((current_q, current_a))

        return pairs

    # ── 매뉴얼 청킹 ─────────────────────────────────────────────────
    def _chunk_manual(self, doc, subscriber: str) -> List[Chunk]:
        """
        3단계 계층 구조: 챕터(Level1) → 섹션(Level2) → 단락(자식)
        부모: 섹션 전체, 자식: 개별 단락
        """
        chunks: List[Chunk] = []
        text = doc.content

        # 헤딩 기반 섹션 분리
        sections = self._split_by_headings(text)

        for sec_idx, (heading, body) in enumerate(sections):
            if not body.strip():
                continue

            parent_text = (f"{heading}\n{body}").strip() if heading else body.strip()
            parent_id = self._gen_id(doc.doc_id, f"sec_{sec_idx}")

            # 부모 청크 (섹션 전체, 최대 parent_size)
            parent_parts = self._split_to_size(parent_text, self.parent_size)
            for pi, part in enumerate(parent_parts):
                pid = self._gen_id(doc.doc_id, f"sec_{sec_idx}_{pi}")
                chunks.append(Chunk(
                    chunk_id=pid,
                    parent_id=None,
                    subscriber=subscriber,
                    doc_id=doc.doc_id,
                    doc_type="manual",
                    text=part,
                    is_child=False,
                    metadata={"section": sec_idx, "heading": heading, "title": doc.title},
                ))
                # 자식 청크: 단락 단위 분할
                paras = [p.strip() for p in self._PARA_SEP.split(body) if p.strip()]
                for para_idx, para in enumerate(paras):
                    child_parts = self._split_to_child_size(para)
                    for ci, child_text in enumerate(child_parts):
                        if not child_text.strip():
                            continue
                        cid = self._gen_id(doc.doc_id, f"sec_{sec_idx}_{pi}_p{para_idx}_{ci}")
                        chunks.append(Chunk(
                            chunk_id=cid,
                            parent_id=pid,
                            subscriber=subscriber,
                            doc_id=doc.doc_id,
                            doc_type="manual",
                            text=child_text,
                            is_child=True,
                            metadata={
                                "section": sec_idx, "heading": heading,
                                "para": para_idx, "title": doc.title
                            },
                        ))
        return chunks

    def _split_by_headings(self, text: str) -> List[tuple]:
        """헤딩 패턴으로 섹션 분리"""
        parts = self._HEADING_RE.split(text)
        if len(parts) < 2:
            # 헤딩 없으면 문단 기반 분리
            paras = [p.strip() for p in self._PARA_SEP.split(text) if p.strip()]
            return [("", "\n\n".join(paras))]

        sections = []
        i = 0
        headings = self._HEADING_RE.findall(text)

        # 첫 섹션 (헤딩 이전 내용)
        pre = parts[0].strip()
        if pre:
            sections.append(("", pre))

        for heading in headings:
            i += 1
            body = parts[i].strip() if i < len(parts) else ""
            sections.append((heading.strip(), body))

        return sections

    # ── 웹사이트 청킹 ────────────────────────────────────────────────
    def _chunk_website(self, doc, subscriber: str) -> List[Chunk]:
        """
        의미 단위(문단/제목 기준) 청킹.
        슬라이딩 윈도우로 부모 청크 → 세부 분할로 자식 청크
        """
        chunks: List[Chunk] = []
        text = doc.content

        # 문단 단위 분리
        paras = [p.strip() for p in self._PARA_SEP.split(text) if len(p.strip()) > 30]

        # 슬라이딩 윈도우로 부모 청크 생성
        parent_groups = self._group_paras_to_size(paras, self.parent_size)

        for pi, parent_paras in enumerate(parent_groups):
            parent_text = "\n\n".join(parent_paras)
            parent_id = self._gen_id(doc.doc_id, f"web_p_{pi}")

            chunks.append(Chunk(
                chunk_id=parent_id,
                parent_id=None,
                subscriber=subscriber,
                doc_id=doc.doc_id,
                doc_type="website",
                text=parent_text,
                is_child=False,
                metadata={"group": pi, "title": doc.title, "source": doc.source},
            ))

            # 자식 청크: 개별 문단 또는 추가 분할
            for ci, para in enumerate(parent_paras):
                child_parts = self._split_to_child_size(para)
                for cj, child_text in enumerate(child_parts):
                    if not child_text.strip():
                        continue
                    cid = self._gen_id(doc.doc_id, f"web_p_{pi}_c{ci}_{cj}")
                    chunks.append(Chunk(
                        chunk_id=cid,
                        parent_id=parent_id,
                        subscriber=subscriber,
                        doc_id=doc.doc_id,
                        doc_type="website",
                        text=child_text,
                        is_child=True,
                        metadata={"group": pi, "para": ci, "title": doc.title},
                    ))

        return chunks

    # ── 내부 유틸 ─────────────────────────────────────────────────

    def _split_to_child_size(self, text: str) -> List[str]:
        """텍스트를 child_size 토큰 이하의 청크로 분할"""
        return self._split_to_size(text, self.child_size)

    def _split_to_size(self, text: str, max_tokens: int) -> List[str]:
        """텍스트를 max_tokens 기준으로 분할 (문장 경계 존중)"""
        if _approx_tokens(text) <= max_tokens:
            return [text]

        # 문장 경계로 분할
        sentences = re.split(r"(?<=[.!?。])\s+|(?<=\n)", text)
        chunks: List[str] = []
        current: List[str] = []
        current_tokens = 0

        for sent in sentences:
            sent_tokens = _approx_tokens(sent)
            if current_tokens + sent_tokens > max_tokens and current:
                chunks.append(" ".join(current))
                # overlap 적용
                overlap_sents = self._get_overlap_sents(current)
                current = overlap_sents + [sent]
                current_tokens = sum(_approx_tokens(s) for s in current)
            else:
                current.append(sent)
                current_tokens += sent_tokens

        if current:
            chunks.append(" ".join(current))

        return [c.strip() for c in chunks if c.strip()]

    def _get_overlap_sents(self, sents: List[str]) -> List[str]:
        """overlap_tokens 만큼의 마지막 문장들 반환"""
        overlap_sents = []
        total = 0
        for s in reversed(sents):
            t = _approx_tokens(s)
            if total + t > self.overlap:
                break
            overlap_sents.insert(0, s)
            total += t
        return overlap_sents

    def _group_paras_to_size(self, paras: List[str], max_tokens: int) -> List[List[str]]:
        """문단 목록을 max_tokens 기준 그룹으로 묶음"""
        groups: List[List[str]] = []
        current: List[str] = []
        current_tokens = 0

        for para in paras:
            pt = _approx_tokens(para)
            if current_tokens + pt > max_tokens and current:
                groups.append(current)
                current = [para]
                current_tokens = pt
            else:
                current.append(para)
                current_tokens += pt

        if current:
            groups.append(current)

        return groups

    @staticmethod
    def _gen_id(doc_id: str, suffix: str) -> str:
        raw = f"{doc_id}_{suffix}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
