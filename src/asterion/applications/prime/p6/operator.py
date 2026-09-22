"""Operator-owned native P6 continual-improvement witness.

Single-mode operator: reads ``ASTERION_PRIME_P6_MODE`` and dispatches to
either the preserved path (``"preserved"``) or the two-record limits path
(``"limits"``). There is no commit/recover split — P6 owns one bounded
candidate-store run per invocation, so the operator reads either mode
and emits one JSON record (preserved) or two JSON records (limits, in
fixed order: rolled-back then global-rejected).

The Makefile targets ``asterion-prime-p6-run`` and
``asterion-prime-p6-run-limits`` (Task 14) will invoke the operator in
``preserved`` and ``limits`` mode respectively. The fake-worker contract
is deterministic: given ``(mode, candidate_kind, run_id)`` the same
SHA-256 is produced across host runs. No real Pi subprocess is involved
on this path; the operator is itself the host-service owner, mirroring
P3 / P4 / P5's pattern.

Composition over duplication (load-bearing): the operator drives the
``prime.candidate-store`` host service, which composes the
framework-owned :class:`HarnessCoordinator` (``src/asterion/control/
harness.py``). The operator does NOT reimplement append-only revision
authority, scope mapping, or inverse rollback — it delegates every
admission, promotion, and rollback through the wrapped coordinator's
public API (``apply(proposal)`` / ``rollback(...)``).

Four error paths fold into the closed 2-element public
``terminal_outcome`` enum (``preserved`` | ``rolled-back``) per spec
L283–L292:

* Cancellation → ``rolled-back`` + ``failure_digest`` carrying the
  cancellation fingerprint.
* Candidate-admission error → ``rolled-back`` + ``failure_digest``
  carrying the admission-error fingerprint.
* Holdout-evaluation error → ``rolled-back`` + ``failure_digest``
  carrying the holdout-error fingerprint.
* Promotion-action error → ``rolled-back`` + ``failure_digest``
  carrying the promotion-error fingerprint.

The oracle's 3-element internal verdict enum (``preserved`` |
``rolled-back`` | ``global-rejected``) does NOT leak through the
public operator output — the public surface expresses the boundary
rejection through ``terminal_outcome="rolled-back"`` +
``global_activation_approved=False``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

from asterion.applications.prime.p6.oracle import P6Oracle
from asterion.applications.prime.p6.receipt import (
    P6NativeReceipt,
    seal_p6_native_receipt,
)
from asterion.applications.prime.services import (
    CandidateStoreLoop,
    CandidateStoreServiceError,
    CandidateStoreVerdict,
    HoldoutResult,
    create_candidate_store_host_service_for_test,
)
from asterion.control.harness import (
    HarnessCoordinator,
    HarnessEdit,
    HarnessEntryDescriptor,
    HarnessError,
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


_OPERATOR_ROOT_ENV = "ASTERION_PRIME_OPERATOR_ROOT"
_PI_ENTRY_ENV = "ASTERION_PRIME_PI_ENTRY"
_PRIVATE_ROOT_ENV = "ASTERION_PRIME_P6_PRIVATE_ROOT"
_MODE_ENV = "ASTERION_PRIME_P6_MODE"


class P6OperatorError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("P6 operator is unavailable")


class P6RecoveryRequired(P6OperatorError):
    def __init__(self) -> None:
        RuntimeError.__init__(self, "P6 effects require recovery")


# ---------------------------------------------------------------------------
# Public result shapes (one JSON record per root run)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class P6PublicResult:
    """Success-path public result (``mode == "preserved"``).

    ``status`` is ``"completed"`` when the candidate-store loop admitted
    one candidate, evaluated one holdout with ``non_regressing=True``,
    applied the explicit promotion action via
    ``HarnessCoordinator.apply(promotion_action)``, and sealed a receipt
    with ``terminal_outcome="preserved"``. All other fields are
    content-safe projections of the sealed receipt plus a constant
    ``private_root_redacted=True`` marker; no prompts, paths, worker
    output, or oracle internal verdicts are exposed.
    """

    status: str
    root_run_id: str
    baseline_snapshot_digest: str
    candidate_revision_digest: str
    task_a_evidence_digest: str
    task_b_result_digest: str
    terminal_outcome: str
    global_activation_approved: bool
    rollback_invocation_count: int
    receipt_sha256: str
    failure_digest: str | None
    private_root_redacted: bool = True


@dataclass(frozen=True, slots=True)
class P6LimitsRecord:
    """Limits-path refusal record (one per refused scenario).

    The ``limits`` mode emits exactly two of these in fixed order:

    * ``rolled-back`` — holdout regressed, exact inverse revision applied,
      ``rollback_invocation_count=1``, ``candidate_revision_digest``
      non-null (the admitted revision existed before rollback).
    * ``global-rejected`` — scope=global without
      ``global_activation_approved=True``, pre-orchestration boundary
      rejection. ``terminal_outcome="rolled-back"`` (folded from the
      oracle's internal verdict), ``rollback_invocation_count=0``,
      ``candidate_revision_digest`` equals ``baseline_snapshot_digest``
      (no candidate was admitted).
    """

    status: str
    scenario: str
    terminal_outcome: str
    global_activation_approved: bool
    rollback_invocation_count: int
    baseline_snapshot_digest: str
    candidate_revision_digest: str
    task_a_evidence_digest: str
    task_b_result_digest: str | None
    receipt_sha256: str
    failure_digest: str | None
    private_root_redacted: bool = True


# ---------------------------------------------------------------------------
# Pre-flight dataclass + env-var parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Preflight:
    operator_root: Path
    worker_python: Path
    private_root: Path
    mode: str
    pi_entry: Path | None


_VALID_MODES: frozenset[str] = frozenset({"preserved", "limits"})


def _preflight(environment: Mapping[str, str]) -> _Preflight:
    """Validate env vars and runtime preflight. Raises P6OperatorError on miss."""

    operator_value = environment.get(_OPERATOR_ROOT_ENV, "").strip()
    private_value = environment.get(_PRIVATE_ROOT_ENV, "").strip()
    mode_value = environment.get(_MODE_ENV, "").strip()
    if not operator_value or not private_value or mode_value not in _VALID_MODES:
        raise P6OperatorError()
    try:
        operator_root = Path(operator_value).resolve(strict=True)
    except OSError:
        raise P6OperatorError() from None
    if not operator_root.is_dir():
        raise P6OperatorError()
    worker_python = Path(sys.executable).absolute()
    if not worker_python.is_file():
        raise P6OperatorError()
    try:
        probe = subprocess.run(
            (str(worker_python), "-I", "-c", "import sys; print(sys.version_info[:2])"),
            check=True,
            capture_output=True,
            timeout=10,
            env={"LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.SubprocessError):
        raise P6OperatorError() from None
    if not probe.stdout or not probe.stdout.strip():
        raise P6OperatorError()
    try:
        private_root = Path(private_value).resolve()
    except OSError:
        raise P6OperatorError() from None
    pi_entry: Path | None = None
    raw_pi = environment.get(_PI_ENTRY_ENV, "").strip()
    if raw_pi:
        try:
            pi_entry = Path(raw_pi).resolve(strict=False)
        except OSError:
            raise P6OperatorError() from None
    return _Preflight(
        operator_root=operator_root,
        worker_python=worker_python,
        private_root=private_root,
        mode=mode_value,
        pi_entry=pi_entry,
    )


# ---------------------------------------------------------------------------
# Deterministic fake-worker payload
# ---------------------------------------------------------------------------


def _fake_worker_payload_sha(*, mode: str, candidate_kind: str, run_id: str) -> str:
    """Deterministic SHA-256 over ``(mode, candidate_kind, run_id)``.

    Different tuples produce different SHAs, so the
    ``task_b_result_digest`` check on the preserved path (must differ
    from the baseline snapshot digest) and the global-rejected path
    (``candidate_revision_digest`` must equal ``baseline_snapshot_digest``)
    are meaningful by construction. The same tuple maps to the same
    SHA across host runs.
    """

    payload = json.dumps(
        {"mode": mode, "candidate_kind": candidate_kind, "run_id": run_id},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Coordinator / scope construction helpers
# ---------------------------------------------------------------------------


def _entry(entry_id: str = "memory-1") -> HarnessEntryDescriptor:
    """Build a minimal :class:`HarnessEntryDescriptor` for proposals."""

    return HarnessEntryDescriptor(
        entry_id=entry_id,
        kind="memory",
        title_digest="a" * 64,
        body_ref=f"private:{entry_id}",
        body_digest="b" * 64,
        grouping_path_digest=None,
        metadata_digest="c" * 64,
        version=1,
    )


def _journal(scope: HarnessScope) -> MemoryCanonicalJournal:
    """Build a fresh in-memory canonical journal for the witness coordinator."""

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
    return journal


def _default_send(proposal: HarnessProposal):  # noqa: ANN202 - framework callable
    """Default effect sender that returns the proposal's declared entries.

    Mirrors the test fixture's effect sender: the coordinator activates
    a successful :class:`HarnessEffectReceipt` carrying the proposal's
    replacement entries. Keeps the in-process path side-effect-free.
    """

    from asterion.control.harness import HarnessEffectReceipt

    changed = tuple(
        edit.replacement for edit in proposal.edits if edit.replacement is not None
    )
    return HarnessEffectReceipt.succeeded(
        proposal,
        effect_digest=harness_effect_digest(proposal),
        result_entries=changed,
        usage={
            "aggregate_tokens": 0,
            "cost_micros": 0,
            "model_credential_reads": 0,
            "provider_operations": 0,
        },
    )


def _build_coordinator(
    *,
    scope: HarnessScope,
    private_store: MemoryHarnessPrivateRevisionStore | None = None,
    effect_sender=None,
) -> HarnessCoordinator:
    """Build a fresh :class:`HarnessCoordinator` for the witness scope."""

    return HarnessCoordinator(
        journal=_journal(scope),
        scope=scope,
        effect_sender=effect_sender or _default_send,
        cancellation_signal=None,
        private_store=private_store,
    )


# ---------------------------------------------------------------------------
# Digest helpers
# ---------------------------------------------------------------------------


def _baseline_snapshot_digest(entries: object) -> str:
    """SHA-256 of the canonical-form of a baseline snapshot's entries."""

    payload = {"entries": [dict(item.to_public_mapping()) for item in entries]}  # type: ignore[union-attr]
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _evidence_digest(proposal: HarnessProposal) -> str:
    """SHA-256 of the canonical-form of the proposal's evidence IDs.

    ``task_a_evidence_digest`` — Task A evidence digest — is the
    canonical-form SHA of the proposal's evidence_ids tuple. Mirrors
    the pre-detachment spec's per-identity shape: a candidate carries
    its own evidence digest, distinct from the candidate revision
    digest and the task B result digest.
    """

    payload = {"evidence_ids": list(proposal.evidence_ids)}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _fail_at_kind(name: str) -> str:
    """Return a sentinel kind string for the failure-path tests.

    The operator drives each failure path through a private
    ``_sealed_error_*`` helper so the sealed receipt always carries the
    canonical-form diagnostic fingerprint. The kinds are namespaced to
    keep them out of the public 2-element ``terminal_outcome`` enum.
    """

    return f"failure::{name}"


# ---------------------------------------------------------------------------
# Sealing helpers
# ---------------------------------------------------------------------------


def _build_promotion_proposal(
    *,
    proposal_id: str,
    scope: HarnessScope,
    baseline_snapshot_id: str,
) -> HarnessProposal:
    """Build the explicit promotion action the wrapper applies on the
    ``preserved`` path.

    The promotion proposal is the framework-owned
    :class:`HarnessCoordinator`'s ``apply(promotion_action)`` payload —
    the operator builds the proposal, the wrapper delegates
    :meth:`apply` to the coordinator (composition over duplication).
    """

    return HarnessProposal(
        proposal_id=proposal_id,
        authority_id="prime.candidate-store",
        authority_revision=1,
        scope=scope,
        baseline_snapshot_id=baseline_snapshot_id,
        edits=(HarnessEdit.create(_entry("skill-promotion-1")),),
        evidence_ids=("promotion-evidence-1",),
        rationale_ref="private:promotion-rationale",
        rationale_digest="d" * 64,
        expected_outcome_digest="e" * 64,
    )


def _build_candidate_proposal(
    *,
    proposal_id: str,
    scope: HarnessScope,
    baseline_snapshot_id: str,
) -> HarnessProposal:
    """Build the candidate revision the wrapper admits on every non-rejected
    path. ``scope`` MUST equal the wrapped coordinator's scope or the
    coordinator's ``apply`` raises :class:`HarnessError`.
    """

    return HarnessProposal(
        proposal_id=proposal_id,
        authority_id="prime.candidate-store",
        authority_revision=1,
        scope=scope,
        baseline_snapshot_id=baseline_snapshot_id,
        edits=(HarnessEdit.create(_entry()),),
        evidence_ids=("evidence-1", "evidence-2"),
        rationale_ref="private:rationale-1",
        rationale_digest="d" * 64,
        expected_outcome_digest="e" * 64,
    )


def _seal_receipt_from_loop(
    *,
    loop: CandidateStoreLoop,
    root_run_id: str,
    candidate_revision: HarnessRevision,
    candidate_proposal: HarnessProposal,
    baseline_digest: str,
    holdout_result: HoldoutResult | None,
    verdict: CandidateStoreVerdict,
    summary: dict[str, object],
    failure_digest: str | None,
) -> P6NativeReceipt:
    """Build and seal a :class:`P6NativeReceipt` from the wrapper's outcome.

    The closed public 2-element ``terminal_outcome`` enum is enforced at
    seal time; the oracle's internal 3-element verdict enum does NOT
    surface on the receipt (defense in depth alongside
    :class:`P6ReceiptError`). ``global-rejected`` verdicts fold into
    ``terminal_outcome="rolled-back"`` with
    ``global_activation_approved=False``.
    """

    if verdict == "preserved":
        terminal_outcome = "preserved"
    else:
        terminal_outcome = "rolled-back"
    rollback_invocation_count = int(summary.get("rollback_invocation_count", 0))
    global_activation_approved = bool(summary.get("global_activation_approved", False))
    if holdout_result is None:
        task_b_result_digest = "0" * 64
    else:
        task_b_result_digest = holdout_result.task_b_result_sha256
    raw_receipt = P6NativeReceipt(
        root_run_id=root_run_id,
        baseline_snapshot_digest=baseline_digest,
        candidate_revision_digest=candidate_revision.proposal_digest,
        task_a_evidence_digest=_evidence_digest(candidate_proposal),
        task_b_result_digest=task_b_result_digest,
        terminal_outcome=terminal_outcome,
        global_activation_approved=global_activation_approved,
        rollback_invocation_count=rollback_invocation_count,
        receipt_sha256="0" * 64,
        failure_digest=failure_digest,
    )
    return seal_p6_native_receipt(raw_receipt)


def _seal_receipt_pre_orchestration(
    *,
    root_run_id: str,
    baseline_digest: str,
    proposal: HarnessProposal,
    task_b_result_digest: str,
    summary: dict[str, object],
    failure_digest: str | None,
) -> P6NativeReceipt:
    """Build and seal a :class:`P6NativeReceipt` for the
    ``global-rejected`` boundary path. The receipt's
    ``candidate_revision_digest`` equals the baseline digest — proof
    that no candidate was admitted.
    """

    raw_receipt = P6NativeReceipt(
        root_run_id=root_run_id,
        baseline_snapshot_digest=baseline_digest,
        candidate_revision_digest=baseline_digest,
        task_a_evidence_digest=_evidence_digest(proposal),
        task_b_result_digest=task_b_result_digest,
        terminal_outcome="rolled-back",
        global_activation_approved=bool(
            summary.get("global_activation_approved", False)
        ),
        rollback_invocation_count=int(summary.get("rollback_invocation_count", 0)),
        receipt_sha256="0" * 64,
        failure_digest=failure_digest,
    )
    return seal_p6_native_receipt(raw_receipt)


# ---------------------------------------------------------------------------
# Cancellation signal stubs
# ---------------------------------------------------------------------------


class _NeverCancelled:
    """A non-cancelling CancellationSignal implementation."""

    @property
    def cancelled(self) -> bool:
        return False


class _AlwaysCancelled:
    """A cancelling CancellationSignal implementation."""

    @property
    def cancelled(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Operator resources — host services + identity the operator owns
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _OperatorResources:
    """One preflighted set of operator-owned resources for the P6 witness."""

    mode: str
    private_root: Path
    root_run_id: str
    scope: HarnessScope
    global_activation_approved: bool
    p6_oracle: P6Oracle


async def _build_resources(preflight: _Preflight) -> _OperatorResources:
    """Build the operator-owned resources for one invocation.

    The candidate-store host service is opened fresh per scenario via
    :meth:`_open_candidate_store` (see the scenario drivers below) so
    cached loop state from one scenario does not bleed into the next
    on the limits path.
    """

    mode = preflight.mode
    private_root = preflight.private_root.resolve()
    private_root.parent.mkdir(parents=True, exist_ok=True)
    # P6 has no cross-process continuation; prior private_root state
    # is irrelevant and may hold stale loop controller state. Wipe it.
    if private_root.exists():
        shutil.rmtree(private_root)
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    root_run_id = "p6-root-" + secrets.token_hex(8)

    if mode == "preserved":
        scope = HarnessScope.project("prime.continual-improvement")
        global_activation_approved = False
    else:
        # Limits path opens its own scope per scenario — see
        # :func:`_run_scenario_rolled_back` and
        # :func:`_run_scenario_global_rejected`.
        scope = HarnessScope.project("prime.continual-improvement")
        global_activation_approved = False

    p6_oracle = P6Oracle()

    return _OperatorResources(
        mode=mode,
        private_root=private_root,
        root_run_id=root_run_id,
        scope=scope,
        global_activation_approved=global_activation_approved,
        p6_oracle=p6_oracle,
    )


# ---------------------------------------------------------------------------
# Scenario drivers
# ---------------------------------------------------------------------------


async def _open_candidate_store_for_run(
    *,
    scope: HarnessScope,
    global_activation_approved: bool,
    private_store: MemoryHarnessPrivateRevisionStore | None = None,
) -> tuple[CandidateStoreLoop, HarnessCoordinator]:
    """Open a fresh candidate-store host service and return the loop +
    the wired coordinator. Used by every scenario driver.

    Goes through the in-process test factory
    :func:`create_candidate_store_host_service_for_test` (not the
    registry path) so the operator can inject the
    :class:`MemoryHarnessPrivateRevisionStore` for the rolled-back
    scenario and exercise the framework-owned ``HarnessCoordinator``
    directly.
    """

    from decimal import Decimal

    from asterion.applications.prime.services import (
        _CandidateStoreLimits,
        MAX_ACTIONS,
        MAX_CANDIDATE_REVISIONS_PER_RUN,
        MAX_COST_USD,
        MAX_DEADLINE_MS,
        MAX_HOLDOUT_EVALUATIONS_PER_RUN,
        MAX_ROLLBACK_INVOCATIONS_PER_RUN,
        MAX_USAGE_PROVIDER_OPS,
    )

    coordinator = _build_coordinator(scope=scope, private_store=private_store)
    limits = _CandidateStoreLimits(
        max_candidate_revisions_per_run=MAX_CANDIDATE_REVISIONS_PER_RUN,
        max_holdout_evaluations_per_run=MAX_HOLDOUT_EVALUATIONS_PER_RUN,
        max_rollback_invocations_per_run=MAX_ROLLBACK_INVOCATIONS_PER_RUN,
        max_actions=MAX_ACTIONS,
        max_usage_provider_ops=MAX_USAGE_PROVIDER_OPS,
        max_deadline_ms=MAX_DEADLINE_MS,
        max_cost_usd=Decimal(str(MAX_COST_USD)),
    )
    loop = create_candidate_store_host_service_for_test(
        limits=limits,
        opened_at_iso="2026-09-19T00:00:00+00:00",
        scope=scope,
        coordinator=coordinator,
        global_activation_approved=global_activation_approved,
    )
    return loop, coordinator


async def _execute_candidate_workflow(
    resources: _OperatorResources, loop, coordinator, signal, *, non_regressing=True
) -> P6NativeReceipt:
    """Drive the preserved path: admit → holdout (non_regressing=True) →
    explicit promotion action → seal.

    Per spec L300–L331 the preserved path proves the third witness
    clause: an improving candidate requires an explicit admitted
    promotion action before becoming current.
    """

    root_run_id = resources.root_run_id
    scope = resources.scope

    # Build the candidate proposal off the empty baseline snapshot.
    baseline_snapshot = coordinator.snapshot()
    candidate_proposal = _build_candidate_proposal(
        proposal_id="candidate-1",
        scope=scope,
        baseline_snapshot_id=baseline_snapshot.snapshot_id,
    )

    # Deterministic fake-worker: emits a task B result SHA that differs
    # from the baseline snapshot digest (the preserved path requires
    # ``task_b_result_digest != baseline_snapshot_digest``).
    task_b_sha = _fake_worker_payload_sha(
        mode=resources.mode, candidate_kind="admit", run_id=root_run_id
    )

    def holdout_callable(candidate: HarnessRevision, baseline: object) -> HoldoutResult:
        return HoldoutResult(
            task_b_result_sha256=task_b_sha,
            non_regressing=non_regressing,
        )

    loop.set_holdout_callable(holdout_callable=holdout_callable)
    candidate_revision = loop.admit_candidate(
        proposal=candidate_proposal, signal=signal
    )
    baseline_snapshot_after_admit = coordinator.snapshot()
    holdout_result = loop.evaluate_holdout(
        candidate=candidate_revision,
        baseline=baseline_snapshot,
        signal=signal,
    )

    promotion_action = _build_promotion_proposal(
        proposal_id="promotion-1",
        scope=scope,
        baseline_snapshot_id=baseline_snapshot_after_admit.snapshot_id,
    )

    verdict, terminal_outcome, summary = loop.promote_or_rollback(
        promotion_action=promotion_action,
        rollback_proposal_id="rollback-1",
        rollback_authority_id="prime.candidate-store",
        rollback_authority_revision=1,
        rollback_target_revision_id=candidate_revision.revision_id,
        rollback_rationale_ref="private:rationale-rb",
        rollback_rationale_digest="f" * 64,
        rollback_expected_outcome_digest="1" * 64,
        signal=signal,
    )
    from datetime import datetime, timezone
    from asterion.applications.prime.p6.host import (
        P6AdmittedProposal,
        P6HoldoutResult,
        P6PromotionAction,
    )

    now = datetime.now(timezone.utc)
    oracle_receipt = resources.p6_oracle.check(
        root_run_id=root_run_id,
        admitted_proposal=P6AdmittedProposal(
            candidate_proposal.proposal_id,
            candidate_proposal.digest,
            candidate_revision.revision_id,
            now,
        ),
        holdout_result=P6HoldoutResult(
            holdout_result.task_b_result_sha256, holdout_result.non_regressing, now
        ),
        promotion_action=(
            P6PromotionAction(
                promotion_action.proposal_id,
                promotion_action.digest,
                candidate_revision.revision_id,
                now,
            )
            if verdict == "preserved"
            else None
        ),
        rollback_invocation_count=loop.rollback_invocation_count,
        global_activation_approved=False,
        signal=signal,
    )
    if oracle_receipt.verdict != verdict or terminal_outcome != verdict:
        raise P6OperatorError()

    baseline_digest = _baseline_snapshot_digest(baseline_snapshot.entries)
    sealed = _seal_receipt_from_loop(
        loop=loop,
        root_run_id=root_run_id,
        candidate_revision=candidate_revision,
        candidate_proposal=candidate_proposal,
        baseline_digest=baseline_digest,
        holdout_result=holdout_result,
        verdict=verdict,
        summary=summary,
        failure_digest=None,
    )
    return sealed


class _ComposedCandidateHost:
    def __init__(self, resources, loop, coordinator, *, non_regressing=True):
        self.resources = resources
        self.loop = loop
        self.coordinator = coordinator
        self.non_regressing = non_regressing
        self.receipt = None
        self.effects_state = "not-started"

    def validate_runtime_services(self, services):
        if (
            services.get("prime.candidate-store") is not self.loop
            or services.get("prime.p6-oracle") is not self.resources.p6_oracle
            or services.get("prime.pi-extension") is not self.coordinator
            or services.get("prime.private-trace") is not None
            or services.get("prime.session-backend") is not self
        ):
            raise P6OperatorError()

    async def run_candidate(self, *, root_run_id, signal):
        from dataclasses import replace

        resources = replace(self.resources, root_run_id=root_run_id)
        baseline = self.coordinator.snapshot()
        try:
            self.receipt = await _execute_candidate_workflow(
                resources,
                self.loop,
                self.coordinator,
                signal,
                non_regressing=self.non_regressing,
            )
        except BaseException:
            self.receipt = None
            if self.coordinator.snapshot().entries == baseline.entries:
                self.effects_state = (
                    "rolled-back"
                    if self.loop.rollback_invocation_count == 1
                    else "unchanged"
                )
                raise
            try:
                # The operator supplied this exact authority for normal
                # rollback too. Cancellation stops work, not its inverse.
                self.loop.rollback_admitted_candidate(
                    proposal_id="rollback-cleanup-1",
                    authority_id="prime.candidate-store",
                    authority_revision=1,
                    rationale_ref="private:rationale-rb",
                    rationale_digest="f" * 64,
                    expected_outcome_digest="1" * 64,
                )
                if self.coordinator.snapshot().entries != baseline.entries:
                    raise P6RecoveryRequired()
            except BaseException:
                self.effects_state = "recovery-required"
                raise P6RecoveryRequired() from None
            self.effects_state = "rolled-back"
            raise
        self.effects_state = self.receipt.terminal_outcome
        return self.receipt


async def _drive_preserved_path(resources: _OperatorResources) -> P6PublicResult:
    from asterion.applications.provider import compose_installed_provider
    from asterion.applications.prime.provider import (
        create_prime_continual_improvement_provider,
    )
    from asterion.applications.prime.p6.runtime_binding import (
        build_p6_runtime,
        P6_RUNTIME_OPTIONS,
    )
    from asterion.capabilities.prime_continual_improvement_native.provider import (
        create_prime_continual_improvement_native_package,
    )
    from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryRegistry
    from asterion.runner.composed import run_composed_application

    loop, coordinator = await _open_candidate_store_for_run(
        scope=resources.scope,
        global_activation_approved=False,
        private_store=MemoryHarnessPrivateRevisionStore(),
    )
    host = _ComposedCandidateHost(resources, loop, coordinator)
    package = create_prime_continual_improvement_native_package()
    provider = compose_installed_provider(
        create_prime_continual_improvement_provider(),
        runtime_factories=RuntimeFactoryRegistry(()),
        installed_packages=(package,),
    )
    plan = provider.applications[0].assemblies[0].plan
    services = {
        "prime.candidate-store": loop,
        "prime.session-backend": host,
        "prime.p6-oracle": resources.p6_oracle,
        "prime.private-trace": None,
        "prime.pi-extension": coordinator,
    }
    runtime = build_p6_runtime(
        RuntimeFactoryContext(
            provider_id="prime-applications",
            application_id="prime.continual-improvement",
            application_version="1.0.0",
            runtime_id="asterion.prime",
            assembly_path=Path(__file__).resolve().parent.parent
            / "assemblies/prime-continual-improvement.json",
            options=P6_RUNTIME_OPTIONS,
            host_services=services,
        )
    )
    result = await run_composed_application(
        plan,
        implementations=tuple(
            (b.capability_ref, b.implementation) for b in package.implementations
        ),
        runtime=runtime,
        run_id=resources.root_run_id,
        input_text="fixed-continual-improvement",
        host_services=services,
        signal=_NeverCancelled(),
    )
    if (
        host.receipt is None
        or len(result.artifacts) != 1
        or result.artifacts[0]["value"]["receipt_sha256"] != host.receipt.receipt_sha256
    ):
        raise P6OperatorError()
    return P6PublicResult(status="completed", **asdict(host.receipt))


async def _run_scenario_rolled_back(
    resources: _OperatorResources,
) -> P6LimitsRecord:
    """Run the rolled-back scenario: admit → holdout (non_regressing=False)
    → exact inverse rollback → seal ``rolled-back``,
    ``rollback_invocation_count=1``.
    """

    root_run_id = resources.root_run_id
    scope = HarnessScope.project("prime.continual-improvement")

    private_store = MemoryHarnessPrivateRevisionStore()
    loop, coordinator = await _open_candidate_store_for_run(
        scope=scope,
        global_activation_approved=False,
        private_store=private_store,
    )

    baseline_snapshot = coordinator.snapshot()
    candidate_proposal = _build_candidate_proposal(
        proposal_id="candidate-rolled-back",
        scope=scope,
        baseline_snapshot_id=baseline_snapshot.snapshot_id,
    )

    task_b_sha = _fake_worker_payload_sha(
        mode=resources.mode,
        candidate_kind="admit",
        run_id=root_run_id,
    )

    def holdout_callable(candidate: HarnessRevision, baseline: object) -> HoldoutResult:
        return HoldoutResult(
            task_b_result_sha256=task_b_sha,
            non_regressing=False,
        )

    loop.set_holdout_callable(holdout_callable=holdout_callable)
    candidate_revision = loop.admit_candidate(
        proposal=candidate_proposal, signal=_NeverCancelled()
    )
    baseline_snapshot_after_admit = coordinator.snapshot()
    holdout_result = loop.evaluate_holdout(
        candidate=candidate_revision,
        baseline=baseline_snapshot_after_admit,
        signal=_NeverCancelled(),
    )

    unused_promotion = _build_promotion_proposal(
        proposal_id="promotion-unused",
        scope=scope,
        baseline_snapshot_id=baseline_snapshot_after_admit.snapshot_id,
    )

    verdict, terminal_outcome, summary = loop.promote_or_rollback(
        promotion_action=unused_promotion,
        rollback_proposal_id="rollback-1",
        rollback_authority_id="prime.candidate-store",
        rollback_authority_revision=1,
        rollback_target_revision_id=candidate_revision.revision_id,
        rollback_rationale_ref="private:rationale-rb",
        rollback_rationale_digest="f" * 64,
        rollback_expected_outcome_digest="1" * 64,
        signal=_NeverCancelled(),
    )
    if verdict != "rolled-back" or terminal_outcome != "rolled-back":
        raise P6OperatorError()
    if int(summary.get("rollback_invocation_count", 0)) != 1:
        raise P6OperatorError()

    baseline_digest = _baseline_snapshot_digest(baseline_snapshot_after_admit.entries)
    sealed = _seal_receipt_from_loop(
        loop=loop,
        root_run_id=root_run_id,
        candidate_revision=candidate_revision,
        candidate_proposal=candidate_proposal,
        baseline_digest=baseline_digest,
        holdout_result=holdout_result,
        verdict=verdict,
        summary=summary,
        failure_digest=None,
    )
    return P6LimitsRecord(
        status="refused",
        scenario="rolled-back",
        terminal_outcome=sealed.terminal_outcome,
        global_activation_approved=sealed.global_activation_approved,
        rollback_invocation_count=sealed.rollback_invocation_count,
        baseline_snapshot_digest=sealed.baseline_snapshot_digest,
        candidate_revision_digest=sealed.candidate_revision_digest,
        task_a_evidence_digest=sealed.task_a_evidence_digest,
        task_b_result_digest=sealed.task_b_result_digest,
        receipt_sha256=sealed.receipt_sha256,
        failure_digest=sealed.failure_digest,
    )


async def _run_scenario_global_rejected(
    resources: _OperatorResources,
) -> P6LimitsRecord:
    """Run the global-rejected scenario: scope=global with
    ``global_activation_approved=False`` — pre-orchestration boundary
    rejection. No ``HarnessRevision`` is created; baseline snapshot is
    unchanged; the oracle's internal verdict is ``global-rejected``,
    folded into public ``terminal_outcome="rolled-back"`` +
    ``global_activation_approved=False``.
    """

    root_run_id = resources.root_run_id
    scope = HarnessScope.global_scope()

    loop, coordinator = await _open_candidate_store_for_run(
        scope=scope, global_activation_approved=False
    )

    baseline_snapshot = coordinator.snapshot()
    candidate_proposal = _build_candidate_proposal(
        proposal_id="candidate-global-rejected",
        scope=scope,
        baseline_snapshot_id=baseline_snapshot.snapshot_id,
    )

    unused_promotion = _build_promotion_proposal(
        proposal_id="promotion-unused",
        scope=scope,
        baseline_snapshot_id=baseline_snapshot.snapshot_id,
    )

    verdict, terminal_outcome, summary = loop.promote_or_rollback(
        promotion_action=unused_promotion,
        rollback_proposal_id="rollback-1",
        rollback_authority_id="prime.candidate-store",
        rollback_authority_revision=1,
        rollback_target_revision_id="never-set",
        rollback_rationale_ref="private:rationale-rb",
        rollback_rationale_digest="f" * 64,
        rollback_expected_outcome_digest="1" * 64,
        signal=_NeverCancelled(),
    )
    if verdict != "global-rejected" or terminal_outcome != "rolled-back":
        raise P6OperatorError()
    if int(summary.get("rollback_invocation_count", 0)) != 0:
        raise P6OperatorError()

    baseline_digest = _baseline_snapshot_digest(baseline_snapshot.entries)
    sealed = _seal_receipt_pre_orchestration(
        root_run_id=root_run_id,
        baseline_digest=baseline_digest,
        proposal=candidate_proposal,
        task_b_result_digest="0" * 64,
        summary=summary,
        failure_digest=None,
    )
    return P6LimitsRecord(
        status="refused",
        scenario="global-rejected",
        terminal_outcome=sealed.terminal_outcome,
        global_activation_approved=sealed.global_activation_approved,
        rollback_invocation_count=sealed.rollback_invocation_count,
        baseline_snapshot_digest=sealed.baseline_snapshot_digest,
        candidate_revision_digest=sealed.candidate_revision_digest,
        task_a_evidence_digest=sealed.task_a_evidence_digest,
        task_b_result_digest=sealed.task_b_result_digest,
        receipt_sha256=sealed.receipt_sha256,
        failure_digest=sealed.failure_digest,
    )


# ---------------------------------------------------------------------------
# Failure-path sealed receipts (spec L283–L292)
# ---------------------------------------------------------------------------


def _sealed_error_receipt(
    *,
    root_run_id: str,
    failure_kind: str,
    summary: dict[str, object],
    candidate_proposal: HarnessProposal,
    baseline_digest: str,
    task_b_result_digest: str,
) -> P6NativeReceipt:
    """Build and seal a :class:`P6NativeReceipt` for one of the four
    failure paths (cancellation / candidate-admission / holdout-
    evaluation / promotion-action).

    All four paths fold into ``terminal_outcome="rolled-back"`` per
    spec L283–L292; the diagnostic digest is the canonical-form
    SHA-256 of the failure kind + summary fields, content-safe per
    spec L437–L438 (no prompt bodies, no model prose, no source
    locations).
    """

    payload = {
        "failure_kind": failure_kind,
        "summary": summary,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    failure_digest = sha256(encoded).hexdigest()
    raw_receipt = P6NativeReceipt(
        root_run_id=root_run_id,
        baseline_snapshot_digest=baseline_digest,
        candidate_revision_digest=_evidence_digest(candidate_proposal),
        task_a_evidence_digest=_evidence_digest(candidate_proposal),
        task_b_result_digest=task_b_result_digest,
        terminal_outcome="rolled-back",
        global_activation_approved=bool(
            summary.get("global_activation_approved", False)
        ),
        rollback_invocation_count=int(summary.get("rollback_invocation_count", 0)),
        receipt_sha256="0" * 64,
        failure_digest=failure_digest,
    )
    return seal_p6_native_receipt(raw_receipt)


# ---------------------------------------------------------------------------
# Limits driver
# ---------------------------------------------------------------------------


async def _drive_limits_async(
    resources: _OperatorResources,
) -> list[P6LimitsRecord]:
    """Async limits driver: two refused scenarios in fixed order.

    The order is the spec's closed order: rolled-back then
    global-rejected. Each scenario opens its own candidate-store host
    service so cached loop state from one scenario does not bleed into
    the next.
    """

    return [
        await _run_scenario_rolled_back(resources),
        await _run_scenario_global_rejected(resources),
    ]


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def _invoke_composed_loop(
    resources: _OperatorResources,
) -> list[dict[str, object]]:
    """Async dispatch on ``resources.mode`` to the right path.

    Preserved path returns one record; limits path returns two records
    in fixed order (rolled-back then global-rejected). Each record is
    a content-safe ``dict`` ready for canonical-JSON serialisation.
    """

    if resources.mode == "preserved":
        result = await _drive_preserved_path(resources)
        return [asdict(result)]
    records = await _drive_limits_async(resources)
    return [asdict(record) for record in records]


def _emit(records: list[dict[str, object]]) -> None:
    for record in records:
        print(json.dumps(record, separators=(",", ":")))
    sys.stdout.flush()


async def _run_async(
    environment: Mapping[str, str],
) -> tuple[int, list[dict[str, object]]]:
    """Top-level async driver used by the sync entry points.

    Returns ``(exit_code, records)``. Caller emits records to stdout.
    Preflight failure → 2; operator error → 1; success → 0.
    """

    try:
        preflight = _preflight(environment)
    except P6OperatorError:
        return 2, []
    try:
        resources = await _build_resources(preflight)
        records = await _invoke_composed_loop(resources)
    except P6OperatorError:
        return 2, []
    except BaseException:
        return 1, []
    return 0, records


def run_preserved_path(environment: Mapping[str, str]) -> int:
    """Run the operator in ``preserved`` mode and emit one JSON record.

    Returns 0 on success, 2 on preflight failure, 1 on operator error.
    """

    rc, records = asyncio.run(_run_async(environment))
    if rc != 0:
        return rc
    _emit(records)
    if records and records[0].get("status") == "completed":
        return 0
    return 2


def run_limits_path(environment: Mapping[str, str]) -> int:
    """Run the operator in ``limits`` mode and emit two JSON records.

    The limits path emits exactly two refusal records in fixed order:

    * ``rolled-back`` — holdout regressed, exact inverse revision
      applied, ``rollback_invocation_count=1``.
    * ``global-rejected`` — scope=global without
      ``global_activation_approved=True``, pre-orchestration boundary
      rejection.

    Returns 0 on success (two refusal records), 2 on preflight
    failure, 1 on operator error.
    """

    rc, records = asyncio.run(_run_async(environment))
    if rc != 0:
        return rc
    _emit(records)
    if (
        len(records) == 2
        and all(record.get("status") == "refused" for record in records)
        and records[0].get("scenario") == "rolled-back"
        and records[1].get("scenario") == "global-rejected"
    ):
        return 0
    return 2


def main() -> int:
    """Run one operator invocation; print one or two JSON lines; exit 0/2/1."""

    environment = dict(os.environ)
    preflight = _preflight(environment)
    if preflight.mode == "preserved":
        return run_preserved_path(environment)
    return run_limits_path(environment)


def _entrypoint() -> None:
    status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    raise SystemExit(status)


# ---------------------------------------------------------------------------
# Public test surface — see ``tests/test_asterion_prime_p6_operator.py``
# ---------------------------------------------------------------------------


async def drive_preserved_for_test(*, root_run_id: str) -> P6PublicResult:
    """In-process helper for the operator's ``preserved`` path.

    Returns a fully-sealed :class:`P6PublicResult` for the supplied
    ``root_run_id``. Used by the unit-test driver to assert every
    receipt field on the success path without going through the
    subprocess / Makefile supervisor.
    """

    scope = HarnessScope.project("prime.continual-improvement")
    resources = _OperatorResources(
        mode="preserved",
        private_root=Path("/tmp/p6-operator-test"),
        root_run_id=root_run_id,
        scope=scope,
        global_activation_approved=False,
        p6_oracle=P6Oracle(),
    )
    return await _drive_preserved_path(resources)


async def drive_scenario_rolled_back_for_test(*, root_run_id: str) -> P6LimitsRecord:
    """In-process helper for the ``rolled-back`` limits scenario."""

    scope = HarnessScope.project("prime.continual-improvement")
    resources = _OperatorResources(
        mode="limits",
        private_root=Path("/tmp/p6-operator-test"),
        root_run_id=root_run_id,
        scope=scope,
        global_activation_approved=False,
        p6_oracle=P6Oracle(),
    )
    return await _run_scenario_rolled_back(resources)


async def drive_scenario_global_rejected_for_test(
    *, root_run_id: str
) -> P6LimitsRecord:
    """In-process helper for the ``global-rejected`` limits scenario."""

    scope = HarnessScope.project("prime.continual-improvement")
    resources = _OperatorResources(
        mode="limits",
        private_root=Path("/tmp/p6-operator-test"),
        root_run_id=root_run_id,
        scope=scope,
        global_activation_approved=False,
        p6_oracle=P6Oracle(),
    )
    return await _run_scenario_global_rejected(resources)


async def drive_cancellation_for_test(*, root_run_id: str) -> P6NativeReceipt:
    """In-process helper for the cancellation-folded-to-rolled-back path."""

    scope = HarnessScope.project("prime.continual-improvement")
    loop, coordinator = await _open_candidate_store_for_run(
        scope=scope, global_activation_approved=False
    )
    baseline_snapshot = coordinator.snapshot()
    candidate_proposal = _build_candidate_proposal(
        proposal_id="candidate-cancel",
        scope=scope,
        baseline_snapshot_id=baseline_snapshot.snapshot_id,
    )
    unused_promotion = _build_promotion_proposal(
        proposal_id="promotion-unused",
        scope=scope,
        baseline_snapshot_id=baseline_snapshot.snapshot_id,
    )
    verdict, _terminal, summary = loop.promote_or_rollback(
        promotion_action=unused_promotion,
        rollback_proposal_id="rollback-1",
        rollback_authority_id="prime.candidate-store",
        rollback_authority_revision=1,
        rollback_target_revision_id="never-set",
        rollback_rationale_ref="private:rationale-rb",
        rollback_rationale_digest="f" * 64,
        rollback_expected_outcome_digest="1" * 64,
        signal=_AlwaysCancelled(),
    )
    if verdict != "rolled-back" or "cancellation_digest" not in summary:
        raise P6OperatorError()
    baseline_digest = _baseline_snapshot_digest(baseline_snapshot.entries)
    return _sealed_error_receipt(
        root_run_id=root_run_id,
        failure_kind=_fail_at_kind("cancellation"),
        summary=summary,
        candidate_proposal=candidate_proposal,
        baseline_digest=baseline_digest,
        task_b_result_digest="0" * 64,
    )


async def drive_candidate_admission_error_for_test(
    *, root_run_id: str
) -> P6NativeReceipt:
    """In-process helper for the candidate-admission-error path.

    Builds a candidate proposal whose scope mismatches the wrapped
    coordinator's scope — ``HarnessCoordinator.apply`` then raises
    :class:`HarnessError`, which the wrapper folds into
    :class:`CandidateStoreServiceError` (spec L283–L292). The error
    digest is the SHA-256 of the wrapped exception's canonical-form
    ``{kind, message, frame_fingerprints}`` projection.
    """

    scope = HarnessScope.project("prime.continual-improvement")
    loop, coordinator = await _open_candidate_store_for_run(
        scope=scope, global_activation_approved=False
    )
    baseline_snapshot = coordinator.snapshot()
    # Mismatched scope — coordinator rejects with ``HarnessError``.
    bad_candidate = _build_candidate_proposal(
        proposal_id="candidate-admission-fail",
        scope=HarnessScope.session("wrong-scope"),
        baseline_snapshot_id=baseline_snapshot.snapshot_id,
    )

    try:
        loop.admit_candidate(proposal=bad_candidate, signal=_NeverCancelled())
    except CandidateStoreServiceError as exc:
        summary = {
            "candidate_admission_error_digest": _hex_digest(repr(exc)),
            "rollback_invocation_count": 0,
            "global_activation_approved": False,
        }
    else:
        # Admission unexpectedly succeeded — surface as operator error.
        raise P6OperatorError()

    baseline_digest = _baseline_snapshot_digest(baseline_snapshot.entries)
    return _sealed_error_receipt(
        root_run_id=root_run_id,
        failure_kind=_fail_at_kind("candidate_admission"),
        summary=summary,
        candidate_proposal=bad_candidate,
        baseline_digest=baseline_digest,
        task_b_result_digest="0" * 64,
    )


async def drive_holdout_evaluation_error_for_test(
    *, root_run_id: str
) -> P6NativeReceipt:
    """In-process helper for the holdout-evaluation-error path."""

    scope = HarnessScope.project("prime.continual-improvement")
    loop, coordinator = await _open_candidate_store_for_run(
        scope=scope, global_activation_approved=False
    )
    baseline_snapshot = coordinator.snapshot()
    candidate_proposal = _build_candidate_proposal(
        proposal_id="candidate-holdout-fail",
        scope=scope,
        baseline_snapshot_id=baseline_snapshot.snapshot_id,
    )

    def holdout_callable(candidate: HarnessRevision, baseline: object) -> HoldoutResult:
        raise HarnessError("SENTINEL_HOLDOUT_FAIL")

    loop.set_holdout_callable(holdout_callable=holdout_callable)
    candidate_revision = loop.admit_candidate(
        proposal=candidate_proposal, signal=_NeverCancelled()
    )

    try:
        loop.evaluate_holdout(
            candidate=candidate_revision,
            baseline=coordinator.snapshot(),
            signal=_NeverCancelled(),
        )
    except CandidateStoreServiceError as exc:
        summary = {
            "holdout_evaluation_error_digest": _hex_digest(repr(exc)),
            "rollback_invocation_count": 0,
            "global_activation_approved": False,
        }
    else:
        raise P6OperatorError()

    baseline_digest = _baseline_snapshot_digest(coordinator.snapshot().entries)
    return _sealed_error_receipt(
        root_run_id=root_run_id,
        failure_kind=_fail_at_kind("holdout_evaluation"),
        summary=summary,
        candidate_proposal=candidate_proposal,
        baseline_digest=baseline_digest,
        task_b_result_digest="0" * 64,
    )


async def drive_promotion_action_error_for_test(*, root_run_id: str) -> P6NativeReceipt:
    """In-process helper for the promotion-action-error path.

    A promotion whose scope mismatches the wrapped coordinator's
    scope triggers :class:`HarnessError` from ``HarnessCoordinator.apply``,
    which the wrapper folds into ``rolled-back`` + a
    ``promotion_action_error_digest``.
    """

    scope = HarnessScope.project("prime.continual-improvement")
    loop, coordinator = await _open_candidate_store_for_run(
        scope=scope, global_activation_approved=False
    )
    baseline_snapshot = coordinator.snapshot()
    candidate_proposal = _build_candidate_proposal(
        proposal_id="candidate-promotion-fail",
        scope=scope,
        baseline_snapshot_id=baseline_snapshot.snapshot_id,
    )

    task_b_sha = _fake_worker_payload_sha(
        mode="preserved", candidate_kind="admit", run_id=root_run_id
    )

    def holdout_callable(candidate: HarnessRevision, baseline: object) -> HoldoutResult:
        return HoldoutResult(
            task_b_result_sha256=task_b_sha,
            non_regressing=True,
        )

    loop.set_holdout_callable(holdout_callable=holdout_callable)
    candidate_revision = loop.admit_candidate(
        proposal=candidate_proposal, signal=_NeverCancelled()
    )
    loop.evaluate_holdout(
        candidate=candidate_revision,
        baseline=coordinator.snapshot(),
        signal=_NeverCancelled(),
    )

    # Promotion proposal with the wrong scope: the coordinator rejects
    # ``apply`` with :class:`HarnessError`; the wrapper folds the
    # failure into ``rolled-back`` + ``promotion_action_error_digest``.
    bad_promotion = HarnessProposal(
        proposal_id="promotion-bad",
        authority_id="prime.candidate-store",
        authority_revision=1,
        scope=HarnessScope.session("wrong-scope"),
        baseline_snapshot_id=coordinator.snapshot().snapshot_id,
        edits=(HarnessEdit.create(_entry("bad-promotion")),),
        evidence_ids=("promotion-bad-evidence",),
        rationale_ref="private:bad-rationale",
        rationale_digest="9" * 64,
        expected_outcome_digest="8" * 64,
    )

    verdict, _terminal, summary = loop.promote_or_rollback(
        promotion_action=bad_promotion,
        rollback_proposal_id="rollback-1",
        rollback_authority_id="prime.candidate-store",
        rollback_authority_revision=1,
        rollback_target_revision_id=candidate_revision.revision_id,
        rollback_rationale_ref="private:rationale-rb",
        rollback_rationale_digest="f" * 64,
        rollback_expected_outcome_digest="1" * 64,
        signal=_NeverCancelled(),
    )
    if verdict != "rolled-back" or "promotion_action_error_digest" not in summary:
        raise P6OperatorError()

    baseline_digest = _baseline_snapshot_digest(coordinator.snapshot().entries)
    return _sealed_error_receipt(
        root_run_id=root_run_id,
        failure_kind=_fail_at_kind("promotion_action"),
        summary=summary,
        candidate_proposal=candidate_proposal,
        baseline_digest=baseline_digest,
        task_b_result_digest=task_b_sha,
    )


def _hex_digest(value: str) -> str:
    """Compute a 64-hex SHA-256 digest for a string payload."""

    return sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    _entrypoint()


__all__ = (
    "P6LimitsRecord",
    "P6OperatorError",
    "P6PublicResult",
    "_entrypoint",
    "drive_candidate_admission_error_for_test",
    "drive_cancellation_for_test",
    "drive_holdout_evaluation_error_for_test",
    "drive_preserved_for_test",
    "drive_promotion_action_error_for_test",
    "drive_scenario_global_rejected_for_test",
    "drive_scenario_rolled_back_for_test",
    "main",
    "run_limits_path",
    "run_preserved_path",
)
