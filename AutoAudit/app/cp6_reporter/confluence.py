"""CP6 — 로컬 HTML/Confluence 보고서 발행."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


class ConfluenceReporter:
    """로컬 HTML 생성 + Confluence 베스트에포트 발행."""

    def __init__(self, config: dict[str, Any], results_dir: str):
        self.config = config
        self.results_dir = Path(results_dir)

    def publish(
        self,
        subscriber: str,
        report: dict[str, Any],
        chart_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        chart_paths = chart_paths or []
        output_dir = self.results_dir / subscriber
        output_dir.mkdir(parents=True, exist_ok=True)

        html_body = self.build_html(report, chart_paths)
        local_report_path = output_dir / "cp6_report.html"
        local_report_path.write_text(html_body, encoding="utf-8")

        result = {
            "status": "local_only",
            "local_report_path": str(local_report_path),
            "chart_paths": chart_paths,
            "confluence_page_id": None,
            "confluence_url": None,
        }

        publish_enabled = all(
            [
                self.config.get("confluence_url"),
                self.config.get("confluence_email"),
                self.config.get("confluence_token"),
                self.config.get("confluence_space_key"),
            ]
        )
        if publish_enabled:
            try:
                from atlassian import Confluence

                cf = Confluence(
                    url=self.config["confluence_url"],
                    username=self.config["confluence_email"],
                    password=self.config["confluence_token"],
                    cloud=True,
                )
                title = f"[{subscriber}] 콜봇 품질 보고서 - {report['evaluation_date']}"
                existing = cf.get_page_by_title(self.config["confluence_space_key"], title)
                if existing:
                    cf.update_page(existing["id"], title, html_body)
                    page_id = existing["id"]
                else:
                    page = cf.create_page(
                        space=self.config["confluence_space_key"],
                        title=title,
                        body=html_body,
                        parent_id=self.config.get("confluence_parent_page_id") or None,
                    )
                    page_id = page["id"]

                for path in chart_paths:
                    try:
                        cf.attach_file(path, name=Path(path).name, page_id=page_id)
                    except Exception as e:
                        logger.warning(f"[CP6] 차트 첨부 실패 {path}: {e}")

                result.update(
                    {
                        "status": "published",
                        "confluence_page_id": page_id,
                        "confluence_url": self.config["confluence_url"],
                    }
                )
            except Exception as e:
                logger.warning(f"[CP6] Confluence 발행 실패 — 로컬 보고서만 저장: {e}")
                result["publish_error"] = str(e)

        meta_path = output_dir / "cp6_publish_result.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"[CP6] 보고서 저장: {local_report_path}")
        return result

    def build_html(self, report: dict[str, Any], chart_paths: list[str]) -> str:
        chart_tags = "\n".join(
            f'<div class="chart"><img src="{html.escape(Path(path).name)}" alt="chart"></div>'
            for path in chart_paths
        )

        conversation_rows = "\n".join(
            f"""
            <tr>
              <td>{html.escape(item.get("source_file") or item["conv_id"])}</td>
              <td>{item["turn_count"]}</td>
              <td>{item["avg_accuracy"]}</td>
              <td>{item["avg_fluency"]}</td>
              <td>{item["avg_overall"]}</td>
              <td>{item["uncertain_count"]}</td>
            </tr>
            """
            for item in report["conversations"]
        )

        issue_rows = "\n".join(
            f"<li>{html.escape(item['issue_type'])} ({item['count']}건)</li>"
            for item in report["low_score_patterns"]
        ) or "<li>특이 패턴 없음</li>"

        uncertain_rows = "\n".join(
            f"""
            <tr>
              <td>{html.escape(item['conv_id'])}</td>
              <td>{item['turn_index']}</td>
              <td>{html.escape(item['user_query'][:80])}</td>
              <td>{item['overall_mean']}</td>
            </tr>
            """
            for item in report["uncertain_cases"]
        ) or '<tr><td colspan="4">불확실 케이스 없음</td></tr>'

        summary = report["summary"]
        return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>{html.escape(report['subscriber'])} 품질 보고서</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #172033; }}
    h1, h2 {{ color: #1f497d; }}
    .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin: 24px 0; }}
    .metric {{ background: #f7fbff; border: 1px solid #d6e5f5; border-radius: 16px; padding: 16px; }}
    .metric .label {{ font-size: 12px; color: #5c6b82; text-transform: uppercase; letter-spacing: 0.06em; }}
    .metric .value {{ font-size: 28px; font-weight: 700; margin-top: 8px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 16px 0 24px; }}
    th, td {{ border-bottom: 1px solid #e6edf5; padding: 10px 8px; text-align: left; font-size: 14px; }}
    th {{ color: #58708e; font-weight: 600; }}
    .chart img {{ max-width: 100%; border: 1px solid #dbe4ee; border-radius: 12px; }}
    .muted {{ color: #66758b; }}
  </style>
</head>
<body>
  <h1>{html.escape(report['subscriber'])} 콜봇 품질 보고서</h1>
  <p class="muted">생성 시각: {html.escape(report['generated_at'])}</p>

  <div class="grid">
    <div class="metric"><div class="label">평균 정확성</div><div class="value">{summary['avg_accuracy']}</div></div>
    <div class="metric"><div class="label">평균 자연스러움</div><div class="value">{summary['avg_fluency']}</div></div>
    <div class="metric"><div class="label">불확실 비율</div><div class="value">{round(summary['uncertain_ratio'] * 100, 1)}%</div></div>
  </div>

  <h2>점수 차트</h2>
  {chart_tags or "<p class='muted'>생성된 차트가 없습니다.</p>"}

  <h2>대화별 요약</h2>
  <table>
    <thead>
      <tr>
        <th>대화</th><th>턴 수</th><th>정확성</th><th>자연스러움</th><th>종합</th><th>불확실</th>
      </tr>
    </thead>
    <tbody>
      {conversation_rows}
    </tbody>
  </table>

  <h2>주요 낮은 점수 패턴</h2>
  <ul>{issue_rows}</ul>

  <h2>불확실 케이스</h2>
  <table>
    <thead>
      <tr><th>대화 ID</th><th>턴</th><th>질문</th><th>종합 점수</th></tr>
    </thead>
    <tbody>
      {uncertain_rows}
    </tbody>
  </table>
</body>
</html>
"""
