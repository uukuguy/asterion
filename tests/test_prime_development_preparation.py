from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from asterion.applications.prime_agent.operator import (
    development_preparation as subject,
)


class TestPrimeDevelopmentPreparation(unittest.TestCase):
    def test_public_error_is_fixed(self) -> None:
        self.assertEqual(
            str(subject.PrimeDevelopmentPreparationError("private")),
            "Prime development preparation is unavailable",
        )

    def test_rejects_invalid_scenarios_without_io(self) -> None:
        with self.assertRaises(subject.PrimeDevelopmentPreparationError):
            subject.prepare_prime_development(Path.cwd(), ("p8",))

    def test_packaged_seccomp_has_locked_canonical_digest(self) -> None:
        lock = subject._seccomp_lock()
        self.assertEqual(
            sha256(subject._bytes("prime-development-seccomp.json")).hexdigest(),
            lock["canonical_sha256"],
        )

    def test_development_seccomp_lock_is_separate_and_complete(self) -> None:
        lock = subject._seccomp_lock()
        self.assertEqual(lock["format"], "asterion.prime-development-seccomp-lock/v1")
        self.assertEqual(lock["platforms"], ["linux/amd64", "linux/arm64"])
        self.assertEqual(
            set(lock["images"]), {"p1", "p2", "p3", "p4", "p5", "p6", "p7"}
        )

    def test_preparation_lock_binds_seccomp_lock_bytes_for_each_architecture(self) -> None:
        lock = subject._lock()
        digest = sha256(subject._bytes("prime-development-seccomp-lock.json")).hexdigest()
        self.assertEqual(
            lock["seccomp"]["lock_sha256_by_arch"],
            {"amd64": digest, "arm64": digest},
        )

    def test_preparation_rejects_tampered_seccomp_lock_before_cache_or_commands(self) -> None:
        original_bytes = subject._bytes
        calls: list[object] = []

        def bytes_with_tampered_seccomp_lock(name: str) -> bytes:
            if name == "prime-development-seccomp-lock.json":
                return original_bytes(name) + b" "
            return original_bytes(name)

        with TemporaryDirectory() as temp, patch.object(subject, "_bytes", bytes_with_tampered_seccomp_lock):
            repo = Path(temp)
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject.prepare_prime_development(
                    repo,
                    ("p1",),
                    downloader=lambda *_args, **_kwargs: calls.append("download"),
                    runner=lambda *_args, **_kwargs: calls.append("run"),
                )
            self.assertEqual(calls, [])
            self.assertFalse((repo / ".asterion-private").exists())

    def test_preparation_rejects_changed_seccomp_provenance_before_cache_or_commands(self) -> None:
        original_bytes = subject._bytes
        calls: list[object] = []

        def bytes_with_changed_provenance(name: str) -> bytes:
            if name == "prime-development-seccomp-lock.json":
                value = json.loads(original_bytes(name))
                value["tag"] = "seccomp/v0.2.4"
                return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            return original_bytes(name)

        with TemporaryDirectory() as temp, patch.object(subject, "_bytes", bytes_with_changed_provenance):
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject.prepare_prime_development(
                    Path(temp),
                    ("p1",),
                    downloader=lambda *_args, **_kwargs: calls.append("download"),
                    runner=lambda *_args, **_kwargs: calls.append("run"),
                )
            self.assertEqual(calls, [])
            self.assertFalse((Path(temp) / ".asterion-private").exists())

    def test_preparation_rejects_missing_seccomp_arch_binding_before_cache_or_commands(self) -> None:
        original_bytes = subject._bytes
        calls: list[object] = []

        def bytes_with_missing_arch_binding(name: str) -> bytes:
            if name == "prime-development-preparation-lock.json":
                value = json.loads(original_bytes(name))
                del value["seccomp"]["lock_sha256_by_arch"]["arm64"]
                return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            return original_bytes(name)

        with TemporaryDirectory() as temp, patch.object(subject, "_bytes", bytes_with_missing_arch_binding):
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject.prepare_prime_development(
                    Path(temp),
                    ("p1",),
                    downloader=lambda *_args, **_kwargs: calls.append("download"),
                    runner=lambda *_args, **_kwargs: calls.append("run"),
                )
            self.assertEqual(calls, [])
            self.assertFalse((Path(temp) / ".asterion-private").exists())

    def test_preparation_rejects_mismatched_seccomp_lock_digest_before_cache_or_commands(self) -> None:
        original_bytes = subject._bytes
        calls: list[object] = []

        def bytes_with_wrong_digest(name: str) -> bytes:
            if name == "prime-development-preparation-lock.json":
                value = json.loads(original_bytes(name))
                value["seccomp"]["lock_sha256_by_arch"]["amd64"] = "0" * 64
                value["seccomp"]["lock_sha256_by_arch"]["arm64"] = "0" * 64
                return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            return original_bytes(name)

        with TemporaryDirectory() as temp, patch.object(subject, "_bytes", bytes_with_wrong_digest):
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject.prepare_prime_development(
                    Path(temp),
                    ("p1",),
                    downloader=lambda *_args, **_kwargs: calls.append("download"),
                    runner=lambda *_args, **_kwargs: calls.append("run"),
                )
            self.assertEqual(calls, [])
            self.assertFalse((Path(temp) / ".asterion-private").exists())

    def test_resolver_rejects_receipt_without_materialized_content(self) -> None:
        with TemporaryDirectory() as temp:
            repo = Path(temp)
            root = subject._root(repo)
            (root / "receipt.json").write_text(
                json.dumps({"context": {}, "scenarios": ["p1"], "identities": {}}),
                encoding="utf-8",
            )
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject.resolve_prepared_prime_development(repo, "p1")

    def test_resolver_rejects_symlinked_receipt(self) -> None:
        with TemporaryDirectory() as temp:
            repo = Path(temp)
            root = subject._root(repo)
            target = repo / "receipt-target.json"
            target.write_text("{}", encoding="utf-8")
            (root / "receipt.json").symlink_to(target)
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject.resolve_prepared_prime_development(repo, "p1")

    def test_node_downloader_has_a_finite_timeout(self) -> None:
        calls: list[object] = []

        class Response:
            def read(self, _size: int) -> bytes:
                return b""

        def downloader(*_args: object, **kwargs: object) -> Response:
            calls.append(kwargs["timeout"])
            return Response()

        with TemporaryDirectory() as temp:
            with self.assertRaises(subject.PrimeDevelopmentPreparationError):
                subject._node(
                    Path(temp),
                    {
                        "url": "https://example.invalid/node.tar.xz",
                        "archive_sha256": "0" * 64,
                        "node_sha256": "0" * 64,
                    },
                    downloader=downloader,
                    runner=lambda *_args, **_kwargs: SimpleNamespace(stdout=b""),
                )
        self.assertEqual(calls, [120])

    def test_command_output_is_bounded(self) -> None:
        calls: list[object] = []

        def runner(*_args: object, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs["timeout"])
            return SimpleNamespace(stdout=b"x" * 4097)

        with self.assertRaises(subject.PrimeDevelopmentPreparationError):
            subject._run(["/usr/bin/true"], runner=runner)
        self.assertEqual(calls, [120])

    def test_node_publication_retains_existing_versioned_tree(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "node.tar.xz"
            archive.write_bytes(b"untrusted archive bytes")
            node = root / ("node-" + subject._digest(archive)[:16]) / "bin" / "node"
            node.parent.mkdir(parents=True)
            node.write_bytes(b"last verified node")
            self.assertEqual(subject._publish_node(root, archive), node)
            self.assertEqual(node.read_bytes(), b"last verified node")

    def test_paths_are_private_and_canonical(self) -> None:
        with TemporaryDirectory() as temp:
            root = subject._root(Path(temp))
            self.assertEqual(
                root, Path(temp).resolve() / ".asterion-private" / "prime-development"
            )

    def test_production_catalogs_remain_empty(self) -> None:
        from asterion.applications.prime_agent.operator.image_input_lock import (
            PRIME_IPYTHON_IMAGE_INPUT_CATALOG,
        )
        from asterion.applications.prime_agent.operator.seccomp_policy_lock import (
            PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG,
        )

        self.assertEqual(PRIME_IPYTHON_IMAGE_INPUT_CATALOG.locks, ())
        self.assertEqual(PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG.locks, ())
