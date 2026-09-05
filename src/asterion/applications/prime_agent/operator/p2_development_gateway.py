"""Private, bounded Python transport for the P1 development Node bridge."""

from __future__ import annotations
import asyncio
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final
from .development_gateway_transport import DevelopmentGatewayTransport, Hook, _absolute

_PROTOCOL: Final = "asterion.prime-p2-development-gateway/v1"


class PrimeP2DevelopmentGatewayError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P2 development gateway is unavailable")


class PrimeP2DevelopmentGateway(DevelopmentGatewayTransport):
    """One private inherited-FD bridge session with synchronous and async APIs."""

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
                / "packages/typescript/prime-gateway/dist/src/p2-development-main.js",
                model_hook=model_hook,
                tool_hook=tool_hook,
                node_bin=node_bin,
                entrypoint=entrypoint,
                deadline_seconds=deadline_seconds,
            )
        except ValueError:
            raise PrimeP2DevelopmentGatewayError() from None
        self._state = "new"

    def __repr__(self) -> str:
        return "PrimeP2DevelopmentGateway(redacted)"

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
        try:
            await asyncio.to_thread(
                self.open_sync,
                run_id=run_id,
                session_id=session_id,
                generation=generation,
                prime_source_root=prime_source_root,
                workspace=workspace,
            )
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self._abort_active_prompt))
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
                self._state = "open"
            except BaseException:
                self._fail()
                raise PrimeP2DevelopmentGatewayError() from None

    async def prompt(self, prompt: str) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        try:
            return await asyncio.to_thread(self.prompt_sync, prompt)
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self._abort_active_prompt))
            raise

    def prompt_sync(self, prompt: str) -> Mapping[str, object]:
        with self._lock:
            try:
                if self._state != "open" or type(prompt) is not str or not prompt:
                    raise ValueError()
                self._state = "prompt"
                frame = self._receive_until(
                    self._send(
                        "prompt", self._next_request_id("prompt"), {"prompt": prompt}
                    ),
                    {"command.result"},
                )
                result = frame["payload"].get("result")
                if type(result) is not dict:
                    raise ValueError()
                self._state = "open"
                return result
            except BaseException:
                self._fail()
                raise PrimeP2DevelopmentGatewayError() from None

    async def cancel(self) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        if self._state == "prompt":
            await asyncio.shield(asyncio.to_thread(self._abort_active_prompt))
            raise PrimeP2DevelopmentGatewayError()
        return await asyncio.to_thread(self.cancel_sync)

    def cancel_sync(self) -> Mapping[str, object]:
        with self._lock:
            try:
                if self._state != "open":
                    raise ValueError()
                frame = self._receive_until(
                    self._send("cancel", self._next_request_id("cancel"), {}),
                    {"command.result"},
                )
                result = frame["payload"].get("result")
                if type(result) is not dict or result.get("lifecycle") != "cancelled":
                    raise ValueError()
                self._state = "cancelled"
                return result
            except BaseException:
                self._fail()
                raise PrimeP2DevelopmentGatewayError() from None

    async def close(self) -> None:
        self._event_loop = asyncio.get_running_loop()
        await asyncio.to_thread(self.close_sync)

    def close_sync(self) -> None:
        with self._lock:
            if self._state in {"closed", "failed"}:
                return
            try:
                if self._state not in {"open", "cancelled"}:
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
                raise PrimeP2DevelopmentGatewayError() from None

    async def aopen(self, **kwargs: object) -> None:
        await self.open(**kwargs)

    async def aprompt(self, prompt: str) -> Mapping[str, object]:
        return await self.prompt(prompt)

    async def acancel(self) -> Mapping[str, object]:
        return await self.cancel()

    async def aclose(self) -> None:
        await self.close()

    def _fail(self) -> None:
        self._state = "failed"
        self._fail_transport()

    def _abort_active_prompt(self) -> None:
        self._fail()


__all__ = ("PrimeP2DevelopmentGateway", "PrimeP2DevelopmentGatewayError")
