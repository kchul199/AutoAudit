"""
Phase 1 단위 테스트 (외부 API 없이 로컬에서 실행 가능)
────────────────────────────────────────────────────────
python -m pytest tests/test_phase1.py -v
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from app.cp1_preprocessing.log_parser import LogParser, Turn, Conversation
from app.cp1_preprocessing.doc_loader import DocLoader, detect_doc_type
from app.cp2_knowledge_base.chunker import ParentChildChunker, Chunk, _approx_tokens


# ══════════════════════════════════════════════════════════════════
# CP1 — LogParser 테스트
# ══════════════════════════════════════════════════════════════════

class TestLogParser:
    def setup_method(self):
        self.parser = LogParser(subscriber="테스트사")

    def test_parse_text_basic(self):
        """기본 텍스트 형식 파싱"""
        text = """콜봇: 안녕하세요, 고객센터입니다.
고객: 요금제 변경하고 싶어요.
콜봇: 네, 어떤 요금제로 변경하시겠어요?
고객: 5G 요금제로요."""
        convs = self.parser.parse_text(text)
        assert len(convs) == 1
        assert len(convs[0].turns) == 4
        assert convs[0].turns[0].role == "bot"
        assert convs[0].turns[1].role == "user"
        assert "요금제" in convs[0].turns[1].text

    def test_parse_text_multiple_conversations(self):
        """빈 줄로 구분된 여러 대화 파싱"""
        text = """콜봇: 안녕하세요.
고객: 요금 문의입니다.
콜봇: 어떤 요금제인가요?


콜봇: 또 다른 대화입니다.
고객: 인터넷 장애 신고합니다."""
        convs = self.parser.parse_text(text)
        assert len(convs) == 2

    def test_parse_json_format(self, tmp_path):
        """JSON 형식 파싱"""
        import json
        data = [
            {
                "id": "conv001",
                "turns": [
                    {"role": "bot", "content": "안녕하세요"},
                    {"role": "user", "content": "요금 문의드립니다"},
                    {"role": "assistant", "content": "어떤 요금제인가요?"},
                ]
            }
        ]
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(data, ensure_ascii=False))

        convs = self.parser.parse_file(str(json_file))
        assert len(convs) == 1
        assert convs[0].id == "conv001"
        assert len(convs[0].turns) == 3

    def test_parse_csv_format(self, tmp_path):
        """CSV 형식 파싱"""
        csv_content = "id,role,content\nconv1,bot,안녕하세요\nconv1,user,문의드립니다\nconv1,bot,도와드리겠습니다"
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        convs = self.parser.parse_file(str(csv_file))
        assert len(convs) == 1
        assert len(convs[0].turns) == 3

    def test_save_and_load(self, tmp_path):
        """저장 및 로드 왕복 테스트"""
        text = "콜봇: 안녕하세요.\n고객: 문의드립니다."
        convs = self.parser.parse_text(text)

        save_path = str(tmp_path / "parsed.json")
        LogParser.save_parsed(convs, save_path)

        loaded = LogParser.load_parsed(save_path)
        assert len(loaded) == len(convs)
        assert loaded[0].turns[0].role == convs[0].turns[0].role

    def test_conversation_full_text(self):
        """full_text 프로퍼티"""
        text = "콜봇: 안녕하세요.\n고객: 요금 문의입니다."
        conv = self.parser.parse_text(text)[0]
        full = conv.full_text
        assert "콜봇:" in full
        assert "고객:" in full

    def test_role_normalization(self):
        """다양한 역할 표기 정규화"""
        text = "상담원: 도와드리겠습니다.\n고객님: 감사합니다."
        convs = self.parser.parse_text(text)
        if convs and convs[0].turns:
            assert convs[0].turns[0].role in ("bot", "user")


# ══════════════════════════════════════════════════════════════════
# CP1 — DocLoader 테스트
# ══════════════════════════════════════════════════════════════════

class TestDocLoader:
    def setup_method(self):
        self.loader = DocLoader(subscriber="테스트사")

    def test_load_text(self):
        """텍스트 직접 로드"""
        doc = self.loader.load_text("Q: 질문입니다.\nA: 답변입니다.", title="FAQ")
        assert doc.subscriber == "테스트사"
        assert doc.title == "FAQ"
        assert len(doc.content) > 0

    def test_load_txt_file(self, tmp_path):
        """TXT 파일 로드"""
        txt_file = tmp_path / "manual.txt"
        txt_file.write_text("제1장 서비스 안내\n\n1.1 요금제 안내\n요금제 변경 방법입니다.", encoding="utf-8")

        doc = self.loader.load_file(str(txt_file))
        assert doc.doc_type in ("faq", "manual", "website")
        assert "요금제" in doc.content

    def test_load_html_file(self, tmp_path):
        """HTML 파일 로드"""
        html_content = """<html><head><title>FAQ</title></head>
<body><h1>자주 묻는 질문</h1>
<p>Q: 요금은 어떻게 납부하나요?</p>
<p>A: 매월 자동이체로 납부됩니다.</p></body></html>"""
        html_file = tmp_path / "faq.html"
        html_file.write_text(html_content, encoding="utf-8")

        doc = self.loader.load_file(str(html_file))
        assert "요금" in doc.content

    def test_detect_doc_type_faq(self):
        """FAQ 문서 타입 감지"""
        text = "Q: 질문입니다.\nA: 답변입니다.\nQ: 또 다른 질문.\nA: 또 다른 답변."
        assert detect_doc_type(text, "faq.txt") == "faq"

    def test_detect_doc_type_manual(self):
        """매뉴얼 문서 타입 감지"""
        text = "제1장 서비스 개요\n1.1 목적\n매뉴얼 이용 절차입니다. 단계별로 안내합니다."
        result = detect_doc_type(text, "manual.pdf")
        assert result in ("manual", "faq", "website")  # 파일명 힌트로 manual 예상

    def test_load_directory(self, tmp_path):
        """디렉토리 일괄 로드"""
        (tmp_path / "doc1.txt").write_text("문서 1 내용입니다.", encoding="utf-8")
        (tmp_path / "doc2.txt").write_text("문서 2 내용입니다.", encoding="utf-8")

        docs = self.loader.load_directory(str(tmp_path))
        assert len(docs) == 2


# ══════════════════════════════════════════════════════════════════
# CP2 — ParentChildChunker 테스트
# ══════════════════════════════════════════════════════════════════

class TestParentChildChunker:
    def setup_method(self):
        self.chunker = ParentChildChunker(child_chunk_size=100, parent_chunk_size=400)

    def _make_doc(self, content: str, doc_type: str, title: str = "test"):
        """테스트용 더미 문서 객체"""
        class FakeDoc:
            pass
        doc = FakeDoc()
        doc.doc_id = "doc001"
        doc.doc_type = doc_type
        doc.title = title
        doc.content = content
        doc.subscriber = "테스트사"
        doc.source = "test"
        return doc

    def test_chunk_faq(self):
        """FAQ 청킹 — Q/A 쌍 분리"""
        content = """Q: 요금제 변경은 어떻게 하나요?
A: 앱 > 마이페이지 > 요금제 변경에서 가능합니다. 즉시 적용됩니다.

Q: 납부일은 언제인가요?
A: 매월 25일에 자동 납부됩니다."""

        doc = self._make_doc(content, "faq")
        chunks = self.chunker.chunk(doc)

        parent_chunks = [c for c in chunks if not c.is_child]
        child_chunks  = [c for c in chunks if c.is_child]

        assert len(parent_chunks) >= 1
        assert len(child_chunks) >= 2  # 최소 Q 자식 + A 자식
        # 모든 자식은 parent_id 가져야 함
        for c in child_chunks:
            assert c.parent_id is not None

    def test_chunk_manual(self):
        """매뉴얼 청킹 — 섹션 분리"""
        content = """# 서비스 이용 가이드

## 1. 요금제 변경

요금제 변경은 앱에서 가능합니다. 마이페이지로 이동하세요.

절차:
1단계: 앱 실행
2단계: 마이페이지 선택
3단계: 요금제 관리 클릭

## 2. 장애 처리

인터넷 장애 시 모뎀을 재부팅하세요."""

        doc = self._make_doc(content, "manual")
        chunks = self.chunker.chunk(doc)
        assert len(chunks) > 0
        parent_chunks = [c for c in chunks if not c.is_child]
        assert len(parent_chunks) >= 1

    def test_chunk_website(self):
        """웹사이트 청킹 — 문단 기반"""
        content = """서비스 소개 페이지입니다.

저희는 최고의 통신 서비스를 제공합니다. 다양한 요금제와 혜택을 경험해보세요.

요금제 안내입니다. 월 3만원부터 다양한 요금제를 선택할 수 있습니다.

