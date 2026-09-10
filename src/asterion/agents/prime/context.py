"""Private, authenticated observations around Pi's built-in compaction.

Only the frozen evidence record is public-safe. Projection bodies, proposals,
summary text, socket identity, and diagnostics belong to the private backend.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import hmac
import inspect
import json
import math
import re
import socket
import struct
import time
from typing import Literal, NoReturn

from .compaction_budget import ModelPrice, quote_compaction_reservation


PROTOCOL = "asterion.prime-context-witness/v1"
PROJECTION = "asterion.prime-context-projection/v1"
_ERROR = "invalid Prime context witness"
_MAX_INTEGER = (1 << 53) - 1
_MAX_FRAME = 1024 * 1024
_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_BASE = {"protocol", "launch_nonce", "command_nonce", "authority_sha256", "phase"}
_PROPOSAL = _BASE | {
    "first_kept_entry_id",
    "covered_leaf_id",
    "preparation",
    "preparation_sha256",
    "source_kind",
    "pre_context_projection",
    "pre_context_json",
    "pre_context_sha256",
    "main_summary_request",
    "turn_prefix_summary_request",
    "pre_units",
    "private_diagnostics",
}
_PERSISTED = _BASE | {
    "first_kept_entry_id",
    "covered_leaf_id",
    "preparation_sha256",
    "compaction_entry",
    "compaction_entry_sha256",
    "summary",
    "summary_sha256",
    "post_context_projection",
    "post_context_json",
    "post_context_sha256",
}
_PREPARATION = {
    "first_kept_entry_id",
    "covered_leaf_id",
    "messages_to_summarize",
    "turn_prefix_messages",
    "is_split_turn",
    "previous_summary",
    "custom_instructions",
    "retained_context_projection",
    "retained_message_count",
}


class PrimeContextError(ValueError):
    """A deliberately body-free private-channel failure."""


def _fail() -> NoReturn:
    raise PrimeContextError(_ERROR) from None


def _string(value: object) -> str:
    if type(value) is not str:
        _fail()
    try:
        value.encode("utf-8")
    except UnicodeError:
        _fail()
    return value


def _integer(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= _MAX_INTEGER:
        _fail()
    return value


def _record(value: object, keys: set[str] | None = None) -> dict:
    if not isinstance(value, Mapping):
        _fail()
    result = dict(value)
    if any(type(key) is not str for key in result) or (
        keys is not None and set(result) != keys
    ):
        _fail()
    return result


def _domain(value: object, depth: int = 0) -> None:
    if depth > 64:
        _fail()
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        _integer(value, minimum=-_MAX_INTEGER)
    elif type(value) is str:
        _string(value)
    elif type(value) is list:
        for child in value:
            _domain(child, depth + 1)
    elif type(value) is dict:
        for key, child in value.items():
            _string(key)
            _domain(child, depth + 1)
    else:
        _fail()


def _encode(value: object) -> bytes:
    _domain(value)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            _fail()
        result[key] = value
    return result


def _json(text: str, *, arguments: bool = False):
    try:
        # Decimal is used only to check JSON syntax; Python never reformats tool arguments.
        return json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=lambda _: _fail(),
            parse_float=Decimal if arguments else lambda _: _fail(),
        )
    except (ValueError, TypeError, RecursionError):
        _fail()


def _content(value: object, allowed: set[str]) -> None:
    if type(value) is not list:
        _fail()
    for raw in value:
        block = _record(raw)
        kind = block.get("type")
        if kind not in allowed:
            _fail()
        if kind in {"text", "thinking"}:
            _record(block, {"type", kind})
            _string(block[kind])
        elif kind == "toolCall":
            _record(block, {"type", "name", "arguments_json"})
            _string(block["name"])
            _validate_argument(_json(_string(block["arguments_json"]), arguments=True))
        elif kind == "image":
            _record(block, {"type", "media_type", "byte_length", "sha256"})
            _string(block["media_type"])
            _integer(block["byte_length"])
            _hex(block["sha256"])


def _validate_argument(value: object, depth: int = 0) -> None:
    """Check the opaque string's JSON domain without reformatting its numbers."""
    if depth > 64:
        _fail()
    if type(value) in {int, Decimal}:
        try:
            if not math.isfinite(float(value)):
                _fail()
        except OverflowError:
            _fail()
    elif type(value) is str:
        _string(value)
    elif type(value) is list:
        for child in value:
            _validate_argument(child, depth + 1)
    elif type(value) is dict:
        for key, child in value.items():
            _string(key)
            _validate_argument(child, depth + 1)


