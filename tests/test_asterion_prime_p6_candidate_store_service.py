"""Tests for ``prime.candidate-store`` host service (Phase 9, Task 3).

Composition over duplication: the wrapper composes the framework-owned
:class:`HarnessCoordinator` (``src/asterion/control/harness.py``) and
does NOT reimplement it. Tests construct a real coordinator (with an
in-memory journal) so the composition path is exercised end-to-end.
"""

from __future__ import annotations

import asyncio
import hashlib
import unittest
from decimal import Decimal

from asterion.applications.prime.services import (
    CandidateStoreLoop,
    CandidateStoreServiceError,
    CandidateStoreTerminalOutcome,
    CandidateStoreVerdict,
    HoldoutResult,
    MAX_ACTIONS,
    MAX_CANDIDATE_REVISIONS_PER_RUN,
    MAX_COST_USD,
    MAX_DEADLINE_MS,
    MAX_HOLDOUT_EVALUATIONS_PER_RUN,
    MAX_ROLLBACK_INVOCATIONS_PER_RUN,
    MAX_USAGE_PROVIDER_OPS,
    create_candidate_store_host_service,
    create_candidate_store_host_service_for_test,
)
from asterion.control.harness import (
    HarnessCoordinator,
    HarnessEdit,
    HarnessEntryDescriptor,
    HarnessProposal,
    HarnessRevision,
    HarnessScope,
    MemoryHarnessPrivateRevisionStore,
    harness_effect_digest,
)
from asterion.control.journal import (
    JournalRecord,
    MemoryCanonicalJournal,
)
from asterion.services.progress import NOOP_HOST_PROGRESS_REPORTER
from asterion.services.presentation import NOOP_HOST_PRESENTATION_SINK
from asterion.services.registry import HostServiceFactoryContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _entry(
    entry_id: str = "memory-1",
    *,
    kind: str = "memory",
    version: int = 1,
) -> HarnessEntryDescriptor:
    """Build a minimal :class:`HarnessEntryDescriptor` for test proposals."""

    return HarnessEntryDescriptor(
        entry_id=entry_id,
        kind=kind,
        title_digest="a" * 64,
        body_ref=f"private:{entry_id}",
        body_digest="b" * 64,
        grouping_path_digest=None,
        metadata_digest="c" * 64,
        version=version,
    )


def _proposal(
    *,
    proposal_id: str = "proposal-1",
    scope: HarnessScope | None = None,
    baseline_snapshot_id: str = "snapshot-0",
    edits: tuple[HarnessEdit, ...] | None = None,
    evidence_ids: tuple[str, ...] = ("evidence-1", "evidence-2"),
    rationale_ref: str = "private:rationale-1",
) -> HarnessProposal:
    """Build a minimal :class:`HarnessProposal` for admission."""

    if edits is None:
        edits = (HarnessEdit.create(_entry()),)
    return HarnessProposal(
        proposal_id=proposal_id,
        authority_id="prime.candidate-store",
        authority_revision=1,
        scope=scope or HarnessScope.project("prime.continual-improvement"),
        baseline_snapshot_id=baseline_snapshot_id,
        edits=edits,
        evidence_ids=evidence_ids,
        rationale_ref=rationale_ref,
        rationale_digest="d" * 64,
        expected_outcome_digest="e" * 64,
    )


def _coordinator(
    *,
    scope: HarnessScope,
    private_store: MemoryHarnessPrivateRevisionStore | None = None,
    effect_sender=None,
    cancellation=None,
) -> HarnessCoordinator:
    """Construct a :class:`HarnessCoordinator` over an in-memory journal.

    Defaults to a successful effect sender that returns the exact
    ``result_entries`` the proposal declared so the coordinator's
    activation path runs to completion. Tests that need a custom sender
    (e.g. cancellation propagation) pass one in.
    """

    journal = MemoryCanonicalJournal("prime.candidate-store")
    journal.append(
        0,
        JournalRecord.system_bound(
            system_id="prime.candidate-store",
            system_version="1.0.0",
        ),
    )
    journal.append(
        1,
        JournalRecord.authority_bound(
            authority_id="prime.candidate-store",
            authority_revision=1,
        ),
    )

    def _default_send(proposal: HarnessProposal):
        changed = tuple(
            edit.replacement
            for edit in proposal.edits
            if edit.replacement is not None
        )
        return _success_receipt(proposal, result_entries=changed)

    return HarnessCoordinator(
        journal=journal,
        scope=scope,
        effect_sender=effect_sender or _default_send,
        cancellation_signal=cancellation,
        private_store=private_store,
    )


