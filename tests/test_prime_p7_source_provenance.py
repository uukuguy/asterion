"""Source ancestry remains complete beyond repeated resume depth."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7 import solution_certificates as cert


class TestSourceProvenance(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def source(self, name, links=()):
        run = self.root / name
        (run / "trace").mkdir(parents=True)
        (run / "summary.json").write_text(
            json.dumps(
                {
                    "diagnostics": {
                        "route_sources": [{"source_run_id": link} for link in links]
                    }
                }
            )
        )
        (run / "trace" / "prime-trace.jsonl").write_text("{}\n")
        return run

    def expected(self, names):
        stamps = []
        for name in names:
            for suffix in ("summary.json", "trace/prime-trace.jsonl"):
                path = self.root / name / suffix
                stamps.append((str(path.relative_to(self.root)), cert._file_hash(path)))
        return cert._digest(stamps)

    def test_ten_source_chain_retains_every_ancestor(self):
        for index in reversed(range(10)):
            self.source(f"run-{index}", () if index == 9 else (f"run-{index + 1}",))
        run = self.root / "run-0"
        before = cert._source_identity(run, descriptor=True)
        self.assertEqual(
            before["source_identity"], self.expected([f"run-{i}" for i in range(10)])
        )
        self.assertEqual(len(before["files"]), 20)
        self.assertTrue(cert._metadata_matches(self.root, before))
        (self.root / "run-9" / "summary.json").write_text(
            '{"diagnostics":{},"changed":true}'
        )
        self.assertNotEqual(cert._source_identity(run), before["source_identity"])
        self.assertFalse(cert._metadata_matches(self.root, before))

    def test_shared_ancestor_preserves_original_sorted_depth_first_hash_order(self):
        self.source("shared")
        self.source("a", ("shared",))
        self.source("b", ("shared",))
        run = self.source("root", ("b", "a", "a"))
        self.assertEqual(
            cert._source_identity(run), self.expected(["root", "a", "shared", "b"])
        )

    def test_cycle_missing_and_symlink_fail_closed(self):
        with self.subTest(kind="cycle"):
            self.source("a", ("b",))
            self.source("b", ("a",))
            with self.assertRaises(ValueError):
                cert._source_identity(self.root / "a")
        with self.subTest(kind="missing"):
            run = self.source("missing-root", ("absent",))
            with self.assertRaises(ValueError):
                cert._source_identity(run)
        with self.subTest(kind="symlink"):
            (self.root / "link").symlink_to(self.root / "a", target_is_directory=True)
            run = self.source("link-root", ("link",))
            with self.assertRaises(ValueError):
                cert._source_identity(run)

    def test_capacity_is_named_and_redacted(self):
        self.source("private-source-sentinel")
        run = self.source("root", ("private-source-sentinel",))
        with patch.object(cert, "_MAX_SOURCE_NODES", 1):
            with self.assertRaises(cert.SourceProvenanceCapacityError) as raised:
                cert._source_identity(run)
        self.assertEqual(raised.exception.code, "source-provenance-capacity-exceeded")
        self.assertNotIn("private-source-sentinel", str(raised.exception))

    def test_descriptor_file_capacity_is_enforced_during_capture(self):
        run = self.source("root")
        with patch.object(cert, "_MAX_SOURCE_FILES", 1):
            with self.assertRaises(cert.SourceProvenanceCapacityError):
                cert._source_identity(run, descriptor=True)

    def test_recovered_membership_resolves_verified_source_beyond_depth_eight(self):
        game, model = "fixture-game", "fixture-model"
        for index in reversed(range(10)):
            run = self.source(f"recovery-{index}")
            summary = {
                "run_id": run.name,
                "sealed_trace": True,
                "replay_verified": True,
                "cleanup_complete": True,
                "completed_prefix": {"levels_completed": 1},
                "diagnostics": {}
                if index == 9
                else {"recovered_from": f"recovery-{index + 1}"},
            }
            if index == 9:
                summary["experiment"] = {
                    "prediction_variant": "verified",
                    "game_id": game,
                    "model": model,
                    "seed": 0,
                }
                from asterion.applications.prime.p7.score import digest

                scope = {
                    "game_id": game,
                    "seed": 0,
                    "win_levels": 2,
                    "run_id": run.name,
                    "attempt_id": run.name,
                }
                pointer = run / "research" / digest(scope)[7:] / "current.json"
                pointer.parent.mkdir(parents=True)
                pointer.write_text("{}")
            (run / "summary.json").write_text(json.dumps(summary))
        catalog = ({"game_id": game, "win_levels": 2},)
        potential = cert._potential_sources(self.root, catalog, model)
        self.assertIn("recovery-0", potential[game])
        self.assertEqual(len(potential[game]), 10)
        # An ancestor cycle is rejected, not treated as a valid attribution.
        path = self.root / "recovery-9" / "summary.json"
        last = json.loads(path.read_text())
        last.pop("experiment")
        last["diagnostics"] = {"recovered_from": "recovery-0"}
        path.write_text(json.dumps(last))
        self.assertEqual(cert._potential_sources(self.root, catalog, model)[game], [])

    def test_public_reader_preserves_capacity_classification(self):
        with patch.object(
            cert,
            "_read_certified_roster",
            side_effect=cert.SourceProvenanceCapacityError(),
        ):
            with self.assertRaises(cert.SourceProvenanceCapacityError):
                cert.read_certified_roster(
                    self.root, self.root, (), expected_model_id="fixture"
                )

    def test_save_status_preserves_safe_capacity_code_and_stage(self):
        from asterion.applications.prime.p7.operator import _publish_save_certificate

        with patch.object(
            cert,
            "publish_verified_save",
            side_effect=cert.SourceProvenanceCapacityError(),
        ):
            _publish_save_certificate(
                self.root,
                self.root,
                object(),
                expected_model_id="fixture",
                eligible=True,
            )
        value = json.loads(
            (self.root / "solution-certification-status.json").read_text()
        )
        self.assertEqual(value["code"], "source-provenance-capacity-exceeded")
        self.assertEqual(value["stage"], "source-provenance")
        self.assertEqual(value["status"], "pending")


class TestRegistryCapacity(unittest.TestCase):
    from tests.test_prime_p7_solution_certificates import (
        TestP7SolutionCertificates as Fixture,
    )

    setUp = Fixture.setUp
    save = Fixture.save
    certify = Fixture.certify

    def test_registry_capacity_rejects_before_certificate_or_pointer_write(self):
        run = self.save()
        with patch.object(cert, "_MAX_REGISTRY_BYTES", 1):
            with self.assertRaises(cert.SourceProvenanceCapacityError):
                self.certify(run)
        self.assertEqual(
            list((self.runs / "solution-certificates").rglob("*.json")), []
        )


if __name__ == "__main__":
    unittest.main()
