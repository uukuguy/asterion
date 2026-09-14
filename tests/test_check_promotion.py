from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.check_promotion import (
    PromotionError,
    _closed_prime_subprocess_environment,
    _closed_npm_subprocess_environment,
    _default_runner,
    _resolve_promotion_npm_cache,
    _run,
    main,
    run_promotion,
)


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
    def test_main_uses_only_the_declared_node_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            cache = temporary / "cache"
            cache.mkdir()
            node = temporary / "node"
            node.write_text("node\n", encoding="utf-8")
            node.chmod(0o700)
            with (
                mock.patch(
                    "tools.check_promotion.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        (str(node), "--version"), 0, stdout="v22.16.0\n", stderr=""
                    ),
                ) as run,
                mock.patch("tools.check_promotion.run_promotion", return_value=3) as promotion,
            ):
                self.assertEqual(
                    main(
                        [
                            "--quick",
                            "--npm-cache",
                            str(cache),
                            "--node-executable",
                            str(node),
                        ]
                    ),
                    0,
                )

        self.assertEqual(run.call_args.args[0], (str(node.resolve()), "--version"))
        self.assertEqual(
            run.call_args.kwargs["env"],
            {
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "NO_COLOR": "1",
                "PATH": os.pathsep.join(
                    (
                        str(node.resolve().parent),
                        "/opt/homebrew/bin",
                        "/usr/local/bin",
                        "/usr/bin",
                        "/bin",
                        "/usr/sbin",
                        "/sbin",
                    )
                ),
            },
        )
        self.assertEqual(
            promotion.call_args.kwargs["node_executable"], node.resolve()
        )

    def test_main_rejects_invalid_declared_node_before_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            cache = temporary / "cache"
            cache.mkdir()
            node = temporary / "node"
            node.write_text("node\n", encoding="utf-8")
            node.chmod(0o700)
            linked_node = temporary / "linked-node"
            try:
                linked_node.symlink_to(node)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            with mock.patch("tools.check_promotion.run_promotion") as promotion:
                with self.assertRaises(SystemExit):
                    main(["--npm-cache", str(cache)])
            promotion.assert_not_called()

            cases = (
                ("relative-node", None),
                (str(temporary / "missing-node"), None),
                (str(linked_node), None),
                (str(node), "v21.9.0\n"),
                (str(node), "v22.14.0\n"),
            )
            for raw, version in cases:
                with self.subTest(raw=raw, version=version):
                    with (
                        mock.patch("tools.check_promotion.run_promotion") as promotion,
                        mock.patch(
                            "tools.check_promotion.subprocess.run",
                            return_value=subprocess.CompletedProcess(
                                (str(node), "--version"),
                                0,
                                stdout=version or "",
                                stderr="",
                            ),
                        ),
                    ):
                        self.assertEqual(
                            main(
                                [
                                    "--npm-cache",
                                    str(cache),
                                    "--node-executable",
                                    raw,
                                ]
                            ),
                            1,
                        )
                        promotion.assert_not_called()

    def test_promotion_npm_cache_rejects_invalid_roots_before_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            cache = temporary / "cache"
            cache.mkdir()
            linked_cache = temporary / "linked-cache"
            try:
                linked_cache.symlink_to(cache, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            for raw in ("relative-cache", str(temporary / "missing"), str(linked_cache)):
                with self.subTest(raw=raw):
                    with self.assertRaisesRegex(
                        PromotionError, "declared npm cache is invalid"
                    ):
                        _resolve_promotion_npm_cache(raw)

    def test_promotion_npm_cache_uses_a_local_empty_argument_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            with mock.patch("tools.check_promotion.tempfile.gettempdir", return_value=str(temporary)):
                cache = _resolve_promotion_npm_cache("")

            self.assertEqual(cache, (temporary / "asterion-promotion-npm-cache").resolve())
            self.assertTrue(cache.is_dir())

    def test_closed_npm_environment_uses_only_declared_cache_configuration(self) -> None:
        hostile_environment = {
            "HOME": "/host/home",
            "HTTP_PROXY": "http://proxy.invalid",
            "HTTPS_PROXY": "http://proxy.invalid",
            "NO_PROXY": "private.invalid",
            "NODE_AUTH_TOKEN": "npm-secret",
            "NPM_CONFIG_CACHE": "/host/npm-cache",
            "NPM_CONFIG_REGISTRY": "https://private.invalid/",
            "NPM_CONFIG_USERCONFIG": "/host/.npmrc",
            "NPM_TOKEN": "npm-secret",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            workspace = temporary / "workspace"
            workspace.mkdir()
            cache = temporary / "cache"
            cache.mkdir()
            with (
                mock.patch.dict(os.environ, hostile_environment, clear=False),
            ):
                environment = _closed_npm_subprocess_environment(
                    workspace, _resolve_promotion_npm_cache(str(cache))
                )

        self.assertEqual(environment["NPM_CONFIG_CACHE"], str(cache.resolve()))
        self.assertEqual(environment["NPM_CONFIG_OFFLINE"], "true")
        self.assertEqual(
            environment["NPM_CONFIG_REGISTRY"], "https://registry.npmjs.org/"
        )
        self.assertNotIn("HOME", environment)
        for key in hostile_environment:
            with self.subTest(key=key):
                if key in {
                    "NPM_CONFIG_CACHE",
                    "NPM_CONFIG_REGISTRY",
                    "NPM_CONFIG_USERCONFIG",
                }:
                    self.assertNotEqual(environment.get(key), hostile_environment[key])
                else:
                    self.assertNotIn(key, environment)

    def test_closed_environment_uses_short_workspace_tmpdir_and_private_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            workspace.mkdir()
            environment = _closed_prime_subprocess_environment(
                workspace, node_executable=Path("/node22/bin/node")
            )

        self.assertEqual(environment["TMPDIR"], str(workspace / "t"))
        self.assertEqual(
            environment["HOME"],
            str(workspace / ".asterion-operational-env/home"),
        )
        self.assertIn(".asterion-operational-env/npm-cache", environment["NPM_CONFIG_CACHE"])


    def test_closed_npm_environment_uses_explicit_node_without_ambient_resolution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            workspace = temporary / "workspace"
            workspace.mkdir()
            cache = temporary / "cache"
            cache.mkdir()
            environment = _closed_npm_subprocess_environment(
                workspace,
                _resolve_promotion_npm_cache(str(cache)),
                node_executable=Path("/node22/bin/node"),
            )

        self.assertEqual(environment["PATH"].split(os.pathsep)[0], "/node22/bin")

    def test_default_runner_forces_sparse_cargo_registry_and_preserves_environment(self) -> None:
        result = completed(("cargo", "test"))
        injected_project_environment = {
            "PYTHONHOME": "/outside/python-home",
            "PYTHONPATH": "/outside/source",
            "PYTHONSTARTUP": "/outside/startup.py",
            "PYTHONUSERBASE": "/outside/user-base",
            "UV_NO_SYNC": "1",
            "UV_PROJECT_ENVIRONMENT": "/outside/venv",
            "VIRTUAL_ENV": "/outside/venv",
        }
        with (
            mock.patch.dict(
                os.environ,
                {
                    "ASTERION_PROMOTION_TEST_MARKER": "preserved",
                    "CARGO_HOME": "/untrusted-cargo-home",
                    **injected_project_environment,
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
        for name in injected_project_environment:
            with self.subTest(name=name):
                self.assertFalse(name in environment, name)

    def test_quick_copy_excludes_external_generated_and_cache_paths(self) -> None:
        excluded = (
            ".asterion-private",
            ".git",
            ".worktrees",
            ".venv",
            ".env",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "node_modules",
            "target",
            "3th-party",
            "worktrees",
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
            local_sdd = source / ".superpowers/sdd"
            local_sdd.mkdir(parents=True)
            (local_sdd / "report.md").write_text("local artifact\n", encoding="utf-8")
            (source / ".superpowers/keep.md").write_text(
                "retained metadata\n", encoding="utf-8"
            )

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
                self.assertFalse((cwd / ".superpowers/sdd").exists())
                self.assertTrue((cwd / ".superpowers/keep.md").is_file())
                for name in excluded:
                    self.assertFalse((cwd / name).exists(), name)
                return completed(command, acceptance_stdout(command))

            run_promotion(
                source_root=source, npm_cache=source, quick=True, runner=runner
            )

        self.assertTrue(observed_roots)
        self.assertEqual(len(set(observed_roots)), 1)
        self.assertNotEqual(observed_roots[0], source)
        self.assertFalse(observed_roots[0].exists())
        if os.name == "posix":
            self.assertEqual(
                observed_roots[0].parent.parent, Path("/tmp").resolve()
            )
            self.assertTrue(observed_roots[0].parent.name.startswith("ap-"))

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
                    npm_cache=source,
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
                    npm_cache=source,
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
                            npm_cache=source,
                            quick=True,
                            runner=lambda command, cwd: completed(command),
                        )

    def test_default_plan_runs_every_provider_free_gate_from_the_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = make_source(Path(temporary_directory))
            node = Path("/sealed/node22/bin/node")
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

            run_promotion(
                source_root=source,
                npm_cache=source,
                quick=False,
                runner=runner,
                node_executable=node,
            )

        rendered = tuple(" ".join(command) for command in commands)
        for expected in (
            "uv sync --frozen --extra dci",
            "uv run --extra dci python -m unittest -v tests.test_setup_pi tests.test_resource_setup tests.test_asterion_dci_verification",
            "uv run --extra dci python -m unittest discover -s tests -v",
            "uv run python -m compileall -q src tests tools",
            "uv run ruff check src tests tools",
            "uv build .",
            "uv run python tools/check_docs.py",
            "npm ci --offline --ignore-scripts --no-audit --no-fund --prefix packages/typescript/asterion-runtime",
            "npm run build --prefix packages/typescript/asterion-prime-extension",
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
        installed_wheel = tuple(
            command
            for command in commands
            if command[:3] == ("uv", "pip", "install")
        )
        self.assertEqual(len(installed_wheel), 1)
        self.assertFalse(any("[dci]" in item or "[prime]" in item for item in installed_wheel[0]))
        wheel_smoke = next(
            command
            for command in commands
            if len(command) == 3
            and command[1] == "-c"
            and "cwd_exec.py" in command[2]
        )
        self.assertIn("PYTHONHOME", wheel_smoke[2])
        self.assertIn("PYTHONPATH", wheel_smoke[2])
        self.assertIn("'-I', '-S'", wheel_smoke[2])
        protocol_smokes = tuple(
            command
            for command in commands
            if len(command) == 3
            and command[1] == "-c"
            and "asterion.capability/v1" in command[2]
        )
        self.assertEqual(len(protocol_smokes), 1)
        smoke_source = protocol_smokes[0][2]
        self.assertIn("'applications/*/assemblies/*.json'", smoke_source)
        self.assertIn("'capabilities/*/capability-package.json'", smoke_source)
        self.assertIn("'capabilities/*/manifests/*.json'", smoke_source)
        self.assertIn(
            "'capabilities/dci/payload/capability-package.json'",
            smoke_source,
        )
        self.assertIn(
            "'capabilities/dci/payload/benchmark-suites/*.json'",
            smoke_source,
        )
        self.assertIn("declared_suite_paths", smoke_source)
        self.assertIn("descriptor_payload['benchmark_suites']", smoke_source)
        self.assertIn("root.glob(pattern)", smoke_source)
        self.assertIn("capability_sdk/templates/minimal", smoke_source)
        self.assertIn("asterion.capability_sdk", smoke_source)
        self.assertIn("asterion.capability_packages.payload", smoke_source)
        for schema_path in (
            "asterion/schemas/agent-system/v1/agent-system.schema.json",
            "asterion/schemas/control-plane/v1/control-plane-manifest.schema.json",
            "asterion/schemas/agent-control/v1/command.schema.json",
            "asterion/schemas/agent-control/v1/event.schema.json",
            "asterion/schemas/session-context/v1/command.schema.json",
            "asterion/schemas/session-context/v1/receipt.schema.json",
            "asterion/schemas/operation/v1/doctor-request.schema.json",
        ):
            self.assertIn(schema_path, smoke_source)
        for expected in (
            "applications/controlled_code/assemblies/controlled-code-validation.json",
            "applications/dci_agent_lite/assemblies/dci-complete-application-claude.json",
            "applications/dci_agent_lite/assemblies/dci-complete-application-pi.json",
            "applications/dci_agent_lite/assemblies/dci-local-benchmark-application-claude.json",
            "applications/dci_agent_lite/assemblies/dci-local-benchmark-application-pi.json",
            "applications/dci_agent_lite/assemblies/dci-local-research.json",
            "applications/dci_agent_lite/assemblies/dci-research-capability-claude.json",
            "applications/dci_agent_lite/assemblies/dci-research-capability.json",
            "capabilities/controlled_code/capability-package.json",
            "capabilities/controlled_code/manifests/code-quality-evaluation.json",
            "capabilities/controlled_code/manifests/code-quality-workflow.json",
            "capabilities/controlled_code/manifests/controlled-code-policy.json",
            "capabilities/controlled_code/manifests/execution-audit-observability.json",
            "capabilities/dci/payload/capability-package.json",
            "capabilities/dci/payload/capabilities/dci-analysis.json",
            "capabilities/dci/payload/capabilities/dci-benchmark.json",
            "capabilities/dci/payload/capabilities/dci-evaluation.json",
            "capabilities/dci/payload/capabilities/dci-export.json",
            "capabilities/dci/payload/capabilities/dci-research.json",
            "capabilities/dci/payload/capabilities/local-corpus-policy.json",
            "capabilities/dci/payload/capabilities/protocol-observability.json",
        ):
            self.assertIn(expected, smoke_source)
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
        self.assertEqual(roots[0], roots[0].resolve())
        command_text = "\n".join(rendered).lower()
        self.assertNotIn("prime-verify-bounded", command_text)
        self.assertNotIn("--level bounded", command_text)
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

    def test_copied_project_npm_commands_use_the_declared_offline_cache(self) -> None:
        calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

        def fake_run(
            command: tuple[str, ...], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            environment = kwargs["env"]
            assert isinstance(environment, dict)
            calls.append((command, environment))
            cwd = kwargs["cwd"]
            assert isinstance(cwd, Path)
            if command == ("uv", "build", "."):
                dist = cwd / "dist"
                dist.mkdir()
                (dist / "asterion-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
            return completed(command, acceptance_stdout(command))

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = make_source(temporary)
            cache = temporary / "operator-npm-cache"
            cache.mkdir()
            with (
                mock.patch("tools.check_promotion.subprocess.run", side_effect=fake_run),
            ):
                run_promotion(
                    source_root=source,
                    npm_cache=cache,
                    node_executable=Path("/node22/bin/node"),
                )

        npm_calls = tuple(
            (command, environment)
            for command, environment in calls
            if command[0] == "npm"
        )
        self.assertTrue(npm_calls)
        for command, environment in npm_calls:
            with self.subTest(command=command):
                self.assertEqual(environment["NPM_CONFIG_CACHE"], str(cache.resolve()))
                self.assertEqual(environment["NPM_CONFIG_OFFLINE"], "true")
                self.assertNotIn("--prefer-offline", command)
        for command, _ in npm_calls:
            if command[:2] == ("npm", "ci"):
                self.assertEqual(
                    command[2:6],
                    ("--offline", "--ignore-scripts", "--no-audit", "--no-fund"),
                )

    def test_full_promotion_default_runner_seals_python_child_environments(self) -> None:
        calls: list[tuple[tuple[str, ...], dict[str, str], str, str]] = []
        ambient = {
            "NPM_CONFIG_CACHE": "/ambient/uppercase-cache",
            "npm_config_cache": "/ambient/lowercase-cache",
            "NPM_CONFIG_OFFLINE": "false",
            "npm_config_offline": "false",
            "NPM_TOKEN": "npm-secret",
            "NODE_AUTH_TOKEN": "node-secret",
        }

        def fake_run(
            command: tuple[str, ...], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            environment = kwargs["env"]
            assert isinstance(environment, dict)
            calls.append((command, environment, "", ""))
            cwd = kwargs["cwd"]
            assert isinstance(cwd, Path)
            if command == ("uv", "build", "."):
                dist = cwd / "dist"
                dist.mkdir()
                (dist / "asterion-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
            return completed(command, acceptance_stdout(command))

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = make_source(temporary)
            cache = temporary / "operator-npm-cache"
            cache.mkdir()
            with (
                mock.patch.dict(os.environ, ambient, clear=False),
                mock.patch("tools.check_promotion.subprocess.run", side_effect=fake_run),
            ):
                run_promotion(
                    source_root=source,
                    npm_cache=cache,
                    node_executable=Path("/node22/bin/node"),
                )

        canonical_cache = str(cache.resolve())
        python_children = tuple(
            (command, environment)
            for command, environment, _, _ in calls
            if command[:2] == ("uv", "run")
            or command[0].endswith("/python")
            or command[0].endswith("/asterion")
        )
        self.assertTrue(python_children)
        for command, environment in python_children:
            with self.subTest(command=command):
                self.assertEqual(environment["NPM_CONFIG_CACHE"], canonical_cache)
                self.assertEqual(environment["NPM_CONFIG_OFFLINE"], "true")
                self.assertNotIn("npm_config_cache", environment)
                self.assertNotIn("npm_config_offline", environment)
                self.assertNotIn("NPM_TOKEN", environment)
                self.assertNotIn("NODE_AUTH_TOKEN", environment)

    def test_npm_cache_miss_does_not_retry_online(self) -> None:
        npm_commands: list[tuple[str, ...]] = []

        def fake_run(
            command: tuple[str, ...], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if command[0] == "npm":
                npm_commands.append(command)
                return subprocess.CompletedProcess(
                    command, 1, stdout="", stderr="cache miss"
                )
            return completed(command, acceptance_stdout(command))

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = make_source(temporary)
            cache = temporary / "operator-npm-cache"
            cache.mkdir()
            with (
                mock.patch("tools.check_promotion.subprocess.run", side_effect=fake_run),
                self.assertRaises(PromotionError),
            ):
                run_promotion(
                    source_root=source,
                    npm_cache=cache,
                    node_executable=Path("/node22/bin/node"),
                )

        self.assertEqual(len(npm_commands), 1)
        self.assertEqual(npm_commands[0][:2], ("npm", "ci"))
        self.assertIn("--offline", npm_commands[0])

    def test_npm_cache_miss_error_does_not_disclose_cache_path(self) -> None:
        npm_commands: list[tuple[str, ...]] = []
        npm_environments: list[dict[str, str]] = []

        def fake_run(
            command: tuple[str, ...], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if command[0] == "npm":
                environment = kwargs["env"]
                assert isinstance(environment, dict)
                npm_commands.append(command)
                npm_environments.append(environment)
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout="",
                    stderr=f"npm ERR! code ENOTCACHED\nnpm ERR! cache {_cache_path}\n",
                )
            return completed(command, acceptance_stdout(command))

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = make_source(temporary)
            cache = temporary / "operator-npm-cache"
            cache.mkdir()
            _cache_path = str(cache.resolve())
            with (
                mock.patch("tools.check_promotion.subprocess.run", side_effect=fake_run),
                self.assertRaises(PromotionError) as raised,
            ):
                run_promotion(
                    source_root=source,
                    npm_cache=cache,
                    node_executable=Path("/node22/bin/node"),
                )

        self.assertEqual(len(npm_commands), 1)
        self.assertEqual(npm_commands[0][:2], ("npm", "ci"))
        self.assertIn("--offline", npm_commands[0])
        self.assertEqual(npm_environments[0]["NPM_CONFIG_CACHE"], _cache_path)
        self.assertEqual(npm_environments[0]["NPM_CONFIG_OFFLINE"], "true")
        self.assertNotIn(_cache_path, str(raised.exception))

    def test_full_promotion_python_environment_keeps_real_npm_ci_offline(self) -> None:
        import http.server
        import threading

        captured_environment: dict[str, str] | None = None
        requests = 0

        def fake_run(
            command: tuple[str, ...], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            nonlocal captured_environment
            environment = kwargs["env"]
            assert isinstance(environment, dict)
            if (
                captured_environment is None
                and command[:2] == ("uv", "run")
                and "python" in command
            ):
                captured_environment = dict(environment)
            cwd = kwargs["cwd"]
            assert isinstance(cwd, Path)
            if command == ("uv", "build", "."):
                dist = cwd / "dist"
                dist.mkdir()
                (dist / "asterion-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
            return completed(command, acceptance_stdout(command))

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                nonlocal requests
                requests += 1
                self.send_response(500)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = make_source(temporary)
            cache = temporary / "empty-npm-cache"
            cache.mkdir()
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "NPM_CONFIG_CACHE": "/ambient/uppercase-cache",
                        "npm_config_cache": "/ambient/lowercase-cache",
                        "NPM_CONFIG_OFFLINE": "false",
                        "npm_config_offline": "false",
                    },
                    clear=False,
                ),
                mock.patch("tools.check_promotion.subprocess.run", side_effect=fake_run),
            ):
                run_promotion(
                    source_root=source,
                    npm_cache=cache,
                    node_executable=Path("/node22/bin/node"),
                )

            self.assertIsNotNone(captured_environment)
            assert captured_environment is not None
            canonical_cache = str(cache.resolve())
            self.assertEqual(captured_environment["NPM_CONFIG_CACHE"], canonical_cache)
            self.assertEqual(captured_environment["NPM_CONFIG_OFFLINE"], "true")
            self.assertNotIn("npm_config_cache", captured_environment)
            self.assertNotIn("npm_config_offline", captured_environment)

            package_root = temporary / "offline-npm-fixture"
            package_root.mkdir()
            (package_root / "package.json").write_text(
                json.dumps(
                    {
                        "private": True,
                        "dependencies": {
                            "invalid-test-fixture": "1.0.0",
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            host, port = server.server_address
            (package_root / "package-lock.json").write_text(
                json.dumps(
                    {
                        "name": "offline-npm-fixture",
                        "lockfileVersion": 3,
                        "requires": True,
                        "packages": {
                            "": {
                                "dependencies": {
                                    "invalid-test-fixture": "1.0.0",
                                },
                            },
                            "node_modules/invalid-test-fixture": {
                                "version": "1.0.0",
                                "resolved": f"http://{host}:{port}/invalid-test-fixture-1.0.0.tgz",
                                "integrity": "sha512-invalid",
                            },
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                npm_environment = dict(captured_environment)
                npm_environment["NPM_CONFIG_REGISTRY"] = f"http://{host}:{port}/"
                completed_process = subprocess.run(
                    ("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"),
                    cwd=package_root,
                    env=npm_environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertNotEqual(completed_process.returncode, 0)
        self.assertIn("ENOTCACHED", completed_process.stderr + completed_process.stdout)
        self.assertEqual(requests, 0)

    def test_quick_plan_uses_valid_discovery_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = make_source(Path(temporary_directory))
            commands: list[tuple[str, ...]] = []

            def runner(
                command: tuple[str, ...], cwd: Path
            ) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                return completed(command, acceptance_stdout(command))

            run_promotion(
                source_root=source, npm_cache=source, quick=True, runner=runner
            )

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
                    run_promotion(
                        source_root=source,
                        npm_cache=source,
                        quick=False,
                        runner=runner,
                        node_executable=Path("/node22/bin/node"),
                    )


def is_acceptance(command: tuple[str, ...]) -> bool:
    return "verify" in command and "acceptance" in command


def acceptance_stdout(command: tuple[str, ...]) -> str:
    if not is_acceptance(command):
        if "validate" in command and "capability" in command:
            return json.dumps({"payload_sha256": "1" * 64})
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
