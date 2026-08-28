from __future__ import annotations

import subprocess
import tempfile
import unittest
import os
import json
import shutil
import hashlib
from collections.abc import Sequence
from pathlib import Path

from tools.setup_prime_agent import (
    OperationalHarnessError,
    PINNED_PRIME_COMMIT,
    _OFFLINE_BUILD_COMMANDS,
    _operational_dependency_tree_digest,
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
    return target


def _clean_pinned_clone(parent: Path, name: str) -> Path:
    """Create the no-hardlinks clone used by the promotion binder."""

    target = parent / name / "prime-agent"
    target.parent.mkdir()
    subprocess.run(
        ("git", "clone", "--no-hardlinks", "--no-checkout", str(PINNED_ROOT), str(target)),
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    subprocess.run(
        ("git", "checkout", "--detach", PINNED_PRIME_COMMIT),
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
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
        installed = subprocess.run(
            ("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"),
            cwd=root, env=environment, check=False, capture_output=True, text=True, timeout=120,
        )
        if installed.returncode != 0:
            raise AssertionError("external locked Prime dependency install failed")
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
        _materialize_operational_dependency_tree(root.parent, root)
    finally:
        installed_modules = root / "node_modules"
        if installed_modules.is_dir() and not installed_modules.is_symlink():
            shutil.rmtree(installed_modules)
        else:
            installed_modules.unlink(missing_ok=True)


def _materialize_operational_dependency_tree(parent: Path, source_root: Path = PINNED_ROOT) -> Path:
    """Hard-link a sealed import mount; workspace links cannot escape it."""

    source = source_root / "node_modules"
    mount = parent / "node_modules"
    target = parent / "sealed-node-modules"
    if mount.exists() or mount.is_symlink():
        mount.unlink()
    if target.exists() or target.is_symlink():
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()

    workspace_targets = {
        "@earendil-works/pi-agent-core": source_root / "packages/agent",
        "@earendil-works/pi-ai": source_root / "packages/ai",
        "@earendil-works/pi-coding-agent": source_root / "packages/coding-agent",
        "@earendil-works/pi-tui": source_root / "packages/tui",
    }

    def clone_tree(origin: Path, destination: Path) -> None:
        destination.mkdir()
        for child in sorted(origin.iterdir(), key=lambda item: item.name):
            relative = child.relative_to(source).as_posix() if child.is_relative_to(source) else ""
            copied = destination / child.name
            if relative == ".bin":
                continue
            if child.is_symlink():
                if relative in workspace_targets:
                    clone_tree(workspace_targets[relative], copied)
                elif child.resolve(strict=True).is_relative_to(source):
                    copied.symlink_to(os.readlink(child))
                # Example extension links escape the sealed import mount and are excluded.
            elif child.is_dir():
                clone_tree(child, copied)
            elif child.is_file():
                os.link(child, copied)
            else:
                raise AssertionError("unsupported Prime dependency entry")

    clone_tree(source, target)
    mount.symlink_to(target, target_is_directory=True)
    return target


def _materialize_locked_dist(root: Path) -> None:
    shutil.copytree(
        PINNED_ROOT / "packages/coding-agent/dist",
        root / "packages/coding-agent/dist",
        symlinks=False,
    )


def _fixture_command(resources: Path, source: Path, package: str = "auth") -> Sequence[str]:
    return (
        str(_resolve_operational_node()), str(REAL_HARNESS),
        "--resource-root", str(resources), "--source-root", str(source),
        "--package", package,
    )


def _run_fixture(
    resources: Path, source: Path, package: str = "auth"
) -> subprocess.CompletedProcess[str]:
    fixture_source = source if source.is_symlink() else source.resolve(strict=True)
    return subprocess.run(
        _fixture_command(resources.resolve(strict=True), fixture_source, package),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestPrimeOperationalHarness(unittest.TestCase):
    def test_locked_settings_schema_matches_the_canonical_request_schema(self) -> None:
        self.assertEqual(
            json.loads(
                (RESOURCE_ROOT / "prime-settings-keybindings-request.schema.json").read_text(
                    encoding="utf-8"
                )
            ),
            json.loads(
                (ROOT / "schemas/operation/v1/settings-keybindings-request.schema.json").read_text(
                    encoding="utf-8"
                )
            ),
        )

    def test_two_clean_node22_npm_ci_builds_have_the_locked_dependency_digest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-clean-") as temporary:
            parent = Path(temporary)
            digests = []
            for name in ("one", "two"):
                root = _clean_pinned_clone(parent, name)
                _rebuild_locked_workspaces(root)
                digests.append(_operational_dependency_tree_digest(root))
            lock = json.loads(
                (RESOURCE_ROOT / "prime-operational-module-lock.json").read_text(encoding="utf-8")
            )
            self.assertEqual(digests, [lock["dependency_tree_digest"]] * 2)

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
                    "credential_reads": 0, "network_requests": 0,
                    "provider_operations": 0, "retained_processes": 0,
                    "stdout_writes": 0, "unauthorized_uploads": 0,
                })
                self.assertEqual(reports[0]["scenario_counts"], {
                    "fake_coordinator_calls": 0, "host_service_calls": 1,
                    "injected_sink_calls": 0, "mock_refresh_calls": 1,
                    "reconcile_calls": 0, "scenario_calls": 1,
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

    def test_malicious_dependency_tree_is_rejected_before_proper_lockfile_import(self) -> None:
        """A changed dependency mount cannot run its module initializer."""

        with tempfile.TemporaryDirectory(prefix="asterion-prime-operational-dependency-") as temporary:
            parent = Path(temporary)
            root = _external_pinned_root(parent)
            resources = parent / "resources"
            side_effect = parent / "proper-lockfile-side-effect"
            shutil.copytree(RESOURCE_ROOT, resources, symlinks=False)
            try:
                _rebuild_locked_workspaces(root)
                malicious = parent / "node_modules/proper-lockfile/index.js"
                malicious.unlink()
                malicious.write_text(
                    "require('node:fs').writeFileSync("
                    f"{json.dumps(str(side_effect))}, 'executed');\n",
                    encoding="utf-8",
                )
                rejected = _run_fixture(resources, root)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertFalse(side_effect.exists())
                with self.assertRaises(OperationalHarnessError):
                    verify_operational_locks(root, resources)
            finally:
                subprocess.run(
                    ("git", "-C", str(PINNED_ROOT), "worktree", "remove", "--force", str(root)),
                    check=False, capture_output=True, text=True, timeout=20,
                )

    def test_fixture_rejects_falsified_model_settings_and_counter_receipts(self) -> None:
        mutations = (
            ("auth", "scenario_counts: Object.freeze({ ...receiptCounters(packageId), scenario_calls: 2 })"),
            ("model-selection", "model_transition: Object.freeze([\"forged\"])"),
            ("settings-keybindings", "settings: Object.freeze([[\"forged\"]])"),
        )
        for package, override in mutations:
            with self.subTest(package=package), tempfile.TemporaryDirectory(
                prefix="asterion-prime-operational-forged-"
            ) as temporary:
                parent = Path(temporary)
                root = _external_pinned_root(parent)
                resources = parent / "resources"
                shutil.copytree(RESOURCE_ROOT, resources, symlinks=False)
                try:
                    _rebuild_locked_workspaces(root)
                    module = resources / "prime-operational-module.mjs"
                    original = module.read_text(encoding="utf-8")
                    needle = "return makeReceipt(frame.package, locks, scenario);"
                    self.assertEqual(original.count(needle), 1)
                    module.write_text(
                        original.replace(
                            needle,
                            "return Object.freeze({ ...makeReceipt(frame.package, locks, scenario), "
                            + override + " });",
                        ),
                        encoding="utf-8",
                    )
                    lock = resources / "prime-operational-module-lock.json"
                    lock_body = json.loads(lock.read_text(encoding="utf-8"))
                    lock_body["module_digest"] = hashlib.sha256(module.read_bytes()).hexdigest()
                    lock.write_text(
                        json.dumps(lock_body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    rejected = _run_fixture(resources, root, package)
                    self.assertNotEqual(rejected.returncode, 0)
                finally:
                    subprocess.run(
                        ("git", "-C", str(PINNED_ROOT), "worktree", "remove", "--force", str(root)),
                        check=False, capture_output=True, text=True, timeout=20,
                    )

    def test_harness_rejects_the_repository_checkout(self) -> None:
        with self.assertRaises(OperationalHarnessError):
            verify_operational_locks(PINNED_ROOT, RESOURCE_ROOT)
