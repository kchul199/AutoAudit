# AutoAudit

RAG 기반 콜봇 답변 품질 자동 평가 플랫폼입니다.  
가입자별 문서와 콜 로그를 입력받아 `CP1 ~ CP6` 파이프라인으로 전처리, 검색, Multi-LLM 합의 평가, 집계, 보고서 발행까지 수행합니다.

이 README는 초보자가 저장소를 처음 받아도 **설치 → 환경 설정 → 실행 → 확인 → 문제 해결**까지 바로 따라갈 수 있도록 작성했습니다.

## 1. 프로젝트 개요

AutoAudit는 다음 문제를 해결하기 위한 프로젝트입니다.

- Ground Truth 정답셋이 없어도 콜봇 답변 품질을 자동으로 점검하고 싶다.
- 가입자마다 FAQ, 매뉴얼, 웹 문서가 다르기 때문에 가입자별 도메인 기준으로 평가해야 한다.
- 사람이 모든 콜을 직접 읽지 않고도, `검토가 꼭 필요한 케이스만` 추려 보고 싶다.

핵심 아이디어는 다음과 같습니다.

1. 가입자별 문서를 지식베이스로 만든다.
2. 고객 질문과 콜봇 답변에 대해 관련 근거 문서를 검색한다.
3. `Claude + GPT + Gemini` 3개 Judge가 같은 schema로 동시에 평가한다.
4. `TRUSTED / UNCERTAIN / DEGRADED / INCOMPLETE` 상태로 결과를 분리한다.
5. 사람이 전부 보는 것이 아니라, 검토 큐만 확인하도록 만든다.

## 2. 이 프로젝트가 하는 일

파이프라인은 아래 순서로 동작합니다.

```text
콜 로그/문서 입력
  -> CP1 데이터 전처리
  -> CP2 지식베이스 구축
  -> CP3 컨텍스트 검색
  -> CP4 Multi-LLM 합의 평가
  -> CP5 결과 집계 / 검토 큐 생성
  -> CP6 HTML / Confluence 보고서 생성
```

각 단계의 역할:

- `CP1`: 로그 파싱, 문서 로딩
- `CP2`: Parent-Child 청킹, Dense + BM25 인덱싱
- `CP3`: 대화 인식 쿼리 재작성, HyDE, Multi-Query, 2단계 리랭킹
- `CP4`: OpenAI / Anthropic / Gemini 3중 Judge 평가
- `CP5`: KPI 집계, review queue 생성
- `CP6`: 로컬 HTML 보고서 및 Confluence 발행

## 3. 현재 구현 상태

현재 저장소에는 아래가 실제로 구현되어 있습니다.

- `AutoAudit/` 아래 CP1~CP6 CLI 파이프라인
- `FastAPI` 백엔드
- `frontend/` Vite + React 운영 UI
- 비동기 job 실행 / SSE 이벤트 스트림
- review queue, 재평가, 담당자 지정, 앵커 eval
- Docker 개발 배포 스택

문서/산출물:

- `RAG콜봇_품질자동화_기획안.docx`
- `RAG콜봇_파이프라인_구현설계서.docx`
- `RAG콜봇_품질자동화_기획발표.pptx`
- `docs/trustworthy-human-minimal-eval-design.md`
- `docs/dev-deployment.md`

## 4. 기술 스택

- Backend: `FastAPI`, `uvicorn`
- Frontend: `React 18`, `Vite`
- Vector DB: `ChromaDB`
- Sparse retrieval: `rank_bm25`
- Reranking: `cross-encoder/ms-marco-MiniLM-L-6-v2`
- OpenAI live judge: `openai` 2.x `Responses API`
- Anthropic live judge: forced tool schema
- Gemini live judge: `google-genai` JSON schema
- Report: 로컬 HTML, Confluence REST API

## 5. 추천 실행 경로

처음 실행하는 분이라면 아래 순서를 추천합니다.

1. 가장 쉬운 방법: **Docker 개발환경으로 먼저 실행**
2. 그다음 필요하면: **로컬 Python/Node 방식으로 실행**

이유:

- Docker 방식은 의존성 충돌이 적습니다.
- 로컬 방식은 디버깅과 코드 수정에는 편하지만, Python/Node 환경 차이를 직접 맞춰야 합니다.

---

## 6. 빠른 시작 A: Docker로 바로 실행하기

초보자에게 가장 추천하는 방법입니다.

### 6-1. 준비물

- Docker Desktop 또는 Docker Engine + Compose Plugin

선택:

