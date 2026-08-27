from __future__ import annotations

import hashlib
import json
import os
import socket
import stat
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from asterion.control import ecosystem_materialization as implementation
from asterion.control.ecosystem import (
    EcosystemError,
    EcosystemPrivateFile,
    EcosystemPrivateResource,
    EcosystemResourceRef,
    EcosystemSourceRef,
    build_ecosystem_portfolio,
)
from asterion.control.ecosystem_materialization import (
    EcosystemMaterializationError,
    FileEcosystemPrivateSourceStore,
    SealedEcosystemMaterializer,
)


ERROR = "ecosystem source is invalid"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _resource_digest(files: tuple[EcosystemPrivateFile, ...]) -> str:
    encoded = json.dumps(
        [
            {
                "relative_path": item.relative_path,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in files
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _private_resource(
    resource_id: str,
    files: dict[str, bytes],
    *,
    source_id: str = "source-1",
) -> EcosystemPrivateResource:
    declarations = tuple(
        EcosystemPrivateFile(path, _sha256(body), len(body))
        for path, body in sorted(files.items())
    )
    return EcosystemPrivateResource(resource_id, source_id, declarations)


def _portfolio_for(*private: EcosystemPrivateResource):
    resources = tuple(
        EcosystemResourceRef(
            item.resource_id,
            "1.0.0",
            "python-skill",
            "project",
            EcosystemSourceRef(
                item.source_id,
                "local-child",
                "1.0.0",
                "a" * 64,
            ),
            _resource_digest(item.files),
        )
        for item in private
    )
    return build_ecosystem_portfolio(
        portfolio_id="portfolio-1",
        authority_id="authority-1",
        authority_revision=1,
        resources=resources,
        registrations=(),
    )


def _write_files(root: Path, files: dict[str, bytes]) -> None:
    for relative_path, body in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)


class TestEcosystemPrivateDeclarations(unittest.TestCase):
    def test_declarations_are_frozen_canonical_and_body_free(self) -> None:
        files = (
            EcosystemPrivateFile("SKILL.md", "a" * 64, 12),
            EcosystemPrivateFile("src/skill_one/__init__.py", "b" * 64, 20),
        )
        resource = EcosystemPrivateResource("python-skill-1", "source-1", files)

        self.assertEqual(resource.files, files)
        self.assertNotIn("source-1", repr(resource))
        with self.assertRaises((AttributeError, TypeError)):
            resource.files += (files[0],)  # type: ignore[misc]

    def test_declarations_reject_unsafe_or_noncanonical_values(self) -> None:
        valid = EcosystemPrivateFile("SKILL.md", "a" * 64, 12)
        invalid_files = (
            lambda: EcosystemPrivateFile("", "a" * 64, 12),
            lambda: EcosystemPrivateFile("/SENTINEL_PRIVATE", "a" * 64, 12),
            lambda: EcosystemPrivateFile("../SENTINEL_PRIVATE", "a" * 64, 12),
            lambda: EcosystemPrivateFile("src/../SENTINEL_PRIVATE", "a" * 64, 12),
            lambda: EcosystemPrivateFile("./SKILL.md", "a" * 64, 12),
            lambda: EcosystemPrivateFile("src//SKILL.md", "a" * 64, 12),
            lambda: EcosystemPrivateFile("SKILL.md", "A" * 64, 12),
            lambda: EcosystemPrivateFile("SKILL.md", "a" * 64, -1),
            lambda: EcosystemPrivateFile("SKILL.md", "a" * 64, True),
        )
        for construct in invalid_files:
            with self.subTest(construct=construct), self.assertRaises(EcosystemError) as raised:
                construct()
            self.assertNotIn("SENTINEL_PRIVATE", str(raised.exception))

        invalid_resources = (
            lambda: EcosystemPrivateResource("../SENTINEL_PRIVATE", "source-1", (valid,)),
            lambda: EcosystemPrivateResource("resource-1", "/SENTINEL_PRIVATE", (valid,)),
            lambda: EcosystemPrivateResource("resource-1", "source-1", [valid]),
            lambda: EcosystemPrivateResource("resource-1", "source-1", (valid, valid)),
            lambda: EcosystemPrivateResource(
                "resource-1",
                "source-1",
                (
                    EcosystemPrivateFile("z", "a" * 64, 1),
                    EcosystemPrivateFile("a", "b" * 64, 1),
                ),
            ),
        )
        for construct in invalid_resources:
            with self.subTest(construct=construct), self.assertRaises(EcosystemError) as raised:
                construct()
            self.assertNotIn("SENTINEL_PRIVATE", str(raised.exception))


class TestFileEcosystemPrivateSourceStore(unittest.TestCase):
    def test_open_file_reads_exact_declared_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "source"
            root.mkdir()
            files = {"src/skill_one/__init__.py": b"VALUE = 1\n"}
            _write_files(root, files)
            private = _private_resource("python-skill-1", files)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": root}, resources=(private,)
            )

            with store.open_file("python-skill-1", next(iter(files))) as stream:
                self.assertEqual(stream.read(), next(iter(files.values())))

    def test_open_file_rejects_root_intermediate_and_final_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            actual = base / "actual"
            actual.mkdir()
            _write_files(actual, {"nested/file": b"body"})
            root_link = base / "root-link"
            root_link.symlink_to(actual, target_is_directory=True)

            intermediate_root = base / "intermediate"
            intermediate_root.mkdir()
            (intermediate_root / "nested").symlink_to(
                actual / "nested", target_is_directory=True
            )

            final_root = base / "final"
            final_root.mkdir()
            (final_root / "nested").mkdir()
            (final_root / "nested/file").symlink_to(actual / "nested/file")

            private = _private_resource(
                "resource-1", {"nested/file": b"body"}
            )
            for name, root in (
                ("root", root_link),
                ("intermediate", intermediate_root),
                ("final", final_root),
            ):
                with self.subTest(component=name):
                    store = FileEcosystemPrivateSourceStore(
                        roots={"source-1": root}, resources=(private,)
                    )
                    self._assert_redacted_error(store, "resource-1", "nested/file")

    def test_open_file_rejects_fifo_socket_and_device_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fifo = root / "fifo"
            os.mkfifo(fifo)
            socket_path = root / "socket"
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(str(socket_path))
            try:
                for name in ("fifo", "socket"):
                    with self.subTest(kind=name):
                        private = EcosystemPrivateResource(
                            "resource-1",
                            "source-1",
                            (EcosystemPrivateFile(name, _sha256(b""), 0),),
                        )
                        store = FileEcosystemPrivateSourceStore(
                            roots={"source-1": root}, resources=(private,)
                        )
                        self._assert_redacted_error(store, "resource-1", name)
            finally:
                listener.close()

        private = EcosystemPrivateResource(
            "resource-1",
            "source-1",
            (EcosystemPrivateFile("null", _sha256(b""), 0),),
        )
        store = FileEcosystemPrivateSourceStore(
            roots={"source-1": Path("/dev")}, resources=(private,)
        )
        self._assert_redacted_error(store, "resource-1", "null")

    def test_open_file_rejects_undeclared_size_and_digest_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "declared").write_bytes(b"correct")
            (root / "undeclared").write_bytes(b"private")
            cases = (
                (
                    "undeclared",
                    EcosystemPrivateResource(
                        "resource-1",
                        "source-1",
                        (EcosystemPrivateFile("declared", _sha256(b"correct"), 7),),
                    ),
                ),
                (
                    "declared",
                    EcosystemPrivateResource(
                        "resource-1",
                        "source-1",
                        (EcosystemPrivateFile("declared", _sha256(b"correct"), 6),),
                    ),
                ),
                (
                    "declared",
                    EcosystemPrivateResource(
                        "resource-1",
                        "source-1",
                        (EcosystemPrivateFile("declared", _sha256(b"wrong!!"), 7),),
                    ),
                ),
            )
            for relative_path, private in cases:
                with self.subTest(relative_path=relative_path, private=private):
                    store = FileEcosystemPrivateSourceStore(
                        roots={"source-1": root}, resources=(private,)
                    )
                    self._assert_redacted_error(store, "resource-1", relative_path)

    def test_open_file_holds_verified_inode_across_path_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            source.write_bytes(b"original")
            original_identity = (source.stat().st_dev, source.stat().st_ino)
            private = _private_resource("resource-1", {"source": b"original"})
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": root}, resources=(private,)
            )
            real_read = os.read
            read_sizes: list[int] = []

            def recording_read(descriptor: int, size: int) -> bytes:
                value = real_read(descriptor, size)
                read_sizes.append(len(value))
                return value

            with patch(
                "asterion.control.ecosystem_materialization.os.read",
                side_effect=recording_read,
            ):
                with store.open_file("resource-1", "source") as stream:
                    details = os.fstat(stream.fileno())
                    self.assertEqual((details.st_dev, details.st_ino), original_identity)
                    moved = root / "moved"
                    source.rename(moved)
                    source.write_bytes(b"replacement")
                    self.assertEqual(stream.read(), b"original")

            self.assertLessEqual(sum(read_sizes), len(b"original") + 1)

    def test_store_copies_private_mappings_and_redacts_all_errors(self) -> None:
        with tempfile.TemporaryDirectory(prefix="SENTINEL_PRIVATE_") as temporary:
            roots = {"source-1": Path(temporary).resolve()}
            private = _private_resource("resource-1", {"file": b"body"})
            store = FileEcosystemPrivateSourceStore(roots=roots, resources=(private,))
            roots.clear()
            self.assertNotIn("SENTINEL_PRIVATE", repr(store))
            self._assert_redacted_error(store, "resource-1", "other")

    def test_final_source_descriptor_closes_when_fstat_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "file").write_bytes(b"body")
            private = _private_resource("resource-1", {"file": b"body"})
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": root}, resources=(private,)
            )
            module = "asterion.control.ecosystem_materialization"
            real_open = os.open
            real_fstat = os.fstat
            final_fd: int | None = None
            failed = False

            def recording_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                nonlocal final_fd
                descriptor = real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]
                if path == "file":
                    final_fd = descriptor
                return descriptor

            def failing_fstat(descriptor: int) -> os.stat_result:
                nonlocal failed
                if descriptor == final_fd and not failed:
                    failed = True
                    raise OSError("SENTINEL_FSTAT")
                return real_fstat(descriptor)

            with (
                patch(f"{module}.os.open", side_effect=recording_open),
                patch(f"{module}.os.fstat", side_effect=failing_fstat),
            ):
                self._assert_redacted_error(store, "resource-1", "file")

            self.assertIsNotNone(final_fd)
            with self.assertRaises(OSError):
                real_fstat(final_fd)  # type: ignore[arg-type]

    def _assert_redacted_error(
        self,
        store: FileEcosystemPrivateSourceStore,
        resource_id: str,
        relative_path: str,
    ) -> None:
        with self.assertRaisesRegex(EcosystemMaterializationError, f"^{ERROR}$") as raised:
            with store.open_file(resource_id, relative_path):
                pass
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn("SENTINEL_PRIVATE", str(raised.exception))


