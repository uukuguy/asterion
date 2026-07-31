from __future__ import annotations

import io
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from asterion.applications.dci_agent_lite.cli import main
from asterion.applications.dci_agent_lite.benchmark_instances import (
    DciBenchmarkInstanceError,
    benchmark_instances,
    public_instance_dict,
    resolve_case_limit,
    select_benchmark_instance,
)


EXPECTED_SELECTORS = (
    "dci.bcplus.level3@1.0.0",
    "dci.bcplus.main@1.0.0",
    "dci.beir.arguana@1.0.0",
    "dci.beir.scifact@1.0.0",
    "dci.bright.biology@1.0.0",
    "dci.bright.earth-science@1.0.0",
    "dci.bright.economics@1.0.0",
    "dci.bright.robotics@1.0.0",
    "dci.local-fixture@1.0.0",
    "dci.qa.2wikimultihopqa@1.0.0",
    "dci.qa.bamboogle@1.0.0",
    "dci.qa.hotpotqa@1.0.0",
    "dci.qa.musique@1.0.0",
    "dci.qa.nq@1.0.0",
    "dci.qa.triviaqa@1.0.0",
)
PROJECT = Path(__file__).resolve().parents[1]
RUNBOOK = PROJECT / "docs/status/DCI-BENCHMARK-INSTANCES.md"