- 실제 live Multi-LLM 평가까지 보려면 아래 키가 필요합니다.
  - `OPENAI_API_KEY`
  - `ANTHROPIC_API_KEY`
  - `GOOGLE_API_KEY`

### 6-2. 환경 파일 만들기

저장소 루트에서 실행합니다.

```bash
cp AutoAudit/.env.example .env
```

중요:

- `.env` 안의 예시 키 문자열(`xxxxxxxx...`)은 실제 키가 아닙니다.
- 실 API 키가 없다면 **값을 비워 두는 것**이 좋습니다.
- placeholder 문자열을 그대로 두어도 코드가 자동 무시하지만, 초보자 입장에서는 빈 값이 더 헷갈리지 않습니다.

최소 권장 형태:

```env
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=

CHROMA_PERSIST_DIR=./data/chroma_db
LOG_DIR=./data/logs
DOC_DIR=./data/docs
RESULTS_DIR=./data/results

BACKEND_PORT=8000
FRONTEND_PORT=5173
VITE_API_BASE_URL=http://localhost:8000
```

### 6-3. 컨테이너 실행

```bash
docker compose -f docker-compose.dev.yml up --build -d
```

실행 후 접속 주소:

- Frontend: `http://127.0.0.1:5173`
- Backend API: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/health`

### 6-4. smoke test 실행

개발 스택이 정상인지 한 번에 확인합니다.

```bash
./scripts/dev_smoke_test.sh
```

이 스크립트가 확인하는 것:

1. 백엔드 health
2. 프런트엔드 응답
3. 가입자 생성
4. 문서 업로드
5. 로그 업로드
6. 파이프라인 job 실행
7. 최신 결과 조회
8. 앵커 eval job 실행
9. review ops 조회

### 6-5. Docker 실행 종료

```bash
docker compose -f docker-compose.dev.yml down
```

추가 문서:

- [docs/dev-deployment.md](docs/dev-deployment.md)

---

## 7. 빠른 시작 B: 로컬 Python/Node로 실행하기

코드 수정이나 디버깅이 필요하면 이 방법을 사용하세요.

### 7-1. 준비물

- Python `3.11` 이상 권장
- Node.js `18` 이상 권장
- npm

버전 확인:

```bash
python3 --version
node --version
npm --version
```

### 7-2. Python 의존성 설치

```bash
python3 -m pip install -r AutoAudit/requirements.txt
```

### 7-3. 프런트엔드 의존성 설치

```bash
cd frontend
npm install
cd ..
```

### 7-4. 환경 파일 만들기

```bash
cp AutoAudit/.env.example .env
```

프런트엔드 API 주소가 기본값과 다르면 `frontend/.env`도 만들 수 있습니다.

```bash
cp frontend/.env.example frontend/.env
```

예시:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

### 7-5. 가장 먼저 해볼 smoke test

실제 입력 파일 없이 빠르게 CP1만 확인:

```bash
python3 AutoAudit/run_pipeline.py --subscriber 데모사 --until cp1 --allow-sample-data --env .env
```

CP4까지 확인:

```bash
python3 AutoAudit/run_pipeline.py --subscriber 데모사 --until cp4 --allow-sample-data --env .env
```

설명:

- API 키가 없으면 CP4는 `DEGRADED`로 동작할 수 있습니다.
- 이것은 비정상이 아니라, **fallback 경로가 정상적으로 동작한 것**입니다.
- 품질 정확도를 보려면 실제 API 키가 필요합니다.

### 7-6. 백엔드 실행

```bash
python3 -m uvicorn app.server:app --app-dir AutoAudit --reload
```

### 7-7. 프런트엔드 실행

새 터미널에서:

```bash
cd frontend
npm run dev
```

이제 브라우저에서 접속:

- `http://127.0.0.1:5173`

---

## 8. 처음 실행할 때 가장 쉬운 검증 순서

처음부터 실제 고객 데이터를 넣기보다 아래 순서를 추천합니다.

### Step 1. health 확인

```bash
curl http://127.0.0.1:8000/health
```

기대 결과:

- `"status": "ok"`

### Step 2. live readiness 확인

```bash
curl http://127.0.0.1:8000/api/live-consensus/readiness
```

여기서 확인할 수 있는 것:

- OpenAI / Anthropic / Gemini 각 provider별 key 존재 여부
- SDK 설치 여부
- 현재 상태가 `ready_to_probe`, `missing_key`, `sdk_missing` 중 무엇인지

실제 live probe:

