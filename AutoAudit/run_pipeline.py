#!/usr/bin/env python3
"""
AutoAudit — RAG 콜봇 품질 자동 검증 파이프라인 실행 진입점
────────────────────────────────────────────────────────────
사용법:
  # 특정 가입자 평가 (전체 CP1~CP6)
  python run_pipeline.py --subscriber 한국통신

  # 전체 가입자 평가
  python run_pipeline.py --all

  # 지식 베이스 재구축 후 평가
  python run_pipeline.py --subscriber 한국통신 --reindex

  # 특정 CP까지만 실행
  python run_pipeline.py --subscriber 한국통신 --until cp3

Phase 1 (CP1~CP3) 구현 완료
Phase 2 (CP4),  Phase 3 (CP5~CP6) 구현 예정
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime

# ── 경로 설정 ─────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from app.utils.logger import get_logger
from app.utils.config import load_config

logger = get_logger("run_pipeline", log_dir="./data/logs")


# ── 파이프라인 단계 정의 ──────────────────────────────────────────

CHECKPOINT_ORDER = ["cp1", "cp2", "cp3", "cp4", "cp5", "cp6"]


def run_cp1(subscriber: str, config: dict, log_dir: str) -> list:
    """CP1 — 데이터 전처리: 로그 파싱 + 문서 로드"""
    from app.cp1_preprocessing.log_parser import LogParser
    from app.cp1_preprocessing.doc_loader import DocLoader

    logger.info(f"━━━ CP1 시작: {subscriber} ━━━")

    # 로그 파싱
    log_path = Path(config["log_dir"]) / subscriber
    log_path.mkdir(parents=True, exist_ok=True)

    parser = LogParser(subscriber=subscriber)
    conversations = []

    if log_path.exists() and any(log_path.iterdir()):
        conversations = parser.parse_directory(str(log_path))
    else:
        logger.warning(f"[CP1] 로그 디렉토리 비어있음: {log_path} — 샘플 데이터 사용")
        conversations = _create_sample_conversations(subscriber, parser)

    # 파싱 결과 저장
    parsed_path = Path(config["results_dir"]) / subscriber / "cp1_parsed_logs.json"
    LogParser.save_parsed(conversations, str(parsed_path))

    # 문서 로드
    doc_path = Path(config["doc_dir"]) / subscriber
    doc_path.mkdir(parents=True, exist_ok=True)

    loader = DocLoader(subscriber=subscriber)
    docs = []
    if doc_path.exists() and any(doc_path.iterdir()):
        docs = loader.load_directory(str(doc_path))
    else:
        logger.warning(f"[CP1] 문서 디렉토리 비어있음: {doc_path} — 샘플 문서 사용")
        docs = _create_sample_docs(subscriber, loader)

    # 문서 로드 결과 저장
    docs_path = Path(config["results_dir"]) / subscriber / "cp1_docs.json"
    Path(docs_path).parent.mkdir(parents=True, exist_ok=True)
    with open(docs_path, "w", encoding="utf-8") as f:
        json.dump([d.to_dict() for d in docs], f, ensure_ascii=False, indent=2)

    logger.info(f"[CP1] 완료: 대화 {len(conversations)}개, 문서 {len(docs)}개")
    return conversations, docs


def run_cp2(subscriber: str, docs: list, config: dict, force_reindex: bool = False) -> object:
    """CP2 — 지식 베이스 구축: 청킹 + 이중 임베딩"""
    from app.cp2_knowledge_base.chunker import ParentChildChunker
    from app.cp2_knowledge_base.embedder import DualEmbedder

    logger.info(f"━━━ CP2 시작: {subscriber} ━━━")

    chunker = ParentChildChunker(
        child_chunk_size=config["child_chunk_size"],
        parent_chunk_size=config["parent_chunk_size"],
    )
    chunks = chunker.chunk_all(docs)

    # 청크 통계 저장
    stats_path = Path(config["results_dir"]) / subscriber / "cp2_chunk_stats.json"
    chunk_stats = {
        "total": len(chunks),
        "parents": sum(1 for c in chunks if not c.is_child),
        "children": sum(1 for c in chunks if c.is_child),
        "by_doc_type": {
            dt: sum(1 for c in chunks if c.doc_type == dt)
            for dt in {"faq", "manual", "website"}
        },
    }
    Path(stats_path).parent.mkdir(parents=True, exist_ok=True)
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(chunk_stats, f, ensure_ascii=False, indent=2)
    logger.info(f"[CP2] 청킹: {chunk_stats}")

    # 이중 임베딩 인덱스 구축
    embedder = DualEmbedder(
        subscriber=subscriber,
        persist_dir=config["chroma_persist_dir"],
        openai_api_key=config["openai_api_key"],
        embedding_model=config["embedding_model"],
    )
    embedder.build_index(chunks, force_rebuild=force_reindex)

    stats = embedder.index_stats()
    logger.info(f"[CP2] 인덱스 통계: {stats}")
    return embedder


def run_cp3(subscriber: str, conversations: list, embedder: object, config: dict) -> list:
    """CP3 — 컨텍스트 검색: HyDE + Multi-Query + 2단계 리랭킹"""
    from app.cp3_retrieval.reranker import RetrievalPipeline

    logger.info(f"━━━ CP3 시작: {subscriber} ━━━")

    pipeline = RetrievalPipeline(
        embedder=embedder,
        anthropic_api_key=config["anthropic_api_key"],
        claude_model=config["claude_model"],
        cross_encoder_model=config["cross_encoder_model"],
        use_hyde=config["hyde_enabled"],
        use_multi_query=True,
        num_query_variants=config["num_query_variants"],
    )

    retrieval_results = []
    for conv in conversations:
        turns = conv.turns
        if not turns:
            continue

        # 각 콜봇 답변 턴에 대해 검색
        for i, turn in enumerate(turns):
            if turn.role != "bot":
                continue

            # 해당 턴 직전 고객 질의 찾기
            user_q = None
            for t in reversed(turns[:i]):
                if t.role == "user":
                    user_q = t
                    break
            if not user_q:
                continue

            context = pipeline.retrieve(
                query=user_q.text,
                conversation_history=turns[:i],
                top_k_first=config["top_k_first_stage"],
                top_k_final=config["top_k_final"],
            )

            retrieval_results.append({
                "conv_id":    conv.id,
                "turn_index": i,
                "bot_answer": turn.text,
                "user_query": user_q.text,
                "context":    context.to_dict(),
            })

    # CP3 결과 저장
    cp3_path = Path(config["results_dir"]) / subscriber / "cp3_retrieval_results.json"
    with open(cp3_path, "w", encoding="utf-8") as f:
        json.dump(retrieval_results, f, ensure_ascii=False, indent=2)

    logger.info(f"[CP3] 완료: {len(retrieval_results)}개 턴 검색")
    return retrieval_results


# ── 메인 실행기 ───────────────────────────────────────────────────

def run_subscriber(subscriber: str, config: dict, args: argparse.Namespace) -> dict:
    """단일 가입자 파이프라인 실행"""
    start_time = datetime.now()
    results = {"subscriber": subscriber, "status": "running", "checkpoints": {}}
    until = args.until or "cp6"

    try:
        # CP1
        if CHECKPOINT_ORDER.index("cp1") <= CHECKPOINT_ORDER.index(until):
            conversations, docs = run_cp1(subscriber, config, config["log_dir"])
            results["checkpoints"]["cp1"] = {
                "status": "done",
                "conversations": len(conversations),
                "docs": len(docs),
            }
        else:
            return results

        # CP2
        if CHECKPOINT_ORDER.index("cp2") <= CHECKPOINT_ORDER.index(until):
            embedder = run_cp2(subscriber, docs, config, force_reindex=args.reindex)
            results["checkpoints"]["cp2"] = {"status": "done", **embedder.index_stats()}
        else:
            return results

        # CP3
        if CHECKPOINT_ORDER.index("cp3") <= CHECKPOINT_ORDER.index(until):
            retrieval_results = run_cp3(subscriber, conversations, embedder, config)
            results["checkpoints"]["cp3"] = {
                "status": "done",
                "retrieval_count": len(retrieval_results),
            }
        else:
            return results

        # CP4~CP6 (Phase 2~3에서 구현)
        for cp in ["cp4", "cp5", "cp6"]:
            if CHECKPOINT_ORDER.index(cp) <= CHECKPOINT_ORDER.index(until):
                results["checkpoints"][cp] = {"status": "pending — Phase 2/3에서 구현 예정"}

        results["status"] = "completed"

    except Exception as e:
        logger.error(f"[Pipeline] {subscriber} 오류: {e}", exc_info=True)
        results["status"] = "error"
        results["error"] = str(e)

    elapsed = (datetime.now() - start_time).total_seconds()
    results["elapsed_sec"] = round(elapsed, 1)
    logger.info(f"[Pipeline] {subscriber} 완료: {elapsed:.1f}초")
    return results


def main():
    parser = argparse.ArgumentParser(
        description="AutoAudit — RAG 콜봇 품질 자동 검증 파이프라인",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python run_pipeline.py --subscriber 한국통신
  python run_pipeline.py --all --reindex
  python run_pipeline.py --subscriber 서울은행 --until cp3
        """,
    )
    parser.add_argument("--subscriber", "-s", type=str, help="가입자명 (단일 실행)")
    parser.add_argument("--all",        "-a", action="store_true", help="전체 가입자 실행")
    parser.add_argument("--reindex",    "-r", action="store_true", help="지식 베이스 강제 재구축")
    parser.add_argument("--until",      "-u", type=str, default="cp6",
                        choices=CHECKPOINT_ORDER, help="마지막 실행 CP (기본: cp6)")
    parser.add_argument("--env",        type=str, default=".env", help=".env 파일 경로")
    args = parser.parse_args()

    if not args.subscriber and not args.all:
        parser.error("--subscriber 또는 --all 옵션이 필요합니다.")

    # 설정 로드
    config = load_config(args.env)
    Path(config["results_dir"]).mkdir(parents=True, exist_ok=True)

    # 가입자 목록 결정
    if args.all:
        # 가입자 디렉토리에서 자동 감지
        doc_root = Path(config["doc_dir"])
        doc_root.mkdir(parents=True, exist_ok=True)
        subscribers = [d.name for d in doc_root.iterdir() if d.is_dir()]
        if not subscribers:
            # 샘플 가입자
            subscribers = ["한국통신", "서울은행", "현대보험", "온라인마트"]
            logger.info(f"[Pipeline] 샘플 가입자 사용: {subscribers}")
    else:
        subscribers = [args.subscriber]

    logger.info(f"━━━ AutoAudit 파이프라인 시작: {subscribers} ━━━")

    all_results = {}
    for sub in subscribers:
        logger.info(f"\n{'='*60}\n가입자: {sub}\n{'='*60}")
        result = run_subscriber(sub, config, args)
        all_results[sub] = result

    # 전체 결과 저장
    summary_path = Path(config["results_dir"]) / f"pipeline_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    # 결과 출력
    print("\n" + "="*60)
    print("AutoAudit 실행 결과 요약")
    print("="*60)
    for sub, result in all_results.items():
        status_icon = "✅" if result["status"] == "completed" else "❌"
        print(f"{status_icon} {sub}: {result['status']} ({result.get('elapsed_sec', '?')}초)")
        for cp, cp_result in result.get("checkpoints", {}).items():
            print(f"    {cp.upper()}: {cp_result.get('status', '?')}")
    print(f"\n결과 저장: {summary_path}")


