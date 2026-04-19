# 사람 최소 개입형 고신뢰 평가 설계

## 목적

이 설계는 초기 기획 의도인 `사람 리소스 최소화`를 유지하면서도, 평가 정확도와 결과 신뢰도를 희생하지 않기 위한 운영 원칙을 정의한다.

핵심 요구사항은 다음 두 가지다.

1. `1차 평가부터 3개 AI Judge를 모두 사용한다.`
2. `fallback 때문에 운영 점수의 신뢰도가 흐려지지 않아야 한다.`


## 핵심 원칙

### 1. 전수 3중 평가

- 모든 평가 대상 턴은 `Claude`, `GPT`, `Gemini` 3개 Judge가 동시에 1차 평가한다.
- 특정 비용 절감을 위해 단일 저비용 Judge로 전수 평가한 뒤 일부만 3중 평가하는 구조는 채택하지 않는다.
- 정확도 향상을 위해 `전수 3중 평가 -> 합의 점수 산출 -> 불확실 케이스만 사람 검토` 순서를 유지한다.

### 2. 신뢰도 보존 우선

- 3개 Judge 중 하나라도 실패하면 결과를 정상 운영 점수로 간주하지 않는다.
- fallback 점수는 운영 점수와 완전히 분리한다.
- 운영 점수는 `3개 live Judge가 모두 성공한 경우`에만 생성한다.
- 나머지는 `DEGRADED` 또는 `INCOMPLETE` 상태로 저장하고, UI와 보고서에서 명확히 구분한다.

### 3. 사람은 예외 처리자

- 사람은 전체 샘플을 평가하지 않는다.
- 사람은 아래 케이스만 본다.
- `3개 Judge 간 점수 편차가 큰 케이스`
- `retrieval 근거가 약한 케이스`
- `정책 위반 가능성이 높은 케이스`
- `3개 Judge 중 일부 실패로 INCOMPLETE 처리된 케이스`


## To-Be 파이프라인

### CP1. 데이터 전처리

- 기존과 동일하게 로그와 도메인 문서를 수집한다.
- 운영 품질을 위해 입력 데이터의 품질 상태를 함께 저장한다.
- 예: 로그 형식 정상 여부, 문서 파싱 성공률, 문서 최신성 메타데이터

### CP2. 지식 베이스 구축

- 기존 Parent-Child 청킹 구조는 유지한다.
- 단, 운영 점수 산출 전제 조건으로 `문서 최신성`, `문서 출처`, `문서 버전`을 메타데이터에 포함한다.
- 근거 추적을 위해 모든 chunk는 `source_uri`, `source_version`, `updated_at`를 가져야 한다.

### CP3. 컨텍스트 검색

- 기존 HyDE, Multi-Query, Cross-Encoder 구조는 유지 가능하다.
- 다만 평가 품질을 위해 검색 결과에 아래 신호를 추가 저장한다.
- `top1 score`
- `top1-top2 gap`
- `retrieval coverage`
- `faq/manual/website 출처 비율`
- `grounding_risk`

- CP3 출력은 단순 context text가 아니라 `평가용 evidence packet`이어야 한다.

```json
{
  "query": "...",
  "top_chunks": [...],
  "grounding_signals": {
    "top1_score": 0.84,
    "score_gap": 0.11,
    "source_diversity": 0.67,
    "grounding_risk": "low"
  }
}
```

### CP4. 3개 AI 동시 평가

- 모든 bot turn에 대해 `Claude`, `GPT`, `Gemini` 3개 Judge를 병렬 호출한다.
- 각 Judge는 반드시 동일한 schema로 반환한다.
- Judge 결과는 자유 텍스트가 아니라 구조화된 필드여야 한다.

필수 필드:

- `accuracy`
- `fluency`
- `groundedness`
- `policy_compliance`
- `task_completion`
- `risk_flags`
- `reason_summary`
- `evidence_alignment`

- 점수는 `structured output` 형태로 강제한다.
- Judge prompt는 버전 관리하고, 평가 run마다 `prompt_version`을 기록한다.

### CP4-A. 상태 분리

운영 상태는 아래처럼 분리한다.

- `TRUSTED`
- 3개 Judge 모두 live 성공
- 합의 점수 생성 가능

- `UNCERTAIN`
- 3개 Judge 모두 성공했지만 편차 또는 grounding risk가 큼
- 사람 검토 큐로 이동

- `DEGRADED`
- 3개 Judge 중 일부가 실패하여 fallback이 개입
- 운영 KPI 집계에서 제외하거나 별도 집계

- `INCOMPLETE`
- 평가 자체를 신뢰할 수 없을 정도로 입력 또는 Judge 상태가 불완전
- 재실행 대상

### CP4-B. fallback 정책