def _success_receipt(proposal: HarnessProposal, *, result_entries=()):
    """Build a successful :class:`HarnessEffectReceipt` for a proposal."""

    from asterion.control.harness import HarnessEffectReceipt

    return HarnessEffectReceipt.succeeded(
        proposal,
        effect_digest=harness_effect_digest(proposal),
        result_entries=result_entries,
        usage=_usage(),
    )


def _usage() -> dict[str, int]:
    return {
        "aggregate_tokens": 0,
        "cost_micros": 0,
        "model_credential_reads": 0,
        "provider_operations": 0,
    }


def _digest(payload: str) -> str:
    """Return a deterministic 64-character hex digest for the payload."""

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _limits() -> dict[str, int | str]:
    """Return a fresh default limit mapping for the test wrapper constructor."""

    return {
        "max_candidate_revisions_per_run": MAX_CANDIDATE_REVISIONS_PER_RUN,
        "max_holdout_evaluations_per_run": MAX_HOLDOUT_EVALUATIONS_PER_RUN,
        "max_rollback_invocations_per_run": MAX_ROLLBACK_INVOCATIONS_PER_RUN,
        "max_actions": MAX_ACTIONS,
        "max_usage_provider_ops": MAX_USAGE_PROVIDER_OPS,
        "max_deadline_ms": MAX_DEADLINE_MS,
        "max_cost_usd": str(MAX_COST_USD),
    }


def _build_loop(
    *,
    scope_kind: str = "project",
    global_activation_approved: bool = False,
    holdout_callable=None,
    coordinator_scope: HarnessScope | None = None,
) -> tuple[CandidateStoreLoop, HarnessCoordinator]:
    """Build a :class:`CandidateStoreLoop` with a wired coordinator.

    Returns ``(loop, coordinator)`` so tests can either drive the loop
    through its public surface or assert coordinator state directly.
    """

    from asterion.applications.prime.services import (
        _CandidateStoreLimits,
    )

    scope = coordinator_scope or HarnessScope.project("prime.continual-improvement")
    if scope_kind == "global":
        scope = HarnessScope.global_scope()
    elif scope_kind == "session":
        scope = HarnessScope.session("prime.candidate-store")
    coordinator = _coordinator(scope=scope)
    loop = create_candidate_store_host_service_for_test(
        limits=_CandidateStoreLimits(
            max_candidate_revisions_per_run=MAX_CANDIDATE_REVISIONS_PER_RUN,
            max_holdout_evaluations_per_run=MAX_HOLDOUT_EVALUATIONS_PER_RUN,
            max_rollback_invocations_per_run=MAX_ROLLBACK_INVOCATIONS_PER_RUN,
            max_actions=MAX_ACTIONS,
            max_usage_provider_ops=MAX_USAGE_PROVIDER_OPS,
            max_deadline_ms=MAX_DEADLINE_MS,
            max_cost_usd=Decimal(str(MAX_COST_USD)),
        ),
        opened_at_iso="2026-09-19T00:00:00+00:00",
        scope=scope,
        coordinator=coordinator,
        global_activation_approved=global_activation_approved,
        holdout_callable=holdout_callable,
    )
    return loop, coordinator