```bash
curl -X POST http://127.0.0.1:8000/api/live-consensus/probe
```

주의:

- 이 probe는 실제 provider live 경로를 한 번 실행합니다.
- 유효한 API 키가 있어야 `live_ok`를 기대할 수 있습니다.

### Step 3. UI에서 가입자 생성

브라우저에서:

1. `대시보드` 또는 `데이터 관리`
2. 가입자 생성
3. 문서 업로드
4. 로그 업로드

### Step 4. 파이프라인 실행

UI에서:

1. `파이프라인`
2. 마지막 단계 `cp6`
3. 실행 버튼 클릭

또는 CLI:

```bash
python3 AutoAudit/run_pipeline.py --subscriber 한국통신 --env .env
```

### Step 5. 결과 확인

생성 결과:

- `data/results/<가입자명>/cp5_summary.json`
- `data/results/<가입자명>/cp6_report.html`
- `data/results/<가입자명>/cp4_evaluation_results.json`

브라우저에서도 `결과 보기` 페이지에서 확인할 수 있습니다.

---

## 9. 입력 데이터 준비 방법

### 9-1. 디렉터리 구조

입력 파일은 아래처럼 둡니다.

```text
data/
  docs/
    한국통신/
      faq.txt
      manual.docx
      website.html
  logs/
    한국통신/
      calls.txt
      calls.json
      calls.csv
```

지원 형식:

- 문서: `.pdf`, `.txt`, `.html`, `.htm`, `.docx`, `.doc`, `.md`
- 로그: `.txt`, `.json`, `.csv`, `.log`

### 9-2. 문서 예시

FAQ 문서 예시:

```text
Q: 요금제 변경은 어떻게 하나요?
A: 앱 > 마이페이지 > 요금제 관리 > 요금제 변경 메뉴에서 가능합니다.
```

### 9-3. 로그 예시

TXT 로그 예시:

```text
고객: 요금제 변경하고 싶은데요.
콜봇: 앱의 마이페이지에서 요금제 변경 메뉴를 선택하시면 됩니다.
```

---

## 10. 주요 실행 명령 모음

### 10-1. 파이프라인 실행

특정 가입자 전체 실행:

```bash
python3 AutoAudit/run_pipeline.py --subscriber 한국통신 --env .env
```

특정 단계까지만 실행:

```bash
python3 AutoAudit/run_pipeline.py --subscriber 한국통신 --until cp3 --env .env
```

지식베이스 재구축:

```bash
python3 AutoAudit/run_pipeline.py --subscriber 한국통신 --reindex --env .env
```

모든 가입자 실행:

```bash
python3 AutoAudit/run_pipeline.py --all --env .env
```

샘플 데이터 허용:

```bash
python3 AutoAudit/run_pipeline.py --subscriber 데모사 --until cp6 --allow-sample-data --env .env
```

### 10-2. 앵커 Eval 실행

```bash
python3 AutoAudit/run_anchor_eval.py \
  --subscriber 한국통신 \
  --dataset AutoAudit/examples/anchor_eval.sample.jsonl \
  --env .env
```

결과 파일:

- `data/results/<가입자명>/anchor_eval_report.json`

### 10-3. 백엔드 API

파이프라인 job 생성:

```bash
curl -X POST http://127.0.0.1:8000/api/pipeline/jobs \
  -H "Content-Type: application/json" \
  -d '{"subscriber":"한국통신","until":"cp6","reindex":false,"allow_sample_data":false}'
```

job 상태 조회:

```bash
curl http://127.0.0.1:8000/api/pipeline/jobs/<job_id>
```

---

## 11. 소스 구조

저장소의 핵심 구조는 아래와 같습니다.

```text
.
├── AutoAudit/
│   ├── app/
│   │   ├── cp1_preprocessing/
│   │   ├── cp2_knowledge_base/
│   │   ├── cp3_retrieval/
│   │   ├── cp4_evaluator/
│   │   ├── cp5_aggregator/
│   │   ├── cp6_reporter/
│   │   ├── eval_ops/
│   │   ├── ops/
│   │   ├── utils/
│   │   └── server.py
│   ├── examples/
│   ├── tests/
│   ├── run_pipeline.py
│   ├── run_anchor_eval.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── docs/
├── scripts/
├── docker-compose.dev.yml
├── Dockerfile.backend
├── Dockerfile.frontend
└── README.md
```

### 11-1. 백엔드 상세 구조

