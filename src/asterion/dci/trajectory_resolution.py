"""Descriptor-safe paper trajectory coverage and localization evidence."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shlex
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from asterion.adapters.pi import map_pi_capabilities
from asterion.dci.artifacts import (
    DciArtifactError,
    validate_latest_context_evidence,
)
from asterion.dci.resolution_metrics import (
    best_document_localization,
    compute_query_coverage,
    compute_retained_coverage,
    gold_document_set,
    query_localization,
    surfaced_gold_set,
)
from asterion.runtime.protocol import (
    MAX_DEADLINE_MS,
    PROTOCOL_VERSION,
    ProtocolError,
    validate_event_stream,
    validate_run_request,
)


class TrajectoryResolutionError(ValueError):
    """Native trajectory evidence is unsafe, ambiguous, or incomplete."""


@dataclass(frozen=True, slots=True)
class TrajectoryAnalysisConfig:
    """Closed identity-bearing alignment configuration."""

    segment_characters: int
    read_minimum_evidence_overlap: float = 0.5
    alignment_version: str = "dci.paper-alignment/v1"

    def __post_init__(self) -> None:
        if (
            type(self.segment_characters) is not int
            or self.segment_characters <= 0
            or type(self.read_minimum_evidence_overlap) is not float
            or not math.isfinite(self.read_minimum_evidence_overlap)
            or not 0.0 < self.read_minimum_evidence_overlap <= 1.0
            or self.alignment_version != "dci.paper-alignment/v1"
        ):
            raise TrajectoryResolutionError(
                "DCI trajectory analysis configuration is invalid"
            )

    def to_mapping(self) -> dict[str, object]:
        return {
            "alignment_version": self.alignment_version,
            "read_minimum_evidence_overlap": self.read_minimum_evidence_overlap,
            "segment_characters": self.segment_characters,
        }


@dataclass(frozen=True, slots=True)
class _Snapshot:
    label: str
    root: Path
    relative: str
    sha256: str
    size: int
    device: int
    inode: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _ImmutableSnapshot:
    label: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class _GoldDocument:
    document_id: str
    relative_path: str
    body: str
    digest: str
    evidence_spans: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class _ToolObservation:
    call_id: str
    name: str
    arguments: dict[str, object]
    output: str
    external_digest: str


_GREP_LINE = re.compile(r"^(?P<path>[^:\r\n]+):(?P<line>[1-9][0-9]*):(?P<text>.*)$")
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_TOOLS = frozenset({"read", "grep", "rg", "bash"})


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_relative_path(value: object) -> str:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise TrajectoryResolutionError("DCI trajectory path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise TrajectoryResolutionError("DCI trajectory path is invalid")
    if any(unicodedata.normalize("NFC", part) != part for part in path.parts):
        raise TrajectoryResolutionError("DCI trajectory path is not canonical")
    return value


def _portable_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _open_directory_path(path: Path) -> int:
    requested = path.absolute()
    absolute = requested
    # macOS exposes /var and /tmp as fixed system aliases under /private. Resolve
    # only that constant first component; every caller-controlled component stays
    # subject to descriptor-relative O_NOFOLLOW traversal below.
    if len(requested.parts) > 1 and requested.parts[1] in {"var", "tmp"}:
        system_alias = Path(os.path.realpath(os.sep + requested.parts[1]))
        if system_alias in {Path("/private/var"), Path("/private/tmp")}:
            absolute = system_alias.joinpath(*requested.parts[2:])
    parts = absolute.parts
    if not parts or parts[0] != os.sep:
        raise TrajectoryResolutionError("DCI trajectory directory is invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.sep, flags)
    try:
        for part in parts[1:]:
            next_descriptor = os.open(part, flags | nofollow, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except (OSError, TypeError) as error:
        os.close(descriptor)
        raise TrajectoryResolutionError(
            "DCI trajectory directory is unsafe or unavailable"
        ) from error


def _read_regular_at(root: Path, relative: str, *, label: str) -> tuple[bytes, _Snapshot]:
    relative = _safe_relative_path(relative)
    root_fd = _open_directory_path(root)
    directory_fd = root_fd
    owned: list[int] = []
    try:
        parts = PurePosixPath(relative).parts
        directory_flags = (
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        for part in parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            owned.append(next_fd)
            directory_fd = next_fd
        file_fd = os.open(
            parts[-1],
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        try:
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode):
                raise TrajectoryResolutionError("DCI trajectory input is not regular")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(file_fd)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise TrajectoryResolutionError("DCI trajectory input changed while read")
            data = b"".join(chunks)
            if len(data) != before.st_size:
                raise TrajectoryResolutionError("DCI trajectory input is truncated")
            snapshot = _Snapshot(
                label=label,
                root=root.absolute(),
                relative=relative,
                sha256=_sha256(data),
                size=len(data),
                device=before.st_dev,
                inode=before.st_ino,
                modified_ns=before.st_mtime_ns,
            )
            return data, snapshot
        finally:
            os.close(file_fd)
    except (OSError, UnicodeError) as error:
        raise TrajectoryResolutionError(
            "DCI trajectory input is unsafe or unavailable"
        ) from error
    finally:
        for descriptor in reversed(owned):
            os.close(descriptor)
        os.close(root_fd)


def _read_path(path: Path, *, label: str) -> tuple[bytes, _Snapshot]:
    absolute = path.absolute()
    if absolute.name in {"", ".", ".."}:
        raise TrajectoryResolutionError("DCI trajectory input path is invalid")
    return _read_regular_at(absolute.parent, absolute.name, label=label)


def _json_object(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TrajectoryResolutionError(f"DCI {label} JSON is invalid") from error
    if type(value) is not dict:
        raise TrajectoryResolutionError(f"DCI {label} JSON is invalid")
    return value


def _jsonl(data: bytes) -> tuple[dict[str, Any], ...]:
    try:
        text = data.decode("utf-8")
        if not text or not text.endswith("\n"):
            raise ValueError
        values = tuple(json.loads(line) for line in text.splitlines())
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise TrajectoryResolutionError("DCI protocol event stream is invalid") from error
    if not values or any(type(value) is not dict for value in values):
        raise TrajectoryResolutionError("DCI protocol event stream is invalid")
    return values


def _validate_completed_attempt(
    state: dict[str, Any], events: tuple[dict[str, Any], ...], attempt: int
) -> str:
    if type(attempt) is not int or attempt <= 0:
        raise TrajectoryResolutionError("DCI trajectory attempt is invalid")
    attempts = state.get("attempts")
    if (
        state.get("status") != "completed"
        or type(attempts) is not list
        or len([item for item in attempts if type(item) is dict and item.get("attempt") == attempt])
        != 1
        or next(item for item in attempts if type(item) is dict and item.get("attempt") == attempt).get("status")
        != "completed"
    ):
        raise TrajectoryResolutionError("DCI trajectory attempt is not completed")
    run_id = state.get("run_id")
    if type(run_id) is not str or not run_id:
        raise TrajectoryResolutionError("DCI trajectory run identity is invalid")
    protocol_run_id = f"{run_id}-attempt-{attempt:04d}"
    try:
        validate_event_stream(events)
    except ProtocolError as error:
        raise TrajectoryResolutionError("DCI protocol event stream is invalid") from error
    for sequence, event in enumerate(events, 1):
        if (
            set(event) != {"protocol", "run_id", "sequence", "type", "payload"}
            or event.get("protocol") != PROTOCOL_VERSION
            or event.get("run_id") != protocol_run_id
            or event.get("sequence") != sequence
            or type(event.get("payload")) is not dict
        ):
            raise TrajectoryResolutionError("DCI protocol event stream is invalid")
    if events[0]["type"] != "run.started" or events[-1]["type"] != "run.completed":
        raise TrajectoryResolutionError("DCI protocol attempt is incomplete")
    if any(event["type"] in {"run.completed", "run.failed"} for event in events[:-1]):
        raise TrajectoryResolutionError("DCI protocol event stream is invalid")
    return run_id


def _validate_native_identity(
    state: dict[str, Any],
    latest: dict[str, Any],
    protocol_request: dict[str, Any],
    *,
    attempt: int,
) -> None:
    latest_keys = {
        "status",
        "question",
        "cwd",
        "provider",
        "model",
        "conversation_features",
        "request_count",
        "runtime_context_management",
        "latest",
        "notes",
        "pi_source_attempts",
    }
    shared = (
        "status",
        "question",
        "cwd",
        "provider",
        "model",
        "conversation_features",
        "notes",
        "pi_source_attempts",
    )
    attempts = state.get("attempts")
    tools = state.get("tools")
    question = state.get("question")
    latest_capture = latest.get("latest")
    if (
        set(latest) != latest_keys
        or any(latest.get(name) != state.get(name) for name in shared)
        or type(question) is not str
        or not question
        or type(state.get("cwd")) is not str
        or not state["cwd"]
        or type(tools) is not str
        or type(state.get("conversation_features")) is not dict
        or type(state.get("notes")) is not list
        or type(state.get("pi_source_attempts")) is not list
        or type(latest.get("request_count")) is not int
        or latest["request_count"] < 0
        or (latest_capture is not None and type(latest_capture) is not dict)
        or type(attempts) is not list
        or not attempts
        or attempt != len(attempts)
        or state.get("resume_count") != len(attempts) - 1
    ):
        raise TrajectoryResolutionError("DCI native artifact identity is invalid")
    if latest_capture is not None:
        if (
            set(latest_capture)
            != {
                "captured_at",
                "request_index",
                "model",
                "runtime_context_management",
                "message_count",
                "messages",
                "payload",
            }
            or type(latest_capture.get("messages")) is not list
            or type(latest_capture.get("message_count")) is not int
            or latest_capture["message_count"] != len(latest_capture["messages"])
            or latest_capture.get("runtime_context_management")
            != latest.get("runtime_context_management")
        ):
            raise TrajectoryResolutionError("DCI final model context is invalid")
    selected = attempts[attempt - 1]
    if (
        type(selected) is not dict
        or set(selected)
        != {
            "attempt",
            "status",
            "command_summary",
            "timeout_seconds",
            "stderr_tail_characters",
        }
        or selected.get("attempt") != attempt
        or selected.get("status") != "completed"
    ):
        raise TrajectoryResolutionError("DCI native attempt identity is invalid")
    summary = selected.get("command_summary")
    timeout = selected.get("timeout_seconds")
    stderr_characters = selected.get("stderr_tail_characters")
    if (
        type(summary) is not dict
        or set(summary)
        != {
            "executable",
            "mode",
            "option_names",
            "configured_extra_argument_groups",
            "typed_extra_argument_count",
        }
        or summary.get("executable") != "node"
        or summary.get("mode") != "rpc"
        or type(summary.get("option_names")) is not list
        or any(type(value) is not str or not value for value in summary["option_names"])
        or type(summary.get("configured_extra_argument_groups")) is not int
        or summary["configured_extra_argument_groups"] < 0
        or type(summary.get("typed_extra_argument_count")) is not int
        or summary["typed_extra_argument_count"] < 0
        or not (
            timeout is None
            or (type(timeout) is float and math.isfinite(timeout) and timeout >= 0)
        )
        or type(stderr_characters) is not int
        or stderr_characters < 0
    ):
        raise TrajectoryResolutionError("DCI native attempt identity is invalid")
    try:
        validate_run_request(protocol_request)
    except ProtocolError as error:
        raise TrajectoryResolutionError("DCI native attempt request is invalid") from error
    expected_request: dict[str, object] = {
        "protocol": PROTOCOL_VERSION,
        "run_id": f"{state['run_id']}-attempt-{attempt:04d}",
        "input": {"text": question},
        "requested_capabilities": map_pi_capabilities(tools),
    }
    if timeout is not None and timeout > 0:
        deadline_ms = int(round(timeout * 1000))
        if deadline_ms <= MAX_DEADLINE_MS:
            expected_request["deadline_ms"] = max(1, deadline_ms)
    if protocol_request != expected_request:
        raise TrajectoryResolutionError("DCI native attempt request is invalid")


def _parse_gold_manifest(
    data: bytes, corpus_dir: Path
) -> tuple[str, str, tuple[_GoldDocument, ...], tuple[_Snapshot, ...]]:
    manifest = _json_object(data, label="gold manifest")
    if set(manifest) != {"schema", "dataset_id", "query_id", "documents"} or manifest.get(
        "schema"
    ) != "dci.gold-document-manifest/v1":
        raise TrajectoryResolutionError("DCI gold manifest is invalid")
    dataset_id = manifest.get("dataset_id")
    query_id = manifest.get("query_id")
    entries = manifest.get("documents")
    if (
        type(dataset_id) is not str
        or not dataset_id
        or type(query_id) is not str
        or not query_id
        or type(entries) is not list
        or not entries
    ):
        raise TrajectoryResolutionError("DCI gold manifest is invalid")
    documents: list[_GoldDocument] = []
    snapshots: list[_Snapshot] = []
    aliases: set[str] = set()
    for entry in entries:
        if type(entry) is not dict or set(entry) != {
            "id",
            "path",
            "sha256",
            "evidence_spans",
        }:
            raise TrajectoryResolutionError("DCI gold manifest is invalid")
        document_id = _safe_relative_path(entry.get("id"))
        relative_path = _safe_relative_path(entry.get("path"))
        alias = _portable_key(document_id)
        path_alias = _portable_key(relative_path)
        if alias in aliases or path_alias in aliases:
            raise TrajectoryResolutionError("DCI gold manifest has duplicate aliases")
        aliases.update({alias, path_alias})
        body_bytes, snapshot = _read_regular_at(
            corpus_dir, relative_path, label=f"corpus:{document_id}"
        )
        if entry.get("sha256") != snapshot.sha256:
            raise TrajectoryResolutionError("DCI gold document digest is stale")
        try:
            body = body_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise TrajectoryResolutionError("DCI gold document is not UTF-8") from error
        spans_value = entry.get("evidence_spans")
        if type(spans_value) is not list or not spans_value:
            raise TrajectoryResolutionError("DCI gold evidence spans are invalid")
        spans: list[tuple[int, int]] = []
        for span in spans_value:
            if (
                type(span) is not dict
                or set(span) != {"start", "end"}
                or type(span.get("start")) is not int
                or type(span.get("end")) is not int
                or span["start"] < 0
                or span["start"] >= span["end"]
                or span["end"] > len(body)
            ):
                raise TrajectoryResolutionError("DCI gold evidence spans are invalid")
            spans.append((span["start"], span["end"]))
        if spans != sorted(set(spans)):
            raise TrajectoryResolutionError("DCI gold evidence spans are invalid")
        documents.append(
            _GoldDocument(
                document_id=document_id,
                relative_path=relative_path,
                body=body,
                digest=snapshot.sha256,
                evidence_spans=tuple(spans),
            )
        )
        snapshots.append(snapshot)
    return dataset_id, query_id, tuple(documents), tuple(snapshots)


def validate_gold_manifest_bytes(
    data: bytes, *, corpus_dir: Path
) -> tuple[str, str, tuple[str, ...]]:
    """Preflight one manifest and every referenced corpus file without a run."""

    if type(data) is not bytes:
        raise TrajectoryResolutionError("DCI gold manifest bytes are invalid")
    dataset_id, query_id, documents, snapshots = _parse_gold_manifest(
        data, Path(corpus_dir)
    )
    _revalidate(snapshots)
    return dataset_id, query_id, tuple(document.document_id for document in documents)


def _externalized_observations(
    run_dir: Path,
    events: tuple[dict[str, Any], ...],
) -> tuple[tuple[_ToolObservation, ...], tuple[_Snapshot, ...]]:
    calls: dict[str, tuple[str, dict[str, object]]] = {}
    results: dict[str, str] = {}
    order: list[str] = []
    for event in events:
        payload = event["payload"]
        if event["type"] == "tool.call":
            call_id = payload.get("call_id")
            name = payload.get("name")
            arguments = payload.get("arguments")
            if (
                type(call_id) is not str
                or not call_id
                or call_id in calls
                or type(name) is not str
                or name not in _SAFE_TOOLS
                or type(arguments) is not dict
            ):
                raise TrajectoryResolutionError("DCI tool call evidence is invalid")
            calls[call_id] = (name, arguments)
            order.append(call_id)
        elif event["type"] == "tool.result":
            call_id = payload.get("call_id")
            output = payload.get("output")
            if (
                type(call_id) is not str
                or call_id not in calls
                or call_id in results
                or payload.get("is_error") is not False
                or type(output) is not str
            ):
                raise TrajectoryResolutionError("DCI tool result evidence is invalid")
            results[call_id] = output
        elif event["type"] not in {
            "run.started",
            "run.completed",
            "text.delta",
            "usage.reported",
            "artifact.created",
        }:
            raise TrajectoryResolutionError("DCI protocol event type is unsupported")
    if set(calls) != set(results):
        raise TrajectoryResolutionError("DCI tool evidence is incomplete")
    if not calls:
        return (), ()

    try:
        tool_fd = _open_directory_path(run_dir / "tool_results")
        names = os.listdir(tool_fd)
        os.close(tool_fd)
    except (OSError, TrajectoryResolutionError) as error:
        raise TrajectoryResolutionError("DCI externalized tool evidence is unavailable") from error
    documents: dict[str, tuple[dict[str, Any], _Snapshot]] = {}
    for name in sorted(names):
        relative = _safe_relative_path(name)
        data, snapshot = _read_regular_at(
            run_dir / "tool_results", relative, label=f"tool-result:{relative}"
        )
        document = _json_object(data, label="externalized tool result")
        message = document.get("message")
        call_id = message.get("toolCallId") if type(message) is dict else None
        if type(call_id) is not str or not call_id or call_id in documents:
            raise TrajectoryResolutionError("DCI externalized tool result is invalid")
        documents[call_id] = (document, snapshot)
    if set(documents) != set(calls):
        raise TrajectoryResolutionError("DCI externalized tool result set is incomplete")

    observations: list[_ToolObservation] = []
    snapshots: list[_Snapshot] = []
    for call_id in order:
        name, arguments = calls[call_id]
        document, snapshot = documents[call_id]
        message = document.get("message")
        content = message.get("content") if type(message) is dict else None
        texts = (
            [part.get("text") for part in content if type(part) is dict and part.get("type") == "text"]
            if type(content) is list
            else []
        )
        if (
            set(document) != {"saved_at", "message"}
            or type(message) is not dict
            or message.get("role") != "toolResult"
            or message.get("toolCallId") != call_id
            or message.get("toolName") != name
            or len(texts) != 1
            or type(texts[0]) is not str
            or texts[0] != results[call_id]
        ):
            raise TrajectoryResolutionError(
                "DCI externalized tool result does not bind protocol output"
            )
        observations.append(
            _ToolObservation(call_id, name, arguments, texts[0], snapshot.sha256)
        )
        snapshots.append(snapshot)
    return tuple(observations), tuple(snapshots)


def _argument_path(value: object, documents: tuple[_GoldDocument, ...]) -> _GoldDocument | None:
    if type(value) is not str or not value:
        return None
    candidate = value[2:] if value.startswith("./") else value
    matches = [
        document
        for document in documents
        if candidate in {document.document_id, document.relative_path}
    ]
    if len(matches) > 1:
        raise TrajectoryResolutionError("DCI observation path is ambiguous")
    return matches[0] if matches else None


def _overlaps_gold(
    start: int,
    end: int,
    spans: tuple[tuple[int, int], ...],
    minimum: float,
) -> bool:
    width = end - start
    return any(max(0, min(end, right) - max(start, left)) / width >= minimum for left, right in spans)


def _line_span(body: str, line_number: int) -> tuple[int, int, str] | None:
    lines = body.splitlines(keepends=True)
    if line_number > len(lines):
        return None
    start = sum(len(line) for line in lines[: line_number - 1])
    text = lines[line_number - 1].rstrip("\r\n")
    return start, start + len(text), text


def _fallback_alignment(observation: _ToolObservation, document: _GoldDocument) -> dict[str, object]:
    return {
        "call_id": observation.call_id,
        "tool": observation.name,
        "document_id": document.document_id,
        "rule": "full-document-fallback",
        "snippet_characters": len(document.body),
        "observation": observation.output,
    }


def _read_alignments(
    observation: _ToolObservation,
    documents: tuple[_GoldDocument, ...],
    config: TrajectoryAnalysisConfig,
) -> list[dict[str, object]]:
    document = _argument_path(observation.arguments.get("path"), documents)
    if document is None:
        return []
    starts = [match.start() for match in re.finditer(re.escape(observation.output), document.body)] if observation.output else []
    if len(starts) == 1:
        start = starts[0]
        end = start + len(observation.output)
        if _overlaps_gold(start, end, document.evidence_spans, config.read_minimum_evidence_overlap):
            return [
                {
                    "call_id": observation.call_id,
                    "tool": observation.name,
                    "document_id": document.document_id,
                    "rule": "read-returned-span",
                    "snippet_characters": len(observation.output),
                    "start": start,
                    "end": end,
                    "observation": observation.output,
                }
            ]
    return [_fallback_alignment(observation, document)]


def _grep_alignments(
    observation: _ToolObservation,
    documents: tuple[_GoldDocument, ...],
) -> list[dict[str, object]]:
    alignments: list[dict[str, object]] = []
    for output_line in observation.output.splitlines():
        match = _GREP_LINE.fullmatch(output_line)
        if match is None:
            continue
        document = _argument_path(match.group("path"), documents)
        if document is None:
            continue
        span = _line_span(document.body, int(match.group("line")))
        if span is None or span[2] != match.group("text"):
            continue
        start, end, text = span
        alignments.append(
            {
                "call_id": observation.call_id,
                "tool": observation.name,
                "document_id": document.document_id,
                "rule": "grep-matched-line",
                "snippet_characters": max(1, len(text)),
                "start": start,
                "end": end,
                "observation": output_line,
            }
        )
    if alignments:
        return alignments
    document = _argument_path(observation.arguments.get("path"), documents)
    return [_fallback_alignment(observation, document)] if document else []


def _bash_alignments(
    observation: _ToolObservation,
    documents: tuple[_GoldDocument, ...],
) -> list[dict[str, object]]:
    command = observation.arguments.get("command")
    if type(command) is not str or not command:
        raise TrajectoryResolutionError("DCI bash observation is invalid")
    try:
        tokens = shlex.split(command)
    except ValueError as error:
        raise TrajectoryResolutionError("DCI bash observation is malformed") from error
    referenced = []
    for token in tokens:
        document = _argument_path(token, documents)
        if document is not None and document not in referenced:
            referenced.append(document)
    if any(token in {"|", "||", "&&", ";", ">", ">>", "<"} for token in tokens):
        return [_fallback_alignment(observation, document) for document in referenced]
    if tokens and PurePosixPath(tokens[0]).name in {"grep", "rg"}:
        return _grep_alignments(observation, documents) or [
            _fallback_alignment(observation, document) for document in referenced
        ]
    return [_fallback_alignment(observation, document) for document in referenced]


def _align(
    observations: tuple[_ToolObservation, ...],
    documents: tuple[_GoldDocument, ...],
    config: TrajectoryAnalysisConfig,
) -> tuple[dict[str, object], ...]:
    alignments: list[dict[str, object]] = []
    for observation in observations:
        if observation.name == "read":
            current = _read_alignments(observation, documents, config)
        elif observation.name in {"grep", "rg"}:
            current = _grep_alignments(observation, documents)
        elif observation.name == "bash":
            current = _bash_alignments(observation, documents)
        else:  # pragma: no cover - closed at protocol validation
            raise TrajectoryResolutionError("DCI observation tool is unsupported")
        alignments.extend(current)
    return tuple(alignments)


def _context_text_blocks(latest: dict[str, Any]) -> tuple[str, ...] | None:
    capture = latest.get("latest")
    if capture is None:
        return None
    if type(capture) is not dict or type(capture.get("messages")) is not list:
        raise TrajectoryResolutionError("DCI final model context is invalid")
    texts: list[str] = []
    for message in capture["messages"]:
        if type(message) is not dict:
            raise TrajectoryResolutionError("DCI final model context is invalid")
        content = message.get("content")
        if content is None:
            continue
        if type(content) is str:
            texts.append(content)
            continue
        if type(content) is not list:
            raise TrajectoryResolutionError("DCI final model context is invalid")
        for part in content:
            if type(part) is not dict:
                raise TrajectoryResolutionError("DCI final model context is invalid")
            text = part.get("text")
            if part.get("type") == "text" and type(text) is str:
                texts.append(text)
    return tuple(texts)


def _contains_exact_path(text: str, path: str) -> bool:
    boundary = r"A-Za-z0-9._/\-"
    return (
        re.search(
            rf"(?<![{boundary}]){re.escape(path)}(?![{boundary}])",
            text,
        )
        is not None
    )


def _retained_alignments(
    latest: dict[str, Any], documents: tuple[_GoldDocument, ...]
) -> tuple[dict[str, object], ...] | None:
    texts = _context_text_blocks(latest)
    if texts is None:
        return None
    evidence_owners: dict[str, set[str]] = {}
    for document in documents:
        for start, end in document.evidence_spans:
            evidence_owners.setdefault(document.body[start:end], set()).add(
                document.document_id
            )
    alignments: list[dict[str, object]] = []
    for document in documents:
        matched_path = next(
            (
                text
                for text in texts
                if any(
                    _contains_exact_path(text, path)
                    for path in {document.document_id, document.relative_path}
                )
            ),
            None,
        )
        if matched_path is not None:
            alignments.append(
                {
                    "document_id": document.document_id,
                    "rule": "final-context-path",
                    "snippet_characters": len(document.body),
                    "observation": matched_path,
                }
            )
            continue
        candidates = [
            document.body[start:end]
            for start, end in document.evidence_spans
            if evidence_owners.get(document.body[start:end]) == {document.document_id}
        ]
        match = next(
            (
                candidate
                for candidate in candidates
                if any(candidate in text for text in texts)
            ),
            None,
        )
        if match is not None:
            alignments.append(
                {
                    "document_id": document.document_id,
                    "rule": "final-context-evidence",
                    "snippet_characters": len(match),
                    "observation": match,
                }
            )
    return tuple(alignments)


def _snapshot_identity(
    snapshot: _Snapshot | _ImmutableSnapshot,
) -> dict[str, object]:
    return {"label": snapshot.label, "sha256": snapshot.sha256, "size": snapshot.size}


def _revalidate(snapshots: tuple[_Snapshot, ...]) -> None:
    for expected in snapshots:
        _data, actual = _read_regular_at(
            expected.root, expected.relative, label=expected.label
        )
        if (
            actual.sha256,
            actual.size,
            actual.device,
            actual.inode,
            actual.modified_ns,
        ) != (
            expected.sha256,
            expected.size,
            expected.device,
            expected.inode,
            expected.modified_ns,
        ):
            raise TrajectoryResolutionError("DCI trajectory evidence changed before publish")


def _atomic_private_json(path: Path, value: object) -> None:
    parent_fd = _open_directory_path(path.absolute().parent)
    name = path.name
    if name in {"", ".", ".."} or "/" in name:
        os.close(parent_fd)
        raise TrajectoryResolutionError("DCI trajectory output path is invalid")
    temporary = f".{name}.tmp-{os.getpid()}"
    descriptor: int | None = None
    try:
        try:
            existing = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and not stat.S_ISREG(existing.st_mode):
            raise TrajectoryResolutionError("DCI trajectory output is unsafe")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_fd,
        )
        payload = _canonical_json_bytes(value)
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.rename(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError as error:
        raise TrajectoryResolutionError("DCI trajectory output could not be published") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        os.close(parent_fd)


def analyze_trajectory_resolution(
    *,
    run_dir: Path,
    attempt: int,
    corpus_dir: Path,
    config: TrajectoryAnalysisConfig,
    gold_manifest_path: Path | None = None,
    gold_manifest_bytes: bytes | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Derive private, digest-bound paper resolution evidence from one attempt."""

    if type(config) is not TrajectoryAnalysisConfig:
        raise TrajectoryResolutionError("DCI trajectory analysis configuration is invalid")
    run_dir = Path(run_dir)
    corpus_dir = Path(corpus_dir)
    if (gold_manifest_path is None) == (gold_manifest_bytes is None):
        raise TrajectoryResolutionError("DCI gold manifest authority is invalid")
    gold_manifest_path = (
        None if gold_manifest_path is None else Path(gold_manifest_path)
    )
    state_data, state_snapshot = _read_regular_at(run_dir, "state.json", label="state")
    protocol_relative = f"protocol/attempt-{attempt:04d}.events.jsonl"
    request_relative = f"protocol/attempt-{attempt:04d}.request.json"
    request_data, request_snapshot = _read_regular_at(
        run_dir, request_relative, label="protocol-request"
    )
    protocol_data, protocol_snapshot = _read_regular_at(
        run_dir, protocol_relative, label="protocol"
    )
    raw_events_data, raw_events_snapshot = _read_regular_at(
        run_dir, "events.jsonl", label="recorder-events"
    )
    latest_data, latest_snapshot = _read_regular_at(
        run_dir, "latest_model_context.json", label="final-context"
    )
    if gold_manifest_bytes is not None:
        if type(gold_manifest_bytes) is not bytes:
            raise TrajectoryResolutionError("DCI gold manifest authority is invalid")
        manifest_data = gold_manifest_bytes
        manifest_snapshot: _Snapshot | _ImmutableSnapshot = _ImmutableSnapshot(
            label="gold-manifest",
            sha256=_sha256(manifest_data),
            size=len(manifest_data),
        )
    else:
        assert gold_manifest_path is not None
        manifest_data, manifest_snapshot = _read_path(
            gold_manifest_path, label="gold-manifest"
        )
    state = _json_object(state_data, label="state")
    latest = _json_object(latest_data, label="final context")
    protocol_request = _json_object(request_data, label="protocol request")
    events = _jsonl(protocol_data)
    raw_events = _jsonl(raw_events_data)
    run_id = _validate_completed_attempt(state, events, attempt)
    _validate_native_identity(state, latest, protocol_request, attempt=attempt)
    tool_calls = state.get("tool_calls")
    if type(tool_calls) is not list:
        raise TrajectoryResolutionError("DCI native tool-call evidence is invalid")
    try:
        validate_latest_context_evidence(list(raw_events), latest, tool_calls)
    except DciArtifactError as error:
        raise TrajectoryResolutionError("DCI final model context is invalid") from error
    dataset_id, query_id, documents, corpus_snapshots = _parse_gold_manifest(
        manifest_data, corpus_dir
    )
    observations, tool_snapshots = _externalized_observations(run_dir, events)
    alignments = _align(observations, documents, config)
    retained_alignments = _retained_alignments(latest, documents)
    surfaced_ids = sorted({str(item["document_id"]) for item in alignments})
    gold = gold_document_set(tuple(document.document_id for document in documents))
    surfaced = surfaced_gold_set(gold, surfaced_ids)
    coverage = compute_query_coverage(gold, surfaced)
    localizations = []
    for document in documents:
        candidates = [
            int(item["snippet_characters"])
            for item in alignments
            if item["document_id"] == document.document_id
        ]
        if candidates:
            localizations.append(
                best_document_localization(
                    document.document_id,
                    len(document.body),
                    candidates,
                    config.segment_characters,
                )
            )
    localization = query_localization(localizations)
    retained_ids = (
        None
        if retained_alignments is None
        else sorted({str(item["document_id"]) for item in retained_alignments})
    )
    retained = compute_retained_coverage(
        gold,
        None if retained_ids is None else surfaced_gold_set(gold, retained_ids),
    )
    snapshots = (
        state_snapshot,
        request_snapshot,
        protocol_snapshot,
        raw_events_snapshot,
        latest_snapshot,
        *((manifest_snapshot,) if isinstance(manifest_snapshot, _Snapshot) else ()),
        *tool_snapshots,
        *corpus_snapshots,
    )
    resolution_payload: dict[str, Any] = {
        "run": {"run_id": run_id, "attempt": attempt},
        "dataset": {"dataset_id": dataset_id, "query_id": query_id},
        "configuration": config.to_mapping(),
        "documents": [
            {
                "id": document.document_id,
                "sha256": document.digest,
                "full_characters": len(document.body),
            }
            for document in documents
        ],
        "metrics": {
            "coverage": {
                "any": coverage.any,
                "mean": coverage.mean,
                "all": coverage.all,
            },
            "localization": {
                "value": localization.value,
                "matched_gold_count": localization.matched_gold_count,
                "unavailable_reason": (
                    localization.unavailable_reason.value
                    if localization.unavailable_reason is not None
                    else None
                ),
                "per_document": [
                    {"document_id": item.document_id, "value": item.score}
                    for item in localization.per_document
                ],
            },
            "retained_coverage": {
                "value": retained.value,
                "unavailable_reason": (
                    retained.unavailable_reason.value
                    if retained.unavailable_reason is not None
                    else None
                ),
            },
        },
        "counts": {
            "gold_documents": len(documents),
            "surfaced_gold_documents": len(surfaced_ids),
            "tool_observations": len(observations),
            "alignments": len(alignments),
        },
        "private": {
            "alignments": list(alignments),
            "retained_alignments": (
                [] if retained_alignments is None else list(retained_alignments)
            ),
        },
    }
    identity_inputs = {
        "analysis_configuration": config.to_mapping(),
        "analysis_configuration_sha256": _sha256(
            _canonical_json_bytes(config.to_mapping())
        ),
        "attempt": attempt,
        "completed_run_state": _snapshot_identity(state_snapshot),
        "corpus": [_snapshot_identity(value) for value in corpus_snapshots],
        "corpus_sha256": _sha256(
            _canonical_json_bytes(
                [_snapshot_identity(value) for value in corpus_snapshots]
            )
        ),
        "externalized_tool_results": [
            _snapshot_identity(value) for value in tool_snapshots
        ],
        "final_model_context": _snapshot_identity(latest_snapshot),
        "gold_manifest": _snapshot_identity(manifest_snapshot),
        "dataset_query_sha256": _sha256(
            _canonical_json_bytes(
                {
                    "dataset_id": dataset_id,
                    "gold_manifest_sha256": manifest_snapshot.sha256,
                    "query_id": query_id,
                }
            )
        ),
        "derived_resolution_sha256": _sha256(
            _canonical_json_bytes(resolution_payload)
        ),
        "protocol_event_stream": _snapshot_identity(protocol_snapshot),
        "recorder_event_stream": _snapshot_identity(raw_events_snapshot),
        "protocol_request": _snapshot_identity(request_snapshot),
        "run_id": run_id,
    }
    identity_sha256 = _sha256(_canonical_json_bytes(identity_inputs))
    evidence: dict[str, Any] = {
        "schema": "dci.trajectory-resolution/v1",
        "identity": {"sha256": identity_sha256, "inputs": identity_inputs},
        **resolution_payload,
    }
    _revalidate(snapshots)
    if output_path is not None:
        _atomic_private_json(Path(output_path), evidence)
    return evidence


