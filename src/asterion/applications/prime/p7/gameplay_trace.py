"""Private per-game trace boundary for official ARC-AGI-3 gameplay."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcBroker, ArcRunReceipt
from asterion.applications.prime.p7.game import ArcGameContract
from asterion.capabilities.prime_arc_agi_3_gameplay.host import (
    PrimeArcAgi3GameplayEvidence,
    validate_prime_arc_agi_3_gameplay_evidence,
)


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
GAMEPLAY_TRACE_IDENTITIES = {
    "application_id": "prime.arc-agi-3-gameplay",
    "application_version": "1.0.0",
    "model_id": "gpt-6-sol",
    "reasoning_id": "asterion.prime",
    "runtime_id": "asterion.prime",
}


class PrimeGameplayTraceError(RuntimeError):
    """The private gameplay trace cannot publish evidence."""


@dataclass(frozen=True, repr=False, slots=True)
class PrimeGameplayTrace:
    """Seal one official game into scoreless private evidence.

    The accessor deliberately accepts only an ``ArcGameContract``. Local P7
    solving retains its separate receipt and replay boundary.
    """

    _broker: ArcBroker
    _recorder: PrimeTraceRecorder
    _guid: str
    _accessed: bool = field(default=False, init=False, compare=False)
    _evidence: PrimeArcAgi3GameplayEvidence | None = field(
        default=None, init=False, compare=False
    )

    def __post_init__(self) -> None:
        if (
            type(self._broker) is not ArcBroker
            or type(self._broker.game) is not ArcGameContract
            or type(self._recorder) is not PrimeTraceRecorder
            or type(self._guid) is not str
            or not self._guid
            or len(self._guid) > 256
            or not self._guid.isascii()
            or any(ord(char) <= 32 or ord(char) == 127 for char in self._guid)
        ):
            raise PrimeGameplayTraceError("P7 gameplay evidence is unavailable")

    def __repr__(self) -> str:
        return "<PrimeGameplayTrace redacted>"

    @property
    def runtime_recorder(self) -> PrimeTraceRecorder:
        return self._recorder

    def matches_runtime_broker(self, broker: object) -> bool:
        return broker is self._broker

    def record_usage(self, *, input_tokens: int, output_tokens: int) -> None:
        if (
            self._accessed
            or isinstance(input_tokens, bool)
            or type(input_tokens) is not int
            or input_tokens < 0
            or isinstance(output_tokens, bool)
            or type(output_tokens) is not int
            or output_tokens < 0
        ):
            raise PrimeGameplayTraceError("P7 gameplay usage is invalid")
        try:
            self._recorder.append(
                "arc.usage.reported",
                GAMEPLAY_TRACE_IDENTITIES,
                {"input_tokens": input_tokens, "output_tokens": output_tokens},
            )
        except Exception:
            raise PrimeGameplayTraceError("P7 gameplay usage is invalid") from None

    def expected_evidence_sha256(self, *, run_id: str) -> str:
        """Finalize terminal broker and trace state and return its digest."""
        if self._accessed:
            raise PrimeGameplayTraceError("P7 gameplay evidence is unavailable")
        try:
            evidence = self._build_evidence(run_id)
            self._recorder.append(
                "arc.run.completed",
                GAMEPLAY_TRACE_IDENTITIES,
                {
                    "game_id": evidence.game_id,
                    "guid": evidence.guid,
                    "win_levels": evidence.win_levels,
                    "action_cap": evidence.action_cap,
                    "completed_level_count": evidence.completed_level_count,
                    "primitive_action_count": evidence.primitive_action_count,
                    "sdk_state": evidence.sdk_state,
                    "terminal_reason": evidence.terminal_reason,
                },
            )
            trace_sha256 = self._recorder.seal().final_sha256
            evidence = PrimeArcAgi3GameplayEvidence.create(
                run_id=evidence.run_id,
                game_id=evidence.game_id,
                guid=evidence.guid,
                win_levels=evidence.win_levels,
                action_cap=evidence.action_cap,
                completed_level_count=evidence.completed_level_count,
                primitive_action_count=evidence.primitive_action_count,
                sdk_state=evidence.sdk_state,
                terminal_reason=evidence.terminal_reason,
                trace_sha256=trace_sha256,
            )
            validate_prime_arc_agi_3_gameplay_evidence(evidence)
            object.__setattr__(self, "_evidence", evidence)
            object.__setattr__(self, "_accessed", True)
            return evidence.evidence_sha256
        except Exception:
            self._recorder.close()
            raise PrimeGameplayTraceError(
                "P7 gameplay evidence is unavailable"
            ) from None

    def get_evidence(
        self, *, run_id: str, evidence_sha256: str
    ) -> PrimeArcAgi3GameplayEvidence:
        if (
            type(evidence_sha256) is not str
            or _DIGEST.fullmatch(evidence_sha256) is None
            or self._evidence is None
            or self._evidence.run_id != run_id
            or self._evidence.evidence_sha256 != evidence_sha256
        ):
            raise PrimeGameplayTraceError("P7 gameplay evidence is unavailable")
        return self._evidence

    def close(self) -> None:
        object.__setattr__(self, "_accessed", True)
        self._recorder.close()

    def _build_evidence(self, run_id: str) -> PrimeArcAgi3GameplayEvidence:
        if type(run_id) is not str or not run_id:
            raise ValueError
        receipt = self._broker.seal()
        snapshot = self._broker.terminal_snapshot()
        if type(receipt) is not ArcRunReceipt:
            raise ValueError
        state = snapshot.observation.state
        reason = receipt.terminal_reason
        if state == "WIN" and reason != "game-won":
            raise ValueError
        if state != "WIN" and reason == "game-won":
            raise ValueError
        return PrimeArcAgi3GameplayEvidence.create(
            run_id=run_id,
            game_id=receipt.game_id,
            guid=self._guid,
            win_levels=self._broker.game.win_levels,
            action_cap=self._broker.game.action_cap,
            completed_level_count=receipt.levels_completed,
            primitive_action_count=receipt.primitive_actions,
            sdk_state=state,
            terminal_reason=reason,
            trace_sha256="sha256:" + "0" * 64,
        )


__all__ = (
    "GAMEPLAY_TRACE_IDENTITIES",
    "PrimeGameplayTrace",
    "PrimeGameplayTraceError",
)
