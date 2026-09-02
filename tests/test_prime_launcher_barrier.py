"""Provider-free tests for the Prime launch ordering barrier."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.applications.prime_agent.operator.launcher_barrier import (
    PrimeLauncherBarrier,
    PrimeLauncherBarrierError,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerLease,
)


_CHALLENGE = "sha256:" + "b" * 64
_IMAGE = "sha256:" + "a" * 64


def _lease(**changes: object) -> RestrictedWorkerLease:
    values: dict[str, object] = {
        "worker_id": "worker-1", "run_id": "run-1", "challenge_digest": _CHALLENGE,
    }
    values.update(changes)
    return RestrictedWorkerLease(**values)  # type: ignore[arg-type]


def _attestation(**changes: object) -> RestrictedWorkerAttestation:
    values: dict[str, object] = {
        "worker_id": "worker-1", "run_id": "run-1", "challenge_digest": _CHALLENGE,
        "image_digest": _IMAGE, "network_isolated": True, "root_read_only": True,
        "workspace_disposable": True, "credentials_absent": True,
        "kernel_credential_absent": True, "source_read_only": True, "resource_limited": True,
    }
    values.update(changes)
    return RestrictedWorkerAttestation(**values)  # type: ignore[arg-type]


class TestPrimeLauncherBarrier(unittest.TestCase):
    def test_releases_only_once_after_exact_admission(self) -> None:
        barrier = PrimeLauncherBarrier(run_id="run-1", challenge_digest=_CHALLENGE)
        released: list[str] = []

        with self.assertRaises(PrimeLauncherBarrierError):
            barrier.release(_lease(), lambda: released.append("released"))
        self.assertEqual(released, [])

        admission = barrier.admit(_lease(), _attestation())
        self.assertEqual(admission.status, "admitted")
        self.assertEqual(tuple(admission.__dataclass_fields__), ("status",))
        with self.assertRaises(FrozenInstanceError):
            admission.status = "released"  # type: ignore[misc]

        barrier.release(_lease(), lambda: released.append("released"))
        self.assertEqual(released, ["released"])
        with self.assertRaises(PrimeLauncherBarrierError):
            barrier.release(_lease(), lambda: released.append("again"))
        self.assertEqual(released, ["released"])

    def test_rejects_substitution_and_attestation_mismatch(self) -> None:
        cases = (
            ("lease worker", _lease(worker_id="worker-2"), _attestation()),
            ("lease run", _lease(run_id="run-2"), _attestation()),
            ("lease challenge", _lease(challenge_digest="sha256:" + "c" * 64), _attestation()),
            ("attestation worker", _lease(), _attestation(worker_id="worker-2")),
            ("attestation run", _lease(), _attestation(run_id="run-2")),
            ("attestation challenge", _lease(), _attestation(challenge_digest="sha256:" + "c" * 64)),
        )
        for name, lease, attestation in cases:
            with self.subTest(name=name), self.assertRaises(PrimeLauncherBarrierError):
                PrimeLauncherBarrier(run_id="run-1", challenge_digest=_CHALLENGE).admit(lease, attestation)

    def test_rejects_release_with_a_substituted_lease(self) -> None:
        barrier = PrimeLauncherBarrier(run_id="run-1", challenge_digest=_CHALLENGE)
        barrier.admit(_lease(), _attestation())
        released: list[str] = []
        for lease in (
            _lease(worker_id="worker-2"),
            _lease(run_id="run-2"),
            _lease(challenge_digest="sha256:" + "c" * 64),
        ):
            with self.subTest(lease=lease), self.assertRaises(PrimeLauncherBarrierError):
                barrier.release(lease, lambda: released.append("released"))
        self.assertEqual(released, [])

    def test_redacts_private_state_and_rejects_unverified_controls(self) -> None:
        barrier = PrimeLauncherBarrier(run_id="run-1", challenge_digest=_CHALLENGE)
        attestation = _attestation()
        object.__setattr__(attestation, "network_isolated", False)
        with self.assertRaises(PrimeLauncherBarrierError):
            barrier.admit(_lease(), attestation)

        rendered = repr(barrier)
        for secret in ("run-1", _CHALLENGE, "socket", "token", "prompt", "credential"):
            self.assertNotIn(secret, rendered)
        self.assertNotIn("__dict__", repr(vars(barrier)))
