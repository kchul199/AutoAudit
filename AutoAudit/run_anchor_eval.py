#!/usr/bin/env python3
"""앵커 Eval 실행 CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.eval_ops import run_anchor_eval
from app.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoAudit 앵커 Eval 실행기")
    parser.add_argument("--subscriber", "-s", required=True, help="가입자명")
    parser.add_argument("--dataset", "-d", required=True, help="JSONL 형식 앵커 eval 데이터셋 경로")
    parser.add_argument("--env", default=".env", help=".env 파일 경로")
    args = parser.parse_args()

    config = load_config(args.env)
    report = run_anchor_eval(
        subscriber=args.subscriber,
        config=config,
        dataset_path=args.dataset,
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
