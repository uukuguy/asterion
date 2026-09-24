"""Application-owned private trace and public solve-receipt boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcBroker, ArcRunReceipt, ArcTransition
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.score import partial_game_score
from asterion.capabilities.prime_arc_agi_3_solver.host import (
    PrimeArcAgi3SolveReceipt,
)


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
P7_TRACE_IDENTITIES = {
    "application_id": "prime.arc-agi-3-solving",
    "application_version": "1.0.0",
    "model_id": "deepseek-v4-flash",
    "reasoning_id": "asterion.prime",
    "runtime_id": "asterion.prime",
}


class P7PrivateTraceReceiptError(RuntimeError):
    """The private trace cannot publish the requested public receipt."""


@dataclass(frozen=True, repr=False, slots=True)
class P7PrivateTraceReceipt:
    """Seal one terminal broker run into private evidence and a safe receipt."""

    _broker: ArcBroker
    _recorder: PrimeTraceRecorder
    _accessed: bool = field(default=False, init=False, compare=False)

    def __post_init__(self) -> None:
        if (
            type(self._broker) is not ArcBroker
            or type(self._broker.game) is not P7GameSelection
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
                    "game_id": broker_receipt.game_id,
                    "seed": broker_receipt.seed,
                    "win_levels": self._broker.game.win_levels,
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

    def _receipt_for(
        self, run_id: str, broker_receipt: ArcRunReceipt
    ) -> PrimeArcAgi3SolveReceipt:
        if (
            type(broker_receipt) is not ArcRunReceipt
            or (broker_receipt.game_id, broker_receipt.seed)
            != (self._broker.game.game_id, self._broker.game.seed)
            or broker_receipt.levels_completed != self._broker.game.target_level
            or broker_receipt.terminal_reason != (
                "game-won" if self._broker.game.is_full_game else "level-completed"
            )
            or (
                self._broker.game.is_full_game
                and self._broker.terminal_snapshot().observation.state != "WIN"
            )
        ):
            raise ValueError
        action_counts = self._completed_level_action_counts(broker_receipt)
        return PrimeArcAgi3SolveReceipt.create(
            run_id=run_id,
            completed_level_count=broker_receipt.levels_completed,
            primitive_action_count=broker_receipt.primitive_actions,
            partial_game_score=partial_game_score(action_counts, self._broker.game),
        )

    def _completed_level_action_counts(
        self, broker_receipt: ArcRunReceipt
    ) -> tuple[int, ...]:
        """Recover each completed level's action count from ordered transitions."""

        previous_sequence = 0
        previous_completion_sequence = 0
        levels_completed = 0
        counts: list[int] = []
        for transition in self._broker.journal:
            if (
                type(transition) is not ArcTransition
                or transition.sequence != previous_sequence + 1
                or transition.levels_completed < levels_completed
                or transition.levels_completed > levels_completed + 1
            ):
                raise ValueError
            previous_sequence = transition.sequence
            if transition.levels_completed == levels_completed + 1:
                counts.append(transition.sequence - previous_completion_sequence)
                previous_completion_sequence = transition.sequence
                levels_completed = transition.levels_completed
        if (
            previous_sequence != broker_receipt.primitive_actions
            or levels_completed != broker_receipt.levels_completed
            or len(counts) != self._broker.game.target_level
        ):
            raise ValueError
        return tuple(counts)


__all__ = (
    "P7PrivateTraceReceipt",
    "P7PrivateTraceReceiptError",
)
