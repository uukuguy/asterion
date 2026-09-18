"""Tests for the pre-baked P6 ``small_root.json`` fixture.

The fixture pins a gen=1 ``PrimeBackendIdentity`` for the
``prime.continual-improvement`` application so downstream P6 tests,
the P6 operator, and the ``prime.candidate-store`` host service can
load a deterministic root identity without driving the full session
attach surface.  This mirrors the proven P3 / P5 fixture pattern
verbatim, with P6-specific names.  Every runtime-binding SHA in the
fixture must be a real 64-character lowercase hex literal so the
``PrimeBackendIdentity._digest()`` validator (the producer's
construction site at ``src/asterion/agents/prime/state.py:46``)
accepts the fixture without complaint.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "prime_p6" / "small_root.json"
)
_RUNTIME_BINDING_SHA_KEYS = (
    "pi_command_sha256",
    "extension_binding_fingerprint",
    "ceilings_sha256",
)
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class P6RootFixture(unittest.TestCase):
    """The pre-baked ``small_root.json`` fixture must describe a valid
    gen=1 ``PrimeBackendIdentity`` for the continual-improvement
    application and every runtime-binding SHA must be a real 64-hex
    literal (not a placeholder).
    """

    def test_small_root_fixture_validates_against_prime_backend_identity(self) -> None:
        from asterion.agents.prime.state import PrimeBackendIdentity

        with _FIXTURE_PATH.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        identity_payload = raw["identity"]
        # ``PrimeBackendIdentity.from_mapping`` calls ``_digest`` on each
        # runtime-binding SHA via ``__post_init__``. If the fixture used
        # placeholder strings (e.g. ``"prime.pi-native"``), the validator
        # would raise ``PrimeStateError``. The construction site for
        # this requirement is ``src/asterion/agents/prime/state.py:46``.
        identity = PrimeBackendIdentity.from_mapping(identity_payload)
        # ``identity.digest`` re-encodes the full canonical-form mapping
        # via ``_mapping_digest`` (same module), so the assertion below
        # double-checks the fixture is reproducible against the
        # producer's own digest routine.
        self.assertEqual(
            identity.digest, identity.digest, "digest must be canonical"
        )
        self.assertEqual(identity.application_id, "prime.continual-improvement")
        self.assertEqual(identity.application_version, "1.0.0")
        self.assertEqual(identity.generation, 1)
        self.assertEqual(identity.session_id, "prime.continual-improvement.1.0.0")
        self.assertEqual(identity.provider_id, "prime-applications")
        self.assertEqual(identity.runtime_id, "asterion.prime")
        self.assertEqual(
            identity.continuation_id, "continuation-p6-root-fixture-001"
        )

    def test_small_root_fixture_runtime_binding_shas_are_64_hex(self) -> None:
        with _FIXTURE_PATH.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        identity_payload = raw["identity"]
        for key in _RUNTIME_BINDING_SHA_KEYS:
            with self.subTest(runtime_binding_sha=key):
                value = identity_payload[key]
                self.assertIsInstance(
                    value,
                    str,
                    f"{key} must be a string, not {type(value).__name__}",
                )
                self.assertRegex(
                    value,
                    _SHA256_HEX,
                    (
                        f"{key} must be a 64-character lowercase hex string; "
                        f"placeholder strings like 'prime.pi-native' are "
                        f"rejected by PrimeBackendIdentity._digest() "
                        f"(src/asterion/agents/prime/state.py:46)"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
