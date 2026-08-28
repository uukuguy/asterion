from __future__ import annotations

import subprocess
import tempfile
import unittest
import os
import json
import shutil
from collections.abc import Sequence
from pathlib import Path

from tools.setup_prime_agent import (
    OperationalHarnessError,
    _OFFLINE_BUILD_COMMANDS,
    _resolve_operational_node,
    verify_operational_locks,
)


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "packages/typescript/prime-gateway/resources"
PINNED_ROOT = ROOT / "3th-party/prime-agent"
REAL_HARNESS = ROOT / "tests/fixtures/prime_gateway/v1/real-prime-operations.mjs"


def _external_pinned_root(parent: Path) -> Path:
    target = parent / "prime-agent"
    subprocess.run(
        ("git", "-C", str(PINNED_ROOT), "worktree", "add", "--detach", str(target), "HEAD"),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    os.symlink(PINNED_ROOT / "node_modules", target / "node_modules")
    return target


def _promotion_like_prime_root(parent: Path) -> tuple[Path, Path]:
    project = parent / "promotion-copy"
    (project / "schemas").mkdir(parents=True)
    (project / "packages").mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\nname = \"asterion\"\n", encoding="utf-8"
    )
    target = project / "3th-party/prime-agent"
    target.parent.mkdir()
    subprocess.run(
        ("git", "-C", str(PINNED_ROOT), "worktree", "add", "--detach", str(target), "HEAD"),
        check=True, capture_output=True, text=True, timeout=20,
    )
    resources = project / "packages/typescript/prime-gateway/resources"
    resources.parent.mkdir(parents=True)
    shutil.copytree(RESOURCE_ROOT, resources, symlinks=False)
    return target, resources