- fallback은 `시스템 가용성 확보` 용도일 뿐 `운영 점수 대체` 용도가 아니다.
- 예를 들어 한 Judge 실패 시 휴리스틱 점수를 넣더라도:
- 합의 평균에 섞지 않는다.
- 운영 평균에 반영하지 않는다.
- 보고서에 `보조 참고값`으로만 표기한다.

즉:

- `운영 점수 = live 3중 평가 결과`
- `fallback 점수 = 보조 진단 정보`

### CP5. 집계

- 평균 점수 집계는 `TRUSTED` 케이스만 기본 KPI에 반영한다.
- `UNCERTAIN`, `DEGRADED`, `INCOMPLETE`는 별도 운영 지표로 분리한다.

핵심 KPI:

- `trusted_avg_accuracy`
- `trusted_avg_groundedness`
- `uncertain_ratio`
- `degraded_ratio`
- `incomplete_ratio`
- `policy_risk_count`
- `review_queue_size`

### CP6. 보고서

- 보고서 첫 화면에는 평균 점수보다 `신뢰 가능한 평가 비율`을 먼저 보여준다.
- 예:
- 신뢰 평가율 91%
- 사람 검토 필요 6%
- 재실행 필요 3%

- 운영자가 가장 먼저 봐야 할 것은 다음이다.
- `오늘 검토해야 하는 케이스`
- `정책 위반 위험 케이스`
- `grounding 실패 상위 케이스`
- `Judge 실패로 인해 incomplete 처리된 케이스`


## 합의 점수 설계

### 합의 계산 전제

- 3개 Judge 결과가 모두 live 성공해야 합의 점수를 계산한다.
- 하나라도 fallback 또는 파싱 실패가 있으면 기본 합의 점수는 생성하지 않는다.

### 합의 계산 방식

- `accuracy`, `groundedness`, `policy_compliance`, `task_completion`은 가중 평균
- `fluency`는 보조 지표
- 최종 운영 점수는 정확도 중심으로 산출

예시:

```text
final_score =
  0.35 * accuracy +
  0.30 * groundedness +
  0.20 * task_completion +
  0.10 * policy_compliance +
  0.05 * fluency
```

### 불확실 판정

표준편차만으로 판단하지 않는다. 아래를 함께 본다.

- 3개 Judge 편차
- retrieval grounding risk
- evidence alignment score
- policy risk flag 존재 여부
- parse 실패 또는 응답 누락 여부


## 사람 개입 최소화 전략

### 사람은 어디에만 개입하나

- prompt 기준 변경 시 앵커 케이스 검토
- `UNCERTAIN` 큐 승인/반려
- `DEGRADED` 원인 확인
- 월간 품질 감사 샘플 검토

### 사람 개입을 줄이는 장치

- 동일 패턴 이슈 자동 묶음
- 같은 원인의 실패는 한 번만 검토
- prompt 변경 전후는 자동 eval 회귀로 비교
- 검토자가 내린 판정을 다음 규칙 보정 데이터로 축적


## 최신 운영 기술 흐름 반영

이 저장소의 향후 설계는 아래 방향을 따른다.

- Judge 출력은 `structured outputs` 기반으로 고정
- prompt는 코드 하드코딩이 아니라 버전 관리 대상
- 대량 평가 run은 `batch` 또는 background job으로 처리
- 장문 시스템 프롬프트/정적 rubric은 `prompt caching` 대상
- 모델 교체보다 `eval set`과 `judge schema` 안정화에 우선 투자


## 구현 반영 포인트

현재 코드 기준으로는 아래 순서로 반영한다.

1. `CP4 state model` 추가
- `TRUSTED`, `UNCERTAIN`, `DEGRADED`, `INCOMPLETE`

2. `JudgeScore schema` 확장
- accuracy, fluency 외에 groundedness, policy_compliance, task_completion 추가

3. `ConsensusEvaluator` 수정
- 3 live 성공이 아닐 경우 운영 합의 점수 미산출

4. `CP5 KPI` 수정
- trusted 기반 KPI와 degraded/incomplete 비율 분리

5. `UI` 수정
- 종합점수 카드보다 검토 큐와 신뢰 평가율을 전면 배치

6. `보고서` 수정
- fallback 사용 여부와 judge 성공/실패 상태를 명시


## 결론

사람 리소스를 최소화하려면 `AI를 줄이는 것`이 아니라 `사람이 볼 대상을 줄이는 것`이 핵심이다.

따라서 이 프로젝트의 평가 설계는 다음 원칙으로 고정한다.

- `전수 3중 AI 평가`
- `운영 점수는 3개 live Judge 성공시에만 산출`
- `fallback은 점수 보조 정보로만 사용`
- `사람은 예외 큐만 검토`

이 방식이 초기 기획의 자동화 방향과, 프로덕션 신뢰도 요구를 동시에 만족한다.
