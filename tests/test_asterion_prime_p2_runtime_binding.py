"""P2 runtime binding: host-capability contract, options, host service identity."""

from __future__ import annotations

import unittest
from pathlib import Path

from asterion.applications.prime.p2.runtime_binding import (
    P2_HOST_CAPABILITIES,
    P2_RUNTIME_OPTIONS,
    build_p2_runtime,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError


def _make_context(**overrides: object) -> RuntimeFactoryContext:
    services: dict[str, object] = {name: object() for name in P2_HOST_CAPABILITIES}
    # prime.private-trace is allowed to be None for P2.
    services["prime.private-trace"] = None
    defaults: dict[str, object] = {
        "provider_id": "prime-applications",
        "application_id": "prime.programmatic-long-context",
        "application_version": "1.0.0",
        "runtime_id": "asterion.prime",
        "assembly_path": Path("/dev/null"),
        "options": dict(P2_RUNTIME_OPTIONS),
        "host_services": services,
    }
    defaults.update(overrides)
    return RuntimeFactoryContext(**defaults)  # type: ignore[arg-type]


class P2RuntimeBindingTests(unittest.TestCase):
    def test_options_match_exact(self) -> None:
        # Sanity: the operator passes these exact strings into Pi.
        self.assertEqual(
            dict(P2_RUNTIME_OPTIONS),
            {
                "aggregate_tokens": "64000",
                "cost_micros": "500000",
                "deadline_ms": "600000",
                "max_callbacks": "8",
                "max_tool_callbacks": "4",
            },
        )

    def test_host_capabilities_match_spec(self) -> None:
        # The spec (L113) names these five host capabilities.
        self.assertEqual(
            P2_HOST_CAPABILITIES,
            (
                "prime.ipython",
                "prime.p2-oracle",
                "prime.pi-extension",
                "prime.private-trace",
                "prime.session-backend",
            ),
        )

    def test_rejects_wrong_application_id(self) -> None:
        ctx = _make_context(application_id="prime.ipython-coding")
        with self.assertRaises(RuntimeFactoryError):
            build_p2_runtime(ctx)

    def test_rejects_missing_host_capability(self) -> None:
        ctx = _make_context(
            host_services={name: object() for name in P2_HOST_CAPABILITIES if name != "prime.p2-oracle"}
        )
        with self.assertRaises(RuntimeFactoryError):
            build_p2_runtime(ctx)

    def test_rejects_extra_host_capability(self) -> None:
        services = {name: object() for name in P2_HOST_CAPABILITIES}
        services["prime.unexpected"] = object()
        ctx = _make_context(host_services=services)
        with self.assertRaises(RuntimeFactoryError):
            build_p2_runtime(ctx)

    def test_rejects_altered_runtime_options(self) -> None:
        ctx = _make_context(options={"aggregate_tokens": "64001"})
        with self.assertRaises(RuntimeFactoryError):
            build_p2_runtime(ctx)


if __name__ == "__main__":
    unittest.main()