def _validate_projection(value: object) -> dict:
    projection = _record(value, {"format", "system_prompt", "messages"})
    _domain(projection)
    if projection["format"] != PROJECTION or type(projection["messages"]) is not list:
        _fail()
    _string(projection["system_prompt"])
    for raw in projection["messages"]:
        message = _record(raw)
        role = message.get("role")
        if role in {"user", "assistant", "custom", "toolResult"}:
            keys = {"role", "content"}
            allowed = (
                {"text", "thinking", "toolCall"}
                if role == "assistant"
                else {"text", "image"}
            )
            if role == "toolResult":
                keys |= {"tool_name", "is_error"}
                _string(message.get("tool_name"))
                if type(message.get("is_error")) is not bool:
                    _fail()
            _record(message, keys)
            _content(message["content"], allowed)
        elif role == "bashExecution":
            _record(
                message,
                {"role", "command", "output", "exit_code", "cancelled", "truncated"},
            )
            _string(message["command"])
            _string(message["output"])
            if message["exit_code"] is not None:
                _integer(message["exit_code"], minimum=-_MAX_INTEGER)
            if any(
                type(message[key]) is not bool for key in ("cancelled", "truncated")
            ):
                _fail()
        elif role == "compactionSummary":
            _record(
                message,
                {"role", "summary", "retained_message_count", "custom_instructions"},
            )
            _string(message["summary"])
            if message["retained_message_count"] is not None:
                _integer(message["retained_message_count"])
            if message["custom_instructions"] is not None:
                _string(message["custom_instructions"])
        elif role == "branchSummary":
            _record(message, {"role", "summary"})
            _string(message["summary"])
        else:
            _fail()
    return projection


def encode_prime_context_v1(projection: Mapping[str, object]) -> bytes:
    """Encode an already projected context, never raw floating-point Pi messages."""
    try:
        return _encode(_validate_projection(projection))
    except (KeyError, TypeError, ValueError, RecursionError):
        _fail()


def count_rebuilt_context(projection: Mapping[str, object]) -> int:
    return len(encode_prime_context_v1(projection))


def _hex(value: object) -> str:
    text = _string(value)
    if _HEX.fullmatch(text) is None:
        _fail()
    return text


def _identifier(value: object) -> str:
    text = _string(value)
    if _ID.fullmatch(text) is None:
        _fail()
    return text


def _digest(value: object) -> str:
    return hashlib.sha256(_encode(value)).hexdigest()


def _identity(frame: dict, launch: str, command: str, phase: str) -> None:
    if frame["protocol"] != PROTOCOL or frame["phase"] != phase:
        _fail()
    if not hmac.compare_digest(_hex(frame["launch_nonce"]), _hex(launch)):
        _fail()
    if not hmac.compare_digest(_hex(frame["command_nonce"]), _hex(command)):
        _fail()
    _hex(frame["authority_sha256"])


def _projection_material(frame: dict, prefix: str) -> dict:
    value = _validate_projection(frame[f"{prefix}_context_projection"])
    encoded = encode_prime_context_v1(value)
    if encoded != _string(frame[f"{prefix}_context_json"]).encode():
        _fail()
    if hashlib.sha256(encoded).hexdigest() != _hex(frame[f"{prefix}_context_sha256"]):
        _fail()
    return value


def _real_source(projection: dict) -> bool:
    for message in projection["messages"]:
        if message["role"] in {"compactionSummary", "branchSummary", "bashExecution"}:
            if any(message.get(key) for key in ("summary", "command", "output")):
                return True
        for content in message.get("content", []):
            if content["type"] == "toolCall" or content.get("byte_length", 0) > 0:
                return True
            if any(
                isinstance(content.get(key), str) and content[key].strip()
                for key in ("text", "thinking")
            ):
                return True
    return False


