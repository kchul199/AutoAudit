"""
CP1 — 콜봇 대화 로그 파서
────────────────────────────────────────────────────
지원 형식:
  1. 텍스트 (콜봇: / 고객: 구분자)
  2. JSON  ({role, content, timestamp})
  3. CSV   (role, content, [timestamp] 컬럼)

출력: List[Conversation]
  Conversation.id          : 고유 대화 ID
  Conversation.subscriber  : 가입자명
  Conversation.turns       : List[Turn]
  Turn.role                : "bot" | "user"
  Turn.text                : 발화 텍스트
  Turn.timestamp           : ISO 8601 문자열 (없으면 None)
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── 데이터 클래스 ─────────────────────────────────────────────────

@dataclass
class Turn:
    role: str          # "bot" | "user"
    text: str
    timestamp: Optional[str] = None

    def to_dict(self) -> dict:
        return {"role": self.role, "text": self.text, "timestamp": self.timestamp}


@dataclass
class Conversation:
    id: str
    subscriber: str
    source_file: str
    turns: List[Turn] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "subscriber": self.subscriber,
            "source_file": self.source_file,
            "turn_count": len(self.turns),
            "turns": [t.to_dict() for t in self.turns],
            "metadata": self.metadata,
        }

    @property
    def full_text(self) -> str:
        """평가용 전체 대화 텍스트 (role: text 형태)"""
        return "\n".join(
            f"{'콜봇' if t.role == 'bot' else '고객'}: {t.text}"
            for t in self.turns
        )


# ── 파서 클래스 ───────────────────────────────────────────────────

class LogParser:
    """
    가입자별 콜봇 로그 파일을 파싱하여 Conversation 목록으로 변환.

    사용 예:
        parser = LogParser(subscriber="한국통신")
        conversations = parser.parse_file("logs/kt_20240101.txt")
    """

    # 텍스트 형식 구분자 패턴 (커스터마이즈 가능)
    BOT_PATTERNS  = [r"^콜봇\s*:", r"^bot\s*:", r"^상담원\s*:", r"^\[bot\]"]
    USER_PATTERNS = [r"^고객\s*:",  r"^user\s*:", r"^고객님\s*:", r"^\[user\]"]

    # 대화 구분자 (빈 줄 2개 이상 또는 특수 패턴)
    CONV_SEPARATOR = re.compile(r"\n{2,}(?=콜봇\s*:|고객\s*:|bot\s*:|user\s*:|\[bot\]|\[user\])",
                                re.MULTILINE | re.IGNORECASE)

    def __init__(
        self,
        subscriber: str,
        bot_patterns: List[str] = None,
        user_patterns: List[str] = None,
    ):
        self.subscriber = subscriber
        self._bot_re  = [re.compile(p, re.IGNORECASE) for p in (bot_patterns  or self.BOT_PATTERNS)]
        self._user_re = [re.compile(p, re.IGNORECASE) for p in (user_patterns or self.USER_PATTERNS)]

    # ── Public API ────────────────────────────────────────────────

    def parse_file(self, file_path: str) -> List[Conversation]:
        """단일 파일 파싱"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"로그 파일 없음: {file_path}")

        ext = path.suffix.lower()
        logger.info(f"[CP1] 파싱 시작: {path.name} ({ext})")

        if ext == ".json":
            convs = self._parse_json(path)
        elif ext == ".csv":
            convs = self._parse_csv(path)
        else:
            convs = self._parse_text(path)

        logger.info(f"[CP1] 파싱 완료: {len(convs)}개 대화, "
                    f"{sum(len(c.turns) for c in convs)}개 턴")
        return convs

    def parse_directory(self, dir_path: str) -> List[Conversation]:
        """디렉토리 내 모든 로그 파일 파싱"""
        exts = {".txt", ".json", ".csv", ".log"}
        files = [f for f in Path(dir_path).rglob("*") if f.suffix.lower() in exts]
        logger.info(f"[CP1] 디렉토리 파싱: {dir_path} ({len(files)}개 파일)")

        all_convs: List[Conversation] = []
        for f in files:
            try:
                all_convs.extend(self.parse_file(str(f)))
            except Exception as e:
                logger.error(f"[CP1] 파싱 오류 {f.name}: {e}")
        return all_convs

    def parse_text(self, text: str, source_name: str = "inline") -> List[Conversation]:
        """텍스트 문자열 직접 파싱 (UI 붙여넣기용)"""
        return self._parse_text_string(text, source_name)

    # ── 내부 파서 ─────────────────────────────────────────────────

    def _parse_text(self, path: Path) -> List[Conversation]:
        text = path.read_text(encoding="utf-8", errors="replace")
        return self._parse_text_string(text, path.name)

    def _parse_text_string(self, text: str, source_name: str) -> List[Conversation]:
        """
        콜봇: / 고객: 구분자 기반 텍스트 파싱.
        빈 줄 2개 이상으로 대화 경계를 구분.
        """
        # 대화 블록 분리
        blocks = self.CONV_SEPARATOR.split(text)
        if len(blocks) == 1:
            blocks = [text]  # 구분자 없으면 전체를 하나의 대화로

        conversations: List[Conversation] = []
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            turns = self._extract_turns_from_text(block)
            if not turns:
                continue
            conv = Conversation(
                id=self._gen_id(block),
                subscriber=self.subscriber,
                source_file=source_name,
                turns=turns,
            )
            conversations.append(conv)
        return conversations

    def _extract_turns_from_text(self, block: str) -> List[Turn]:
        """텍스트 블록에서 Turn 목록 추출"""
        lines = block.split("\n")
        turns: List[Turn] = []
        current_role: Optional[str] = None
        current_lines: List[str] = []

        for line in lines:
            line = line.rstrip()
            role, text = self._detect_role_and_text(line)
            if role:
                # 이전 turn 저장
                if current_role and current_lines:
                    full_text = " ".join(current_lines).strip()
                    if full_text:
                        turns.append(Turn(role=current_role, text=full_text))
                current_role = role
                current_lines = [text] if text else []
            elif current_role and line:
                current_lines.append(line)

        # 마지막 turn 저장
        if current_role and current_lines:
            full_text = " ".join(current_lines).strip()
            if full_text:
                turns.append(Turn(role=current_role, text=full_text))

        return turns

    def _detect_role_and_text(self, line: str) -> tuple[Optional[str], str]:
        """줄에서 역할과 발화 텍스트 분리"""
        for pat in self._bot_re:
            m = pat.match(line)
            if m:
                return "bot", line[m.end():].strip()
        for pat in self._user_re:
            m = pat.match(line)
            if m:
                return "user", line[m.end():].strip()
        return None, line

    def _parse_json(self, path: Path) -> List[Conversation]:
        """
        JSON 형식 파싱.
        지원 구조:
          A) 배열: [{id, turns: [{role, content, timestamp}]}]
          B) 단일 대화: {id, turns: [...]}
          C) 배열 of turns: [{role, content, timestamp}] (전체를 1개 대화로)
        """
        raw = json.loads(path.read_text(encoding="utf-8"))

        # 구조 A/B 판별
        if isinstance(raw, dict):
            raw = [raw]

        conversations: List[Conversation] = []

        # 구조 C: turns 배열 직접
        if raw and isinstance(raw[0], dict) and "role" in raw[0]:
            turns = [self._parse_turn_dict(t) for t in raw]
            turns = [t for t in turns if t]
            if turns:
                conversations.append(Conversation(
                    id=self._gen_id(str(raw)),
                    subscriber=self.subscriber,
                    source_file=path.name,
                    turns=turns,
                ))
            return conversations

        # 구조 A/B: 대화 배열
        for item in raw:
            conv_id = item.get("id") or item.get("conversation_id") or self._gen_id(str(item))
            raw_turns = item.get("turns") or item.get("messages") or []
            turns = [self._parse_turn_dict(t) for t in raw_turns]
            turns = [t for t in turns if t]
            if turns:
                conversations.append(Conversation(
                    id=str(conv_id),
                    subscriber=self.subscriber,
                    source_file=path.name,
                    turns=turns,
                    metadata={k: v for k, v in item.items() if k not in ("turns", "messages", "id")},
                ))
        return conversations

    def _parse_turn_dict(self, d: dict) -> Optional[Turn]:
        """JSON 딕셔너리에서 Turn 생성"""
        role_raw = str(d.get("role", "")).lower()
        text = str(d.get("content") or d.get("text") or "").strip()
        if not text:
            return None
        # role 정규화
        if role_raw in ("bot", "assistant", "콜봇", "상담원"):
            role = "bot"
        elif role_raw in ("user", "human", "고객", "고객님"):
            role = "user"
        else:
            return None
        ts = d.get("timestamp") or d.get("created_at")
        return Turn(role=role, text=text, timestamp=str(ts) if ts else None)

    def _parse_csv(self, path: Path) -> List[Conversation]:
        """
        CSV 형식 파싱.
        필수 컬럼: role, content (또는 text)
        선택 컬럼: id, timestamp
        """
        conversations: List[Conversation] = []
        current_id: Optional[str] = None
        current_turns: List[Turn] = []

        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 컬럼명 유연 처리
                role_raw = (row.get("role") or row.get("역할") or "").strip().lower()
                text = (row.get("content") or row.get("text") or row.get("발화") or "").strip()
                conv_id = (row.get("id") or row.get("conversation_id") or "").strip()
                ts = row.get("timestamp") or row.get("time")

                if not text:
                    continue

                # 새 대화 시작 감지
                if conv_id and conv_id != current_id:
                    if current_turns:
                        conversations.append(Conversation(
                            id=current_id or self._gen_id(str(current_turns)),
                            subscriber=self.subscriber,
                            source_file=path.name,
                            turns=current_turns,
                        ))
                    current_id = conv_id
                    current_turns = []

                # role 정규화
                if role_raw in ("bot", "assistant", "콜봇", "상담원"):
                    role = "bot"
                elif role_raw in ("user", "human", "고객", "고객님"):
                    role = "user"
                else:
                    continue

                current_turns.append(Turn(role=role, text=text, timestamp=str(ts) if ts else None))

        # 마지막 대화 저장
        if current_turns:
            conversations.append(Conversation(
                id=current_id or self._gen_id(str(current_turns)),
                subscriber=self.subscriber,
                source_file=path.name,
                turns=current_turns,
            ))
        return conversations

    @staticmethod
    def _gen_id(content: str) -> str:
        """콘텐츠 기반 고유 ID 생성"""
        return hashlib.md5(content.encode("utf-8")).hexdigest()[:12]

    # ── 저장 ─────────────────────────────────────────────────────

    @staticmethod
    def save_parsed(conversations: List[Conversation], output_path: str) -> None:
        """파싱 결과를 JSON으로 저장"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        data = [c.to_dict() for c in conversations]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[CP1] 저장 완료: {output_path} ({len(data)}개 대화)")

    @staticmethod
    def load_parsed(input_path: str) -> List[Conversation]:
        """저장된 파싱 결과 로드"""
        with open(input_path, encoding="utf-8") as f:
            data = json.load(f)
        convs = []
        for d in data:
            turns = [Turn(**t) for t in d["turns"]]
            convs.append(Conversation(
                id=d["id"],
                subscriber=d["subscriber"],
                source_file=d["source_file"],
                turns=turns,
                metadata=d.get("metadata", {}),
            ))
        return convs