| 경로 | 설명 |
|------|------|
| `AutoAudit/run_pipeline.py` | CP1~CP6 실행 메인 CLI |
| `AutoAudit/run_anchor_eval.py` | 앵커 eval 실행 CLI |
| `AutoAudit/app/server.py` | FastAPI 서버 |
| `AutoAudit/app/utils/config.py` | `.env` 로딩 및 설정 정규화 |
| `AutoAudit/app/ops/job_manager.py` | background job 관리 |
| `AutoAudit/app/eval_ops/anchor_eval.py` | 앵커 eval 로직 |

### 11-2. CP별 모듈 설명

| 경로 | 역할 |
|------|------|
| `cp1_preprocessing/log_parser.py` | 로그 파싱 |
| `cp1_preprocessing/doc_loader.py` | 문서 로딩 |
| `cp2_knowledge_base/chunker.py` | Parent-Child 청킹 |
| `cp2_knowledge_base/embedder.py` | Dense/BM25 인덱싱 |
| `cp3_retrieval/query_builder.py` | 대화 인식 쿼리 재작성 |
| `cp3_retrieval/hyde_retriever.py` | HyDE / Multi-Query |
| `cp3_retrieval/reranker.py` | 2단계 검색 및 리랭킹 |
| `cp4_evaluator/judges.py` | 각 LLM Judge 구현 |
| `cp4_evaluator/consensus.py` | 3중 합의 / 상태 결정 |
| `cp4_evaluator/preflight.py` | live readiness / probe |
| `cp5_aggregator/stats.py` | KPI 집계 / review queue |
| `cp6_reporter/confluence.py` | HTML / Confluence 보고서 생성 |

### 11-3. 프런트엔드 구조

| 경로 | 설명 |
|------|------|
| `frontend/src/App.jsx` | 메인 UI |
| `frontend/src/api.js` | 백엔드 API 호출 |
| `frontend/src/styles.css` | UI 스타일 |

### 11-4. 테스트 구조

| 경로 | 설명 |
|------|------|
| `AutoAudit/tests/test_phase1.py` | CP1 중심 테스트 |
| `AutoAudit/tests/test_phase1_unittest.py` | CP1 보조 테스트 |
| `AutoAudit/tests/test_runtime_safety.py` | 런타임 안전장치 테스트 |
| `AutoAudit/tests/test_app_scaffold.py` | CP4~CP6 / API / readiness / UI 스캐폴드 회귀 |

---

## 12. 실행 후 생성되는 산출물

`data/results/<가입자명>/` 아래에 주요 결과가 저장됩니다.

| 파일 | 설명 |
|------|------|
| `cp1_parsed_logs.json` | 파싱된 대화 |
| `cp1_docs.json` | 로드된 문서 |
| `cp2_chunk_stats.json` | 청킹 통계 |
| `cp3_retrieval_results.json` | 검색 결과 |
| `cp4_evaluation_results.json` | 턴별 3중 합의 평가 결과 |
| `cp5_summary.json` | 집계 결과와 review queue |
| `cp6_report.html` | 로컬 HTML 보고서 |
| `cp6_publish_result.json` | 보고서 발행 결과 |
| `anchor_eval_report.json` | 앵커 eval 결과 |

job 관련 메타데이터:

- `data/results/_jobs/*.json`

---

## 13. Live Multi-LLM 합의 엔진 설명

현재 live judge는 아래 방식으로 구현돼 있습니다.

- OpenAI: `responses.parse` + Pydantic schema
- Anthropic: forced tool schema
- Gemini: `google-genai` JSON schema

운영 점수 규칙:

- `TRUSTED`: 3개 Judge 모두 live 성공
- `UNCERTAIN`: 3개 live 성공이지만 편차/grounding risk 큼
- `DEGRADED`: 일부 Judge가 fallback으로 대체됨
- `INCOMPLETE`: 입력이나 평가 상태가 불완전

중요:

- `TRUSTED` 점수만 운영 평균에 반영됩니다.
- fallback 결과는 참고용입니다.

---

## 14. 초보자를 위한 권장 확인 순서

아래 순서대로 확인하면 가장 덜 헷갈립니다.

1. `docker compose` 또는 로컬 서버를 띄운다.
2. `/health`가 `ok`인지 본다.
3. `/api/live-consensus/readiness`를 본다.
4. 샘플 데이터로 `--allow-sample-data` 실행을 해본다.
5. UI 접속 후 가입자 생성 / 문서 / 로그 업로드를 해본다.
6. `cp6`까지 실행한다.
7. `cp6_report.html` 생성 여부를 확인한다.
8. 실제 API 키가 있다면 `POST /api/live-consensus/probe`를 실행한다.

