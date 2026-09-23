"""Bounded P5 model proposal verified against a fixed semantic task.

The model supplies candidate artifacts. The local verifier computes every
verdict from those artifacts; the existing P5 loop owns repair admission and
the public composed route owns the terminal receipt.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
from typing import Protocol

from asterion.applications.prime.p5 import operator
from asterion.applications.prime.live_model import (
    LiveModelSession,
    resolve_live_model_launch,
)
from asterion.applications.prime.p5.oracle import P5Oracle
from asterion.applications.prime.p5.runtime_binding import P5_RUNTIME_OPTIONS
from asterion.applications.prime.services import (
    P5ProposeStep,
    P5RepairStep,
    P5VerifyStep,
)
from asterion.runtime.host import CancellationSignal


class P5LiveError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("P5 live verification failed")


class ModelSession(Protocol):
    async def open(self, *, signal: CancellationSignal) -> None: ...
    async def prompt(self, text: str, *, signal: CancellationSignal) -> object: ...
    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class P5LiveResult(operator.P5PublicResult):
    model_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0
    evidence_sha256: str = ""


def _encoded(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _digest(value: object) -> str:
    return sha256(_encoded(value)).hexdigest()


def _candidate(text: object) -> dict[str, int]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise P5LiveError()
            result[key] = value
        return result

    if type(text) is not str or len(text.encode()) > 4096:
        raise P5LiveError()
    try:
        value = json.loads(text, object_pairs_hook=unique)
    except (ValueError, TypeError):
        raise P5LiveError() from None
    if (
        type(value) is not dict
        or set(value) != {"offset"}
        or type(value["offset"]) is not int
        or not -100 <= value["offset"] <= 100
    ):
        raise P5LiveError()
    return value


class _CandidateWork:
    def __init__(self, session: ModelSession, run_id: str) -> None:
        self.session = session
        self.run_id = run_id
        self.candidates: list[dict[str, int]] = []
        self.verdicts: list[dict[str, object]] = []
        self.usage: list[dict[str, int]] = []
        self.feedback: str | None = None

    async def _ask(
        self, prompt: str, signal: CancellationSignal | None
    ) -> dict[str, int]:
        active = signal if signal is not None else operator._NeverCancelled()
        if active.cancelled:
            raise asyncio.CancelledError()
        reply = await self.session.prompt(prompt, signal=active)
        usage = {
            key: getattr(reply.usage, key)
            for key in ("input_tokens", "output_tokens", "cost_micros")
        }
        if (
            any(type(value) is not int or value < 0 for value in usage.values())
            or usage["input_tokens"] + usage["output_tokens"] == 0
        ):
            raise P5LiveError()
        candidate = _candidate(reply.text)
        self.usage.append(usage)
        self.candidates.append(candidate)
        return candidate

    async def propose(self, signal: CancellationSignal | None) -> P5ProposeStep:
        candidate = await self._ask(
            "Fixed task: choose one integer offset for f(x) = 3*x + offset "
            "so f(-2)=-4, f(0)=2, and f(3)=11. "
            'Return only JSON with one integer key "offset". Use no tools.',
            signal,
        )
        return P5ProposeStep(f"propose-{self.run_id}", _digest(candidate))

    async def verify(self, signal: CancellationSignal | None) -> P5VerifyStep:
        if signal is not None and signal.cancelled:
            raise asyncio.CancelledError()
        if not self.candidates:
            raise P5LiveError()
        candidate = self.candidates[-1]
        failure = next(
            (
                (value, 3 * value + 2, 3 * value + candidate["offset"])
                for value in (-2, 0, 3)
                if 3 * value + candidate["offset"] != 3 * value + 2
            ),
            None,
        )
        verdict = "pass" if failure is None else "fail"
        self.feedback = (
            None
            if failure is None
            else (f"For x={failure[0]}, expected {failure[1]}, observed {failure[2]}.")
        )
        self.verdicts.append(
            {
                "candidate_sha256": _digest(candidate),
                "verdict": verdict,
                "failed_case": failure,
            }
        )
        return P5VerifyStep(
            f"verify-{self.run_id}-{len(self.verdicts)}",
            verdict,
            _digest(self.verdicts[-1]),
        )

    async def repair(self, signal: CancellationSignal | None) -> P5RepairStep:
        if self.feedback is None:
            raise P5LiveError()
        candidate = await self._ask(
            "Repair your prior candidate for f(x)=3*x+offset. "
            + self.feedback
            + ' Return only JSON with one integer key "offset". Use no tools.',
            signal,
        )
        return P5RepairStep(
            f"repair-{self.run_id}-{len(self.candidates) - 1}", _digest(candidate)
        )


async def run_live_verification(
    *,
    session_factory: Callable[[str, Path], ModelSession],
    private_root: Path,
    command_sha256: str,
    binding_sha256: str,
    signal: CancellationSignal | None = None,
) -> P5LiveResult:
    """Run one fixed model proposal through semantic verification and P5 composition."""
    active = signal if signal is not None else operator._NeverCancelled()
    if active.cancelled:
        raise asyncio.CancelledError()
    session: ModelSession | None = None
    try:
        root = private_root.absolute()
        root.mkdir(parents=True, mode=0o700, exist_ok=False)
        run_id = "p5-live-" + secrets.token_hex(12)
        identity = operator._build_identity(
            private_root=root,
            generation=1,
            session_id=run_id,
            continuation_id="p5-live-continuation",
            worker_sha=_digest({"session_lease": run_id}),
            pi_command_sha256=command_sha256,
            extension_binding_fingerprint=binding_sha256,
            ceilings_sha256=_digest(dict(P5_RUNTIME_OPTIONS)),
        )
        session = session_factory("loop", root)
        resources = operator._OperatorResources(
            mode="live",
            private_root=root,
            root_run_id=run_id,
            root_identity=identity,
            p5_oracle=P5Oracle(),
            pi_extension=session,
            private_trace=None,
        )
        work = _CandidateWork(session, run_id)
        await session.open(signal=active)
        loop = await operator._open_bounded_autonomy_loop(
            work.propose,
            work.verify,
            work.repair,
        )
        receipt = await operator._run_composed_loop(
            loop,
            resources,
            signal=active,
            finalize=session.close,
        )
        if receipt.terminal_reason != "success":
            raise P5LiveError()
        session = None
        evidence = {
            "candidates": work.candidates,
            "verdicts": work.verdicts,
            "usage": work.usage,
            "receipt": asdict(receipt),
            "session_closed": True,
        }
        raw = _encoded(evidence)
        path = root / "live-evidence.json"
        with path.open("xb") as stream:
            path.chmod(0o600)
            stream.write(raw)
        public = operator.P5PublicResult(
            status="completed",
            **asdict(receipt),
        )
        return P5LiveResult(
            **asdict(public),
            model_call_count=len(work.usage),
            input_tokens=sum(item["input_tokens"] for item in work.usage),
            output_tokens=sum(item["output_tokens"] for item in work.usage),
            cost_micros=sum(item["cost_micros"] for item in work.usage),
            evidence_sha256=sha256(raw).hexdigest(),
        )
    except asyncio.CancelledError:
        raise asyncio.CancelledError() from None
    except Exception:
        raise P5LiveError() from None
    finally:
        if session is not None:
            async with asyncio.timeout(5):
                await session.close()


async def run_operator_live(environment: dict[str, str]) -> P5LiveResult:
    """Resolve the one operator preset and run without user model settings."""
    try:
        root_text = environment["ASTERION_PRIME_OPERATOR_ROOT"]
        private_text = environment["ASTERION_PRIME_P5_PRIVATE_ROOT"]
        if not root_text or not private_text:
            raise ValueError
        private_base = Path(private_text).resolve()
        private_base.mkdir(mode=0o700, parents=True, exist_ok=True)
        private_root = private_base / ("live-" + secrets.token_hex(12))
        launch = resolve_live_model_launch(Path(root_text), environment)
        return await run_live_verification(
            session_factory=lambda role, cwd: LiveModelSession(
                command=launch.command,
                environment=launch.environment,
                cwd=launch.cwd,
            ),
            private_root=private_root,
            command_sha256=_digest(launch.command),
            binding_sha256=_digest({"extension": "none", "task": "p5-offset"}),
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        raise P5LiveError() from None


def main() -> int:
    try:
        result = asyncio.run(run_operator_live(dict(os.environ)))
    except BaseException:
        print('{"status":"unavailable"}')
        return 2
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "P5LiveError",
    "P5LiveResult",
    "run_live_verification",
    "run_operator_live",
    "main",
)
