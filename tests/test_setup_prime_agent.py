from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.setup_prime_agent import (
    PrimeSetupError,
    derive_prime_rlm_runtime,
    setup_prime_source,
    verify_prime_source,
)


PROJECT = Path(__file__).resolve().parents[1]
LOCK_PATH = (
    PROJECT / "packages/typescript/prime-gateway/resources/prime-artifact-lock.json"
)
PINNED_SOURCE = PROJECT / "3th-party/prime-agent"
OFFLINE_BUILD_COMMANDS = (
    ("npm", "--prefix", "packages/tui", "run", "build"),
    (
        "node_modules/.bin/tsgo",
        "-p",
        "packages/ai/tsconfig.build.json",
    ),
    ("npm", "--prefix", "packages/agent", "run", "build"),
    ("npm", "--prefix", "packages/coding-agent", "run", "build"),
)


def _fixture_source(root: Path) -> tuple[Path, Path]:
    source = root / "prime-source"
    contents = {
        "package-lock.json": '{"name":"prime-fixture"}\n',
        "packages/coding-agent/package.json": (
            '{"name":"@earendil-works/pi-coding-agent","version":"0.7.1"}\n'
        ),
        "packages/coding-agent/src/modes/daemon/daemon-client.ts": (
            "export const fixture = true;\n"
        ),
        "packages/coding-agent/src/modes/daemon/daemon-protocol.ts": (
            "export const protocol = 7;\n"
        ),
        "prime-agent.sh": "#!/bin/sh\nexit 0\n",
    }
    for relative, content in contents.items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    (source / "prime-agent.sh").chmod(0o755)
    (source / ".git").mkdir()
    lock_path = root / "prime-artifact-lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "format": "asterion.prime-artifact-lock/v1",
                "source_commit": "a18809e00ea30638584d87b3afea7285a9d7296c",
                "package_name": "@earendil-works/pi-coding-agent",
                "package_version": "0.7.1",
                "daemon_protocol": 7,
                "daemon_schema_revision": 14,
                "daemon_schema_id": "protocol-7-schema-14-816309b1cd50",
                "files": {
                    relative: hashlib.sha256(content.encode()).hexdigest()
                    for relative, content in sorted(contents.items())
                },
            }
        )
    )
    return source, lock_path


def _rlm_runtime_fixture(root: Path) -> tuple[Path, Path, Path]:
    source, lock_path = _fixture_source(root)
    entry = source / "packages/coding-agent/dist/bundle/cli.js"
    binding = source / "packages/coding-agent/dist/bundle/chunk-binding.js"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text('import "./chunk-binding.js";\n')
    binding.write_text('const binding = "native-host";\nconst delivery = "native-delivery";\n')
    shim_path = root / "prime-rlm-host-shim.json"
    shim_path.write_text(
        json.dumps(
            {
                "format": "asterion.prime-rlm-host-shim/v1",
                "patches": [
                    {
                        "anchor": 'const binding = "native-host";',
                        "replacement": 'const binding = "asterion-host";',
                    },
                    {
                        "anchor": 'const delivery = "native-delivery";',
                        "replacement": 'const delivery = "asterion-delivery";',
                    },
                ],
                "target": "packages/coding-agent/dist/bundle/chunk-binding.js",
            },
            sort_keys=True,
        )
    )
    lock = json.loads(lock_path.read_text())
    closure = {
        "packages/coding-agent/dist/bundle/chunk-binding.js": hashlib.sha256(
            binding.read_bytes()
        ).hexdigest(),
        "packages/coding-agent/dist/bundle/cli.js": hashlib.sha256(
            entry.read_bytes()
        ).hexdigest(),
    }
    derived_binding = (
        binding.read_text()
        .replace("native-host", "asterion-host")
        .replace("native-delivery", "asterion-delivery")
    )
    lock["rlm_runtime"] = {
        "entry": "packages/coding-agent/dist/bundle/cli.js",
        "binding_chunk": "packages/coding-agent/dist/bundle/chunk-binding.js",
        "closure": closure,
        "derived_closure": {
            **closure,
            "packages/coding-agent/dist/bundle/chunk-binding.js": hashlib.sha256(
                derived_binding.encode()
            ).hexdigest(),
        },
        "patch_sha256": hashlib.sha256(shim_path.read_bytes()).hexdigest(),
    }
    lock_path.write_text(json.dumps(lock))
    return source, lock_path, shim_path


