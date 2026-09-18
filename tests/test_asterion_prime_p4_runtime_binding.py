"""P4 runtime binding: host-capability contract, options, dispatcher routing."""

from __future__ import annotations

from pathlib import Path
import unittest

from asterion.applications.prime.p4.runtime_binding import (
    P4_HOST_CAPABILITIES,
    P4_RUNTIME_OPTIONS,
    build_p4_runtime,
)
from asterion.applications.prime.runtime_binding import (
    build_asterion_prime_runtime,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError


def _make_context(**overrides: object) -> RuntimeFactoryContext:
    # All host services are placeholders; the runtime-binding code only
    # checks identity via isinstance(..., ContinuityStoreHostService) and
    # isinstance(..., P4RuntimeHost). For preflight we need a real
    # ContinuityStoreHostService and P4RuntimeHost instance, but the
    # rejection tests fail before reaching validate_runtime_services, so
    # plain object() placeholders are sufficient there.
    services: dict[str, object] = {name: object() for name in P4_HOST_CAPABILITIES}
    # prime.private-trace is allowed to be None for P4 (no persistent session).
    services["prime.private-trace"] = None
    defaults: dict[str, object] = {
        "provider_id": "prime-applications",
        "application_id": "prime.long-session-continuity",
        "application_version": "1.0.0",
        "runtime_id": "asterion.prime",
        "assembly_path": Path("/dev/null"),
        "options": dict(P4_RUNTIME_OPTIONS),
        "host_services": services,
    }
    defaults.update(overrides)
    return RuntimeFactoryContext(**defaults)  # type: ignore[arg-type]


class P4RuntimeBindingTests(unittest.TestCase):
    def test_options_match_exact(self) -> None:
        self.assertEqual(
            dict(P4_RUNTIME_OPTIONS),
            {
                "aggregate_tokens": "32000",
                "cost_micros": "300000",
                "deadline_ms": "120000",
                "max_callbacks": "4",
                "max_tool_callbacks": "2",
            },
        )

    def test_host_capabilities_match_spec(self) -> None:
        # The spec (L115) names these five host capabilities for P4.
        self.assertEqual(
            P4_HOST_CAPABILITIES,
            (
                "prime.continuity-store",
                "prime.p4-oracle",
                "prime.pi-extension",
                "prime.private-trace",
                "prime.session-backend",
            ),
        )

    def test_rejects_wrong_application_id(self) -> None:
        ctx = _make_context(application_id="prime.ipython-coding")
        with self.assertRaises(RuntimeFactoryError):
            build_p4_runtime(ctx)

    def test_rejects_wrong_provider(self) -> None:
        ctx = _make_context(provider_id="other-applications")
        with self.assertRaises(RuntimeFactoryError):
            build_p4_runtime(ctx)

    def test_rejects_missing_host_capability(self) -> None:
        ctx = _make_context(
            host_services={
                name: object() for name in P4_HOST_CAPABILITIES if name != "prime.p4-oracle"
            }
        )
        with self.assertRaises(RuntimeFactoryError):
            build_p4_runtime(ctx)

    def test_rejects_extra_host_capability(self) -> None:
        services = {name: object() for name in P4_HOST_CAPABILITIES}
        services["prime.unexpected"] = object()
        ctx = _make_context(host_services=services)
        with self.assertRaises(RuntimeFactoryError):
            build_p4_runtime(ctx)

    def test_rejects_altered_runtime_options(self) -> None:
        ctx = _make_context(options={"aggregate_tokens": "32001"})
        with self.assertRaises(RuntimeFactoryError):
            build_p4_runtime(ctx)


class AsterionPrimeDispatcherTests(unittest.TestCase):
    def test_dispatcher_routes_p4_application_id_to_build_p4_runtime(self) -> None:
        # We can't easily construct a fully-valid context here, so we just
        # verify the dispatcher dispatches to P4 by passing an invalid
        # context (wrong application_id) and confirming the dispatcher
        # rejects it with RuntimeFactoryError — proving the dispatch path
        # at least gets exercised.
        ctx = _make_context(application_id="prime.long-session-continuity")
        # Patch build_p4_runtime to a sentinel that raises a specific
        # marker, confirming dispatch.
        sentinel_calls: list[bool] = []

        def _sentinel_build(_context: object) -> None:
            sentinel_calls.append(True)
            raise RuntimeFactoryError("sentinel")

        import asterion.applications.prime.p4.runtime_binding as p4_binding

        original = p4_binding.build_p4_runtime
        p4_binding.build_p4_runtime = _sentinel_build
        try:
            with self.assertRaises(RuntimeFactoryError):
                build_asterion_prime_runtime(ctx)
            self.assertTrue(sentinel_calls)
        finally:
            p4_binding.build_p4_runtime = original

    def test_dispatcher_rejects_unknown_application(self) -> None:
        ctx = _make_context(application_id="prime.unknown")
        with self.assertRaises(RuntimeFactoryError):
            build_asterion_prime_runtime(ctx)


if __name__ == "__main__":
    unittest.main()