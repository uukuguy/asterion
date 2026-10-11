"""Private, authenticated observations around Pi's built-in compaction.

Only the frozen evidence record is public-safe. Projection bodies, proposals,
summary text, socket identity, and diagnostics belong to the private backend.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
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
from typing import Literal, NoReturn, cast

from .compaction_budget import ModelPrice, PrimeCompactionPolicy, quote_compaction_reservation
from asterion.services.diagnostics import LimitDiagnostic, ResourceLimitExceeded
from .summarization import (
    MATERIAL_KEYS,
    MATERIAL_VERSION,
    build_summarization_material,
)


PROTOCOL = "asterion.prime-context-witness/v1"
PROJECTION = "asterion.prime-context-projection/v1"
_ERROR = "invalid Prime context witness"
_MAX_INTEGER = (1 << 53) - 1


def _input_token_ceiling(request: str) -> int:
    """Estimate request tokens from UTF-8 bytes; this is not a native input bound.

    The inherited bytes/4 convention supports reservation arithmetic only. It
    cannot certify actual provider token usage or request-bound authorization.
    """
    return (len(request.encode("utf-8")) + 3) // 4
_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_BASE = {"protocol", "launch_nonce", "command_nonce", "authority_sha256", "phase"}
# Each template must carry exactly one marker of its own and no other template's
# marker, so a substitution can never rescan private text it just inserted.
_MARKERS = {
    "conversation_block": ("{conversation}",),
    "previous_summary_block": ("{previous_summary}",),
    "user_instructions_template": ("{instructions}",),
}
_OTHER_MARKERS = ("{conversation}", "{previous_summary}", "{instructions}")
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


def _validate_policy(policy: PrimeCompactionPolicy, config_source: str) -> None:
    if (type(policy) is not PrimeCompactionPolicy or type(config_source) is not str
            or config_source not in {"framework-default", "application", "operator", "authority"}):
        _fail()


def _limit(code: str, observed: int, cap: int, source: str, *,
           phase: str = "admission", action: str = "rejected") -> NoReturn:
    raise ResourceLimitExceeded(LimitDiagnostic(
        code, phase, action, observed, cap, "bytes", "exact", source))


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
            if not math.isfinite(float(cast(int | Decimal, value))):
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
        elif role == "system":
            _record(message, {"role", "content", "sections", "tools_added_json", "tools_removed_json"})
            _content(message["content"], {"text"})
            if type(message["sections"]) is not list:
                _fail()
            names = set()
            for raw_section in message["sections"]:
                section = _record(raw_section, {"name", "value"})
                name = _string(section["name"])
                if name in names:
                    _fail()
                names.add(name)
                if section["value"] is not None:
                    _string(section["value"])
            for key in ("tools_added_json", "tools_removed_json"):
                tools = _json(_string(message[key]), arguments=True)
                if type(tools) is not list:
                    _fail()
                for tool in tools:
                    _string(_record(tool).get("name"))
                _validate_argument(tools)
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


def _validate_summarization(value: object, *,
    policy: PrimeCompactionPolicy = PrimeCompactionPolicy(),
    config_source: str = "framework-default",
) -> dict:
    """Validate inherited frozen templates, not proof of native request parity."""
    _validate_policy(policy, config_source)

    material = _record(value, set(MATERIAL_KEYS))
    _domain(material)
    if material["version"] != MATERIAL_VERSION:
        _fail()
    for key in MATERIAL_KEYS:
        _string(material[key])
        if not material[key]:
            _fail()
    encoded = _encode(material)
    if len(encoded) > policy.max_material_bytes:
        _limit("summarization-material-limit", len(encoded), policy.max_material_bytes, config_source)
    for key in MATERIAL_KEYS:
        text = material[key]
        expected = _MARKERS.get(key, ())
        for marker in _OTHER_MARKERS:
            present = marker in text
            if present != (marker in expected):
                _fail()
            if present and text.count(marker) != 1:
                _fail()
    return material


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
        if message["role"] == "system":
            continue
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
    proposal: Mapping[str, object], launch: str, command: str, *,
    policy: PrimeCompactionPolicy = PrimeCompactionPolicy(),
    config_source: str = "framework-default",
) -> dict:
    _validate_policy(policy, config_source)
    encoded_size = len(_encode(proposal))
    if encoded_size > policy.max_frame_bytes:
        _limit("witness-frame-limit", encoded_size, policy.max_frame_bytes, config_source)
    p = _record(proposal, _PROPOSAL)
    _identity(p, launch, command, "proposal")
    _identifier(p["first_kept_entry_id"])
    _identifier(p["covered_leaf_id"])
    pre = _projection_material(p, "pre")
    if _integer(p["pre_units"]) != count_rebuilt_context(pre):
        _fail()
    preparation = _record(p["preparation"])
    _record(preparation, _PREPARATION | ({"system_context_projection"}
        if "system_context_projection" in preparation else set()))
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
    has_system = any(message["role"] == "system" for message in pre["messages"])
    if has_system != ("system_context_projection" in preparation):
        _fail()
    if has_system:
        system = _validate_projection(preparation["system_context_projection"])
        if (system["system_prompt"] or len(system["messages"]) != 1
                or system["messages"][0]["role"] != "system"):
            _fail()
    # Pi states retention by `firstKeptEntryId` and never emits a retained
    # count, so a witness proposal declares null. The bound applies only when a
    # producer actually supplies one (the takeover shape, D-2026-09-16-01).
    declared_retained = preparation["retained_message_count"]
    if declared_retained is not None and _integer(declared_retained) < len(
        retained["messages"]
    ):
        _fail()
    for key in ("main_summary_request", "turn_prefix_summary_request"):
        request = p[key]
        if key == "turn_prefix_summary_request" and request is None:
            if sources[1]["messages"]:
                _fail()
            continue
        parsed = _json(_string(request))
        # The request embeds the serialized conversation being summarized, so a
        # real one exceeds any small constant. The transport frame cap is the
        # only non-arbitrary limit; the channel write enforces the total.
        if encode_prime_context_v1(parsed).decode() != request:
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
    policy: PrimeCompactionPolicy = PrimeCompactionPolicy(),
    config_source: str = "framework-default",
) -> PrimeCompactionEvidence:
    """Validate exact private material; a session enforces the authenticated order."""
    try:
        p = _validate_proposal(proposal, expected_launch_nonce, expected_command_nonce,
            policy=policy, config_source=config_source)
        s = _record(persisted, _PERSISTED)
        persisted_size = len(_encode(s))
        if persisted_size > policy.max_frame_bytes:
            _limit("witness-frame-limit", persisted_size, policy.max_frame_bytes,
                config_source, phase="settlement", action="recovery-required")
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
        # Pi's compaction entry is exactly this shape at both of its construction
        # sites; `customInstructions` is not among its fields. Pi carries the
        # custom instructions on the `before_compaction` hook event, never on the
        # entry it persists, so requiring them here could never be satisfied.
        if not required <= set(entry) or set(entry) - required - {
            "details",
            "fromHook",
            "systemMessage",
        }:
            _fail()
        if (
            entry["type"] != "compaction"
            or entry["parentId"] != p["covered_leaf_id"]
            or entry["firstKeptEntryId"] != p["first_kept_entry_id"]
            or entry.get("fromHook") is not False
            or entry["tokensBefore"] != p["private_diagnostics"]["tokensBefore"]
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
        system_messages = preparation.get("system_context_projection", {}).get("messages", [])
        if system_messages:
            if entry.get("systemMessage") != system_messages[0]:
                _fail()
        elif "systemMessage" in entry:
            _fail()
        expected_post = {
            **retained,
            "messages": [
                *system_messages,
                {
                    "role": "compactionSummary",
                    "summary": summary,
                    "retained_message_count": preparation["retained_message_count"],
                    # Pi's `createCompactionSummaryMessage` emits only role,
                    # summary, tokensBefore and timestamp, so the post-context
                    # projection of the persisted entry carries no custom
                    # instructions. The declared value is summarization material
                    # (`preparation["custom_instructions"]`), not context state.
                    "custom_instructions": None,
                },
                *retained["messages"],
            ],
        }
        # The equality above already binds the rebuild to the retained tail plus
        # the summary, so the only free quantity is the summary's own size, which
        # Pi chooses. A byte bound on it refused legitimate compactions: a
        # markdown-heavy summary costs more JSON bytes per token than the
        # conversation it replaces. `after` is still reported as evidence.
        after = count_rebuilt_context(post)
        if post != expected_post:
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
    except ResourceLimitExceeded:
        raise
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
        policy: PrimeCompactionPolicy = PrimeCompactionPolicy(),
        config_source: str = "framework-default",
        max_frame_bytes: int | None = None,
    ):
        _validate_policy(policy, config_source)
        if max_frame_bytes is not None:
            if type(max_frame_bytes) is not int:
                _fail()
            if policy != PrimeCompactionPolicy() and max_frame_bytes != policy.max_frame_bytes:
                _fail()
            try:
                policy = replace(policy, max_frame_bytes=max_frame_bytes)
            except ValueError:
                _fail()
        if (
            type(channel) is not socket.socket
            or channel.family != socket.AF_UNIX
            or channel.type != socket.SOCK_STREAM
            or not callable(mark_uncertain)
            or type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 60
        ):
            _fail()
        self._launch = _hex(launch_nonce)
        self._socket = channel
        channel.setblocking(False)
        self._mark_uncertain = mark_uncertain
        self._timeout = timeout_seconds
        self._policy, self._config_source = policy, config_source
        self._cap = policy.max_frame_bytes
        self._state = "idle"
        self._nonce = ""
        self._authority = ""
        self._seen: set[str] = set()
        self._proposal: dict | None = None
        self._uncertain = False
        self._active = False
        self._deadline: float | None = None

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

    def _validate_arm_capacity(self) -> None:
        # Establish complete arm admission before the owner activates any process.
        arm = {"protocol": PROTOCOL, "launch_nonce": self._launch,
            "command_nonce": self._launch, "authority_sha256": self._launch,
            "phase": "arm", "compaction_policy": self._policy_payload(),
            "summarization": _validate_summarization(build_summarization_material(),
                policy=self._policy, config_source=self._config_source)}
        self._check_frame_size(len(_encode(arm)))

    def _policy_payload(self) -> dict:
        return {**asdict(self._policy), "config_source": self._config_source}

    def _check_frame_size(self, size: int) -> None:
        if size <= 0:
            _fail()
        if size > self._cap:
            _limit("witness-frame-limit", size, self._cap, self._config_source,
                phase="settlement" if self._state == "approved" else "admission",
                action="recovery-required" if self._state == "approved" else "rejected")

    def _peer_limit(self, value: dict) -> None:
        if value.get("phase") != "limit":
            return
        frame = _record(value, _BASE | {"limit_diagnostic"})
        _identity(frame, self._launch, self._nonce, "limit")
        if frame["authority_sha256"] != self._authority or not self._nonce:
            _fail()
        raw = _record(frame["limit_diagnostic"], {
            "limit_code", "phase", "action", "observed", "limit", "unit",
            "measurement", "config_source"})
        try:
            diagnostic = LimitDiagnostic(**raw)
        except (TypeError, ValueError):
            _fail()
        # This peer only measures its injected transport and template capacities.
        limits = {"witness-frame-limit": self._cap,
            "summarization-material-limit": self._policy.max_material_bytes}
        if (diagnostic.limit_code not in limits
                or diagnostic.limit != limits[diagnostic.limit_code]
                or diagnostic.config_source != self._config_source
                or diagnostic.measurement != "exact" or diagnostic.observed is None
                or diagnostic.observed <= diagnostic.limit
                or (diagnostic.phase, diagnostic.action) != (
                    ("settlement", "recovery-required") if self._state == "approved"
                    else ("admission", "rejected"))):
            _fail()
        raise ResourceLimitExceeded(diagnostic)

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

    def _wait_seconds(self) -> float:
        if self._deadline is None:
            return self._timeout
        return min(self._timeout, max(0.0, self._deadline - time.monotonic()))

    async def _send(self, value: dict) -> None:
        encoded = _encode(value)
        self._check_frame_size(len(encoded))
        raw = bytearray(encoded)
        try:
            self._no_pending()
            wire = bytearray(struct.pack("!I", len(raw))) + raw
            try:

                async def send_frame():
                    if self._wait_seconds() <= 0:
                        _fail()
                    await asyncio.get_running_loop().sock_sendall(self._socket, wire)

                await asyncio.wait_for(
                    send_frame(),
                    self._wait_seconds(),
                )
                if self._wait_seconds() <= 0:
                    _fail()
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
            self._check_frame_size(size)
            raw = await exact(size)
            try:
                self._no_pending()
                value = _record(_json(raw.decode("utf-8")))
                if _encode(value) != raw:
                    _fail()
                self._peer_limit(value)
                return value
            finally:
                raw[:] = b"\x00" * len(raw)

        value = await asyncio.wait_for(read_frame(), self._wait_seconds())
        if self._wait_seconds() <= 0:
            _fail()
        return value

    def _enter(self, state: str) -> None:
        if self._active or self._state != state:
            self._fence()
            _fail()
        self._active = True

    async def arm(
        self,
        *,
        command_nonce: str,
        authority_sha256: str,
        deadline: float | None = None,
    ) -> None:
        """Bind an optional absolute deadline through the final persisted ack."""
        self._enter("idle")
        try:
            if deadline is not None and (
                type(deadline) not in {int, float} or not math.isfinite(deadline)
            ):
                _fail()
            self._deadline = deadline
            self._nonce, self._authority = _hex(command_nonce), _hex(authority_sha256)
            if self._nonce in self._seen:
                _fail()
            self._seen.add(self._nonce)
            await self._send(
                {
                    **self._base("arm"),
                    "compaction_policy": self._policy_payload(),
                    "summarization": _validate_summarization(
                        build_summarization_material(), policy=self._policy,
                        config_source=self._config_source
                    ),
                }
            )
            self._state = "armed"
        except ResourceLimitExceeded:
            self._fence()
            raise
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
            p = _validate_proposal(await self._receive(), self._launch, self._nonce,
                policy=self._policy, config_source=self._config_source)
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
                    _input_token_ceiling(_string(p[key])) if p[key] is not None else 0
                    for key in ("main_summary_request", "turn_prefix_summary_request")
                )
                quote = quote_compaction_reservation(
                    branch_input_caps=cast(tuple[int, int], caps),
                    branch_output_caps=(3276, 3276),
                    price=price, policy=self._policy, config_source=self._config_source,
                )
                result = reserve(quote)
                if inspect.isawaitable(result):
                    result = await asyncio.wait_for(
                        result,
                        min(
                            self._wait_seconds(), max(0.0, deadline - time.monotonic())
                        ),
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
        except ResourceLimitExceeded:
            self._fence()
            raise
        except BaseException:
            self._fence()
            _fail()
        finally:
            self._active = False

    async def receive_persisted(
        self, *, persist: Callable[[bytes], object]
    ) -> PrimeCompactionEvidence:
        """Persist the exact validated canonical private frame as immutable bytes.

        The checkpoint owner must durably store these bytes before returning.
        Retaining the bytes is safe; decoded mutable dictionaries never cross
        this callback boundary. Evidence is derived from this same frame.
        """
        self._enter("approved")
        try:
            persisted = await self._receive()
            evidence = validate_compaction_witness(
                cast(Mapping[str, object], self._proposal),
                persisted,
                expected_launch_nonce=self._launch,
                expected_command_nonce=self._nonce,
                policy=self._policy, config_source=self._config_source,
            )
            if not callable(persist):
                _fail()
            if self._wait_seconds() <= 0:
                _fail()
            result = persist(_encode(persisted))
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(result, self._wait_seconds())
            if result is False or self._wait_seconds() <= 0:
                _fail()
            await self._send(self._base("ack"))
            self._proposal = None
            self._state = "idle"
            return evidence
        except ResourceLimitExceeded:
            self._fence()
            raise
        except BaseException:
            self._fence()
            _fail()
        finally:
            self._active = False