def _validate_proposal(
    proposal: Mapping[str, object], launch: str, command: str
) -> dict:
    p = _record(proposal, _PROPOSAL)
    _identity(p, launch, command, "proposal")
    _identifier(p["first_kept_entry_id"])
    _identifier(p["covered_leaf_id"])
    pre = _projection_material(p, "pre")
    if _integer(p["pre_units"]) != count_rebuilt_context(pre):
        _fail()
    preparation = _record(p["preparation"], _PREPARATION)
    if _digest(preparation) != _hex(p["preparation_sha256"]):
        _fail()
    for key in ("first_kept_entry_id", "covered_leaf_id"):
        if preparation[key] != p[key]:
            _fail()
    sources = [
        _validate_projection(preparation[key])
        for key in ("messages_to_summarize", "turn_prefix_messages")
    ]
    if not any(_real_source(source) for source in sources):
        _fail()
    if any(source["system_prompt"] for source in sources):
        _fail()
    if type(preparation["is_split_turn"]) is not bool:
        _fail()
    if sources[1]["messages"] and not preparation["is_split_turn"]:
        _fail()
    expected_kind = "messages" if sources[0]["messages"] else "turn-prefix"
    if p["source_kind"] != expected_kind:
        _fail()
    for key in ("previous_summary", "custom_instructions"):
        if preparation[key] is not None:
            _string(preparation[key])
    retained = _validate_projection(preparation["retained_context_projection"])
    if retained["system_prompt"] != pre["system_prompt"]:
        _fail()
    if _integer(preparation["retained_message_count"]) < len(retained["messages"]):
        _fail()
    for key in ("main_summary_request", "turn_prefix_summary_request"):
        request = p[key]
        if key == "turn_prefix_summary_request" and request is None:
            if sources[1]["messages"]:
                _fail()
            continue
        parsed = _json(_string(request))
        if (
            encode_prime_context_v1(parsed).decode() != request
            or count_rebuilt_context(parsed) > 4096
        ):
            _fail()
    diagnostics = _record(p["private_diagnostics"], {"tokensBefore"})
    _integer(diagnostics["tokensBefore"])
    return p


@dataclass(frozen=True, slots=True)
class PrimeCompactionEvidence:
    command_nonce: str
    covered_leaf_id: str
    preparation_sha256: str
    source_kind: Literal["messages", "turn-prefix"]
    before_context_tokens: int
    after_context_tokens: int
    summary_sha256: str
    compact_entry_sha256: str
    usage_label: Literal["reservation-charged"] = "reservation-charged"


