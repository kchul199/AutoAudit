"""CP4 — 합의 점수 산출."""
from __future__ import annotations

import asyncio
import statistics
from dataclasses import dataclass
from typing import Any

from app.cp4_evaluator.judges import JudgeScore

STATE_TRUSTED = "TRUSTED"
STATE_UNCERTAIN = "UNCERTAIN"
STATE_DEGRADED = "DEGRADED"
STATE_INCOMPLETE = "INCOMPLETE"


@dataclass
class ConsensusScore:
    accuracy_mean: float | None
    fluency_mean: float | None
    groundedness_mean: float | None
    policy_compliance_mean: float | None
    task_completion_mean: float | None
    evidence_alignment_mean: float | None
    overall_mean: float | None
    support_accuracy_mean: float
    support_fluency_mean: float
    support_groundedness_mean: float
    support_policy_compliance_mean: float
    support_task_completion_mean: float
    support_evidence_alignment_mean: float
    support_overall_mean: float
    accuracy_std: float
    fluency_std: float
    groundedness_std: float
    state: str
    state_reason: str
    is_uncertain: bool
    review_required: bool
    all_judges_live: bool
    live_judge_count: int
    fallback_judge_count: int
    scores_detail: list[JudgeScore]
    flag: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accuracy_mean": self.accuracy_mean,
            "fluency_mean": self.fluency_mean,
            "groundedness_mean": self.groundedness_mean,
            "policy_compliance_mean": self.policy_compliance_mean,
            "task_completion_mean": self.task_completion_mean,
            "evidence_alignment_mean": self.evidence_alignment_mean,
            "overall_mean": self.overall_mean,
            "support_accuracy_mean": self.support_accuracy_mean,
            "support_fluency_mean": self.support_fluency_mean,
            "support_groundedness_mean": self.support_groundedness_mean,
            "support_policy_compliance_mean": self.support_policy_compliance_mean,
            "support_task_completion_mean": self.support_task_completion_mean,
            "support_evidence_alignment_mean": self.support_evidence_alignment_mean,
            "support_overall_mean": self.support_overall_mean,
            "accuracy_std": self.accuracy_std,
            "fluency_std": self.fluency_std,
            "groundedness_std": self.groundedness_std,
            "state": self.state,
            "state_reason": self.state_reason,
            "is_uncertain": self.is_uncertain,
            "review_required": self.review_required,
            "all_judges_live": self.all_judges_live,
            "live_judge_count": self.live_judge_count,
            "fallback_judge_count": self.fallback_judge_count,
            "flag": self.flag,
            "scores_detail": [score.to_dict() for score in self.scores_detail],
        }


