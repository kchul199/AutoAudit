# AutoAudit — RAG 기반 콜봇 품질 자동 검증 시스템

> **SaaS 콜봇 서비스의 답변 품질을 GT(Ground Truth) 없이 완전 자동화로 검증하는 로컬 실행형 AI 파이프라인**

---

## 📋 프로젝트 개요

RAG(Retrieval-Augmented Generation) 기반 SaaS 콜봇을 운영하면서 겪는 3가지 핵심 문제를 해결합니다.

| 문제 | 해결 방법 |
|------|-----------|
| 도메인 지식 부재로 품질 평가 곤란 | 가입자별 도메인 문서(매뉴얼·FAQ·웹사이트)를 GT 대체재로 활용 |
| Ground Truth 데이터 없음 | RAG 검색 결과를 기준으로 LLM-as-a-Judge 평가 |
| 가입자 증가 시 리소스 선형 증가 | 완전 자동화 파이프라인 + 비동기 병렬 Multi-LLM 평가 |

---

## 🏗️ 파이프라인 구조 (CP1 ~ CP6)

```
[콜봇 대화 로그] ──▶ CP1: 데이터 전처리
                           │
[도메인 문서]    ──▶ CP2: 지식 베이스 구축 (Parent-Child 인덱싱 + 이중 임베딩)
                           │
                      CP3: 컨텍스트 검색 (HyDE + Multi-Query + 2단계 리랭킹)
                           │
                      CP4: Multi-LLM 합의 평가 (Claude + GPT-4o + Gemini)
                           │
                      CP5: 결과 집계 & 이상 감지
                           │
                      CP6: Confluence 보고서 자동 발행
```

### 핵심 기술 스택

- **벡터 DB**: ChromaDB (Dense 임베딩 — `text-embedding-3-large`)
- **희소 검색**: BM25 (`rank_bm25`)
- **리랭킹**: Cross-Encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`)
- **평가 LLM**: Claude Opus 4 · GPT-4o · Gemini 1.5 Pro (비동기 병렬 호출)
- **보고서**: 로컬 HTML + Confluence REST API (`atlassian-python-api`)
- **운영 UI**: React 18 + Vite 프런트엔드 (`frontend/`)
- **레거시 시안**: 단일 JSX 목업 (`callbot_quality_ui.jsx`)

## 📍 현재 저장소 상태

- **실제 구현 범위**: `AutoAudit/` 아래 CP1~CP6 CLI 파이프라인 + FastAPI 서버 + `frontend/` Vite 앱
- **보고서 출력**: 기본은 로컬 HTML 보고서 저장, Confluence 연동 정보가 있으면 베스트에포트 발행
- **UI 파일 상태**: `callbot_quality_ui.jsx`는 초기 시안이고, 실제 실행 가능한 화면은 `frontend/` 아래에 있습니다.

---

## 📁 문서 목록

| 파일 | 설명 |
|------|------|
| `RAG콜봇_품질자동화_기획안.docx` | 프로젝트 기획서 (8개 섹션, CP1~CP6 상세 기획) |
| `RAG콜봇_품질자동화_기획발표.pptx` | 부서장 보고용 PPT (11슬라이드) |
| `RAG콜봇_파이프라인_구현설계서.docx` | 구현 설계서 (7개 챕터, CP별 모듈 + UI 화면 설계) |
| `callbot_quality_ui.jsx` | 관리 UI 단일 파일 목업 (10개 화면 시안) |
| `README.md` | 본 문서 |

---

## 🖥️ UI 화면 구성 (10개 화면)

```
개요
 ├─ 대시보드           — 전체 가입자 품질 현황 요약
 └─ 가입자 관리         — 가입자 CRUD

데이터 관리
 ├─ 지식 베이스 등록    — 도메인 문서 업로드 & 임베딩 (CP2 연동)
 ├─ 콜봇 이력 등록      — 대화 로그 업로드 & 파싱 (CP1 연동)
 └─ 임베딩 검증         — 청크 품질 확인 & 검색 테스트 (CP2~CP3 연동)

평가
 ├─ 콜봇 시뮬레이터     — 실시간 대화 테스트 & 즉시 평가
 ├─ 평가 실행           — CP 단계별 파이프라인 실행 제어
 └─ 평가 결과           — 대화별 점수, 불확실 케이스 분석

설정
 ├─ 모니터링 & 알림     — 품질 하락 감지 알림 & 임계값 설정
 └─ AI API 키 설정      — LLM API 키 & Confluence 연동 설정
```

---

## 🚀 빠른 시작

### 1. 환경 설정

아래 명령은 저장소 루트 기준입니다. 같은 인터프리터로 설치와 실행을 맞추기 위해 `python3 -m pip` 사용을 권장합니다.

```bash
# 의존성 설치
python3 -m pip install -r AutoAudit/requirements.txt