# ── 샘플 데이터 생성기 (테스트용) ────────────────────────────────

def _create_sample_conversations(subscriber: str, parser) -> list:
    """테스트용 샘플 대화 데이터 생성"""
    sample_text = f"""콜봇: 안녕하세요, {subscriber} 고객센터입니다. 무엇을 도와드릴까요?
고객: 요금제 변경하고 싶은데요.
콜봇: 네, 요금제 변경을 도와드리겠습니다. 현재 어떤 요금제를 사용 중이신가요?
고객: LTE 기본 요금제인데 5G로 바꾸고 싶어요.
콜봇: 5G 요금제로 변경하시려면 고객센터 앱 > 요금제 변경 메뉴에서 가능합니다. 또는 저희 상담사를 통해서도 변경 가능합니다.
고객: 앱에서 하려면 어떻게 해요?
콜봇: 앱 실행 후 하단 메뉴에서 '마이페이지' 선택 > '요금제 관리' > '요금제 변경' 순서로 진행하시면 됩니다.

콜봇: 감사합니다. 불편사항 있으시면 말씀해주세요.
고객: 인터넷이 자꾸 끊겨요.
콜봇: 불편을 드려 죄송합니다. 모뎀 재부팅을 해보셨나요?
고객: 네 해봤는데도 안돼요.
콜봇: 그렇다면 기술 상담사를 통한 원격 점검을 신청해드리겠습니다. 가능한 날짜를 알려주시면 예약해드리겠습니다."""

    return parser.parse_text(sample_text, source_name="sample_conversations.txt")