def validate_compaction_witness(
    proposal: Mapping[str, object],
    persisted: Mapping[str, object] | None = None,
    *,
    expected_launch_nonce: str = "",
    expected_command_nonce: str = "",
) -> PrimeCompactionEvidence:
    """Validate exact private material; a session enforces the authenticated order."""
    try:
        p = _validate_proposal(proposal, expected_launch_nonce, expected_command_nonce)
        s = _record(persisted, _PERSISTED)
        _identity(s, expected_launch_nonce, expected_command_nonce, "persisted")
        for key in (
            "authority_sha256",
            "first_kept_entry_id",
            "covered_leaf_id",
            "preparation_sha256",
        ):
            if s[key] != p[key]:
                _fail()
        entry = _record(s["compaction_entry"])
        required = {
            "type",
            "id",
            "parentId",
            "timestamp",
            "firstKeptEntryId",
            "summary",
            "tokensBefore",
        }
        if not required <= set(entry) or set(entry) - required - {
            "details",
            "fromHook",
            "customInstructions",
        }:
            _fail()
        if (
            entry["type"] != "compaction"
            or entry["parentId"] != p["covered_leaf_id"]
            or entry["firstKeptEntryId"] != p["first_kept_entry_id"]
            or entry.get("fromHook") is not False
            or entry["tokensBefore"] != p["private_diagnostics"]["tokensBefore"]
            or entry.get("customInstructions")
            != p["preparation"]["custom_instructions"]
        ):
            _fail()
        _identifier(entry["id"])
        _string(entry["timestamp"])
        if entry["id"] == p["covered_leaf_id"]:
            _fail()
        summary = _string(s["summary"])
        if not summary.strip() or summary != entry["summary"]:
            _fail()
        if hashlib.sha256(summary.encode()).hexdigest() != _hex(s["summary_sha256"]):
            _fail()
        if _digest(entry) != _hex(s["compaction_entry_sha256"]):
            _fail()
        post = _projection_material(s, "post")
        preparation = p["preparation"]
        retained = preparation["retained_context_projection"]
        expected_post = {
            **retained,
            "messages": [
                {
                    "role": "compactionSummary",
                    "summary": summary,
                    "retained_message_count": preparation["retained_message_count"],
                    "custom_instructions": preparation["custom_instructions"],
                },
                *retained["messages"],
            ],
        }
        after = count_rebuilt_context(post)
        if post != expected_post or after >= p["pre_units"]:
            _fail()
        return PrimeCompactionEvidence(
            expected_command_nonce,
            p["covered_leaf_id"],
            p["preparation_sha256"],
            p["source_kind"],
            p["pre_units"],
            after,
            s["summary_sha256"],
            s["compaction_entry_sha256"],
        )
    except (KeyError, TypeError, ValueError, RecursionError):
        _fail()


