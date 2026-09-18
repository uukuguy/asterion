"""P5 runtime binding: host-capability contract, options, validation surface."""

from __future__ import annotations

from pathlib import Path
import unittest

from asterion.applications.prime.p5.oracle import P5Oracle
from asterion.applications.prime.p5.runtime_binding import (
    P5_HOST_CAPABILITIES,
    P5_RUNTIME_OPTIONS,
    build_p5_runtime,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError


class _StubP5RuntimeHost:
    """Minimal stub satisfying the P5RuntimeHost Protocol shape.

    The runtime binding's ``isinstance`` check uses ``@runtime_checkable``
    on the Protocol, so the stub only needs the four method names — the
    bodies are never invoked by the test.
    """

    def validate_runtime_services(self, services) -> None:
        return None

    async def run_loop(self, *, root_run_id, signal):
        return None  # type: ignore[return-value]

    def report_loop_stopped(self, *, terminal_reason, root_run_id):
        return None

    async def wait_finalization(self, *, signal):
        return None  # type: ignore[return-value]


def _make_context(**overrides: object) -> RuntimeFactoryContext:
    # All host services are placeholders; the runtime-binding code only
    # checks identity via isinstance(..., P5RuntimeHost) and
    # isinstance(..., P5Oracle). For tests that drive build_p5_runtime,
    # those placeholders are plain object() instances — the rejection
    # paths fail before the P5RuntimeHost implementation is ever invoked.
    services: dict[str, object] = {name: object() for name in P5_HOST_CAPABILITIES}
    # prime.private-trace is allowed to be None for P5 (no persistent
    # session to trace).
    services["prime.private-trace"] = None
    defaults: dict[str, object] = {
        "provider_id": "prime-applications",
        "application_id": "prime.bounded-autonomy",
        "application_version": "1.0.0",
        "runtime_id": "asterion.prime",
        "assembly_path": Path("/dev/null"),
        "options": dict(P5_RUNTIME_OPTIONS),
        "host_services": services,
    }
    defaults.update(overrides)
    return RuntimeFactoryContext(**defaults)  # type: ignore[arg-type]


class P5RuntimeBindingTests(unittest.TestCase):
    def test_options_match_exact(self) -> None:
        # Sanity: the operator passes these exact strings into the
        # P5 bounded-autonomy witness.
        self.assertEqual(
            dict(P5_RUNTIME_OPTIONS),
            {
                "aggregate_tokens": "32000",
                "cost_micros": "300000",
                "deadline_ms": "120000",
                "max_callbacks": "4",
                "max_tool_callbacks": "2",
            },
        )

    def test_host_capabilities_match_spec(self) -> None:
        # The application assembly JSON
        # (src/asterion/applications/prime/assemblies/prime-bounded-autonomy.json)
        # names these five host capabilities for P5.
        self.assertEqual(
            P5_HOST_CAPABILITIES,
            (
                "prime.ipython",
                "prime.p5-oracle",
                "prime.pi-extension",
                "prime.private-trace",
                "prime.session-backend",
            ),
        )

    def test_p5_host_capabilities_match_application_assembly(self) -> None:
        # Cross-check the runtime-binding tuple against the assembly
        # JSON — set equality is the spec's contract.
        import json

        path = (
            Path(__file__).resolve().parents[1]
            / "src/asterion/applications/prime/assemblies/prime-bounded-autonomy.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(P5_HOST_CAPABILITIES), set(data["host_capabilities"]))

    def test_build_p5_runtime_returns_client_with_p5_methods(self) -> None:
        # Build a context whose host-services are P5-shaped, then
        # assert that the returned client surfaces the four
        # P5RuntimeHost methods on the bound session.
        session_backend = _StubP5RuntimeHost()
        oracle = P5Oracle()
        services: dict[str, object] = {
            "prime.ipython": object(),
            "prime.p5-oracle": oracle,
            "prime.pi-extension": object(),
            "prime.private-trace": None,
            "prime.session-backend": session_backend,
        }
        ctx = _make_context(host_services=services)
        client = build_p5_runtime(ctx)
        session = client._session  # type: ignore[attr-defined]
        self.assertTrue(hasattr(session, "validate_runtime_services"))
        self.assertTrue(hasattr(session, "run_loop"))
        self.assertTrue(hasattr(session, "report_loop_stopped"))
        self.assertTrue(hasattr(session, "wait_finalization"))
        self.assertTrue(callable(session.validate_runtime_services))
        self.assertTrue(callable(session.run_loop))
        self.assertTrue(callable(session.report_loop_stopped))
        self.assertTrue(callable(session.wait_finalization))

    def test_p5_runtime_session_validates_services(self) -> None:
        # Construct a session by hand (avoiding build_p5_runtime's
        # full validation), then drive validate_runtime_services to
        # confirm it accepts the 5-tuple and rejects drift.
        from asterion.applications.prime.p5.runtime_binding import (
            _P5RuntimeSession,
        )

        services: dict[str, object] = {name: object() for name in P5_HOST_CAPABILITIES}
        services["prime.private-trace"] = None
        session = _P5RuntimeSession(
            session_backend=object(),  # type: ignore[arg-type]
            oracle=object(),  # type: ignore[arg-type]
            private_trace=None,
        )
        # Accept the exact 5-tuple.
        session.validate_runtime_services(services)

        # Reject a missing key.
        missing = {
            name: object()
            for name in P5_HOST_CAPABILITIES
            if name != "prime.p5-oracle"
        }
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
            build_p5_runtime(ctx)

    def test_rejects_wrong_provider(self) -> None:
        ctx = _make_context(provider_id="other-applications")
        with self.assertRaises(RuntimeFactoryError):
            build_p5_runtime(ctx)

    def test_rejects_missing_host_capability(self) -> None:
        ctx = _make_context(
            host_services={
                name: object()
                for name in P5_HOST_CAPABILITIES
                if name != "prime.p5-oracle"
            }
        )
        with self.assertRaises(RuntimeFactoryError):
            build_p5_runtime(ctx)

    def test_rejects_extra_host_capability(self) -> None:
        services = {name: object() for name in P5_HOST_CAPABILITIES}
        services["prime.unexpected"] = object()
        ctx = _make_context(host_services=services)
        with self.assertRaises(RuntimeFactoryError):
            build_p5_runtime(ctx)

    def test_rejects_altered_runtime_options(self) -> None:
        ctx = _make_context(options={"aggregate_tokens": "32001"})
        with self.assertRaises(RuntimeFactoryError):
            build_p5_runtime(ctx)


if __name__ == "__main__":
    unittest.main()
