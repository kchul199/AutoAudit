"""CP4 — 합의 점수 산출."""
from __future__ import annotations

import asyncio
import statistics
from dataclasses import dataclass
from typing import Any

from app.cp4_evaluator.judges import JudgeScore


@dataclass
class ConsensusScore:
    accuracy_mean: float
    fluency_mean: float
    overall_mean: float
    accuracy_std: float
    fluency_std: float
    is_uncertain: bool
    scores_detail: list[JudgeScore]
    flag: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accuracy_mean": self.accuracy_mean,
            "fluency_mean": self.fluency_mean,
            "overall_mean": self.overall_mean,
            "accuracy_std": self.accuracy_std,
            "fluency_std": self.fluency_std,
            "is_uncertain": self.is_uncertain,
            "flag": self.flag,
            "scores_detail": [score.to_dict() for score in self.scores_detail],
        }


class ConsensusEvaluator:
    """3개 Judge 결과를 취합해 합의 점수 계산."""

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

        acc_scores = [result.accuracy for result in results]
        flu_scores = [result.fluency for result in results]

        accuracy_mean = round(self._weighted_mean(results, "accuracy"), 2)
        fluency_mean = round(self._weighted_mean(results, "fluency"), 2)
        overall_mean = round((accuracy_mean + fluency_mean) / 2, 2)
        accuracy_std = round(statistics.pstdev(acc_scores) if len(acc_scores) > 1 else 0.0, 2)
        fluency_std = round(statistics.pstdev(flu_scores) if len(flu_scores) > 1 else 0.0, 2)

        is_uncertain = (
            accuracy_std > self.uncertainty_threshold
            or fluency_std > self.uncertainty_threshold
        )

        return ConsensusScore(
            accuracy_mean=accuracy_mean,
            fluency_mean=fluency_mean,
            overall_mean=overall_mean,
            accuracy_std=accuracy_std,
            fluency_std=fluency_std,
            is_uncertain=is_uncertain,
            flag="UNCERTAIN" if is_uncertain else None,
            scores_detail=results,
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
