from __future__ import annotations

import os
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
            "paper-full",
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
                "--env-file",
                str(PROJECT / ".env"),
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
        self.assertIn("node-version: '22.19.0'", text)
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
            "Node.js 22.19.0",
            "`npm ci`",
            "checked-in model catalogs",
            "dirty checkout",
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

    def test_docs_publish_bounded_reproduction_boundary(self) -> None:
        public_documents = (
            PROJECT / "README.md",
            PROJECT / "docs/guides/asterion-dci-complete-reference.md",
            PROJECT / "docs/verification/asterion-dci-validation-guide.md",
        )
        required_fragments = (
            "paper reproduce",
            "--scope bright.robotics.main.full",
            "--limit 1",
            "--execute",
            "--max-agent-operations 1",
            "--max-judge-operations 1",
            "External-limited",
        )
        for document in public_documents:
            text = document.read_text(encoding="utf-8")
            with self.subTest(document=document.relative_to(PROJECT)):
                for fragment in required_fragments:
                    self.assertIn(fragment, text)

        corrected_documents = (
            *public_documents,
            PROJECT
            / "docs/superpowers/plans/2026-07-24-dci-provenance-reproduction.md",
        )
        forbidden_fragments = (
            "--dry-run",
            "--authorize-full",
            "asterion-safe/pi",
            "browsecomp-plus.appendix-a1.random50",
        )
        overstated_output_claims = (
            "prints only the scope",
            "CLI 只输出",
            "reports only `manifest_scope`",
            "CLI output contains only",
        )
        for document in corrected_documents:
            text = document.read_text(encoding="utf-8")
            with self.subTest(document=document.relative_to(PROJECT)):
                for fragment in forbidden_fragments:
                    self.assertNotIn(fragment, text)
                for claim in overstated_output_claims:
                    self.assertNotIn(claim, text)
                self.assertNotRegex(
                    text,
                    r"(?i)one-query (?:result|run|evidence) "
                    r"(?:is|constitutes|qualifies as) (?:a )?"
                    r"(?:full paper|published-score) reproduction",
                )

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

    def test_docs_checker_rejects_retired_protocols_only_in_active_docs(self) -> None:
        checker = PROJECT / "tools/check_docs.py"
        retired = tuple(
            f"dci.{name}/v1" for name in ("agent-runtime", "package", "assembly")
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "tools").mkdir()
            shutil.copy2(checker, root / "tools/check_docs.py")
            historical = root / "docs/superpowers/plans/historical.md"
            historical.parent.mkdir(parents=True)
            historical.write_text("\n".join(retired), encoding="utf-8")

            def run() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["python3", "tools/check_docs.py"],
                    cwd=root,
                    check=False,
                    capture_output=True,
                    text=True,
                )

            (root / "README.md").write_text("# Active\n", encoding="utf-8")
            self.assertEqual(run().returncode, 0)

            for value in retired:
                with self.subTest(value=value):
                    (root / "README.md").write_text(value, encoding="utf-8")
                    completed = run()
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("retired protocol identifier", completed.stderr)

    def test_typescript_readme_documents_the_complete_protocol_family(self) -> None:
        text = (
            PROJECT / "packages/typescript/asterion-runtime/README.md"
        ).read_text(encoding="utf-8")
        for protocol in (
            "asterion.agent-runtime/v1",
            "asterion.capability/v1",
            "asterion.capability-package/v1",
            "asterion.application-assembly/v1",
            "asterion.benchmark-suite/v1",
            "asterion.capability-source/v1",
            "asterion.capability-lock/v1",
        ):
            with self.subTest(protocol=protocol):
                self.assertIn(protocol, text)
        for schema in (
            "runtime-manifest.schema.json",
            "run-request.schema.json",
            "event.schema.json",
            "capability-manifest.schema.json",
            "capability-package.schema.json",
            "application-assembly.schema.json",
            "benchmark-suite.schema.json",
            "capability-source.schema.json",
            "capability-lock.schema.json",
        ):
            with self.subTest(schema=schema):
                self.assertIn(schema, text)

    def test_docs_checker_validates_asterion_import_snippets(self) -> None:
        checker = PROJECT / "tools/check_docs.py"
        self.assertTrue(checker.is_file(), "standalone docs checker is missing")
        if not checker.is_file():
            return

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "tools").mkdir()
            shutil.copy2(checker, root / "tools/check_docs.py")
            (root / "docs").mkdir()
            package = root / "src/asterion"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "fixture.py").write_text(
                "from pathlib import Path\n"
                'Path("IMPORT_SIDE_EFFECT").write_text("executed", encoding="utf-8")\n'
                "DOCUMENTED_API = object()\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(root / "src")
            marker = root / "IMPORT_SIDE_EFFECT"

            def run() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["python3", "tools/check_docs.py"],
                    cwd=root,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )

            cases = (
                (
                    "missing direct module",
                    "import asterion.definitely_missing\n",
                    False,
                    "documented import is unavailable",
                ),
                (
                    "missing explicit symbol",
                    "from asterion.fixture import MISSING_API\n",
                    False,
                    "documented import is unavailable",
                ),
                (
                    "existing direct module",
                    "import asterion.fixture\n",
                    True,
                    "",
                ),
                (
                    "existing explicit symbol",
                    "from asterion.fixture import DOCUMENTED_API\n",
                    True,
                    "",
                ),
                (
                    "malformed multiline import",
                    "from asterion.fixture import (\n    DOCUMENTED_API\n",
                    False,
                    "documented import is invalid",
                ),
            )
            for label, snippet, should_pass, expected_error in cases:
                with self.subTest(case=label):
                    marker.unlink(missing_ok=True)
                    (root / "README.md").write_text(
                        f"# Root\n\n```python\n{snippet}```\n",
                        encoding="utf-8",
                    )
                    completed = run()
                    if should_pass:
                        self.assertEqual(
                            completed.returncode,
                            0,
                            completed.stderr,
                        )
                    else:
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertIn(expected_error, completed.stderr)
                    self.assertNotIn("Traceback", completed.stderr)
                    self.assertFalse(
                        marker.exists(),
                        "documentation checking executed imported module code",
                    )

    def test_docs_checker_resolves_namespace_packages_without_importing(
        self,
    ) -> None:
        checker = PROJECT / "tools/check_docs.py"
        self.assertTrue(checker.is_file(), "standalone docs checker is missing")
        if not checker.is_file():
            return

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "tools").mkdir()
            shutil.copy2(checker, root / "tools/check_docs.py")
            (root / "docs").mkdir()
            marker = root / "IMPORT_SIDE_EFFECT"
            side_effect_source = (
                "from pathlib import Path\n"
                'Path("IMPORT_SIDE_EFFECT").write_text("executed", encoding="utf-8")\n'
            )

            regular_root = root / "regular"
            nested_namespace = regular_root / "asterion/ns"
            nested_namespace.mkdir(parents=True)
            (regular_root / "asterion/__init__.py").write_text(
                side_effect_source,
                encoding="utf-8",
            )
            (nested_namespace / "child.py").write_text(
                f"{side_effect_source}API = object()\n",
                encoding="utf-8",
            )
            (nested_namespace / "broken.py").write_text(
                "API = (\n",
                encoding="utf-8",
            )
            (nested_namespace / "loop.py").symlink_to("loop.py")

            namespace_root_one = root / "namespace-one"
            namespace_root_two = root / "namespace-two"
            top_namespace_one = namespace_root_one / "asterion/top"
            top_namespace_two = namespace_root_two / "asterion/top"
            top_namespace_one.mkdir(parents=True)
            top_namespace_two.mkdir(parents=True)
            (top_namespace_one / "child.py").write_text(
                f"{side_effect_source}API = object()\n",
                encoding="utf-8",
            )
            (top_namespace_two / "sibling.py").write_text(
                f"{side_effect_source}SIBLING_API = object()\n",
                encoding="utf-8",
            )
            (top_namespace_two / "public.py").write_text(
                f"{side_effect_source}from .child import API as PUBLIC\n",
                encoding="utf-8",
            )

            def run(
                search_roots: tuple[Path, ...],
                snippet: str,
            ) -> subprocess.CompletedProcess[str]:
                marker.unlink(missing_ok=True)
                (root / "README.md").write_text(
                    f"# Root\n\n```python\n{snippet}```\n",
                    encoding="utf-8",
                )
                environment = os.environ.copy()
                environment["PYTHONPATH"] = os.pathsep.join(
                    str(path) for path in search_roots
                )
                return subprocess.run(
                    ["python3", "-S", "tools/check_docs.py"],
                    cwd=root,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )

            cases = (
                (
                    "nested direct child",
                    (regular_root,),
                    "import asterion.ns.child\n",
                    True,
                ),
                (
                    "nested from-import child",
                    (regular_root,),
                    "from asterion.ns import child\n",
                    True,
                ),
                (
                    "nested explicit symbol",
                    (regular_root,),
                    "from asterion.ns.child import API\n",
                    True,
                ),
                (
                    "nested missing child",
                    (regular_root,),
                    "import asterion.ns.missing\n",
                    False,
                ),
                (
                    "nested missing symbol",
                    (regular_root,),
                    "from asterion.ns.child import MISSING\n",
                    False,
                ),
                (
                    "nested invalid source",
                    (regular_root,),
                    "import asterion.ns.broken\n",
                    False,
                ),
                (
                    "nested resolver error",
                    (regular_root,),
                    "import asterion.ns.loop\n",
                    False,
                ),
                (
                    "top-level namespace direct child",
                    (namespace_root_one, namespace_root_two),
                    "import asterion.top.child\n",
                    True,
                ),
                (
                    "top-level namespace from-import child",
                    (namespace_root_one, namespace_root_two),
                    "from asterion.top import child\n",
                    True,
                ),
                (
                    "top-level namespace explicit symbol",
                    (namespace_root_one, namespace_root_two),
                    "from asterion.top.child import API\n",
                    True,
                ),
                (
                    "top-level namespace second root",
                    (namespace_root_one, namespace_root_two),
                    "from asterion.top import sibling\n",
                    True,
                ),
                (
                    "top-level namespace cross-root re-export",
                    (namespace_root_one, namespace_root_two),
                    "from asterion.top.public import PUBLIC\n",
                    True,
                ),
                (
                    "top-level namespace missing child",
                    (namespace_root_one, namespace_root_two),
                    "import asterion.top.missing\n",
                    False,
                ),
                (
                    "top-level namespace missing symbol",
                    (namespace_root_one, namespace_root_two),
                    "from asterion.top.child import MISSING\n",
                    False,
                ),
            )
            for label, search_roots, snippet, should_pass in cases:
                with self.subTest(case=label):
                    completed = run(search_roots, snippet)
                    if should_pass:
                        self.assertEqual(
                            completed.returncode,
                            0,
                            completed.stderr,
                        )
                    else:
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertIn(
                            "documented import is unavailable",
                            completed.stderr,
                        )
                    self.assertNotIn("Traceback", completed.stderr)
                    self.assertFalse(
                        marker.exists(),
                        "documentation checking executed imported module code",
                    )

    def test_docs_checker_validates_reexport_provenance_without_importing(
        self,
    ) -> None:
        checker = PROJECT / "tools/check_docs.py"
        self.assertTrue(checker.is_file(), "standalone docs checker is missing")
        if not checker.is_file():
            return

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "tools").mkdir()
            shutil.copy2(checker, root / "tools/check_docs.py")
            (root / "docs").mkdir()
            source_root = root / "src"
            package = source_root / "asterion"
            package.mkdir(parents=True)
            marker = root / "IMPORT_SIDE_EFFECT"
            side_effect_source = (
                "from pathlib import Path\n"
                'Path("IMPORT_SIDE_EFFECT").write_text("executed", encoding="utf-8")\n'
            )
            (package / "__init__.py").write_text(
                side_effect_source,
                encoding="utf-8",
            )

            valid = package / "valid"
            valid.mkdir()
            (valid / "__init__.py").write_text(
                f"{side_effect_source}"
                "DIRECT = object()\n"
                "from .child import API\n"
                "from .child import API as PublicAPI\n"
                "from . import child\n"
                "from asterion.valid.child import API as AbsoluteAPI\n"
                "import asterion.valid.child as ChildAlias\n"
                "from .hop_one import CHAIN_API\n",
                encoding="utf-8",
            )
            (valid / "child.py").write_text(
                f"{side_effect_source}API = object()\n",
                encoding="utf-8",
            )
            (valid / "hop_one.py").write_text(
                "from .hop_two import API as CHAIN_API\n",
                encoding="utf-8",
            )
            (valid / "hop_two.py").write_text(
                "API = object()\n",
                encoding="utf-8",
            )

            broken_module = package / "broken_module"
            broken_module.mkdir()
            (broken_module / "__init__.py").write_text(
                "from .missing import API\n",
                encoding="utf-8",
            )

            broken_symbol = package / "broken_symbol"
            broken_symbol.mkdir()
            (broken_symbol / "__init__.py").write_text(
                "from asterion.valid.child import MISSING as API\n",
                encoding="utf-8",
            )

            broken_source = package / "broken_source"
            broken_source.mkdir()
            (broken_source / "__init__.py").write_text(
                "from .target import API\n",
                encoding="utf-8",
            )
            (broken_source / "target.py").write_text(
                "API = (\n",
                encoding="utf-8",
            )

            cycle = package / "cycle"
            cycle.mkdir()
            (cycle / "__init__.py").write_text(
                "from .a import API\n",
                encoding="utf-8",
            )
            (cycle / "a.py").write_text(
                "from . import API\n",
                encoding="utf-8",
            )

            external = package / "external"
            external.mkdir()
            (external / "__init__.py").write_text(
                "from pathlib import Path as API\n",
                encoding="utf-8",
            )

            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(source_root)

            def run_checker(snippet: str) -> subprocess.CompletedProcess[str]:
                marker.unlink(missing_ok=True)
                (root / "README.md").write_text(
                    f"# Root\n\n```python\n{snippet}```\n",
                    encoding="utf-8",
                )
                return subprocess.run(
                    ["python3", "-S", "tools/check_docs.py"],
                    cwd=root,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )

            def run_python(snippet: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["python3", "-S", "-c", snippet],
                    cwd=root,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )

            cases = (
                (
                    "direct assignment",
                    "from asterion.valid import DIRECT\n",
                    True,
                    True,
                ),
                (
                    "local re-export",
                    "from asterion.valid import API\n",
                    True,
                    True,
                ),
                (
                    "aliased local re-export",
                    "from asterion.valid import PublicAPI\n",
                    True,
                    True,
                ),
                (
                    "module as child",
                    "from asterion.valid import child\n",
                    True,
                    True,
                ),
                (
                    "absolute re-export",
                    "from asterion.valid import AbsoluteAPI\n",
                    True,
                    True,
                ),
                (
                    "imported module alias",
                    "from asterion.valid import ChildAlias\n",
                    True,
                    True,
                ),
                (
                    "multi-hop re-export",
                    "from asterion.valid import CHAIN_API\n",
                    True,
                    True,
                ),
                (
                    "missing re-export module",
                    "from asterion.broken_module import API\n",
                    False,
                    False,
                ),
                (
                    "missing re-export symbol",
                    "from asterion.broken_symbol import API\n",
                    False,
                    False,
                ),
                (
                    "invalid re-export source",
                    "from asterion.broken_source import API\n",
                    False,
                    False,
                ),
                (
                    "re-export cycle",
                    "from asterion.cycle import API\n",
                    False,
                    False,
                ),
                (
                    "external import fails closed",
                    "from asterion.external import API\n",
                    False,
                    True,
                ),
            )
            for label, snippet, checker_should_pass, python_should_pass in cases:
                with self.subTest(case=label):
                    checked = run_checker(snippet)
                    if checker_should_pass:
                        self.assertEqual(checked.returncode, 0, checked.stderr)
                    else:
                        self.assertNotEqual(checked.returncode, 0)
                        self.assertIn(
                            "documented import is unavailable",
                            checked.stderr,
                        )
                    self.assertNotIn("Traceback", checked.stderr)
                    self.assertFalse(
                        marker.exists(),
                        "documentation checking executed imported module code",
                    )

                    imported = run_python(snippet)
                    if python_should_pass:
                        self.assertEqual(imported.returncode, 0, imported.stderr)
                    else:
                        self.assertNotEqual(imported.returncode, 0)


if __name__ == "__main__":
    unittest.main()