class TestDciBenchmarkInstances(unittest.TestCase):
    def test_instance_runbooks_match_implemented_catalog_entries(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        implemented = {
            instance.selector
            for instance in benchmark_instances()
            if instance.implementation_state == "implemented"
        }
        planned = {
            instance.selector
            for instance in benchmark_instances()
            if instance.implementation_state == "planned"
        }

        for selector in implemented:
            with self.subTest(selector=selector):
                self.assertIn(f"## 运行手册：`{selector}`", text)
        for selector in planned:
            with self.subTest(selector=selector):
                self.assertNotIn(f"## 运行手册：`{selector}`", text)
        self.assertIn("# DCI Benchmark 实例", text)
        self.assertIn("## 如何使用本文档", text)
        self.assertIn("### 当前 50 条阶段性评估", text)
        self.assertIn('export DCI_RUN_ROOT="$PWD/outputs/manual/', text)
        self.assertIn(
            'export DCI_RUN_ID="$(jq -er \'.run_id\' "$DCI_RUN_RESULT")"',
            text,
        )
        self.assertGreaterEqual(text.count("--all-cases"), 1)
        self.assertIn("不产生原 DCI benchmark 评估分数", text)
        self.assertIn("尚未实现", text)
        self.assertIn(
            "| `dci.qa.bamboogle@1.0.0` "
            "| implemented / Verified-bounded | 50/125 | 82%（41/50） |",
            text,
        )
        self.assertIn(
            "## 运行手册：`dci.qa.bamboogle@1.0.0`",
            text,
        )
        self.assertIn("50/125 的阶段性结果", text)
        self.assertIn("41/50", text)
        self.assertIn("82%", text)
        self.assertNotRegex(text, r"--run-id\s+run-[0-9a-f]{32}")
        self.assertNotRegex(
            text,
            r"--(?:capability-source-lock|evidence-root)\s+FRESH_",
        )

    def test_catalog_is_canonical_immutable_and_complete(self) -> None:
        instances = benchmark_instances()

        self.assertEqual(
            tuple(instance.selector for instance in instances),
            EXPECTED_SELECTORS,
        )
        self.assertEqual(len({instance.selector for instance in instances}), 15)
        with self.assertRaises(FrozenInstanceError):
            instances[0].version = "2.0.0"  # type: ignore[misc]

    def test_local_bamboogle_and_bcplus_are_the_implemented_instances(self) -> None:
        implemented = tuple(
            instance.selector
            for instance in benchmark_instances()
            if instance.implementation_state == "implemented"
        )

        self.assertEqual(
            implemented,
            (
                "dci.bcplus.level3@1.0.0",
                "dci.local-fixture@1.0.0",
                "dci.qa.bamboogle@1.0.0",
            ),
        )
        local = select_benchmark_instance("dci.local-fixture@1.0.0")
        self.assertEqual(local.application_ref.selector, "dci.local-benchmark-application@1.0.0")
        self.assertEqual(local.suite_ref.suite_id, "dci.all")
        self.assertEqual(len(local.task_ids), 15)
        self.assertEqual(local.executor_profile, "local-fixture")

    def test_bamboogle_resolves_default_bounded_and_all_case_ranges(self) -> None:
        instance = select_benchmark_instance(
            "dci.qa.bamboogle@1.0.0"
        )

        self.assertEqual(resolve_case_limit(instance, case_limit=None, all_cases=False), 1)
        self.assertEqual(resolve_case_limit(instance, case_limit=7, all_cases=False), 7)
        self.assertEqual(resolve_case_limit(instance, case_limit=None, all_cases=True), 125)
        self.assertEqual(instance.task_ids, ("qa.bamboogle.paper-full125",))

    def test_paper_full125_is_implemented_with_bounded_and_full_ranges(self) -> None:
        instance = select_benchmark_instance(
            "dci.qa.bamboogle@1.0.0"
        )

        self.assertEqual(instance.implementation_state, "implemented")
        self.assertEqual(
            resolve_case_limit(instance, case_limit=50, all_cases=False),
            50,
        )
        self.assertEqual(
            resolve_case_limit(instance, case_limit=None, all_cases=True),
            125,
        )
        self.assertEqual(instance.task_ids, ("qa.bamboogle.paper-full125",))

    def test_bcplus_level3_is_implemented_with_bounded_and_full_ranges(self) -> None:
        instance = select_benchmark_instance("dci.bcplus.level3@1.0.0")

        self.assertEqual(instance.implementation_state, "implemented")
        self.assertEqual(resolve_case_limit(instance, case_limit=50, all_cases=False), 50)
        self.assertEqual(resolve_case_limit(instance, case_limit=None, all_cases=True), 830)
        self.assertEqual(instance.task_ids, ("bcplus.level3",))

    def test_invalid_selection_and_ranges_fail_closed(self) -> None:
        instance = select_benchmark_instance("dci.local-fixture@1.0.0")
        for selector in (
            "",
            "dci.local-fixture",
            "dci.local-fixture@2.0.0",
            "dci.unknown@1.0.0",
        ):
            with self.subTest(selector=selector), self.assertRaises(
                DciBenchmarkInstanceError
            ):
                select_benchmark_instance(selector)
        for case_limit, all_cases in ((0, False), (-1, False), (True, False), (1, True)):
            with self.subTest(case_limit=case_limit, all_cases=all_cases), self.assertRaises(
                DciBenchmarkInstanceError
            ):
                resolve_case_limit(
                    instance,
                    case_limit=case_limit,
                    all_cases=all_cases,
                )
        with self.assertRaises(DciBenchmarkInstanceError):
            resolve_case_limit(instance, case_limit=None, all_cases=True)

    def test_public_projection_is_body_free(self) -> None:
        sentinel = "secret-prompt-answer-private-path"
        instance = select_benchmark_instance(
            "dci.qa.bamboogle@1.0.0"
        )

        rendered = json.dumps(public_instance_dict(instance), sort_keys=True)

        self.assertNotIn(sentinel, rendered)
        self.assertNotIn("dataset", rendered)
        self.assertNotIn("corpus", rendered)
        self.assertNotIn("credential", rendered)
        self.assertNotIn("prompt", repr(instance))

    def test_bamboogle_default_and_all_case_plans_use_product_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "source-lock.json"
            self.assertEqual(
                main(
                    [
                        "benchmark",
                        "lock",
                        "--instance",
                        "dci.qa.bamboogle@1.0.0",
                        "--output",
                        str(lock),
                    ],
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                0,
            )
            default_stdout = io.StringIO()
            default_stderr = io.StringIO()
            default_code = main(
                [
                    "benchmark",
                    "plan",
                    "--instance",
                    "dci.qa.bamboogle@1.0.0",
                    "--capability-source-lock",
                    str(lock),
                ],
                stdout=default_stdout,
                stderr=default_stderr,
            )

            all_stdout = io.StringIO()
            all_stderr = io.StringIO()
            all_code = main(
                [
                    "benchmark",
                    "plan",
                    "--instance",
                    "dci.qa.bamboogle@1.0.0",
                    "--all-cases",
                    "--capability-source-lock",
                    str(lock),
                ],
                stdout=all_stdout,
                stderr=all_stderr,
            )

            self.assertEqual(default_code, 0, default_stderr.getvalue())
            self.assertEqual(json.loads(default_stdout.getvalue())["case_limit"], 1)
            self.assertEqual(all_code, 0, all_stderr.getvalue())
            self.assertEqual(json.loads(all_stdout.getvalue())["case_limit"], 125)


if __name__ == "__main__":
    unittest.main()
