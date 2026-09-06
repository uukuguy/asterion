"""Private, bounded Python transport for the P1 development Node bridge."""

from __future__ import annotations
import asyncio
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final
from types import MappingProxyType
from .development_gateway_transport import DevelopmentGatewayTransport, Hook, _absolute

_PROTOCOL: Final = "asterion.prime-p7-development-gateway/v1"


class PrimeP7DevelopmentGatewayError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P7 development gateway is unavailable")


class PrimeP7DevelopmentGateway(DevelopmentGatewayTransport):
    """One private inherited-FD bridge session with synchronous and async APIs."""

    __slots__ = ("_state", "_prompts", "_terminal_witness")

    def __init__(
        self,
        *,
        model_hook: Hook | None = None,
        tool_hook: Hook | None = None,
        node_bin: str | os.PathLike[str] | None = None,
        entrypoint: str | os.PathLike[str] | None = None,
        deadline_seconds: float = 300.0,
    ) -> None:
        try:
            super().__init__(
                protocol=_PROTOCOL,
                default_entrypoint=Path(__file__).resolve().parents[5]
                / "packages/typescript/prime-gateway/dist/src/p7-development-main.js",
                model_hook=model_hook,
                tool_hook=tool_hook,
                node_bin=node_bin,
                entrypoint=entrypoint,
                deadline_seconds=deadline_seconds,
                nested_command_kinds=frozenset(),
            )
        except ValueError:
            raise PrimeP7DevelopmentGatewayError() from None
        self._state = "new"
        self._prompts = 0
        self._terminal_witness: Mapping[str, object] | None = None

    def __repr__(self) -> str:
        return "PrimeP7DevelopmentGateway(redacted)"

    def bind(self, *, model_hook: Hook, tool_hook: Hook) -> None:
        if (
            self._state != "new"
            or not callable(model_hook)
            or not callable(tool_hook)
            or self._model_hook is not None
            or self._tool_hook is not None
        ):
            raise PrimeP7DevelopmentGatewayError()
        self._model_hook, self._tool_hook = model_hook, tool_hook

    async def open(
        self,
        *,
        run_id: str,
        session_id: str,
        generation: int,
        prime_source_root: str = "/workspace",
        workspace: str = "/workspace",
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
                raise PrimeP7DevelopmentGatewayError() from None

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
                normalized, witness = _normalize_result(result, self._prompts + 1)
                self._prompts += 1
                self._terminal_witness = witness
                self._state = "open"
                return normalized
            except BaseException:
                self._fail()
                raise PrimeP7DevelopmentGatewayError() from None

    async def cancel(self) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        if self._state == "prompt":
            await asyncio.shield(asyncio.to_thread(self._abort_active_prompt))
            raise PrimeP7DevelopmentGatewayError()
        return await asyncio.to_thread(self.cancel_sync)

    async def feedback(self, feedback: str) -> None:
        self._event_loop = asyncio.get_running_loop()
        await asyncio.to_thread(self.feedback_sync, feedback)

    def feedback_sync(self, feedback: str) -> None:
        with self._lock:
            try:
                if self._state != "open" or type(feedback) is not str or not feedback:
                    raise ValueError()
                frame = self._receive_until(
                    self._send(
                        "feedback", self._next_request_id("feedback"), {"feedback": feedback}
                    ),
                    {"command.result"},
                )
                if frame["payload"] != {"result": {}}:
                    raise ValueError()
            except BaseException:
                self._fail()
                raise PrimeP7DevelopmentGatewayError() from None

    def terminal_witness(self) -> Mapping[str, object]:
        if self._prompts != 3 or self._terminal_witness is None or self._state not in {"open", "closed"}:
            raise PrimeP7DevelopmentGatewayError()
        identity = self._identity
        if type(identity) is not dict or set(identity) != {"run_id", "session_id", "runtime_id", "generation"}:
            raise PrimeP7DevelopmentGatewayError()
        witness = self._terminal_witness
        return MappingProxyType({
            "identity": MappingProxyType(dict(identity)),
            "result": MappingProxyType({
                "lifecycle": witness["lifecycle"],
                "usage": MappingProxyType(dict(witness["usage"])),
                "assistant": MappingProxyType(dict(witness["assistant"])),
                "observations": MappingProxyType(dict(witness["observations"])),
            }),
            "cumulative": MappingProxyType({"model_callback_count": 6, "tool_callback_count": 3}),
        })

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
                raise PrimeP7DevelopmentGatewayError() from None

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
                raise PrimeP7DevelopmentGatewayError() from None

    async def aopen(self, **kwargs: object) -> None:
        await self.open(**kwargs)

    async def aprompt(self, prompt: str) -> Mapping[str, object]:
        return await self.prompt(prompt)

    async def acancel(self) -> Mapping[str, object]:
        return await self.cancel()

    async def afeedback(self, feedback: str) -> None:
        await self.feedback(feedback)

    async def aclose(self) -> None:
        await self.close()

    def _fail(self) -> None:
        self._state = "failed"
        print(f"p7-sdk-gateway category={_stderr_category(self._stderr)}", flush=True)
        self._fail_transport()

    def _abort_active_prompt(self) -> None:
        self._fail()


__all__ = ("PrimeP7DevelopmentGateway", "PrimeP7DevelopmentGatewayError")


def _normalize_result(value: object, prompt_count: int) -> tuple[dict[str, object], Mapping[str, object]]:
    if type(value) is not dict or set(value) != {"lifecycle", "usage", "assistant", "observations"}:
        raise ValueError()
    usage, assistant, observations = value["usage"], value["assistant"], value["observations"]
    expected = {"active_tool_names": ["ipython"], "compact_count": 0, "model_callback_count": prompt_count * 2, "rlm_child_count": 0, "tool_call_count": prompt_count}
    if value["lifecycle"] != "completed" or type(assistant) is not dict or assistant.get("completed") is not True or assistant.get("stop_reason") != "stop" or set(assistant) != {"completed", "stop_reason"} or type(observations) is not dict or observations.get("active_tool_names") != ["ipython"] or any(type(observations.get(key)) is not int or observations[key] != expected[key] for key in ("compact_count", "model_callback_count", "rlm_child_count", "tool_call_count")) or type(usage) is not dict or set(usage) != {"input_tokens", "output_tokens", "total_tokens"} or any(type(usage[key]) is not int or usage[key] < 0 for key in usage) or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
        raise ValueError()
    return ({"lifecycle": "completed", "model_callback_count": prompt_count * 2, "tool_callback_count": prompt_count}, value)


def _stderr_category(value: object) -> str:
    """Return a fixed error type from the child stderr, never its message."""
    try:
        text = bytes(value).decode("utf-8", "strict")
        matches = re.findall(r"p7 bridge failed:([A-Za-z][A-Za-z0-9_]*)", text)
        if len(matches) == 1:
            return matches[0]
    except (TypeError, UnicodeDecodeError):
        pass
    return "unavailable"
