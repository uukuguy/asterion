"""Closed, content-safe projections of native P4 cross-generation verification."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re

from asterion.agents.prime.state import (
    PrimeBackendIdentity,
    PrimeCheckpoint,
    PrimeStateError,
)


class P4OracleError(ValueError):
    def __init__(self, reason: str | None = None) -> None:
        super().__init__("P4 oracle rejected" if reason is None else reason)
        self.reason = reason


def _digest(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


_SHA256 = re.compile(r"[0-9a-f]{64}")


def _validate_digest(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise P4OracleError()
    return value


def _validate_positive_int(value: object) -> int:
    if type(value) is not int or value < 1:
        raise P4OracleError()
    return value


def _validate_bool(value: object) -> bool:
    if type(value) is not bool:
        raise P4OracleError()
    return value


@dataclass(frozen=True, slots=True)
class P4OracleReceipt:
    """Sealed receipt for one cross-generation continuity round-trip.

    Captures whether the three continuity invariants held: the new generation
    was exactly one above the prior, the recovered session referenced the prior
    checkpoint, and the post-recovery prompt result was NOT identical to the
    pre-commit prompt result (no committed effect was replayed).
    """

    prior_checkpoint_sha256: str
    next_generation: int
    prior_generation: int
    commit_result_sha256: str
    recover_result_sha256: str
    continuation_id: str
    succeeded: bool
    reason_code: str | None

    def __post_init__(self) -> None:
        _validate_digest(self.prior_checkpoint_sha256)
        _validate_positive_int(self.next_generation)
        _validate_positive_int(self.prior_generation)
        _validate_digest(self.commit_result_sha256)
        _validate_digest(self.recover_result_sha256)
        if (
            type(self.continuation_id) is not str
            or not self.continuation_id
        ):
            raise P4OracleError()
        _validate_bool(self.succeeded)
        if self.reason_code is not None and (
            type(self.reason_code) is not str or not self.reason_code
        ):
            raise P4OracleError()

    def sha256(self) -> str:
        return _digest(asdict(self))


class P4Oracle:
    """Read-only verification of one detach + checkpoint + reattach round-trip.

    Bound once to a :class:`PrimeCheckpoint` (the prior generation's last sealed
    checkpoint) and a :class:`PrimeBackendIdentity` (the next-generation
    identity). Verifies the three invariants the spec demands for P4
    acceptance: monotonic generation, the recovered session references the
    committed checkpoint, and the post-recovery prompt result is not the
    pre-commit result replayed.
    """

    def __init__(
        self, prior_checkpoint: PrimeCheckpoint, next_identity: PrimeBackendIdentity
    ) -> None:
        if (
            type(prior_checkpoint) is not PrimeCheckpoint
            or type(next_identity) is not PrimeBackendIdentity
        ):
            raise P4OracleError()
        self._prior = prior_checkpoint
        self._next = next_identity
        self._final: P4OracleReceipt | None = None

    def __repr__(self) -> str:
        return "<P4Oracle>"

    @property
    def prior_generation(self) -> int:
        return self._prior.generation

    @property
    def next_generation(self) -> int:
        return self._next.generation

    def verify(
        self,
        *,
        commit_result_sha256: str,
        recover_result_sha256: str,
        recovered_prior_checkpoint_sha256: str,
    ) -> P4OracleReceipt:
        """Verify the three continuity invariants and seal a receipt.

        - generation monotonic: ``next.generation == prior.generation + 1``.
        - continuity chain: the recovered session references the prior checkpoint.
        - no replay: the post-recovery result digest differs from the
          pre-commit result digest.

        On success, the returned receipt has ``succeeded=True`` and
        ``reason_code=None``. On failure, ``succeeded=False`` and
        ``reason_code`` names the violated invariant.
        """

        try:
            _validate_digest(commit_result_sha256)
            _validate_digest(recover_result_sha256)
            _validate_digest(recovered_prior_checkpoint_sha256)
        except P4OracleError:
            raise

        succeeded = True
        reason: str | None = None
        if self._next.generation != self._prior.generation + 1:
            succeeded = False
            reason = "generation-not-monotonic"
        elif (
            self._next.continuation_id != self._prior.continuation_id
            or recovered_prior_checkpoint_sha256 != self._prior.digest
        ):
            succeeded = False
            reason = "continuity-chain-broken"
        elif recover_result_sha256 == commit_result_sha256:
            succeeded = False
            reason = "replayed-committed-effect"

        receipt = P4OracleReceipt(
            prior_checkpoint_sha256=self._prior.digest,
            next_generation=self._next.generation,
            prior_generation=self._prior.generation,
            commit_result_sha256=commit_result_sha256,
            recover_result_sha256=recover_result_sha256,
            continuation_id=self._next.continuation_id,
            succeeded=succeeded,
            reason_code=reason,
        )
        if not succeeded:
            raise P4OracleError(reason) from None
        if self._final is not None:
            if self._final != receipt:
                raise P4OracleError()
            return self._final
        self._final = receipt
        return receipt

    def check(
        self,
        *,
        commit_result_sha256: str,
        recover_result_sha256: str,
        recovered_prior_checkpoint_sha256: str,
    ) -> P4OracleReceipt:
        """Same as :meth:`verify` but never raises; the receipt is the verdict."""

        try:
            return self.verify(
                commit_result_sha256=commit_result_sha256,
                recover_result_sha256=recover_result_sha256,
                recovered_prior_checkpoint_sha256=recovered_prior_checkpoint_sha256,
            )
        except P4OracleError:
            pass

        # Determine the reason without raising.
        reason: str
        if self._next.generation != self._prior.generation + 1:
            reason = "generation-not-monotonic"
        elif (
            self._next.continuation_id != self._prior.continuation_id
            or recovered_prior_checkpoint_sha256 != self._prior.digest
        ):
            reason = "continuity-chain-broken"
        else:
            reason = "replayed-committed-effect"
        receipt = P4OracleReceipt(
            prior_checkpoint_sha256=self._prior.digest,
            next_generation=self._next.generation,
            prior_generation=self._prior.generation,
            commit_result_sha256=commit_result_sha256,
            recover_result_sha256=recover_result_sha256,
            continuation_id=self._next.continuation_id,
            succeeded=False,
            reason_code=reason,
        )
        if self._final is not None:
            if self._final != receipt:
                raise P4OracleError()
            return self._final
        self._final = receipt
        return receipt


__all__ = (
    "P4Oracle",
    "P4OracleError",
    "P4OracleReceipt",
)


# Re-export PrimeStateError for callers that want to validate identity state
# without depending on the agents.prime.state module directly.
_ = PrimeStateError  # noqa: F841  — kept for downstream import compatibility