class PrimeContextWitnessSession:
    """One owned duplex socket. Admission and private durability are injected.

    ``arm`` completes before the owner sends the Pi compact RPC. The owner must
    also require that RPC's matching successful terminal; an ack alone is not
    a compaction outcome. Synchronous callbacks must be bounded local actions.
    """

    def __init__(
        self,
        channel: socket.socket,
        *,
        launch_nonce: str,
        mark_uncertain: Callable[[], object],
        timeout_seconds: float = 5.0,
        max_frame_bytes: int = _MAX_FRAME,
    ):
        if (
            type(channel) is not socket.socket
            or channel.family != socket.AF_UNIX
            or channel.type != socket.SOCK_STREAM
            or not callable(mark_uncertain)
            or type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 60
            or type(max_frame_bytes) is not int
            or not 128 <= max_frame_bytes <= _MAX_FRAME
        ):
            _fail()
        self._launch = _hex(launch_nonce)
        self._socket = channel
        channel.setblocking(False)
        self._mark_uncertain = mark_uncertain
        self._timeout = timeout_seconds
        self._cap = max_frame_bytes
        self._state = "idle"
        self._nonce = ""
        self._authority = ""
        self._seen: set[str] = set()
        self._proposal: dict | None = None
        self._uncertain = False
        self._active = False

    def __repr__(self) -> str:
        return "<PrimeContextWitnessSession redacted>"

    @property
    def uncertain(self) -> bool:
        return self._uncertain

    def close(self) -> None:
        if self._state == "approved":
            self._fence()
        else:
            self._close_transport()

    def _close_transport(self) -> None:
        self._socket.close()
        self._proposal = None
        self._launch = self._nonce = self._authority = ""
        self._state = "closed"

    def _fence(self) -> None:
        first = not self._uncertain
        self._uncertain = True
        self._close_transport()
        if first:
            try:
                self._mark_uncertain()
            except Exception:
                pass

    def _base(self, phase: str) -> dict:
        return {
            "protocol": PROTOCOL,
            "launch_nonce": self._launch,
            "command_nonce": self._nonce,
            "authority_sha256": self._authority,
            "phase": phase,
        }

    def _no_pending(self) -> None:
        try:
            self._socket.recv(1, socket.MSG_PEEK)
        except BlockingIOError:
            return
        _fail()

    async def _send(self, value: dict) -> None:
        raw = bytearray(_encode(value))
        try:
            if not 0 < len(raw) <= self._cap:
                _fail()
            self._no_pending()
            wire = bytearray(struct.pack("!I", len(raw))) + raw
            try:
                await asyncio.wait_for(
                    asyncio.get_running_loop().sock_sendall(self._socket, wire),
                    self._timeout,
                )
            finally:
                wire[:] = b"\x00" * len(wire)
        finally:
            raw[:] = b"\x00" * len(raw)

    async def _receive(self) -> dict:
        async def read_frame():
            async def exact(size):
                value = bytearray(size)
                offset = 0
                try:
                    while offset < size:
                        count = await asyncio.get_running_loop().sock_recv_into(
                            self._socket, memoryview(value)[offset:]
                        )
                        if not count:
                            _fail()
                        offset += count
                    return value
                except BaseException:
                    value[:] = b"\x00" * len(value)
                    raise

            header = await exact(4)
            try:
                size = struct.unpack("!I", header)[0]
            finally:
                header[:] = b"\x00" * len(header)
            if not 0 < size <= self._cap:
                _fail()
            raw = await exact(size)
            try:
                self._no_pending()
                value = _record(_json(raw.decode("utf-8")))
                _domain(value)
                return value
            finally:
                raw[:] = b"\x00" * len(raw)

        return await asyncio.wait_for(read_frame(), self._timeout)

    def _enter(self, state: str) -> None:
        if self._active or self._state != state:
            self._fence()
            _fail()
        self._active = True

    async def arm(self, *, command_nonce: str, authority_sha256: str) -> None:
        self._enter("idle")
        try:
            self._nonce, self._authority = _hex(command_nonce), _hex(authority_sha256)
            if self._nonce in self._seen:
                _fail()
            self._seen.add(self._nonce)
            await self._send(self._base("arm"))
            self._state = "armed"
        except BaseException:
            self._fence()
            _fail()
        finally:
            self._active = False

    async def receive_proposal_and_decide(
        self,
        *,
        price: ModelPrice,
        remaining_callbacks: int,
        deadline: float,
        reserve: Callable,
    ) -> bool:
        self._enter("armed")
        try:
            p = _validate_proposal(await self._receive(), self._launch, self._nonce)
            if p["authority_sha256"] != self._authority:
                _fail()
            approved = False
            try:
                if (
                    type(remaining_callbacks) is not int
                    or remaining_callbacks < 2
                    or type(deadline) not in {int, float}
                    or not math.isfinite(deadline)
                    or deadline <= time.monotonic()
                    or not callable(reserve)
                ):
                    _fail()
                caps = tuple(
                    len(_string(p[key]).encode()) if p[key] is not None else 0
                    for key in ("main_summary_request", "turn_prefix_summary_request")
                )
                quote = quote_compaction_reservation(
                    branch_input_caps=caps, branch_output_caps=(3276, 3276), price=price
                )
                result = reserve(quote)
                if inspect.isawaitable(result):
                    result = await asyncio.wait_for(
                        result, min(self._timeout, deadline - time.monotonic())
                    )
                if result is False or deadline <= time.monotonic():
                    _fail()
                approved = True
            except (ValueError, TypeError):
                approved = False
            # Once approval bytes may be sent, shutdown must retain the uncertain
            # obligation even before this coroutine resumes from its write.
            if approved:
                self._state = "approved"
            await self._send(
                {
                    **self._base("decision"),
                    "status": "approve" if approved else "reject",
                }
            )
            self._proposal = p if approved else None
            self._state = "approved" if approved else "idle"
            return approved
        except BaseException:
            self._fence()
            _fail()
        finally:
            self._active = False

    async def receive_persisted(self, *, persist: Callable) -> PrimeCompactionEvidence:
        self._enter("approved")
        try:
            persisted = await self._receive()
            evidence = validate_compaction_witness(
                self._proposal,
                persisted,
                expected_launch_nonce=self._launch,
                expected_command_nonce=self._nonce,
            )
            if not callable(persist):
                _fail()
            result = persist(persisted)
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(result, self._timeout)
            if result is False:
                _fail()
            await self._send(self._base("ack"))
            self._proposal = None
            self._state = "idle"
            return evidence
        except BaseException:
            self._fence()
            _fail()
        finally:
            self._active = False
