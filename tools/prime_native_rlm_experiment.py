"""Pure preparation boundary for one bounded native Prime RLM experiment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from asterion.control.authority import AuthorityEnvelope
from tools.verify_prime_loop import PrimeVerificationError, load_bounded_rlm_authority


_MAX_COST_MICROS = 500_000
_MAX_DEADLINE_MS = 600_000
_MODEL_KEY = "ASTERION_PRIME_EXPERIMENT_MODEL"


class PrimeRlmExperimentError(RuntimeError):
    """Raised with a public-safe native RLM experiment preparation failure."""


@dataclass(frozen=True, repr=False)
class NativeRlmExperimentLimits:
    cost_micros: int
    deadline_ms: int


@dataclass(frozen=True, repr=False)
class NativeRlmExperimentReservation:
    authority: AuthorityEnvelope
    limits: NativeRlmExperimentLimits
    configuration_digest: str
    consumed: bool = False

    def consume(self) -> NativeRlmExperimentReservation:
        if self.consumed:
            raise PrimeRlmExperimentError("Native RLM experiment reservation is inactive")
        return replace(self, consumed=True)


def prepare_native_rlm_experiment(
    authority_path: Path,
    *,
    max_cost_micros: int,
    deadline_ms: int,
    environ: Mapping[str, str],
    now_ms: int | None = None,
) -> NativeRlmExperimentReservation:
    """Validate all non-executing admission inputs without reading process state."""
    try:
        if (
            not isinstance(authority_path, Path)
            or not isinstance(environ, Mapping)
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in environ.items())
            or isinstance(max_cost_micros, bool)
            or not isinstance(max_cost_micros, int)
            or max_cost_micros < 1
            or max_cost_micros > _MAX_COST_MICROS
            or isinstance(deadline_ms, bool)
            or not isinstance(deadline_ms, int)
            or deadline_ms < 1
            or deadline_ms > _MAX_DEADLINE_MS
        ):
            raise ValueError
        model = environ.get(_MODEL_KEY)
        if not isinstance(model, str) or not model:
            raise ValueError
        authority = load_bounded_rlm_authority(
            authority_path, max_cost_micros=max_cost_micros, now_ms=now_ms
        )
        if authority.max_action_deadline_ms > deadline_ms:
            raise ValueError
        digest = sha256(b"asterion.prime.native-rlm\0" + model.encode()).hexdigest()
        return NativeRlmExperimentReservation(
            authority=authority,
            limits=NativeRlmExperimentLimits(max_cost_micros, deadline_ms),
            configuration_digest=digest,
        )
    except (PrimeVerificationError, TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM experiment authorization is invalid") from None
