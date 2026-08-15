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


if __name__ == "__main__":
    unittest.main()