class TestSealedEcosystemMaterializer(unittest.TestCase):
    def test_materializes_exact_files_with_private_modes_and_immutable_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source_root = base / "SENTINEL_SOURCE"
            source_root.mkdir()
            files = {
                "SKILL.md": b"# Skill\n",
                "src/skill_one/__init__.py": b"VALUE = 1\n",
            }
            _write_files(source_root, files)
            private = _private_resource("python-skill-1", files)
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source_root}, resources=(private,)
            )
            materializer = SealedEcosystemMaterializer(base / "private")

            projection = materializer.materialize(portfolio, store)

            self.assertEqual(projection.portfolio_digest, portfolio.digest)
            self.assertEqual(projection.root.parent, base / "private")
            self.assertEqual(stat.S_IMODE(projection.root.stat().st_mode), 0o700)
            self.assertIsInstance(projection.resource_roots, MappingProxyType)
            resource_root = projection.resource_roots["python-skill-1"]
            self.assertEqual(stat.S_IMODE(resource_root.stat().st_mode), 0o700)
            for relative_path, body in files.items():
                target = resource_root / relative_path
                self.assertEqual(target.read_bytes(), body)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertNotIn(str(source_root), repr(projection))
            self.assertNotIn(str(projection.root), repr(projection))
            with self.assertRaises(TypeError):
                projection.resource_roots["other"] = resource_root  # type: ignore[index]

            materializer.close(projection)
            self.assertFalse(projection.root.exists())
            materializer.close(projection)

    def test_materialization_rejects_resource_digest_drift_and_missing_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"file": b"body"})
            private = _private_resource("resource-1", {"file": b"body"})
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            portfolio = _portfolio_for(private)
            drifted = build_ecosystem_portfolio(
                portfolio_id=portfolio.portfolio_id,
                authority_id=portfolio.authority_id,
                authority_revision=portfolio.authority_revision,
                resources=(
                    EcosystemResourceRef(
                        "resource-1",
                        "1.0.0",
                        "python-skill",
                        "project",
                        portfolio.resources[0].source,
                        "f" * 64,
                    ),
                ),
                registrations=(),
            )
            missing = build_ecosystem_portfolio(
                portfolio_id="portfolio-2",
                authority_id="authority-1",
                authority_revision=1,
                resources=(
                    EcosystemResourceRef(
                        "resource-2",
                        "1.0.0",
                        "python-skill",
                        "project",
                        EcosystemSourceRef(
                            "source-1", "local-child", "1.0.0", "a" * 64
                        ),
                        "f" * 64,
                    ),
                ),
                registrations=(),
            )
            for candidate in (drifted, missing):
                with self.subTest(candidate=candidate), self.assertRaisesRegex(
                    EcosystemMaterializationError, f"^{ERROR}$"
                ) as raised:
                    SealedEcosystemMaterializer(base / "private").materialize(
                        candidate, store
                    )
                self.assertIsNone(raised.exception.__cause__)
                self.assertFalse(any((base / "private").glob("*")))

    def test_existing_final_projection_is_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"file": b"body"})
            private = _private_resource("resource-1", {"file": b"body"})
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            first = SealedEcosystemMaterializer(base / "private")
            projection = first.materialize(portfolio, store)
            marker = projection.root / "marker"
            marker.write_bytes(b"existing")

            with self.assertRaisesRegex(EcosystemMaterializationError, f"^{ERROR}$"):
                SealedEcosystemMaterializer(base / "private").materialize(portfolio, store)

            self.assertEqual(marker.read_bytes(), b"existing")
            self.assertEqual(
                tuple(path.name for path in (base / "private").iterdir()),
                (projection.projection_id,),
            )
            first.close(projection)

    def test_partial_copy_and_cleanup_failures_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="SENTINEL_PRIVATE_") as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            files = {"a": b"one", "b": b"two"}
            _write_files(source, files)
            private = _private_resource("resource-1", files)
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            module = "asterion.control.ecosystem_materialization"

            with patch(f"{module}._copy_declared_file", side_effect=OSError("SENTINEL_COPY")):
                with self.assertRaisesRegex(EcosystemMaterializationError, f"^{ERROR}$") as raised:
                    SealedEcosystemMaterializer(base / "private").materialize(
                        portfolio, store
                    )
            self.assertIsNone(raised.exception.__cause__)
            self.assertFalse(any((base / "private").glob("*")))

            with (
                patch(f"{module}._copy_declared_file", side_effect=OSError("SENTINEL_COPY")),
                patch(f"{module}._remove_owned_tree", side_effect=OSError("SENTINEL_CLEANUP")),
            ):
                with self.assertRaisesRegex(EcosystemMaterializationError, f"^{ERROR}$") as raised:
                    SealedEcosystemMaterializer(base / "private").materialize(
                        portfolio, store
                    )
            self.assertIsNone(raised.exception.__cause__)
            self.assertNotIn("SENTINEL", str(raised.exception))

    def test_early_staging_fsync_failure_removes_owned_staging_inode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"file": b"body"})
            private = _private_resource("resource-1", {"file": b"body"})
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            module = "asterion.control.ecosystem_materialization"
            real_mkdir = os.mkdir
            real_fsync = os.fsync
            staging_created = False
            failed = False

            def recording_mkdir(
                path: object, mode: int = 0o777, *, dir_fd: int | None = None
            ) -> None:
                nonlocal staging_created
                real_mkdir(path, mode, dir_fd=dir_fd)
                if isinstance(path, str) and path.startswith(".staging-"):
                    staging_created = True

            def failing_fsync(descriptor: int) -> None:
                nonlocal failed
                if staging_created and not failed:
                    failed = True
                    raise OSError("SENTINEL_EARLY_FSYNC")
                real_fsync(descriptor)

            with (
                patch(f"{module}.os.mkdir", side_effect=recording_mkdir),
                patch(f"{module}.os.fsync", side_effect=failing_fsync),
            ):
                with self.assertRaisesRegex(
                    EcosystemMaterializationError, f"^{ERROR}$"
                ) as raised:
                    SealedEcosystemMaterializer(base / "private").materialize(
                        portfolio, store
                    )

            self.assertIsNone(raised.exception.__cause__)
            self.assertTrue(staging_created)
            self.assertEqual(tuple((base / "private").iterdir()), ())

    def test_early_staging_open_failure_reopens_only_quarantined_inode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"file": b"body"})
            private = _private_resource("resource-1", {"file": b"body"})
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            module = "asterion.control.ecosystem_materialization"
            real_open = os.open
            staging_open_failed = False

            def failing_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                nonlocal staging_open_failed
                if (
                    isinstance(path, str)
                    and path.startswith(".staging-")
                    and not staging_open_failed
                ):
                    staging_open_failed = True
                    raise OSError("SENTINEL_STAGING_OPEN")
                return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

            with patch(f"{module}.os.open", side_effect=failing_open):
                with self.assertRaisesRegex(
                    EcosystemMaterializationError, f"^{ERROR}$"
                ) as raised:
                    SealedEcosystemMaterializer(base / "private").materialize(
                        portfolio, store
                    )

            self.assertIsNone(raised.exception.__cause__)
            self.assertTrue(staging_open_failed)
            self.assertEqual(tuple((base / "private").iterdir()), ())

    def test_close_cleanup_failure_retains_ownership_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"file": b"body"})
            private = _private_resource("resource-1", {"file": b"body"})
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            materializer = SealedEcosystemMaterializer(base / "private")
            projection = materializer.materialize(portfolio, store)

            with patch(
                "asterion.control.ecosystem_materialization._remove_owned_tree",
                side_effect=OSError("SENTINEL_TRANSIENT"),
            ):
                with self.assertRaisesRegex(
                    EcosystemMaterializationError, f"^{ERROR}$"
                ) as raised:
                    materializer.close(projection)
            self.assertIsNone(raised.exception.__cause__)
            self.assertTrue(projection.root.exists())

            materializer.close(projection)

            self.assertFalse(projection.root.exists())
            materializer.close(projection)

    def test_close_retries_only_parent_fsync_after_tree_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"file": b"body"})
            private = _private_resource("resource-1", {"file": b"body"})
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            materializer = SealedEcosystemMaterializer(base / "private")
            projection = materializer.materialize(portfolio, store)
            root_identity = (
                (base / "private").stat().st_dev,
                (base / "private").stat().st_ino,
            )
            real_fsync = os.fsync
            failed = False

            def failing_root_fsync(descriptor: int) -> None:
                nonlocal failed
                details = os.fstat(descriptor)
                if (
                    not failed
                    and (details.st_dev, details.st_ino) == root_identity
                    and not projection.root.exists()
                ):
                    failed = True
                    raise OSError("SENTINEL_ROOT_FSYNC")
                real_fsync(descriptor)

            with (
                patch(
                    "asterion.control.ecosystem_materialization._remove_owned_tree",
                    wraps=implementation._remove_owned_tree,
                ) as remove_owned_tree,
                patch(
                    "asterion.control.ecosystem_materialization.os.fsync",
                    side_effect=failing_root_fsync,
                ),
            ):
                with self.assertRaisesRegex(
                    EcosystemMaterializationError, f"^{ERROR}$"
                ) as raised:
                    materializer.close(projection)
                self.assertIsNone(raised.exception.__cause__)
                self.assertFalse(projection.root.exists())

                materializer.close(projection)

            self.assertTrue(failed)
            self.assertEqual(remove_owned_tree.call_count, 1)
            materializer.close(projection)

    def test_projection_descriptor_close_failure_is_terminal_uncertainty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"file": b"body"})
            private = _private_resource("resource-1", {"file": b"body"})
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            materializer = SealedEcosystemMaterializer(base / "private")
            projection = materializer.materialize(portfolio, store)
            projection_fd = materializer._owned[id(projection)].projection_fd
            real_close = os.close
            close_attempts: list[int] = []
            failed = False

            def failing_projection_close(descriptor: int) -> None:
                nonlocal failed
                close_attempts.append(descriptor)
                real_close(descriptor)
                if descriptor == projection_fd and not failed:
                    failed = True
                    raise OSError("SENTINEL_PROJECTION_CLOSE")

            with patch(
                "asterion.control.ecosystem_materialization.os.close",
                side_effect=failing_projection_close,
            ):
                with self.assertRaisesRegex(
                    EcosystemMaterializationError, f"^{ERROR}$"
                ) as raised:
                    materializer.close(projection)
                self.assertIsNone(raised.exception.__cause__)
                attempts_after_failure = tuple(close_attempts)

                with self.assertRaisesRegex(
                    EcosystemMaterializationError, f"^{ERROR}$"
                ):
                    materializer.close(projection)

            self.assertTrue(failed)
            self.assertEqual(close_attempts.count(projection_fd), 1)
            self.assertEqual(tuple(close_attempts), attempts_after_failure)
            self.assertFalse(projection.root.exists())

    def test_root_descriptor_close_failure_is_terminal_uncertainty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"file": b"body"})
            private = _private_resource("resource-1", {"file": b"body"})
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            materializer = SealedEcosystemMaterializer(base / "private")
            projection = materializer.materialize(portfolio, store)
            root_fd = materializer._owned[id(projection)].root_fd
            real_close = os.close
            close_attempts: list[int] = []
            failed = False

            def failing_root_close(descriptor: int) -> None:
                nonlocal failed
                close_attempts.append(descriptor)
                real_close(descriptor)
                if descriptor == root_fd and not failed:
                    failed = True
                    raise OSError("SENTINEL_ROOT_CLOSE")

            with patch(
                "asterion.control.ecosystem_materialization.os.close",
                side_effect=failing_root_close,
            ):
                with self.assertRaisesRegex(
                    EcosystemMaterializationError, f"^{ERROR}$"
                ) as raised:
                    materializer.close(projection)
                self.assertIsNone(raised.exception.__cause__)
                attempts_after_failure = tuple(close_attempts)

                with self.assertRaisesRegex(
                    EcosystemMaterializationError, f"^{ERROR}$"
                ):
                    materializer.close(projection)

            self.assertTrue(failed)
            self.assertEqual(close_attempts.count(root_fd), 1)
            self.assertEqual(tuple(close_attempts), attempts_after_failure)
            self.assertFalse(projection.root.exists())

    def test_close_quarantines_projection_before_descendant_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"nested/file": b"body"})
            private = _private_resource("resource-1", {"nested/file": b"body"})
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            materializer = SealedEcosystemMaterializer(base / "private")
            projection = materializer.materialize(portfolio, store)
            real_unlink = os.unlink
            real_rmdir = os.rmdir
            deletion_count = 0

            def guarded_unlink(
                path: object, *, dir_fd: int | None = None
            ) -> None:
                nonlocal deletion_count
                deletion_count += 1
                if projection.root.exists():
                    raise AssertionError("public projection remained bound")
                real_unlink(path, dir_fd=dir_fd)

            def guarded_rmdir(
                path: object, *, dir_fd: int | None = None
            ) -> None:
                nonlocal deletion_count
                deletion_count += 1
                if projection.root.exists():
                    raise AssertionError("public projection remained bound")
                real_rmdir(path, dir_fd=dir_fd)

            with (
                patch(
                    "asterion.control.ecosystem_materialization.os.unlink",
                    side_effect=guarded_unlink,
                ),
                patch(
                    "asterion.control.ecosystem_materialization.os.rmdir",
                    side_effect=guarded_rmdir,
                ),
            ):
                materializer.close(projection)

            self.assertGreaterEqual(deletion_count, 3)

    def test_close_never_rmdirs_replaceable_public_projection_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"file": b"body"})
            private = _private_resource("resource-1", {"file": b"body"})
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            materializer = SealedEcosystemMaterializer(base / "private")
            projection = materializer.materialize(portfolio, store)
            real_rmdir = os.rmdir
            public_rmdir = False

            def replacing_rmdir(
                path: object, *, dir_fd: int | None = None
            ) -> None:
                nonlocal public_rmdir
                if path == projection.projection_id:
                    public_rmdir = True
                    moved = base / "owned-after-race"
                    projection.root.rename(moved)
                    projection.root.mkdir(mode=0o700)
                real_rmdir(path, dir_fd=dir_fd)

            with patch(
                "asterion.control.ecosystem_materialization.os.rmdir",
                side_effect=replacing_rmdir,
            ):
                materializer.close(projection)

            self.assertFalse(public_rmdir)

    def test_close_failed_replacement_restore_retains_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"file": b"body"})
            private = _private_resource("resource-1", {"file": b"body"})
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            materializer = SealedEcosystemMaterializer(base / "private")
            projection = materializer.materialize(portfolio, store)
            projection.root.rename(base / "moved-owned")
            projection.root.mkdir(mode=0o700)
            marker = projection.root / "replacement"
            marker.write_bytes(b"keep")
            module = "asterion.control.ecosystem_materialization"
            real_move = implementation._atomic_move_no_replace

            def failing_restore(
                source_fd: int,
                source_name: str,
                target_fd: int,
                target_name: str,
            ) -> None:
                if source_name.startswith(".cleanup-"):
                    raise OSError("SENTINEL_RESTORE")
                real_move(source_fd, source_name, target_fd, target_name)

            with patch(f"{module}._atomic_move_no_replace", side_effect=failing_restore):
                with self.assertRaisesRegex(
                    EcosystemMaterializationError, f"^{ERROR}$"
                ) as raised:
                    materializer.close(projection)

            self.assertIsNone(raised.exception.__cause__)
            quarantined = tuple((base / "private").glob(".cleanup-*"))
            self.assertEqual(len(quarantined), 1)
            self.assertEqual((quarantined[0] / "replacement").read_bytes(), b"keep")
            with self.assertRaisesRegex(EcosystemMaterializationError, f"^{ERROR}$"):
                materializer.close(projection)

    def test_close_rejects_replaced_projection_until_exact_inode_is_restored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"file": b"body"})
            private = _private_resource("resource-1", {"file": b"body"})
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            materializer = SealedEcosystemMaterializer(base / "private")
            projection = materializer.materialize(portfolio, store)
            moved = base / "moved-original"
            projection.root.rename(moved)
            projection.root.mkdir(mode=0o700)
            marker = projection.root / "replacement"
            marker.write_bytes(b"keep")
            replacement_identity = projection.root.stat().st_dev, projection.root.stat().st_ino

            with self.assertRaisesRegex(
                EcosystemMaterializationError, f"^{ERROR}$"
            ) as raised:
                materializer.close(projection)

            self.assertIsNone(raised.exception.__cause__)
            self.assertEqual(marker.read_bytes(), b"keep")
            self.assertTrue(moved.exists())
            self.assertEqual(
                (projection.root.stat().st_dev, projection.root.stat().st_ino),
                replacement_identity,
            )

            preserved_replacement = base / "preserved-replacement"
            projection.root.rename(preserved_replacement)
            moved.rename(projection.root)
            materializer.close(projection)

            self.assertFalse(projection.root.exists())
            self.assertEqual(
                (preserved_replacement / "replacement").read_bytes(), b"keep"
            )
            materializer.close(projection)

    def test_close_rejects_missing_projection_until_exact_inode_is_restored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"file": b"body"})
            private = _private_resource("resource-1", {"file": b"body"})
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            materializer = SealedEcosystemMaterializer(base / "private")
            projection = materializer.materialize(portfolio, store)
            moved = base / "moved-original"
            projection.root.rename(moved)

            with self.assertRaisesRegex(
                EcosystemMaterializationError, f"^{ERROR}$"
            ) as raised:
                materializer.close(projection)

            self.assertIsNone(raised.exception.__cause__)
            self.assertTrue(moved.exists())

            moved.rename(projection.root)
            materializer.close(projection)

            self.assertFalse(projection.root.exists())
            materializer.close(projection)

    def test_private_root_and_publish_operations_use_no_follow_and_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            _write_files(source, {"file": b"body"})
            private = _private_resource("resource-1", {"file": b"body"})
            portfolio = _portfolio_for(private)
            store = FileEcosystemPrivateSourceStore(
                roots={"source-1": source}, resources=(private,)
            )
            real_open = os.open
            flags: list[int] = []

            def recording_open(path: object, open_flags: int, *args: object, **kwargs: object) -> int:
                flags.append(open_flags)
                return real_open(path, open_flags, *args, **kwargs)  # type: ignore[arg-type]

            with (
                patch("asterion.control.ecosystem_materialization.os.open", side_effect=recording_open),
                patch("asterion.control.ecosystem_materialization.os.fsync", wraps=os.fsync) as fsync,
            ):
                materializer = SealedEcosystemMaterializer(base / "private")
                projection = materializer.materialize(portfolio, store)

            self.assertTrue(flags)
            self.assertTrue(all(value & os.O_NOFOLLOW for value in flags))
            self.assertGreaterEqual(fsync.call_count, 4)
            materializer.close(projection)

    def test_private_root_symlink_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            target = base / "target"
            target.mkdir(mode=0o700)
            private_root = base / "private"
            private_root.symlink_to(target, target_is_directory=True)
            empty = build_ecosystem_portfolio(
                portfolio_id="portfolio-1",
                authority_id="authority-1",
                authority_revision=1,
                resources=(),
                registrations=(),
            )

            with self.assertRaisesRegex(EcosystemMaterializationError, f"^{ERROR}$"):
                SealedEcosystemMaterializer(private_root).materialize(
                    empty, _EmptyStore()
                )
            self.assertEqual(tuple(target.iterdir()), ())


class _EmptyStore:
    def private_resource(self, resource_id: str) -> EcosystemPrivateResource:
        raise EcosystemMaterializationError(ERROR)

    @contextmanager
    def open_file(self, resource_id: str, relative_path: str):
        raise EcosystemMaterializationError(ERROR)
        yield  # pragma: no cover


if __name__ == "__main__":
    unittest.main()