def _safe_public_id(value: object) -> str:
    if (
        type(value) is not str
        or _PUBLIC_ID.fullmatch(value) is None
        or value.startswith("/")
        or "\\" in value
        or ".." in PurePosixPath(value).parts
    ):
        raise TrajectoryResolutionError("DCI public resolution identity is invalid")
    return value


def _finite_unit_float(value: object) -> float:
    if type(value) is not float or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise TrajectoryResolutionError("DCI public resolution metric is invalid")
    return value


def _non_negative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise TrajectoryResolutionError("DCI public resolution count is invalid")
    return value


def _validated_public_fields(
    evidence: object,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if (
        type(evidence) is not dict
        or set(evidence)
        != {
            "schema",
            "identity",
            "run",
            "dataset",
            "configuration",
            "documents",
            "metrics",
            "counts",
            "private",
        }
        or evidence.get("schema") != "dci.trajectory-resolution/v1"
    ):
        raise TrajectoryResolutionError("DCI trajectory resolution evidence is invalid")
    identity = evidence.get("identity")
    run = evidence.get("run")
    dataset = evidence.get("dataset")
    configuration = evidence.get("configuration")
    metrics = evidence.get("metrics")
    counts = evidence.get("counts")
    if (
        type(identity) is not dict
        or set(identity) != {"sha256", "inputs"}
        or type(identity.get("sha256")) is not str
        or _SHA256.fullmatch(identity["sha256"]) is None
        or type(identity.get("inputs")) is not dict
        or identity["sha256"] != _sha256(_canonical_json_bytes(identity["inputs"]))
        or type(run) is not dict
        or set(run) != {"run_id", "attempt"}
        or type(dataset) is not dict
        or set(dataset) != {"dataset_id", "query_id"}
        or type(configuration) is not dict
        or type(metrics) is not dict
        or set(metrics) != {"coverage", "localization", "retained_coverage"}
        or type(counts) is not dict
        or set(counts)
        != {
            "gold_documents",
            "surfaced_gold_documents",
            "tool_observations",
            "alignments",
        }
    ):
        raise TrajectoryResolutionError("DCI trajectory resolution evidence is invalid")
    inputs = identity["inputs"]
    expected_input_keys = {
        "analysis_configuration",
        "analysis_configuration_sha256",
        "attempt",
        "completed_run_state",
        "corpus",
        "corpus_sha256",
        "externalized_tool_results",
        "final_model_context",
        "gold_manifest",
        "dataset_query_sha256",
        "derived_resolution_sha256",
        "protocol_event_stream",
        "protocol_request",
        "recorder_event_stream",
        "run_id",
    }
    dataset_id = _safe_public_id(dataset.get("dataset_id"))
    query_id = _safe_public_id(dataset.get("query_id"))
    manifest_identity = inputs.get("gold_manifest")
    if (
        set(inputs) != expected_input_keys
        or run.get("run_id") != inputs.get("run_id")
        or run.get("attempt") != inputs.get("attempt")
        or type(run.get("run_id")) is not str
        or not run["run_id"]
        or type(run.get("attempt")) is not int
        or run["attempt"] <= 0
        or configuration != inputs.get("analysis_configuration")
        or inputs.get("analysis_configuration_sha256")
        != _sha256(_canonical_json_bytes(configuration))
        or type(manifest_identity) is not dict
        or _SHA256.fullmatch(str(manifest_identity.get("sha256"))) is None
        or inputs.get("dataset_query_sha256")
        != _sha256(
            _canonical_json_bytes(
                {
                    "dataset_id": dataset_id,
                    "gold_manifest_sha256": manifest_identity["sha256"],
                    "query_id": query_id,
                }
            )
        )
        or inputs.get("derived_resolution_sha256")
        != _sha256(
            _canonical_json_bytes(
                {
                    key: evidence[key]
                    for key in (
                        "run",
                        "dataset",
                        "configuration",
                        "documents",
                        "metrics",
                        "counts",
                        "private",
                    )
                }
            )
        )
    ):
        raise TrajectoryResolutionError("DCI public resolution identity is invalid")
    coverage = metrics.get("coverage")
    localization = metrics.get("localization")
    retained = metrics.get("retained_coverage")
    if (
        type(coverage) is not dict
        or set(coverage) != {"any", "mean", "all"}
        or type(localization) is not dict
        or set(localization)
        != {"value", "matched_gold_count", "unavailable_reason", "per_document"}
        or type(retained) is not dict
        or set(retained) != {"value", "unavailable_reason"}
    ):
        raise TrajectoryResolutionError("DCI trajectory resolution evidence is invalid")
    any_value = _finite_unit_float(coverage.get("any"))
    mean_value = _finite_unit_float(coverage.get("mean"))
    all_value = _finite_unit_float(coverage.get("all"))
    if not all_value <= mean_value <= any_value:
        raise TrajectoryResolutionError("DCI public resolution metric is invalid")
    gold_count = _non_negative_int(counts.get("gold_documents"))
    surfaced_count = _non_negative_int(counts.get("surfaced_gold_documents"))
    _non_negative_int(counts.get("tool_observations"))
    alignment_count = _non_negative_int(counts.get("alignments"))
    if (
        gold_count <= 0
        or surfaced_count > gold_count
        or alignment_count < surfaced_count
        or any_value != float(surfaced_count > 0)
        or not math.isclose(
            mean_value, surfaced_count / gold_count, rel_tol=0.0, abs_tol=1e-15
        )
        or all_value != float(surfaced_count == gold_count)
    ):
        raise TrajectoryResolutionError("DCI public resolution aggregate is invalid")
    matched_count = _non_negative_int(localization.get("matched_gold_count"))
    per_document = localization.get("per_document")
    if type(per_document) is not list or len(per_document) != matched_count:
        raise TrajectoryResolutionError("DCI public localization evidence is invalid")
    for item in per_document:
        if (
            type(item) is not dict
            or set(item) != {"document_id", "value"}
            or type(item.get("document_id")) is not str
            or not item["document_id"]
        ):
            raise TrajectoryResolutionError("DCI public localization evidence is invalid")
        _finite_unit_float(item.get("value"))
    value = localization.get("value")
    reason = localization.get("unavailable_reason")
    if matched_count:
        expected = sum(item["value"] for item in per_document) / matched_count
        if (
            type(value) is not float
            or not math.isclose(value, expected, rel_tol=0.0, abs_tol=1e-15)
            or reason is not None
            or matched_count != surfaced_count
        ):
            raise TrajectoryResolutionError("DCI public localization evidence is invalid")
    elif value is not None or reason != "no-surfaced-gold" or surfaced_count != 0:
        raise TrajectoryResolutionError("DCI public localization evidence is invalid")
    retained_value = retained.get("value")
    retained_reason = retained.get("unavailable_reason")
    if retained_value is None:
        if retained_reason != "final-context-unavailable":
            raise TrajectoryResolutionError("DCI retained coverage evidence is invalid")
    elif (
        type(retained_value) is not float
        or not math.isfinite(retained_value)
        or not 0.0 <= retained_value <= 1.0
        or retained_reason is not None
    ):
        raise TrajectoryResolutionError("DCI retained coverage evidence is invalid")
    return identity, dataset, metrics, counts


def public_resolution_projection(evidence: object) -> dict[str, Any]:
    """Return the body-free aggregate projection of one private artifact."""

    identity, dataset, metrics, counts = _validated_public_fields(evidence)
    coverage = metrics["coverage"]
    localization = metrics["localization"]
    retained = metrics["retained_coverage"]
    public_metrics = {
        "coverage": {
            "any": coverage.get("any"),
            "mean": coverage.get("mean"),
            "all": coverage.get("all"),
        },
        "localization": {
            "value": localization.get("value"),
            "matched_gold_count": localization.get("matched_gold_count"),
            "unavailable_reason": localization.get("unavailable_reason"),
        },
        "retained_coverage": {
            "value": retained.get("value"),
            "unavailable_reason": retained.get("unavailable_reason"),
        },
    }
    return {
        "schema": "dci.trajectory-resolution-summary/v1",
        "identity_sha256": identity["sha256"],
        "dataset_id": dataset.get("dataset_id"),
        "query_id": dataset.get("query_id"),
        "metrics": public_metrics,
        "counts": {
            "gold_documents": counts.get("gold_documents"),
            "surfaced_gold_documents": counts.get("surfaced_gold_documents"),
            "tool_observations": counts.get("tool_observations"),
            "alignments": counts.get("alignments"),
        },
    }


def validate_public_resolution_summary(summary: object) -> dict[str, Any]:
    """Validate and copy the closed, body-free public summary shape."""

    if (
        type(summary) is not dict
        or set(summary)
        != {"schema", "identity_sha256", "dataset_id", "query_id", "metrics", "counts"}
        or summary.get("schema") != "dci.trajectory-resolution-summary/v1"
        or type(summary.get("identity_sha256")) is not str
        or _SHA256.fullmatch(summary["identity_sha256"]) is None
    ):
        raise TrajectoryResolutionError("DCI public resolution summary is invalid")
    dataset_id = _safe_public_id(summary.get("dataset_id"))
    query_id = _safe_public_id(summary.get("query_id"))
    metrics = summary.get("metrics")
    counts = summary.get("counts")
    if (
        type(metrics) is not dict
        or set(metrics) != {"coverage", "localization", "retained_coverage"}
        or type(counts) is not dict
        or set(counts)
        != {
            "gold_documents",
            "surfaced_gold_documents",
            "tool_observations",
            "alignments",
        }
    ):
        raise TrajectoryResolutionError("DCI public resolution summary is invalid")
    coverage = metrics.get("coverage")
    localization = metrics.get("localization")
    retained = metrics.get("retained_coverage")
    if (
        type(coverage) is not dict
        or set(coverage) != {"any", "mean", "all"}
        or type(localization) is not dict
        or set(localization)
        != {"value", "matched_gold_count", "unavailable_reason"}
        or type(retained) is not dict
        or set(retained) != {"value", "unavailable_reason"}
    ):
        raise TrajectoryResolutionError("DCI public resolution summary is invalid")
    any_value = _finite_unit_float(coverage.get("any"))
    mean_value = _finite_unit_float(coverage.get("mean"))
    all_value = _finite_unit_float(coverage.get("all"))
    gold_count = _non_negative_int(counts.get("gold_documents"))
    surfaced_count = _non_negative_int(counts.get("surfaced_gold_documents"))
    tool_count = _non_negative_int(counts.get("tool_observations"))
    alignment_count = _non_negative_int(counts.get("alignments"))
    if (
        gold_count <= 0
        or surfaced_count > gold_count
        or alignment_count < surfaced_count
        or any_value != float(surfaced_count > 0)
        or not math.isclose(
            mean_value, surfaced_count / gold_count, rel_tol=0.0, abs_tol=1e-15
        )
        or all_value != float(surfaced_count == gold_count)
    ):
        raise TrajectoryResolutionError("DCI public resolution summary is invalid")
    matched_count = _non_negative_int(localization.get("matched_gold_count"))
    localization_value = localization.get("value")
    localization_reason = localization.get("unavailable_reason")
    if matched_count:
        _finite_unit_float(localization_value)
        if matched_count != surfaced_count or localization_reason is not None:
            raise TrajectoryResolutionError("DCI public resolution summary is invalid")
    elif (
        localization_value is not None
        or localization_reason != "no-surfaced-gold"
        or surfaced_count != 0
    ):
        raise TrajectoryResolutionError("DCI public resolution summary is invalid")
    retained_value = retained.get("value")
    retained_reason = retained.get("unavailable_reason")
    if retained_value is None:
        if retained_reason != "final-context-unavailable":
            raise TrajectoryResolutionError("DCI public resolution summary is invalid")
    else:
        _finite_unit_float(retained_value)
        if retained_reason is not None:
            raise TrajectoryResolutionError("DCI public resolution summary is invalid")
    return {
        "schema": "dci.trajectory-resolution-summary/v1",
        "identity_sha256": summary["identity_sha256"],
        "dataset_id": dataset_id,
        "query_id": query_id,
        "metrics": {
            "coverage": {"any": any_value, "mean": mean_value, "all": all_value},
            "localization": {
                "value": localization_value,
                "matched_gold_count": matched_count,
                "unavailable_reason": localization_reason,
            },
            "retained_coverage": {
                "value": retained_value,
                "unavailable_reason": retained_reason,
            },
        },
        "counts": {
            "gold_documents": gold_count,
            "surfaced_gold_documents": surfaced_count,
            "tool_observations": tool_count,
            "alignments": alignment_count,
        },
    }
