"""Operator-injected, bounded Pi model session for Prime applications.

The operator owns command, environment, and working directory selection. This
module never reads configuration or exposes provider traffic on public surfaces.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import time
from types import MappingProxyType
from typing import Mapping

from dotenv import dotenv_values

from asterion.runtime.host import CancellationSignal
from asterion.runtimes.pi_rpc import (
    PiRpcConfig,
    PiRpcEvent,
    PiRpcSession,
    normalize_pi_usage,
)


_DEADLINE_SECONDS = 120.0
_MAX_PROMPTS = 4
_MAX_INPUT_BYTES = 8_192
_MAX_OUTPUT_BYTES = 32_768
_MAX_INPUT_TOKENS = 16_000
_MAX_OUTPUT_TOKENS = 8_000
_MAX_COST_MICROS = 3_000
_PROVIDER_MAX_OUTPUT_TOKENS = 512
_INPUT_PRICE_MICROS_PER_MILLION = 140_000
_OUTPUT_PRICE_MICROS_PER_MILLION = 280_000


class LiveModelError(RuntimeError):
    """Public-safe failure of the bounded model session."""

    def __init__(self) -> None:
        super().__init__("Prime live model session failed")


@dataclass(frozen=True, slots=True, repr=False)
class LiveModelLaunch:
    """Private, immutable operator-approved Pi process resources."""

    command: tuple[str, ...]
    environment: Mapping[str, str]
    cwd: Path

    def __repr__(self) -> str:
        return "<LiveModelLaunch redacted>"


def resolve_live_model_launch(
    operator_root: Path, environment: Mapping[str, str]
) -> LiveModelLaunch:
    """Preflight the fixed, no-tool Pi launch from operator-owned inputs.

    This is an application integration boundary. It reads only the operator
    root's `.env`, never framework configuration or a neighboring source tree.
    """

    import asterion

    try:
        if not isinstance(operator_root, Path) or not isinstance(environment, Mapping):
            raise ValueError
        root = operator_root.resolve(strict=True)
        package = Path(str(asterion.__file__)).resolve(strict=True)
        if (
            not root.is_dir()
            or package.is_relative_to(root)
            or "site-packages" not in package.parts
        ):
            raise ValueError
        dotenv = {
            name: value
            for name, value in dotenv_values(root / ".env").items()
            if value is not None
        }
        merged = {**dotenv, **dict(environment)}
        credential = merged.get("DEEPSEEK_API_KEY", "")
        if (
            type(credential) is not str
            or not credential.strip()
            or any(character in credential for character in "\x00\r\n")
        ):
            raise ValueError
        executable_paths = []
        for name in ("ASTERION_PRIME_NODE", "ASTERION_PRIME_PI_ENTRY"):
            value = merged.get(name)
            if type(value) is not str or not value.strip():
                raise ValueError
            path = Path(value).resolve(strict=True)
            if not path.is_file() or not os.access(path, os.X_OK):
                raise ValueError
            executable_paths.append(str(path))
        approved_environment = {"DEEPSEEK_API_KEY": credential}
        for name in ("PATH", "LANG", "LC_ALL"):
            value = environment.get(name)
            if type(value) is str and value and "\x00" not in value:
                approved_environment[name] = value
        command = (
            *executable_paths,
            "--mode",
            "rpc",
            "--print",
            "--no-tools",
            "--no-session",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            "--system-prompt",
            "Follow the user task exactly. Return only the requested JSON.",
            "--thinking",
            "off",
            "--provider",
            "deepseek",
            "--model",
            "deepseek-v4-flash",
        )
        return LiveModelLaunch(command, MappingProxyType(approved_environment), root)
    except Exception:
        raise LiveModelError() from None


@dataclass(frozen=True, slots=True, repr=False)
class LiveModelUsage:
    input_tokens: int
    output_tokens: int
    cost_micros: int

    def __repr__(self) -> str:
        return "<LiveModelUsage redacted>"


@dataclass(frozen=True, slots=True, repr=False)
class LiveModelReply:
    text: str
    usage: LiveModelUsage

    def __repr__(self) -> str:
        return "<LiveModelReply redacted>"


class LiveModelSession:
    """One child process with fixed application limits and private replies."""

    def __init__(
        self,
        *,
        command: tuple[str, ...],
        environment: Mapping[str, str],
        cwd: Path,
    ) -> None:
        config_root = None
        try:
            config_root = tempfile.TemporaryDirectory(prefix="asterion-prime-pi-")
            models_path = Path(config_root.name) / "models.json"
            models_path.write_text(
                json.dumps(
                    {
                        "providers": {
                            "deepseek": {
                                "modelOverrides": {
                                    "deepseek-v4-flash": {
                                        "maxTokens": _PROVIDER_MAX_OUTPUT_TOKENS
                                    }
                                }
                            }
                        }
                    },
                    separators=(",", ":"),
                )
            )
            models_path.chmod(0o600)
            config = PiRpcConfig(
                command=command,
                environment={**environment, "PI_CODING_AGENT_DIR": config_root.name},
                cwd=cwd,
                deadline_seconds=_DEADLINE_SECONDS,
                compact_events=False,
            )
        except Exception:
            if config_root is not None:
                config_root.cleanup()
            raise LiveModelError() from None
        self._config_root = config_root
        self._rpc = PiRpcSession(config)
        self._opened = False
        self._closed = False
        self._prompts = 0
        self._input_bytes = 0
        self._output_bytes = 0
        self._input_tokens = 0
        self._output_tokens = 0

    def __repr__(self) -> str:
        return "<LiveModelSession redacted>"

    @property
    def process(self):
        """Return the child handle for operator-owned cleanup verification."""
        return self._rpc.process

    def _verify_model_cap(self) -> None:
        request_id = self._rpc.next_id()
        self._rpc.send({"id": request_id, "type": "get_state"})
        deadline = time.monotonic() + 5
        for _ in range(16):
            response = self._rpc.read_json_line(
                timeout_seconds=max(0.001, deadline - time.monotonic())
            )
            if response.get("type") != "response" or response.get("id") != request_id:
                continue
            data = response.get("data")
            model = data.get("model") if isinstance(data, Mapping) else None
            if (
                response.get("command") != "get_state"
                or response.get("success") is not True
                or not isinstance(model, Mapping)
                or model.get("provider") != "deepseek"
                or model.get("id") != "deepseek-v4-flash"
                or type(model.get("maxTokens")) is not int
                or model.get("maxTokens") != _PROVIDER_MAX_OUTPUT_TOKENS
            ):
                raise LiveModelError()
            return
        raise LiveModelError()

    async def open(self, *, signal: CancellationSignal) -> None:
        if self._opened or self._closed or signal.cancelled:
            raise LiveModelError()
        try:
            await self._rpc.open(signal=signal)
            await asyncio.to_thread(self._verify_model_cap)
            if signal.cancelled:
                raise LiveModelError()
        except BaseException as error:
            await self.close()
            if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                raise
            if isinstance(error, asyncio.CancelledError):
                raise
            raise LiveModelError() from None
        self._opened = True

    async def prompt(self, text: str, *, signal: CancellationSignal) -> LiveModelReply:
        if (
            not self._opened
            or self._closed
            or signal.cancelled
            or type(text) is not str
            or not text
        ):
            await self.close()
            raise LiveModelError()
        encoded = text.encode("utf-8")
        if (
            self._prompts >= _MAX_PROMPTS
            or self._input_bytes + len(encoded) > _MAX_INPUT_BYTES
        ):
            await self.close()
            raise LiveModelError()
        self._prompts += 1
        self._input_bytes += len(encoded)
        usage_events: list[tuple[int, int]] = []
        output_bytes = 0

        def record(event: PiRpcEvent) -> None:
            nonlocal output_bytes
            if event.type == "message_update":
                update = event.payload.get("assistantMessageEvent")
                if isinstance(update, Mapping) and update.get("type") == "text_delta":
                    delta = update.get("delta")
                    if type(delta) is not str:
                        raise LiveModelError()
                    output_bytes += len(delta.encode("utf-8"))
                    if self._output_bytes + output_bytes > _MAX_OUTPUT_BYTES:
                        raise LiveModelError()
            if event.type == "message_end":
                message = event.payload.get("message")
                if isinstance(message, Mapping) and message.get("role") == "assistant":
                    usage = normalize_pi_usage(event.payload)
                    if usage is None:
                        raise LiveModelError()
                    # The shared Pi normalizer already includes cache reads
                    # and writes in input_tokens. Budget all of them at the
                    # full input rate to conservatively bound cost.
                    usage_events.append((usage["input_tokens"], usage["output_tokens"]))

        try:
            result = await self._rpc.prompt(text, signal=signal, on_event=record)
            if not usage_events or signal.cancelled:
                raise LiveModelError()
            incoming = sum(item[0] for item in usage_events)
            outgoing = sum(item[1] for item in usage_events)
            total_incoming = self._input_tokens + incoming
            total_outgoing = self._output_tokens + outgoing
            cost_micros = (
                total_incoming * _INPUT_PRICE_MICROS_PER_MILLION
                + total_outgoing * _OUTPUT_PRICE_MICROS_PER_MILLION
                + 999_999
            ) // 1_000_000
            if (
                total_incoming > _MAX_INPUT_TOKENS
                or total_outgoing > _MAX_OUTPUT_TOKENS
                or cost_micros > _MAX_COST_MICROS
                or self._output_bytes + len(result.final_text.encode("utf-8"))
                > _MAX_OUTPUT_BYTES
            ):
                raise LiveModelError()
            self._input_tokens = total_incoming
            self._output_tokens = total_outgoing
            self._output_bytes += len(result.final_text.encode("utf-8"))
            prompt_cost = (
                incoming * _INPUT_PRICE_MICROS_PER_MILLION
                + outgoing * _OUTPUT_PRICE_MICROS_PER_MILLION
                + 999_999
            ) // 1_000_000
            return LiveModelReply(
                result.final_text, LiveModelUsage(incoming, outgoing, prompt_cost)
            )
        except BaseException as error:
            await self.close()
            if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                raise
            if isinstance(error, asyncio.CancelledError):
                raise
            raise LiveModelError() from None

    async def close(self) -> None:
        """Reap the child; safe after failure, cancellation, and repeated calls."""
        if self._closed:
            return
        self._closed = True
        self._opened = False
        try:
            self._rpc.stop()
        except BaseException:
            raise LiveModelError() from None
        finally:
            self._config_root.cleanup()
