"""Application-owned private trace and public solve-receipt boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
import re

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcBroker, ArcRunReceipt
from asterion.capabilities.prime_arc_agi_3_solver.host import (
    PrimeArcAgi3SolveReceipt,
)


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SIX_PLACES = Decimal("0.000001")
P7_TRACE_IDENTITIES = {
    "application_id": "prime.arc-agi-3-solving",
    "application_version": "1.0.0",
    "model_id": "deepseek-v4-flash",
    "reasoning_id": "asterion.prime",
    "runtime_id": "asterion.prime",
}


class P7PrivateTraceReceiptError(RuntimeError):
    """The private trace cannot publish the requested public receipt."""


def _partial_score(action_count: int) -> str:
    if type(action_count) is not int or action_count <= 0:
        raise ValueError
    completed_fraction = Decimal(100) / Decimal(28)
    efficiency = min(
        Decimal(115),
        (Decimal(22) / Decimal(action_count)) ** 2 * Decimal(100),
    ) / Decimal(28)
    return format(
        min(completed_fraction, efficiency).quantize(
            _SIX_PLACES, rounding=ROUND_HALF_UP
        ),
        ".6f",
    )


@dataclass(frozen=True, repr=False, slots=True)
class P7PrivateTraceReceipt:
    """Seal one terminal broker run into private evidence and a safe receipt."""

    _broker: ArcBroker
    _recorder: PrimeTraceRecorder
    _accessed: bool = field(default=False, init=False, compare=False)

    def __post_init__(self) -> None:
        if (
            type(self._broker) is not ArcBroker
            or type(self._recorder) is not PrimeTraceRecorder
        ):
            raise P7PrivateTraceReceiptError("P7 solve receipt is unavailable")

    def __repr__(self) -> str:
        return "<P7PrivateTraceReceipt redacted>"

    @property
    def runtime_recorder(self) -> PrimeTraceRecorder:
        """Expose only the typed recorder required by the selected runtime."""

        return self._recorder

    def matches_runtime_broker(self, broker: object) -> bool:
        """Confirm that runtime and receipt paths share one exact broker."""

        return broker is self._broker

    def record_usage(self, *, input_tokens: int, output_tokens: int) -> None:
        """Append one validated public runtime usage event to private evidence."""

        if (
            self._accessed
            or isinstance(input_tokens, bool)
            or type(input_tokens) is not int
            or input_tokens < 0
            or isinstance(output_tokens, bool)
            or type(output_tokens) is not int
            or output_tokens < 0
        ):
            raise P7PrivateTraceReceiptError("P7 usage evidence is invalid")
        try:
            self._recorder.append(
                "arc.usage.reported",
                P7_TRACE_IDENTITIES,
                {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            )
        except Exception:
            raise P7PrivateTraceReceiptError(
                "P7 usage evidence is invalid"
            ) from None

    def close(self) -> None:
        """Release an unpublished trace and prevent later receipt access."""

        object.__setattr__(self, "_accessed", True)
        self._recorder.close()

    def get_receipt(
        self, *, run_id: str, receipt_sha256: str
    ) -> PrimeArcAgi3SolveReceipt:
        """Publish exactly one receipt after the fixed broker reaches a level."""

        if self._accessed:
            raise P7PrivateTraceReceiptError("P7 solve receipt is unavailable")
        object.__setattr__(self, "_accessed", True)
        try:
            if (
                type(run_id) is not str
                or type(receipt_sha256) is not str
                or _DIGEST.fullmatch(receipt_sha256) is None
            ):
                raise ValueError
            broker_receipt = self._broker.seal()
            receipt = self._receipt_for(run_id, broker_receipt)
            if receipt.receipt_sha256 != receipt_sha256:
                raise ValueError
            self._recorder.append(
                "arc.run.completed",
                P7_TRACE_IDENTITIES,
                {
                    "levels_completed": broker_receipt.levels_completed,
                    "primitive_actions": broker_receipt.primitive_actions,
                    "replay_sha256": broker_receipt.replay_sha256,
                    "terminal_reason": broker_receipt.terminal_reason,
                },
            )
            self._recorder.seal()
            return receipt
        except Exception:
            self._recorder.close()
            raise P7PrivateTraceReceiptError(
                "P7 solve receipt is unavailable"
            ) from None

    def expected_receipt_sha256(self, *, run_id: str) -> str:
        """Return the pending public receipt identity without sealing its trace."""

        if self._accessed:
            raise P7PrivateTraceReceiptError("P7 solve receipt is unavailable")
        try:
            return self._receipt_for(run_id, self._broker.seal()).receipt_sha256
        except Exception:
            raise P7PrivateTraceReceiptError(
                "P7 solve receipt is unavailable"
            ) from None

    @staticmethod
    def _receipt_for(
        run_id: str, broker_receipt: ArcRunReceipt
    ) -> PrimeArcAgi3SolveReceipt:
        if (
            type(broker_receipt) is not ArcRunReceipt
            or broker_receipt.levels_completed != 1
            or broker_receipt.terminal_reason != "level-completed"
        ):
            raise ValueError
        return PrimeArcAgi3SolveReceipt.create(
            run_id=run_id,
            completed_level_count=broker_receipt.levels_completed,
            primitive_action_count=broker_receipt.primitive_actions,
            partial_game_score=_partial_score(broker_receipt.primitive_actions),
        )


__all__ = (
    "P7PrivateTraceReceipt",
    "P7PrivateTraceReceiptError",
)
