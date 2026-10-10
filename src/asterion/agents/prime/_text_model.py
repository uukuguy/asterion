"""Private bounded text engine and one owner usage ledger."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import tempfile
import time
from typing import TYPE_CHECKING

from asterion.agents.prime import _launch
from asterion.agents.prime.compaction_budget import ModelPrice
from asterion.agents.prime.deadline import TaskDeadline
from asterion.runtime.host import CancellationSignal
from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcEvent, normalize_pi_usage

if TYPE_CHECKING:
    from asterion.agents.prime.application import PrimeTextLimits


class LiveModelError(RuntimeError):
    def __init__(self) -> None:
        super().__init__('Prime live model session failed')


@dataclass(frozen=True, slots=True, repr=False)
class LiveModelUsage:
    input_tokens: int
    output_tokens: int
    cost_micros: int

    def __repr__(self) -> str:
        return '<LiveModelUsage redacted>'


@dataclass(frozen=True, slots=True, repr=False)
class LiveModelReply:
    text: str
    usage: LiveModelUsage

    def __repr__(self) -> str:
        return '<LiveModelReply redacted>'


class _TextUsage:
    """All key conversations consume the same fixed authority."""
    def __init__(self, limits: PrimeTextLimits, task_deadline: TaskDeadline | None):
        self.prompts = self.input_bytes = self.output_bytes = 0
        self.input_tokens = self.output_tokens = 0
        self.blocked = False
        self.started = time.monotonic()
        self.deadline = self.started + limits.deadline_seconds
        self.task_deadline = task_deadline
        self.lock = asyncio.Lock()

    def remaining(self, limits: PrimeTextLimits) -> float:
        remaining = min(self.deadline, self.started + limits.deadline_seconds) - time.monotonic()
        if self.task_deadline is not None:
            remaining = min(remaining, self.task_deadline.remaining_seconds())
        if self.blocked or remaining <= 0:
            raise LiveModelError()
        return remaining


def _over(value: int, ceiling: int | None) -> bool:
    return ceiling is not None and value > ceiling


def _cost(incoming: int, outgoing: int, price: ModelPrice | None) -> int:
    if price is None:
        return 0
    return (incoming * price.input_per_million + outgoing * price.output_per_million + 999999) // 1000000


class LiveModelSession:
    """Existing RPC engine, privately owned by Prime or the transitional adapter."""
    def __init__(self, *, command: tuple[str, ...], environment: Mapping[str, str], cwd: Path,
                 limits: PrimeTextLimits, provider: str, model: str,
                 usage: _TextUsage | None = None,
                 task_deadline: TaskDeadline | None = None):
        self._limits = limits
        self._usage = _TextUsage(self._limits, task_deadline) if usage is None else usage
        self._provider, self._model = provider, model
        self._config_root = None
        try:
            remaining = self._usage.remaining(self._limits)
            self._config_root = tempfile.TemporaryDirectory(prefix='asterion-prime-pi-')
            root = Path(self._config_root.name)
            # Keep operator-approved OAuth/profile material while isolating settings.
            # Only explicit profile files are copied; core never discovers credentials.
            profile = environment.get('PI_CODING_AGENT_DIR')
            if profile is not None:
                for name in ('auth.json', 'models.json'):
                    source = Path(profile) / name
                    if source.is_file():
                        shutil.copyfile(source, root / name)
                        (root / name).chmod(0o600)
            path = root / 'models.json'
            material = json.loads(path.read_text()) if path.exists() else {}
            if self._limits.provider_output_tokens is not None:
                provider_config = material.setdefault('providers', {}).setdefault(provider, {})
                override = provider_config.setdefault('modelOverrides', {}).setdefault(model, {})
                override['maxTokens'] = self._limits.provider_output_tokens
            path.write_text(json.dumps(material, separators=(',', ':')))
            path.chmod(0o600)
            config = PiRpcConfig(command=command,
                                 environment={**environment, 'PI_CODING_AGENT_DIR': str(root)},
                                 cwd=cwd, deadline_seconds=remaining, compact_events=False)
            self._rpc = _launch.text_rpc(config)
        except Exception:
            if self._config_root is not None:
                self._config_root.cleanup()
            raise LiveModelError() from None
        self._opened = self._closed = self._closing = False

    def __repr__(self) -> str:
        return '<LiveModelSession redacted>'

    @property
    def process(self):
        return self._rpc.process

    def _verify_model_cap(self) -> None:
        request_id = self._rpc.next_id()
        self._rpc.send({'id': request_id, 'type': 'get_state'})
        deadline = time.monotonic() + min(5, self._usage.remaining(self._limits))
        for _ in range(16):
            response = self._rpc.read_json_line(timeout_seconds=max(0.001, deadline - time.monotonic()))
            if response.get('type') != 'response' or response.get('id') != request_id:
                continue
            data = response.get('data')
            model = data.get('model') if isinstance(data, Mapping) else None
            cap = self._limits.provider_output_tokens
            if (response.get('command') != 'get_state' or response.get('success') is not True
                    or not isinstance(model, Mapping) or model.get('provider') != self._provider
                    or model.get('id') != self._model
                    or cap is not None and (type(model.get('maxTokens')) is not int
                                           or model.get('maxTokens') != cap)):
                raise LiveModelError()
            return
        raise LiveModelError()

    async def open(self, *, signal: CancellationSignal) -> None:
        if self._opened or self._closed or self._closing or signal.cancelled:
            raise LiveModelError()
        try:
            self._usage.remaining(self._limits)
            await self._rpc.open(signal=signal)
            await asyncio.to_thread(self._verify_model_cap)
            if signal.cancelled:
                raise LiveModelError()
        except BaseException as error:
            await self.close()
            if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
                raise
            raise LiveModelError() from None
        self._opened = True

    async def prompt(self, text: str, *, signal: CancellationSignal) -> LiveModelReply:
        usage, limits = self._usage, self._limits
        effect_started = False
        try:
            usage.remaining(limits)
            if not self._opened or self._closed or self._closing or signal.cancelled or type(text) is not str or not text:
                raise LiveModelError()
            encoded = text.encode('utf-8')
            if _over(usage.prompts + 1, limits.max_prompts) or _over(usage.input_bytes + len(encoded), limits.max_input_bytes):
                raise LiveModelError()
            usage.prompts += 1
            usage.input_bytes += len(encoded)
            usage_events: list[tuple[int, int]] = []
            output_bytes = 0

            def record(event: PiRpcEvent) -> None:
                nonlocal output_bytes
                if event.type == 'message_update':
                    update = event.payload.get('assistantMessageEvent')
                    if isinstance(update, Mapping) and update.get('type') == 'text_delta':
                        delta = update.get('delta')
                        if type(delta) is not str:
                            raise LiveModelError()
                        output_bytes += len(delta.encode('utf-8'))
                        if _over(usage.output_bytes + output_bytes, limits.max_output_bytes):
                            raise LiveModelError()
                if event.type == 'message_end':
                    message = event.payload.get('message')
                    if isinstance(message, Mapping) and message.get('role') == 'assistant':
                        event_usage = normalize_pi_usage(event.payload)
                        if event_usage is None:
                            raise LiveModelError()
                        usage_events.append((event_usage['input_tokens'], event_usage['output_tokens']))

            effect_started = True
            result = await asyncio.wait_for(self._rpc.prompt(text, signal=signal, on_event=record),
                                            timeout=usage.remaining(limits))
            if not usage_events or signal.cancelled:
                raise LiveModelError()
            incoming = sum(item[0] for item in usage_events)
            outgoing = sum(item[1] for item in usage_events)
            usage.input_tokens += incoming
            usage.output_tokens += outgoing
            usage.output_bytes += len(result.final_text.encode('utf-8'))
            if (_over(usage.input_tokens, limits.max_input_tokens)
                    or _over(usage.output_tokens, limits.max_output_tokens)
                    or _over(_cost(usage.input_tokens, usage.output_tokens, limits.price), limits.max_cost_micros)
                    or _over(usage.output_bytes, limits.max_output_bytes)):
                raise LiveModelError()
            usage.remaining(limits)
            return LiveModelReply(result.final_text, LiveModelUsage(incoming, outgoing,
                                  _cost(incoming, outgoing, limits.price)))
        except BaseException as error:
            if effect_started:
                usage.blocked = True
            await self.close()
            if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
                raise
            raise LiveModelError() from None

    async def close(self) -> None:
        """A failed reap remains retryable; never record a successful close early."""
        if self._closed:
            return
        self._closing = True
        self._opened = False
        try:
            self._rpc.stop()
            self._config_root.cleanup()
        except BaseException:
            self._usage.blocked = True
            raise LiveModelError() from None
        self._closed = True
