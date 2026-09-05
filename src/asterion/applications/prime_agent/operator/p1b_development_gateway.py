"""Private fixed-flow Python gateway for the P1-B Node development bridge."""

from __future__ import annotations
import asyncio
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final
from .development_gateway_transport import DevelopmentGatewayTransport, Hook, _absolute

_PROTOCOL: Final = "asterion.prime-p1-b-development-gateway/v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_SAFE_INTEGER: Final = 2**53 - 1
_WITNESS = frozenset(
    (
        "compact_called",
        "succeeded",
        "start_count",
        "end_count",
        "message_count_before",
        "message_count_after",
        "tokens_before",
        "first_kept_entry_id_sha256",
    )
)


class PrimeP1BDevelopmentGatewayError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P1-B development gateway is unavailable")


class PrimeP1BDevelopmentGateway(DevelopmentGatewayTransport):
    """A one-shot ``open → prompt1 → compact → prompt2 → close`` bridge."""

    __slots__ = ("_state",)

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
                / "packages/typescript/prime-gateway/dist/src/p1b-development-main.js",
                model_hook=model_hook,
                tool_hook=tool_hook,
                node_bin=node_bin,
                entrypoint=entrypoint,
                deadline_seconds=deadline_seconds,
            )
        except ValueError:
            raise PrimeP1BDevelopmentGatewayError() from None
        self._state = "new"

    def __repr__(self) -> str:
        return "PrimeP1BDevelopmentGateway(redacted)"

    async def open(
        self,
        *,
        run_id: str,
        session_id: str,
        generation: int,
        prime_source_root: str,
        workspace: str,
    ) -> None:
        self._event_loop = asyncio.get_running_loop()
        await asyncio.to_thread(
            self.open_sync,
            run_id=run_id,
            session_id=session_id,
            generation=generation,
            prime_source_root=prime_source_root,
            workspace=workspace,
        )

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
                raise PrimeP1BDevelopmentGatewayError() from None

    async def prompt(self, prompt: str) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        try:
            return await asyncio.to_thread(self.prompt_sync, prompt)
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self._abort_active))
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
                self._state = "active"
                frame = self._receive_until(
                    self._send(
                        "prompt", self._next_request_id("prompt"), {"prompt": prompt}
                    ),
                    {"command.result"},
                )
                result = _safe_prompt_result(frame["payload"].get("result"))
                self._state = "compact" if phase == "prompt1" else "close_ready"
                return result
            except BaseException:
                self._fail()
                raise PrimeP1BDevelopmentGatewayError() from None

    async def compact(self) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        try:
            return await asyncio.to_thread(self.compact_sync)
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self._abort_active))
            raise

    def compact_sync(self) -> Mapping[str, object]:
        with self._lock:
            try:
                if self._state != "compact":
                    raise ValueError()
                self._state = "active"
                frame = self._receive_until(
                    self._send("compact", self._next_request_id("compact"), {}),
                    {"command.result"},
                )
                result = _safe_witness(frame["payload"].get("result"))
                self._state = "prompt2"
                return result
            except BaseException:
                self._fail()
                raise PrimeP1BDevelopmentGatewayError() from None

    async def cancel(self) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        if self._state != "prompt1":
            await asyncio.shield(asyncio.to_thread(self._abort_active))
            raise PrimeP1BDevelopmentGatewayError()
        return await asyncio.to_thread(self.cancel_sync)

    def cancel_sync(self) -> Mapping[str, object]:
        with self._lock:
            try:
                if self._state != "prompt1":
                    raise ValueError()
                frame = self._receive_until(
                    self._send("cancel", self._next_request_id("cancel"), {}),
                    {"command.result"},
                )
                result = frame["payload"].get("result")
                if result != {"lifecycle": "cancelled"}:
                    raise ValueError()
                self._state = "cancelled"
                return {"lifecycle": "cancelled"}
            except BaseException:
                self._fail()
                raise PrimeP1BDevelopmentGatewayError() from None

    async def close(self) -> None:
        self._event_loop = asyncio.get_running_loop()
        await asyncio.to_thread(self.close_sync)

    def close_sync(self) -> None:
        with self._lock:
            if self._state == "closed":
                return
            try:
                if self._state not in {"close_ready", "cancelled"}:
                    raise ValueError()
                frame = self._receive_until(
                    self._send("close", self._next_request_id("close"), {}),
                    {"command.result"},
                )
                if frame["payload"] != {"result": {"lifecycle": "closed"}}:
                    raise ValueError()
                self._state = "closed"
                self._reap(graceful=True)
            except BaseException:
                self._fail()
                raise PrimeP1BDevelopmentGatewayError() from None

    async def aopen(self, **kwargs: object) -> None:
        await self.open(**kwargs)

    async def aprompt(self, prompt: str) -> Mapping[str, object]:
        return await self.prompt(prompt)

    async def acompact(self) -> Mapping[str, object]:
        return await self.compact()

    async def acancel(self) -> Mapping[str, object]:
        return await self.cancel()

    async def aclose(self) -> None:
        await self.close()

    def _fail(self) -> None:
        self._state = "failed"
        self._fail_transport()

    def _abort_active(self) -> None:
        self._fail()


def _safe_prompt_result(value: object) -> dict[str, object]:
    if type(value) is not dict or value.get("lifecycle") not in {
        "completed",
        "cancelled",
    }:
        raise ValueError()
    lifecycle = value["lifecycle"]
    # The child result is intentionally projected: no provider/model or payload data crosses this boundary.
    return {"lifecycle": lifecycle}


def _safe_witness(value: object) -> dict[str, object]:
    if (
        type(value) is not dict
        or set(value) != _WITNESS
        or value["compact_called"] is not True
        or value["succeeded"] is not True
        or value["start_count"] != 1
        or value["end_count"] != 1
    ):
        raise ValueError()
    if any(
        type(value[key]) is not int or not 0 <= value[key] <= _MAX_SAFE_INTEGER
        for key in (
            "message_count_before",
            "message_count_after",
            "tokens_before",
        )
    ):
        raise ValueError()
    digest = value["first_kept_entry_id_sha256"]
    if type(digest) is not str or not _DIGEST.fullmatch(digest):
        raise ValueError()
    return {key: value[key] for key in sorted(_WITNESS)}


__all__ = ("PrimeP1BDevelopmentGateway", "PrimeP1BDevelopmentGatewayError")
