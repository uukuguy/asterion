"""Synchronize one reviewed Plan 4 task into the tracked climb state."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "docs/status/climb"
HYPOTHESES = STATE / "hypotheses.yaml"
RUNS = STATE / "runs.csv"
SESSION = STATE / "session-state.json"
JOURNAL = ROOT / "docs/status/JOURNAL.md"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("hypothesis_id")
    parser.add_argument("--commit-range", required=True)
    parser.add_argument("--review", required=True)
    args = parser.parse_args()

    data = json.loads(HYPOTHESES.read_text())
    hypotheses = data["hypotheses"]
    current = next(
        (item for item in hypotheses if item["id"] == args.hypothesis_id),
        None,
    )
    if current is None:
        raise SystemExit("unknown hypothesis")
    if current["status"] != "in-flight":
        raise SystemExit("hypothesis is not in-flight")

    cycle = int(args.hypothesis_id.split("-")[1])
    completed = sum(item["status"] == "confirmed" for item in hypotheses) + 1
    run_id = f"plan4-climb-h{cycle:03d}"
    current["status"] = "confirmed"
    current["results"].append(
        {
            "session": "2026-07-28-plan4",
            "cycle": cycle,
            "run": run_id,
            "local": completed,
            "verdict": "confirmed",
            "decision_reason": args.review,
            "commit_range": args.commit_range,
        }
    )

    next_item = next(
        (item for item in hypotheses if item["status"] == "pending"),
        None,
    )
    if next_item is not None:
        next_item["status"] = "in-flight"

    HYPOTHESES.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    with RUNS.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                run_id,
                cycle,
                "2026-07-28-plan4",
                args.hypothesis_id,
                current["parent_paradigm"],
                "",
                "",
                "",
                completed,
                "",
                "",
                "LOCAL",
                args.review,
                "confirmed",
                current["cost_h"],
                "",
            ]
        )

    session = json.loads(SESSION.read_text())
    session.update(
        {
            "phase": (
                f"Plan 4 Task {cycle + 1} implementation"
                if next_item is not None
                else "Plan 4 closure"
            ),
            "last_cycle": cycle,
            "next_hypothesis": (
                next_item["id"] if next_item is not None else None
            ),
            "in_flight": (
                {
                    "kind": "subagent-driven-development",
                    "task": f"Plan 4 Task {cycle + 1}",
                    "external_execution": False,
                }
                if next_item is not None
                else None
            ),
            "next_action": (
                f"Dispatch Plan 4 Task {cycle + 1} implementer with TDD brief."
                if next_item is not None
                else "Run the complete Plan 4 closure gate and final review."
            ),
            "sota": {"local": completed},
        }
    )
    SESSION.write_text(json.dumps(session, indent=2) + "\n")

    now = datetime.now().astimezone()
    journal = JOURNAL.read_text()
    header = f"## {now:%Y-%m-%d}"
    if header not in journal:
        journal = journal.rstrip() + f"\n\n{header}\n"
    journal += (
        f"- {now:%H:%M} climb confirmed Plan 4 Task {cycle}: "
        f"{args.review} [{args.commit_range}]\n"
    )
    JOURNAL.write_text(journal)

    subprocess.run(
        ["python3", "tools/climb/regen-tree.py"],
        cwd=ROOT,
        check=True,
    )
    result = subprocess.run(
        ["python3", "tools/climb/check-target.py"],
        cwd=ROOT,
        check=False,
    )
    if result.returncode not in (0, 10):
        raise SystemExit(result.returncode)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
