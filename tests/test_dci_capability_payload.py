from __future__ import annotations

import json
import unittest
from pathlib import Path

from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import (
    BenchmarkSuiteRef,
    CapabilityPackageRef,
)


PROJECT = Path(__file__).resolve().parents[1]
PAYLOAD = PROJECT / "src/asterion/capabilities/dci/payload"

GITHUB_TASKS = (
    "bcplus.level3",
    "bcplus.main",
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
    "qa.2wikimultihopqa",
    "qa.bamboogle.github-sample50",
    "qa.hotpotqa",
    "qa.musique",
    "qa.nq",
    "qa.triviaqa",
)
PAPER_MAIN_TASKS = (
    "bcplus.main",
    "beir.arguana",
    "beir.scifact",
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
    "qa.2wikimultihopqa",
    "qa.bamboogle.paper-full125",
    "qa.hotpotqa",
    "qa.musique",
    "qa.nq",
    "qa.triviaqa",
)
ALL_TASKS = tuple(sorted(set(GITHUB_TASKS) | set(PAPER_MAIN_TASKS)))
CAPABILITIES = (
    CapabilityRef("dci.analysis", "1.0.0"),
    CapabilityRef("dci.benchmark", "1.0.0"),
    CapabilityRef("dci.evaluation", "1.0.0"),
    CapabilityRef("dci.export", "1.0.0"),
    CapabilityRef("dci.research", "1.0.0"),
    CapabilityRef("policy.local-corpus", "1.0.0"),
    CapabilityRef("protocol.observability", "1.0.0"),
)
SUITES = (
    BenchmarkSuiteRef("dci.all", "1.0.0"),
    BenchmarkSuiteRef("dci.github", "1.0.0"),
    BenchmarkSuiteRef("dci.paper-main", "1.0.0"),
)


def _document(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


class DciCapabilityPayloadTests(unittest.TestCase):
    def test_declares_the_complete_authority_free_portable_payload(self) -> None:
        payload = open_portable_payload(PAYLOAD)

        self.assertEqual(
            payload.manifest.package_ref,
            CapabilityPackageRef("dci", "1.0.0"),
        )
        self.assertEqual(payload.manifest.capabilities, CAPABILITIES)
        self.assertEqual(payload.manifest.benchmark_suites, SUITES)
        self.assertEqual(payload.manifest.resources, ())
        self.assertRegex(payload.payload_sha256, r"^[0-9a-f]{64}$")
        self.assertTrue((PAYLOAD / "conformance/profile.json").is_file())

        expected_members = {
            "capability-package.json",
            "conformance/profile.json",
            "capabilities/dci-analysis.json",
            "capabilities/dci-benchmark.json",
            "capabilities/dci-evaluation.json",
            "capabilities/dci-export.json",
            "capabilities/dci-research.json",
            "capabilities/local-corpus-policy.json",
            "capabilities/protocol-observability.json",
            "benchmark-suites/all.json",
            "benchmark-suites/github.json",
            "benchmark-suites/paper-main.json",
        }
        actual_members = {
            path.relative_to(PAYLOAD).as_posix()
            for path in PAYLOAD.rglob("*")
            if path.is_file() and path.name != "__init__.py"
        }
        self.assertEqual(actual_members, expected_members)

    def test_suites_declare_exact_task_sets_and_distinct_bamboogle_notes(
        self,
    ) -> None:
        expected = {
            "github.json": GITHUB_TASKS,
            "paper-main.json": PAPER_MAIN_TASKS,
            "all.json": ALL_TASKS,
        }
        bamboogle_notes: dict[str, str] = {}
        for name, task_ids in expected.items():
            with self.subTest(suite=name):
                suite = _document(PAYLOAD / "benchmark-suites" / name)
                self.assertEqual(
                    suite["protocol"], "asterion.benchmark-suite/v1"
                )
                self.assertEqual(
                    suite["owner_package"],
                    {"package_id": "dci", "version": "1.0.0"},
                )
                tasks = suite["tasks"]
                assert isinstance(tasks, list)
                self.assertEqual(
                    tuple(task["task_id"] for task in tasks), task_ids
                )
                self.assertTrue(
                    all(
                        task["capability"]
                        == {
                            "capability_id": "dci.benchmark",
                            "version": "1.0.0",
                        }
                        for task in tasks
                    )
                )
                self.assertEqual(
                    tuple(task["binding_id"] for task in tasks), task_ids
                )
                for task in tasks:
                    task_id = task["task_id"]
                    note = task["note"]
                    if isinstance(task_id, str) and isinstance(note, str):
                        if task_id.startswith("qa.bamboogle."):
                            bamboogle_notes[task_id] = note
        self.assertEqual(
            set(bamboogle_notes),
            {
                "qa.bamboogle.github-sample50",
                "qa.bamboogle.paper-full125",
            },
        )
        self.assertNotEqual(*bamboogle_notes.values())

    def test_payload_documents_use_only_public_protocol_data(self) -> None:
        forbidden = (
            "scripts/",
            ".env",
            "dataset_path",
            "corpus_path",
            "prompt",
            "provider",
            "/private/dci-sentinel",
        )
        documents = tuple(PAYLOAD.rglob("*.json"))
        self.assertTrue(documents)
        for path in documents:
            with self.subTest(path=path.relative_to(PAYLOAD)):
                text = path.read_text(encoding="utf-8")
                for forbidden_value in forbidden:
                    self.assertNotIn(forbidden_value, text)
                value = _document(path)
                if path.parent.name == "capabilities":
                    self.assertEqual(
                        value["protocol"], "asterion.capability/v1"
                    )


if __name__ == "__main__":
    unittest.main()
