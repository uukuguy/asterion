"""Private DCI gold registries and public-safe per-case coverage projections."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from asterion.capabilities.dci.implementation.datasets import (
    BenchmarkRow,
    DatasetError,
    load_benchmark_rows_bytes,
    normalize_retrieved_path,
)


_MANIFEST_SCHEMA = "dci.retrieval-coverage-manifest/v1"
_REGISTRY_SCHEMA = "dci.retrieval-coverage-registry/v1"
_MAX_INPUT_BYTES = 1 << 30
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DciCoverageError(Exception):
    """A context-free DCI coverage trust-boundary failure."""


@dataclass(frozen=True, slots=True)
class DciCoverageManifestRef:
    """One public-safe content binding to a private query manifest."""

    query_sha256: str
    relative_path: str
    sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.query_sha256) is not str
            or _SHA256.fullmatch(self.query_sha256) is None
            or type(self.relative_path) is not str
            or _safe_relative(self.relative_path)
            != f"manifests/{self.query_sha256}.json"
            or type(self.sha256) is not str
            or _SHA256.fullmatch(self.sha256) is None
        ):
            raise DciCoverageError("DCI coverage manifest reference is invalid")

    def to_mapping(self) -> dict[str, str]:
        return {
            "query_sha256": self.query_sha256,
            "path": self.relative_path,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class DciCoverageRegistry:
    """A published coverage-only registry without raw query identities."""

    dataset_id: str
    selected_ids_sha256: str
    manifests: tuple[DciCoverageManifestRef, ...]
    relative_path: str
    sha256: str

    def __post_init__(self) -> None:
        if (
            _safe_identity(self.dataset_id) != self.dataset_id
            or type(self.selected_ids_sha256) is not str
            or _SHA256.fullmatch(self.selected_ids_sha256) is None
            or type(self.manifests) is not tuple
            or not self.manifests
            or any(type(item) is not DciCoverageManifestRef for item in self.manifests)
            or len({item.query_sha256 for item in self.manifests}) != len(self.manifests)
            or self.relative_path != "registry.json"
            or type(self.sha256) is not str
            or _SHA256.fullmatch(self.sha256) is None
        ):
            raise DciCoverageError("DCI coverage registry is invalid")

    @property
    def selected_count(self) -> int:
        return len(self.manifests)

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": _REGISTRY_SCHEMA,
            "dataset_id": self.dataset_id,
            "selected_ids_sha256": self.selected_ids_sha256,
            "manifests": [manifest.to_mapping() for manifest in self.manifests],
        }


@dataclass(frozen=True, slots=True)
class DciCoverageRecord:
    """Content-free document coverage derived from one completed DCI run."""

    dataset_id: str
    query_sha256: str
    coverage_microunits: int
    retained_coverage_microunits: int | None
    localization_microunits: int | None
    evidence_state: Literal["observed"]
    evidence_sha256: str

    def __post_init__(self) -> None:
        metrics = (
            self.coverage_microunits,
            self.retained_coverage_microunits,
            self.localization_microunits,
        )
        if (
            _safe_identity(self.dataset_id) != self.dataset_id
            or type(self.query_sha256) is not str
            or _SHA256.fullmatch(self.query_sha256) is None
            or any(
                value is not None
                and (type(value) is not int or not 0 <= value <= 1_000_000)
                for value in metrics
            )
            or self.evidence_state != "observed"
            or type(self.evidence_sha256) is not str
            or _SHA256.fullmatch(self.evidence_sha256) is None
        ):
            raise DciCoverageError("DCI coverage record is invalid")

    def to_mapping(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "query_sha256": self.query_sha256,
            "coverage_microunits": self.coverage_microunits,
            "retained_coverage_microunits": self.retained_coverage_microunits,
            "localization_microunits": self.localization_microunits,
            "evidence_state": self.evidence_state,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    root: Path
    relative_path: str
    data: bytes
    sha256: str
    size: int
    device: int
    inode: int
    modified_ns: int


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def validate_coverage_manifest_bytes(
    data: bytes, *, corpus_dir: Path
) -> tuple[str, str, tuple[str, ...]]:
    """Validate canonical coverage-only manifest bytes and their exact corpus files."""

    try:
        if type(data) is not bytes:
            raise ValueError
        value = json.loads(data, object_pairs_hook=_unique_object)
        if (
            type(value) is not dict
            or set(value) != {"schema", "dataset_id", "query_id", "documents"}
            or value.get("schema") != _MANIFEST_SCHEMA
            or data != _canonical_bytes(value)
        ):
            raise ValueError
        from asterion.capabilities.dci.implementation.research.trajectory_resolution import (
            validate_gold_manifest_bytes,
        )

        return validate_gold_manifest_bytes(data, corpus_dir=Path(corpus_dir))
    except DciCoverageError:
        raise
    except Exception as error:
        raise DciCoverageError("DCI coverage manifest is invalid") from error


def validate_coverage_registry_bytes(data: bytes) -> DciCoverageRegistry:
    """Validate and reconstruct one canonical descriptor-safe registry."""

    try:
        if type(data) is not bytes:
            raise ValueError
        value = json.loads(data, object_pairs_hook=_unique_object)
        if (
            type(value) is not dict
            or set(value)
            != {"schema", "dataset_id", "selected_ids_sha256", "manifests"}
            or value.get("schema") != _REGISTRY_SCHEMA
            or data != _canonical_bytes(value)
        ):
            raise ValueError
        dataset_id = _safe_identity(value.get("dataset_id"))
        selected = value.get("selected_ids_sha256")
        entries = value.get("manifests")
        if (
            type(selected) is not str
            or _SHA256.fullmatch(selected) is None
            or type(entries) is not list
            or not entries
        ):
            raise ValueError
        refs: list[DciCoverageManifestRef] = []
        seen: set[str] = set()
        for entry in entries:
            if type(entry) is not dict or set(entry) != {
                "query_sha256",
                "path",
                "sha256",
            }:
                raise ValueError
            query_sha256 = entry.get("query_sha256")
            relative_path = entry.get("path")
            digest = entry.get("sha256")
            if (
                type(query_sha256) is not str
                or _SHA256.fullmatch(query_sha256) is None
                or query_sha256 in seen
                or type(relative_path) is not str
                or _safe_relative(relative_path)
                != f"manifests/{query_sha256}.json"
                or type(digest) is not str
                or _SHA256.fullmatch(digest) is None
            ):
                raise ValueError
            seen.add(query_sha256)
            refs.append(DciCoverageManifestRef(query_sha256, relative_path, digest))
        return DciCoverageRegistry(
            dataset_id=dataset_id,
            selected_ids_sha256=selected,
            manifests=tuple(refs),
            relative_path="registry.json",
            sha256=hashlib.sha256(data).hexdigest(),
        )
    except DciCoverageError:
        raise
    except Exception as error:
        raise DciCoverageError("DCI coverage registry is invalid") from error


def _safe_identity(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != unicodedata.normalize("NFC", value)
        or any(unicodedata.category(character) in {"Cc", "Cs"} for character in value)
    ):
        raise DciCoverageError("DCI coverage identity is invalid")
    return value


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or "\x00" in value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(part != unicodedata.normalize("NFC", part) for part in path.parts)
    ):
        raise DciCoverageError("DCI coverage path is invalid")
    return value


def _nofollow() -> int:
    value = getattr(os, "O_NOFOLLOW", None)
    if type(value) is not int:
        raise DciCoverageError("DCI coverage filesystem is unsupported")
    return value


def _open_directory(path: Path) -> int:
    requested = path.absolute()
    absolute = requested
    if len(requested.parts) > 1 and requested.parts[1] in {"var", "tmp"}:
        system_alias = Path(os.path.realpath(os.sep + requested.parts[1]))
        if system_alias in {Path("/private/var"), Path("/private/tmp")}:
            absolute = system_alias.joinpath(*requested.parts[2:])
    flags = os.O_RDONLY | os.O_DIRECTORY | _nofollow() | getattr(os, "O_CLOEXEC", 0)
    descriptor = -1
    try:
        descriptor = os.open(absolute.anchor, flags)
        for component in absolute.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise DciCoverageError("DCI coverage directory is unsafe") from error


def _read_from_descriptor(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(65_536, _MAX_INPUT_BYTES + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > _MAX_INPUT_BYTES:
            raise DciCoverageError("DCI coverage input is oversized")


def _read_snapshot(root: Path, relative_path: str) -> _FileSnapshot:
    relative_path = _safe_relative(relative_path)
    root_fd = _open_directory(root)
    directory_fd = root_fd
    owned: list[int] = []
    descriptor = -1
    try:
        parts = PurePosixPath(relative_path).parts
        directory_flags = (
            os.O_RDONLY | os.O_DIRECTORY | _nofollow() | getattr(os, "O_CLOEXEC", 0)
        )
        for component in parts[:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            owned.append(next_fd)
            directory_fd = next_fd
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NONBLOCK | _nofollow() | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise DciCoverageError("DCI coverage input is not regular")
        first = _read_from_descriptor(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        second = _read_from_descriptor(descriptor)
        after = os.fstat(descriptor)
        metadata = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if (
            metadata
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or first != second
            or len(first) != before.st_size
        ):
            raise DciCoverageError("DCI coverage input changed while reading")
        return _FileSnapshot(
            root=root.absolute(),
            relative_path=relative_path,
            data=first,
            sha256=hashlib.sha256(first).hexdigest(),
            size=len(first),
            device=before.st_dev,
            inode=before.st_ino,
            modified_ns=before.st_mtime_ns,
        )
    except DciCoverageError:
        raise
    except Exception as error:
        raise DciCoverageError("DCI coverage input is unsafe") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        for owned_fd in reversed(owned):
            os.close(owned_fd)
        os.close(root_fd)


def _read_path_snapshot(path: Path) -> _FileSnapshot:
    absolute = path.absolute()
    if absolute.name in {"", ".", ".."}:
        raise DciCoverageError("DCI coverage input path is invalid")
    return _read_snapshot(absolute.parent, absolute.name)


def _snapshot_matches(expected: _FileSnapshot) -> bool:
    actual = _read_snapshot(expected.root, expected.relative_path)
    return (
        actual.sha256,
        actual.size,
        actual.device,
        actual.inode,
        actual.modified_ns,
    ) == (
        expected.sha256,
        expected.size,
        expected.device,
        expected.inode,
        expected.modified_ns,
    )


def _corpus_candidates(corpus_dir: Path, wanted: frozenset[str]) -> dict[str, list[str]]:
    results = {name: [] for name in wanted}
    root_fd = _open_directory(corpus_dir)

    def visit(directory_fd: int, prefix: tuple[str, ...]) -> None:
        for name in sorted(os.listdir(directory_fd)):
            if name in {"", ".", ".."} or "/" in name or "\\" in name:
                raise DciCoverageError("DCI coverage corpus entry is invalid")
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                if normalize_retrieved_path(name, corpus_dir) in wanted:
                    raise DciCoverageError("DCI coverage corpus document is unsafe")
                continue
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | _nofollow()
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=directory_fd,
                )
                try:
                    visit(child, (*prefix, name))
                finally:
                    os.close(child)
                continue
            if stat.S_ISREG(metadata.st_mode):
                normalized = normalize_retrieved_path(name, corpus_dir)
                if normalized in wanted:
                    results[normalized].append(PurePosixPath(*prefix, name).as_posix())

    try:
        visit(root_fd, ())
    except DciCoverageError:
        raise
    except (DatasetError, OSError) as error:
        raise DciCoverageError("DCI coverage corpus is unsafe") from error
    finally:
        os.close(root_fd)
    return results


def _bind_documents(
    corpus_dir: Path, rows: tuple[BenchmarkRow, ...]
) -> tuple[dict[str, tuple[dict[str, str], ...]], tuple[_FileSnapshot, ...]]:
    row_gold: dict[str, tuple[tuple[str, str], ...]] = {}
    all_gold: list[str] = []
    source_ids: dict[str, str] = {}
    for row in rows:
        raw = row.gold_ids if row.gold_ids is not None else row.gold_docs
        if raw is None:
            raise DciCoverageError("DCI coverage requires IR dataset rows")
        normalized = tuple(normalize_retrieved_path(value, corpus_dir) for value in raw)
        if len(set(normalized)) != len(normalized):
            raise DciCoverageError("DCI coverage gold documents are ambiguous")
        for source_id, normalized_id in zip(raw, normalized, strict=True):
            _safe_relative(source_id)
            prior = source_ids.setdefault(normalized_id, source_id)
            if prior != source_id:
                raise DciCoverageError("DCI coverage gold documents are ambiguous")
        row_gold[row.query_id] = tuple(zip(raw, normalized, strict=True))
        all_gold.extend(normalized)
    wanted = frozenset(all_gold)
    candidates = _corpus_candidates(corpus_dir, wanted)
    snapshots_by_path: dict[str, _FileSnapshot] = {}
    document_by_id: dict[str, dict[str, str]] = {}
    for document_id in sorted(wanted):
        paths = candidates.get(document_id, [])
        if len(paths) != 1:
            raise DciCoverageError("DCI coverage gold document binding is ambiguous")
        relative_path = paths[0]
        snapshot = _read_snapshot(corpus_dir, relative_path)
        try:
            snapshot.data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise DciCoverageError("DCI coverage corpus document is not UTF-8") from error
        snapshots_by_path[relative_path] = snapshot
        document_by_id[document_id] = {
            "id": source_ids[document_id],
            "path": relative_path,
            "sha256": snapshot.sha256,
        }
    manifests = {
        row.query_id: tuple(
            document_by_id[normalized_id]
            for _source_id, normalized_id in sorted(row_gold[row.query_id])
        )
        for row in rows
    }
    return manifests, tuple(snapshots_by_path[path] for path in sorted(snapshots_by_path))


def _write_at(directory_fd: int, relative_path: str, data: bytes) -> None:
    parts = PurePosixPath(_safe_relative(relative_path)).parts
    current = directory_fd
    owned: list[int] = []
    descriptor = -1
    try:
        for component in parts[:-1]:
            try:
                os.mkdir(component, 0o700, dir_fd=current)
            except FileExistsError:
                pass
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | _nofollow(),
                dir_fd=current,
            )
            os.fchmod(next_fd, 0o700)
            owned.append(next_fd)
            current = next_fd
        descriptor = os.open(
            parts[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _nofollow(),
            0o600,
            dir_fd=current,
        )
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(data)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("short write")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        for owned_fd in reversed(owned):
            os.close(owned_fd)


def _staging_root(output_root: Path) -> tuple[int, int, str]:
    absolute = output_root.absolute()
    if absolute.name in {"", ".", ".."}:
        raise DciCoverageError("DCI coverage output is invalid")
    parent_fd = _open_directory(absolute.parent)
    try:
        try:
            os.stat(absolute.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise DciCoverageError("DCI coverage output already exists")
        for _attempt in range(16):
            staging_name = f".{absolute.name}.staging-{secrets.token_hex(8)}"
            try:
                os.mkdir(staging_name, 0o700, dir_fd=parent_fd)
                break
            except FileExistsError:
                continue
        else:
            raise DciCoverageError("DCI coverage staging is unavailable")
        staging_fd = os.open(
            staging_name,
            os.O_RDONLY | os.O_DIRECTORY | _nofollow(),
            dir_fd=parent_fd,
        )
        os.fchmod(staging_fd, 0o700)
        return parent_fd, staging_fd, staging_name
    except Exception:
        os.close(parent_fd)
        raise


def _remove_staging(parent_fd: int, staging_fd: int, staging_name: str) -> None:
    try:
        for name in os.listdir(staging_fd):
            metadata = os.stat(name, dir_fd=staging_fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | _nofollow(), dir_fd=staging_fd)
                try:
                    for child_name in os.listdir(child):
                        os.unlink(child_name, dir_fd=child)
                finally:
                    os.close(child)
                os.rmdir(name, dir_fd=staging_fd)
            else:
                os.unlink(name, dir_fd=staging_fd)
        os.close(staging_fd)
        os.rmdir(staging_name, dir_fd=parent_fd)
    except Exception:
        try:
            os.close(staging_fd)
        except OSError:
            pass


def prepare_coverage_registry(
    *,
    dataset_id: str,
    dataset_path: Path,
    corpus_dir: Path,
    selected_count: int,
    output_root: Path,
) -> DciCoverageRegistry:
    """Publish exact coverage-only manifests for the first N validated IR rows."""

    parent_fd = -1
    staging_fd = -1
    staging_name = ""
    published: DciCoverageRegistry | None = None
    try:
        dataset_id = _safe_identity(dataset_id)
        if type(selected_count) is not int or selected_count <= 0:
            raise DciCoverageError("DCI coverage selection is invalid")
        dataset_snapshot = _read_path_snapshot(Path(dataset_path))
        rows = load_benchmark_rows_bytes(dataset_snapshot.data)
        if selected_count > len(rows):
            raise DciCoverageError("DCI coverage selection exceeds dataset")
        selected = rows[:selected_count]
        documents, corpus_snapshots = _bind_documents(Path(corpus_dir), selected)
        selected_ids = tuple(row.query_id for row in selected)
        refs: list[DciCoverageManifestRef] = []
        encoded_manifests: list[tuple[str, bytes]] = []
        for row in selected:
            query_sha256 = _canonical_sha256(row.query_id)
            manifest = {
                "schema": _MANIFEST_SCHEMA,
                "dataset_id": dataset_id,
                "query_id": row.query_id,
                "documents": list(documents[row.query_id]),
            }
            encoded = _canonical_bytes(manifest)
            relative_path = f"manifests/{query_sha256}.json"
            ref = DciCoverageManifestRef(
                query_sha256=query_sha256,
                relative_path=relative_path,
                sha256=hashlib.sha256(encoded).hexdigest(),
            )
            refs.append(ref)
            encoded_manifests.append((relative_path, encoded))
        selected_ids_sha256 = _canonical_sha256(selected_ids)
        registry_mapping = {
            "schema": _REGISTRY_SCHEMA,
            "dataset_id": dataset_id,
            "selected_ids_sha256": selected_ids_sha256,
            "manifests": [manifest.to_mapping() for manifest in refs],
        }
        registry_bytes = _canonical_bytes(registry_mapping)
        published = DciCoverageRegistry(
            dataset_id=dataset_id,
            selected_ids_sha256=selected_ids_sha256,
            manifests=tuple(refs),
            relative_path="registry.json",
            sha256=hashlib.sha256(registry_bytes).hexdigest(),
        )
        if validate_coverage_registry_bytes(registry_bytes) != published:
            raise DciCoverageError("DCI coverage registry is invalid")
        parent_fd, staging_fd, staging_name = _staging_root(Path(output_root))
        for relative_path, encoded in encoded_manifests:
            _write_at(staging_fd, relative_path, encoded)
        _write_at(staging_fd, published.relative_path, registry_bytes)
        if not _snapshot_matches(dataset_snapshot) or any(
            not _snapshot_matches(snapshot) for snapshot in corpus_snapshots
        ):
            raise DciCoverageError("DCI coverage input changed before publish")
        os.fsync(staging_fd)
        os.close(staging_fd)
        staging_fd = -1
        output_name = Path(output_root).absolute().name
        try:
            os.stat(output_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise DciCoverageError("DCI coverage output already exists")
        os.rename(staging_name, output_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        staging_name = ""
        os.fsync(parent_fd)
    except DciCoverageError:
        raise
    except (DatasetError, OSError, UnicodeError, ValueError) as error:
        raise DciCoverageError("DCI coverage registry preparation failed") from error
    finally:
        if parent_fd >= 0:
            if staging_name:
                if staging_fd < 0:
                    try:
                        staging_fd = os.open(
                            staging_name,
                            os.O_RDONLY | os.O_DIRECTORY | _nofollow(),
                            dir_fd=parent_fd,
                        )
                    except OSError:
                        staging_fd = -1
                if staging_fd >= 0:
                    _remove_staging(parent_fd, staging_fd, staging_name)
                    staging_fd = -1
            elif staging_fd >= 0:
                os.close(staging_fd)
            os.close(parent_fd)
    if published is None:
        raise DciCoverageError("DCI coverage registry preparation failed")
    return published


def analyze_coverage_run(
    *, run_dir: Path, corpus_dir: Path, manifest: Path | bytes | Mapping[str, object]
) -> DciCoverageRecord:
    """Analyze one completed run and return a content-free coverage projection."""

    # Imported lazily so the DCI trajectory implementation remains product-owned
    # without becoming a dependency of the generic Pathlight framework.
    from asterion.capabilities.dci.implementation.research.trajectory_resolution import (
        TrajectoryAnalysisConfig,
        analyze_trajectory_resolution,
    )

    try:
        state_snapshot = _read_snapshot(Path(run_dir), "state.json")
        state = json.loads(state_snapshot.data)
        attempts = state.get("attempts") if type(state) is dict else None
        if type(attempts) is not list or not attempts:
            raise DciCoverageError("DCI coverage run is incomplete")
        attempt = len(attempts)
        arguments: dict[str, object] = {
            "run_dir": Path(run_dir),
            "attempt": attempt,
            "corpus_dir": Path(corpus_dir),
            "config": TrajectoryAnalysisConfig(segment_characters=4096),
        }
        if isinstance(manifest, Path):
            arguments["gold_manifest_path"] = manifest
        elif type(manifest) is bytes:
            arguments["gold_manifest_bytes"] = manifest
        elif type(manifest) is dict:
            arguments["gold_manifest_bytes"] = _canonical_bytes(manifest)
        else:
            raise DciCoverageError("DCI coverage manifest is invalid")
        evidence = analyze_trajectory_resolution(**arguments)  # type: ignore[arg-type]
        dataset = evidence["dataset"]
        metrics = evidence["metrics"]
        coverage = metrics["coverage"]["mean"]
        retained = metrics["retained_coverage"]["value"]
        localization = metrics["localization"]["value"]
        if (
            type(dataset) is not dict
            or type(dataset.get("dataset_id")) is not str
            or type(dataset.get("query_id")) is not str
            or type(coverage) is not float
        ):
            raise DciCoverageError("DCI coverage evidence is invalid")
        return DciCoverageRecord(
            dataset_id=dataset["dataset_id"],
            query_sha256=_canonical_sha256(dataset["query_id"]),
            coverage_microunits=_microunits(coverage),
            retained_coverage_microunits=(
                None if retained is None else _microunits(retained)
            ),
            localization_microunits=(
                None if localization is None else _microunits(localization)
            ),
            evidence_state="observed",
            evidence_sha256=str(evidence["identity"]["sha256"]),
        )
    except DciCoverageError:
        raise
    except Exception as error:
        raise DciCoverageError("DCI coverage evidence is invalid") from error


def _microunits(value: object) -> int:
    if type(value) is not float or not 0.0 <= value <= 1.0:
        raise DciCoverageError("DCI coverage metric is invalid")
    return int(round(value * 1_000_000))


__all__ = (
    "DciCoverageError",
    "DciCoverageManifestRef",
    "DciCoverageRecord",
    "DciCoverageRegistry",
    "analyze_coverage_run",
    "prepare_coverage_registry",
    "validate_coverage_manifest_bytes",
    "validate_coverage_registry_bytes",
)
