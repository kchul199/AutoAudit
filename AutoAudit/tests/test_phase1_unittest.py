"""Phase 1 단위 테스트 — unittest 기반 (외부 패키지 불필요)"""
import sys
import json
import unittest
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.cp1_preprocessing.log_parser import LogParser, Turn, Conversation
from app.cp1_preprocessing.doc_loader import DocLoader, detect_doc_type
from app.cp2_knowledge_base.chunker import ParentChildChunker, Chunk, _approx_tokens
from app.cp3_retrieval.query_builder import ConversationAwareQueryBuilder


# ── CP1 LogParser 테스트 ──────────────────────────────────────────

class TestLogParser(unittest.TestCase):

    def setUp(self):
        self.parser = LogParser(subscriber="테스트사")

    def test_parse_basic_text(self):
        text = "콜봇: 안녕하세요.\n고객: 요금제 변경하고 싶어요.\n콜봇: 어떤 요금제인가요?"
        convs = self.parser.parse_text(text)
        self.assertEqual(len(convs), 1)
        self.assertEqual(len(convs[0].turns), 3)
        self.assertEqual(convs[0].turns[0].role, "bot")
        self.assertEqual(convs[0].turns[1].role, "user")
        self.assertIn("요금제", convs[0].turns[1].text)

    def test_parse_multiple_conversations(self):
        text = "콜봇: 대화1.\n고객: 질문1.\n\n\n콜봇: 대화2.\n고객: 질문2."
        convs = self.parser.parse_text(text)
        self.assertGreaterEqual(len(convs), 1)

    def test_parse_json_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = [{"id": "c001", "turns": [
                {"role": "bot", "content": "안녕하세요"},
                {"role": "user", "content": "문의드립니다"},
            ]}]
            p = Path(tmp) / "test.json"
            p.write_text(json.dumps(data, ensure_ascii=False))
            convs = self.parser.parse_file(str(p))
            self.assertEqual(len(convs), 1)
            self.assertEqual(convs[0].id, "c001")
            self.assertEqual(len(convs[0].turns), 2)

    def test_parse_csv_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_content = "id,role,content\nc1,bot,안녕하세요\nc1,user,문의드립니다\nc1,bot,도와드릴게요"
            p = Path(tmp) / "test.csv"
            p.write_text(csv_content, encoding="utf-8")
            convs = self.parser.parse_file(str(p))
            self.assertEqual(len(convs), 1)
            self.assertEqual(len(convs[0].turns), 3)

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = "콜봇: 안녕하세요.\n고객: 문의드립니다."
            convs = self.parser.parse_text(text)
            save_path = str(Path(tmp) / "parsed.json")
            LogParser.save_parsed(convs, save_path)
            loaded = LogParser.load_parsed(save_path)
            self.assertEqual(len(loaded), len(convs))
            self.assertEqual(loaded[0].turns[0].role, convs[0].turns[0].role)

    def test_full_text_property(self):
        text = "콜봇: 안녕하세요.\n고객: 요금 문의입니다."
        conv = self.parser.parse_text(text)[0]
        full = conv.full_text
        self.assertIn("콜봇:", full)
        self.assertIn("고객:", full)

    def test_conversation_subscriber(self):
        text = "콜봇: 안녕.\n고객: 네."
        convs = self.parser.parse_text(text)
        self.assertEqual(convs[0].subscriber, "테스트사")


# ── CP1 DocLoader 테스트 ──────────────────────────────────────────

class TestDocLoader(unittest.TestCase):

    def setUp(self):
        self.loader = DocLoader(subscriber="테스트사")

    def test_load_text_inline(self):
        doc = self.loader.load_text("Q: 질문입니다.\nA: 답변입니다.", title="FAQ")
        self.assertEqual(doc.subscriber, "테스트사")
        self.assertEqual(doc.title, "FAQ")
        self.assertGreater(len(doc.content), 0)

    def test_load_txt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "manual.txt"
            p.write_text("제1장 서비스 안내\n\n요금제 변경 방법입니다.", encoding="utf-8")
            doc = self.loader.load_file(str(p))
            self.assertIn("요금제", doc.content)
            self.assertIn(doc.doc_type, ("faq", "manual", "website"))

    def test_load_html_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = "<html><body><h1>FAQ</h1><p>Q: 요금?\nA: 3만원입니다.</p></body></html>"
            p = Path(tmp) / "faq.html"
            p.write_text(html, encoding="utf-8")
            doc = self.loader.load_file(str(p))
            self.assertIn("FAQ", doc.content)

    def test_detect_faq_type(self):
        text = "Q: 질문.\nA: 답변.\nQ: 질문2.\nA: 답변2."
        result = detect_doc_type(text, "faq.txt")
        self.assertEqual(result, "faq")

    def test_detect_manual_type(self):
        result = detect_doc_type("내용", "manual.pdf")
        self.assertEqual(result, "manual")

    def test_load_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("내용1", encoding="utf-8")
            (Path(tmp) / "b.txt").write_text("내용2", encoding="utf-8")
            docs = self.loader.load_directory(tmp)
            self.assertEqual(len(docs), 2)

    def test_doc_id_generated(self):
        doc = self.loader.load_text("테스트 내용", title="test")
        self.assertIsNotNone(doc.doc_id)
        self.assertGreater(len(doc.doc_id), 0)


