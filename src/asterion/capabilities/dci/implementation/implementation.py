"""Runtime-neutral DCI local-corpus research implementation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from asterion.capability_sdk import (
    CapabilityExecutionError,
    CapabilityExecutionResult,
    CapabilityInvocation,
)
from asterion.capabilities.dci.implementation._runtime import (
    RuntimeEventError,
    RuntimeRequest,
    event_mappings,
)
from asterion.documents.tools import DocumentToolError, verify_public_anchor


ANSWER_MEDIA_TYPE = "application/vnd.dci.research.answer+json"
LOCATIONS_MEDIA_TYPE = "application/vnd.dci.research.locations+json"
TRAJECTORY_MEDIA_TYPE = "application/vnd.dci.research.trajectory+json"
CORE_ARTIFACT_MEDIA_TYPES = (
    ANSWER_MEDIA_TYPE,
    LOCATIONS_MEDIA_TYPE,
    TRAJECTORY_MEDIA_TYPE,
)
_REQUIRED_CAPABILITIES = ("filesystem.read", "shell")
_REQUIRED_POLICIES = ("policy.context-management", "policy.local-corpus")


class DciLocalResearchImplementation:
    """Delegate local-corpus research to an explicitly supplied runtime."""

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        corpus = _require_local_corpus(invocation)
        required = invocation.manifest["requires_capabilities"]
        policies = invocation.manifest["requires_policies"]
        if required != _REQUIRED_CAPABILITIES or policies != _REQUIRED_POLICIES:
            raise CapabilityExecutionError("research capability declaration is invalid")
        request = RuntimeRequest(
            run_id=invocation.run_id,
            input_text=invocation.input_text,
            requested_capabilities=required,
        )
        try:
            events = event_mappings(
                [
                    event
                    async for event in cast(Any, invocation.runtime).run(
                        request, signal=invocation.signal
                    )
                ]
            )
            answer_uri, locations, trajectory = _core_evidence(events, corpus)
        except (RuntimeEventError, TypeError, ValueError, RuntimeError):
            raise CapabilityExecutionError(
                "research runtime execution failed"
            ) from None
        return CapabilityExecutionResult(
            events=(
                {"type": "research.completed", "payload": {"status": "completed"}},
            ),
            artifacts=(
                {
                    "artifact_id": "dci-research-answer",
                    "media_type": ANSWER_MEDIA_TYPE,
                    "value": {"answer_artifact_uri": answer_uri},
                },
                {
                    "artifact_id": "dci-research-locations",
                    "media_type": LOCATIONS_MEDIA_TYPE,
                    "value": locations,
                },
                {
                    "artifact_id": "dci-research-trajectory",
                    "media_type": TRAJECTORY_MEDIA_TYPE,
                    "value": trajectory,
                },
            ),
        )


def _require_local_corpus(invocation: CapabilityInvocation) -> Path:
    try:
        service = invocation.host_services.get("corpus.local-root")
        root = cast(Any, service).root
    except Exception:
        raise CapabilityExecutionError("local corpus service is unavailable") from None
    if not isinstance(root, Path):
        raise CapabilityExecutionError("local corpus service is unavailable")
    return root


_LOCATION_TOOLS = frozenset({"read", "grep"})
_PATH_KEYS = ("path", "file_path", "file")


def _core_evidence(
    events: Sequence[Mapping[str, object]],
    corpus: Path,
) -> tuple[str, Mapping[str, object], Mapping[str, object]]:
    answer_uri: str | None = None
    artifact_paths: list[str] = []
    artifact_calls: list[str] = []
    calls_by_id: dict[str, tuple[str, Mapping[str, object]]] = {}
    call_order: list[str] = []
    result_errors: dict[str, bool] = {}
    for event in events:
        event_type = event.get("type")
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if event_type == "artifact.created":
            artifact = payload.get("artifact")
            if not isinstance(artifact, Mapping):
                continue
            uri = artifact.get("uri")
            if not isinstance(uri, str) or not uri:
                continue
            kind = artifact.get("kind")
            if kind == "answer":
                if answer_uri is None:
                    answer_uri = uri
            elif kind == "locations":
                artifact_paths.append(uri)
            elif kind == "trajectory":
                artifact_calls.append(uri)
        elif event_type == "tool.call":
            call_id, name, arguments = _tool_call(payload)
            if call_id in calls_by_id:
                raise CapabilityExecutionError(
                    "research runtime evidence is unavailable"
                )
            calls_by_id[call_id] = (name, arguments)
            call_order.append(call_id)
        elif event_type == "tool.result":
            call_id = payload.get("call_id")
            is_error = payload.get("is_error")
            if (
                not isinstance(call_id, str)
                or call_id not in calls_by_id
                or call_id in result_errors
                or not isinstance(is_error, bool)
            ):
                raise CapabilityExecutionError(
                    "research runtime evidence is unavailable"
                )
            result_errors[call_id] = is_error
    anchors: list[Mapping[str, object]] = []
    if call_order:
        if set(call_order) != set(result_errors):
            raise CapabilityExecutionError("research runtime evidence is unavailable")
        paths: list[str] = []
        calls: list[str] = []
        for call_id in call_order:
            name, arguments = calls_by_id[call_id]
            calls.append(name)
            if name.casefold() == "document-read":
                if result_errors[call_id]:
                    continue
                document, anchor = _verified_document_anchor(arguments, corpus)
                paths.append(document)
                anchors.append(anchor)
                continue
            location = _tool_location(name, arguments)
            if location is not None:
                paths.append(location)
    else:
        paths = artifact_paths
        calls = artifact_calls
    if answer_uri is None or not paths or not calls:
        raise CapabilityExecutionError("research runtime evidence is unavailable")
    locations: dict[str, object] = {"paths": tuple(paths)}
    if anchors:
        locations["anchors"] = tuple(anchors)
    return answer_uri, locations, {"calls": tuple(calls)}


def _verified_document_anchor(
    arguments: Mapping[str, object], corpus: Path
) -> tuple[str, Mapping[str, object]]:
    if set(arguments) != {"anchor"} or not isinstance(arguments["anchor"], Mapping):
        raise CapabilityExecutionError("research runtime evidence is unavailable")
    try:
        anchor = verify_public_anchor(corpus, arguments["anchor"])
    except DocumentToolError:
        raise CapabilityExecutionError(
            "research runtime evidence is unavailable"
        ) from None
    document = anchor["document"]
    if not isinstance(document, str):
        raise CapabilityExecutionError("research runtime evidence is unavailable")
    return document, anchor


def _tool_call(
    payload: Mapping[str, object],
) -> tuple[str, str, Mapping[str, object]]:
    call_id = payload.get("call_id")
    name = payload.get("name")
    arguments = payload.get("arguments")
    if (
        not isinstance(call_id, str)
        or not call_id
        or not isinstance(name, str)
        or not name
        or not isinstance(arguments, Mapping)
    ):
        raise CapabilityExecutionError("research runtime evidence is unavailable")
    return call_id, name, arguments


def _tool_location(name: str, arguments: Mapping[str, object]) -> str | None:
    kind = name.casefold()
    if kind not in _LOCATION_TOOLS:
        return None
    raw = _argument_path(arguments)
    if raw is None:
        if kind == "grep":
            return "."
        raise CapabilityExecutionError("research runtime evidence is unavailable")
    if not _corpus_relative(raw):
        raise CapabilityExecutionError("research runtime evidence is unavailable")
    return raw


def _argument_path(arguments: Mapping[str, object]) -> str | None:
    for key in _PATH_KEYS:
        if key not in arguments:
            continue
        value = arguments[key]
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
            continue
        raise CapabilityExecutionError("research runtime evidence is unavailable")
    return None


def _corpus_relative(value: str) -> bool:
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts
