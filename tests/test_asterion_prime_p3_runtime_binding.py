"""P3 runtime binding: host-capability contract, options, validation surface."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import unittest

from asterion.applications.prime.p3.oracle import P3Oracle
from asterion.applications.prime.p3.runtime_binding import (
    P3_HOST_CAPABILITIES,
    P3_RUNTIME_OPTIONS,
    build_p3_runtime,
)
from asterion.applications.prime.services import (
    ChildRunnerHostService,
    _ChildRunnerLimits,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError


class _StubP3RuntimeHost:
    """Minimal stub satisfying the P3RuntimeHost Protocol shape.

    The runtime binding's ``isinstance`` check uses ``@runtime_checkable``
    on the Protocol, so the stub only needs the four method names — the
    bodies are never invoked by the test.
    """

    def validate_runtime_services(self, services) -> None:
        return None

    async def run_root(self, *, parent_run_id, child_request, signal):
        return None  # type: ignore[return-value]

    def report_admission_refused(self, *, refusal) -> None:
        return None

    async def wait_finalization(self, *, signal):
        return None  # type: ignore[return-value]


def _make_context(**overrides: object) -> RuntimeFactoryContext:
    # All host services are placeholders; the runtime-binding code only
    # checks identity via isinstance(..., P3RuntimeHost) /
    # isinstance(..., ChildRunnerHostService) / isinstance(..., P3Oracle).
    # For tests that drive build_p3_runtime, those placeholders are
    # plain object() instances — the rejection paths fail before the
    # P3RuntimeHost implementation is ever invoked.
    services: dict[str, object] = {name: object() for name in P3_HOST_CAPABILITIES}
    # prime.private-trace is allowed to be None for P3 (no persistent
    # session to trace).
    services["prime.private-trace"] = None
    defaults: dict[str, object] = {
        "provider_id": "prime-applications",
        "application_id": "prime.recursive-workflow",
        "application_version": "1.0.0",
        "runtime_id": "asterion.prime",
        "assembly_path": Path("/dev/null"),
        "options": dict(P3_RUNTIME_OPTIONS),
        "host_services": services,
    }
    defaults.update(overrides)
    return RuntimeFactoryContext(**defaults)  # type: ignore[arg-type]


class P3RuntimeBindingTests(unittest.TestCase):
    def test_options_match_exact(self) -> None:
        # Sanity: the operator passes these exact strings into the
        # P3 recursive-workflow witness.
        self.assertEqual(
            dict(P3_RUNTIME_OPTIONS),
            {
                "aggregate_tokens": "16000",
                "cost_micros": "100000",
                "deadline_ms": "60000",
                "max_callbacks": "4",
                "max_tool_callbacks": "2",
            },
        )

    def test_host_capabilities_match_spec(self) -> None:
        # The application assembly JSON
        # (src/asterion/applications/prime/assemblies/prime-recursive-workflow.json)
        # names these five host capabilities for P3.
        self.assertEqual(
            P3_HOST_CAPABILITIES,
            (
                "prime.child-runner",
                "prime.p3-oracle",
                "prime.pi-extension",
                "prime.private-trace",
                "prime.session-backend",
            ),
        )

    def test_p3_host_capabilities_match_application_assembly(self) -> None:
        # Cross-check the runtime-binding tuple against the assembly
        # JSON — set equality is the spec's contract.
        import json

        path = (
            Path(__file__).resolve().parents[1]
            / "src/asterion/applications/prime/assemblies/prime-recursive-workflow.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(P3_HOST_CAPABILITIES), set(data["host_capabilities"]))

    def test_build_p3_runtime_returns_client_with_p3_methods(self) -> None:
        # Build a context whose host-services are P3-shaped, then
        # assert that the returned client surfaces the four
        # P3RuntimeHost methods on the bound session.
        session_backend = _StubP3RuntimeHost()
        child_runner = ChildRunnerHostService(
            limits=_ChildRunnerLimits(
                max_depth=2,
                max_concurrent_children=1,
                max_child_cost_usd=Decimal("0.10"),
                max_total_duration_ms=60_000,
            ),
            opened_at_iso="2026-09-18T00:00:00Z",
        )
        oracle = P3Oracle()
        services: dict[str, object] = {
            "prime.child-runner": child_runner,
            "prime.p3-oracle": oracle,
            "prime.pi-extension": object(),
            "prime.private-trace": None,
            "prime.session-backend": session_backend,
        }
        ctx = _make_context(host_services=services)
        client = build_p3_runtime(ctx)
        session = client._session  # type: ignore[attr-defined]
        self.assertTrue(hasattr(session, "validate_runtime_services"))
        self.assertTrue(hasattr(session, "run_root"))
        self.assertTrue(hasattr(session, "report_admission_refused"))
        self.assertTrue(hasattr(session, "wait_finalization"))
        self.assertTrue(callable(session.validate_runtime_services))
        self.assertTrue(callable(session.run_root))
        self.assertTrue(callable(session.report_admission_refused))
        self.assertTrue(callable(session.wait_finalization))

    def test_p3_runtime_session_validates_services(self) -> None:
        # Construct a session by hand (avoiding build_p3_runtime's
        # full validation), then drive validate_runtime_services to
        # confirm it accepts the 5-tuple and rejects drift.
        from asterion.applications.prime.p3.runtime_binding import (
            _P3RuntimeSession,
        )

        services: dict[str, object] = {name: object() for name in P3_HOST_CAPABILITIES}
        services["prime.private-trace"] = None
        session = _P3RuntimeSession(
            session_backend=object(),  # type: ignore[arg-type]
            child_runner=object(),  # type: ignore[arg-type]
            oracle=object(),  # type: ignore[arg-type]
            private_trace=None,
        )
        # Accept the exact 5-tuple.
        session.validate_runtime_services(services)

        # Reject a missing key.
        missing = {name: object() for name in P3_HOST_CAPABILITIES if name != "prime.p3-oracle"}
        with self.assertRaises(RuntimeFactoryError):
            session.validate_runtime_services(missing)

        # Reject an unknown key.
        extra = dict(services)
        extra["prime.unexpected"] = object()
        with self.assertRaises(RuntimeFactoryError):
            session.validate_runtime_services(extra)

    def test_rejects_wrong_application_id(self) -> None:
        ctx = _make_context(application_id="prime.ipython-coding")
        with self.assertRaises(RuntimeFactoryError):
            build_p3_runtime(ctx)

    def test_rejects_wrong_provider(self) -> None:
        ctx = _make_context(provider_id="other-applications")
        with self.assertRaises(RuntimeFactoryError):
            build_p3_runtime(ctx)

    def test_rejects_missing_host_capability(self) -> None:
        ctx = _make_context(
            host_services={
                name: object()
                for name in P3_HOST_CAPABILITIES
                if name != "prime.p3-oracle"
            }
        )
        with self.assertRaises(RuntimeFactoryError):
            build_p3_runtime(ctx)

    def test_rejects_extra_host_capability(self) -> None:
        services = {name: object() for name in P3_HOST_CAPABILITIES}
        services["prime.unexpected"] = object()
        ctx = _make_context(host_services=services)
        with self.assertRaises(RuntimeFactoryError):
            build_p3_runtime(ctx)

    def test_rejects_altered_runtime_options(self) -> None:
        ctx = _make_context(options={"aggregate_tokens": "16001"})
        with self.assertRaises(RuntimeFactoryError):
            build_p3_runtime(ctx)


if __name__ == "__main__":
    unittest.main()