def _completed(
    command: tuple[str, ...], returncode: int = 0, stdout: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")


class RecordingRunner:
    def __init__(
        self,
        *,
        node_version: str = "v22.8.0",
        npm_returncode: int = 0,
        build_returncode: int = 0,
    ):
        self.node_version = node_version
        self.npm_returncode = npm_returncode
        self.build_returncode = build_returncode
        self.calls: list[tuple[tuple[str, ...], Path, dict[str, str]]] = []

    def __call__(
        self, command: tuple[str, ...], cwd: Path, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, cwd, dict(env)))
        if command[-1] == "--version":
            return _completed(command, stdout=f"{self.node_version}\n")
        if command == ("git", "rev-parse", "--show-toplevel"):
            return _completed(command, stdout=f"{cwd}\n")
        if command == ("git", "rev-parse", "HEAD"):
            return _completed(
                command,
                stdout="a18809e00ea30638584d87b3afea7285a9d7296c\n",
            )
        if command[:2] == ("git", "status"):
            return _completed(command, stdout="")
        if command == ("npm", "ci"):
            return _completed(command, returncode=self.npm_returncode)
        if command == ("npm", "run", "build") or command in OFFLINE_BUILD_COMMANDS:
            return _completed(command, returncode=self.build_returncode)
        raise AssertionError(command)


