#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8000}"
FRONTEND_BASE="${FRONTEND_BASE:-http://127.0.0.1:5173}"
POLL_RETRIES="${POLL_RETRIES:-90}"
POLL_INTERVAL_SEC="${POLL_INTERVAL_SEC:-2}"
SUBSCRIBER="${SUBSCRIBER:-SmokeDev$(date +%Y%m%d%H%M%S)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCAL_ANCHOR_DATASET="${REPO_ROOT}/AutoAudit/examples/anchor_eval.sample.jsonl"
CONTAINER_ANCHOR_DATASET="/app/AutoAudit/examples/anchor_eval.sample.jsonl"

if [[ -z "${ANCHOR_DATASET_PATH:-}" ]]; then
  ANCHOR_DATASET_PATH="${LOCAL_ANCHOR_DATASET}"
fi

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

json_get() {
  local json_text="$1"
  local json_path="$2"
  JSON_TEXT="$json_text" JSON_PATH="$json_path" python3 - <<'PY'
import json
import os

data = json.loads(os.environ["JSON_TEXT"])
value = data
for part in os.environ["JSON_PATH"].split("."):
    if part.isdigit():
        value = value[int(part)]
    else:
        value = value[part]
if value is None:
    print("")
else:
    print(value)
PY
}

wait_for_url() {
  local url="$1"
  local label="$2"
  local attempt
  for attempt in $(seq 1 "$POLL_RETRIES"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[smoke] ${label} ready: ${url}"
      return 0
    fi
    sleep "$POLL_INTERVAL_SEC"
  done
  echo "[smoke] ${label} timeout: ${url}" >&2
  return 1
}

poll_job() {
  local endpoint="$1"
  local label="$2"
  local body
  local status
  local attempt

  for attempt in $(seq 1 "$POLL_RETRIES"); do
    body="$(curl -fsS "${API_BASE}${endpoint}")"
    status="$(json_get "$body" "status")"
    echo "[smoke] ${label} status=${status} attempt=${attempt}"
    case "$status" in
      completed)
        printf '%s' "$body"
        return 0
        ;;
      failed|error)
        echo "[smoke] ${label} failed: $body" >&2
        return 1
        ;;
    esac
    sleep "$POLL_INTERVAL_SEC"
  done

  echo "[smoke] ${label} timeout" >&2
  return 1
}

run_anchor_eval_job() {
  local dataset_path="$1"
  local label="$2"
  local job_json
  local job_id
  local job_body
  local job_status

  echo "[smoke] starting anchor eval job (${label} path)"
  job_json="$(
    curl -fsS \
      -X POST "${API_BASE}/api/evals/anchor/jobs" \
      -H "Content-Type: application/json" \
      -d "{\"subscriber\":\"${SUBSCRIBER}\",\"dataset_path\":\"${dataset_path}\"}"
  )"
  job_id="$(json_get "$job_json" "id")"
  job_body="$(curl -fsS "${API_BASE}/api/evals/anchor/jobs/${job_id}")"
  job_status="$(json_get "$job_body" "status")"

  if [[ "$job_status" == "failed" || "$job_status" == "error" ]]; then
    printf '%s' "$job_body"
    return 1
  fi

  poll_job "/api/evals/anchor/jobs/${job_id}" "anchor-eval" >/dev/null
}

echo "[smoke] waiting for backend and frontend"
wait_for_url "${API_BASE}/health" "backend"
wait_for_url "${FRONTEND_BASE}" "frontend"

cat > "${TMP_DIR}/faq.txt" <<'EOF'
FAQ
- 요금제 변경은 앱 > 마이페이지 > 요금제 변경 메뉴에서 가능합니다.
- 앱에서 처리할 수 없는 경우 고객센터로 연결할 수 있습니다.
EOF

