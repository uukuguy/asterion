from __future__ import annotations

import io
import json
import unittest
from unittest import mock

from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource
from asterion.cli import main as asterion_main


class DefaultBenchmarkHostTests(unittest.TestCase):
    def test_installed_cli_plans_builtin_suite_without_execution_authority(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch.object(
            BuiltinCapabilitySource,
            "load_provider",
            side_effect=AssertionError("implementation provider loaded"),
        ):
            code = asterion_main(
                [
                    "benchmark",
                    "plan",
                    "--application",
                    "code.quality@1.0.0",
                    "--suite",
                    "controlled-code.conformance@1.0.0",
                ],
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(code, 0, stderr.getvalue())
        plan = json.loads(stdout.getvalue())
        self.assertEqual(plan["application"], "code.quality@1.0.0")
        self.assertEqual(plan["suite"], "controlled-code.conformance@1.0.0")
        self.assertEqual(plan["case_limit"], 1)
        self.assertEqual(
            plan["tasks"],
            [
                {
                    "binding_id": "controlled-code.conformance",
                    "capability": "workflow.code-quality@1.0.0",
                    "ordinal": 1,
                    "task_id": "controlled-code.conformance",
                }
            ],
        )
        self.assertEqual(stderr.getvalue(), "")

    def test_installed_cli_run_remains_unavailable_without_external_authority(
        self,
    ) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = asterion_main(
            [
                "benchmark",
                "run",
                "--application",
                "code.quality@1.0.0",
                "--suite",
                "controlled-code.conformance@1.0.0",
                "--execute",
                "--capability-source-lock",
                "missing.lock.json",
                "--evidence-root",
                "evidence",
            ],
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn("missing.lock.json", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
