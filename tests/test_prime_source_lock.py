"""Tests for the pinned, read-only Prime source contract."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from asterion.applications.prime_agent.source_lock import (
    PrimeSourceLock,
    PrimeSourceLockError,
    canonical_prime_source_lock_bytes,
    prime_source_lock_sha256,
    verify_prime_source_lock,
)


_COMMIT = "a" * 40


def _write_source(root: Path, *, package_version: str = "1.0.0") -> None:
    (root / ".git").mkdir()
    (root / "src").mkdir()
    (root / "src" / "main.ts").write_text("export const prime = 1;\n")
    (root / "package.json").write_text(json.dumps({"version": package_version}))
    (root / "package-lock.json").write_text(
        json.dumps({"lockfileVersion": 3, "packages": {"": {"version": package_version}}})
    )
    (root / ".git" / "HEAD").write_text(f"{_COMMIT}\n")


def _lock(root: Path) -> PrimeSourceLock:
    tree = sha256()
    for relative_path in ("package.json", "src/main.ts"):
        content = (root / relative_path).read_bytes()
        tree.update(relative_path.encode("utf-8"))
        tree.update(b"\0")
        tree.update(content)
        tree.update(b"\0")
    return PrimeSourceLock(
        commit=_COMMIT,
        tree_sha256=tree.hexdigest(),
        package_lock_sha256=sha256((root / "package-lock.json").read_bytes()).hexdigest(),
    )


class TestPrimeSourceLock(unittest.TestCase):
    def test_canonical_identity_is_deterministic_and_field_sensitive(self) -> None:
        lock = PrimeSourceLock(_COMMIT, "b" * 64, "c" * 64)
        expected = b'{"commit":"' + _COMMIT.encode() + b'","package_lock_sha256":"' + (
            b"c" * 64
        ) + b'","tree_sha256":"' + (b"b" * 64) + b'"}'

        self.assertEqual(canonical_prime_source_lock_bytes(lock), expected)
        digest = prime_source_lock_sha256(lock)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, prime_source_lock_sha256(lock))
        self.assertNotEqual(
            digest,
            prime_source_lock_sha256(PrimeSourceLock(_COMMIT, "d" * 64, "c" * 64)),
        )

        with self.assertRaises(PrimeSourceLockError):
            canonical_prime_source_lock_bytes(object())

    def test_verifies_exact_canonical_source_and_package_lock(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            source_root = (Path(temporary_directory) / "prime-agent").resolve()
            source_root.mkdir()
            _write_source(source_root)
            lock = _lock(source_root)

            self.assertEqual(verify_prime_source_lock(source_root, lock), lock)

    def test_ignores_declared_generated_build_outputs(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            source_root = (Path(temporary_directory) / "prime-agent").resolve()
            source_root.mkdir()
            _write_source(source_root)
            lock = _lock(source_root)
            (source_root / "dist").mkdir()
            (source_root / "dist" / "main.js").write_text("generated\n")
            (source_root / "packages" / "agent" / "dist").mkdir(parents=True)
            (source_root / "packages" / "agent" / "dist" / "main.js").write_text(
                "generated\n"
            )
            (source_root / "build.tsbuildinfo").write_text("generated\n")
            (source_root / "src" / "__pycache__").mkdir()
            (source_root / "src" / "__pycache__" / "main.cpython-311.pyc").write_bytes(
                b"generated"
            )
            (source_root / ".husky" / "_").mkdir(parents=True)
            (source_root / ".husky" / "_" / "generated").write_text("generated\n")

            self.assertEqual(verify_prime_source_lock(source_root, lock), lock)

    def test_lock_is_frozen(self) -> None:
        lock = PrimeSourceLock(_COMMIT, "a" * 64, "b" * 64)

        with self.assertRaises(FrozenInstanceError):
            lock.commit = "b" * 40  # type: ignore[misc]

    def test_rejects_wrong_digest_commit_or_invalid_lock(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            source_root = (Path(temporary_directory) / "prime-agent").resolve()
            source_root.mkdir()
            _write_source(source_root)
            lock = _lock(source_root)
            wrong_lock = PrimeSourceLock(
                commit="b" * 40,
                tree_sha256=lock.tree_sha256,
                package_lock_sha256=lock.package_lock_sha256,
            )

            for value in (wrong_lock, {}, PrimeSourceLock(_COMMIT, "invalid", "b" * 64)):
                with self.subTest(value=value), self.assertRaises(PrimeSourceLockError):
                    verify_prime_source_lock(source_root, value)  # type: ignore[arg-type]

    def test_rejects_ref_that_escapes_git_refs_directory(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            source_root = (Path(temporary_directory) / "prime-agent").resolve()
            source_root.mkdir()
            _write_source(source_root)
            lock = _lock(source_root)
            (source_root / ".git" / "refs").mkdir()
            (source_root / ".git" / "escaped").write_text(f"{_COMMIT}\n")
            (source_root / ".git" / "HEAD").write_text(
                "ref: refs/../../.git/escaped\n"
            )

            with self.assertRaises(PrimeSourceLockError):
                verify_prime_source_lock(source_root, lock)

    def test_rejects_noncanonical_roots_and_symlinked_inputs(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            source_root = (Path(temporary_directory) / "prime-agent").resolve()
            source_root.mkdir()
            _write_source(source_root)
            lock = _lock(source_root)
            link = Path(temporary_directory) / "prime-link"
            link.symlink_to(source_root, target_is_directory=True)

            with self.assertRaises(PrimeSourceLockError):
                verify_prime_source_lock(link, lock)

            (source_root / "src" / "main.ts").unlink()
            (source_root / "src" / "main.ts").symlink_to("elsewhere.ts")
            with self.assertRaises(PrimeSourceLockError):
                verify_prime_source_lock(source_root, lock)

    def test_rejects_symlinked_excluded_directory(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            source_root = (Path(temporary_directory) / "prime-agent").resolve()
            source_root.mkdir()
            _write_source(source_root)
            lock = _lock(source_root)
            dependencies = Path(temporary_directory) / "dependencies"
            dependencies.mkdir()
            (source_root / "node_modules").symlink_to(
                dependencies, target_is_directory=True
            )

            with self.assertRaises(PrimeSourceLockError):
                verify_prime_source_lock(source_root, lock)

    def test_rejects_symlinked_nested_excluded_file(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            source_root = (Path(temporary_directory) / "prime-agent").resolve()
            source_root.mkdir()
            _write_source(source_root)
            lock = _lock(source_root)
            excluded_target = Path(temporary_directory) / "package-lock.json"
            excluded_target.write_text("untrusted")
            (source_root / "src" / "package-lock.json").symlink_to(excluded_target)

            with self.assertRaises(PrimeSourceLockError):
                verify_prime_source_lock(source_root, lock)

    def test_rejects_missing_or_version_drifted_package_inputs(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            source_root = (Path(temporary_directory) / "prime-agent").resolve()
            source_root.mkdir()
            _write_source(source_root, package_version="1.0.0")
            lock = _lock(source_root)

            (source_root / "package-lock.json").write_text(
                json.dumps({"lockfileVersion": 3, "packages": {"": {"version": "2.0.0"}}})
            )
            with self.assertRaises(PrimeSourceLockError):
                verify_prime_source_lock(source_root, lock)
