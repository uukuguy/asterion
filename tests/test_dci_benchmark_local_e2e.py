from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from asterion.applications.dci_agent_lite.cli import main


class DciBenchmarkLocalE2ETests(unittest.TestCase):
    def test_installed_command_runs_and_resumes_all_fixture_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            lock = root / "source-lock.json"
            evidence = root / "evidence"
            self.assertEqual(
                main(
                    [
                        "benchmark",
                        "lock",
                        "--instance",
                        "dci.local-fixture@1.0.0",
                        "--output",
                        str(lock),
                    ],
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                0,
            )
            run_stdout = io.StringIO()
            run_stderr = io.StringIO()
            run_code = main(
                [
                    "benchmark",
                    "run",
                    "--instance",
                    "dci.local-fixture@1.0.0",
                    "--case-limit",
                    "1",
                    "--capability-source-lock",
                    str(lock),
                    "--evidence-root",
                    str(evidence),
                    "--execute",
                ],
                stdout=run_stdout,
                stderr=run_stderr,
            )
            run = json.loads(run_stdout.getvalue())
            progress = tuple(
                (evidence / "runs" / run["run_id"] / "progress").glob("*.json")
            )
            resume_stdout = io.StringIO()
            resume_code = main(
                [
                    "benchmark",
                    "resume",
                    "--instance",
                    "dci.local-fixture@1.0.0",
                    "--run-id",
                    run["run_id"],
                    "--case-limit",
                    "1",
                    "--capability-source-lock",
                    str(lock),
                    "--evidence-root",
                    str(evidence),
                    "--execute",
                ],
                stdout=resume_stdout,
                stderr=io.StringIO(),
            )

            self.assertEqual(run_code, 0, run_stderr.getvalue())
            self.assertEqual(run["status"], "completed")
            self.assertEqual(len(run["tasks"]), 15)
            self.assertTrue(
                all(
                    task["status"] == "completed"
                    and task["case_count"] == 1
                    for task in run["tasks"]
                )
            )
            self.assertEqual(resume_code, 0)
            self.assertEqual(json.loads(resume_stdout.getvalue()), run)
            self.assertEqual(
                tuple(
                    (evidence / "runs" / run["run_id"] / "progress").glob(
                        "*.json"
                    )
                ),
                progress,
            )


if __name__ == "__main__":
    unittest.main()
