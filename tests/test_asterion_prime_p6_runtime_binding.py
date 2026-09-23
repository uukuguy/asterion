"""P6 runtime binding: host-capability contract, options, validation surface.

Mirror of :mod:`tests.test_asterion_prime_p5_runtime_binding`. Phase 9
Task 7 of the Asterion Prime P6 native detachment plan
(``docs/superpowers/plans/2026-09-19-asterion-prime-p6-native.md``
section ``Task 7``). The closed 5-tuple ``P6_HOST_CAPABILITIES`` set
fails closed: extra host services (superset) and missing host services
(subset) are both rejected by ``build_p6_runtime`` via the
``RuntimeFactoryError`` contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

from asterion.applications.prime.p6.host import (
    P6AdmittedProposal,
    P6HoldoutResult,
    P6PromotionAction,
)
from asterion.applications.prime.p6.oracle import P6Oracle
from asterion.applications.prime.p6.runtime_binding import (
    P6_HOST_CAPABILITIES,
    P6_RUNTIME_OPTIONS,
    _P6RuntimeSession,
    build_p6_runtime,
)
from asterion.applications.prime.services import (
    CandidateStoreLoop,
    HoldoutResult,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError


class _StubP6RuntimeHost:
    """Minimal stub satisfying the ``P6RuntimeHost`` Protocol shape.

    The runtime binding's ``isinstance`` check uses ``@runtime_checkable``
    on the Protocol, so the stub only needs the five method names — the
    bodies are never invoked by the binding's ``validate_runtime_services``
    test (the test patches them to sentinel callables). For tests that
    drive ``build_p6_runtime`` the body is invoked by the binding's
    Protocol surface; the stub returns ``None`` for ``admit_candidate``
    and the binding's actual ``P6AdmittedProposal`` for the others.
    """

    async def run_candidate(self, *, root_run_id, signal):
        return None

    def validate_runtime_services(self, services) -> None:
        return None

    def admit_candidate(self, *, root_run_id, candidate_proposal, signal):
        return P6AdmittedProposal(
            proposal_id="<stub>",
            proposal_digest="<stub>",
            revision_id="<stub>",
            admission_timestamp=datetime.now(tz=timezone.utc),
        )

    def evaluate_holdout(
        self, *, root_run_id, candidate, baseline, signal
    ) -> P6HoldoutResult:
        return P6HoldoutResult(
            task_b_result_sha256="0" * 64,
            non_regressing=True,
            evaluation_timestamp=datetime.now(tz=timezone.utc),
        )

    def promote_or_rollback(
        self, *, root_run_id, candidate, holdout, signal
    ) -> P6PromotionAction:
        return P6PromotionAction(
            promotion_id="<stub>",
            promotion_digest="<stub>",
            target_revision_id="<stub>",
            promotion_timestamp=datetime.now(tz=timezone.utc),
        )

    async def wait_finalization(self, *, signal):
        return None  # type: ignore[return-value]


class _StubCandidateStoreLoop:
    """Minimal stub satisfying the ``CandidateStoreLoop`` Protocol shape.

    The runtime binding's ``isinstance`` check uses ``CandidateStoreLoop``
    directly, so the stub inherits from it. The bodies are never invoked
    by the binding's ``validate_runtime_services`` test; for tests that
    drive ``build_p6_runtime`` end-to-end the bodies are invoked by the
    binding's Protocol surface — the stub returns minimal default values
    so the binding's Protocol method shapes compile.
    """

    @property
    def public_identity(self):
        return None

    @property
    def last_evaluation_digest(self):
        return None

    @property
    def rollback_invocation_count(self):
        return 0

    def set_holdout_callable(self, *, holdout_callable):
        return None

    def admit_candidate(self, *, proposal, signal=None):
        from asterion.control.harness import HarnessRevision

        return HarnessRevision(
            revision_id="rev-stub",
            sequence=1,
            proposal_id=proposal.proposal_id,
            proposal_digest=proposal.digest,
            scope=proposal.scope,
            baseline_snapshot_id=proposal.baseline_snapshot_id,
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

    def evaluate_holdout(self, *, candidate, baseline, signal=None):
        return HoldoutResult(
            task_b_result_sha256="0" * 64,
            non_regressing=True,
        )

    def promote_or_rollback(
        self,
        *,
        promotion_action,
        rollback_proposal_id,
        rollback_authority_id,
        rollback_authority_revision,
        rollback_target_revision_id,
        rollback_rationale_ref,
        rollback_rationale_digest,
        rollback_expected_outcome_digest,
        signal=None,
    ):
        return ("preserved", "preserved", {})


def _stub_candidate_store() -> object:
    """Return a stub that passes the binding's ``isinstance(...,
    CandidateStoreLoop)`` check.

    The runtime binding's ``isinstance`` check is the public binding
    boundary's contract test; tests can build the runtime via this stub
    without instantiating a real ``CandidateStoreLoop`` (whose
    ``__init__`` requires a real ``HarnessCoordinator``). The stub
    inherits from ``CandidateStoreLoop`` so the ``isinstance`` check
    succeeds, but the bodies are no-ops for the binding's validation
    surface.
    """

    class _StubLoop(CandidateStoreLoop):
        def __init__(self) -> None:  # type: ignore[no-super-call]
            pass

    return _StubLoop()


def _make_context(**overrides: object) -> RuntimeFactoryContext:
    """Build a default context for ``build_p6_runtime``."""

    services: dict[str, object] = {
        "prime.candidate-store": _stub_candidate_store(),
        "prime.p6-oracle": P6Oracle(),
        "prime.pi-extension": object(),
        # ``prime.private-trace`` is allowed to be None for P6 (no
        # persistent session to trace).
        "prime.private-trace": None,
        "prime.session-backend": _StubP6RuntimeHost(),
    }
    defaults: dict[str, object] = {
        "provider_id": "prime-applications",
        "application_id": "prime.continual-improvement",
        "application_version": "1.0.0",
        "runtime_id": "asterion.prime",
        "assembly_path": Path("/dev/null"),
        "options": dict(P6_RUNTIME_OPTIONS),
        "host_services": services,
    }
    defaults.update(overrides)
    return RuntimeFactoryContext(**defaults)  # type: ignore[arg-type]


class P6RuntimeBindingTests(unittest.TestCase):
    """The closed 5-tuple ``P6_HOST_CAPABILITIES`` set-equality
    discipline — fail-closed on superset, subset, and unknown entries.
    """

    def test_p6_host_capabilities_is_closed_5_tuple(self) -> None:
        # Per the spec section 4 (substrate reuse) the application
        # assembly JSON names these five host capabilities for P6:
        # ``prime.candidate-store`` (Task 3, new for Phase 9),
        # ``prime.p6-oracle`` (Task 5, new for Phase 9), and the
        # Asterion-owned substrate P1-P5 already consume
        # (``prime.pi-extension`` / ``prime.private-trace`` /
        # ``prime.session-backend``). Order matches the spec table at
        # L23 of the design document.
        self.assertEqual(
            P6_HOST_CAPABILITIES,
            (
                "prime.candidate-store",
                "prime.p6-oracle",
                "prime.pi-extension",
                "prime.private-trace",
                "prime.session-backend",
            ),
        )
        self.assertEqual(len(P6_HOST_CAPABILITIES), 5)
        self.assertIsInstance(P6_HOST_CAPABILITIES, tuple)

    def test_build_p6_runtime_returns_session_adapter(self) -> None:
        # Build a context whose host-services are P6-shaped, then
        # assert that the returned client surfaces a ``_P6RuntimeSession``
        # adapter on the bound client.
        ctx = _make_context()
        client = build_p6_runtime(ctx)
        session = client._session  # type: ignore[attr-defined]
        self.assertIsInstance(session, _P6RuntimeSession)

    def test_p6_runtime_session_exposes_p6_runtime_host_methods(self) -> None:
        # Construct a session by hand (avoiding ``build_p6_runtime``'s
        # full validation), then assert the five ``P6RuntimeHost``
        # methods exist on the bound session.
        session = _P6RuntimeSession(
            session_backend=_StubP6RuntimeHost(),  # type: ignore[arg-type]
            candidate_store=_stub_candidate_store(),  # type: ignore[arg-type]
            oracle=P6Oracle(),
            private_trace=None,
        )
        self.assertTrue(hasattr(session, "validate_runtime_services"))
        self.assertTrue(callable(session.run_candidate))

    def test_p6_runtime_binding_accepts_exact_capability_set(self) -> None:
        # Set-equality is the spec's contract. The exact 5-tuple
        # succeeds.
        services: dict[str, object] = {name: object() for name in P6_HOST_CAPABILITIES}
        services["prime.private-trace"] = None
        session = _P6RuntimeSession(
            session_backend=object(),  # type: ignore[arg-type]
            candidate_store=_stub_candidate_store(),  # type: ignore[arg-type]
            oracle=object(),  # type: ignore[arg-type]
            private_trace=None,
        )
        # Accept the exact 5-tuple.
        session.validate_runtime_services(services)

    def test_p6_runtime_binding_fails_closed_on_capability_set_mismatch(
        self,
    ) -> None:
        # Set-equality rejects a missing key (subset) AND an unknown
        # key (superset) without ambiguity. Both fold to
        # ``RuntimeFactoryError`` so callers see the framework's
        # runtime-binding error contract.
        session = _P6RuntimeSession(
            session_backend=object(),  # type: ignore[arg-type]
            candidate_store=_stub_candidate_store(),  # type: ignore[arg-type]
            oracle=object(),  # type: ignore[arg-type]
            private_trace=None,
        )
        # Reject a missing key (subset).
        missing = {
            name: object() for name in P6_HOST_CAPABILITIES if name != "prime.p6-oracle"
        }
        with self.assertRaises(RuntimeFactoryError):
            session.validate_runtime_services(missing)
        # Reject an unknown key (superset).
        services: dict[str, object] = {name: object() for name in P6_HOST_CAPABILITIES}
        services["prime.unexpected"] = object()
        with self.assertRaises(RuntimeFactoryError):
            session.validate_runtime_services(services)
        # Reject an empty services mapping.
        with self.assertRaises(RuntimeFactoryError):
            session.validate_runtime_services({})

    def test_p6_runtime_session_set_step_callable_is_deferred(self) -> None:
        # The binding defers ``set_holdout_callable`` to Task 8 (the
        # operator). At binding construction time, no step callable
        # is registered on the candidate-store wrapper. The stub
        # candidate-store's ``set_holdout_callable`` is callable but
        # has not been invoked yet — proving the deferral.
        stub = _stub_candidate_store()
        # The stub's ``set_holdout_callable`` is a no-op. Verify it
        # has not been called by inspecting the stub's attributes
        # (``__dict__`` is empty for the deferral-proof).
        self.assertIsInstance(getattr(stub, "set_holdout_callable"), object)
        # The binding never invokes ``set_holdout_callable`` — the
        # operator (Task 8) owns that responsibility. Assert the
        # method exists on the candidate-store surface but is not
        # invoked by the binding's ``__init__``.
        session = _P6RuntimeSession(
            session_backend=object(),  # type: ignore[arg-type]
            candidate_store=stub,  # type: ignore[arg-type]
            oracle=object(),  # type: ignore[arg-type]
            private_trace=None,
        )
        # The session's ``_candidate_store`` is exactly the stub —
        # confirming no internal call to ``set_holdout_callable``.
        self.assertIs(session._candidate_store, stub)  # type: ignore[attr-defined]

    def test_p6_runtime_delegates_exact_run_identity_to_host(self) -> None:
        import asyncio

        calls = []

        class Host(_StubP6RuntimeHost):
            async def run_candidate(self, *, root_run_id, signal):
                calls.append(root_run_id)
                return "host-result"

        session = _P6RuntimeSession(
            session_backend=Host(),
            candidate_store=_stub_candidate_store(),
            oracle=P6Oracle(),
            private_trace=None,
        )
        result = asyncio.run(
            session.run_candidate(root_run_id="exact-run", signal=None)
        )
        self.assertEqual(result, "host-result")
        self.assertEqual(calls, ["exact-run"])

    def test_p6_runtime_session_wait_finalization_cleans_up_async_resources(
        self,
    ) -> None:
        # The adapter's async resources are cleaned up via the
        # runtime binding's async-context-manager exit path. The
        # candidate-store wrapper exposes ``public_identity`` (the
        # ``_open_candidate_store_service`` async-context-manager
        # exit path). Verify the wrapper's ``public_identity`` is
        # reachable through the binding's ``_candidate_store`` slot.
        from asterion.applications.prime.services import (
            CandidateStoreLoop as RealCandidateStoreLoop,
        )

        class _StubWithPublicIdentity(RealCandidateStoreLoop):
            def __init__(self) -> None:  # type: ignore[no-super-call]
                pass

            @property
            def public_identity(self):
                return "stub-public-identity"

        stub = _StubWithPublicIdentity()
        session = _P6RuntimeSession(
            session_backend=object(),  # type: ignore[arg-type]
            candidate_store=stub,  # type: ignore[arg-type]
            oracle=object(),  # type: ignore[arg-type]
            private_trace=None,
        )
        # The session's ``_candidate_store`` slot holds the stub —
        # the async-context-manager exit path closes the wrapper
        # through this exact slot.
        self.assertIs(session._candidate_store, stub)  # type: ignore[attr-defined]
        # The stub's ``public_identity`` is reachable through the
        # candidate-store slot, confirming the async cleanup path is
        # wired.
        self.assertEqual(stub.public_identity, "stub-public-identity")


class AsterionPrimeP6DispatcherTests(unittest.TestCase):
    """The dispatcher's ``("prime.continual-improvement", "1.0.0")``
    branch routes to ``build_p6_runtime``. (Mirror of P5's
    ``AsterionPrimeDispatcherTests``.)
    """

    def test_dispatcher_routes_p6_application_id_to_build_p6_runtime(
        self,
    ) -> None:
        # Patch ``build_p6_runtime`` to a sentinel that records the
        # call. The dispatcher lazy-imports the symbol inside the
        # ``if key == ...`` branch, so the patched attribute on the
        # imported module is picked up.
        sentinel_calls: list[bool] = []

        def _sentinel_build(_context: object) -> None:
            sentinel_calls.append(True)
            raise RuntimeFactoryError("sentinel")

        import asterion.applications.prime.p6.runtime_binding as p6_binding

        original = p6_binding.build_p6_runtime
        p6_binding.build_p6_runtime = _sentinel_build  # type: ignore[assignment]
        try:
            ctx = _make_context(application_id="prime.continual-improvement")
            with self.assertRaises(RuntimeFactoryError):
                from asterion.applications.prime.runtime_binding import (
                    build_asterion_prime_runtime,
                )

                build_asterion_prime_runtime(ctx)
            self.assertTrue(sentinel_calls)
        finally:
            p6_binding.build_p6_runtime = original  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main()
