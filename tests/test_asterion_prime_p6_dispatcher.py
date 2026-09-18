"""P6 dispatcher branch — routes ``prime.continual-improvement`` to ``build_p6_runtime``.

Mirror of the P4 / P5 dispatcher tests. Phase 9 Task 9 (plan
``docs/superpowers/plans/2026-09-19-asterion-prime-p6-native.md``)
adds the ``("prime.continual-improvement", "1.0.0")`` branch to
``build_asterion_prime_runtime``; this test asserts the dispatcher
routes to ``build_p6_runtime``.

The test installs a sentinel ``build_p6_runtime`` into
``sys.modules`` under ``asterion.applications.prime.p6.runtime_binding``
before invoking the dispatcher, so the test does not depend on
Task 7's ``p6.runtime_binding`` module being present on disk.
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path

from asterion.applications.prime.runtime_binding import (
    build_asterion_prime_runtime,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError


def _install_p6_runtime_binding_stub() -> tuple[types.ModuleType, object]:
    """Install a stub ``asterion.applications.prime.p6.runtime_binding`` module.

    The stub carries one attribute — ``build_p6_runtime`` — that the
    dispatcher's lazy import resolves. The test patches that attribute
    to a sentinel that records the call.

    Returns the stub module and the placeholder object stored as
    ``build_p6_runtime`` (the caller patches it).
    """

    package = importlib.import_module("asterion.applications.prime.p6")
    if not hasattr(package, "__path__"):
        # ``p6`` exists as a namespace module only (Task 7 not shipped).
        # Give it a synthetic __path__ so importlib treats it as a package.
        package.__path__ = []  # type: ignore[attr-defined]
    module = types.ModuleType("asterion.applications.prime.p6.runtime_binding")
    module.build_p6_runtime = None  # type: ignore[attr-defined]
    sys.modules["asterion.applications.prime.p6.runtime_binding"] = module
    setattr(package, "runtime_binding", module)
    return module, module.build_p6_runtime


def _remove_p6_runtime_binding_stub(module: types.ModuleType) -> None:
    """Tear down the stub installed by ``_install_p6_runtime_binding_stub``."""

    sys.modules.pop("asterion.applications.prime.p6.runtime_binding", None)
    package = sys.modules.get("asterion.applications.prime.p6")
    if package is not None and hasattr(package, "runtime_binding"):
        delattr(package, "runtime_binding")


def _make_context(application_id: str) -> RuntimeFactoryContext:
    """Build a context whose identity routes through the dispatcher.

    The dispatcher only inspects ``application_id`` and
    ``application_version`` to pick the branch — the sentinel test
    does not need any other field to be valid because the sentinel
    raises before the inner binding's validation runs.
    """

    return RuntimeFactoryContext(
        provider_id="prime-applications",
        application_id=application_id,
        application_version="1.0.0",
        runtime_id="asterion.prime",
        assembly_path=Path("/dev/null"),
        options={},
        host_services={},
    )


class AsterionPrimeP6DispatcherTests(unittest.TestCase):
    def test_dispatcher_routes_continual_improvement_to_build_p6_runtime(self) -> None:
        # Patch build_p6_runtime to a sentinel that records the call and
        # raises with a specific marker. The dispatcher lazy-imports the
        # symbol inside the ``if key == ...`` branch, so the patched
        # attribute on the installed module is picked up.
        stub, original_build = _install_p6_runtime_binding_stub()
        try:
            sentinel_calls: list[bool] = []

            def _sentinel_build(_context: object) -> None:
                sentinel_calls.append(True)
                raise RuntimeFactoryError("sentinel")

            stub.build_p6_runtime = _sentinel_build  # type: ignore[attr-defined]
            try:
                ctx = _make_context("prime.continual-improvement")
                with self.assertRaises(RuntimeFactoryError):
                    build_asterion_prime_runtime(ctx)
                self.assertTrue(
                    sentinel_calls,
                    "dispatcher did not route to build_p6_runtime",
                )
            finally:
                stub.build_p6_runtime = original_build  # type: ignore[attr-defined]
        finally:
            _remove_p6_runtime_binding_stub(stub)


if __name__ == "__main__":
    unittest.main()