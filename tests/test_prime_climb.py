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

    def test_h035_closure_records_exact_transition_and_contiguous_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary) / "climb"
            state_dir.mkdir()
            (state_dir / "runs.csv").write_text(
                "\n".join(
                    (ROOT / "docs" / "status" / "climb" / "runs.csv")
                    .read_text()
                    .splitlines()[:35]
                )
                + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "python3",
                    str(ROOT / "tools" / "climb" / "regen-tree.py"),
                    "H-035",
                    "passed",
                    "H-036",
                    "check.client-interfaces-closure",
                ],
                cwd=ROOT,
                env={**os.environ, "ASTERION_CLIMB_STATE_DIR": str(state_dir)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                json.loads((state_dir / "session-state.json").read_text()),
                {
                    "last_hypothesis": "H-035",
                    "last_outcome": "passed",
                    "next_action": "H-036",
                },
            )
            rows = (state_dir / "runs.csv").read_text().splitlines()
            self.assertEqual(
                rows[-1],
                "35,H-035,passed,check.client-interfaces-closure",
            )
            self.assertEqual(
                [int(row.split(",", 1)[0]) for row in rows[1:]],
                list(range(1, 36)),
            )
            self.assertIn(
                "- H-035: passed — client interface closure gates",
                (state_dir / "research-tree.md").read_text(),
            )
            self.assertIn(
                "- Next: H-036 — operational surface inventory",
                (state_dir / "research-tree.md").read_text(),
            )

    def test_h035_transition_rejects_noncanonical_existing_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary) / "climb"
            state_dir.mkdir()
            (state_dir / "runs.csv").write_text(
                "cycle,hypothesis_id,outcome,command_id\n"
                "34,H-034,passed,check.ecosystem-capabilities-closure\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "python3",
                    str(ROOT / "tools" / "climb" / "regen-tree.py"),
                    "H-035",
                    "passed",
                    "H-036",
                    "check.client-interfaces-closure",
                ],
                cwd=ROOT,
                env={**os.environ, "ASTERION_CLIMB_STATE_DIR": str(state_dir)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)

    def test_h035_handoff_declares_exact_pending_h036_inventory(self) -> None:
        hypotheses = (ROOT / "docs" / "status" / "climb" / "hypotheses.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "- id: H-035\n"
            "  description: client interface closure inventory identifies exact shared-stream evidence packages\n"
            "  parent_paradigm: interface-clients\n"
            "  ranking: 0.7\n"
            "  status: passed\n",
            hypotheses,
        )
        self.assertIn(
            "- id: H-036\n"
            "  description: operational surface inventory identifies six host-owned authority packages\n"
            "  parent_paradigm: interface-operations\n"
            "  ranking: 0.7\n"
            "  status: pending\n",
            hypotheses,
        )


if __name__ == "__main__":
    unittest.main()