def _create_sample_docs(subscriber: str, loader) -> list:
    """테스트용 샘플 문서 데이터 생성"""
    faq_text = f"""Q: {subscriber} 요금제 변경은 어떻게 하나요?
A: 고객센터 앱 > 마이페이지 > 요금제 관리 > 요금제 변경 메뉴에서 가능합니다. 변경은 즉시 적용되며 당월 요금은 일할 계산됩니다.

Q: 요금 납부는 언제 하나요?
A: 매월 25일에 자동 납부가 진행됩니다. 출금 계좌는 마이페이지 > 결제 관리에서 변경 가능합니다.

Q: 인터넷 속도가 느릴 때 어떻게 해야 하나요?
A: 1. 모뎀 전원을 껐다가 30초 후 다시 켜세요. 2. 그래도 문제가 지속되면 고객센터(1588-0000)로 연락주세요. 3. 기술 상담사가 원격 또는 방문 점검을 제공합니다."""

    manual_text = f"""# {subscriber} 서비스 이용 가이드

## 1. 요금제 변경 절차

### 1.1 앱을 통한 변경
고객센터 앱에서 요금제를 변경할 수 있습니다.

절차:
1. {subscriber} 앱 실행
2. 하단 '마이페이지' 탭 선택
3. '요금제 관리' 메뉴 진입
4. '요금제 변경' 버튼 클릭
5. 원하는 요금제 선택 후 확인

### 1.2 유의사항
- 변경 전 현재 요금제 약정 기간을 확인하세요
- 약정 기간 중 변경 시 위약금이 발생할 수 있습니다

## 2. 장애 처리 절차

### 2.1 인터넷 장애
인터넷 연결이 불안정할 때:
- 1단계: 모뎀 재부팅 (전원 OFF 30초 후 ON)
- 2단계: 케이블 연결 상태 확인
- 3단계: 고객센터 원격 점검 신청"""

    return [
        loader.load_text(faq_text, title="FAQ", doc_type="faq"),
        loader.load_text(manual_text, title="서비스 이용 가이드", doc_type="manual"),
    ]


if __name__ == "__main__":
    main()
