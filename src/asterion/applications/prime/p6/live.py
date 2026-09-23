"""One bounded, model-proposed P6 candidate through the composed application."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from typing import Callable, Mapping

from asterion.applications.prime.live_model import (
    LiveModelReply,
    LiveModelSession,
    resolve_live_model_launch,
)
from asterion.applications.prime.p6.host import (
    P6AdmittedProposal,
    P6HoldoutResult,
    P6PromotionAction,
)
from asterion.applications.prime.p6.live_task import (
    P6Candidate,
    evaluate_holdout,
    parse_candidate,
    task_a_evidence,
)
from asterion.applications.prime.p6.operator import (
    P6OperatorError,
    P6PublicResult,
    _ComposedCandidateHost,
    _NeverCancelled,
    _OperatorResources,
    _baseline_snapshot_digest,
    _open_candidate_store_for_run,
    _seal_receipt_from_loop,
)
from asterion.applications.prime.p6.oracle import P6Oracle
from asterion.applications.prime.services import HoldoutResult
from asterion.control.harness import (
    HarnessEdit,
    HarnessEffectReceipt,
    HarnessEntryDescriptor,
    HarnessProposal,
    HarnessScope,
    MemoryHarnessPrivateRevisionStore,
    harness_effect_digest,
)
from asterion.runtime.host import CancellationSignal


_TASK_A_PROMPT = (
    "Find the integer affine rule y = multiplier*x + offset for these training "
    "examples: 1 -> 4, 4 -> 13, 7 -> 22. Respond with only a JSON object "
    'having exactly integer keys "multiplier" and "offset". Bounds: -16 to 16.'
)


def _descriptor(
    entry_id: str, candidate: P6Candidate, train_sha: str
) -> HarnessEntryDescriptor:
    return HarnessEntryDescriptor(
        entry_id=entry_id,
        kind="memory",
        title_digest=sha256(b"p6-affine-candidate").hexdigest(),
        body_ref=f"private:{candidate.body_sha256}",
        body_digest=candidate.body_sha256,
        grouping_path_digest=None,
        metadata_digest=train_sha,
        version=1,
    )


def _proposal(
    *,
    proposal_id: str,
    entry_id: str,
    candidate: P6Candidate,
    train_sha: str,
    scope: HarnessScope,
    baseline_snapshot_id: str,
) -> HarnessProposal:
    return HarnessProposal(
        proposal_id=proposal_id,
        authority_id="prime.candidate-store",
        authority_revision=1,
        scope=scope,
        baseline_snapshot_id=baseline_snapshot_id,
        edits=(HarnessEdit.create(_descriptor(entry_id, candidate, train_sha)),),
        evidence_ids=(f"evidence-{train_sha}",),
        rationale_ref=f"private:{candidate.body_sha256}",
        rationale_digest=train_sha,
        expected_outcome_digest=candidate.body_sha256,
    )


async def _run_workflow(
    resources,
    loop,
    coordinator,
    signal,
    *,
    non_regressing,
    candidate: P6Candidate,
    train_sha: str,
):
    baseline = coordinator.snapshot()
    candidate_proposal = _proposal(
        proposal_id="candidate-1",
        entry_id="memory-1",
        candidate=candidate,
        train_sha=train_sha,
        scope=resources.scope,
        baseline_snapshot_id=baseline.snapshot_id,
    )
    revision = loop.admit_candidate(proposal=candidate_proposal, signal=signal)
    after_admit = coordinator.snapshot()
    evidence = evaluate_holdout(candidate)
    private_evidence = json.dumps(
        {
            "candidate_body_sha256": candidate.body_sha256,
            "task_a_evidence_digest": train_sha,
            "baseline_error": evidence.baseline_error,
            "candidate_error": evidence.candidate_error,
            "improved": evidence.improved,
            "task_b_result_digest": evidence.task_b_result_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    evidence_path = resources.private_root / "holdout-evidence.json"
    evidence_fd = os.open(evidence_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(evidence_fd, "wb") as stream:
        stream.write(private_evidence)

    def holdout_callable(admitted, baseline_entries):
        if (
            admitted.revision_id != revision.revision_id
            or baseline_entries != baseline.entries
        ):
            raise P6OperatorError()
        return HoldoutResult(evidence.task_b_result_sha256, evidence.improved)

    loop.set_holdout_callable(holdout_callable=holdout_callable)
    holdout = loop.evaluate_holdout(
        candidate=revision, baseline=baseline.entries, signal=signal
    )
    promotion = _proposal(
        proposal_id="promotion-1",
        entry_id="skill-promotion-1",
        candidate=candidate,
        train_sha=train_sha,
        scope=resources.scope,
        baseline_snapshot_id=after_admit.snapshot_id,
    )
    verdict, terminal, summary = loop.promote_or_rollback(
        promotion_action=promotion,
        rollback_proposal_id="rollback-1",
        rollback_authority_id="prime.candidate-store",
        rollback_authority_revision=1,
        rollback_target_revision_id=revision.revision_id,
        rollback_rationale_ref="private:rollback-rationale",
        rollback_rationale_digest=train_sha,
        rollback_expected_outcome_digest=candidate.body_sha256,
        signal=signal,
    )
    now = datetime.now(timezone.utc)
    oracle = resources.p6_oracle.check(
        root_run_id=resources.root_run_id,
        admitted_proposal=P6AdmittedProposal(
            candidate_proposal.proposal_id,
            candidate_proposal.digest,
            revision.revision_id,
            now,
        ),
        holdout_result=P6HoldoutResult(
            holdout.task_b_result_sha256,
            holdout.non_regressing,
            now,
        ),
        promotion_action=(
            P6PromotionAction(
                promotion.proposal_id, promotion.digest, revision.revision_id, now
            )
            if verdict == "preserved"
            else None
        ),
        rollback_invocation_count=loop.rollback_invocation_count,
        global_activation_approved=False,
        signal=signal,
    )
    if oracle.verdict != verdict or terminal != verdict:
        raise P6OperatorError()
    return _seal_receipt_from_loop(
        loop=loop,
        root_run_id=resources.root_run_id,
        candidate_revision=revision,
        candidate_proposal=candidate_proposal,
        baseline_digest=_baseline_snapshot_digest(baseline.entries),
        holdout_result=holdout,
        verdict=verdict,
        summary=summary,
        failure_digest=None,
        task_a_evidence_digest=train_sha,
    )


async def run_live_candidate(
    *,
    session_factory: Callable[[], LiveModelSession],
    root_run_id: str,
    private_root: Path,
    signal: CancellationSignal | None = None,
) -> P6PublicResult:
    """Propose on task A, independently test task B, then compose the P6 run."""

    from asterion.applications.provider import compose_installed_provider
    from asterion.applications.prime.provider import (
        create_prime_continual_improvement_provider,
    )
    from asterion.applications.prime.p6.runtime_binding import (
        P6_RUNTIME_OPTIONS,
        build_p6_runtime,
    )
    from asterion.capabilities.prime_continual_improvement_native.provider import (
        create_prime_continual_improvement_native_package,
    )
    from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryRegistry
    from asterion.runner.composed import run_composed_application

    if (
        type(root_run_id) is not str
        or not root_run_id
        or not isinstance(private_root, Path)
    ):
        raise P6OperatorError()
    active_signal = signal or _NeverCancelled()
    session = None
    try:
        session = session_factory()
        await session.open(signal=active_signal)
        reply: LiveModelReply = await session.prompt(
            _TASK_A_PROMPT, signal=active_signal
        )
        candidate = parse_candidate(reply.text)
    except BaseException as error:
        if isinstance(
            error,
            (asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit),
        ):
            raise
        raise P6OperatorError() from None
    finally:
        if session is not None:
            await session.close()

    root = private_root.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    body_path = root / "candidate.json"
    descriptor = os.open(body_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(candidate.body)
    train_sha = task_a_evidence(candidate)
    scope = HarnessScope.project("prime.continual-improvement")
    resources = _OperatorResources(
        mode="live",
        private_root=root,
        root_run_id=root_run_id,
        scope=scope,
        global_activation_approved=False,
        p6_oracle=P6Oracle(),
    )

    def effect_sender(proposal):
        changed = tuple(
            edit.replacement for edit in proposal.edits if edit.replacement is not None
        )
        model_effect = proposal.proposal_id == "candidate-1"
        return HarnessEffectReceipt.succeeded(
            proposal,
            effect_digest=harness_effect_digest(proposal),
            result_entries=changed,
            usage={
                "aggregate_tokens": (
                    reply.usage.input_tokens + reply.usage.output_tokens
                    if model_effect
                    else 0
                ),
                "cost_micros": reply.usage.cost_micros if model_effect else 0,
                "model_credential_reads": 1 if model_effect else 0,
                "provider_operations": 1 if model_effect else 0,
            },
        )

    loop, coordinator = await _open_candidate_store_for_run(
        scope=scope,
        global_activation_approved=False,
        private_store=MemoryHarnessPrivateRevisionStore(),
        effect_sender=effect_sender,
    )

    async def workflow(resources, loop, coordinator, signal, *, non_regressing):
        return await _run_workflow(
            resources,
            loop,
            coordinator,
            signal,
            non_regressing=non_regressing,
            candidate=candidate,
            train_sha=train_sha,
        )

    host = _ComposedCandidateHost(resources, loop, coordinator, workflow=workflow)
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
    try:
        result = await run_composed_application(
            plan,
            implementations=tuple(
                (binding.capability_ref, binding.implementation)
                for binding in package.implementations
            ),
            runtime=runtime,
            run_id=root_run_id,
            input_text="fixed-continual-improvement",
            host_services=services,
            signal=active_signal,
        )
        if (
            host.receipt is None
            or len(result.artifacts) != 1
            or result.artifacts[0]["value"]["receipt_sha256"]
            != host.receipt.receipt_sha256
        ):
            raise P6OperatorError()
        status = "completed"
    except Exception:
        if host.receipt is None or host.receipt.terminal_outcome != "rolled-back":
            raise P6OperatorError() from None
        status = "refused"
    return P6PublicResult(status=status, **asdict(host.receipt))


def run_operator_live(environment: Mapping[str, str]) -> int:
    """Run the fixed public-safe P6 live preset from operator-owned resources."""

    try:
        operator_value = environment.get("ASTERION_PRIME_OPERATOR_ROOT", "")
        private_value = environment.get("ASTERION_PRIME_P6_PRIVATE_ROOT", "")
        if not operator_value or not private_value:
            raise P6OperatorError()
        launch = resolve_live_model_launch(Path(operator_value), environment)
        private_base = Path(private_value).resolve()
        private_base.mkdir(parents=True, exist_ok=True, mode=0o700)
        child = Path(tempfile.mkdtemp(prefix="live-", dir=private_base))
        result = asyncio.run(
            run_live_candidate(
                session_factory=lambda: LiveModelSession(
                    command=launch.command,
                    environment=launch.environment,
                    cwd=launch.cwd,
                ),
                root_run_id="p6-live-" + secrets.token_hex(8),
                private_root=child,
            )
        )
        print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
        return 0 if result.status == "completed" else 2
    except Exception:
        print('{"reason":"p6-live-unavailable","status":"failed"}')
        return 2


def main() -> int:
    return run_operator_live(dict(os.environ))


__all__ = ("main", "run_live_candidate", "run_operator_live")


if __name__ == "__main__":
    status = main()
    sys.stdout.flush()
    raise SystemExit(status)
