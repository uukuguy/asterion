"""Bounded model continuation across two independent operator invocations.

The immutable checkpoint transcript is the task-state artifact. Recovery gives
that validated artifact to a new model process, without replaying the commit
prompt or assuming that Python heap objects survived the prior process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sys
import tempfile
from typing import Protocol

from asterion.agents.prime.store import FilePrimeSessionStore
from asterion.applications.prime.p4 import operator
from asterion.applications.prime.p4.host import P4CommitReceipt
from asterion.applications.prime.p4.oracle import P4Oracle
from asterion.applications.prime.p4.runtime_binding import P4_RUNTIME_OPTIONS
from asterion.applications.prime.services import ContinuityStoreHostService
from asterion.runtime.host import CancellationSignal


class P4LiveError(RuntimeError):
    def __init__(self):
        super().__init__("P4 live continuity failed")


class ModelSession(Protocol):
    async def open(self, *, signal: CancellationSignal) -> None: ...
    async def prompt(self, text: str, *, signal: CancellationSignal) -> object: ...
    async def close(self) -> None: ...


class _NeverCancelled:
    cancelled = False


@dataclass(frozen=True, slots=True)
class P4LiveResult(operator.P4PublicResult):
    model_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0
    recovered_payload_sha256: str | None = None


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return sha256(_encoded(value)).hexdigest()


def _object(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise P4LiveError()
            result[key] = value
        return result

    if type(text) is not str or len(text.encode()) > 4096:
        raise P4LiveError()
    try:
        result = json.loads(text, object_pairs_hook=unique)
    except (TypeError, ValueError):
        raise P4LiveError() from None
    if type(result) is not dict:
        raise P4LiveError()
    return result


def _committed_state(text):
    result = _object(text)
    if (
        set(result) != {"token", "total"}
        or type(result["token"]) is not str
        or len(result["token"]) != 32
        or any(c not in "0123456789abcdef" for c in result["token"])
        or type(result["total"]) is not int
        or result["total"] != sum((11, 17, 23))
    ):
        raise P4LiveError()
    return result


class P4LiveHost(operator._OperatorP4RuntimeHost):
    """Live host using existing continuity storage and public composed runtime."""

    def __init__(self, *, mode, private_root, session_factory, command_sha256, binding_sha256):
        self.mode = mode
        self._store = None
        self._temporary = None
        self._session = None
        self._worker_closed = False
        self._prior = None
        self._state = None
        self._classification = None
        self._checkpoint = None
        self._result_sha = None
        self.usage = None
        self._factory = session_factory
        ceilings_sha = _digest(dict(P4_RUNTIME_OPTIONS))
        try:
            if mode == "commit":
                private_root.mkdir(parents=True, mode=0o700, exist_ok=False)
                generation = 1
                continuation_id = "p4-live-" + secrets.token_hex(12)
                session_id = "p4-live-" + secrets.token_hex(12)
            elif mode == "recover":
                prior = operator._read_prior_identity(private_root)
                if (
                    prior.generation != 1
                    or prior.pi_command_sha256 != command_sha256
                    or prior.extension_binding_fingerprint != binding_sha256
                    or prior.ceilings_sha256 != ceilings_sha
                ):
                    raise P4LiveError()
                # Authenticate all prior material before changing the generation.
                prior_store = FilePrimeSessionStore(private_root, prior)
                try:
                    recovered = prior_store.recover_checkpoint()
                    if recovered is None or recovered.checkpoint.generation != 1:
                        raise P4LiveError()
                    self._state = _committed_state(recovered.transcript.decode())
                    if recovered.usage.get("result_sha256") != _digest(self._state):
                        raise P4LiveError()
                finally:
                    prior_store.close()
                generation = 2
                continuation_id = prior.continuation_id
                session_id = prior.session_id
            else:
                raise P4LiveError()
            identity = operator._build_identity(
                private_root=private_root, generation=generation,
                continuation_id=continuation_id, session_id=session_id,
                worker_sha=_digest({"model_session_lease": secrets.token_hex(32)}),
                pi_command_sha256=command_sha256,
                extension_binding_fingerprint=binding_sha256,
                ceilings_sha256=ceilings_sha,
            )
            self._store = (
                FilePrimeSessionStore(private_root, identity)
                if mode == "commit"
                else FilePrimeSessionStore.open_continued(private_root, identity)
            )
            if mode == "recover":
                self._prior = self._store.recover_checkpoint()
                if self._prior is None:
                    raise P4LiveError()
            self.continuity = ContinuityStoreHostService(self._store)
            self.oracle = object()
            self.extension = session_factory
            self._temporary = tempfile.TemporaryDirectory(prefix="p4-live-session-")
        except BaseException:
            if self._store is not None:
                self._store.close()
            raise

    async def _close_model(self):
        if self._session is not None and not self._worker_closed:
            async with asyncio.timeout(5):
                await self._session.close()
            self._worker_closed = True

    async def commit_checkpoint(self, *, run_id, call, signal):
        if self._checkpoint is not None or signal.cancelled:
            raise P4LiveError()
        prior_sha = None if self._prior is None else self._prior.checkpoint.digest
        if call.generation != self.identity.generation or call.prior_checkpoint_sha256 != prior_sha:
            raise P4LiveError()
        if self._prior is None:
            token = secrets.token_hex(16)
            task = {"token": token, "inputs": [11, 17, 23]}
            prompt = (
                'Sum the inputs. Return only JSON with keys "token" (copied exactly) '
                'and "total" (integer sum). Use no tools. TASK_JSON='
            )
        else:
            task = {"prior": self._state, "increment": 7}
            prompt = (
                'Continue this previously committed task state. Return only JSON with '
                '"token" copied exactly from prior, "prior_total" copied from prior total, '
                'and "total" equal to prior total plus increment. Use no tools. TASK_JSON='
            )
        self._session = self._factory(self.mode, Path(self._temporary.name))
        try:
            await self._session.open(signal=signal)
            reply = await self._session.prompt(prompt + _encoded(task).decode(), signal=signal)
            usage = {key: getattr(reply.usage, key) for key in ("input_tokens", "output_tokens", "cost_micros")}
            if (
                any(type(value) is not int or value < 0 for value in usage.values())
                or not 0 < usage["input_tokens"] + usage["output_tokens"] <= 32_000
                or usage["cost_micros"] > 300_000
            ):
                raise P4LiveError()
            self.usage = usage
            if self._prior is None:
                result = _committed_state(reply.text)
                if result["token"] != token:
                    raise P4LiveError()
            else:
                result = _object(reply.text)
                if (
                    set(result) != {"token", "prior_total", "total"}
                    or result["token"] != self._state["token"]
                    or type(result["prior_total"]) is not int
                    or type(result["total"]) is not int
                    or result["prior_total"] != self._state["total"]
                    or result["total"] != self._state["total"] + 7
                ):
                    raise P4LiveError()
            if signal.cancelled:
                raise asyncio.CancelledError()
        finally:
            # No checkpoint is signed until the model process has been reaped.
            await self._close_model()
        encoded = _encoded(result)
        self._result_sha = sha256(encoded).hexdigest()
        if self._prior is not None:
            P4Oracle(self._prior.checkpoint, self.identity).verify(
                commit_result_sha256=self._prior.usage["result_sha256"],
                recover_result_sha256=self._result_sha,
                recovered_prior_checkpoint_sha256=prior_sha,
            )
        self._checkpoint = operator._seal_commit_checkpoint(
            store=self._store, worker_sha=self.identity.worker_identity_sha256,
            prior_checkpoint_sha=prior_sha, run_id=run_id, transcript=encoded,
            usage={**self.usage, "result_sha256": self._result_sha},
            continuation_id=self.identity.continuation_id,
        )
        return P4CommitReceipt(call.call_id, self._checkpoint.digest, self._result_sha,
                               self.identity.generation, len(encoded))

    async def report_recovery_stopped(self, *, run_id, pending_classification):
        await self._close_model()
        self._classification = pending_classification

    async def close(self):
        try:
            await self._close_model()
        finally:
            if self._store is not None:
                self._store.close()
            if self._temporary is not None:
                self._temporary.cleanup()


async def run_live_round(
    *, mode: str, private_root: Path,
    session_factory: Callable[[str, Path], ModelSession],
    command_sha256: str, binding_sha256: str,
    signal: CancellationSignal | None = None,
) -> P4LiveResult:
    """Run one fixed commit or recover round in the calling operator process."""
    signal = signal if signal is not None else _NeverCancelled()
    if signal.cancelled:
        raise asyncio.CancelledError()
    host = None
    try:
        host = P4LiveHost(
            mode=mode, private_root=private_root.absolute(), session_factory=session_factory,
            command_sha256=command_sha256, binding_sha256=binding_sha256,
        )
        preflight = operator._Preflight(
            private_root.parent, Path(sys.executable), private_root, mode, None,
        )
        async with asyncio.timeout(120):
            public = await operator._invoke_composed_round(preflight, host=host, signal=signal)
        if host.usage is None or not host._worker_closed:
            raise P4LiveError()
        return P4LiveResult(
            **asdict(public), model_call_count=1, **host.usage,
            recovered_payload_sha256=(
                None if host._prior is None else host._prior.checkpoint.private_transcript_sha256
            ),
        )
    except asyncio.CancelledError:
        raise asyncio.CancelledError() from None
    except Exception:
        raise P4LiveError() from None
    finally:
        if host is not None:
            try:
                await host.close()
            except Exception:
                raise P4LiveError() from None


__all__ = ("P4LiveError", "P4LiveHost", "P4LiveResult", "run_live_round")
