"""Private inherited-FD gateway for the fixed P4 native reattachment proof."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Final

from .development_gateway_transport import (
    DevelopmentGatewayTransport,
    Hook,
    _absolute,
    _canonical_json,
    _valid_id,
)


_PROTOCOL: Final = "asterion.prime-p4-development-gateway/v1"
_DIGEST: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CANDIDATE_KEYS: Final = frozenset(
    (
        "active_session_id",
        "artifact_sha256",
        "cursor",
        "initial_attach_cursor",
        "session_id",
        "settled_model_callback_count",
        "settled_tool_callback_count",
        "transcript_sha256",
        "tree_sha256",
    )
)
_RECOVERY_KEYS: Final = frozenset(
    (
        "active_session_id",
        "from_cursor",
        "replay_status",
        "session_id",
        "snapshot_cursor",
        "to_cursor",
    )
)
_COMPACTION_KEYS: Final = frozenset(
    (
        "active_path_sha256",
        "compact_called",
        "end_count",
        "first_kept_entry_id_sha256",
        "new_entry_count",
        "start_count",
        "succeeded",
        "tokens_before",
    )
)


class PrimeP4DevelopmentGatewayError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P4 development gateway is unavailable")


class PrimeP4DevelopmentGateway(DevelopmentGatewayTransport):
    """One fixed ``open → prompt → recover → compact → prompt → close`` session."""

    __slots__ = (
        "_checkpoint",
        "_checkpoint_candidate",
        "_checkpoint_sha256",
        "_model_count",
        "_seen_tool_ids",
        "_state",
        "_tool_count",
    )

    def __init__(
        self,
        *,
        model_hook: Hook | None = None,
        tool_hook: Hook | None = None,
        node_bin: str | os.PathLike[str] | None = None,
        entrypoint: str | os.PathLike[str] | None = None,
        deadline_seconds: float = 30.0,
    ) -> None:
        try:
            super().__init__(
                protocol=_PROTOCOL,
                default_entrypoint=Path(__file__).resolve().parents[5]
                / "packages/typescript/prime-gateway/dist/src/p4-development-main.js",
                model_hook=model_hook,
                tool_hook=tool_hook,
                node_bin=node_bin,
                entrypoint=entrypoint,
                deadline_seconds=deadline_seconds,
            )
        except ValueError:
            raise PrimeP4DevelopmentGatewayError() from None
        self._state = "new"
        self._checkpoint: Path | None = None
        self._checkpoint_candidate: dict[str, object] | None = None
        self._checkpoint_sha256: str | None = None
        self._model_count = self._tool_count = 0
        self._seen_tool_ids: set[str] = set()

    def __repr__(self) -> str:
        return "PrimeP4DevelopmentGateway(redacted)"

    async def open(self, **kwargs: object) -> None:
        self._event_loop = asyncio.get_running_loop()
        try:
            await asyncio.to_thread(self.open_sync, **kwargs)
        except asyncio.CancelledError:
            await self._abort_shielded()
            raise

    def open_sync(
        self,
        *,
        run_id: str,
        session_id: str,
        generation: int,
        prime_source_root: str,
        workspace: str,
    ) -> None:
        with self._lock:
            try:
                if (
                    self._state != "new"
                    or not _absolute(prime_source_root)
                    or not _absolute(workspace)
                ):
                    raise ValueError()
                self._set_identity(
                    run_id=run_id, session_id=session_id, generation=generation
                )
                self._launch()
                frame = self._receive_until(
                    self._send(
                        "open",
                        "open-1",
                        {
                            "prime_source_root": prime_source_root,
                            "workspace": workspace,
                        },
                    ),
                    {"ready"},
                )
                if frame["payload"] != {}:
                    raise ValueError()
                self._state = "prompt1"
            except BaseException:
                self._fail()
                raise PrimeP4DevelopmentGatewayError() from None

    async def prompt(self, prompt: str) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        try:
            return await asyncio.to_thread(self.prompt_sync, prompt)
        except asyncio.CancelledError:
            await self._abort_shielded()
            raise

    def prompt_sync(self, prompt: str) -> Mapping[str, object]:
        with self._lock:
            try:
                if (
                    self._state not in {"prompt1", "prompt2"}
                    or type(prompt) is not str
                    or not prompt
                ):
                    raise ValueError()
                phase = self._state
                self._state = phase + "_active"
                frame = self._receive_until(
                    self._send(
                        "prompt", self._next_request_id("prompt"), {"prompt": prompt}
                    ),
                    {"command.result"},
                )
                result = frame["payload"].get("result")
                if phase == "prompt1":
                    candidate = _candidate(result)
                    if self._model_count != 2 or self._tool_count != 1:
                        raise ValueError()
                    self._persist_checkpoint(candidate)
                    self._state = "recover"
                    return {
                        "lifecycle": "completed",
                        "checkpoint_candidate": _public_candidate(candidate),
                    }
                result = _second_prompt(result)
                if self._model_count != 5 or self._tool_count != 2:
                    raise ValueError()
                self._state = "close_ready"
                return result
            except BaseException:
                self._fail()
                raise PrimeP4DevelopmentGatewayError() from None

    async def recover(self) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        try:
            return await asyncio.to_thread(self.recover_sync)
        except asyncio.CancelledError:
            await self._abort_shielded()
            raise

    def recover_sync(self) -> Mapping[str, object]:
        with self._lock:
            try:
                if (
                    self._state != "recover"
                    or self._checkpoint_candidate is None
                    or self._checkpoint_sha256 is None
                ):
                    raise ValueError()
                candidate = self._read_checkpoint()
                if candidate != self._checkpoint_candidate:
                    raise ValueError()
                self._state = "recover_active"
                frame = self._receive_until(
                    self._send(
                        "recover",
                        self._next_request_id("recover"),
                        {
                            "checkpoint_candidate": candidate,
                            "checkpoint_sha256": self._checkpoint_sha256,
                        },
                    ),
                    {"command.result"},
                )
                result = _recovery(frame["payload"].get("result"), candidate)
                self._state = "compact"
                return result
            except BaseException:
                self._fail()
                raise PrimeP4DevelopmentGatewayError() from None

    async def compact(self) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        try:
            return await asyncio.to_thread(self.compact_sync)
        except asyncio.CancelledError:
            await self._abort_shielded()
            raise

    def compact_sync(self) -> Mapping[str, object]:
        with self._lock:
            try:
                if self._state != "compact":
                    raise ValueError()
                self._state = "compact_active"
                frame = self._receive_until(
                    self._send("compact", self._next_request_id("compact"), {}),
                    {"command.result"},
                )
                result = _compaction(frame["payload"].get("result"))
                if self._model_count != 3 or self._tool_count != 1:
                    raise ValueError()
                self._state = "prompt2"
                return result
            except BaseException:
                self._fail()
                raise PrimeP4DevelopmentGatewayError() from None

    async def cancel(self) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        try:
            return await asyncio.to_thread(self.cancel_sync)
        except asyncio.CancelledError:
            await self._abort_shielded()
            raise

    def cancel_sync(self) -> Mapping[str, object]:
        with self._lock:
            try:
                if self._state not in {
                    "prompt1",
                    "prompt1_active",
                    "recover",
                    "recover_active",
                    "compact",
                    "compact_active",
                    "prompt2",
                    "prompt2_active",
                }:
                    raise ValueError()
                self._state = "cancel_active"
                frame = self._receive_until(
                    self._send("cancel", self._next_request_id("cancel"), {}),
                    {"command.result"},
                )
                if frame["payload"] != {"result": {"lifecycle": "cancelled"}}:
                    raise ValueError()
                self._state = "cancelled"
                self._cleanup_checkpoint()
                self._fail_transport()
                return {"lifecycle": "cancelled"}
            except BaseException:
                self._fail()
                raise PrimeP4DevelopmentGatewayError() from None

    async def close(self) -> None:
        self._event_loop = asyncio.get_running_loop()
        await asyncio.to_thread(self.close_sync)

    def close_sync(self) -> None:
        with self._lock:
            if self._state == "closed":
                return
            if self._state == "cancelled":
                self._state = "closed"
                return
            try:
                if self._state != "close_ready":
                    raise ValueError()
                frame = self._receive_until(
                    self._send("close", self._next_request_id("close"), {}),
                    {"command.result"},
                )
                _close_result(
                    frame["payload"].get("result"), self._model_count, self._tool_count
                )
                self._state = "closed"
                self._cleanup_checkpoint()
                self._reap(graceful=True)
            except BaseException:
                self._fail()
                raise PrimeP4DevelopmentGatewayError() from None

    async def aopen(self, **kwargs: object) -> None:
        await self.open(**kwargs)

    async def aprompt(self, prompt: str) -> Mapping[str, object]:
        return await self.prompt(prompt)

    async def arecover(self) -> Mapping[str, object]:
        return await self.recover()

    async def acompact(self) -> Mapping[str, object]:
        return await self.compact()

    async def acancel(self) -> Mapping[str, object]:
        return await self.cancel()

    async def aclose(self) -> None:
        await self.close()

    def bind(self, *, model_hook: Hook, tool_hook: Hook) -> None:
        """Inject the two operator-owned callback ports before opening."""
        if (
            self._state != "new"
            or not callable(model_hook)
            or not callable(tool_hook)
            or self._model_hook is not None
            or self._tool_hook is not None
        ):
            raise PrimeP4DevelopmentGatewayError()
        self._model_hook = model_hook
        self._tool_hook = tool_hook

    def _dispatch_callback(
        self,
        response_kind: str,
        request_id: object,
        key: str,
        hook: Hook | None,
        payload: object,
    ) -> None:
        if response_kind == "model.response":
            if (
                self._state
                not in {"prompt1_active", "compact_active", "prompt2_active"}
                or self._model_count >= 5
            ):
                raise PrimeP4DevelopmentGatewayError()
            self._model_count += 1
        elif response_kind == "tool.response":
            if (
                self._state
                not in {"prompt1_active", "compact_active", "prompt2_active"}
                or self._tool_count >= 2
                or type(payload) is not dict
            ):
                raise PrimeP4DevelopmentGatewayError()
            tool_id = payload.get("tool_call_id")
            if not _valid_id(tool_id) or tool_id in self._seen_tool_ids:
                raise PrimeP4DevelopmentGatewayError()
            self._seen_tool_ids.add(tool_id)
            self._tool_count += 1
        else:
            raise PrimeP4DevelopmentGatewayError()
        super()._dispatch_callback(response_kind, request_id, key, hook, payload)

    def _persist_checkpoint(self, candidate: dict[str, object]) -> None:
        raw = _canonical_json(candidate).encode("utf-8")
        descriptor, name = tempfile.mkstemp(prefix="asterion-p4-checkpoint-")
        path = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, raw)
        finally:
            os.close(descriptor)
        self._checkpoint = path
        self._checkpoint_candidate = candidate
        self._checkpoint_sha256 = "sha256:" + sha256(raw).hexdigest()
        if self._read_checkpoint() != candidate:
            raise ValueError()

    def _read_checkpoint(self) -> dict[str, object]:
        path = self._checkpoint
        if path is None:
            raise ValueError()
        info = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
        ):
            raise ValueError()
        raw = path.read_bytes()
        if self._checkpoint_sha256 != "sha256:" + sha256(raw).hexdigest():
            raise ValueError()
        import json

        value = json.loads(raw.decode("utf-8"))
        if type(value) is not dict or _canonical_json(value).encode("utf-8") != raw:
            raise ValueError()
        return _candidate({"checkpoint_candidate": value})

    def _cleanup_checkpoint(self) -> None:
        path, self._checkpoint = self._checkpoint, None
        self._checkpoint_candidate = self._checkpoint_sha256 = None
        if path is not None:
            try:
                path.unlink()
            except OSError:
                pass

    def _fail(self) -> None:
        self._state = "failed"
        self._cleanup_checkpoint()
        self._fail_transport()

    def _abort_active(self) -> None:
        self._fail()

    async def _abort_shielded(self) -> None:
        cleanup = asyncio.create_task(asyncio.to_thread(self._abort_active))
        interrupted = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                interrupted = True
        cleanup.result()
        if interrupted:
            raise asyncio.CancelledError


def _digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _cursor(value: object) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != {"generation", "sequence"}
        or not _valid_id(value.get("generation"))
        or type(value.get("sequence")) is not int
        or value["sequence"] < 0
    ):
        raise ValueError()
    return {"generation": value["generation"], "sequence": value["sequence"]}


def _candidate(value: object) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != {"checkpoint_candidate"}
        or type(value["checkpoint_candidate"]) is not dict
    ):
        raise ValueError()
    candidate = value["checkpoint_candidate"]
    initial = _cursor(candidate.get("initial_attach_cursor"))
    cursor = _cursor(candidate.get("cursor"))
    if (
        set(candidate) != _CANDIDATE_KEYS
        or not _valid_id(candidate.get("active_session_id"))
        or not _valid_id(candidate.get("session_id"))
        or any(
            not _digest(candidate.get(key))
            for key in ("transcript_sha256", "tree_sha256", "artifact_sha256")
        )
        or candidate.get("settled_model_callback_count") != 2
        or candidate.get("settled_tool_callback_count") != 1
        or initial["generation"] != cursor["generation"]
        or initial["sequence"] >= cursor["sequence"]
    ):
        raise ValueError()
    return {
        key: (
            _cursor(candidate[key])
            if key in {"cursor", "initial_attach_cursor"}
            else candidate[key]
        )
        for key in sorted(_CANDIDATE_KEYS)
    }


def _public_candidate(candidate: Mapping[str, object]) -> dict[str, object]:
    return {
        key: candidate[key]
        for key in (
            "active_session_id",
            "session_id",
            "initial_attach_cursor",
            "cursor",
            "transcript_sha256",
            "tree_sha256",
            "artifact_sha256",
        )
    }


def _recovery(value: object, candidate: Mapping[str, object]) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != _RECOVERY_KEYS
        or value.get("replay_status") != "complete"
        or value.get("active_session_id") != candidate["active_session_id"]
        or value.get("session_id") != candidate["session_id"]
    ):
        raise ValueError()
    cursor = candidate["cursor"]
    values = {
        key: _cursor(value[key])
        for key in ("from_cursor", "to_cursor", "snapshot_cursor")
    }
    if any(item != cursor for item in values.values()):
        raise ValueError()
    return {
        "active_session_id": candidate["active_session_id"],
        "session_id": candidate["session_id"],
        "replay_status": "complete",
        **values,
    }


def _compaction(value: object) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != _COMPACTION_KEYS
        or value.get("compact_called") is not True
        or value.get("succeeded") is not True
        or value.get("start_count") != 1
        or value.get("end_count") != 1
        or any(
            type(value.get(key)) is not int or value[key] < 0
            for key in ("new_entry_count", "tokens_before")
        )
        or not _digest(value.get("active_path_sha256"))
        or not _digest(value.get("first_kept_entry_id_sha256"))
    ):
        raise ValueError()
    return {key: value[key] for key in sorted(_COMPACTION_KEYS)}


def _second_prompt(value: object) -> dict[str, object]:
    if value != {
        "lifecycle": "completed",
        "model_callback_count": 5,
        "tool_callback_count": 2,
    }:
        raise ValueError()
    return dict(value)


def _close_result(value: object, models: int, tools: int) -> None:
    if (
        type(value) is not dict
        or set(value)
        != {
            "lifecycle",
            "model_callback_count",
            "tool_callback_count",
            "active_session_id_sha256",
            "session_id_sha256",
            "cursor_sha256",
        }
        or value.get("lifecycle") != "closed"
        or value.get("model_callback_count") != models
        or value.get("tool_callback_count") != tools
        or any(
            not _digest(value.get(key))
            for key in (
                "active_session_id_sha256",
                "session_id_sha256",
                "cursor_sha256",
            )
        )
    ):
        raise ValueError()


__all__ = ("PrimeP4DevelopmentGateway", "PrimeP4DevelopmentGatewayError")
