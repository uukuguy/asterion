"""Private, append-only evidence for one Asterion-prime execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from stat import S_ISDIR
from types import MappingProxyType
from typing import NoReturn, cast


_MAX_DEPTH = 16
_MAX_NODES = 512
_MAX_BYTES = 64 * 1024
_TRACE_FILE = "prime-trace.jsonl"
_SEAL_FILE = "prime-trace.seal.json"


class PrimeTraceError(RuntimeError):
    """A trace boundary rejected private evidence without disclosing it."""


@dataclass(frozen=True, repr=False, slots=True)
class PrimeTraceEntry:
    sequence: int
    kind: str
    identities: Mapping[str, str]
    payload: Mapping[str, object]
    previous_sha256: str | None
    sha256: str


@dataclass(frozen=True, slots=True)
class PrimeTraceSeal:
    entry_count: int
    final_sha256: str
    sealed_at: str


def _reject() -> NoReturn:
    raise PrimeTraceError("trace is unavailable")


def _snapshot(value: object, *, depth: int = 0, nodes: list[int] | None = None) -> object:
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if nodes[0] > _MAX_NODES or depth > _MAX_DEPTH:
        _reject()
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _reject()
        return value
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            _reject()
        return value
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        copied: dict[str, object] = {}
        for key, item in mapping.items():
            if type(key) is not str or key in copied:
                _reject()
            copied[key] = _snapshot(item, depth=depth + 1, nodes=nodes)
        return MappingProxyType(dict(sorted(copied.items())))
    if type(value) is list:
        return tuple(_snapshot(item, depth=depth + 1, nodes=nodes) for item in cast(list[object], value))
    if type(value) is tuple:
        return tuple(_snapshot(item, depth=depth + 1, nodes=nodes) for item in cast(tuple[object, ...], value))
    _reject()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_plain(item) for item in value]
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            _plain(value), allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError):
        _reject()
    if len(encoded) > _MAX_BYTES:
        _reject()
    return encoded


def _digest(value: object) -> str:
    return "sha256:" + sha256(_canonical_bytes(value)).hexdigest()


def _identities(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not value:
        _reject()
    copied: dict[str, str] = {}
    for key, item in cast(Mapping[object, object], value).items():
        if type(key) is not str or not key or type(item) is not str or not item:
            _reject()
        try:
            key.encode("utf-8")
            item.encode("utf-8")
        except UnicodeEncodeError:
            _reject()
        copied[key] = item
    _canonical_bytes(copied)
    return MappingProxyType(dict(sorted(copied.items())))


def _payload(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _reject()
    snapshot = _snapshot(value)
    if not isinstance(snapshot, Mapping):
        _reject()
    _canonical_bytes(snapshot)
    return cast(Mapping[str, object], snapshot)


def _entry_digest(
    sequence: int,
    kind: str,
    identities: Mapping[str, str],
    payload: Mapping[str, object],
    previous_sha256: str | None,
) -> str:
    return _digest(
        {
            "identities": identities,
            "kind": kind,
            "payload": payload,
            "previous_sha256": previous_sha256,
            "sequence": sequence,
        }
    )


def validate_trace(entries: object) -> tuple[PrimeTraceEntry, ...]:
    """Verify a detached trace before using it for a public projection."""

    if type(entries) is not tuple:
        _reject()
    expected_previous: str | None = None
    expected_identities: Mapping[str, str] | None = None
    validated: list[PrimeTraceEntry] = []
    for sequence, entry in enumerate(cast(tuple[object, ...], entries), 1):
        if type(entry) is not PrimeTraceEntry or entry.sequence != sequence:
            _reject()
        if type(entry.kind) is not str or not entry.kind or len(entry.kind) > 128:
            _reject()
        try:
            entry.kind.encode("utf-8")
        except UnicodeEncodeError:
            _reject()
        identities = _identities(entry.identities)
        payload = _payload(entry.payload)
        if expected_identities is None:
            expected_identities = identities
        elif dict(expected_identities) != dict(identities):
            _reject()
        if entry.previous_sha256 != expected_previous:
            _reject()
        if entry.sha256 != _entry_digest(sequence, entry.kind, identities, payload, expected_previous):
            _reject()
        expected_previous = entry.sha256
        validated.append(
            PrimeTraceEntry(
                sequence=entry.sequence,
                kind=entry.kind,
                identities=identities,
                payload=payload,
                previous_sha256=entry.previous_sha256,
                sha256=entry.sha256,
            )
        )
    if not validated or validated[-1].kind != "trace.sealed":
        _reject()
    marker = validated[-1]
    if (
        any(entry.kind == "trace.sealed" for entry in validated[:-1])
        or set(marker.payload) != {"entry_count", "final_sha256"}
        or marker.payload["entry_count"] != len(validated) - 1
        or marker.payload["final_sha256"] != marker.previous_sha256
        or marker.previous_sha256 is None
    ):
        _reject()
    return tuple(validated)


class PrimeTraceRecorder:
    """Create one private, hash-chained trace in a pinned existing directory."""

    __slots__ = ("_directory_fd", "_entries", "_identities", "_seal", "_trace_fd")

    def __init__(self, directory: Path | str) -> None:
        if not isinstance(directory, (Path, str)):
            _reject()
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(os.fspath(directory), flags)
            if not S_ISDIR(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                _reject()
        except (OSError, TypeError):
            _reject()
        if descriptor is None:
            _reject()
        trace_descriptor: int | None = None
        try:
            trace_descriptor = os.open(
                _TRACE_FILE,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=descriptor,
            )
        except OSError:
            os.close(descriptor)
            _reject()
        if trace_descriptor is None:
            os.close(descriptor)
            _reject()
        self._directory_fd: int | None = descriptor
        self._entries: list[PrimeTraceEntry] = []
        self._identities: Mapping[str, str] | None = None
        self._seal: PrimeTraceSeal | None = None
        self._trace_fd: int | None = trace_descriptor

    def __repr__(self) -> str:
        return "<PrimeTraceRecorder redacted>"

    @staticmethod
    def _write_descriptor(file_descriptor: int, payload: object) -> None:
        data = _canonical_bytes(payload) + b"\n"
        try:
            offset = 0
            while offset < len(data):
                written = os.write(file_descriptor, data[offset:])
                if written <= 0:
                    raise OSError
                offset += written
            os.fsync(file_descriptor)
        except OSError:
            _reject()

    def _write_seal(self, payload: object) -> None:
        if self._directory_fd is None:
            _reject()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        file_descriptor: int | None = None
        try:
            file_descriptor = os.open(_SEAL_FILE, flags, 0o600, dir_fd=self._directory_fd)
            self._write_descriptor(file_descriptor, payload)
        except OSError:
            _reject()
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)

    def append(
        self, kind: str, identities: Mapping[str, str], private_payload: Mapping[str, object]
    ) -> PrimeTraceEntry:
        trace_descriptor = self._trace_fd
        if self._seal is not None or self._directory_fd is None or trace_descriptor is None:
            _reject()
        if type(kind) is not str or not kind or len(kind) > 128:
            _reject()
        if kind == "trace.sealed":
            _reject()
        try:
            kind.encode("utf-8")
        except UnicodeEncodeError:
            _reject()
        stable_identities = _identities(identities)
        payload = _payload(private_payload)
        if self._identities is not None and dict(self._identities) != dict(stable_identities):
            _reject()
        entry = self._append_entry(kind, stable_identities, payload)
        if self._identities is None:
            self._identities = stable_identities
        return entry

    def _append_entry(
        self, kind: str, identities: Mapping[str, str], payload: Mapping[str, object]
    ) -> PrimeTraceEntry:
        trace_descriptor = self._trace_fd
        if trace_descriptor is None:
            _reject()
        previous = self._entries[-1].sha256 if self._entries else None
        entry = PrimeTraceEntry(
            sequence=len(self._entries) + 1,
            kind=kind,
            identities=identities,
            payload=payload,
            previous_sha256=previous,
            sha256=_entry_digest(len(self._entries) + 1, kind, identities, payload, previous),
        )
        self._write_descriptor(
            trace_descriptor,
            {
                "identities": entry.identities,
                "kind": entry.kind,
                "payload": entry.payload,
                "previous_sha256": entry.previous_sha256,
                "sequence": entry.sequence,
                "sha256": entry.sha256,
            },
        )
        self._entries.append(entry)
        return entry

    def snapshot(self) -> tuple[PrimeTraceEntry, ...]:
        """Return the current private snapshot; only a sealed one is analyzable."""

        return tuple(self._entries)

    @property
    def entries(self) -> tuple[PrimeTraceEntry, ...]:
        if self._seal is None:
            _reject()
        return tuple(self._entries)

    def seal(self) -> PrimeTraceSeal:
        if self._seal is not None:
            return self._seal
        if not self._entries or self._identities is None:
            _reject()
        previous_sha256 = self._entries[-1].sha256
        final_entry = self._append_entry(
            "trace.sealed",
            self._identities,
            {"entry_count": len(self._entries), "final_sha256": previous_sha256},
        )
        seal = PrimeTraceSeal(
            entry_count=len(self._entries),
            final_sha256=final_entry.sha256,
            sealed_at=datetime.now(timezone.utc).isoformat(),
        )
        self._write_seal(
            {
                "entry_count": seal.entry_count,
                "final_sha256": seal.final_sha256,
                "sealed_at": seal.sealed_at,
            },
        )
        self._seal = seal
        if self._trace_fd is not None:
            os.close(self._trace_fd)
            self._trace_fd = None
        if self._directory_fd is not None:
            os.close(self._directory_fd)
            self._directory_fd = None
        return seal


__all__ = (
    "PrimeTraceEntry",
    "PrimeTraceError",
    "PrimeTraceRecorder",
    "PrimeTraceSeal",
    "validate_trace",
)
