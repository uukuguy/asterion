"""Private per-game trace boundary for official ARC-AGI-3 gameplay."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
import sys
from types import MappingProxyType

from asterion.agents.prime.execution import PrimeRoundDiagnostic
from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcBroker, ArcRunReceipt
from asterion.applications.prime.p7.game import ArcGameContract
from asterion.applications.prime.p7.model_selection import (
    DEFAULT_MODEL,
    P7ModelSelectionError,
    valid_selection_name,
)
from asterion.capabilities.prime_arc_agi_3_gameplay.host import (
    PrimeArcAgi3GameplayEvidence,
    validate_prime_arc_agi_3_gameplay_evidence,
)


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
# The identity of the default selection. Runs that select another model
# record that model through ``trace_identities_for``; the four non-model
# fields are the stable application identity.
GAMEPLAY_TRACE_IDENTITIES = {
    "application_id": "prime.arc-agi-3-gameplay",
    "application_version": "1.0.0",
    "model_id": DEFAULT_MODEL,
    "reasoning_id": "asterion.prime",
    "runtime_id": "asterion.prime",
}


def trace_identities_for(model_id: str) -> dict[str, str]:
    """Return the P7 gameplay trace identity for one selected model."""

    if not valid_selection_name(model_id):
        raise P7ModelSelectionError("P7 model selection is invalid")
    return {**GAMEPLAY_TRACE_IDENTITIES, "model_id": model_id}


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
    _identities: Mapping[str, str] | None = field(default=None, compare=False)
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
        declared = (
            GAMEPLAY_TRACE_IDENTITIES if self._identities is None else self._identities
        )
        stable = {
            name: item for name, item in GAMEPLAY_TRACE_IDENTITIES.items()
            if name != "model_id"
        }
        if (
            not isinstance(declared, Mapping)
            or {name: item for name, item in declared.items() if name != "model_id"} != stable
        ):
            raise PrimeGameplayTraceError("P7 gameplay evidence is unavailable")
        object.__setattr__(self, "_identities", dict(declared))

    def __repr__(self) -> str:
        return "<PrimeGameplayTrace redacted>"

    @property
    def identities(self) -> Mapping[str, str]:
        """Return the exact trace identity this trace records."""

        return MappingProxyType(dict(self._identities or GAMEPLAY_TRACE_IDENTITIES))

    @property
    def runtime_recorder(self) -> PrimeTraceRecorder:
        return self._recorder

    def record_model_round(self, diagnostic: PrimeRoundDiagnostic) -> None:
        """Print bounded model-round signals without exposing model prose."""

        if type(diagnostic) is not PrimeRoundDiagnostic or self._accessed:
            raise PrimeGameplayTraceError("P7 gameplay evidence is unavailable")
        signals = "、".join(diagnostic.output_signals) if diagnostic.output_signals else "无"
        print(
            f"[p7] P7推理轮次：第 {diagnostic.round_index + 1} 轮；模型输出信号={signals}。",
            file=sys.stderr,
            flush=True,
        )

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
                self._identities,
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
                self._identities,
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
    "trace_identities_for",
)