# ── CP2 ParentChildChunker 테스트 ─────────────────────────────────

class TestParentChildChunker(unittest.TestCase):

    def setUp(self):
        self.chunker = ParentChildChunker(child_chunk_size=100, parent_chunk_size=400)

    def _make_doc(self, content, doc_type, title="test"):
        class FakeDoc:
            pass
        d = FakeDoc()
        d.doc_id, d.doc_type, d.title = "doc001", doc_type, title
        d.content, d.subscriber, d.source = content, "테스트사", "test"
        return d

    def test_faq_chunking(self):
        content = "Q: 요금제 변경 방법은?\nA: 앱 > 마이페이지 > 요금제 변경에서 가능합니다."
        chunks = self.chunker.chunk(self._make_doc(content, "faq"))
        self.assertGreater(len(chunks), 0)
        parents = [c for c in chunks if not c.is_child]
        children = [c for c in chunks if c.is_child]
        self.assertGreater(len(parents), 0)
        self.assertGreater(len(children), 0)

    def test_manual_chunking(self):
        content = "## 1. 요금제 변경\n앱에서 변경 가능합니다.\n\n## 2. 장애처리\n모뎀을 재부팅하세요."
        chunks = self.chunker.chunk(self._make_doc(content, "manual"))
        self.assertGreater(len(chunks), 0)

    def test_website_chunking(self):
        content = (
            "저희는 최고의 통신 서비스를 제공하는 기업입니다. 다양한 요금제와 부가서비스를 제공합니다.\n\n"
            "월 3만원부터 시작하는 합리적인 요금제를 선택하실 수 있습니다. 가족 결합 할인도 가능합니다.\n\n"
            "고객센터는 24시간 365일 운영되며 언제든지 문의하실 수 있습니다. 전화, 채팅, 방문 상담 가능합니다."
        )
        chunks = self.chunker.chunk(self._make_doc(content, "website"))
        self.assertGreater(len(chunks), 0)

    def test_parent_child_integrity(self):
        content = "Q: 질문1.\nA: 답변1.\n\nQ: 질문2.\nA: 답변2."
        chunks = self.chunker.chunk(self._make_doc(content, "faq"))
        parent_ids = {c.chunk_id for c in chunks if not c.is_child}
        for child in (c for c in chunks if c.is_child):
            self.assertIn(child.parent_id, parent_ids)

    def test_chunk_fields(self):
        content = "Q: 질문.\nA: 답변입니다."
        chunks = self.chunker.chunk(self._make_doc(content, "faq"))
        for c in chunks:
            self.assertEqual(c.doc_id, "doc001")
            self.assertEqual(c.subscriber, "테스트사")
            self.assertIn(c.doc_type, ("faq", "manual", "website"))
            self.assertIsNotNone(c.chunk_id)
            self.assertGreater(len(c.text), 0)

    def test_chunk_to_dict(self):
        content = "Q: 질문.\nA: 답변."
        chunks = self.chunker.chunk(self._make_doc(content, "faq"))
        d = chunks[0].to_dict()
        self.assertIn("chunk_id", d)
        self.assertIn("text", d)
        self.assertIn("is_child", d)

    def test_chunk_all_multiple_docs(self):
        docs = [
            self._make_doc("Q: 질문1.\nA: 답변1.", "faq", "FAQ"),
            self._make_doc("## 섹션\n내용.", "manual", "Manual"),
        ]
        all_chunks = self.chunker.chunk_all(docs)
        self.assertGreater(len(all_chunks), 0)

    def test_approx_tokens(self):
        self.assertEqual(_approx_tokens("안녕하세요"), max(1, len("안녕하세요") // 2))
        self.assertEqual(_approx_tokens(""), 1)


# ── CP3 QueryBuilder 테스트 (API 없이) ───────────────────────────

class TestQueryBuilder(unittest.TestCase):

    def setUp(self):
        self.builder = ConversationAwareQueryBuilder(
            context_turns=3,
            anthropic_api_key="DUMMY",
        )

    def test_standalone_true(self):
        self.assertTrue(ConversationAwareQueryBuilder._is_standalone("요금제 변경 방법이 뭔가요?"))

    def test_standalone_false(self):
        self.assertFalse(ConversationAwareQueryBuilder._is_standalone("그것은 어떻게 하나요?"))

    def test_format_history(self):
        turns = [
            Turn(role="user", text="요금제 변경하고 싶어요"),
            Turn(role="bot", text="어떤 요금제로 변경하시겠어요?"),
        ]
        history = ConversationAwareQueryBuilder._format_history(turns)
        self.assertIn("고객:", history)
        self.assertIn("콜봇:", history)

    def test_build_no_history_returns_original(self):
        turn = Turn(role="user", text="요금제 변경 방법이 뭔가요?")
        result = self.builder.build(turn, [])
        self.assertEqual(result, "요금제 변경 방법이 뭔가요?")

    def test_build_standalone_query_no_rewrite(self):
        turn = Turn(role="user", text="인터넷 속도 개선 방법을 알고 싶어요")
        history = [Turn(role="bot", text="안녕하세요")]
        result = self.builder.build(turn, history)
        # standalone이므로 원본 반환
        self.assertEqual(result, "인터넷 속도 개선 방법을 알고 싶어요")


# ── 통합 테스트 ───────────────────────────────────────────────────

class TestIntegration(unittest.TestCase):

    def test_cp1_to_cp2_pipeline(self):
        """CP1 파싱 → CP2 청킹 통합 흐름"""
        # CP1
        parser = LogParser(subscriber="통합테스트")
        convs = parser.parse_text("콜봇: 안녕하세요.\n고객: 요금 문의입니다.\n콜봇: 어떤 요금제인가요?")
        self.assertEqual(len(convs), 1)
        self.assertEqual(len(convs[0].turns), 3)

        loader = DocLoader(subscriber="통합테스트")
        doc = loader.load_text("Q: 요금제 변경?\nA: 앱에서 가능합니다.", title="FAQ", doc_type="faq")
        self.assertGreater(len(doc.content), 0)

        # CP2
        chunker = ParentChildChunker(child_chunk_size=50, parent_chunk_size=200)
        chunks = chunker.chunk(doc)
        self.assertGreater(len(chunks), 0)

        parent_ids = {c.chunk_id for c in chunks if not c.is_child}
        for child in (c for c in chunks if c.is_child):
            self.assertIn(child.parent_id, parent_ids)

    def test_sample_data_flow(self):
        """샘플 데이터로 전체 CP1~CP2 흐름"""
        subscriber = "샘플가입자"

        # CP1: 로그 파싱
        parser = LogParser(subscriber=subscriber)
        log_text = """콜봇: 안녕하세요, 고객센터입니다.
고객: 요금제 변경하고 싶습니다.
콜봇: 네, 요금제 변경을 도와드리겠습니다. 현재 어떤 요금제이신가요?
고객: LTE 기본 요금제입니다.
콜봇: 5G 요금제로 변경 가능합니다. 앱 > 마이페이지 > 요금제 변경에서 진행해주세요."""
        conversations = parser.parse_text(log_text)
        self.assertGreater(len(conversations), 0)
        self.assertGreater(len(conversations[0].turns), 0)

        # CP1: 문서 로드
        loader = DocLoader(subscriber=subscriber)
        faq_doc = loader.load_text(
            "Q: 요금제 변경은 어떻게 하나요?\nA: 앱 > 마이페이지 > 요금제 변경에서 가능합니다.",
            title="요금제 FAQ", doc_type="faq"
        )
        manual_doc = loader.load_text(
            "## 1. 요금제 변경 절차\n\n앱을 실행하세요.\n마이페이지를 클릭하세요.\n요금제 변경을 선택하세요.",
            title="서비스 가이드", doc_type="manual"
        )

        # CP2: 청킹
        chunker = ParentChildChunker()
        all_chunks = chunker.chunk_all([faq_doc, manual_doc])
        self.assertGreater(len(all_chunks), 0)

        child_chunks = [c for c in all_chunks if c.is_child]
        parent_chunks = [c for c in all_chunks if not c.is_child]
        self.assertGreater(len(child_chunks), 0)
        self.assertGreater(len(parent_chunks), 0)

        # 가입자 일치 확인
        for chunk in all_chunks:
            self.assertEqual(chunk.subscriber, subscriber)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
