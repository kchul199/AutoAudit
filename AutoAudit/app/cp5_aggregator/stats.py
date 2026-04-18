"""CP5 — 평가 결과 집계 및 차트 생성."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app.utils.logger import get_logger

logger = get_logger(__name__)


class StatsAggregator:
    """턴 단위 평가 결과를 대화/가입자 단위로 집계."""

    def __init__(self, results_dir: str):
        self.results_dir = Path(results_dir)

    def aggregate(self, subscriber: str, turn_results: list[dict[str, Any]]) -> dict[str, Any]:
        output_dir = self.results_dir / subscriber
        output_dir.mkdir(parents=True, exist_ok=True)

        conversation_map: dict[str, dict[str, Any]] = {}
        issue_counter: Counter[str] = Counter()
        uncertain_cases: list[dict[str, Any]] = []

        for item in turn_results:
            consensus = item["consensus"]
            conv_id = item["conv_id"]
            conversation = conversation_map.setdefault(
                conv_id,
                {
                    "conv_id": conv_id,
                    "source_file": item.get("source_file", ""),
                    "turns": [],
                },
            )

            overall = round((consensus["accuracy_mean"] + consensus["fluency_mean"]) / 2, 2)
            turn_entry = {
                "turn_index": item["turn_index"],
                "user_query": item["user_query"],
                "bot_answer": item["bot_answer"],
                "overall_mean": overall,
                "consensus": consensus,
                "context": item.get("context", {}),
            }
            conversation["turns"].append(turn_entry)

            if consensus["is_uncertain"]:
                uncertain_cases.append(
                    {
                        "conv_id": conv_id,
                        "turn_index": item["turn_index"],
                        "user_query": item["user_query"],
                        "bot_answer": item["bot_answer"][:200],
                        "overall_mean": overall,
                    }
                )

            for detail in consensus["scores_detail"]:
                for issue in detail.get("key_issues", []):
                    issue_counter[issue] += 1
                for issue in detail.get("flow_issues", []):
                    issue_counter[issue] += 1

        conversations = []
        accuracy_values = []
        fluency_values = []
        overall_values = []

        for conversation in conversation_map.values():
            turns = conversation["turns"]
            acc_avg = round(sum(t["consensus"]["accuracy_mean"] for t in turns) / len(turns), 2)
            flu_avg = round(sum(t["consensus"]["fluency_mean"] for t in turns) / len(turns), 2)
            overall_avg = round(sum(t["overall_mean"] for t in turns) / len(turns), 2)
            uncertain_count = sum(1 for t in turns if t["consensus"]["is_uncertain"])

            accuracy_values.extend(t["consensus"]["accuracy_mean"] for t in turns)
            fluency_values.extend(t["consensus"]["fluency_mean"] for t in turns)
            overall_values.extend(t["overall_mean"] for t in turns)

            conversations.append(
                {
                    **conversation,
                    "avg_accuracy": acc_avg,
                    "avg_fluency": flu_avg,
                    "avg_overall": overall_avg,
                    "uncertain_count": uncertain_count,
                    "turn_count": len(turns),
                }
            )

        conversations.sort(key=lambda item: item["avg_overall"])

        summary = {
            "total_conversations": len(conversations),
            "total_bot_turns": len(turn_results),
            "avg_accuracy": round(sum(accuracy_values) / len(accuracy_values), 2) if accuracy_values else 0.0,
            "avg_fluency": round(sum(fluency_values) / len(fluency_values), 2) if fluency_values else 0.0,
            "avg_overall": round(sum(overall_values) / len(overall_values), 2) if overall_values else 0.0,
            "uncertain_count": len(uncertain_cases),
            "uncertain_ratio": round(len(uncertain_cases) / len(turn_results), 3) if turn_results else 0.0,
            "low_score_turns": sum(1 for value in overall_values if value < 3.0),
        }

        report = {
            "subscriber": subscriber,
            "evaluation_date": datetime.now().strftime("%Y-%m-%d"),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "summary": summary,
            "conversations": conversations,
            "low_score_patterns": [
                {"issue_type": issue, "count": count}
                for issue, count in issue_counter.most_common(8)
            ],
            "uncertain_cases": uncertain_cases[:20],
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
        ]

        if overall_values:
            fig, ax = plt.subplots(figsize=(8, 4.5))
            ax.hist(overall_values, bins=10, color="#2E75B6", edgecolor="white")
            ax.set_title("Turn Score Distribution")
            ax.set_xlabel("Overall score")
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
            item["avg_overall"] for item in report["conversations"][:10]
        ]
        if conversation_scores:
            fig, ax = plt.subplots(figsize=(8, 4.8))
            ax.barh(conversation_scores, conversation_values, color="#16A34A")
            ax.set_xlim(0, 5)
            ax.set_title("Conversation Average Score")
            ax.set_xlabel("Average overall score")
            ax.grid(axis="x", alpha=0.15)
            path = output_dir / "cp5_conversation_scores.png"
            fig.tight_layout()
            fig.savefig(path, dpi=160)
            plt.close(fig)
            chart_paths.append(str(path))

        return chart_paths
