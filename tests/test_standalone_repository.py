from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
REQUIRED_ASSETS = (
    ".env.template",
    ".github/workflows/ci.yml",
    ".gitignore",
    "LICENSE",
    "Makefile",
    "README.md",
    "pi-revision.txt",
    "scripts/setup_pi.sh",
    "tools/check_docs.py",
    "tools/check_promotion.py",
    "tools/setup_resources.py",
    "uv.lock",
)
LIFECYCLE_TARGETS = (
    "help",
    "sync",
    "build",
    "test",
    "lint",
    "docs-check",
    "check",
    "promotion-check",
    "first-run-check",
    "setup",
    "setup-pi",
    "check-pi",
    "setup-resources-basic",
    "check-resources-basic",
    "setup-resources-benchmark",
    "check-resources-benchmark",
    "doctor",
)
FRAMEWORK_TARGETS = (
    "asterion-list",
    "asterion-describe",
    "asterion-verify-preflight",
    "asterion-verify-basic",
    "asterion-verify-acceptance",
    "asterion-verify-complete",
    "asterion-run",
)
DCI_TARGETS = (
    "dci-system-prompt",
    "dci-run",
    "dci-terminal",
    "dci-resume",
    "dci-evaluate",
    "dci-benchmark",
    "dci-export",
    "dci-ablation",
    "dci-paper",
)
CROSS_LANGUAGE_TARGETS = ("test-typescript", "test-rust", "check-rust")