class TestSetupPrimeAgent(unittest.TestCase):
    def test_check_verifies_exact_source_without_install_or_path_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, lock_path = _fixture_source(Path(directory))
            runner = RecordingRunner()

            report = verify_prime_source(source, lock_path=lock_path, runner=runner)

        self.assertEqual(
            report.source_commit, "a18809e00ea30638584d87b3afea7285a9d7296c"
        )
        self.assertEqual(report.package_version, "0.7.1")
        self.assertNotIn(str(source), repr(report))
        self.assertFalse(any(call[0] == ("npm", "ci") for call in runner.calls))

    def test_export_without_git_metadata_is_rejected_before_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, lock_path = _fixture_source(Path(directory))
            (source / ".git").rmdir()
            runner = RecordingRunner()

            with self.assertRaises(PrimeSetupError):
                verify_prime_source(source, lock_path=lock_path, runner=runner)

        self.assertEqual(runner.calls, [])

    def test_setup_runs_npm_ci_with_a_closed_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, lock_path = _fixture_source(Path(directory))
            runner = RecordingRunner()
            with mock.patch.dict(
                os.environ,
                {
                    "PATH": os.environ.get("PATH", ""),
                    "HOME": str(Path(directory) / "home"),
                    "OPENAI_API_KEY": "SENTINEL_SECRET",
                    "NPM_TOKEN": "SENTINEL_SECRET",
                    "ASTERION_PRIVATE": "SENTINEL_SECRET",
                },
                clear=True,
            ):
                setup_prime_source(source, lock_path=lock_path, runner=runner)

        npm_call = next(call for call in runner.calls if call[0] == ("npm", "ci"))
        self.assertNotIn("OPENAI_API_KEY", npm_call[2])
        self.assertNotIn("NPM_TOKEN", npm_call[2])
        self.assertNotIn("ASTERION_PRIVATE", npm_call[2])
        self.assertNotIn("SENTINEL_SECRET", repr(npm_call))
        self.assertIn(OFFLINE_BUILD_COMMANDS[-1], (call[0] for call in runner.calls))

    def test_setup_builds_locked_workspaces_without_live_catalog_generation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, lock_path = _fixture_source(Path(directory))
            runner = RecordingRunner()

            setup_prime_source(source, lock_path=lock_path, runner=runner)

        commands = tuple(call[0] for call in runner.calls)
        self.assertNotIn(("npm", "run", "build"), commands)
        self.assertNotIn("generate-models", repr(commands))
        build_offset = commands.index(OFFLINE_BUILD_COMMANDS[0])
        self.assertEqual(
            commands[build_offset : build_offset + len(OFFLINE_BUILD_COMMANDS)],
            OFFLINE_BUILD_COMMANDS,
        )

    def test_setup_derives_the_locked_rlm_runtime_after_the_ordinary_build(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, lock_path, shim_path = _rlm_runtime_fixture(Path(directory))
            setup_prime_source(
                source,
                lock_path=lock_path,
                rlm_shim_path=shim_path,
                runner=RecordingRunner(),
            )

            binding = source / "packages/coding-agent/dist/bundle/chunk-binding.js"
            self.assertIn("asterion-host", binding.read_text())

    def test_setup_revalidates_after_install_and_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            for mutation_command in (("npm", "ci"), OFFLINE_BUILD_COMMANDS[-1]):
                source, lock_path = _fixture_source(parent / "-".join(mutation_command))
                runner = RecordingRunner()

                def mutating_runner(command, cwd, env):
                    completed = runner(command, cwd, env)
                    if command == mutation_command:
                        (cwd / "prime-agent.sh").write_text("SENTINEL_SECRET\n")
                    return completed

                with (
                    self.subTest(command=mutation_command),
                    self.assertRaises(PrimeSetupError) as raised,
                ):
                    setup_prime_source(
                        source, lock_path=lock_path, runner=mutating_runner
                    )
                self.assertNotIn(str(source), str(raised.exception))
                self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
                if mutation_command == ("npm", "ci"):
                    self.assertNotIn(
                        OFFLINE_BUILD_COMMANDS[0],
                        (call[0] for call in runner.calls),
                    )

    def test_derives_locked_rlm_bundle_without_mutating_prime_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, lock_path, shim_path = _rlm_runtime_fixture(Path(directory))
            runner = RecordingRunner()
            source_file = source / "packages/coding-agent/src/modes/daemon/daemon-client.ts"
            original_source = source_file.read_bytes()

            runtime_entry = derive_prime_rlm_runtime(
                source,
                lock_path=lock_path,
                shim_path=shim_path,
                runner=runner,
            )
            repeated_entry = derive_prime_rlm_runtime(
                source,
                lock_path=lock_path,
                shim_path=shim_path,
                runner=runner,
            )

            self.assertEqual(runtime_entry, repeated_entry)
            self.assertEqual(source_file.read_bytes(), original_source)
            self.assertIn(
                "asterion-host",
                (source / "packages/coding-agent/dist/bundle/chunk-binding.js").read_text(),
            )
            self.assertIn(
                "asterion-delivery",
                (source / "packages/coding-agent/dist/bundle/chunk-binding.js").read_text(),
            )
            self.assertTrue(
                any(call[0][:2] == ("git", "status") for call in runner.calls)
            )

    def test_shipped_rlm_hunk_loads_the_private_host_shim_before_binding(self) -> None:
        patch = json.loads(
            (PROJECT / "packages/typescript/prime-gateway/resources/prime-rlm-host-shim.json").read_text()
        )["patches"][0]
        replacement = patch["replacement"]

        self.assertIn("asterion-rlm-host-shim.mjs", replacement)
        self.assertIn("createRlmHostClient", replacement)
        self.assertIn("wrapSubagentRuntimeHost", replacement)
        self.assertLess(
            replacement.index("createRlmHostClient"),
            replacement.index("setSubagentRuntimeHost"),
        )

    def test_derivation_rejects_runtime_anchor_drift_without_private_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, lock_path, shim_path = _rlm_runtime_fixture(Path(directory))
            (source / "packages/coding-agent/dist/bundle/chunk-binding.js").write_text(
                "SENTINEL_SECRET\n"
            )

            with self.assertRaises(PrimeSetupError) as raised:
                derive_prime_rlm_runtime(
                    source,
                    lock_path=lock_path,
                    shim_path=shim_path,
                    runner=RecordingRunner(),
                )

        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    def test_drift_old_node_dirty_tree_and_install_failure_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            cases = (
                ("digest", RecordingRunner(), False),
                ("old-node", RecordingRunner(node_version="v22.7.9"), False),
                ("unsupported-node", RecordingRunner(node_version="v23.11.0"), False),
                ("npm-failure", RecordingRunner(npm_returncode=1), True),
                ("build-failure", RecordingRunner(build_returncode=1), True),
            )
            for name, runner, install in cases:
                source, lock_path = _fixture_source(parent / name)
                if name == "digest":
                    (source / "prime-agent.sh").write_text("SENTINEL_SECRET\n")
                with (
                    self.subTest(name=name),
                    self.assertRaises(PrimeSetupError) as raised,
                ):
                    if install:
                        setup_prime_source(source, lock_path=lock_path, runner=runner)
                    else:
                        verify_prime_source(source, lock_path=lock_path, runner=runner)
                self.assertNotIn(str(source), str(raised.exception))
                self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

            clean_source, clean_lock = _fixture_source(parent / "dirty")
            dirty = RecordingRunner()

            def dirty_runner(command, cwd, env):
                if command[:2] == ("git", "status"):
                    return _completed(command, stdout=" M private-file\n")
                return dirty(command, cwd, env)

            with self.assertRaises(PrimeSetupError):
                verify_prime_source(
                    clean_source, lock_path=clean_lock, runner=dirty_runner
                )

    def test_repository_pinned_source_matches_production_lock_when_available(
        self,
    ) -> None:
        if not PINNED_SOURCE.is_dir():
            self.skipTest("external pinned Prime checkout is unavailable")

        report = verify_prime_source(
            PINNED_SOURCE,
            lock_path=LOCK_PATH,
            runner=RecordingRunner(node_version="v22.19.0"),
        )

        self.assertEqual(
            report.source_commit,
            "a18809e00ea30638584d87b3afea7285a9d7296c",
        )
        self.assertFalse(report.installed)


if __name__ == "__main__":
    unittest.main()
