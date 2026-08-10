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
    setup_prime_source,
    verify_prime_source,
)


PROJECT = Path(__file__).resolve().parents[1]
LOCK_PATH = (
    PROJECT / "packages/typescript/prime-gateway/resources/prime-artifact-lock.json"
)
PINNED_SOURCE = PROJECT / "3th-party/prime-agent"


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
        if command[:2] == ("git", "rev-parse"):
            return _completed(
                command,
                stdout="a18809e00ea30638584d87b3afea7285a9d7296c\n",
            )
        if command[:2] == ("git", "status"):
            return _completed(command, stdout="")
        if command == ("npm", "ci"):
            return _completed(command, returncode=self.npm_returncode)
        if command == ("npm", "run", "build"):
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

    def test_digest_locked_export_without_git_metadata_skips_git_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, lock_path = _fixture_source(Path(directory))
            (source / ".git").rmdir()
            runner = RecordingRunner()

            report = verify_prime_source(source, lock_path=lock_path, runner=runner)

        self.assertFalse(report.installed)
        self.assertFalse(any(call[0][0] == "git" for call in runner.calls))

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
        self.assertIn(("npm", "run", "build"), (call[0] for call in runner.calls))

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