---

## 15. 트러블슈팅

### 15-1. `--subscriber 또는 --all 옵션이 필요합니다`

원인:

- `run_pipeline.py` 실행 시 가입자 지정이 빠졌습니다.

해결:

```bash
python3 AutoAudit/run_pipeline.py --subscriber 데모사 --allow-sample-data --env .env
```

### 15-2. `로그 파일이 없습니다` 또는 `문서 파일이 없습니다`

원인:

- `data/logs/<가입자명>/`, `data/docs/<가입자명>/` 아래 입력 파일이 없습니다.

해결:

- 실제 파일을 넣거나
- 테스트 목적이면 `--allow-sample-data`를 추가하세요.

### 15-3. CP4 결과가 계속 `DEGRADED`로 나옵니다

원인:

- API 키가 없거나
- 예시 placeholder 키가 들어 있거나
- provider SDK / 네트워크 문제가 있습니다.

확인:

```bash
curl http://127.0.0.1:8000/api/live-consensus/readiness
curl -X POST http://127.0.0.1:8000/api/live-consensus/probe
```

해결:

- `.env`에 실제 키 입력
- placeholder 문자열 제거
- 패키지 재설치 후 다시 실행

### 15-4. `TRUSTED`가 하나도 안 나옵니다

가능한 원인:

- 세 provider 중 하나라도 live 실패
- readiness는 ok인데 probe 시 fallback 발생
- 문서 검색 품질이 낮아 grounding risk가 큼

권장 확인:

1. readiness / probe 결과 확인
2. `cp4_evaluation_results.json`에서 `error_reason`, `source`, `state_reason` 확인
3. `review queue`에서 top chunks와 judge breakdown 확인

### 15-5. 첫 실행이 매우 느립니다

정상일 수 있습니다.

이유:

- `sentence-transformers`
- `cross-encoder`
- Chroma/ONNX 캐시

첫 실행에서 모델 다운로드가 일어날 수 있습니다.  
두 번째 실행부터는 빨라집니다.

### 15-6. `npm run dev` 또는 `npm run build`가 실패합니다

해결 순서:

```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
npm run build
```

### 15-7. `uvicorn` 실행은 되는데 UI가 API에 연결되지 않습니다

확인:

- 백엔드: `http://127.0.0.1:8000/health`
- 프런트 `.env`: `VITE_API_BASE_URL`

예시:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

### 15-8. Docker는 올라오는데 smoke test가 실패합니다

가능한 원인:

- backend/frontend가 아직 완전히 ready 되기 전 실행
- 포트 충돌
- `AUTOAUDIT_ENV_FILE` 경로 문제

확인:

```bash
docker compose -f docker-compose.dev.yml ps
docker compose -f docker-compose.dev.yml logs -f backend
docker compose -f docker-compose.dev.yml logs -f frontend
```

### 15-9. Confluence 발행이 되지 않습니다

원인:

- `CONFLUENCE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_TOKEN` 등이 비어 있거나 잘못됨

참고:

- Confluence 발행이 실패해도 로컬 HTML 보고서는 생성될 수 있습니다.

### 15-10. macOS에서 권한 문제로 smoke script가 실행되지 않습니다

```bash
chmod +x scripts/dev_smoke_test.sh
./scripts/dev_smoke_test.sh
```

---

## 16. 검증 명령 모음

자주 쓰는 검증 명령:

```bash
python3 -m pytest AutoAudit/tests/test_runtime_safety.py -q
python3 -m pytest AutoAudit/tests/test_app_scaffold.py -q
python3 -m pytest AutoAudit/tests/test_phase1.py -q
python3 -m unittest AutoAudit/tests/test_phase1_unittest.py -q
cd frontend && npm run build
```

---

## 17. 관련 문서

- [docs/dev-deployment.md](docs/dev-deployment.md)
- [docs/trustworthy-human-minimal-eval-design.md](docs/trustworthy-human-minimal-eval-design.md)

---

## 18. 한 줄 요약

가장 쉬운 시작 방법은 아래 4줄입니다.

```bash
cp AutoAudit/.env.example .env
docker compose -f docker-compose.dev.yml up --build -d
./scripts/dev_smoke_test.sh
```

그다음 브라우저에서 `http://127.0.0.1:5173`를 열면 됩니다.

실제 품질 정확도까지 보려면, 마지막으로 `.env`에 **실제 OpenAI / Anthropic / Gemini 키를 넣고** `Live probe`를 실행하세요.
