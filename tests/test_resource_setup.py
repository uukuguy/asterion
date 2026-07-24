from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]


class BasicResourceSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.resources = self.root / "resources"
        wiki = self.source / "wiki"
        bcplus = self.source / "browsecomp_plus"
        wiki.mkdir(parents=True)
        bcplus.mkdir(parents=True)
        (wiki / "wiki_dump.jsonl").write_text('{"title":"fixture"}\n')
        (bcplus / "fixture.parquet").write_bytes(b"fixture parquet")

    def test_basic_profile_materializes_both_required_corpora(self) -> None:
        from asterion.dci.resource_setup import prepare_resources

        def fake_export(source: Path, destination: Path) -> int:
            self.assertEqual(source, self.source / "browsecomp_plus")
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "fixture.txt").write_text("fixture\n")
            return 1

        with patch("asterion.dci.resource_setup.export_bcplus", fake_export):
            result = prepare_resources(
                profile="basic",
                resource_root=self.resources,
                source_root=self.source,
            )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.prepared, ("corpus.bc-plus", "corpus.wiki"))
        self.assertTrue(
            (self.resources / "corpus/wiki_corpus/wiki_dump.jsonl").is_file()
        )
        self.assertTrue(
            (self.resources / "corpus/bc_plus_docs/fixture.txt").is_file()
        )

    def test_check_only_reports_missing_without_creating_anything(self) -> None:
        from asterion.dci.resource_setup import prepare_resources

        result = prepare_resources(
            profile="basic",
            resource_root=self.resources,
            source_root=self.source,
            check_only=True,
        )

        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.missing, ("corpus.bc-plus", "corpus.wiki"))
        self.assertFalse(self.resources.exists())

    def test_complete_destinations_are_idempotent_and_not_overwritten(self) -> None:
        from asterion.dci.resource_setup import prepare_resources

        wiki = self.resources / "corpus/wiki_corpus"
        bcplus = self.resources / "corpus/bc_plus_docs"
        wiki.mkdir(parents=True)
        bcplus.mkdir(parents=True)
        (wiki / "keep.txt").write_text("wiki\n")
        (bcplus / "keep.txt").write_text("bc+\n")

        with patch("asterion.dci.resource_setup.export_bcplus") as export:
            result = prepare_resources(
                profile="basic",
                resource_root=self.resources,
                source_root=self.source,
            )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.present, ("corpus.bc-plus", "corpus.wiki"))
        self.assertEqual(result.prepared, ())
        self.assertEqual((wiki / "keep.txt").read_text(), "wiki\n")
        self.assertEqual((bcplus / "keep.txt").read_text(), "bc+\n")
        export.assert_not_called()

    def test_symlinked_resource_root_is_rejected(self) -> None:
        from asterion.dci.resource_setup import ResourceSetupError, prepare_resources

        actual = self.root / "actual"
        actual.mkdir()
        try:
            os.symlink(actual, self.resources)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")

        with self.assertRaisesRegex(ResourceSetupError, "symlink"):
            prepare_resources(
                profile="basic",
                resource_root=self.resources,
                source_root=self.source,
            )

    def test_symlinked_destination_is_rejected(self) -> None:
        from asterion.dci.resource_setup import ResourceSetupError, prepare_resources

        corpus = self.resources / "corpus"
        corpus.mkdir(parents=True)
        outside = self.root / "outside"
        outside.mkdir()
        try:
            os.symlink(outside, corpus / "wiki_corpus")
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")

        with self.assertRaisesRegex(ResourceSetupError, "symlink"):
            prepare_resources(
                profile="basic",
                resource_root=self.resources,
                source_root=self.source,
            )
        self.assertEqual(tuple(outside.iterdir()), ())

    def test_symlink_inside_local_source_is_rejected_without_copying_target(self) -> None:
        from asterion.dci.resource_setup import ResourceSetupError, prepare_resources

        outside = self.root / "outside-secret.txt"
        outside.write_text("SECRET-OUTSIDE\n")
        wiki_file = self.source / "wiki/wiki_dump.jsonl"
        wiki_file.unlink()
        try:
            os.symlink(outside, wiki_file)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        bcplus = self.resources / "corpus/bc_plus_docs"
        bcplus.mkdir(parents=True)
        (bcplus / "ready.txt").write_text("ready\n")

        with self.assertRaisesRegex(ResourceSetupError, "symlink"):
            prepare_resources(
                profile="basic",
                resource_root=self.resources,
                source_root=self.source,
            )

        copied = self.resources / "corpus/wiki_corpus/wiki_dump.jsonl"
        self.assertFalse(copied.exists())

    def test_unknown_profile_fails_without_creating_root(self) -> None:
        from asterion.dci.resource_setup import ResourceSetupError, prepare_resources

        with self.assertRaisesRegex(ResourceSetupError, "profile"):
            prepare_resources(
                profile="large",
                resource_root=self.resources,
                source_root=self.source,
            )
        self.assertFalse(self.resources.exists())

    def test_network_source_symlink_is_rejected(self) -> None:
        from asterion.dci.resource_setup import (
            BASIC_RESOURCES,
            ResourceSetupError,
            _network_source,
        )

        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("SECRET\n")
        staging = self.root / "staging"
        staging.mkdir()

        def fake_download(**kwargs):
            del kwargs
            os.symlink(outside, staging / "wiki")

        fake_huggingface_hub = types.ModuleType("huggingface_hub")
        fake_huggingface_hub.snapshot_download = fake_download
        with (
            patch.dict(sys.modules, {"huggingface_hub": fake_huggingface_hub}),
            self.assertRaisesRegex(ResourceSetupError, "symlink"),
        ):
            _network_source(BASIC_RESOURCES[1], staging)

    def test_cli_check_is_body_free_and_reports_zero_operations(self) -> None:
        completed = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "tools/setup_resources.py",
                "--profile",
                "basic",
                "--resource-root",
                str(self.resources),
                "--source-root",
                str(self.source),
                "--check",
                "--json",
            ],
            cwd=PROJECT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 4, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(payload["provider_backed_operation_count"], 0)
        self.assertEqual(payload["judge_operation_count"], 0)
        self.assertFalse(payload["full_dataset_ran"])
        self.assertNotIn("fixture parquet", completed.stdout + completed.stderr)


class BenchmarkResourceSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_benchmark_profile_covers_packaged_dataset_and_corpus_inventory(self) -> None:
        from importlib import resources

        from asterion.dci.resource_setup import resource_specs

        inventory = json.loads(
            resources.files("asterion.dci")
            .joinpath("resources/paper-benchmarks.json")
            .read_text(encoding="utf-8")
        )
        expected = {
            row[field]
            for row in inventory["datasets"]
            for field in ("dataset_path", "corpus_path")
        }

        self.assertTrue(
            expected.issubset(
                {spec.destination for spec in resource_specs("benchmark")}
            )
        )

    def test_benchmark_profile_also_covers_every_checked_in_launcher_path(self) -> None:
        import re

        from asterion.dci.resource_setup import resource_specs

        launcher_paths = {
            match
            for launcher in (PROJECT / "scripts").rglob("*.sh")
            for match in re.findall(
                r'\$RESOURCE_ROOT/([^";]+)',
                launcher.read_text(encoding="utf-8"),
            )
        }

        self.assertTrue(
            launcher_paths.issubset(
                {spec.destination for spec in resource_specs("benchmark")}
            )
        )

    def test_benchmark_check_reports_exact_paths_and_upstreams(self) -> None:
        from asterion.dci.resource_setup import prepare_resources

        result = prepare_resources(
            profile="benchmark",
            resource_root=self.root / "resources",
            check_only=True,
        )

        self.assertEqual(result.status, "FAIL")
        rendered = "\n".join(result.diagnostics)
        self.assertIn("data/dci-bench/data/hotpotqa/test.jsonl", rendered)
        self.assertIn("corpus/beir/arguana", rendered)
        self.assertIn("DCI-Agent/dci-bench", rendered)
        self.assertIn("manual/external", rendered)

    def test_benchmark_local_fixture_can_materialize_one_inventory_path(self) -> None:
        from asterion.dci.resource_setup import prepare_resources

        source = self.root / "source"
        fixture = source / "data/dci-bench/data/hotpotqa/test.jsonl"
        fixture.parent.mkdir(parents=True)
        fixture.write_text('{"id":"fixture"}\n')
        resources_root = self.root / "resources"

        result = prepare_resources(
            profile="benchmark",
            resource_root=resources_root,
            source_root=source,
        )

        self.assertEqual(result.status, "FAIL")
        self.assertTrue(
            (
                resources_root
                / "data/dci-bench/data/hotpotqa/test.jsonl"
            ).is_file()
        )
        self.assertIn(
            "dataset.data/dci-bench/data/hotpotqa/test.jsonl",
            result.prepared,
        )

    def test_benchmark_cli_check_lists_repairs_without_running_launchers(self) -> None:
        completed = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "tools/setup_resources.py",
                "--profile",
                "benchmark",
                "--resource-root",
                str(self.root / "resources"),
                "--check",
            ],
            cwd=PROJECT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 4, completed.stderr)
        self.assertIn("data/dci-bench", completed.stdout)
        self.assertIn("corpus/beir", completed.stdout)
        self.assertIn("Agent operations=0", completed.stdout)

    def test_manual_benchmark_requirements_never_attempt_a_network_fetch(self) -> None:
        from asterion.dci.resource_setup import (
            ResourceSetupError,
            prepare_resources,
        )

        def offline(spec, staging_root):
            del staging_root
            if spec.source_repo == "manual/external" or spec.conversion == "manual":
                self.fail(f"manual resource attempted network: {spec.resource_id}")
            raise ResourceSetupError("fixture offline")

        with patch("asterion.dci.resource_setup._network_source", offline):
            result = prepare_resources(
                profile="benchmark",
                resource_root=self.root / "resources",
            )

        self.assertEqual(result.status, "FAIL")


if __name__ == "__main__":
    unittest.main()