class ConsensusEvaluator:
    """3개 Judge 결과를 취합해 신뢰 상태와 합의 점수를 계산."""

    def __init__(
        self,
        judges: list,
        uncertainty_threshold: float = 1.5,
        weights: dict[str, float] | None = None,
    ):
        self.judges = judges
        self.uncertainty_threshold = uncertainty_threshold
        self.weights = weights or {
            "claude": 0.40,
            "gpt4o": 0.35,
            "gemini": 0.25,
        }

    async def evaluate(self, turn_data: dict[str, Any]) -> ConsensusScore:
        results: list[JudgeScore] = await asyncio.gather(
            *(judge.evaluate_async(turn_data) for judge in self.judges)
        )

        expected = len(self.judges)
        live_results = [result for result in results if result.is_live]
        fallback_results = [result for result in results if not result.is_live]
        all_judges_live = len(live_results) == expected and expected > 0

        support_accuracy_mean = round(self._weighted_mean(results, "accuracy"), 2)
        support_fluency_mean = round(self._weighted_mean(results, "fluency"), 2)
        support_groundedness_mean = round(self._weighted_mean(results, "groundedness"), 2)
        support_policy_compliance_mean = round(self._weighted_mean(results, "policy_compliance"), 2)
        support_task_completion_mean = round(self._weighted_mean(results, "task_completion"), 2)
        support_evidence_alignment_mean = round(self._weighted_mean(results, "evidence_alignment"), 2)
        support_overall_mean = round(
            self._overall_from_fields(
                support_accuracy_mean,
                support_groundedness_mean,
                support_task_completion_mean,
                support_policy_compliance_mean,
                support_fluency_mean,
            ),
            2,
        )

        accuracy_std = round(self._stddev(results, "accuracy"), 2)
        fluency_std = round(self._stddev(results, "fluency"), 2)
        groundedness_std = round(self._stddev(results, "groundedness"), 2)

        retrieval = turn_data.get("retrieval", {}) or {}
        grounding_signals = retrieval.get("grounding_signals", {})
        grounding_risk = grounding_signals.get("grounding_risk", "unknown")
        evidence_low = grounding_risk in {"high", "critical"} or not retrieval.get("top_chunks")
        policy_risk = any(
            "POLICY" in flag
            for result in results
            for flag in result.risk_flags
        )

        if len(results) < expected:
            state = STATE_INCOMPLETE
            state_reason = "Judge 응답 수가 부족해 신뢰 가능한 합의 점수를 만들 수 없습니다."
        elif not all_judges_live:
            state = STATE_DEGRADED
            degraded_models = ", ".join(result.model for result in fallback_results)
            state_reason = (
                f"3개 Judge live 평가가 모두 성공하지 않아 fallback이 개입했습니다: {degraded_models}."
            )
        else:
            is_uncertain = (
                accuracy_std > self.uncertainty_threshold
                or fluency_std > self.uncertainty_threshold
                or groundedness_std > self.uncertainty_threshold
                or evidence_low
                or support_evidence_alignment_mean < 2.5
                or policy_risk
            )
            if is_uncertain:
                state = STATE_UNCERTAIN
                state_reason = "3개 live Judge는 성공했지만 편차, grounding risk, 또는 정책 위험으로 검토가 필요합니다."
            else:
                state = STATE_TRUSTED
                state_reason = "3개 live Judge가 모두 성공했고 평가 편차와 grounding risk가 낮습니다."

        accuracy_mean = None
        fluency_mean = None
        groundedness_mean = None
        policy_compliance_mean = None
        task_completion_mean = None
        evidence_alignment_mean = None
        overall_mean = None

        if all_judges_live:
            accuracy_mean = round(self._weighted_mean(live_results, "accuracy"), 2)
            fluency_mean = round(self._weighted_mean(live_results, "fluency"), 2)
            groundedness_mean = round(self._weighted_mean(live_results, "groundedness"), 2)
            policy_compliance_mean = round(self._weighted_mean(live_results, "policy_compliance"), 2)
            task_completion_mean = round(self._weighted_mean(live_results, "task_completion"), 2)
            evidence_alignment_mean = round(self._weighted_mean(live_results, "evidence_alignment"), 2)
            overall_mean = round(
                self._overall_from_fields(
                    accuracy_mean,
                    groundedness_mean,
                    task_completion_mean,
                    policy_compliance_mean,
                    fluency_mean,
                ),
                2,
            )

        is_uncertain = state == STATE_UNCERTAIN
        review_required = state != STATE_TRUSTED

        return ConsensusScore(
            accuracy_mean=accuracy_mean,
            fluency_mean=fluency_mean,
            groundedness_mean=groundedness_mean,
            policy_compliance_mean=policy_compliance_mean,
            task_completion_mean=task_completion_mean,
            evidence_alignment_mean=evidence_alignment_mean,
            overall_mean=overall_mean,
            support_accuracy_mean=support_accuracy_mean,
            support_fluency_mean=support_fluency_mean,
            support_groundedness_mean=support_groundedness_mean,
            support_policy_compliance_mean=support_policy_compliance_mean,
            support_task_completion_mean=support_task_completion_mean,
            support_evidence_alignment_mean=support_evidence_alignment_mean,
            support_overall_mean=support_overall_mean,
            accuracy_std=accuracy_std,
            fluency_std=fluency_std,
            groundedness_std=groundedness_std,
            state=state,
            state_reason=state_reason,
            is_uncertain=is_uncertain,
            review_required=review_required,
            all_judges_live=all_judges_live,
            live_judge_count=len(live_results),
            fallback_judge_count=len(fallback_results),
            scores_detail=results,
            flag=state,
        )

    def _weighted_mean(self, results: list[JudgeScore], field_name: str) -> float:
        total = 0.0
        weight_sum = 0.0
        for result in results:
            weight = self.weights.get(result.model, 0.0)
            total += getattr(result, field_name) * weight
            weight_sum += weight
        if weight_sum == 0:
            return 0.0
        return total / weight_sum

    @staticmethod
    def _stddev(results: list[JudgeScore], field_name: str) -> float:
        values = [getattr(result, field_name) for result in results]
        if len(values) <= 1:
            return 0.0
        return statistics.pstdev(values)

    @staticmethod
    def _overall_from_fields(
        accuracy: float,
        groundedness: float,
        task_completion: float,
        policy_compliance: float,
        fluency: float,
    ) -> float:
        return (
            0.35 * accuracy
            + 0.30 * groundedness
            + 0.20 * task_completion
            + 0.10 * policy_compliance
            + 0.05 * fluency
        )
