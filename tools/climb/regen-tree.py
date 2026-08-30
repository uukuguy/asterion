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
    accepted = {
        ("H-001", "passed", "H-002", "test.prime-rlm.provider-free"): 1,
        ("H-002", "passed", "H-003", "test.prime-rlm.recovery-read-only"): 2,
        ("H-003", "passed", "H-004", "make.prime-verified-loop"): 3,
        (
            "H-004",
            "falsified",
            "H-005",
            "make.prime-native-rlm-bounded",
        ): 4,
        (
            "H-005",
            "passed",
            "H-006",
            "make.prime-native-rlm-bounded",
        ): 5,
        (
            "H-006",
            "passed",
            "H-007",
            "test.prime-session-context-parity.bounded",
        ): 6,
        (
            "H-007",
            "passed",
            "H-008",
            "check.phase2-session-context-closure",
        ): 7,
        (
            "H-008",
            "passed",
            "H-009",
            "test.prime-rlm-spawn-admission.provider-free",
        ): 8,
        (
            "H-009",
            "falsified",
            "H-010",
            "audit.prime-native-rlm-bounded-receipt",
        ): 9,
        (
            "H-010",
            "passed",
            "H-011",
            "check.rlm-programmatic-closure",
        ): 10,
        (
            "H-011",
            "passed",
            "H-012",
            "check.operation-long-running-inventory",
        ): 11,
        (
            "H-012",
            "passed",
            "H-013",
            "test.prime-long-running-matrix.provider-free",
        ): 12,
        (
            "H-013",
            "passed",
            "H-014",
            "test.control-long-running.provider-free",
        ): 13,
        (
            "H-014",
            "passed",
            "H-015",
            "test.prime-heartbeat-wire.provider-free",
        ): 14,
        (
            "H-015",
            "passed",
            "H-016",
            "test.prime-heartbeat-fencing.provider-free",
        ): 15,
        (
            "H-016",
            "passed",
            "H-017",
            "test.prime-heartbeat-ipc.provider-free",
        ): 16,
        (
            "H-017",
            "passed",
            "H-018",
            "test.prime-long-running-binding.provider-free",
        ): 17,
        (
            "H-018",
            "passed",
            "H-019",
            "test.prime-residency-recovery.provider-free",
        ): 18,
        (
            "H-019",
            "passed",
            "H-020",
            "test.prime-long-running-authority.provider-free",
        ): 19,
        (
            "H-020",
            "passed",
            "H-021",
            "test.prime-long-running.bounded",
        ): 20,
        (
            "H-021",
            "passed",
            "H-022",
            "test.prime-long-running.provider-free",
        ): 21,
        (
            "H-022",
            "passed",
            "H-023",
            "check.operation-long-running-closure",
        ): 22,
        (
            "H-023",
            "passed",
            "H-024",
            "check.harness-continual-closure",
        ): 23,
        (
            "H-024",
            "passed",
            "H-025",
            "check.ecosystem-capabilities-inventory",
        ): 24,
        (
            "H-025",
            "passed",
            "H-026",
            "test.control-ecosystem.provider-free",
        ): 25,
        (
            "H-026",
            "passed",
            "H-027",
            "test.ecosystem-materialization.provider-free",
        ): 26,
        (
            "H-027",
            "passed",
            "H-028",
            "test.prime-ecosystem-adapter.provider-free",
        ): 27,
        (
            "H-028",
            "passed",
            "H-029",
            "test.prime-ecosystem-gateway.provider-free",
        ): 28,
        (
            "H-029",
            "passed",
            "H-030",
            "test.prime-ecosystem-module.provider-free",
        ): 29,
        (
            "H-030",
            "passed",
            "H-031",
            "test.prime-ecosystem-resources.provider-free",
        ): 30,
        (
            "H-031",
            "passed",
            "H-032",
            "test.prime-ecosystem-extensions.provider-free",
        ): 31,
        (
            "H-032",
            "passed",
            "H-033",
            "test.prime-ecosystem-packages.provider-free",
        ): 32,
        (
            "H-033",
            "passed",
            "H-034",
            "test.prime-ecosystem-mcp.provider-free",
        ): 33,
        (
            "H-034",
            "passed",
            "H-035",
            "check.ecosystem-capabilities-closure",
        ): 34,
        (
            "H-035",
            "passed",
            "H-036",
            "check.client-interfaces-closure",
        ): 35,
        (
            "H-036",
            "passed",
            "future-work-queue",
            "check.operational-parity-closure",
        ): 36,
        (
            "H-037",
            "passed",
            "H-038",
            "prime-system-parity-operation-host-callback",
        ): 37,
        (
            "H-038",
            "passed",
            "phase-3.2-native-verified-loop-design",
            "check.native-controller-core-provider-free",
        ): 38,
    }
    cycle = accepted.get((hypothesis_id, outcome, next_action, command_id))
    if cycle is None:
        return 2
    root = state_dir()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    runs_path = root / "runs.csv"
    expected_transitions = tuple(accepted.items())
    existing_rows: list[tuple[str, str, str, str]] = []
    if runs_path.exists():
        with runs_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            if next(reader, None) != ["cycle", "hypothesis_id", "outcome", "command_id"]:
                return 2
            for row in reader:
                if len(row) != 4:
                    return 2
                existing_rows.append((row[0], row[1], row[2], row[3]))
    if len(existing_rows) != cycle - 1:
        return 2
    for index, row in enumerate(existing_rows, start=1):
        transition, expected_cycle = expected_transitions[index - 1]
        expected_row = (
            str(index),
            transition[0],
            transition[1],
            transition[3],
        )
        if expected_cycle != index or row != expected_row:
            return 2
    existing = runs_path.exists()
    with runs_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        if not existing:
            writer.writerow(("cycle", "hypothesis_id", "outcome", "command_id"))
        writer.writerow((str(cycle), hypothesis_id, outcome, command_id))
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
    rendered = [
        "# Prime Climb Research Tree",
        "",
        "- H-001: passed — provider-free RLM harness",
    ]
    if cycle == 1:
        rendered.append("- Next: H-002 — real daemon durable read-only recovery")
    else:
        rendered.append("- H-002: passed — real daemon durable read-only recovery")
    if cycle == 2:
        rendered.append("- Next: H-003 — bounded real-model native RLM receipt")
    elif cycle >= 3:
        rendered.append("- H-003: passed — bounded real-model native RLM receipt")
    if cycle == 3:
        rendered.append(
            "- Next: H-004 — Phase 1 Verified-loop gate audit and promotion evidence"
        )
    elif cycle >= 4:
        rendered.append(
            "- H-004: falsified — early prepare conflicts with coordinator ownership"
        )
    if cycle == 4:
        rendered.append(
            "- Next: H-005 — coordinator-owned checkpoint manifest and restored transport"
        )
    elif cycle >= 5:
        rendered.append(
            "- H-005: passed — coordinator-owned checkpoint manifest and restored transport"
        )
    if cycle == 5:
        rendered.append("- Next: H-006 — bounded session/context model evidence")
    elif cycle >= 6:
        rendered.append("- H-006: passed — bounded session/context model evidence")
    if cycle == 6:
        rendered.append("- Next: H-007 — Phase 2 session/context closure audit")
    elif cycle >= 7:
        rendered.append("- H-007: passed — Phase 2 session/context closure audit")
    if cycle == 7:
        rendered.append("- Next: H-008 — provider-free RLM evidence promotion")
    elif cycle >= 8:
        rendered.append("- H-008: passed — provider-free RLM evidence promotion")
    if cycle == 8:
        rendered.append("- Next: H-009 — bounded RLM model evidence promotion")
    elif cycle >= 9:
        rendered.append(
            "- H-009: falsified — Phase 1 receipt lacks exact RLM model assertions"
        )
    if cycle == 9:
        rendered.append("- Next: H-010 — exact bounded RLM model assertions")
    elif cycle >= 10:
        rendered.extend(
            (
                "- H-010: passed — exact bounded RLM model assertions",
            )
        )
    if cycle == 10:
        rendered.append("- Next: H-011 — operation/long-running closure inventory")
    elif cycle >= 11:
        rendered.append(
            "- H-011: passed — operation/long-running closure inventory"
        )
    if cycle == 11:
        rendered.append(
            "- Next: H-012 — exact long-running scenario matrix and Phase 1 promotion"
        )
    elif cycle >= 12:
        rendered.append(
            "- H-012: passed — exact long-running scenario matrix and Phase 1 promotion"
        )
    if cycle == 12:
        rendered.append(
            "- Next: H-013 — host-owned heartbeat and schedule coordinator"
        )
    elif cycle >= 13:
        rendered.append(
            "- H-013: passed — host-owned heartbeat and schedule coordinator"
        )
    if cycle == 13:
        rendered.append(
            "- Next: H-014 — pinned Prime heartbeat command translation"
        )
    elif cycle >= 14:
        rendered.append(
            "- H-014: passed — pinned Prime heartbeat command translation"
        )
    if cycle == 14:
        rendered.append(
            "- Next: H-015 — durable Prime heartbeat command fencing"
        )
    elif cycle >= 15:
        rendered.append(
            "- H-015: passed — durable Prime heartbeat command fencing"
        )
    if cycle == 15:
        rendered.append(
            "- Next: H-016 — Prime heartbeat session and private IPC bridge"
        )
    elif cycle >= 16:
        rendered.append(
            "- H-016: passed — Prime heartbeat session and private IPC bridge"
        )
    if cycle == 16:
        rendered.append("- Next: H-017 — selected-provider long-running binding")
    elif cycle >= 17:
        rendered.append("- H-017: passed — selected-provider long-running binding")
    if cycle == 17:
        rendered.append("- Next: H-018 — residency recovery and orphan audit")
    elif cycle >= 18:
        rendered.append("- H-018: passed — residency recovery and orphan audit")
    if cycle == 18:
        rendered.append(
            "- Next: H-019 — finite autonomous-quality evidence boundary"
        )
    elif cycle >= 19:
        rendered.append(
            "- H-019: passed — finite autonomous-quality evidence boundary"
        )
    if cycle == 19:
        rendered.append("- Next: H-020 — authorized bounded autonomous-quality run")
    elif cycle >= 20:
        rendered.append(
            "- H-020: passed — authorized bounded autonomous-quality run"
        )
    if cycle == 20:
        rendered.append(
            "- Next: H-021 — provider-free long-running evidence promotion"
        )
    elif cycle >= 21:
        rendered.append(
            "- H-021: passed — provider-free long-running evidence promotion"
        )
    if cycle == 21:
        rendered.append("- Next: H-022 — operation long-running closure gates")
    elif cycle >= 22:
        rendered.append("- H-022: passed — operation long-running closure gates")
    if cycle == 22:
        rendered.append("- Next: H-023 — continual harness closure inventory")
    elif cycle >= 23:
        rendered.append("- H-023: passed — continual harness closure gates")
    if cycle == 23:
        rendered.append("- Next: H-024 — ecosystem capabilities closure inventory")
    elif cycle >= 24:
        rendered.append("- H-024: passed — ecosystem capabilities closure inventory")
    if cycle == 24:
        rendered.append("- Next: H-025 — closed ecosystem portfolio contracts")
    elif cycle >= 25:
        rendered.append("- H-025: passed — closed ecosystem portfolio contracts")
    if cycle == 25:
        rendered.append("- Next: H-026 — exact materialization and cleanup")
    elif cycle >= 26:
        rendered.append("- H-026: passed — exact materialization and cleanup")
    if cycle == 26:
        rendered.append("- Next: H-027 — selected Prime adapter and host preflight")
    elif cycle >= 27:
        rendered.append("- H-027: passed — selected Prime adapter and host preflight")
    if cycle == 27:
        rendered.append("- Next: H-028 — Gateway frame and lifecycle fencing")
    elif cycle >= 28:
        rendered.append("- H-028: passed — Gateway frame and lifecycle fencing")
    if cycle == 28:
        rendered.append("- Next: H-029 — pinned Prime module bundle")
    elif cycle >= 29:
        rendered.append("- H-029: passed — pinned Prime module bundle")
    if cycle == 29:
        rendered.append("- Next: H-030 — resource evidence package")
    elif cycle >= 30:
        rendered.append("- H-030: passed — resource evidence package")
    if cycle == 30:
        rendered.append("- Next: H-031 — extension evidence package")
    elif cycle >= 31:
        rendered.append("- H-031: passed — extension evidence package")
    if cycle == 31:
        rendered.append("- Next: H-032 — exact package evidence")
    elif cycle >= 32:
        rendered.append("- H-032: passed — exact package evidence")
    if cycle == 32:
        rendered.append("- Next: H-033 — local MCP evidence")
    elif cycle >= 33:
        rendered.append("- H-033: passed — local MCP evidence")
    if cycle == 33:
        rendered.append("- Next: H-034 — ecosystem closure gates")
    elif cycle == 34:
        rendered.extend(
            (
                "- H-034: passed — ecosystem closure gates",
                "- Next: H-035 — client interface closure inventory",
            )
        )
    elif cycle == 35:
        rendered.extend(
            (
                "- H-034: passed — ecosystem closure gates",
                "- H-035: passed — client interface closure gates",
                "- Next: H-036 — operational surface inventory",
            )
        )
    elif cycle == 36:
        rendered.extend(
            (
                "- H-034: passed — ecosystem closure gates",
                "- H-035: passed — client interface closure gates",
                "- H-036: passed — operational surface closure gates",
                "- Future: separately approved hypothesis required",
            )
        )
    elif cycle == 37:
        rendered.extend(
            (
                "- H-034: passed — ecosystem closure gates",
                "- H-035: passed — client interface closure gates",
                "- H-036: passed — operational surface closure gates",
                "- H-037: passed — Prime system parity production callback",
                "- Next: H-038 — Native durable controller core",
            )
        )
    elif cycle >= 38:
        rendered.extend(
            (
                "- H-034: passed — ecosystem closure gates",
                "- H-035: passed — client interface closure gates",
                "- H-036: passed — operational surface closure gates",
                "- H-037: passed — Prime system parity production callback",
                "- H-038: passed — Native durable controller core",
                "- Next: Phase 3.2 — Native Verified-loop",
            )
        )
    (root / "research-tree.md").write_text(
        "\n".join(rendered) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
