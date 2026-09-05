"""Development-only one-call provider with a private, reaped child boundary.

This is deliberately not a bundle-owned or sealed authority entry.  It forks
the locally installed source process for development work only; production
authority adapters and receipt issuance do not import this module.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import os
import signal
import struct
import time

from .model_broker import PrimeModelBrokerTokenUsage
from .model_session_host import (
    PrimeModelSessionHostError,
    _P1_DEADLINE_SECONDS,
    _PrivatePrimeModelConfig,
    _invoke_provider_sync,
    _private_config_from_values,
)

_INPUT_CAP = 4096
_OUTPUT_CAP = 4096
_DEADLINE_SECONDS = float(_P1_DEADLINE_SECONDS)
_REAP_GRACE_SECONDS = 2.0
_POLL_SECONDS = 0.01
_USAGE_SIZE = struct.calcsize("!QQQ")


class PrimeP1DevelopmentProviderError(ValueError):
    """Public-safe development provider failure."""


class PrimeP1DevelopmentProvider:
    """A one-call provider whose HTTP work dies with its private child."""

    __slots__ = ("_called", "_child_pid", "_config", "_terminal")

    def __init__(self, config: _PrivatePrimeModelConfig) -> None:
        if type(config) is not _PrivatePrimeModelConfig:
            raise PrimeP1DevelopmentProviderError(
                "prime development provider is unavailable"
            )
        self._called = False
        self._child_pid: int | None = None
        self._config = config
        self._terminal: PrimeModelBrokerTokenUsage | None = None

    def __repr__(self) -> str:
        return "PrimeP1DevelopmentProvider(redacted)"

    async def __call__(self, body: bytes) -> bytes:
        if (
            self._called
            or type(body) is not bytes
            or not body
            or len(body) > _INPUT_CAP
        ):
            raise PrimeP1DevelopmentProviderError(
                "prime development provider is unavailable"
            )
        self._called = True
        request_read: int | None = None
        request_write: int | None = None
        result_read: int | None = None
        result_write: int | None = None
        try:
            request_read, request_write = os.pipe()
            result_read, result_write = os.pipe()
            pid = os.fork()
            if pid == 0:
                _development_provider_child(
                    self._config, request_read, request_write, result_read, result_write
                )
            self._child_pid = pid
            os.close(request_read)
            request_read = None
            os.close(result_write)
            result_write = -1
            _write_all(request_write, body)
            os.close(request_write)
            request_write = -1
            os.set_blocking(result_read, False)
            result = await self._receive_result(result_read)
            self._terminal = result[1]
            return result[0]
        except asyncio.CancelledError:
            await self._reap_shielded()
            raise
        except BaseException:
            await self._reap_shielded()
            raise PrimeP1DevelopmentProviderError(
                "prime development provider is unavailable"
            ) from None
        finally:
            _close_quietly(request_read)
            _close_quietly(request_write)
            _close_quietly(result_read)
            _close_quietly(result_write)

    def terminal_usage(self) -> PrimeModelBrokerTokenUsage:
        if self._terminal is None:
            raise PrimeP1DevelopmentProviderError(
                "prime development provider is unavailable"
            )
        return self._terminal

    async def _receive_result(
        self, result_read: int
    ) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
        deadline = time.monotonic() + _DEADLINE_SECONDS
        chunks: list[bytes] = []
        while True:
            _drain(result_read, chunks)
            try:
                observed, status = os.waitpid(self._child_pid, os.WNOHANG)  # type: ignore[arg-type]
            except ChildProcessError:
                self._child_pid = None
                raise PrimeP1DevelopmentProviderError(
                    "prime development provider is unavailable"
                ) from None
            if observed:
                self._child_pid = None
                if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
                    raise PrimeP1DevelopmentProviderError(
                        "prime development provider is unavailable"
                    )
                _drain(result_read, chunks)
                return _decode_result(b"".join(chunks))
            if time.monotonic() >= deadline:
                raise TimeoutError
            await asyncio.sleep(_POLL_SECONDS)

    async def _reap_shielded(self) -> None:
        """Finish process cleanup even if cancellation is delivered again."""
        task = asyncio.create_task(self._kill_and_reap())
        interrupted = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                interrupted = True
        task.result()
        if interrupted:
            raise asyncio.CancelledError

    async def _kill_and_reap(self) -> None:
        pid = self._child_pid
        if pid is None:
            return
        try:
            observed, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            self._child_pid = None
            raise PrimeP1DevelopmentProviderError(
                "prime development provider is unavailable"
            ) from None
        if observed:
            self._child_pid = None
            return
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        deadline = time.monotonic() + _REAP_GRACE_SECONDS
        while time.monotonic() < deadline:
            try:
                observed, _ = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                self._child_pid = None
                raise PrimeP1DevelopmentProviderError(
                    "prime development provider is unavailable"
                ) from None
            if observed:
                self._child_pid = None
                return
            await asyncio.sleep(_POLL_SECONDS)
        raise PrimeP1DevelopmentProviderError(
            "prime development provider is unavailable"
        )


def create_prime_p1_development_provider(
    operator_config: Mapping[str, object],
) -> PrimeP1DevelopmentProvider:
    """Parse operator-supplied private values without reading dotenv or env."""
    try:
        config = _private_config_from_values(operator_config)
        return PrimeP1DevelopmentProvider(config)
    except (PrimeModelSessionHostError, TypeError, ValueError):
        raise PrimeP1DevelopmentProviderError(
            "prime development provider is unavailable"
        ) from None


def _development_provider_child(
    config: _PrivatePrimeModelConfig,
    request_read: int,
    request_write: int,
    result_read: int,
    result_write: int,
) -> None:
    """Fixed child entry; config is inherited memory, never argv or environment."""
    try:
        _close_quietly(request_write)
        _close_quietly(result_read)
        body = _read_exact(request_read, _INPUT_CAP)
        _close_quietly(request_read)
        cell, usage = _invoke_provider_sync(config, body)
        if (
            type(cell) is not bytes
            or not cell
            or len(cell) > _OUTPUT_CAP
            or type(usage) is not PrimeModelBrokerTokenUsage
        ):
            raise ValueError
        _write_all(
            result_write,
            b"S"
            + struct.pack("!I", len(cell))
            + cell
            + struct.pack(
                "!QQQ",
                usage.input_tokens,
                usage.output_tokens,
                usage.cost_microunits,
            ),
        )
        os._exit(0)
    except BaseException:
        try:
            _write_all(result_write, b"F")
        except BaseException:
            pass
        os._exit(1)
    finally:
        _close_quietly(request_read)
        _close_quietly(request_write)
        _close_quietly(result_read)
        _close_quietly(result_write)


def _read_exact(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, maximum + 1 - sum(map(len, chunks)))
        if not chunk:
            break
        chunks.append(chunk)
        if sum(map(len, chunks)) > maximum:
            raise ValueError
    value = b"".join(chunks)
    if not value:
        raise ValueError
    return value


def _write_all(descriptor: int, value: bytes) -> None:
    offset = 0
    while offset < len(value):
        offset += os.write(descriptor, value[offset:])


def _drain(descriptor: int, chunks: list[bytes]) -> None:
    while True:
        try:
            chunk = os.read(descriptor, _OUTPUT_CAP + _USAGE_SIZE + 6)
        except BlockingIOError:
            return
        if not chunk:
            return
        chunks.append(chunk)
        if sum(map(len, chunks)) > _OUTPUT_CAP + _USAGE_SIZE + 5:
            raise ValueError


def _decode_result(raw: bytes) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
    if len(raw) < 1 or raw[:1] != b"S":
        raise ValueError
    size = struct.unpack("!I", raw[1:5])[0] if len(raw) >= 5 else -1
    if not 0 < size <= _OUTPUT_CAP or len(raw) != 5 + size + _USAGE_SIZE:
        raise ValueError
    input_tokens, output_tokens, cost = struct.unpack("!QQQ", raw[5 + size :])
    return raw[5 : 5 + size], PrimeModelBrokerTokenUsage(
        input_tokens, output_tokens, cost
    )


def _close_quietly(descriptor: int | None) -> None:
    if type(descriptor) is int and descriptor >= 0:
        try:
            os.close(descriptor)
        except OSError:
            pass


__all__ = (
    "PrimeP1DevelopmentProvider",
    "PrimeP1DevelopmentProviderError",
    "create_prime_p1_development_provider",
)
