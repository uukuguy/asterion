"""Functional, provider-neutral views over an injected client event stream.

The module deliberately keeps its TUI representation as immutable public state.
Renderers may consume that state, but no renderer receives private values unless it
uses the injected :class:`AgentClient` private-value service with a named purpose.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TextIO

from asterion.client.protocol import ClientEvent, ClientIntent, validate_client_event
from asterion.client.sdk import AgentClient


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_DEFAULT_RENDER_BYTES = 64 * 1024


class ClientInteractiveError(ValueError):
    """Raised with a public-safe explanation for an unusable client view."""


@dataclass(frozen=True)
class ClientCommand:
    """One public command exposed at an exact command registry revision."""

    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _IDENTIFIER.fullmatch(self.name) is None:
            raise ClientInteractiveError("client command is invalid")


@dataclass(frozen=True)
class ClientUiRequest:
    """A body-free extension UI request awaiting a public response."""

    request_id: str
    method: str
    payload_ref: str
    deadline_ms: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, str)
            or _OPAQUE_ID.fullmatch(self.request_id) is None
            or not isinstance(self.method, str)
            or _IDENTIFIER.fullmatch(self.method) is None
            or not isinstance(self.payload_ref, str)
            or _OPAQUE_ID.fullmatch(self.payload_ref) is None
            or not _positive_integer(self.deadline_ms)
        ):
            raise ClientInteractiveError("client UI request is invalid")


@dataclass(frozen=True, repr=False)
class ExtensionUiResponse:
    """Public response projection.  It contains only an opaque response reference."""

    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        payload = _freeze_mapping(self.payload)
        if set(payload) != {"request_id", "cancelled", "response_ref"}:
            raise ClientInteractiveError("client UI response is invalid")
        if (
            not isinstance(payload["request_id"], str)
            or _OPAQUE_ID.fullmatch(payload["request_id"]) is None
            or type(payload["cancelled"]) is not bool
            or payload["response_ref"] is not None
            and (
                not isinstance(payload["response_ref"], str)
                or _OPAQUE_ID.fullmatch(payload["response_ref"]) is None
            )
            or (payload["cancelled"] and payload["response_ref"] is not None)
        ):
            raise ClientInteractiveError("client UI response is invalid")
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True)
class ClientViewState:
    """Complete immutable projection of one client event generation.

    All stored event data is already public protocol metadata.  Mappings are
    frozen so one renderer cannot mutate another renderer's view.
    """

    session_id: str
    generation: int
    next_sequence: int
    status: str | None
    command_revision: int
    commands: tuple[ClientCommand, ...]
    pending_ui: Mapping[str, ClientUiRequest]
    terminal: bool = False
    artifacts: tuple[ClientEvent, ...] = ()
    exports: tuple[ClientEvent, ...] = ()
    faults: tuple[ClientEvent, ...] = ()
    messages: tuple[ClientEvent, ...] = ()
    operation_receipts: tuple[ClientEvent, ...] = ()
    shares: tuple[ClientEvent, ...] = ()
    active_tool_calls: Mapping[str, ClientEvent] = field(default_factory=dict)
    completed_tool_calls: tuple[ClientEvent, ...] = ()
    usage: Mapping[str, int] | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.session_id, str)
            or _OPAQUE_ID.fullmatch(self.session_id) is None
            or not _positive_integer(self.generation)
            or not _positive_integer(self.next_sequence)
            or not _nonnegative_integer(self.command_revision)
            or self.status is not None and not isinstance(self.status, str)
            or not isinstance(self.commands, tuple)
            or any(type(command) is not ClientCommand for command in self.commands)
            or tuple(command.name for command in self.commands)
            != tuple(sorted({command.name for command in self.commands}))
        ):
            raise ClientInteractiveError("client view state is invalid")
        pending_ui = _freeze_mapping(self.pending_ui)
        active_calls = _freeze_mapping(self.active_tool_calls)
        if (
            any(not isinstance(key, str) or type(value) is not ClientUiRequest for key, value in pending_ui.items())
            or any(not isinstance(key, str) or type(value) is not ClientEvent for key, value in active_calls.items())
            or not isinstance(self.terminal, bool)
            or any(not isinstance(group, tuple) for group in (self.artifacts, self.exports, self.faults, self.messages, self.operation_receipts, self.shares, self.completed_tool_calls))
            or any(type(event) is not ClientEvent for group in (self.artifacts, self.exports, self.faults, self.messages, self.operation_receipts, self.shares, self.completed_tool_calls) for event in group)
        ):
            raise ClientInteractiveError("client view state is invalid")
        if self.usage is not None:
            usage = _freeze_mapping(self.usage)
            if set(usage) != {"aggregate_tokens", "application_tokens", "child_tokens", "controller_tokens", "cost_micros"} or any(not _nonnegative_integer(value) for value in usage.values()):
                raise ClientInteractiveError("client view state is invalid")
            object.__setattr__(self, "usage", usage)
        object.__setattr__(self, "pending_ui", pending_ui)
        object.__setattr__(self, "active_tool_calls", active_calls)

    @classmethod
    def empty(cls, session_id: str, generation: int) -> ClientViewState:
        return cls(
            session_id=session_id, generation=generation, next_sequence=1,
            status=None, command_revision=0, commands=(), pending_ui=MappingProxyType({}),
        )


@dataclass(frozen=True)
class ClientCommandRegistry:
    """Exact command registry with one direct owner per canonical intent identity.

    A normal failure is retained and replayed as the same public error.  Owner
    cancellation/process control abandons the local record: waiters are cancelled
    and a later retry is a new endpoint admission, including if the endpoint had
    already acted before signalling cancellation.
    """

    revision: int
    commands: tuple[ClientCommand, ...]
    _invocations: dict[tuple[str, ...], _CommandInvocation] = field(
        default_factory=dict, init=False, compare=False, repr=False
    )
    _invocation_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        if (
            not _nonnegative_integer(self.revision)
            or not isinstance(self.commands, tuple)
            or any(type(command) is not ClientCommand for command in self.commands)
            or tuple(command.name for command in self.commands)
            != tuple(sorted({command.name for command in self.commands}))
        ):
            raise ClientInteractiveError("client command registry is invalid")

    @classmethod
    def empty(cls) -> ClientCommandRegistry:
        return cls(0, ())

    @classmethod
    def from_state(cls, state: ClientViewState) -> ClientCommandRegistry:
        if not isinstance(state, ClientViewState):
            raise ClientInteractiveError("client command registry is invalid")
        return cls(state.command_revision, state.commands)

    def update(self, *, revision: int, commands: tuple[ClientCommand, ...]) -> ClientCommandRegistry:
        candidate = ClientCommandRegistry(revision, commands)
        if candidate.revision <= self.revision:
            raise ClientInteractiveError("client command revision is not monotonic")
        return candidate

    def intent(
        self, *, session_id: str, authority_revision: int, intent_id: str,
        command_name: str, arguments_ref: str, client_id: str = "client-1",
    ) -> ClientIntent:
        if command_name not in {command.name for command in self.commands}:
            raise ClientInteractiveError("client command is unavailable")
        try:
            return ClientIntent(
                protocol="asterion.agent-client/v1", intent_id=intent_id, client_id=client_id,
                session_id=session_id, authority_revision=authority_revision, type="command.invoke",
                payload={"arguments_ref": arguments_ref, "command_name": command_name, "command_revision": self.revision},
            )
        except Exception:
            raise ClientInteractiveError("client command is invalid") from None

    async def invoke(
        self, client: AgentClient, *, session_id: str, authority_revision: int,
        intent_id: str, command_name: str, arguments_ref: str,
    ) -> str:
        if not isinstance(client, AgentClient):
            raise ClientInteractiveError("client command is invalid")
        try:
            client_id = _client_id(client)
            intent = self.intent(
                session_id=session_id, authority_revision=authority_revision,
                intent_id=intent_id, command_name=command_name,
                arguments_ref=arguments_ref, client_id=client_id,
            )
            identity = (
                intent.client_id, intent.session_id, str(intent.authority_revision),
                intent.intent_id,
            )
            digest = _intent_digest(intent)
            async with self._invocation_lock:
                invocation = self._invocations.get(identity)
                if invocation is None:
                    invocation = _CommandInvocation(
                        digest=digest,
                        completed=asyncio.get_running_loop().create_future(),
                    )
                    self._invocations[identity] = invocation
                    owner = True
                elif invocation.digest != digest:
                    raise ClientInteractiveError("client command invocation conflicts")
                else:
                    owner = False
            if owner:
                return await self._submit_owner(client, intent, identity, invocation)
            return await self._wait_for_invocation(invocation)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except ClientInteractiveError:
            raise
        except Exception:
            raise ClientInteractiveError("client command submission is unavailable") from None

    async def _submit_owner(
        self, client: AgentClient, intent: ClientIntent, identity: tuple[str, ...],
        invocation: _CommandInvocation,
    ) -> str:
        try:
            result = await client.submit(intent)
            if not isinstance(result, str):
                raise ValueError
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            await self._abandon_invocation(identity, invocation)
            raise
        except Exception:
            await self._finish_invocation(invocation, result=None)
            raise ClientInteractiveError("client command submission is unavailable") from None
        await self._finish_invocation(invocation, result=result)
        return result

    async def _wait_for_invocation(self, invocation: _CommandInvocation) -> str:
        await asyncio.shield(invocation.completed)
        if invocation.result is None:
            raise ClientInteractiveError("client command submission is unavailable")
        return invocation.result

    async def _finish_invocation(
        self, invocation: _CommandInvocation, *, result: str | None,
    ) -> None:
        async with self._invocation_lock:
            invocation.result = result
            if not invocation.completed.done():
                invocation.completed.set_result(None)

    async def _abandon_invocation(
        self, identity: tuple[str, ...], invocation: _CommandInvocation,
    ) -> None:
        async with self._invocation_lock:
            if self._invocations.get(identity) is invocation:
                del self._invocations[identity]
            if not invocation.completed.done():
                invocation.completed.cancel()


@dataclass
class _CommandInvocation:
    """One digest-bound command admission shared by its owner and waiters."""

    digest: str
    completed: asyncio.Future[None]
    result: str | None = None


def reduce_client_view(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    """Apply exactly one revalidated public event to an immutable view state."""

    if not isinstance(state, ClientViewState):
        raise ClientInteractiveError("client view state is invalid")
    safe_event = _validated_event(event)
    _require_next_client_event(state, safe_event)
    reducer = _VIEW_EVENT_REDUCERS.get(safe_event.type)
    if reducer is None:
        raise ClientInteractiveError("client event is unsupported")
    updated = reducer(state, safe_event)
    return replace(updated, next_sequence=state.next_sequence + 1)


async def run_headless(
    client: AgentClient, *, mode: str, stdout: TextIO, max_output_bytes: int = _DEFAULT_RENDER_BYTES,
    deadline_ms: int | None = None,
) -> ClientViewState:
    """Render a body-free JSON event stream or only the final assistant message."""

    _require_client_and_output(client, stdout, max_output_bytes)
    if mode not in {"json", "text"}:
        raise ClientInteractiveError("client headless mode is invalid")
    state: ClientViewState | None = None
    final_messages: list[ClientEvent] = []
    try:
        async for raw_event in client.events():
            event = _validated_event(raw_event)
            if state is None:
                state = ClientViewState.empty(event.session_id, event.generation)
            state = reduce_client_view(state, event)
            if mode == "json":
                _write_bounded(stdout, json.dumps(_public_event(event), separators=(",", ":"), sort_keys=True) + "\n", max_output_bytes)
            elif event.type == "operation.receipted":
                _write_bounded(stdout, _operation_receipt_text(event) + "\n", max_output_bytes)
            elif event.type == "message.available" and event.payload["role"] == "assistant":
                final_messages.append(event)
        if state is None or not state.terminal:
            raise ClientInteractiveError("client event stream is incomplete")
        if mode == "text":
            if len(final_messages) != 1:
                raise ClientInteractiveError("client final message is unavailable")
            payload = final_messages[0].payload
            size = payload["size"]
            if not isinstance(size, int) or isinstance(size, bool) or not _nonnegative_integer(size):
                raise ClientInteractiveError("client final message is unavailable")
            try:
                value = client.resolve_text(
                    str(payload["content_ref"]), purpose="headless-final",
                    max_bytes=max(1, size), deadline_ms=_deadline(deadline_ms),
                )
                body = value.encode("utf-8")
                if len(body) != size or hashlib.sha256(body).hexdigest() != payload["sha256"]:
                    raise ValueError
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                raise ClientInteractiveError("client final message is unavailable") from None
            _write_bounded(stdout, value + "\n", max_output_bytes)
        return state
    except asyncio.CancelledError:
        raise
    except ClientInteractiveError:
        raise
    except Exception:
        raise ClientInteractiveError("client headless view is unavailable") from None
    finally:
        await _close_client(client)


async def run_interactive(
    client: AgentClient, *, stdout: TextIO, max_output_bytes: int = _DEFAULT_RENDER_BYTES,
) -> ClientViewState:
    """Run the accessible deterministic TUI projection without pixel assumptions."""

    _require_client_and_output(client, stdout, max_output_bytes)
    state: ClientViewState | None = None
    try:
        async for raw_event in client.events():
            event = _validated_event(raw_event)
            if state is None:
                state = ClientViewState.empty(event.session_id, event.generation)
            state = reduce_client_view(state, event)
            _write_bounded(stdout, json.dumps(_accessible_state(state), separators=(",", ":"), sort_keys=True) + "\n", max_output_bytes)
        if state is None or not state.terminal:
            raise ClientInteractiveError("client event stream is incomplete")
        return state
    except asyncio.CancelledError:
        raise
    except ClientInteractiveError:
        raise
    except Exception:
        raise ClientInteractiveError("client interactive view is unavailable") from None
    finally:
        await _close_client(client)


async def respond_to_extension_ui(
    request: ClientUiRequest, client: AgentClient, *,
    render: Callable[[str, ClientUiRequest], str | Awaitable[str]] | None = None,
    max_bytes: int = _DEFAULT_RENDER_BYTES, clock_ms: Callable[[], int] | None = None,
) -> ExtensionUiResponse:
    """Resolve an extension descriptor only under a named injected-service purpose.

    A stale deadline, cancellation, private-service fault, or absent renderer is
    represented by one body-free cancelled response.  No error body is surfaced.
    """

    if not isinstance(request, ClientUiRequest) or not isinstance(client, AgentClient) or not _positive_integer(max_bytes):
        raise ClientInteractiveError("client UI response is invalid")
    now = _clock_ms(clock_ms)
    if now > request.deadline_ms:
        return _cancelled_response(request.request_id)
    try:
        payload = client.resolve_text(
            request.payload_ref, purpose="interactive-render", max_bytes=max_bytes,
            deadline_ms=request.deadline_ms,
        )
        if render is None:
            return _cancelled_response(request.request_id)
        rendered = render(payload, request)
        response_ref = await rendered if isinstance(rendered, Awaitable) else rendered
        if _clock_ms(clock_ms) > request.deadline_ms:
            return _cancelled_response(request.request_id)
        if not isinstance(response_ref, str) or _OPAQUE_ID.fullmatch(response_ref) is None:
            return _cancelled_response(request.request_id)
        return ExtensionUiResponse({"request_id": request.request_id, "cancelled": False, "response_ref": response_ref})
    except asyncio.CancelledError:
        return _cancelled_response(request.request_id)
    except Exception:
        return _cancelled_response(request.request_id)


def _reduce_artifact(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    return replace(state, artifacts=state.artifacts + (event,))


def _reduce_commands(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    payload = event.payload
    revision = payload["revision"]
    commands = payload["commands"]
    if not isinstance(revision, int) or revision <= state.command_revision or not isinstance(commands, tuple):
        raise ClientInteractiveError("client command revision is invalid")
    try:
        updated = tuple(ClientCommand(name) for name in commands)
    except Exception:
        raise ClientInteractiveError("client command registry is invalid") from None
    if tuple(command.name for command in updated) != tuple(sorted({command.name for command in updated})):
        raise ClientInteractiveError("client command registry is invalid")
    return replace(state, command_revision=revision, commands=updated)


def _reduce_export(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    return replace(state, exports=state.exports + (event,))


def _reduce_ui_request(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    payload = event.payload
    deadline = payload["deadline_ms"]
    if not isinstance(deadline, int) or isinstance(deadline, bool) or not _positive_integer(deadline):
        raise ClientInteractiveError("client UI request is invalid")
    try:
        request = ClientUiRequest(str(payload["request_id"]), str(payload["method"]), str(payload["payload_ref"]), deadline)
    except Exception:
        raise ClientInteractiveError("client UI request is invalid") from None
    if request.request_id in state.pending_ui:
        raise ClientInteractiveError("client UI request is reused")
    return replace(state, pending_ui=_freeze_mapping({**state.pending_ui, request.request_id: request}))


def _reduce_fault(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    return replace(state, faults=state.faults + (event,))


def _reduce_message(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    return replace(state, messages=state.messages + (event,))


def _reduce_operation_receipt(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    operation_id = event.payload["operation_id"]
    status = event.payload["status"]
    for prior in state.operation_receipts:
        if prior.payload["operation_id"] == operation_id:
            if prior.payload["status"] != "uncertain" or status == "uncertain":
                raise ClientInteractiveError("client operation receipt is not monotonic")
    return replace(state, operation_receipts=state.operation_receipts + (event,))


def _reduce_state(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    return replace(state, status=str(event.payload["status"]))


def _reduce_terminal(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    if state.active_tool_calls:
        raise ClientInteractiveError("client terminal has active tool calls")
    return replace(state, status=str(event.payload["status"]), terminal=True, pending_ui=MappingProxyType({}))


def _reduce_share(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    return replace(state, shares=state.shares + (event,))


def _reduce_tool_started(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    call_id = event.payload["call_id"]
    if not isinstance(call_id, str) or call_id in state.active_tool_calls or any(item.payload["call_id"] == call_id for item in state.completed_tool_calls):
        raise ClientInteractiveError("client tool call is invalid")
    return replace(state, active_tool_calls=_freeze_mapping({**state.active_tool_calls, call_id: event}))


def _reduce_tool_completed(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    call_id = event.payload["call_id"]
    if not isinstance(call_id, str) or call_id not in state.active_tool_calls:
        raise ClientInteractiveError("client tool completion is unmatched")
    active = dict(state.active_tool_calls)
    del active[call_id]
    return replace(state, active_tool_calls=_freeze_mapping(active), completed_tool_calls=state.completed_tool_calls + (event,))


def _reduce_usage(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    if any(not _nonnegative_integer(value) for value in event.payload.values()):
        raise ClientInteractiveError("client usage is invalid")
    return replace(state, usage=_freeze_mapping(dict(event.payload)))


_VIEW_EVENT_REDUCERS: Mapping[str, Callable[[ClientViewState, ClientEvent], ClientViewState]] = MappingProxyType({
    "artifact.available": _reduce_artifact, "commands.changed": _reduce_commands,
    "export.created": _reduce_export, "extension-ui.requested": _reduce_ui_request,
    "fault.raised": _reduce_fault, "message.available": _reduce_message,
    "operation.receipted": _reduce_operation_receipt,
    "session.state": _reduce_state, "session.terminal": _reduce_terminal,
    "share.created": _reduce_share, "tool.started": _reduce_tool_started,
    "tool.completed": _reduce_tool_completed, "usage.reported": _reduce_usage,
})


def _require_next_client_event(state: ClientViewState, event: ClientEvent) -> None:
    if state.terminal:
        raise ClientInteractiveError("client event follows terminal state")
    if event.session_id != state.session_id or event.generation != state.generation:
        raise ClientInteractiveError("client event identity is invalid")
    if event.sequence != state.next_sequence:
        raise ClientInteractiveError("client event sequence is invalid")


def _validated_event(value: object) -> ClientEvent:
    if not isinstance(value, ClientEvent):
        raise ClientInteractiveError("client event is invalid")
    try:
        return validate_client_event(_thaw(value.to_mapping()))
    except Exception:
        raise ClientInteractiveError("client event is invalid") from None


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _freeze_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ClientInteractiveError("client view state is invalid")
    return MappingProxyType(dict(value))


def _public_event(event: ClientEvent) -> Mapping[str, object]:
    return _thaw(event.to_mapping())  # type: ignore[return-value]


def _operation_receipt_text(event: ClientEvent) -> str:
    payload = event.payload
    counts = payload["effect_counts"]
    if not isinstance(counts, Mapping):
        raise ClientInteractiveError("client operation receipt is invalid")
    return "operation " + " ".join((
        f"status={payload['status']}",
        f"feature={payload['feature_id']}",
        f"reason={payload['reason_code']}",
        "counters=" + json.dumps(dict(counts), sort_keys=True, separators=(",", ":")),
    ))


def _accessible_state(state: ClientViewState) -> Mapping[str, object]:
    return {
        "session_id": state.session_id, "generation": state.generation,
        "sequence": state.next_sequence - 1, "status": state.status,
        "terminal": state.terminal, "command_revision": state.command_revision,
        "commands": [command.name for command in state.commands],
        "pending_ui": sorted(state.pending_ui), "active_tool_calls": sorted(state.active_tool_calls),
    }


def _require_client_and_output(client: object, stdout: object, max_output_bytes: object) -> None:
    if not isinstance(client, AgentClient) or not callable(getattr(stdout, "write", None)) or not _positive_integer(max_output_bytes):
        raise ClientInteractiveError("client view is invalid")


def _write_bounded(stdout: TextIO, value: str, max_output_bytes: int) -> None:
    if not isinstance(value, str) or len(value.encode("utf-8")) > max_output_bytes:
        raise ClientInteractiveError("client view output exceeds limit")
    try:
        stdout.write(value)
    except Exception:
        raise ClientInteractiveError("client view output is unavailable") from None


async def _close_client(client: AgentClient) -> None:
    try:
        await client.close()
    except asyncio.CancelledError:
        raise
    except Exception:
        raise ClientInteractiveError("client close is unavailable") from None


def _deadline(value: int | None) -> int:
    if value is None:
        return int(time.time() * 1000) + 30_000
    if not _positive_integer(value):
        raise ClientInteractiveError("client deadline is invalid")
    return value


def _clock_ms(clock_ms: Callable[[], int] | None) -> int:
    try:
        value = int(time.time() * 1000) if clock_ms is None else clock_ms()
    except Exception:
        raise ClientInteractiveError("client UI clock is invalid") from None
    if not _nonnegative_integer(value):
        raise ClientInteractiveError("client UI clock is invalid")
    return value


def _cancelled_response(request_id: str) -> ExtensionUiResponse:
    return ExtensionUiResponse({"request_id": request_id, "cancelled": True, "response_ref": None})


def _client_id(client: AgentClient) -> str:
    value = getattr(client, "_client_id", None)
    if not isinstance(value, str) or _OPAQUE_ID.fullmatch(value) is None:
        raise ClientInteractiveError("client command is invalid")
    return value


def _intent_digest(intent: ClientIntent) -> str:
    """Return a canonical digest of every field admitted under one intent identity."""

    try:
        encoded = json.dumps(
            _thaw(intent.to_mapping()), ensure_ascii=False,
            separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
    except Exception:
        raise ClientInteractiveError("client command submission is unavailable") from None
    return hashlib.sha256(encoded).hexdigest()


def _positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= _MAX_SAFE_INTEGER


def _nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= _MAX_SAFE_INTEGER