# API 키 설정 (.env 파일)
cp AutoAudit/.env.example .env
# .env 파일에 API 키 입력
```

### 2. 지식 베이스 구축

```bash
# 특정 가입자 문서 인덱싱
python3 AutoAudit/run_pipeline.py --subscriber 한국통신 --reindex

# 전체 가입자 인덱싱
python3 AutoAudit/run_pipeline.py --all --reindex
```

입력 파일은 아래 경로에 준비해야 합니다.

```text
data/logs/<가입자명>/   # .txt .json .csv .log
data/docs/<가입자명>/   # .pdf .txt .html .htm .docx .doc .md
```

### 3. 품질 평가 실행

```bash
# 특정 가입자 평가 (CP1~CP6 전체)
python3 AutoAudit/run_pipeline.py --subscriber 한국통신

# 전체 가입자 평가
python3 AutoAudit/run_pipeline.py --all
```

### 4. 샘플 데이터 smoke test

```bash
# 입력 파일 없이 CP1만 빠르게 검증
python3 AutoAudit/run_pipeline.py --subscriber 데모사 --until cp1 --allow-sample-data
```

### 5. API 서버 실행

```bash
python3 -m uvicorn app.server:app --app-dir AutoAudit --reload
```

기본 주소는 `http://127.0.0.1:8000`이며, 정적 결과물은 `/artifacts/...`, API는 `/api/...`에서 제공합니다.

### 6. 프런트엔드 실행

```bash
cd frontend
npm install
npm run dev
```

필요하면 `frontend/.env`에 아래 값을 둘 수 있습니다.

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

### 7. UI 참고

- `frontend/`는 실제 API 호출이 연결된 운영용 스캐폴드입니다.
- `callbot_quality_ui.jsx`는 디자인/기획 참고용 목업 파일로 유지합니다.

---

## ⚙️ 환경 변수 (.env)

```env
# Multi-LLM API Keys
ANTHROPIC_API_KEY=sk-ant-api03-...
OPENAI_API_KEY=sk-proj-...
GOOGLE_API_KEY=AIzaSy...

# Model Configuration
CLAUDE_MODEL=claude-opus-4-6
OPENAI_MODEL=gpt-4o
GEMINI_MODEL=gemini-1.5-pro
EMBEDDING_MODEL=text-embedding-3-large
LOCAL_EMBEDDING_MODEL=all-MiniLM-L6-v2

# Confluence
CONFLUENCE_URL=https://your-domain.atlassian.net
CONFLUENCE_EMAIL=user@company.com
CONFLUENCE_TOKEN=...
CONFLUENCE_SPACE_KEY=CALLBOT
CONFLUENCE_PARENT_PAGE_ID=123456789

# Pipeline
CHROMA_PERSIST_DIR=./data/chroma_db
LOG_DIR=./data/logs
DOC_DIR=./data/docs
RESULTS_DIR=./data/results
LOG_LEVEL=INFO
UNCERTAINTY_THRESHOLD=1.5
```

---

## 📊 평가 기준

| 항목 | 기준 | 설명 |
|------|------|------|
| 정확성 | 0 ~ 5점 | 도메인 문서 기반 RAG 검색 결과와의 일치 여부 |
| 자연스러움 | 0 ~ 5점 | 대화 흐름의 일관성 및 자연스러움 |
| 합의 점수 | 가중 평균 | Claude(40%) + GPT-4o(35%) + Gemini(25%) |
| 불확실 플래그 | 표준편차 > 1.5 | 3개 모델 간 점수 편차가 클 경우 수동 검토 권고 |

---

## 📅 구현 로드맵

| Phase | 기간 | 내용 |
|-------|------|------|
| Phase 1 | 1~2주차 | 데이터 파이프라인 (CP1~CP3) |
| Phase 2 | 3~4주차 | Multi-LLM 평가 엔진 (CP4) |
| Phase 3 | 5주차 | 집계 & 보고서 (CP5~CP6) |
| Phase 4 | 6주차 | FastAPI + 운영 UI + 파일럿 검증 |

---

## 📌 주요 설계 결정

- **GT-Free 평가**: Ground Truth 없이 가입자 도메인 문서를 RAG 검색해 LLM Judge 프롬프트에 주입
- **로컬 실행**: 콜봇 시스템과의 직접 API 연계 없이 파일 기반 I/O로만 동작
- **정확도 우선**: 비용보다 정확도를 우선하여 최상위 모델(Claude Opus 4, GPT-4o, Gemini 1.5 Pro) 사용
- **비동기 병렬**: `asyncio.gather()`로 3개 LLM 동시 호출 → 평가 시간 1/3 단축
- **Tenacity 재시도**: 지수 백오프로 API 오류 자동 복구

---

*문서 버전: v1.0 | 작성일: 2026-04-05 | 작성 부서: 품질관리팀*