cat > "${TMP_DIR}/manual.txt" <<'EOF'
장애 대응 매뉴얼
1. 인터넷이 자꾸 끊기면 먼저 모뎀 전원을 끄고 30초 후 다시 켭니다.
2. 문제가 계속되면 원격 점검을 신청합니다.
EOF

cat > "${TMP_DIR}/log.txt" <<'EOF'
고객: 요금제 변경하고 싶은데요.
콜봇: 앱의 마이페이지에서 요금제 변경 메뉴를 선택하시면 됩니다.

고객: 인터넷이 자꾸 끊겨요.
콜봇: 모뎀 전원을 껐다가 30초 후 다시 켜시고, 지속되면 원격 점검을 신청해 주세요.
EOF

echo "[smoke] creating subscriber ${SUBSCRIBER}"
curl -fsS \
  -X POST "${API_BASE}/api/subscribers" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${SUBSCRIBER}\",\"industry\":\"smoke\",\"contact\":\"smoke@example.com\",\"desc\":\"dev smoke test\"}" \
  >/dev/null

echo "[smoke] uploading documents"
curl -fsS \
  -X POST "${API_BASE}/api/subscribers/${SUBSCRIBER}/documents/upload" \
  -F "files=@${TMP_DIR}/faq.txt" \
  -F "files=@${TMP_DIR}/manual.txt" \
  >/dev/null

echo "[smoke] uploading logs"
curl -fsS \
  -X POST "${API_BASE}/api/subscribers/${SUBSCRIBER}/logs/upload" \
  -F "files=@${TMP_DIR}/log.txt" \
  >/dev/null

echo "[smoke] starting pipeline job"
PIPELINE_JOB_JSON="$(
  curl -fsS \
    -X POST "${API_BASE}/api/pipeline/jobs" \
    -H "Content-Type: application/json" \
    -d "{\"subscriber\":\"${SUBSCRIBER}\",\"until\":\"cp6\",\"reindex\":false,\"allow_sample_data\":false}"
)"
PIPELINE_JOB_ID="$(json_get "$PIPELINE_JOB_JSON" "id")"
poll_job "/api/pipeline/jobs/${PIPELINE_JOB_ID}" "pipeline" >/dev/null

LATEST_RESULTS_JSON="$(curl -fsS "${API_BASE}/api/subscribers/${SUBSCRIBER}/results/latest")"
echo "[smoke] latest results summary trusted_rate=$(json_get "$LATEST_RESULTS_JSON" "summary.summary.trusted_rate")"

ANCHOR_JOB_OUTPUT=""
if ! ANCHOR_JOB_OUTPUT="$(run_anchor_eval_job "${ANCHOR_DATASET_PATH}" "primary" 2>&1)"; then
  if [[ "${ANCHOR_DATASET_PATH}" != "${CONTAINER_ANCHOR_DATASET}" ]] && grep -q "앵커 eval 데이터셋이 없습니다" <<<"${ANCHOR_JOB_OUTPUT}"; then
    echo "[smoke] host path failed, retrying anchor eval with container path"
    run_anchor_eval_job "${CONTAINER_ANCHOR_DATASET}" "container" >/dev/null
  else
    echo "${ANCHOR_JOB_OUTPUT}" >&2
    exit 1
  fi
fi

ANCHOR_RESULTS_JSON="$(curl -fsS "${API_BASE}/api/subscribers/${SUBSCRIBER}/evals/anchor/latest")"
echo "[smoke] anchor eval retrieval_hit_rate=$(json_get "$ANCHOR_RESULTS_JSON" "summary.retrieval_hit_rate")"

REVIEW_OPS_JSON="$(curl -fsS "${API_BASE}/api/dashboard/review-ops")"
echo "[smoke] review ops pending=$(json_get "$REVIEW_OPS_JSON" "overview.total_pending_reviews")"

echo "[smoke] success"
echo "[smoke] subscriber=${SUBSCRIBER}"
echo "[smoke] backend=${API_BASE}"
echo "[smoke] frontend=${FRONTEND_BASE}"
