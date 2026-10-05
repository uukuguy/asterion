"""Domain-neutral, serial persistent Python research workspace.

The operator supplies all bootstrap resources. Arbitrary Python runs under the
operator's UID; this lifecycle and capability separation is not an OS sandbox.
Only explicit successful-cell exports are durable, never arbitrary namespaces.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from time import monotonic
from types import MappingProxyType
from typing import Literal, Protocol
import uuid

from asterion.agents.prime.tools import PrimeToolResult, _freeze_json
from asterion.runtime.host import CancellationSignal


class PersistentIpythonHostError(ValueError):
    def __init__(self) -> None:
        super().__init__("Prime workspace operation is unavailable")


class _ExportLimitError(PersistentIpythonHostError):
    pass


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item) for item in value]
    return value


def _encoded(value: object) -> bytes:
    return json.dumps(
        _plain(value),
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()


def _name(value: object) -> bool:
    return (
        type(value) is str
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", value) is not None
    )


def _binding(value: object) -> bool:
    return (
        type(value) is str
        and value.isidentifier()
        and value not in {"prime_workspace", "__builtins__"}
    )


@dataclass(frozen=True, repr=False, slots=True)
class KernelBootstrap:
    modules: Mapping[str, str]
    initial_data: Mapping[str, object]
    workspace: Path

    def __post_init__(self) -> None:
        try:
            if (
                not isinstance(self.modules, Mapping)
                or not isinstance(self.initial_data, Mapping)
                or not isinstance(self.workspace, Path)
            ):
                raise ValueError
            if any(
                not _binding(name) or type(source) is not str
                for name, source in self.modules.items()
            ):
                raise ValueError
            if any(not _binding(name) for name in self.initial_data):
                raise ValueError
            object.__setattr__(self, "modules", MappingProxyType(dict(self.modules)))
            object.__setattr__(self, "initial_data", _freeze_json(self.initial_data))
            _encoded(self.initial_data)
        except Exception:
            raise PersistentIpythonHostError() from None

    def __repr__(self) -> str:
        return "<KernelBootstrap redacted>"


@dataclass(frozen=True, slots=True)
class KernelLimits:
    max_code_bytes: int = 16 * 1024
    deadline_seconds: float = 60.0
    max_output_bytes: int = 64 * 1024
    max_exports_per_cell: int = 16
    max_export_bytes: int = 256 * 1024
    max_exports: int = 256
    max_total_export_bytes: int = 16 * 1024 * 1024
    cleanup_seconds: float = 2.0

    def __post_init__(self) -> None:
        for name in (
            "max_code_bytes",
            "max_output_bytes",
            "max_exports_per_cell",
            "max_export_bytes",
            "max_exports",
            "max_total_export_bytes",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise PersistentIpythonHostError()
        for value in (self.deadline_seconds, self.cleanup_seconds):
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or value <= 0
            ):
                raise PersistentIpythonHostError()
        # A complete status envelope must fit even when no stdout is retained.
        if self.max_output_bytes < 256:
            raise PersistentIpythonHostError()


def _export_payload(
    name: str, kind: str, value: object, source_call_id: str
) -> dict[str, object]:
    return {
        "name": name,
        "kind": kind,
        "value": _plain(value),
        "source_call_id": source_call_id,
    }


def _export_id(payload: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(_encoded(payload)).hexdigest()


@dataclass(frozen=True, repr=False, slots=True)
class KernelExport:
    export_id: str
    name: str
    kind: Literal["json", "text"]
    value: object
    source_call_id: str

    def __post_init__(self) -> None:
        try:
            if (
                not _name(self.name)
                or self.kind not in {"json", "text"}
                or type(self.source_call_id) is not str
                or not self.source_call_id
            ):
                raise ValueError
            if self.kind == "text" and type(self.value) is not str:
                raise ValueError
            object.__setattr__(self, "value", _freeze_json(self.value))
            if self.export_id != _export_id(
                _export_payload(self.name, self.kind, self.value, self.source_call_id)
            ):
                raise ValueError
        except Exception:
            raise PersistentIpythonHostError() from None

    @property
    def id(self) -> str:
        return self.export_id

    def __repr__(self) -> str:
        return "<KernelExport redacted>"


class PersistentIpythonWorker(Protocol):
    async def start(
        self,
        bootstrap: KernelBootstrap,
        *,
        limits: KernelLimits,
        signal: CancellationSignal,
    ) -> None: ...
    async def execute_cell(
        self, code: str, *, signal: CancellationSignal
    ) -> Mapping[str, object]: ...
    async def restore(
        self,
        sources: tuple[str, ...],
        data: Mapping[str, object],
        *,
        signal: CancellationSignal,
    ) -> None: ...
    async def close(self) -> None: ...


class PersistentIpythonHost:
    def __init__(
        self,
        worker: PersistentIpythonWorker,
        bootstrap: KernelBootstrap,
        limits: KernelLimits = KernelLimits(),
        observer: Callable[[str, Mapping[str, object]], None] | None = None,
    ) -> None:
        if (
            type(bootstrap) is not KernelBootstrap
            or type(limits) is not KernelLimits
            or any(
                not callable(getattr(worker, name, None))
                for name in ("start", "execute_cell", "restore", "close")
            )
        ):
            raise PersistentIpythonHostError()
        self._worker = worker
        self._bootstrap = bootstrap
        self._limits = limits
        self._lock = asyncio.Lock()
        self._started = False
        self._lost = False
        self._closed = False
        self._used = False
        self._call_ids: set[str] = set()
        self._export_count = 0
        self._export_bytes = 0
        if observer is not None and not callable(observer):
            raise PersistentIpythonHostError()
        self._observer = observer
        self._generation = uuid.uuid4().hex
        self._execution_status = "idle"

    def __repr__(self) -> str:
        return "<PersistentIpythonHost redacted>"

    @property
    def lost(self) -> bool:
        return self._lost

    @property
    def generation(self) -> str:
        return self._generation

    def status(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "generation": self.generation,
                "execution_status": self._execution_status,
                "lost": self._lost,
                "closed": self._closed,
                "started": self._started,
            }
        )

    async def execute(
        self, call_id: str, code: str, signal: CancellationSignal
    ) -> PrimeToolResult:
        safe_id = call_id if type(call_id) is str and call_id else "invalid"
        try:
            valid = (
                type(call_id) is str
                and bool(call_id)
                and type(code) is str
                and 0 < len(code.encode("utf-8")) <= self._limits.max_code_bytes
            )
        except UnicodeError:
            valid = False
        if not valid:
            return self._result(safe_id, "error", "IPython cell rejected")
        async with self._lock:
            if call_id in self._call_ids:
                return self._result(call_id, "error", "IPython duplicate call rejected")
            self._call_ids.add(call_id)
            if self._lost or self._closed:
                return self._result(
                    call_id, "uncertain", "IPython kernel lost or closed"
                )
            if signal.cancelled:
                return self._result(
                    call_id,
                    "error",
                    "IPython cell cancelled before execution",
                    execution_status="interrupted",
                )
            started_at = monotonic()
            try:
                await self._start(signal)
                self._used = True
                self._emit("cell_started", call_id, "running", None)
                value = await self._operation(
                    self._worker.execute_cell(code, signal=signal), signal
                )
                if (
                    not isinstance(value, Mapping)
                    or set(value) != {"is_error", "output", "exports"}
                    or type(value["is_error"]) is not bool
                    or type(value["output"]) is not str
                    or type(value["exports"]) is not list
                ):
                    raise PersistentIpythonHostError()
                output = value["output"]
                if len(output.encode("utf-8")) > self._limits.max_output_bytes:
                    raise PersistentIpythonHostError()
                if value["is_error"]:
                    self._emit("cell_finished", call_id, "python-error", started_at)
                    return self._result(call_id, "error", output)
                try:
                    exports = self._publish(call_id, value["exports"])
                except _ExportLimitError:
                    self._emit("cell_finished", call_id, "python-error", started_at)
                    return self._result(
                        call_id,
                        "error",
                        "IPython export limit reached; no exports published",
                    )
                self._emit("cell_finished", call_id, "ok", started_at, exports)
                return self._result(call_id, "ok", output, exports)
            except asyncio.CancelledError:
                await self._mark_lost()
                self._emit("cell_interrupted", call_id, "interrupted", started_at)
                self._emit("kernel_lost", call_id, "interrupted", started_at)
                raise
            except (TimeoutError, asyncio.TimeoutError):
                await self._mark_lost()
                self._emit("cell_interrupted", call_id, "interrupted", started_at)
                self._emit("kernel_lost", call_id, "interrupted", started_at)
                return self._result(
                    call_id,
                    "uncertain",
                    "IPython kernel lost; computation interrupted",
                    execution_status="interrupted",
                )
            except Exception:
                await self._mark_lost()
                self._emit("kernel_lost", call_id, "lost", started_at)
                return self._result(
                    call_id,
                    "uncertain",
                    "IPython kernel lost; computation did not complete",
                )

    def read_export(self, export_id: str) -> KernelExport:
        try:
            if (
                type(export_id) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", export_id) is None
            ):
                raise ValueError
            path = self._bootstrap.workspace / "exports" / (export_id[7:] + ".json")
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as handle:
                raw = handle.read(self._limits.max_export_bytes + 4097)
            if len(raw) > self._limits.max_export_bytes + 4096:
                raise ValueError
            payload = json.loads(raw)
            if type(payload) is not dict or set(payload) != {
                "name",
                "kind",
                "value",
                "source_call_id",
            }:
                raise ValueError
            return KernelExport(export_id=export_id, **payload)
        except Exception:
            raise PersistentIpythonHostError() from None

    async def restore(
        self,
        source_exports: tuple[KernelExport, ...],
        data_exports: Mapping[str, KernelExport],
        signal: CancellationSignal,
    ) -> None:
        async with self._lock:
            try:
                if (
                    self._used
                    or self._started
                    or self._lost
                    or self._closed
                    or type(source_exports) is not tuple
                    or not isinstance(data_exports, Mapping)
                ):
                    raise ValueError
                if len(source_exports) + len(data_exports) > self._limits.max_exports:
                    raise ValueError
                for artifact in source_exports:
                    if (
                        type(artifact) is not KernelExport
                        or artifact.kind != "text"
                        or len(_encoded(artifact.value)) > self._limits.max_export_bytes
                    ):
                        raise ValueError
                for name, artifact in data_exports.items():
                    if (
                        not _binding(name)
                        or type(artifact) is not KernelExport
                        or artifact.kind != "json"
                        or len(_encoded(artifact.value)) > self._limits.max_export_bytes
                    ):
                        raise ValueError
                sources = tuple(artifact.value for artifact in source_exports)
                data = {
                    name: _plain(artifact.value)
                    for name, artifact in data_exports.items()
                }
                if (
                    len(_encoded({"sources": sources, "data": data}))
                    > self._limits.max_total_export_bytes
                    or signal.cancelled
                ):
                    raise ValueError
            except Exception:
                raise PersistentIpythonHostError() from None
            try:
                await self._start(signal)
                await self._operation(
                    self._worker.restore(sources, data, signal=signal), signal
                )
                self._used = True
            except asyncio.CancelledError:
                await self._mark_lost()
                raise
            except Exception:
                await self._mark_lost()
                raise PersistentIpythonHostError() from None

    async def close(self) -> None:
        async with self._lock:
            if not self._closed:
                await asyncio.wait_for(
                    self._worker.close(), self._limits.cleanup_seconds
                )
                self._closed = True

    async def _start(self, signal: CancellationSignal) -> None:
        if not self._started:
            await self._operation(
                self._worker.start(self._bootstrap, limits=self._limits, signal=signal),
                signal,
            )
            self._started = True

    async def _operation(self, operation: object, signal: CancellationSignal) -> object:
        task = asyncio.ensure_future(operation)
        deadline = monotonic() + self._limits.deadline_seconds
        try:
            while not task.done():
                if signal.cancelled or monotonic() >= deadline:
                    raise TimeoutError
                await asyncio.wait(
                    {task}, timeout=min(0.01, max(0.0, deadline - monotonic()))
                )
            return task.result()
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _mark_lost(self) -> None:
        self._lost = True
        try:
            await asyncio.wait_for(self._worker.close(), self._limits.cleanup_seconds)
            self._closed = True
        except Exception:
            pass

    def _publish(self, call_id: str, values: list[object]) -> tuple[KernelExport, ...]:
        if (
            len(values) > self._limits.max_exports_per_cell
            or self._export_count + len(values) > self._limits.max_exports
        ):
            raise _ExportLimitError()
        artifacts = []
        payloads = []
        names = set()
        for value in values:
            if (
                type(value) is not dict
                or set(value) != {"name", "kind", "value"}
                or value["name"] in names
            ):
                raise PersistentIpythonHostError()
            payload = _export_payload(
                value["name"], value["kind"], value["value"], call_id
            )
            artifact = KernelExport(_export_id(payload), **payload)
            encoded = _encoded(payload)
            if len(_encoded(value["value"])) > self._limits.max_export_bytes:
                raise PersistentIpythonHostError()
            names.add(value["name"])
            artifacts.append(artifact)
            payloads.append(encoded)
        total = sum(map(len, payloads))
        if (
            sum(len(_encoded(artifact.value)) for artifact in artifacts)
            > self._limits.max_export_bytes
        ):
            raise _ExportLimitError()
        if self._export_bytes + total > self._limits.max_total_export_bytes:
            raise _ExportLimitError()
        if (
            len(self._metadata("ok", "", tuple(artifacts), False).encode())
            > self._limits.max_output_bytes
        ):
            raise _ExportLimitError()
        directory = self._bootstrap.workspace / "exports"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink():
            raise PersistentIpythonHostError()
        for artifact, encoded in zip(artifacts, payloads):
            target = directory / (artifact.export_id[7:] + ".json")
            descriptor, temporary = tempfile.mkstemp(prefix=".export-", dir=directory)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        self._export_count += len(artifacts)
        self._export_bytes += total
        return tuple(artifacts)

    def _result(
        self,
        call_id: str,
        status: str,
        output: str,
        exports: tuple[KernelExport, ...] = (),
        *,
        execution_status: str | None = None,
    ) -> PrimeToolResult:
        self._execution_status = (
            execution_status
            or {"ok": "ok", "error": "python-error", "uncertain": "lost"}[status]
        )
        metadata = self._metadata(self._execution_status, output, exports, False)
        if len(metadata.encode()) > self._limits.max_output_bytes:
            # Budget the escaped JSON representation, not only raw stdout.
            marker = "\n[stdout truncated]"
            low, high = 0, len(output)
            while low < high:
                middle = (low + high + 1) // 2
                candidate = self._metadata(
                    self._execution_status, output[:middle] + marker, exports, True
                )
                if len(candidate.encode()) <= self._limits.max_output_bytes:
                    low = middle
                else:
                    high = middle - 1
            metadata = self._metadata(
                self._execution_status, output[:low] + marker, exports, True
            )
            if len(metadata.encode()) > self._limits.max_output_bytes:
                metadata = self._metadata(self._execution_status, "", exports, True)
        return PrimeToolResult(call_id, status, ({"type": "text", "text": metadata},))

    def _metadata(
        self,
        execution_status: str,
        output: str,
        exports: tuple[KernelExport, ...],
        truncated: bool,
    ) -> str:
        return json.dumps(
            {
                "execution_status": execution_status,
                "generation": self.generation,
                "stdout": output,
                "stdout_truncated": truncated,
                "kernel_exports": [
                    {
                        "export_id": artifact.export_id,
                        "name": artifact.name,
                        "kind": artifact.kind,
                    }
                    for artifact in exports
                ],
            },
            separators=(",", ":"),
        )

    def _emit(
        self,
        kind: str,
        call_id: str,
        execution_status: str,
        started_at: float | None,
        exports: tuple[KernelExport, ...] = (),
    ) -> None:
        self._execution_status = execution_status
        if self._observer is not None:
            payload = _freeze_json(
                {
                    "call_id": call_id,
                    "generation": self.generation,
                    "execution_status": execution_status,
                    "elapsed_ms": None
                    if started_at is None
                    else max(0, int((monotonic() - started_at) * 1000)),
                    "export_ids": [artifact.export_id for artifact in exports],
                }
            )
            # Observers cannot change the kernel outcome or inject exports.
            try:
                self._observer(kind, payload)
            except Exception:
                pass


__all__ = (
    "KernelBootstrap",
    "KernelExport",
    "KernelLimits",
    "PersistentIpythonHost",
    "PersistentIpythonHostError",
    "PersistentIpythonWorker",
)
