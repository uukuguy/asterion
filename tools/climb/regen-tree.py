#!/usr/bin/env python3
"""Write only stable, public-safe climb cycle state."""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_DIR = ROOT / "docs" / "status" / "climb"


def state_dir() -> Path:
    configured = os.environ.get("ASTERION_CLIMB_STATE_DIR")
    return Path(configured) if configured else DEFAULT_STATE_DIR


def main(arguments: list[str]) -> int:
    if len(arguments) != 4:
        return 2
    hypothesis_id, outcome, next_action, command_id = arguments
    if (hypothesis_id, outcome, next_action, command_id) != (
        "H-001",
        "passed",
        "H-002",
        "test.prime-rlm.provider-free",
    ):
        return 2
    root = state_dir()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    runs_path = root / "runs.csv"
    existing = runs_path.exists()
    with runs_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        if not existing:
            writer.writerow(("cycle", "hypothesis_id", "outcome", "command_id"))
        writer.writerow(("1", hypothesis_id, outcome, command_id))
    (root / "session-state.json").write_text(
        json.dumps(
            {
                "last_hypothesis": hypothesis_id,
                "last_outcome": outcome,
                "next_action": next_action,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "research-tree.md").write_text(
        "# Prime Climb Research Tree\n\n"
        "- H-001: passed — provider-free RLM harness\n"
        "- Next: H-002 — RLM recovery evidence\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
