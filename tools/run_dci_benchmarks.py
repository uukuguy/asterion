#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from dci_benchmark_orchestrator import (
    OrchestratorError,
    RunOptions,
    build_plan,
    render_plan,
)


def parse_args(argv: Sequence[str] | None = None) -> RunOptions:
    parser = argparse.ArgumentParser(description="Run Asterion DCI benchmarks")
    parser.add_argument("--suite", choices=("github", "paper-main", "all"), default="all")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    return RunOptions(
        suite=args.suite,
        limit=args.limit,
        max_concurrency=args.max_concurrency,
        output_root=args.output_root,
        env_file=args.env_file,
        execute=args.execute,
    )


def _run_label() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def main(argv: Sequence[str] | None = None) -> int:
    try:
        plan = build_plan(parse_args(argv), run_label=_run_label())
        render_plan(plan, sys.stdout)
        if not plan.options.execute:
            return 0
        from dci_benchmark_orchestrator import execute_plan

        return execute_plan(plan, stream=sys.stdout)
    except OrchestratorError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
