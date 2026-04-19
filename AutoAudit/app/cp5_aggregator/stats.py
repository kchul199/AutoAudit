"""CP5 — 평가 결과 집계 및 차트 생성."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app.cp4_evaluator.consensus import (
    STATE_DEGRADED,
    STATE_INCOMPLETE,
    STATE_TRUSTED,
    STATE_UNCERTAIN,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

STATE_PRIORITY = {
    STATE_INCOMPLETE: 0,
    STATE_DEGRADED: 1,
    STATE_UNCERTAIN: 2,
    STATE_TRUSTED: 3,
}


class StatsAggregator:
    """턴 단위 평가 결과를 대화/가입자 단위로 집계."""

    def __init__(self, results_dir: str):
        self.results_dir = Path(results_dir)

    def aggregate(self, subscriber: str, turn_results: list[dict[str, Any]]) -> dict[str, Any]:
        output_dir = self.results_dir / subscriber
        output_dir.mkdir(parents=True, exist_ok=True)

        conversation_map: dict[str, dict[str, Any]] = {}
        issue_counter: Counter[str] = Counter()
        review_queue: list[dict[str, Any]] = []

        for item in turn_results:
            consensus = item["consensus"]
            state = consensus.get("state", STATE_INCOMPLETE)
            conv_id = item["conv_id"]
            conversation = conversation_map.setdefault(
                conv_id,
                {
                    "conv_id": conv_id,
                    "source_file": item.get("source_file", ""),
                    "turns": [],
                    "state_counts": Counter(),
                },
            )

            overall = consensus.get("overall_mean")
            support_overall = consensus.get("support_overall_mean")
            turn_entry = {
                "turn_index": item["turn_index"],
                "user_query": item["user_query"],
                "bot_answer": item["bot_answer"],
                "overall_mean": overall,
                "support_overall_mean": support_overall,
                "state": state,
                "review_required": consensus.get("review_required", state != STATE_TRUSTED),
                "consensus": consensus,
                "context": item.get("context", {}),
            }
            conversation["turns"].append(turn_entry)
            conversation["state_counts"][state] += 1

            if turn_entry["review_required"]:
                grounding_signals = (item.get("context", {}) or {}).get("grounding_signals", {})
                review_queue.append(
                    {
                        "conv_id": conv_id,
                        "source_file": item.get("source_file", ""),
                        "turn_index": item["turn_index"],
                        "user_query": item["user_query"],
                        "bot_answer": item["bot_answer"][:200],
                        "state": state,
                        "state_reason": consensus.get("state_reason", ""),
                        "overall_mean": overall,
                        "support_overall_mean": support_overall,
                        "grounding_risk": grounding_signals.get("grounding_risk", "unknown"),
                        "top1_score": grounding_signals.get("top1_score", 0.0),
                        "live_judge_count": consensus.get("live_judge_count", 0),
                        "fallback_judge_count": consensus.get("fallback_judge_count", 0),
                    }
                )

            for detail in consensus.get("scores_detail", []):
                for issue in detail.get("key_issues", []):
                    issue_counter[issue] += 1
                for issue in detail.get("flow_issues", []):
                    issue_counter[issue] += 1
                for flag in detail.get("risk_flags", []):
                    issue_counter[flag] += 1

        trusted_turns: list[dict[str, Any]] = []
        operational_turns: list[dict[str, Any]] = []
        conversations = []
        review_queue.sort(
            key=lambda item: (
                STATE_PRIORITY.get(item["state"], 9),
                item["overall_mean"] if item["overall_mean"] is not None else item["support_overall_mean"] or 0.0,
            )
        )

        for conversation in conversation_map.values():
            turns = conversation["turns"]
            trusted = [turn for turn in turns if turn["state"] == STATE_TRUSTED]
            operational = [turn for turn in turns if turn["overall_mean"] is not None]
            trusted_turns.extend(trusted)
            operational_turns.extend(operational)

            state_counts = conversation.pop("state_counts")
            dominant_state = min(
                state_counts,
                key=lambda state: STATE_PRIORITY.get(state, 99),
            ) if state_counts else STATE_INCOMPLETE

            conversations.append(
                {
                    **conversation,
                    "trusted_turn_count": len(trusted),
                    "review_turn_count": sum(1 for turn in turns if turn["review_required"]),
                    "uncertain_count": state_counts.get(STATE_UNCERTAIN, 0),
                    "degraded_turn_count": state_counts.get(STATE_DEGRADED, 0),
                    "incomplete_turn_count": state_counts.get(STATE_INCOMPLETE, 0),
                    "dominant_state": dominant_state,
                    "avg_accuracy": self._mean(trusted, "accuracy_mean"),
                    "avg_fluency": self._mean(trusted, "fluency_mean"),
                    "avg_overall": self._mean_direct(trusted, "overall_mean"),
                    "avg_operational_overall": self._mean_direct(operational, "overall_mean"),
                    "turn_count": len(turns),
                }
            )

        conversations.sort(
            key=lambda item: (
                STATE_PRIORITY.get(item["dominant_state"], 99),
                item["avg_overall"] if item["avg_overall"] is not None else item["avg_operational_overall"] or 0.0,
            )
        )

        total_turns = len(turn_results)
        trusted_count = sum(1 for item in turn_results if item["consensus"].get("state") == STATE_TRUSTED)
        uncertain_count = sum(1 for item in turn_results if item["consensus"].get("state") == STATE_UNCERTAIN)
        degraded_count = sum(1 for item in turn_results if item["consensus"].get("state") == STATE_DEGRADED)
        incomplete_count = sum(1 for item in turn_results if item["consensus"].get("state") == STATE_INCOMPLETE)
        live_consensus_count = trusted_count + uncertain_count

        trusted_avg_accuracy = self._mean(trusted_turns, "accuracy_mean")
        trusted_avg_fluency = self._mean(trusted_turns, "fluency_mean")
        trusted_avg_groundedness = self._mean(trusted_turns, "groundedness_mean")
        trusted_avg_policy = self._mean(trusted_turns, "policy_compliance_mean")
        trusted_avg_task = self._mean(trusted_turns, "task_completion_mean")
        trusted_avg_overall = self._mean_direct(trusted_turns, "overall_mean")

        summary = {
            "total_conversations": len(conversations),
            "total_bot_turns": total_turns,
            "trusted_turns": trusted_count,
            "uncertain_turns": uncertain_count,
            "degraded_turns": degraded_count,
            "incomplete_turns": incomplete_count,
            "trusted_rate": self._ratio(trusted_count, total_turns),
            "live_consensus_rate": self._ratio(live_consensus_count, total_turns),
            "review_queue_size": len(review_queue),
            "uncertain_ratio": self._ratio(uncertain_count, total_turns),
            "degraded_ratio": self._ratio(degraded_count, total_turns),
            "incomplete_ratio": self._ratio(incomplete_count, total_turns),
            "trusted_avg_accuracy": trusted_avg_accuracy,
            "trusted_avg_fluency": trusted_avg_fluency,
            "trusted_avg_groundedness": trusted_avg_groundedness,
            "trusted_avg_policy_compliance": trusted_avg_policy,
            "trusted_avg_task_completion": trusted_avg_task,
            "trusted_avg_overall": trusted_avg_overall,
            # Legacy aliases for existing UI/API consumers.
            "avg_accuracy": trusted_avg_accuracy,
            "avg_fluency": trusted_avg_fluency,
            "avg_overall": trusted_avg_overall,
            "uncertain_count": uncertain_count,
            "low_score_turns": sum(
                1 for turn in trusted_turns
                if (turn.get("overall_mean") or 0.0) < 3.0
            ),
        }

        report = {
            "subscriber": subscriber,
            "evaluation_date": datetime.now().strftime("%Y-%m-%d"),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "summary": summary,
            "conversations": conversations,
            "review_queue": review_queue[:20],
            "low_score_patterns": [
                {"issue_type": issue, "count": count}
                for issue, count in issue_counter.most_common(10)
            ],
        }

        chart_paths = self.generate_charts(subscriber, report)
        report["chart_paths"] = [Path(path).name for path in chart_paths]

        output_path = output_dir / "cp5_summary.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"[CP5] 집계 결과 저장: {output_path}")

        return report

    def generate_charts(self, subscriber: str, report: dict[str, Any]) -> list[str]:
        output_dir = self.results_dir / subscriber
        output_dir.mkdir(parents=True, exist_ok=True)
        chart_paths: list[str] = []

        overall_values = [
            turn["overall_mean"]
            for conversation in report["conversations"]
            for turn in conversation["turns"]
            if turn["overall_mean"] is not None
        ]

        if overall_values:
            fig, ax = plt.subplots(figsize=(8, 4.5))
            ax.hist(overall_values, bins=10, color="#2E75B6", edgecolor="white")
            ax.set_title("Operational Score Distribution")
            ax.set_xlabel("Operational score")
            ax.set_ylabel("Turns")
            ax.grid(alpha=0.15)
            path = output_dir / "cp5_score_distribution.png"
            fig.tight_layout()
            fig.savefig(path, dpi=160)
            plt.close(fig)
            chart_paths.append(str(path))

        conversation_scores = [
            (item["source_file"] or item["conv_id"])[:18]
            for item in report["conversations"][:10]
        ]
        conversation_values = [
            item["avg_operational_overall"] or 0.0
            for item in report["conversations"][:10]
        ]
        if conversation_scores and any(value > 0 for value in conversation_values):
            fig, ax = plt.subplots(figsize=(8, 4.8))
            ax.barh(conversation_scores, conversation_values, color="#16A34A")
            ax.set_xlim(0, 5)
            ax.set_title("Conversation Operational Score")
            ax.set_xlabel("Average operational score")
            ax.grid(axis="x", alpha=0.15)
            path = output_dir / "cp5_conversation_scores.png"
            fig.tight_layout()
            fig.savefig(path, dpi=160)
            plt.close(fig)
            chart_paths.append(str(path))

        return chart_paths

    @staticmethod
    def _mean(items: list[dict[str, Any]], consensus_field: str) -> float | None:
        values = [
            item["consensus"].get(consensus_field)
            for item in items
            if item["consensus"].get(consensus_field) is not None
        ]
        if not values:
            return None
        return round(sum(values) / len(values), 2)

    @staticmethod
    def _mean_direct(items: list[dict[str, Any]], field_name: str) -> float | None:
        values = [
            item.get(field_name)
            for item in items
            if item.get(field_name) is not None
        ]
        if not values:
            return None
        return round(sum(values) / len(values), 2)

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        if denominator == 0:
            return 0.0
        return round(numerator / denominator, 3)
