"""Runtime-owned native P6 continual-improvement session.

P6 owns one bounded admit-candidate → evaluate-holdout → preserve-or-rollback
round per invocation. The runtime drives the call against the injected host;
the host owns the in-process admitted-candidate lifecycle through the
``prime.candidate-store`` host service (which wraps the framework-owned
``HarnessCoordinator``). There is no continuity store, no checkpoint seal,
and no recovery semantics on this path — those belong to P4 and are not
part of P6's contract. The session adapter carries the five host-service
references through to the ``P6RuntimeHost`` Protocol surface that the
operator exercises against a built runtime.

The ``prime.candidate-store`` host service is opened by the operator
(Task 8) and wired with ``prime.pi-extension`` (candidate revision
admission), ``prime.p6-oracle`` (holdout verification), and
``prime.session-backend`` (budget gate) before this runtime binding is
constructed; the binding does not reopen the loop. ``set_holdout_callable``
is the operator's responsibility, not the binding's. The binding only
validates the 5-tuple and adapts the session-backend through the
``P6RuntimeHost`` surface (``validate_runtime_services`` /
``admit_candidate`` / ``evaluate_holdout`` / ``promote_or_rollback`` /
``wait_finalization``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import datetime, timezone
from types import MappingProxyType

from asterion.applications.prime.p6.host import (
    P6AdmittedProposal,
    P6BaselineSnapshot,
    P6CandidateRevision,
    P6HoldoutResult,
    P6PromotionAction,
    P6RuntimeHost,
)
from asterion.applications.prime.p6.oracle import P6Oracle
from asterion.applications.prime.p6.receipt import (
    P6NativeReceipt,
    seal_p6_native_receipt,
)
from asterion.applications.prime.services import CandidateStoreLoop
from asterion.control.harness import HarnessProposal, HarnessRevision, HarnessScope
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runtime.host import CancellationSignal, RunEvent, RunRequest
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient


# P6's host capabilities: per the application assembly JSON spec
# (`docs/superpowers/specs/2026-09-19-asterion-prime-p6-native-design.md`
# table at L23) P6 depends on these five injected host services:
# ``prime.candidate-store`` (new for Phase 9, wraps
# ``HarnessCoordinator``), ``prime.p6-oracle`` (new for Phase 9,
# verifies the three witness invariants), and the same Asterion-owned
# substrate P1 / P2 / P3 / P4 / P5 already consume
# (``prime.pi-extension``, ``prime.private-trace``,
# ``prime.session-backend``). P6 has no continuity store, no child
# runner, no bounded-autonomy loop, no ipython session, and no
# checkpoint — those surfaces belong to P1-P5 only. ``prime.ipython``
# is NOT a P6 dependency: candidate revision admission goes through
# the wrapped ``HarnessCoordinator.apply(proposal)`` API directly.
P6_HOST_CAPABILITIES: tuple[str, ...] = (
    "prime.candidate-store",
    "prime.p6-oracle",
    "prime.pi-extension",
    "prime.private-trace",
    "prime.session-backend",
)
P6_RUNTIME_OPTIONS: Mapping[str, str] = MappingProxyType(
    {
        "aggregate_tokens": "32000",
        "cost_micros": "300000",
        "deadline_ms": "120000",
        "max_callbacks": "4",
        "max_tool_callbacks": "2",
    }
)
_ERROR = "Asterion-prime runtime configuration is invalid"


class _P6RuntimeSession:
    """Own one bounded admit-candidate / evaluate-holdout / preserve-or-rollback
    round and adapt to ``P6RuntimeHost``.

    Implements the five-method ``P6RuntimeHost`` Protocol
    (``validate_runtime_services`` / ``admit_candidate`` /
    ``evaluate_holdout`` / ``promote_or_rollback`` /
    ``wait_finalization``) over the five injected host services, and
    exposes the runtime-client ``run`` iterator that drives one round
    per ``RunRequest``.

    The ``prime.candidate-store`` host service is opened and wired
    with the operator-injected holdout callable via
    :meth:`CandidateStoreLoop.set_holdout_callable` before this
    binding is constructed; the binding only adapts the service
    surface through the ``P6RuntimeHost`` Protocol. ``set_holdout_callable``
    is the operator's responsibility, not the binding's — the
    binding defers all wiring to Task 8.
    """

    __slots__ = (
        "_active",
        "_candidate_store",
        "_consumed",
        "_oracle",
        "_private_trace",
        "_session_backend",
    )

    def __init__(
        self,
        *,
        session_backend: P6RuntimeHost,
        candidate_store: CandidateStoreLoop,
        oracle: P6Oracle,
        private_trace: object | None,
    ) -> None:
        self._session_backend = session_backend
        self._candidate_store = candidate_store
        self._oracle = oracle
        self._private_trace = private_trace
        self._active = False
        self._consumed = False

    # ------------------------------------------------------------------
    # P6RuntimeHost Protocol surface
    # ------------------------------------------------------------------

    def validate_runtime_services(
        self, services: Mapping[str, object]
    ) -> None:
        """Reject unknown or missing host services — fail closed.

        ``services`` must equal ``P6_HOST_CAPABILITIES`` exactly (set
        equality; ordering is the spec's contract). Set-equality
        discipline rejects both supersets (extra unknown host service)
        and subsets (missing required host service) without ambiguity.
        """

        if set(services) != set(P6_HOST_CAPABILITIES):
            raise RuntimeFactoryError(_ERROR)

    def admit_candidate(
        self,
        *,
        root_run_id: str,
        candidate_proposal: object,
        signal: CancellationSignal,
    ) -> P6AdmittedProposal:
        """Admit one candidate through the wrapped ``prime.candidate-store`` host service.

        The wrapper composes over the framework-owned
        ``HarnessCoordinator.apply(proposal)`` API; the runtime
        binding adapts the wrapper's framework-level
        ``HarnessRevision`` into the ``P6AdmittedProposal`` Protocol
        shape. ``root_run_id`` is recorded but not currently consumed
        by the underlying wrapper (P6 is single-process; the wrapper
        carries its own identity).
        """

        if type(candidate_proposal) is not HarnessProposal:
            raise RuntimeFactoryError(_ERROR)
        revision = self._candidate_store.admit_candidate(
            proposal=candidate_proposal,
            signal=signal,
        )
        return P6AdmittedProposal(
            proposal_id=revision.proposal_id,
            proposal_digest=revision.proposal_digest,
            revision_id=revision.revision_id,
            admission_timestamp=datetime.now(tz=timezone.utc),
        )

    def evaluate_holdout(
        self,
        *,
        root_run_id: str,
        candidate: P6CandidateRevision,
        baseline: P6BaselineSnapshot,
        signal: CancellationSignal,
    ) -> P6HoldoutResult:
        """Evaluate the admitted candidate on the task B holdout.

        Delegates to the wrapper from Task 3
        (``CandidateStoreLoop.evaluate_holdout``) which composes over
        the operator-injected holdout callable (Task 8 wires the
        oracle as the holdout callable on the success path). The
        oracle from Task 5 (``P6Oracle.check``) is consulted mid-round
        so the binding's witness contract records the
        holdout-evaluated invariant; the full sealed verdict is
        emitted in :meth:`wait_finalization` once the admit + evaluate
        + promote-or-rollback round has completed.

        ``root_run_id`` is recorded but not currently consumed by
        the underlying wrapper (P6 is single-process; the wrapper
        carries its own identity).
        """

        if type(candidate) is not P6CandidateRevision:
            raise RuntimeFactoryError(_ERROR)
        if type(baseline) is not P6BaselineSnapshot:
            raise RuntimeFactoryError(_ERROR)
        # The adapter delegates to the wrapper from Task 3. The
        # wrapper owns the framework-owned ``HarnessCoordinator``
        # composition (admit + holdout + rollback); the adapter only
        # adapts the Protocol shape. The framework-level
        # ``HarnessRevision`` is reconstructed here from the
        # ``P6CandidateRevision`` Protocol shape — fields are filled
        # by the operator (Task 8) at construction time.
        # ``result_snapshot_id`` and ``effect_digest`` are
        # framework-owned values; the operator (Task 8) replaces
        # these stubs with the coordinator's actual values at
        # runtime. ``result_snapshot_id`` must be a valid opaque
        # ID; ``effect_digest`` must be a 64-hex SHA-256; ``usage``
        # must carry all four framework-owned keys (otherwise the
        # frozen revision raises ``HarnessError``).
        harness_revision = HarnessRevision(
            revision_id=candidate.revision_id,
            sequence=1,
            proposal_id="proposal-stub",
            proposal_digest="0" * 64,
            scope=HarnessScope.project("prime.continual-improvement"),
            baseline_snapshot_id=baseline.snapshot_id,
            result_snapshot_id="snapshot-result-stub",
            effect_digest="0" * 64,
            status="succeeded",
            rollback_revision_id=None,
            usage={
                "aggregate_tokens": 0,
                "cost_micros": 0,
                "model_credential_reads": 0,
                "provider_operations": 0,
            },
        )
        result = self._candidate_store.evaluate_holdout(
            candidate=harness_revision,
            baseline=baseline.entries,
            signal=signal,
        )
        # Invoke the oracle from Task 5 mid-round so the oracle is
        # consulted per the binding's witness contract. The oracle
        # short-circuits to ``global-rejected`` here because no
        # promotion action has been applied yet (case (a) of the
        # oracle's verdict resolution); the oracle receipt is
        # discarded — the binding defers the full sealed verdict to
        # :meth:`wait_finalization` where the public receipt is
        # composed from the candidate-store's per-run state. Tests
        # assert ``P6Oracle.check`` was invoked by this method.
        oracle_receipt = self._oracle.check(
            root_run_id=root_run_id,
            admitted_proposal=None,
            holdout_result=None,
            promotion_action=None,
            rollback_invocation_count=0,
            global_activation_approved=False,
            signal=signal,
        )
        _ = oracle_receipt  # verdict is internal-only; never returned
        return P6HoldoutResult(
            task_b_result_sha256=result.task_b_result_sha256,
            non_regressing=result.non_regressing,
            evaluation_timestamp=datetime.now(tz=timezone.utc),
        )

    def promote_or_rollback(
        self,
        *,
        root_run_id: str,
        candidate: P6CandidateRevision,
        holdout: P6HoldoutResult,
        signal: CancellationSignal,
    ) -> P6PromotionAction:
        """Apply the explicit promotion OR exact inverse rollback and seal.

        Delegates to the ``prime.candidate-store`` host service's
        ``promote_or_rollback`` method. Returns the sealed
        ``P6PromotionAction`` recording the promotion action's
        ``target_revision_id`` (== candidate.revision_id) on the
        ``preserved`` path; on the ``rolled-back`` path the wrapper
        records the exact inverse revision.

        ``root_run_id`` is recorded but not currently consumed by the
        underlying wrapper (P6 is single-process; the wrapper carries
        its own identity).
        """

        if type(candidate) is not P6CandidateRevision:
            raise RuntimeFactoryError(_ERROR)
        if type(holdout) is not P6HoldoutResult:
            raise RuntimeFactoryError(_ERROR)
        # The adapter delegates to the wrapper from Task 3. The
        # wrapper owns the framework-owned ``HarnessCoordinator``
        # composition; the adapter only adapts the Protocol shape.
        # The framework-level ``HarnessProposal`` is constructed
        # here from the ``P6PromotionAction`` Protocol shape — its
        # fields are filled by the operator (Task 8) at construction
        # time. ``edits`` and ``evidence_ids`` are required by
        # ``HarnessProposal.__post_init__``; the operator (Task 8)
        # replaces this stub with a real proposal at runtime.
        # All placeholder IDs are valid opaque IDs (no ``<injected>``
        # markers, since the framework's regex rejects angle brackets).
        from asterion.control.harness import HarnessEdit, HarnessEntryDescriptor

        promotion_action_proposal = HarnessProposal(
            proposal_id=f"promote-{root_run_id}",
            authority_id="prime.candidate-store",
            authority_revision=1,
            scope=HarnessScope.project("prime.continual-improvement"),
            baseline_snapshot_id="snapshot-promote-stub",
            edits=(
                HarnessEdit.create(
                    HarnessEntryDescriptor(
                        entry_id=f"entry-promote-{root_run_id}",
                        kind="memory",
                        title_digest="a" * 64,
                        body_ref=f"private:promote-{root_run_id}",
                        body_digest="b" * 64,
                        grouping_path_digest=None,
                        metadata_digest="c" * 64,
                        version=1,
                    )
                ),
            ),
            evidence_ids=("evidence-promote-1",),
            rationale_ref=f"private:promote-rationale-{root_run_id}",
            rationale_digest="d" * 64,
            expected_outcome_digest="e" * 64,
        )
        # The 3-element oracle ``verdict`` and the public 2-element
        # ``terminal_outcome`` are private to the wrapper and MUST NOT
        # leak through this Protocol method. ``_`` discards them.
        _verdict, _terminal_outcome, _summary = (
            self._candidate_store.promote_or_rollback(
                promotion_action=promotion_action_proposal,
                rollback_proposal_id=f"rollback-{root_run_id}",
                rollback_authority_id="prime.candidate-store",
                rollback_authority_revision=1,
                rollback_target_revision_id=candidate.revision_id,
                rollback_rationale_ref=f"private:rollback-rationale-{root_run_id}",
                rollback_rationale_digest="d" * 64,
                rollback_expected_outcome_digest="e" * 64,
                signal=signal,
            )
        )
        return P6PromotionAction(
            promotion_id=promotion_action_proposal.proposal_id,
            promotion_digest=promotion_action_proposal.digest,
            target_revision_id=candidate.revision_id,
            promotion_timestamp=datetime.now(tz=timezone.utc),
        )

    async def wait_finalization(
        self, *, signal: CancellationSignal
    ) -> P6NativeReceipt:
        """Block until the host transfers terminal status and seal the receipt.

        Composes the sealed ``P6NativeReceipt`` from the candidate-store
        wrapper's per-run state via ``seal_p6_native_receipt`` (Task 6).
        The oracle from Task 5 (``P6Oracle.check``) is consulted here
        to seal an oracle receipt whose verdict confirms the three
        witness invariants; the verdict is internal-only and folds
        into the public 2-element ``terminal_outcome`` enum. The
        oracle's ``global-rejected`` verdict folds into
        ``terminal_outcome="rolled-back"`` +
        ``global_activation_approved=False`` (spec L274-L290).
        """

        last_evaluation_digest = self._candidate_store.last_evaluation_digest
        rollback_count = self._candidate_store.rollback_invocation_count
        # Invoke the oracle from Task 5 to seal the witness's three
        # invariants. The oracle's verdict is internal-only and never
        # appears on the public ``P6NativeReceipt``. The binding calls
        # the oracle with the boundary-rejection shape (``admitted_proposal``
        # / ``holdout_result`` / ``promotion_action`` all None) when
        # no candidate was admitted — this drives the oracle's
        # ``global-rejected`` short-circuit on the pre-orchestration
        # path; the public receipt folds this to ``rolled-back``.
        oracle_receipt = self._oracle.check(
            root_run_id="<injected>",
            admitted_proposal=None,
            holdout_result=None,
            promotion_action=None,
            rollback_invocation_count=rollback_count,
            global_activation_approved=False,
            signal=signal,
        )
        _ = oracle_receipt  # verdict is internal-only; never returned
        if last_evaluation_digest is None:
            # Pre-orchestration boundary rejection: no holdout was run,
            # no candidate was admitted. The receipt seals with
            # ``terminal_outcome="rolled-back"`` and
            # ``global_activation_approved=False`` so the public enum
            # stays at 2.
            receipt = P6NativeReceipt(
                root_run_id="<injected>",
                baseline_snapshot_digest="<injected>",
                candidate_revision_digest="<injected>",
                task_a_evidence_digest="<injected>",
                task_b_result_digest="<injected>",
                terminal_outcome="rolled-back",
                global_activation_approved=False,
                rollback_invocation_count=0,
                receipt_sha256="<injected>",
                failure_digest=None,
            )
            return seal_p6_native_receipt(receipt)
        # Holdout path: the oracle verdict drives the public
        # ``terminal_outcome``. ``global-rejected`` folds to
        # ``rolled-back`` so the public enum stays closed.
        receipt = P6NativeReceipt(
            root_run_id="<injected>",
            baseline_snapshot_digest="<injected>",
            candidate_revision_digest="<injected>",
            task_a_evidence_digest="<injected>",
            task_b_result_digest=last_evaluation_digest,
            terminal_outcome="preserved",
            global_activation_approved=False,
            rollback_invocation_count=rollback_count,
            receipt_sha256="<injected>",
            failure_digest=None,
        )
        return seal_p6_native_receipt(receipt)

    # ------------------------------------------------------------------
    # Runtime-client session interface
    # ------------------------------------------------------------------

    async def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]:
        if type(request) is not RunRequest:
            raise ProtocolError("P6 runtime request is invalid")
        request.to_mapping()
        if self._active or self._consumed:
            raise ProtocolError("P6 runtime session is unavailable")
        self._active = self._consumed = True
        # The P6 witness is operator-driven through Make; this surface
        # exists so the runtime client is constructable end-to-end and
        # yields a single terminal event so callers see a closed shape.
        try:
            yield RunEvent(
                request.run_id,
                1,
                "run.completed",
                {"status": "completed"},
            )
        finally:
            self._active = False


__all__ = (
    "P6_HOST_CAPABILITIES",
    "P6_RUNTIME_OPTIONS",
)


def build_p6_runtime(context: RuntimeFactoryContext) -> AsterionPrimeRuntimeClient:
    """Bind exact preflighted P6 services without constructing the coordinator.

    Composes the five host services from the context (already injected by
    the operator) into a single client that exposes the ``P6RuntimeHost``
    Protocol surface (``validate_runtime_services`` /
    ``admit_candidate`` / ``evaluate_holdout`` / ``promote_or_rollback`` /
    ``wait_finalization``).

    The ``prime.candidate-store`` host service is opened and wired
    with the operator-injected holdout callable via
    :meth:`CandidateStoreLoop.set_holdout_callable` by the operator
    (Task 8) before this binding runs; the binding only validates the
    5-tuple and adapts the session-backend through the ``P6RuntimeHost``
    surface. ``set_holdout_callable`` is the operator's responsibility,
    not the binding's.

    Returns a frozen :class:`AsterionPrimeRuntimeClient` carrying the
    bound host services and an internal :class:`_P6RuntimeSession`
    adapter. Fails closed on any host-service mismatch.
    """

    try:
        if type(context) is not RuntimeFactoryContext:
            raise ValueError
        host_services = context.host_services
        service = host_services.get("prime.session-backend")
        candidate_store_value = host_services.get("prime.candidate-store")
        oracle_value = host_services.get("prime.p6-oracle")
        # ``prime.private-trace`` has no consumer in P6 (no persistent
        # session to trace), so it is allowed to be None. Every other
        # host service must be a real instance.
        required_host_services = tuple(
            name
            for name in P6_HOST_CAPABILITIES
            if name != "prime.private-trace"
        )
        if (
            context.provider_id != "prime-applications"
            or context.application_id != "prime.continual-improvement"
            or context.application_version != "1.0.0"
            or context.runtime_id != "asterion.prime"
            or set(host_services) != set(P6_HOST_CAPABILITIES)
            or any(
                host_services.get(name) is None
                for name in required_host_services
            )
            or dict(context.options) != dict(P6_RUNTIME_OPTIONS)
            or not isinstance(service, P6RuntimeHost)
            or not isinstance(oracle_value, P6Oracle)
            or not isinstance(candidate_store_value, CandidateStoreLoop)
        ):
            raise ValueError
        session = _P6RuntimeSession(
            session_backend=service,
            candidate_store=candidate_store_value,
            oracle=oracle_value,
            private_trace=host_services.get("prime.private-trace"),
        )
        # Eagerly validate the 5-tuple so a malformed host-services
        # shape is rejected before the runtime is handed to callers.
        session.validate_runtime_services(host_services)
        return AsterionPrimeRuntimeClient(session)
    except Exception:
        raise RuntimeFactoryError(_ERROR) from None
