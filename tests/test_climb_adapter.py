from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


class ClimbAdapterTests(unittest.TestCase):
    def test_state_tools_use_only_project_dependencies(self) -> None:
        result = subprocess.run(
            [sys.executable, "tools/climb/sync-state.py", "--help"],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_run_ledger_uses_deterministic_lf_lines(self) -> None:
        runs = (PROJECT / "docs/status/climb/runs.csv").read_bytes()

        self.assertNotIn(b"\r\n", runs)


if __name__ == "__main__":
    unittest.main()
