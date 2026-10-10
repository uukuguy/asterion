"""Application-owned P3 preset: admitted independent child, validated root join.

Model transport is injected after operator preflight. All text and evidence
remain private; the selected composed application emits its native receipt.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import secrets

from asterion.agents.prime.application import PrimeApplication, PrimeTextLimits
from asterion.applications.prime.live_model import bounded_text_limits
from asterion.applications.prime.p3 import operator
from asterion.applications.prime.p3.host import P3RootResult
from asterion.applications.prime.p3.oracle import P3Oracle
from asterion.applications.prime.p3.receipt import seal
from asterion.applications.prime.p3.runtime_binding import P3_RUNTIME_OPTIONS
from asterion.applications.prime.services import ChildAdmissionRefused, ChildRunnerHostService
from asterion.runtime.host import CancellationSignal


class P3LiveError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("P3 live verification failed")


@dataclass(frozen=True, slots=True)
class P3LiveResult(operator.P3PublicResult):
    model_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0
    evidence_sha256: str = ""


@dataclass(frozen=True, slots=True)
class _ChildResult:
    result_sha256: str
    root_result_sha256: str
    depth_reached: int = 2


def _encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: object) -> str:
    return sha256(_encoded(value)).hexdigest()


def _answer(text: object, key: str, expected: int) -> dict[str, int]:
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise P3LiveError()
            result[name] = value
        return result

    if type(text) is not str or len(text.encode()) > 4096:
        raise P3LiveError()
    try:
        result = json.loads(text, object_pairs_hook=unique)
        if (
            type(result) is not dict or set(result) != {key}
            or type(result[key]) is not int or result[key] != expected
        ):
            raise P3LiveError()
        return result
    except (ValueError, TypeError):
        raise P3LiveError() from None


class P3LiveHost(operator._OperatorP3RuntimeHost):
    """Host execution reached exclusively through the composed P3 runtime."""

    def __init__(self, resources, prime: PrimeApplication, limits: PrimeTextLimits):
        super().__init__(resources)
        self._prime = prime
        self._limits = limits
        self._usage: list[dict[str, int]] = []
        self.evidence_sha256 = ""

    def _record_usage(self, reply) -> dict[str, int]:
        usage = {
            key: getattr(reply.usage, key)
            for key in ("input_tokens", "output_tokens", "cost_micros")
        }
        if any(type(value) is not int or value < 0 for value in usage.values()):
            raise P3LiveError()
        if usage["input_tokens"] + usage["output_tokens"] == 0:
            raise P3LiveError()
        self._usage.append(usage)
        return usage

    def _check_budget(self):
        if (
            sum(u["input_tokens"] + u["output_tokens"] for u in self._usage) > 16_000
            or sum(u["cost_micros"] for u in self._usage) > 100_000
        ):
            raise P3LiveError()

    async def _prompt(self, role, text, signal, *, child_run_id=None):
        if signal.cancelled:
            raise asyncio.CancelledError()
        before = self._prime._text_usage_summary()
        try:
            reply = await self._prime.text_once(
                key=role, text=text, limits=self._limits, signal=signal,
            )
        finally:
            after = self._prime._text_usage_summary()
            # Accounting releases admission only for a known, finished effect.
            # A paid reply stays known even if Prime cannot reap its process.
            if (child_run_id is not None and not after.unknown_effect
                    and after.prompts > before.prompts):
                self._resources.child_runner.record_child_cost(
                    Decimal(after.cost_micros - before.cost_micros) / Decimal(1_000_000),
                    child_run_id=child_run_id,
                )
        self._record_usage(reply)
        self._check_budget()
        if signal.cancelled:
            raise asyncio.CancelledError()
        return reply.text

    async def run_root(self, *, parent_run_id, child_request, signal):
        resources = self._resources
        if (
            parent_run_id != resources.root_run_id or child_request is not None
            or self.result is not None
        ):
            raise P3LiveError()
        if signal.cancelled:
            raise asyncio.CancelledError()
        admission = await resources.child_runner.admit_child(
            parent_run_id=parent_run_id, depth=2,
            child_identity=resources.child_identity, signal=signal,
        )
        if isinstance(admission, ChildAdmissionRefused):
            raise P3LiveError()
        child = _answer(
            await self._prompt(
                "child", "Compute the sum of the squares of 3, 5 and 14. "
                'Return only a JSON object with one integer key "sum_squares". '
                "Use no tools.", signal, child_run_id=admission.child_run_id,
            ), "sum_squares", sum(value * value for value in (3, 5, 14)),
        )
        root = _answer(
            await self._prompt(
                "root", "An independent admitted child returned this verified JSON: "
                + _encoded(child).decode()
                + '. Compute 2 * sum_squares + 3. Return only JSON with one integer key "result". '
                "Use no tools.", signal,
            ), "result", 2 * child["sum_squares"] + 3,
        )
        child_sha = _digest(child)
        joined_sha = await resources.child_runner.join_child_result(
            parent_run_id=parent_run_id,
            child_receipt=_ChildResult(child_sha, _digest(root)),
        )
        values = dict(
            root_run_id=parent_run_id, root_generation=1,
            child_run_id=admission.child_run_id, child_generation=2,
            child_result_sha256=child_sha, joined_result_sha256=joined_sha,
            depth_reached=2, refusal_reason=None,
        )
        resources.p3_oracle.check(**values)
        receipt = seal(**values)
        evidence = {
            "child": child, "root": root, "usage": self._usage,
            "root_identity": asdict(resources.root_identity),
            "child_identity": asdict(resources.child_identity),
            "receipt": asdict(receipt), "sessions_closed": True,
        }
        raw = _encoded(evidence)
        evidence_path = resources.private_root / "live-evidence.json"
        with evidence_path.open("xb") as stream:
            evidence_path.chmod(0o600)
            stream.write(raw)
        self.evidence_sha256 = sha256(raw).hexdigest()
        self.result = operator.P3PublicResult(
            status="completed", **values, receipt_sha256=receipt.sha256(),
        )
        return P3RootResult(**values)


async def run_live_verification(
    *, prime: PrimeApplication, private_root: Path,
    limits: PrimeTextLimits | None = None,
    signal: CancellationSignal | None = None,
    child_runner: ChildRunnerHostService | None = None,
) -> P3LiveResult:
    """One fixed two-call small verification with finite application limits."""
    active_signal = signal if signal is not None else operator._NeverCancelled()
    if active_signal.cancelled:
        raise asyncio.CancelledError()
    try:
        limits = bounded_text_limits() if limits is None else limits
        identity_summary = prime._text_identity_summary()
        private_root = private_root.absolute()
        private_root.mkdir(mode=0o700, parents=True, exist_ok=False)
        run_id = "p3-live-" + secrets.token_hex(12)
        identity = operator._build_identity(
            private_root=private_root, generation=1, session_id=run_id,
            continuation_id="p3-live-continuation",
            worker_sha=_digest({"session_lease": run_id, "role": "root"}),
            pi_command_sha256=identity_summary.command_sha256,
            extension_binding_fingerprint=identity_summary.binding_sha256,
            ceilings_sha256=_digest(dict(P3_RUNTIME_OPTIONS)),
        )
        resources = operator._OperatorResources(
            mode="live", private_root=private_root, root_run_id=run_id,
            root_identity=identity,
            child_identity=replace(
                identity.bump_generation(),
                worker_identity_sha256=_digest({"session_lease": run_id, "role": "child"}),
            ),
            child_runner=child_runner if child_runner is not None else await operator._open_child_runner(),
            p3_oracle=P3Oracle(), pi_extension=prime, private_trace=None,
        )
        host = P3LiveHost(resources, prime, limits)
        async with asyncio.timeout(60):
            public = await operator._invoke_composed_success(
                resources, active_signal, session_backend=host,
            )
        return P3LiveResult(
            **asdict(public), model_call_count=len(host._usage),
            input_tokens=sum(u["input_tokens"] for u in host._usage),
            output_tokens=sum(u["output_tokens"] for u in host._usage),
            cost_micros=sum(u["cost_micros"] for u in host._usage),
            evidence_sha256=host.evidence_sha256,
        )
    except asyncio.CancelledError:
        raise asyncio.CancelledError() from None
    except Exception:
        raise P3LiveError() from None
    finally:
        async with asyncio.timeout(5):
            cleanup = await prime.close()
        if not cleanup.complete:
            raise P3LiveError()


__all__ = ("P3LiveError", "P3LiveHost", "P3LiveResult", "run_live_verification")
