# AutoAudit Dev Deployment

## 목적

이 문서는 `Dockerfile + docker compose` 기반으로 AutoAudit를 개발환경에 올리고,
백엔드/프런트엔드/비동기 job/SSE/앵커 eval까지 한 번에 검증하는 절차를 정리합니다.

현재 개발 배포 구성은 아래를 전제로 합니다.

- 백엔드: `uvicorn` 단일 프로세스, `workers=1`
- 백엔드 추론 런타임: CPU 전용 PyTorch wheel
- 프런트엔드: Vite preview 서버
- 영속 데이터: 호스트 `./data` 디렉토리 바인드 마운트
- background job: 프로세스 내부 thread 기반

## 왜 단일 인스턴스인가

현재 [JobManager](/Users/kchul199/Desktop/project/ax/AutoAudit/app/ops/job_manager.py)는
프로세스 내부 thread로 job을 관리합니다.
따라서 개발환경에서는 반드시 단일 백엔드 인스턴스로 테스트하는 것이 안전합니다.

다중 인스턴스 또는 공유 개발환경으로 확장하려면 이후 `Redis/Celery/RQ/Arq` 같은
외부 job queue로 분리하는 것이 맞습니다.

## 준비물

필수:

- Docker Desktop 또는 Docker Engine + Compose Plugin
- 실 API 검증이 필요하면 아래 키 중 하나 이상
  - `OPENAI_API_KEY`
  - `ANTHROPIC_API_KEY`
  - `GOOGLE_API_KEY`

참고:

- 개발용 Docker 백엔드는 PyTorch 공식 CPU wheel 인덱스를 사용합니다.
- 목적은 `sentence-transformers` 설치 시 불필요한 CUDA 패키지 다운로드를 막아 이미지 크기와 빌드 시간을 줄이는 것입니다.

선택:

- `CONFLUENCE_*`
- `VITE_API_BASE_URL`
- `BACKEND_PORT`, `FRONTEND_PORT`

## 환경 변수 준비

가장 간단한 방법은 저장소 루트에 `.env`를 두는 것입니다.

```bash
cp AutoAudit/.env.example .env
```

그리고 아래 값을 최소한 점검하세요.

```env
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
CONFLUENCE_URL=
CONFLUENCE_EMAIL=
CONFLUENCE_TOKEN=
CHROMA_PERSIST_DIR=./data/chroma_db
LOG_DIR=./data/logs
DOC_DIR=./data/docs
RESULTS_DIR=./data/results
VITE_API_BASE_URL=http://localhost:8000
BACKEND_PORT=8000
FRONTEND_PORT=5173
```

루트 `.env`를 만들지 않고 다른 파일을 쓰고 싶다면 아래처럼 지정할 수 있습니다.

```bash
export AUTOAUDIT_ENV_FILE=AutoAudit/.env.example
```

## 기동

```bash
docker compose -f docker-compose.dev.yml up --build -d
```

기동 후 주소:

- 프런트엔드: `http://127.0.0.1:5173`
- 백엔드: `http://127.0.0.1:8000`
- 백엔드 health: `http://127.0.0.1:8000/health`

로그 확인:

```bash
docker compose -f docker-compose.dev.yml logs -f backend
docker compose -f docker-compose.dev.yml logs -f frontend
```

중지:

```bash
docker compose -f docker-compose.dev.yml down
```

이미지까지 정리:

```bash
docker compose -f docker-compose.dev.yml down --rmi local
```

## 저장 위치

컨테이너 내부 `/app/data`는 호스트 `./data`와 연결됩니다.

- `./data/docs`
- `./data/logs`
- `./data/results`
- `./data/chroma_db`
- `./data/model_cache`

즉, 검토 이력/결과 HTML/Chroma/job metadata는 컨테이너를 내려도 유지됩니다.

## Smoke Test

기동 후 아래 스크립트를 실행하면 개발환경의 핵심 경로를 한 번에 확인합니다.

```bash
./scripts/dev_smoke_test.sh
```

참고:

- 스크립트는 호스트 실행과 Docker 백엔드 실행을 모두 지원하도록 `anchor eval` 데이터셋 경로를 자동 재시도합니다.
- 첫 실행은 `sentence-transformers`, `cross-encoder`, Chroma ONNX 모델 캐시 생성 때문에 1~3분 정도 더 걸릴 수 있습니다.

검증 항목:

1. 백엔드 health
2. 프런트엔드 응답
3. 가입자 생성
4. 문서 업로드
5. 로그 업로드
6. 파이프라인 job 실행 및 완료
7. 최신 결과 조회
8. 앵커 eval job 실행 및 완료
9. 앵커 eval 리포트 조회
10. review ops 대시보드 조회

환경 변수로 URL을 바꿀 수 있습니다.

```bash
API_BASE=http://10.0.0.5:8000 \
FRONTEND_BASE=http://10.0.0.5:5173 \
./scripts/dev_smoke_test.sh
```

## 기대 동작

- API 키가 없으면 CP4는 `DEGRADED` 중심으로 동작할 수 있습니다.
- 그래도 파이프라인, background job, SSE, 결과 저장, review queue 흐름 자체는 검증 가능합니다.
- 실 정확도 테스트는 반드시 실제 API 키를 넣은 상태에서 해야 합니다.

## 개발환경 체크리스트

- `docker compose ps`에서 두 컨테이너가 healthy인지
- UI 접속이 되는지
- `scripts/dev_smoke_test.sh`가 끝까지 통과하는지
- `./data/results/<subscriber>/cp6_report.html`이 생성되는지
- `./data/results/<subscriber>/anchor_eval_report.json`이 생성되는지
- review queue와 대시보드가 비어 있지 않은지

## 운영 전 주의

- 현재 CORS는 전체 허용입니다. 공유 dev 환경이면 reverse proxy 또는 auth 추가가 필요합니다.
- 현재 background job은 단일 인스턴스 전제입니다.
- SSE를 프록시 뒤에 둘 경우 buffering 설정을 꺼야 합니다.