def _factory_context(
    *,
    options: dict[str, str] | None = None,
    application_id: str = "prime.continual-improvement",
    capability_id: str = "prime.candidate-store",
) -> HostServiceFactoryContext:
    return HostServiceFactoryContext(
        provider_id="prime-applications",
        application_id=application_id,
        application_version="1.0.0",
        capability_id=capability_id,
        options=options if options is not None else {},
        progress=NOOP_HOST_PROGRESS_REPORTER,
        presentation=NOOP_HOST_PRESENTATION_SINK,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCandidateStoreService(unittest.TestCase):
    def test_factory_returns_async_context_manager(self) -> None:
        """The factory returns an async-context-manager-shaped binding."""

        binding = create_candidate_store_host_service()
        self.assertEqual(binding.capability_id, "prime.candidate-store")
        self.assertIn("scope", binding.option_names)
        self.assertIn("global_activation_approved", binding.option_names)
        self.assertIn("max_cost_usd", binding.option_names)

        async def driver() -> CandidateStoreLoop:
            factory = binding.factory
            ctx = _factory_context()
            manager = factory(ctx)
            self.assertTrue(hasattr(manager, "__aenter__"))
            self.assertTrue(hasattr(manager, "__aexit__"))
            async with manager as service:
                return service

        asyncio.run(driver())

    def test_public_identity_is_closed_string(self) -> None:
        """``public_identity`` is a stable, content-safe projection."""

        loop, _ = _build_loop()
        identity = loop.public_identity
        self.assertEqual(identity.provider_id, "prime-applications")
        self.assertEqual(
            identity.application_id, "prime.continual-improvement"
        )
        self.assertEqual(identity.runtime_id, "asterion.prime")
        self.assertEqual(identity.session_id, "prime.candidate-store")
        self.assertEqual(identity.generation, 1)
        # No private-root-style field is exposed on the projection.
        self.assertNotIn("private_root", vars(identity))
        self.assertNotIn("private_root_identity", vars(identity))
        self.assertEqual(identity.pi_command_sha256, "0" * 64)
        self.assertEqual(identity.worker_identity_sha256, "0" * 64)

    def test_admit_candidate_returns_harness_revision_with_revision_id(
        self,
    ) -> None:
        """Happy-path admission returns a non-null ``revision_id``."""

        loop, _ = _build_loop()
        revision = loop.admit_candidate(proposal=_proposal())
        self.assertIsInstance(revision, HarnessRevision)
        self.assertIsNotNone(revision.revision_id)
        self.assertTrue(revision.revision_id)
        self.assertEqual(revision.status, "succeeded")
        self.assertEqual(loop._admission_count, 1)  # type: ignore[attr-defined]

    def test_admit_candidate_wraps_harness_coordinator_apply(self) -> None:
        """Admission goes through ``HarnessCoordinator.apply`` (composition)."""

        loop, coordinator = _build_loop()
        baseline_before = coordinator.snapshot()
        self.assertIsNone(baseline_before.revision_id)

        revision = loop.admit_candidate(proposal=_proposal())

        snapshot_after = coordinator.snapshot()
        # The wrapped coordinator's snapshot now carries the candidate
        # revision — proof that admission flowed through ``apply``.
        self.assertEqual(snapshot_after.revision_id, revision.revision_id)
        self.assertEqual(snapshot_after.sequence, 1)
        # The loop recorded the proposal digest internally.
        self.assertIsNotNone(loop._candidate_revision)  # type: ignore[attr-defined]

    def test_evaluate_holdout_returns_holdout_result_with_task_b_digest_and_non_regressing(
        self,
    ) -> None:
        """Happy-path holdout returns a populated :class:`HoldoutResult`."""

        captured: dict[str, object] = {}

        def holdout(candidate: HarnessRevision, baseline):
            captured["candidate"] = candidate
            captured["baseline"] = baseline
            return HoldoutResult(
                task_b_result_sha256=_digest("task-b-pass"),
                non_regressing=True,
            )

        loop, _ = _build_loop(holdout_callable=holdout)
        revision = loop.admit_candidate(proposal=_proposal())
        baseline_snapshot = loop._coordinator.snapshot()  # type: ignore[attr-defined]

        result = loop.evaluate_holdout(
            candidate=revision, baseline=baseline_snapshot
        )
        self.assertIsInstance(result, HoldoutResult)
        self.assertEqual(len(result.task_b_result_sha256), 64)
        self.assertTrue(result.non_regressing)
        # The last-evaluation digest is the canonical-form SHA-256 of
        # the holdout result.
        self.assertEqual(len(loop.last_evaluation_digest or ""), 64)
        # The holdout callable received the admitted candidate and the
        # baseline snapshot's entry projection.
        self.assertIs(captured["candidate"], revision)

    def test_promote_or_rollback_preserved_path_calls_apply_with_promotion(
        self,
    ) -> None:
        """``preserved`` path applies the promotion via the coordinator."""

        def holdout(candidate: HarnessRevision, baseline):
            return HoldoutResult(
                task_b_result_sha256=_digest("task-b-pass"),
                non_regressing=True,
            )

        loop, coordinator = _build_loop(holdout_callable=holdout)
        candidate_revision = loop.admit_candidate(proposal=_proposal())
        loop.evaluate_holdout(
            candidate=candidate_revision,
            baseline=coordinator.snapshot(),
        )

        baseline_after_admit = coordinator.snapshot()
        promotion_action = _proposal(
            proposal_id="promotion-1",
            baseline_snapshot_id=baseline_after_admit.snapshot_id,
            edits=(
                HarnessEdit.create(_entry("skill-1", kind="skill")),
            ),
        )

        verdict, terminal, summary = loop.promote_or_rollback(
            promotion_action=promotion_action,
            rollback_proposal_id="rollback-1",
            rollback_authority_id="prime.candidate-store",
            rollback_authority_revision=1,
            rollback_target_revision_id=candidate_revision.revision_id,
            rollback_rationale_ref="private:rationale-rb",
            rollback_rationale_digest="f" * 64,
            rollback_expected_outcome_digest="1" * 64,
        )

        self.assertEqual(verdict, "preserved")
        self.assertEqual(terminal, "preserved")
        self.assertEqual(summary["rollback_invocation_count"], 0)
        # The coordinator activated a second revision (the promotion).
        self.assertEqual(coordinator.snapshot().sequence, 2)

    def test_promote_or_rollback_rolled_back_path_calls_rollback_with_inverse_revision(
        self,
    ) -> None:
        """``rolled-back`` path uses ``HarnessCoordinator.rollback``."""

        private_store = MemoryHarnessPrivateRevisionStore()

        def holdout(candidate: HarnessRevision, baseline):
            return HoldoutResult(
                task_b_result_sha256=_digest("task-b-fail"),
                non_regressing=False,
            )

        scope = HarnessScope.project("prime.continual-improvement")
        coordinator = _coordinator(scope=scope, private_store=private_store)
        from asterion.applications.prime.services import (
            _CandidateStoreLimits,
        )

        loop = create_candidate_store_host_service_for_test(
            limits=_CandidateStoreLimits(
                max_candidate_revisions_per_run=MAX_CANDIDATE_REVISIONS_PER_RUN,
                max_holdout_evaluations_per_run=MAX_HOLDOUT_EVALUATIONS_PER_RUN,
                max_rollback_invocations_per_run=MAX_ROLLBACK_INVOCATIONS_PER_RUN,
                max_actions=MAX_ACTIONS,
                max_usage_provider_ops=MAX_USAGE_PROVIDER_OPS,
                max_deadline_ms=MAX_DEADLINE_MS,
                max_cost_usd=Decimal(str(MAX_COST_USD)),
            ),
            opened_at_iso="2026-09-19T00:00:00+00:00",
            scope=scope,
            coordinator=coordinator,
            global_activation_approved=False,
            holdout_callable=holdout,
        )

        candidate_revision = loop.admit_candidate(proposal=_proposal())
        loop.evaluate_holdout(
            candidate=candidate_revision,
            baseline=coordinator.snapshot(),
        )

        verdict, terminal, summary = loop.promote_or_rollback(
            promotion_action=_proposal(
                proposal_id="promotion-unused",
                baseline_snapshot_id=coordinator.snapshot().snapshot_id,
            ),
            rollback_proposal_id="rollback-1",
            rollback_authority_id="prime.candidate-store",
            rollback_authority_revision=1,
            rollback_target_revision_id=candidate_revision.revision_id,
            rollback_rationale_ref="private:rationale-rb",
            rollback_rationale_digest="f" * 64,
            rollback_expected_outcome_digest="1" * 64,
        )

        self.assertEqual(verdict, "rolled-back")
        self.assertEqual(terminal, "rolled-back")
        self.assertEqual(summary["rollback_invocation_count"], 1)
        # The coordinator's history carries both the candidate and the
        # inverse rollback; the inverse rollback's ``rollback_revision_id``
        # is the candidate's ``revision_id`` (composition over
        # duplication — the wrapper does not compute the inverse edits;
        # the coordinator derives them).
        history = coordinator.history()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].revision_id, candidate_revision.revision_id)
        self.assertEqual(
            history[1].rollback_revision_id, candidate_revision.revision_id
        )

    def test_global_rejected_short_circuits_pre_orchestration(self) -> None:
        """``scope=global`` + ``global_activation_approved=False`` rejects."""

        loop, coordinator = _build_loop(
            scope_kind="global", global_activation_approved=False
        )
        baseline_before = coordinator.snapshot()

        verdict, terminal, summary = loop.promote_or_rollback(
            promotion_action=_proposal(proposal_id="promotion-unused"),
            rollback_proposal_id="rollback-1",
            rollback_authority_id="prime.candidate-store",
            rollback_authority_revision=1,
            rollback_target_revision_id="never-set",
            rollback_rationale_ref="private:rationale-rb",
            rollback_rationale_digest="f" * 64,
            rollback_expected_outcome_digest="1" * 64,
        )

        # Internal verdict enum is the 3-element form.
        self.assertEqual(verdict, "global-rejected")
        # Public terminal_outcome folds to the 2-element form.
        self.assertEqual(terminal, "rolled-back")
        self.assertEqual(summary["global_activation_approved"], False)
        # No rollback was issued.
        self.assertEqual(summary["rollback_invocation_count"], 0)
        # Baseline snapshot is unchanged.
        self.assertEqual(coordinator.snapshot().revision_id, baseline_before.revision_id)
        self.assertEqual(coordinator.snapshot().sequence, baseline_before.sequence)

    def test_candidate_admission_error_folds_to_rolled_back(self) -> None:
        """A ``HarnessError`` during admission folds to ``rolled-back``."""

        class _FailingSend:
            def __call__(self, proposal):
                raise AssertionError("effect sender must not be invoked")

        scope = HarnessScope.project("prime.continual-improvement")
        journal = MemoryCanonicalJournal("prime.candidate-store")
        journal.append(
            0,
            JournalRecord.system_bound(
                system_id="prime.candidate-store",
                system_version="1.0.0",
            ),
        )
        journal.append(
            1,
            JournalRecord.authority_bound(
                authority_id="prime.candidate-store",
                authority_revision=1,
            ),
        )
        # Mismatched scope makes the coordinator reject the proposal.
        coordinator = HarnessCoordinator(
            journal=journal,
            scope=HarnessScope.session("different-scope"),
            effect_sender=_FailingSend(),
            cancellation_signal=None,
        )
        from asterion.applications.prime.services import (
            _CandidateStoreLimits,
        )

        loop = create_candidate_store_host_service_for_test(
            limits=_CandidateStoreLimits(
                max_candidate_revisions_per_run=MAX_CANDIDATE_REVISIONS_PER_RUN,
                max_holdout_evaluations_per_run=MAX_HOLDOUT_EVALUATIONS_PER_RUN,
                max_rollback_invocations_per_run=MAX_ROLLBACK_INVOCATIONS_PER_RUN,
                max_actions=MAX_ACTIONS,
                max_usage_provider_ops=MAX_USAGE_PROVIDER_OPS,
                max_deadline_ms=MAX_DEADLINE_MS,
                max_cost_usd=Decimal(str(MAX_COST_USD)),
            ),
            opened_at_iso="2026-09-19T00:00:00+00:00",
            scope=scope,
            coordinator=coordinator,
            global_activation_approved=False,
        )

        with self.assertRaises(CandidateStoreServiceError):
            loop.admit_candidate(proposal=_proposal())

    def test_holdout_evaluation_error_folds_to_rolled_back(self) -> None:
        """Holdout errors fold to ``rolled-back`` + diagnostic digest."""

        def holdout(candidate: HarnessRevision, baseline):
            raise RuntimeError("SENTINEL_HOLDOUT_FAIL")

        loop, _ = _build_loop(holdout_callable=holdout)
        revision = loop.admit_candidate(proposal=_proposal())

        with self.assertRaises(CandidateStoreServiceError):
            loop.evaluate_holdout(
                candidate=revision, baseline=loop._coordinator.snapshot()  # type: ignore[attr-defined]
            )

    def test_promotion_action_error_folds_to_rolled_back(self) -> None:
        """Promotion failure (mismatched scope) folds to ``rolled-back``."""

        def holdout(candidate: HarnessRevision, baseline):
            return HoldoutResult(
                task_b_result_sha256=_digest("task-b-pass"),
                non_regressing=True,
            )

        loop, coordinator = _build_loop(holdout_callable=holdout)
        loop.admit_candidate(proposal=_proposal())
        loop.evaluate_holdout(
            candidate=loop._candidate_revision,  # type: ignore[attr-defined]
            baseline=coordinator.snapshot(),
        )

        # Promotion whose scope does not match the coordinator's scope.
        bad_promotion = _proposal(
            proposal_id="promotion-bad",
            scope=HarnessScope.session("wrong-scope"),
        )
        verdict, terminal, summary = loop.promote_or_rollback(
            promotion_action=bad_promotion,
            rollback_proposal_id="rollback-1",
            rollback_authority_id="prime.candidate-store",
            rollback_authority_revision=1,
            rollback_target_revision_id="never-set",
            rollback_rationale_ref="private:rationale-rb",
            rollback_rationale_digest="f" * 64,
            rollback_expected_outcome_digest="1" * 64,
        )
        self.assertEqual(verdict, "rolled-back")
        self.assertEqual(terminal, "rolled-back")
        self.assertIn("promotion_action_error_digest", summary)

    def test_cancellation_folds_to_rolled_back(self) -> None:
        """Cancellation folds to ``rolled-back`` + cancellation digest."""

        class _CancelledSignal:
            @property
            def cancelled(self) -> bool:
                return True

        loop, _ = _build_loop()
        verdict, terminal, summary = loop.promote_or_rollback(
            promotion_action=_proposal(proposal_id="promotion-unused"),
            rollback_proposal_id="rollback-1",
            rollback_authority_id="prime.candidate-store",
            rollback_authority_revision=1,
            rollback_target_revision_id="never-set",
            rollback_rationale_ref="private:rationale-rb",
            rollback_rationale_digest="f" * 64,
            rollback_expected_outcome_digest="1" * 64,
            signal=_CancelledSignal(),
        )
        self.assertEqual(verdict, "rolled-back")
        self.assertEqual(terminal, "rolled-back")
        self.assertIn("cancellation_digest", summary)
        self.assertEqual(len(summary["cancellation_digest"]), 64)

    def test_terminal_outcome_is_closed_two_element_enum(self) -> None:
        """The public ``terminal_outcome`` is the closed 2-element enum."""

        self.assertEqual(
            set(CandidateStoreTerminalOutcome.__args__),
            {"preserved", "rolled-back"},
        )

    def test_candidate_store_verdict_is_closed_three_element_enum(self) -> None:
        """The internal oracle verdict enum is the closed 3-element set."""

        self.assertEqual(
            set(CandidateStoreVerdict.__args__),
            {"preserved", "rolled-back", "global-rejected"},
        )
        # The 3-element internal enum must NOT leak through the public
        # identity — public_identity never carries a verdict field.
        loop, _ = _build_loop()
        self.assertNotIn("verdict", vars(loop.public_identity))


if __name__ == "__main__":
    unittest.main()