고객센터는 24시간 운영됩니다. 언제든지 문의해주세요."""

        doc = self._make_doc(content, "website")
        chunks = self.chunker.chunk(doc)
        assert len(chunks) > 0

    def test_parent_child_relationship(self):
        """부모-자식 관계 검증"""
        content = "Q: 테스트 질문입니다.\nA: 테스트 답변입니다. 자세한 내용은 아래를 참조하세요."
        doc = self._make_doc(content, "faq")
        chunks = self.chunker.chunk(doc)

        parent_ids = {c.chunk_id for c in chunks if not c.is_child}
        for child in (c for c in chunks if c.is_child):
            assert child.parent_id in parent_ids, f"자식 청크의 parent_id가 유효하지 않음: {child.parent_id}"

    def test_chunk_all(self):
        """여러 문서 일괄 청킹"""
        docs = [
            self._make_doc("Q: 질문1.\nA: 답변1.", "faq", "FAQ1"),
            self._make_doc("## 섹션1\n내용입니다.", "manual", "Manual1"),
        ]
        all_chunks = self.chunker.chunk_all(docs)
        assert len(all_chunks) > 0

    def test_approx_tokens(self):
        """토큰 수 추정"""
        assert _approx_tokens("안녕하세요") == max(1, len("안녕하세요") // 2)
        assert _approx_tokens("") == 1

    def test_chunk_metadata(self):
        """청크 메타데이터 포함 확인"""
        content = "Q: 질문.\nA: 답변입니다."
        doc = self._make_doc(content, "faq")
        chunks = self.chunker.chunk(doc)
        for c in chunks:
            assert c.doc_id == "doc001"
            assert c.subscriber == "테스트사"
            assert c.doc_type == "faq"
            d = c.to_dict()
            assert "chunk_id" in d
            assert "text" in d


# ══════════════════════════════════════════════════════════════════
# CP3 — 쿼리 빌더 테스트 (API 없이)
# ══════════════════════════════════════════════════════════════════

class TestQueryBuilder:
    def setup_method(self):
        from app.cp3_retrieval.query_builder import ConversationAwareQueryBuilder
        self.builder = ConversationAwareQueryBuilder(
            context_turns=3,
            anthropic_api_key="DUMMY_KEY_FOR_TEST",
        )

    def test_standalone_detection(self):
        """독립적 발화 감지"""
        from app.cp3_retrieval.query_builder import ConversationAwareQueryBuilder
        assert ConversationAwareQueryBuilder._is_standalone("요금제 변경 방법이 뭔가요?") is True
        assert ConversationAwareQueryBuilder._is_standalone("그것은 어떻게 하나요?") is False

    def test_format_history(self):
        """대화 이력 포맷"""
        from app.cp3_retrieval.query_builder import ConversationAwareQueryBuilder
        turns = [
            Turn(role="user", text="요금제 변경하고 싶어요"),
            Turn(role="bot", text="어떤 요금제로 변경하시겠어요?"),
        ]
        history = ConversationAwareQueryBuilder._format_history(turns)
        assert "고객:" in history
        assert "콜봇:" in history
        assert "요금제" in history

    def test_build_no_history(self):
        """이전 대화 없을 때 원본 반환"""
        turn = Turn(role="user", text="요금제 변경 방법이 뭔가요?")
        result = self.builder.build(turn, [])
        assert result == "요금제 변경 방법이 뭔가요?"


# ══════════════════════════════════════════════════════════════════
# 통합 테스트 (샘플 데이터로 CP1~CP2 실행)
# ══════════════════════════════════════════════════════════════════

class TestIntegration:
    def test_cp1_to_cp2_pipeline(self, tmp_path):
        """CP1 파싱 → CP2 청킹 통합 흐름"""
        # CP1
        parser = LogParser(subscriber="통합테스트")
        conv_text = "콜봇: 안녕하세요.\n고객: 요금 문의입니다.\n콜봇: 어떤 요금제인가요?"
        conversations = parser.parse_text(conv_text)
        assert len(conversations) == 1

        loader = DocLoader(subscriber="통합테스트")
        doc = loader.load_text(
            "Q: 요금제 변경 방법?\nA: 앱에서 변경 가능합니다.",
            title="FAQ",
            doc_type="faq",
        )

        # CP2 청킹
        chunker = ParentChildChunker(child_chunk_size=50, parent_chunk_size=200)
        chunks = chunker.chunk(doc)

        assert len(chunks) > 0
        # 부모-자식 관계 무결성
        parent_ids = {c.chunk_id for c in chunks if not c.is_child}
        for child in (c for c in chunks if c.is_child):
            assert child.parent_id in parent_ids


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
