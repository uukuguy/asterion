from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = tuple(sorted((PROJECT / "scripts").glob("*/*.sh")))
REPRESENTATIVE_SCRIPTS = (
    "qa/run_nq_test_sample50.sh",
    "bright/run_bio.sh",
    "beir/benchmark_arguana.sh",
    "bcplus_eval/run_L3.sh",
)


class StandaloneLauncherTests(unittest.TestCase):
    def test_all_fourteen_launchers_use_the_standalone_root_contract(self) -> None:
        self.assertEqual(len(SCRIPTS), 14)
        for script in SCRIPTS:
            with self.subTest(script=script.relative_to(PROJECT)):
                text = script.read_text(encoding="utf-8")
                self.assertIn(
                    'PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)',
                    text,
                )
                self.assertIn(
                    "RESOURCE_ROOT=${ASTERION_DCI_RESOURCE_ROOT:-$PROJECT_ROOT}",
                    text,
                )
                self.assertIn(
                    'uv run --project "$PROJECT_ROOT" asterion-dci', text
                )
                self.assertNotIn("REPO_ROOT", text)
                self.assertNotIn("../../..", text)
                self.assertNotIn("$PROJECT_ROOT/asterion", text)

    def test_every_launcher_has_valid_bash_syntax(self) -> None:
        for script in SCRIPTS:
            with self.subTest(script=script.relative_to(PROJECT)):
                completed = subprocess.run(
                    ["bash", "-n", str(script)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_representative_launchers_resolve_copy_and_external_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temporary = Path(temp_dir)
            copied = temporary / "asterion"
            shutil.copytree(PROJECT / "scripts", copied / "scripts")
            resource_root = temporary / "external-resources"
            for relative in (
                "data/dci-bench/data/nq/test.jsonl",
                "data/dci-bench/data/bright_biology/bright_biology.jsonl",
                "data/dci-bench/data/beir_arguana/test.jsonl",
                "data/bcplus_qa.jsonl",
            ):
                path = resource_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
            for relative in (
                "corpus/wiki_corpus",
                "corpus/bright_corpus/biology",
                "corpus/beir/arguana",
                "corpus/bc_plus_docs",
            ):
                (resource_root / relative).mkdir(parents=True, exist_ok=True)

            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake_uv = fake_bin / "uv"
            fake_uv.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$UV_LOG"\n',
                encoding="utf-8",
            )
            fake_uv.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "ASTERION_DCI_RESOURCE_ROOT": str(resource_root),
                    "PATH": os.pathsep.join(
                        (str(fake_bin), environment.get("PATH", ""))
                    ),
                }
            )

            for relative in REPRESENTATIVE_SCRIPTS:
                with self.subTest(script=relative):
                    log = temporary / (relative.replace("/", "-") + ".argv")
                    environment["UV_LOG"] = str(log)
                    completed = subprocess.run(
                        [str(copied / "scripts" / relative), "--fixture-flag"],
                        check=False,
                        capture_output=True,
                        text=True,
                        env=environment,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    argv = log.read_text(encoding="utf-8").splitlines()
                    self.assertEqual(
                        argv[:4],
                        ["run", "--project", str(copied), "asterion-dci"],
                    )
                    self.assertIn("--fixture-flag", argv)
                    for option in ("--dataset", "--corpus"):
                        value = Path(argv[argv.index(option) + 1])
                        self.assertTrue(value.is_relative_to(resource_root), value)


if __name__ == "__main__":
    unittest.main()