def dry_run(target: str, *assignments: str) -> tuple[str, ...]:
    completed = subprocess.run(
        ["make", "-n", target, *assignments],
        cwd=PROJECT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return tuple(shlex.split(completed.stdout.replace("\\\n", " ")))


class StandaloneRepositoryTests(unittest.TestCase):
    def _makefile_text(self) -> str:
        path = PROJECT / "Makefile"
        self.assertTrue(path.is_file(), "standalone Makefile is missing")
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def test_required_repository_assets_exist(self) -> None:
        missing = [name for name in REQUIRED_ASSETS if not (PROJECT / name).is_file()]
        self.assertEqual(missing, [])

    def test_environment_template_has_no_credentials_or_parent_defaults(self) -> None:
        path = PROJECT / ".env.template"
        self.assertTrue(path.is_file(), "standalone environment template is missing")
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        self.assertNotRegex(text, r"(?m)^[A-Z0-9_]*(?:KEY|TOKEN|SECRET)=.+$")
        self.assertNotIn("../", text)
        self.assertNotIn("pi-mono", text)
        self.assertIn("ASTERION_DCI_RESOURCE_ROOT=", text)
        self.assertIn("DCI_PROVIDER=openai-codex", text)
        self.assertIn("DCI_MODEL=gpt-5.6-luna", text)
        self.assertIn("DCI_PI_AGENT_DIR=~/.pi/agent", text)
        self.assertIn("ASTERION_DCI_RESOURCE_ROOT=.", text)
        for default in (
            "DCI_EVAL_JUDGE_BASE_URL=https://api.deepseek.com/v1",
            "DCI_EVAL_JUDGE_API=chat-completions",
            "DCI_EVAL_JUDGE_MODEL=deepseek-v4-flash",
            "DCI_EVAL_JUDGE_API_KEY_ENV=DEEPSEEK_API_KEY",
            "DCI_EVAL_JUDGE_TIMEOUT_SECONDS=120",
            "DCI_EVAL_JUDGE_THINKING=disabled",
            "DCI_EVAL_JUDGE_JSON_MODE=true",
            "DCI_EVAL_JUDGE_STRICT_JSON_SCHEMA=false",
            "DCI_EVAL_JUDGE_RESPONSES_STORE=false",
            "DCI_EVAL_JUDGE_MAX_OUTPUT_TOKENS=1024",
            "DCI_EVAL_JUDGE_INPUT_PRICE_PER_1M=0",
            "DCI_EVAL_JUDGE_CACHED_INPUT_PRICE_PER_1M=0",
            "DCI_EVAL_JUDGE_OUTPUT_PRICE_PER_1M=0",
        ):
            with self.subTest(default=default):
                self.assertIn(default, text)

    def test_external_data_ignore_rules_do_not_hide_packaged_resources(self) -> None:
        text = (PROJECT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for name in (
            "pi",
            "pi-mono",
            "corpus",
            "corpora",
            "data",
            "datasets",
            "outputs",
            "runs",
            "logs",
        ):
            with self.subTest(name=name):
                self.assertIn(f"/{name}/", text)
                self.assertNotIn(f"{name}/", text)

    def test_makefile_exposes_complete_explicit_command_surface(self) -> None:
        text = self._makefile_text()
        phony = {
            token
            for line in text.splitlines()
            if line.startswith(".PHONY:")
            for token in line.removeprefix(".PHONY:").split()
        }
        expected = set(
            LIFECYCLE_TARGETS
            + FRAMEWORK_TARGETS
            + DCI_TARGETS
            + CROSS_LANGUAGE_TARGETS
        )
        self.assertTrue(expected.issubset(phony), sorted(expected - phony))
        self.assertIsNone(re.search(r"(?m)^asterion-verify:\s*$", text))
        self.assertNotIn("eval ", text)

    def test_make_help_labels_cost_boundaries(self) -> None:
        completed = subprocess.run(
            ["make", "help"],
            cwd=PROJECT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("provider-free", completed.stdout)
        self.assertIn("bounded provider-backed", completed.stdout)
        self.assertIn(
            "full execution requires separate authorization", completed.stdout
        )
        self.assertIn("network/disk; Agent operations 0; Judge operations 0", completed.stdout)
        self.assertIn("doctor", completed.stdout)

    def test_framework_targets_render_exact_commands(self) -> None:
        expected = {
            "asterion-list": ("uv", "run", "asterion", "list"),
            "asterion-describe": (
                "uv",
                "run",
                "asterion",
                "describe",
                "--provider",
                "dci-agent-lite",
            ),
            "asterion-verify-preflight": (
                "uv",
                "run",
                "asterion",
                "verify",
                "--provider",
                "dci-agent-lite",
                "--level",
                "preflight",
            ),
            "asterion-verify-basic": (
                "uv",
                "run",
                "asterion",
                "verify",
                "--provider",
                "dci-agent-lite",
                "--level",
                "basic",
            ),
            "asterion-verify-acceptance": (
                "uv",
                "run",
                "asterion",
                "verify",
                "--provider",
                "dci-agent-lite",
                "--level",
                "acceptance",
            ),
            "asterion-verify-complete": (
                "uv",
                "run",
                "asterion",
                "verify",
                "--provider",
                "dci-agent-lite",
                "--level",
                "complete",
            ),
            "asterion-run": ("uv", "run", "asterion", "run"),
        }
        for target, command in expected.items():
            with self.subTest(target=target):
                self.assertEqual(dry_run(target), command)

    def test_dci_targets_render_exact_commands(self) -> None:
        commands = {
            "dci-system-prompt": "system-prompt",
            "dci-run": "run",
            "dci-terminal": "terminal",
            "dci-resume": "resume",
            "dci-evaluate": "evaluate",
            "dci-benchmark": "benchmark",
            "dci-export": "export",
            "dci-ablation": "ablation",
            "dci-paper": "paper",
        }
        for target, command in commands.items():
            with self.subTest(target=target):
                self.assertEqual(
                    dry_run(target), ("uv", "run", "asterion-dci", command)
                )

    def test_make_passthrough_arguments_are_not_shell_evaluated(self) -> None:
        self.assertEqual(
            dry_run("asterion-run", "ASTERION_ARGS=--help"),
            ("uv", "run", "asterion", "run", "--help"),
        )
        self.assertEqual(
            dry_run("dci-run", "DCI_ARGS=--help"),
            ("uv", "run", "asterion-dci", "run", "--help"),
        )

    def test_lifecycle_and_cross_language_recipes_use_native_gates(self) -> None:
        text = self._makefile_text()
        for command in (
            "$(UV_BIN) sync --frozen",
            "$(UV_BIN) build .",
            "python -m unittest discover -s tests -v",
            "python -m compileall -q src tests tools",
            "ruff check src tests tools",
            "python tools/check_docs.py",
            "python tools/check_promotion.py",
            "npm ci --prefix packages/typescript/asterion-runtime",
            "npm test --prefix packages/typescript/asterion-runtime",
            "npm test --prefix packages/typescript/dci-context-extension",
            "cargo test --manifest-path packages/rust/controlled-executor/Cargo.toml",
            "cargo fmt --manifest-path packages/rust/controlled-executor/Cargo.toml -- --check",
            "cargo clippy --manifest-path packages/rust/controlled-executor/Cargo.toml -- -D warnings",
        ):
            with self.subTest(command=command):
                self.assertIn(command, text)

    def test_pi_setup_targets_render_exact_commands(self) -> None:
        self.assertEqual(
            dry_run("setup-pi"), ("bash", "scripts/setup_pi.sh")
        )
        self.assertEqual(
            dry_run("check-pi"), ("bash", "scripts/setup_pi.sh", "--check")
        )

    def test_basic_resource_targets_render_exact_commands(self) -> None:
        self.assertEqual(
            dry_run("setup-resources-basic"),
            (
                "uv",
                "run",
                "--extra",
                "setup",
                "python",
                "tools/setup_resources.py",
                "--profile",
                "basic",
            ),
        )
        self.assertEqual(
            dry_run("check-resources-basic"),
            (
                "uv",
                "run",
                "python",
                "tools/setup_resources.py",
                "--profile",
                "basic",
                "--check",
            ),
        )

    def test_benchmark_resource_targets_render_exact_commands(self) -> None:
        self.assertEqual(
            dry_run("setup-resources-benchmark"),
            (
                "uv",
                "run",
                "--extra",
                "setup",
                "python",
                "tools/setup_resources.py",
                "--profile",
                "benchmark",
            ),
        )
        self.assertEqual(
            dry_run("check-resources-benchmark"),
            (
                "uv",
                "run",
                "python",
                "tools/setup_resources.py",
                "--profile",
                "benchmark",
                "--check",
            ),
        )

    def test_doctor_renders_provider_free_preflight(self) -> None:
        self.assertEqual(
            dry_run("doctor"),
            (
                "uv",
                "run",
                "asterion",
                "verify",
                "--provider",
                "dci-agent-lite",
                "--level",
                "preflight",
            ),
        )

    def test_first_run_check_uses_only_local_fixture_modules(self) -> None:
        self.assertEqual(
            dry_run("first-run-check"),
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
        )

    def test_setup_composes_sync_pi_and_basic_resources(self) -> None:
        self.assertEqual(
            dry_run("setup"),
            (
                "uv",
                "sync",
                "--frozen",
                "bash",
                "scripts/setup_pi.sh",
                "uv",
                "run",
                "--extra",
                "setup",
                "python",
                "tools/setup_resources.py",
                "--profile",
                "basic",
            ),
        )

    def test_ci_runs_only_the_full_provider_free_promotion_gate(self) -> None:
        path = PROJECT / ".github/workflows/ci.yml"
        self.assertTrue(path.is_file(), "standalone CI workflow is missing")
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        self.assertIn("pull_request:", text)
        self.assertIn("push:", text)
        self.assertIn("contents: read", text)
        self.assertIn("python-version: '3.10'", text)
        self.assertIn("node-version: '20'", text)
        self.assertIn("toolchain: stable", text)
        self.assertIn("make promotion-check", text)
        self.assertIn("make first-run-check", text)
        for forbidden in (
            "API_KEY",
            "provider-backed",
            "verify-basic",
            "verify-complete",
            "--quick",
            "publish",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_readme_is_a_complete_standalone_landing_page(self) -> None:
        text = (PROJECT / "README.md").read_text(encoding="utf-8")
        for heading in (
            "## Installation",
            "## Discovery and installed acceptance",
            "## External Pi and resources",
            "## Cost boundaries",
            "## Development",
            "## Promotion",
            "## Mixed-repository integration parity",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, text)
        for command in (
            "uv sync --frozen",
            "make setup-pi",
            "make setup-resources-basic",
            "cp .env.template .env",
            "make doctor",
            "uv run asterion list",
            "uv run asterion describe --provider dci-agent-lite",
            "uv run asterion verify --provider dci-agent-lite --level acceptance",
            "make check",
            "make promotion-check",
        ):
            with self.subTest(command=command):
                self.assertIn(command, text)
        for statement in (
            "global `pi`",
            "DCI_PI_AGENT_DIR",
            "setup-resources-benchmark",
            "zero Agent",
            "zero Judge",
        ):
            with self.subTest(statement=statement):
                self.assertIn(statement, text)
        for setting in (
            "DCI_PI_DIR",
            "ASTERION_DCI_RESOURCE_ROOT",
            ".env",
            "corpora",
            "datasets",
            "Judge",
        ):
            with self.subTest(setting=setting):
                self.assertIn(setting, text)

    def test_docs_reject_mixed_root_commands_paths_and_current_counts(self) -> None:
        documents = (PROJECT / "README.md", *sorted((PROJECT / "docs").rglob("*.md")))
        forbidden = (
            "uv run --project " + "asterion",
            "../../../docs/superpowers/",
            "/Users/" + "sujiangwen/",
            "90 tests",
            "1230 tests",
            "Run these checks from the parent mixed-repository root",
            "python3 tools/project_scope_check.py",
            "python3 ../tools/project_scope_check.py",
            "npm --prefix asterion/",
            "uv run ruff check asterion/",
            "uv build asterion",
            "make -C ..",
        )
        for document in documents:
            text = document.read_text(encoding="utf-8")
            with self.subTest(document=document.relative_to(PROJECT)):
                for value in forbidden:
                    self.assertNotIn(value, text)
                for line in text.splitlines():
                    if "tools/verify_asterion_dci_product.py" in line:
                        self.assertIn("mixed-repository only", line)
                    if re.search(r"\b(?:533/533|538/538)\b", line):
                        self.assertRegex(line, r"historical|历史|mixed-repository")

    def test_docs_checker_passes_the_current_standalone_tree(self) -> None:
        completed = subprocess.run(
            ["uv", "run", "python", "tools/check_docs.py"],
            cwd=PROJECT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertRegex(
            completed.stdout.strip(),
            r"^checked \d+ markdown files, \d+ local links$",
        )

    def test_docs_checker_handles_links_and_rejects_unsafe_targets(self) -> None:
        checker = PROJECT / "tools/check_docs.py"
        self.assertTrue(checker.is_file(), "standalone docs checker is missing")
        if not checker.is_file():
            return

        with tempfile.TemporaryDirectory() as temporary_directory:
            sandbox = Path(temporary_directory)
            root = sandbox / "project"
            (root / "tools").mkdir(parents=True)
            shutil.copy2(checker, root / "tools/check_docs.py")
            (root / "docs").mkdir()
            (root / "docs/My Guide.md").write_text(
                "# Guide\n\n## Section\n", encoding="utf-8"
            )
            (root / "README.md").write_text(
                "# Root\n\n[guide](docs/My%20Guide.md#section) "
                "[anchor](#root) [web](https://example.invalid)\n",
                encoding="utf-8",
            )

            def run() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["python3", "tools/check_docs.py"],
                    cwd=root,
                    check=False,
                    capture_output=True,
                    text=True,
                )

            valid = run()
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(valid.stdout.strip(), "checked 2 markdown files, 1 local links")

            outside = sandbox / "outside.md"
            outside.write_text("# Outside\n", encoding="utf-8")
            unsafe_targets = (
                "docs/missing.md",
                "../outside.md",
                "%2E%2E/outside.md",
                str(outside),
            )
            for target in unsafe_targets:
                with self.subTest(target=target):
                    (root / "README.md").write_text(
                        f"# Root\n\n[unsafe]({target})\n", encoding="utf-8"
                    )
                    self.assertNotEqual(run().returncode, 0)


if __name__ == "__main__":
    unittest.main()