def _rebuild_locked_workspaces(root: Path) -> None:
    node = _resolve_operational_node()
    environment = dict(os.environ)
    environment["PATH"] = f"{node.parent}:{environment.get('PATH', '')}"
    try:
        for command in _OFFLINE_BUILD_COMMANDS:
            completed = subprocess.run(
                command,
                cwd=root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if completed.returncode != 0:
                raise AssertionError("external locked Prime workspace build failed")
    finally:
        (root / "node_modules").unlink(missing_ok=True)


def _materialize_locked_dist(root: Path) -> None:
    shutil.copytree(
        PINNED_ROOT / "packages/coding-agent/dist",
        root / "packages/coding-agent/dist",
        symlinks=False,
    )


def _fixture_command(resources: Path, source: Path) -> Sequence[str]:
    return (
        str(_resolve_operational_node()), str(REAL_HARNESS),
        "--resource-root", str(resources), "--source-root", str(source),
        "--package", "auth",
    )


def _run_fixture(resources: Path, source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _fixture_command(resources, source),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestPrimeOperationalHarness(unittest.TestCase):
    def test_copied_repository_resource_runs_only_against_external_pinned_prime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-run-") as temporary:
            parent = Path(temporary)
            root = _external_pinned_root(parent)
            resources = parent / "resources"
            shutil.copytree(RESOURCE_ROOT, resources, symlinks=False)
            try:
                _rebuild_locked_workspaces(root)
                reports = []
                for _ in range(2):
                    completed = _run_fixture(resources, root)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertNotIn(str(root), completed.stdout)
                    self.assertNotIn(str(resources), completed.stdout)
                    reports.append(json.loads(completed.stdout))
                self.assertEqual(reports[0], reports[1])
                self.assertEqual(reports[0]["node_runtime"], "v22.23.2")
                self.assertEqual(reports[0]["effect_counts"], {
                    "credential_reads": 0, "fake_coordinator_calls": 0,
                    "host_service_calls": 0, "injected_sink_calls": 0,
                    "mock_refresh_calls": 0, "network_requests": 0,
                    "provider_operations": 0, "reconcile_calls": 0,
                    "retained_processes": 0, "stdout_writes": 0,
                    "unauthorized_uploads": 0,
                })
            finally:
                subprocess.run(
                    ("git", "-C", str(PINNED_ROOT), "worktree", "remove", "--force", str(root)),
                    check=False, capture_output=True, text=True, timeout=20,
                )

    def test_copied_resource_rejects_repository_prime_root_in_node_and_python(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-repository-") as temporary:
            resources = Path(temporary) / "resources"
            shutil.copytree(RESOURCE_ROOT, resources, symlinks=False)
            rejected = _run_fixture(resources, PINNED_ROOT)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertNotIn(str(PINNED_ROOT), rejected.stdout + rejected.stderr)
            with self.assertRaises(OperationalHarnessError):
                verify_operational_locks(PINNED_ROOT, resources)

    def test_promotion_like_asterion_tree_rejects_nested_prime_in_node_and_python(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-promotion-") as temporary:
            root, resources = _promotion_like_prime_root(Path(temporary))
            try:
                _materialize_locked_dist(root)
                rejected = _run_fixture(resources, root)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertNotIn(str(root), rejected.stdout + rejected.stderr)
                with self.assertRaises(OperationalHarnessError):
                    verify_operational_locks(root, resources)
            finally:
                subprocess.run(
                    ("git", "-C", str(PINNED_ROOT), "worktree", "remove", "--force", str(root)),
                    check=False, capture_output=True, text=True, timeout=20,
                )

    def test_fixture_rejects_symlink_source_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-symlink-") as temporary:
            parent = Path(temporary)
            root = _external_pinned_root(parent)
            resources = parent / "resources"
            link = parent / "source-link"
            shutil.copytree(RESOURCE_ROOT, resources, symlinks=False)
            link.symlink_to(root, target_is_directory=True)
            try:
                _rebuild_locked_workspaces(root)
                rejected = _run_fixture(resources, link)
                self.assertNotEqual(rejected.returncode, 0)
                with self.assertRaises(OperationalHarnessError):
                    verify_operational_locks(link, resources)
            finally:
                subprocess.run(
                    ("git", "-C", str(PINNED_ROOT), "worktree", "remove", "--force", str(root)),
                    check=False, capture_output=True, text=True, timeout=20,
                )

    def test_fixture_rejects_duplicate_source_and_built_lock_keys(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-duplicate-") as temporary:
            parent = Path(temporary)
            root = _external_pinned_root(parent)
            try:
                _rebuild_locked_workspaces(root)
                for relative in (
                    "packages/coding-agent/src/core/auth-storage.ts",
                    "packages/coding-agent/dist/core/auth-storage.js",
                ):
                    with self.subTest(relative=relative):
                        resources = parent / relative.rsplit("/", 1)[-1]
                        shutil.copytree(RESOURCE_ROOT, resources, symlinks=False)
                        lock = resources / "prime-operational-module-lock.json"
                        body = lock.read_text(encoding="utf-8")
                        line = next(item for item in body.splitlines(keepends=True) if f'"{relative}"' in item)
                        lock.write_text(body.replace(line, line + line, 1), encoding="utf-8")
                        rejected = _run_fixture(resources, root)
                        self.assertNotEqual(rejected.returncode, 0)
                        self.assertNotIn(relative, rejected.stdout + rejected.stderr)
                        with self.assertRaises(OperationalHarnessError):
                            verify_operational_locks(root, resources)
            finally:
                subprocess.run(
                    ("git", "-C", str(PINNED_ROOT), "worktree", "remove", "--force", str(root)),
                    check=False, capture_output=True, text=True, timeout=20,
                )

    def test_fixture_and_python_reject_reordered_operational_lock_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-order-") as temporary:
            parent = Path(temporary)
            root = _external_pinned_root(parent)
            resources = parent / "resources"
            shutil.copytree(RESOURCE_ROOT, resources, symlinks=False)
            try:
                _rebuild_locked_workspaces(root)
                lock = resources / "prime-operational-module-lock.json"
                parsed = json.loads(lock.read_text(encoding="utf-8"))
                reordered = dict(reversed(tuple(parsed.items())))
                lock.write_text(json.dumps(reordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                rejected = _run_fixture(resources, root)
                self.assertNotEqual(rejected.returncode, 0)
                with self.assertRaises(OperationalHarnessError):
                    verify_operational_locks(root, resources)
            finally:
                subprocess.run(
                    ("git", "-C", str(PINNED_ROOT), "worktree", "remove", "--force", str(root)),
                    check=False, capture_output=True, text=True, timeout=20,
                )

    def test_harness_rejects_source_or_built_distribution_anchor_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-") as temporary:
            parent = Path(temporary)
            root = _external_pinned_root(parent)
            resources = parent / "resources"
            shutil.copytree(RESOURCE_ROOT, resources, symlinks=False)
            try:
                _rebuild_locked_workspaces(root)
                locks = verify_operational_locks(root, resources)
                self.assertIn("packages/coding-agent/dist/core/auth-storage.js", locks.built_anchor_digests)
                target = root / "packages/coding-agent/dist/core/auth-storage.js"
                target.write_text(target.read_text(encoding="utf-8") + "\n// drift\n", encoding="utf-8")
                with self.assertRaises(OperationalHarnessError):
                    verify_operational_locks(root, resources)
            finally:
                subprocess.run(
                    ("git", "-C", str(PINNED_ROOT), "worktree", "remove", "--force", str(root)),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )

    def test_harness_rejects_the_repository_checkout(self) -> None:
        with self.assertRaises(OperationalHarnessError):
            verify_operational_locks(PINNED_ROOT, RESOURCE_ROOT)
