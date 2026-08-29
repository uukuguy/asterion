from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestPrimeClimb(unittest.TestCase):
    def test_h001_cycle_records_safe_provider_free_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary) / "climb"
            completed = subprocess.run(
                [str(ROOT / "tools" / "climb" / "cycle.sh"), "H-001"],
                cwd=ROOT,
                env={**os.environ, "ASTERION_CLIMB_STATE_DIR": str(state_dir)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            rendered = completed.stdout + completed.stderr
            self.assertNotIn("PRIVATE", rendered)
            self.assertNotIn("SECRET", rendered)
            state = json.loads((state_dir / "session-state.json").read_text())
            self.assertEqual(
                state,
                {
                    "last_hypothesis": "H-001",
                    "last_outcome": "passed",
                    "next_action": "H-002",
                },
            )
            rows = (state_dir / "runs.csv").read_text().splitlines()
            self.assertEqual(
                rows,
                [
                    "cycle,hypothesis_id,outcome,command_id",
                    "1,H-001,passed,test.prime-rlm.provider-free",
                ],
            )

    def test_verified_phase_transitions_render_the_current_successor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary) / "climb"
            environment = {
                **os.environ,
                "ASTERION_CLIMB_STATE_DIR": str(state_dir),
            }
            transitions = (
                (
                    "H-004",
                    "falsified",
                    "H-005",
                    "make.prime-native-rlm-bounded",
                ),
                (
                    "H-005",
                    "passed",
                    "H-006",
                    "make.prime-native-rlm-bounded",
                ),
                (
                    "H-006",
                    "passed",
                    "H-007",
                    "test.prime-session-context-parity.bounded",
                ),
                (
                    "H-007",
                    "passed",
                    "H-008",
                    "check.phase2-session-context-closure",
                ),
                (
                    "H-008",
                    "passed",
                    "H-009",
                    "test.prime-rlm-spawn-admission.provider-free",
                ),
                (
                    "H-009",
                    "falsified",
                    "H-010",
                    "audit.prime-native-rlm-bounded-receipt",
                ),
                (
                    "H-010",
                    "passed",
                    "H-011",
                    "check.rlm-programmatic-closure",
                ),
                (
                    "H-011",
                    "passed",
                    "H-012",
                    "check.operation-long-running-inventory",
                ),
                (
                    "H-012",
                    "passed",
                    "H-013",
                    "test.prime-long-running-matrix.provider-free",
                ),
                (
                    "H-013",
                    "passed",
                    "H-014",
                    "test.control-long-running.provider-free",
                ),
                (
                    "H-014",
                    "passed",
                    "H-015",
                    "test.prime-heartbeat-wire.provider-free",
                ),
                (
                    "H-015",
                    "passed",
                    "H-016",
                    "test.prime-heartbeat-fencing.provider-free",
                ),
                (
                    "H-016",
                    "passed",
                    "H-017",
                    "test.prime-heartbeat-ipc.provider-free",
                ),
                (
                    "H-017",
                    "passed",
                    "H-018",
                    "test.prime-long-running-binding.provider-free",
                ),
                (
                    "H-018",
                    "passed",
                    "H-019",
                    "test.prime-residency-recovery.provider-free",
                ),
                (
                    "H-019",
                    "passed",
                    "H-020",
                    "test.prime-long-running-authority.provider-free",
                ),
                (
                    "H-020",
                    "passed",
                    "H-021",
                    "test.prime-long-running.bounded",
                ),
                (
                    "H-021",
                    "passed",
                    "H-022",
                    "test.prime-long-running.provider-free",
                ),
                (
                    "H-022",
                    "passed",
                    "H-023",
                    "check.operation-long-running-closure",
                ),
            )
            for transition in transitions:
                completed = subprocess.run(
                    [
                        "python3",
                        str(ROOT / "tools" / "climb" / "regen-tree.py"),
                        *transition,
                    ],
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

            self.assertEqual(
                json.loads((state_dir / "session-state.json").read_text()),
                {
                    "last_hypothesis": "H-022",
                    "last_outcome": "passed",
                    "next_action": "H-023",
                },
            )
            self.assertEqual(
                (state_dir / "runs.csv").read_text().splitlines(),
                [
                    "cycle,hypothesis_id,outcome,command_id",
                    "4,H-004,falsified,make.prime-native-rlm-bounded",
                    "5,H-005,passed,make.prime-native-rlm-bounded",
                    "6,H-006,passed,test.prime-session-context-parity.bounded",
                    "7,H-007,passed,check.phase2-session-context-closure",
                    "8,H-008,passed,test.prime-rlm-spawn-admission.provider-free",
                    "9,H-009,falsified,audit.prime-native-rlm-bounded-receipt",
                    "10,H-010,passed,check.rlm-programmatic-closure",
                    "11,H-011,passed,check.operation-long-running-inventory",
                    "12,H-012,passed,test.prime-long-running-matrix.provider-free",
                    "13,H-013,passed,test.control-long-running.provider-free",
                    "14,H-014,passed,test.prime-heartbeat-wire.provider-free",
                    "15,H-015,passed,test.prime-heartbeat-fencing.provider-free",
                    "16,H-016,passed,test.prime-heartbeat-ipc.provider-free",
                    "17,H-017,passed,test.prime-long-running-binding.provider-free",
                    "18,H-018,passed,test.prime-residency-recovery.provider-free",
                    "19,H-019,passed,test.prime-long-running-authority.provider-free",
                    "20,H-020,passed,test.prime-long-running.bounded",
                    "21,H-021,passed,test.prime-long-running.provider-free",
                    "22,H-022,passed,check.operation-long-running-closure",
                ],
            )
            tree = (state_dir / "research-tree.md").read_text()
            self.assertIn(
                "H-006: passed — bounded session/context model evidence",
                tree,
            )
            self.assertIn(
                "H-007: passed — Phase 2 session/context closure audit",
                tree,
            )
            self.assertIn(
                "H-008: passed — provider-free RLM evidence promotion",
                tree,
            )
            self.assertIn(
                "H-009: falsified — Phase 1 receipt lacks exact RLM model assertions",
                tree,
            )
            self.assertIn(
                "H-010: passed — exact bounded RLM model assertions",
                tree,
            )
            self.assertIn(
                "H-011: passed — operation/long-running closure inventory",
                tree,
            )
            self.assertIn(
                "H-012: passed — exact long-running scenario matrix and Phase 1 promotion",
                tree,
            )
            self.assertIn(
                "H-013: passed — host-owned heartbeat and schedule coordinator",
                tree,
            )
            self.assertIn(
                "H-014: passed — pinned Prime heartbeat command translation",
                tree,
            )
            self.assertIn(
                "H-015: passed — durable Prime heartbeat command fencing",
                tree,
            )
            self.assertIn(
                "H-016: passed — Prime heartbeat session and private IPC bridge",
                tree,
            )
            self.assertIn(
                "H-017: passed — selected-provider long-running binding",
                tree,
            )
            self.assertIn(
                "H-018: passed — residency recovery and orphan audit",
                tree,
            )
            self.assertIn(
                "H-019: passed — finite autonomous-quality evidence boundary",
                tree,
            )
            self.assertIn(
                "H-020: passed — authorized bounded autonomous-quality run",
                tree,
            )
            self.assertIn(
                "H-021: passed — provider-free long-running evidence promotion",
                tree,
            )
            self.assertIn(
                "H-022: passed — operation long-running closure gates",
                tree,
            )
            self.assertIn(
                "Next: H-023 — continual harness closure inventory",
                tree,
            )


if __name__ == "__main__":
    unittest.main()
