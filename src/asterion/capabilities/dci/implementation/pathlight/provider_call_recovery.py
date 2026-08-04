"""Provider-free publication of an explicitly named DCI offline companion."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import NoReturn, cast

from asterion.capabilities.dci.implementation.evaluation.provider_requests import (
    read_sealed_provider_requests_at,
)
from asterion.runtime.host import RunRequest
from asterion.runtime.protocol import validate_event_stream, validate_run_request
from asterion.runtimes.pi_observation import PiObservationBuilder
from asterion.workflow_evidence import (
    build_workflow_observation_bundle,
    project_completed_runtime_evidence,
    read_workflow_observation_bundle_mapping,
)


_COMPANION_NAME = "workflow-evidence.provider-calls.offline.json"
_STAGING_NAME = ".workflow-evidence.provider-calls.offline.json.staging"
_FIXED_ERROR = "DCI provider call recovery is invalid"
_EVENTS_NAME = "events.jsonl"
_CAPTURE_NAME = "provider-requests.jsonl"
_WORKFLOW_NAME = "workflow-evidence.json"
_PROTOCOL_NAME = "protocol"
_REQUEST_NAME = "attempt-0001.request.json"
_PROTOCOL_EVENTS_NAME = "attempt-0001.events.jsonl"
_MAX_JSON_BYTES = 64 * 1024 * 1024
_MAX_JSONL_BYTES = 512 * 1024 * 1024
_MAX_LINE_BYTES = 64 * 1024 * 1024


class DciProviderCallRecoveryError(RuntimeError):
    """One fixed, content-free offline-recovery trust-boundary failure."""


def _invalid() -> NoReturn:
    raise DciProviderCallRecoveryError(_FIXED_ERROR) from None


def recover_provider_call_companion(
    generation_root: Path, companion_path: Path
) -> Mapping[str, object]:
    """Publish one validated offline companion beside an immutable generation."""

    root_fd = -1
    protocol_fd = -1
    output_fd = -1
    owned_identity: tuple[int, int] | None = None
    published = False
    try:
        _validate_paths(generation_root, companion_path)
        root_fd = _open_private_directory(generation_root)
        native_raw = _read_private_file_at(root_fd, _EVENTS_NAME, _MAX_JSONL_BYTES)
        workflow_raw = _read_private_file_at(root_fd, _WORKFLOW_NAME, _MAX_JSON_BYTES)
        protocol_fd = _open_private_directory_at(root_fd, _PROTOCOL_NAME)
        request_raw = _read_private_file_at(protocol_fd, _REQUEST_NAME, _MAX_JSON_BYTES)
        protocol_events_raw = _read_private_file_at(
            protocol_fd, _PROTOCOL_EVENTS_NAME, _MAX_JSONL_BYTES
        )

        workflow_document = _json_mapping(workflow_raw)
        read_workflow_observation_bundle_mapping(workflow_document)
        request_mapping = _json_mapping(request_raw)
        validate_run_request(request_mapping)
        request = _run_request(request_mapping)
        _validate_original_identity(workflow_document, request)
        protocol_events = _jsonl_mappings(protocol_events_raw)
        validate_event_stream(protocol_events)
        if any(event.get("run_id") != request.run_id for event in protocol_events):
            _invalid()

        builder, safe_entries = _observe_native_events(native_raw)
        observations = read_sealed_provider_requests_at(root_fd, safe_entries)
        builder.reconcile_provider_requests(observations)
        native_observation = builder.complete(request.run_id)
        if (
            native_observation.provider_requests != observations
            or len(native_observation.frames) != len(observations)
            or len(native_observation.model_calls) != len(observations)
        ):
            _invalid()

        projected = project_completed_runtime_evidence(
            request=request,
            event_observations=tuple(
                (event, sequence * 2, sequence * 2 + 1)
                for sequence, event in enumerate(protocol_events, 1)
            ),
            native_observation=native_observation,
            runtime_id="pi.dci-native",
            trace_id=_offline_trace_id(
                request_raw=request_raw,
                protocol_events_raw=protocol_events_raw,
                native_raw=native_raw,
                workflow_raw=workflow_raw,
                private_references=tuple(
                    observation.private_reference_sha256
                    for observation in observations
                ),
            ),
            invocation_started_ns=1,
            invocation_ended_ns=len(protocol_events) * 2 + 2,
        )
        bundle = build_workflow_observation_bundle(
            (projected.record,), pathlight_traces=(projected.trace,)
        )
        read_workflow_observation_bundle_mapping(bundle)
        encoded = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )

        output_fd = os.open(
            _STAGING_NAME,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | os.O_NONBLOCK
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=root_fd,
        )
        created = os.fstat(output_fd)
        if not stat.S_ISREG(created.st_mode) or created.st_uid != os.geteuid():
            _invalid()
        owned_identity = (created.st_dev, created.st_ino)
        os.fchmod(output_fd, 0o600)
        before = os.fstat(output_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size != 0
        ):
            _invalid()
        if (before.st_dev, before.st_ino) != owned_identity:
            _invalid()
        _write_all(output_fd, encoded)
        os.fsync(output_fd)
        after = os.fstat(output_fd)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_uid != os.geteuid()
            or stat.S_IMODE(after.st_mode) != 0o600
            or (after.st_dev, after.st_ino) != owned_identity
            or after.st_size != len(encoded)
        ):
            _invalid()
        os.link(
            _STAGING_NAME,
            _COMPANION_NAME,
            src_dir_fd=root_fd,
            dst_dir_fd=root_fd,
            follow_symlinks=False,
        )
        _verify_published_target(root_fd, owned_identity, len(encoded))
        os.unlink(_STAGING_NAME, dir_fd=root_fd)
        os.fsync(root_fd)
        published = True
        return cast(Mapping[str, object], _freeze(bundle))
    except DciProviderCallRecoveryError:
        raise
    except Exception:
        _invalid()
    finally:
        if not published and root_fd >= 0 and owned_identity is not None:
            _rollback_owned_name(root_fd, _COMPANION_NAME, owned_identity)
            _rollback_owned_name(root_fd, _STAGING_NAME, owned_identity)
        if output_fd >= 0:
            _close_quietly(output_fd)
        if protocol_fd >= 0:
            _close_quietly(protocol_fd)
        if root_fd >= 0:
            _close_quietly(root_fd)


def _validate_paths(generation_root: Path, companion_path: Path) -> None:
    if (
        not isinstance(generation_root, Path)
        or not isinstance(companion_path, Path)
        or not generation_root.is_absolute()
        or not companion_path.is_absolute()
        or ".." in generation_root.parts
        or ".." in companion_path.parts
        or companion_path.name != _COMPANION_NAME
        or companion_path.parent != generation_root
    ):
        _invalid()


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


def _open_private_directory(path: Path) -> int:
    descriptor = os.open(path, _directory_flags())
    try:
        _validate_private_directory(descriptor)
        return descriptor
    except Exception:
        _close_quietly(descriptor)
        raise


def _open_private_directory_at(directory_fd: int, name: str) -> int:
    descriptor = os.open(name, _directory_flags(), dir_fd=directory_fd)
    try:
        _validate_private_directory(descriptor)
        return descriptor
    except Exception:
        _close_quietly(descriptor)
        raise


def _validate_private_directory(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        _invalid()


def _read_private_file_at(directory_fd: int, name: str, limit: int) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | os.O_NOFOLLOW
            | os.O_NONBLOCK
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size < 0
            or before.st_size > limit
        ):
            _invalid()
        chunks: list[bytes] = []
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(descriptor, min(1024 * 1024, before.st_size - offset), offset)
            if not chunk:
                _invalid()
            chunks.append(chunk)
            offset += len(chunk)
        if os.pread(descriptor, 1, before.st_size):
            _invalid()
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_uid != os.geteuid()
            or stat.S_IMODE(after.st_mode) != 0o600
            or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        ):
            _invalid()
        return b"".join(chunks)
    finally:
        if descriptor >= 0:
            _close_quietly(descriptor)


def _loads_exact(raw: bytes) -> object:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                _invalid()
            result[key] = value
        return result

    def invalid_constant(_value: str) -> NoReturn:
        _invalid()

    return json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=object_pairs,
        parse_constant=invalid_constant,
    )


def _json_mapping(raw: bytes) -> dict[str, object]:
    value = _loads_exact(raw)
    if type(value) is not dict:
        _invalid()
    return cast(dict[str, object], value)


def _jsonl_mappings(raw: bytes) -> tuple[dict[str, object], ...]:
    if not raw or not raw.endswith(b"\n"):
        _invalid()
    lines = raw[:-1].split(b"\n")
    if any(not line or len(line) + 1 > _MAX_LINE_BYTES for line in lines):
        _invalid()
    values: list[dict[str, object]] = []
    for line in lines:
        value = _loads_exact(line)
        if type(value) is not dict:
            _invalid()
        values.append(cast(dict[str, object], value))
    return tuple(values)


def _observe_native_events(
    raw: bytes,
) -> tuple[PiObservationBuilder, tuple[dict[str, object], ...]]:
    events = _jsonl_mappings(raw)
    builder = PiObservationBuilder(lambda: 0)
    safe_entries: list[dict[str, object]] = []
    for sequence, event in enumerate(events, 1):
        builder.consume(event, sequence, native_event_sequence=sequence)
        marker = _provider_marker(event)
        if marker is not None:
            index, safe = marker
            builder.observe_provider_request_marker(index, sequence)
            safe_entries.append(safe)
    if not safe_entries:
        _invalid()
    return builder, tuple(safe_entries)


def _provider_marker(
    event: Mapping[str, object],
) -> tuple[int, dict[str, object]] | None:
    if event.get("type") != "entry_appended":
        return None
    entry = event.get("entry")
    if not isinstance(entry, Mapping):
        return None
    if entry.get("type") != "custom":
        return None
    if entry.get("customType") != "dci-provider-request-observation":
        return None
    safe = entry.get("data")
    if not isinstance(safe, dict):
        _invalid()
    index = safe.get("request_index")
    if (
        safe.get("schema") != "dci.provider-request-observation/v1"
        or safe.get("capture_status") != "captured"
        or type(index) is not int
        or index < 1
    ):
        _invalid()
    return index, dict(safe)


def _run_request(mapping: Mapping[str, object]) -> RunRequest:
    input_value = mapping["input"]
    assert isinstance(input_value, Mapping)
    capabilities = mapping.get("requested_capabilities", [])
    assert isinstance(capabilities, list)
    deadline = mapping.get("deadline_ms")
    return RunRequest(
        protocol=cast(str, mapping["protocol"]),
        run_id=cast(str, mapping["run_id"]),
        input_text=cast(str, input_value["text"]),
        requested_capabilities=tuple(cast(list[str], capabilities)),
        deadline_ms=cast(int | None, deadline),
    )


def _validate_original_identity(
    workflow_document: Mapping[str, object], request: RunRequest
) -> None:
    records = workflow_document.get("records")
    if not isinstance(records, list) or len(records) != 1:
        _invalid()
    record = records[0]
    if (
        not isinstance(record, Mapping)
        or record.get("run_id") != request.run_id
        or record.get("input_digest")
        != hashlib.sha256(request.input_text.encode("utf-8")).hexdigest()
    ):
        _invalid()


def _offline_trace_id(
    *,
    request_raw: bytes,
    protocol_events_raw: bytes,
    native_raw: bytes,
    workflow_raw: bytes,
    private_references: tuple[str, ...],
) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "domain": "asterion.dci.provider-call-offline-trace/v1",
                "request_sha256": hashlib.sha256(request_raw).hexdigest(),
                "protocol_events_sha256": hashlib.sha256(
                    protocol_events_raw
                ).hexdigest(),
                "native_events_sha256": hashlib.sha256(native_raw).hexdigest(),
                "workflow_evidence_sha256": hashlib.sha256(workflow_raw).hexdigest(),
                "private_references": private_references,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return (
        f"{digest[:8]}-{digest[8:12]}-4{digest[13:16]}-"
        f"8{digest[17:20]}-{digest[20:32]}"
    )


def _write_all(descriptor: int, value: bytes) -> None:
    offset = 0
    while offset < len(value):
        written = os.write(descriptor, value[offset:])
        if written <= 0:
            _invalid()
        offset += written


def _verify_published_target(
    directory_fd: int, identity: tuple[int, int], size: int
) -> None:
    metadata = os.stat(_COMPANION_NAME, dir_fd=directory_fd, follow_symlinks=False)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or (metadata.st_dev, metadata.st_ino) != identity
        or metadata.st_size != size
    ):
        _invalid()


def _rollback_owned_name(
    directory_fd: int, name: str, identity: tuple[int, int]
) -> None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (metadata.st_dev, metadata.st_ino) == identity:
            os.unlink(name, dir_fd=directory_fd)
    except OSError:
        pass


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _close_quietly(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass
