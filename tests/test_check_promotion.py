from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.check_promotion import PromotionError, _default_runner, run_promotion


REQUIRED_FIXTURE_ASSETS = (
    ".env.template",
    ".github/workflows/ci.yml",
    ".gitignore",
    "LICENSE",
    "Makefile",
    "README.md",
    "pi-revision.txt",
    "pyproject.toml",
    "scripts/setup_pi.sh",
    "tools/check_docs.py",
    "tools/check_promotion.py",
    "tools/setup_resources.py",
    "uv.lock",
)


def make_source(parent: Path) -> Path:
    source = parent / "source"
    source.mkdir(parents=True)
    for relative in REQUIRED_FIXTURE_ASSETS:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    (source / "src").mkdir()
    (source / "tests").mkdir()
    (source / "included.txt").write_text("included\n", encoding="utf-8")
    return source


def completed(
    command: tuple[str, ...], stdout: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


class PromotionCheckTests(unittest.TestCase):
    def test_default_runner_forces_sparse_cargo_registry_and_preserves_environment(self) -> None:
        result = completed(("cargo", "test"))
        with (
            mock.patch.dict(
                os.environ,
                {
                    "ASTERION_PROMOTION_TEST_MARKER": "preserved",
                    "CARGO_HOME": "/untrusted-cargo-home",
                },
                clear=False,
            ),
            mock.patch("tools.check_promotion.subprocess.run", return_value=result) as run,
        ):
            self.assertIs(
                _default_runner(
                    ("cargo", "test"), Path("/promotion-workspace/project")
                ),
                result,
            )

        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["CARGO_REGISTRIES_CRATES_IO_PROTOCOL"], "sparse")
        self.assertEqual(environment["CARGO_HOME"], "/promotion-workspace/cargo-home")
        self.assertEqual(environment["ASTERION_PROMOTION_TEST_MARKER"], "preserved")

    def test_quick_copy_excludes_external_generated_and_cache_paths(self) -> None:
        excluded = (
            ".git",
            ".venv",
            ".env",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "node_modules",
            "target",
            "dist",
            "outputs",
            "corpus",
            "corpora",
            "data",
            "datasets",
            "pi",
            "pi-mono",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = make_source(Path(temporary_directory))
            for name in excluded:
                path = source / name
                if name == ".env":
                    path.write_text("SECRET=value\n", encoding="utf-8")
                else:
                    path.mkdir(parents=True)
                    (path / "excluded.txt").write_text("x\n", encoding="utf-8")
            try:
                os.symlink(
                    source / "included.txt",
                    source / "node_modules/generated-link",
                )
            except OSError:
                pass
            packaged_corpus = source / "src/product/resources/paper-fixtures/corpus"
            packaged_corpus.mkdir(parents=True)
            (packaged_corpus / "fixture.json").write_text("{}\n", encoding="utf-8")
            packaged_pi = source / "src/product/resources/pi"
            packaged_pi.mkdir(parents=True)
            (packaged_pi / "manifest.json").write_text("{}\n", encoding="utf-8")

            observed_roots: list[Path] = []

            def runner(
                command: tuple[str, ...], cwd: Path
            ) -> subprocess.CompletedProcess[str]:
                observed_roots.append(cwd)
                self.assertTrue((cwd / "included.txt").is_file())
                self.assertTrue(
                    (cwd / "src/product/resources/paper-fixtures/corpus/fixture.json").is_file()
                )
                self.assertTrue(
                    (cwd / "src/product/resources/pi/manifest.json").is_file()
                )
                for name in excluded:
                    self.assertFalse((cwd / name).exists(), name)
                return completed(command, acceptance_stdout(command))

            run_promotion(source_root=source, quick=True, runner=runner)

        self.assertTrue(observed_roots)
        self.assertEqual(len(set(observed_roots)), 1)
        self.assertNotEqual(observed_roots[0], source)

    def test_symlinks_are_rejected_before_copy_or_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = make_source(Path(temporary_directory))
            target = source / "included.txt"
            link = source / "linked.txt"
            try:
                os.symlink(target, link)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            calls: list[tuple[str, ...]] = []

            with self.assertRaises(PromotionError):
                run_promotion(
                    source_root=source,
                    quick=True,
                    runner=lambda command, cwd: calls.append(command)
                    or completed(command),
                )

        self.assertEqual(calls, [])

    def test_copy_audit_rejects_missing_assets_and_nonportable_references(self) -> None:
        forbidden = (
            "/Users/" + "sujiangwen/",
            "--project " + "asterion",
            "../src/" + "dci",
            "../tools/" + "verify_asterion_dci_product.py",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = make_source(temporary)
            (source / "LICENSE").unlink()
            with self.assertRaises(PromotionError):
                run_promotion(
                    source_root=source,
                    quick=True,
                    runner=lambda command, cwd: completed(command),
                )

            for index, value in enumerate(forbidden):
                with self.subTest(value=value):
                    source = make_source(temporary / f"case-{index}")
                    (source / "README.md").write_text(value, encoding="utf-8")
                    with self.assertRaises(PromotionError):
                        run_promotion(
                            source_root=source,
                            quick=True,
                            runner=lambda command, cwd: completed(command),
                        )

    def test_default_plan_runs_every_provider_free_gate_from_the_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = make_source(Path(temporary_directory))
            commands: list[tuple[str, ...]] = []
            roots: list[Path] = []

            def runner(
                command: tuple[str, ...], cwd: Path
            ) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                roots.append(cwd)
                if command == ("uv", "build", "."):
                    dist = cwd / "dist"
                    dist.mkdir()
                    (dist / "asterion-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
                return completed(command, acceptance_stdout(command))

            run_promotion(source_root=source, quick=False, runner=runner)

        rendered = tuple(" ".join(command) for command in commands)
        for expected in (
            "uv sync --frozen",
            "uv run python -m unittest -v tests.test_setup_pi tests.test_resource_setup tests.test_asterion_dci_verification",
            "uv run python -m unittest discover -s tests -v",
            "uv run python -m compileall -q src tests tools",
            "uv run ruff check src tests tools",
            "uv build .",
            "uv run python tools/check_docs.py",
            "npm ci --prefix packages/typescript/asterion-runtime",
            "npm test --prefix packages/typescript/asterion-runtime",
            "npm test --prefix packages/typescript/dci-context-extension",
            "cargo test --manifest-path packages/rust/controlled-executor/Cargo.toml",
            "cargo fmt --manifest-path packages/rust/controlled-executor/Cargo.toml -- --check",
            "cargo clippy --manifest-path packages/rust/controlled-executor/Cargo.toml -- -D warnings",
        ):
            with self.subTest(command=expected):
                self.assertIn(expected, rendered)
        self.assertTrue(any(command[:2] == ("uv", "venv") for command in commands))
        self.assertTrue(
            any(command[:3] == ("uv", "pip", "install") for command in commands)
        )
        for suffix in (
            ("list",),
            ("describe", "--provider", "dci-agent-lite", "--json"),
            (
                "verify",
                "--provider",
                "dci-agent-lite",
                "--level",
                "acceptance",
                "--json",
            ),
        ):
            self.assertTrue(
                any(command[0].endswith("/asterion") and command[1:] == suffix for command in commands),
                suffix,
            )
        self.assertEqual(len(set(roots)), 1)
        self.assertNotEqual(roots[0], source)
        command_text = "\n".join(rendered).lower()
        for forbidden in (
            "api_key",
            "provider-backed",
            "verify-basic",
            "verify-complete",
            "--level basic",
            "--level complete",
            "--authorize-full",
            "paper compare",
        ):
            self.assertNotIn(forbidden, command_text)

    def test_quick_plan_uses_valid_discovery_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = make_source(Path(temporary_directory))
            commands: list[tuple[str, ...]] = []

            def runner(
                command: tuple[str, ...], cwd: Path
            ) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                return completed(command, acceptance_stdout(command))

            run_promotion(source_root=source, quick=True, runner=runner)

        self.assertIn(("uv", "run", "asterion", "list"), commands)
        self.assertIn(
            (
                "uv",
                "run",
                "python",
                "-m",
                "unittest",
                "-v",
                "tests.test_setup_pi",
                "tests.test_resource_setup",
                "tests.test_asterion_dci_verification",
            ),
            commands,
        )
        self.assertIn(
            (
                "uv",
                "run",
                "asterion",
                "describe",
                "--provider",
                "dci-agent-lite",
                "--json",
            ),
            commands,
        )
        self.assertFalse(
            any(command[3:5] == ("describe", "describe") for command in commands)
        )

    def test_acceptance_json_must_be_provider_free_and_not_full_dataset(self) -> None:
        bad_payloads = (
            {"status": "FAIL", "provider_backed_operation_count": 0, "full_dataset_ran": False},
            {"status": "PASS", "provider_backed_operation_count": 1, "full_dataset_ran": False},
            {"status": "PASS", "provider_backed_operation_count": 0, "full_dataset_ran": True},
        )
        for index, payload in enumerate(bad_payloads):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temporary_directory:
                source = make_source(Path(temporary_directory))

                def runner(
                    command: tuple[str, ...], cwd: Path
                ) -> subprocess.CompletedProcess[str]:
                    if command == ("uv", "build", "."):
                        dist = cwd / "dist"
                        dist.mkdir()
                        (dist / "asterion-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
                    stdout = json.dumps(payload) if is_acceptance(command) else ""
                    return completed(command, stdout)

                with self.assertRaises(PromotionError):
                    run_promotion(source_root=source, quick=False, runner=runner)


def is_acceptance(command: tuple[str, ...]) -> bool:
    return "verify" in command and "acceptance" in command


def acceptance_stdout(command: tuple[str, ...]) -> str:
    if not is_acceptance(command):
        return ""
    return json.dumps(
        {
            "status": "PASS",
            "provider_backed_operation_count": 0,
            "full_dataset_ran": False,
        }
    )


if __name__ == "__main__":
    unittest.main()
