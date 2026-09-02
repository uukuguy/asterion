"""Provider-free admission tests for the Prime worker evidence gate."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any, cast
import unittest

from asterion.applications.prime_agent.restricted_worker import (
    PrimeRestrictedWorkerProfile,
)
from asterion.applications.prime_agent.worker_gate import (
    PrimeWorkerBoundaryError,
    verify_prime_worker_boundary,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerCleanupReceipt,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
)


_IMAGE_DIGEST = "sha256:" + "a" * 64
_CHALLENGE_DIGEST = "sha256:" + "b" * 64


def _profile(**changes: object) -> PrimeRestrictedWorkerProfile:
    values: dict[str, object] = {
        "image_digest": _IMAGE_DIGEST,
        "network_mode": "none",
        "workspace_mode": "disposable",
        "credential_mode": "absent",
        "max_runtime_seconds": 300,
        "max_output_bytes": 65536,
    }
    values.update(changes)
    return PrimeRestrictedWorkerProfile(**values)  # type: ignore[arg-type]


def _request(**changes: object) -> RestrictedWorkerRequest:
    values: dict[str, object] = {
        "role_id": "prime.ipython-coding",
        "image_digest": _IMAGE_DIGEST,
        "run_id": "run-1",
        "challenge_digest": _CHALLENGE_DIGEST,
        "max_runtime_seconds": 300,
        "max_output_bytes": 65536,
    }
    values.update(changes)
    return RestrictedWorkerRequest(**values)  # type: ignore[arg-type]


def _lease(**changes: object) -> RestrictedWorkerLease:
    values: dict[str, object] = {
        "worker_id": "worker-1",
        "run_id": "run-1",
        "challenge_digest": _CHALLENGE_DIGEST,
    }
    values.update(changes)
    return RestrictedWorkerLease(**values)  # type: ignore[arg-type]


def _attestation(**changes: object) -> RestrictedWorkerAttestation:
    values: dict[str, object] = {
        "worker_id": "worker-1",
        "run_id": "run-1",
        "challenge_digest": _CHALLENGE_DIGEST,
        "image_digest": _IMAGE_DIGEST,
        "network_isolated": True,
        "root_read_only": True,
        "workspace_disposable": True,
        "credentials_absent": True,
        "kernel_credential_absent": True,
        "source_read_only": True,
        "resource_limited": True,
    }
    values.update(changes)
    return RestrictedWorkerAttestation(**values)  # type: ignore[arg-type]


def _cleanup(**changes: object) -> RestrictedWorkerCleanupReceipt:
    values: dict[str, object] = {
        "worker_id": "worker-1",
        "run_id": "run-1",
        "challenge_digest": _CHALLENGE_DIGEST,
        "destroyed": True,
    }
    values.update(changes)
    return RestrictedWorkerCleanupReceipt(**values)  # type: ignore[arg-type]


class TestPrimeWorkerBoundary(unittest.TestCase):
    def test_admits_only_a_fully_bound_restricted_worker_lifecycle(self) -> None:
        receipt = verify_prime_worker_boundary(
            _profile(), _request(), _lease(), _attestation(), _cleanup()
        )

        self.assertEqual(receipt.status, "PASS")
        self.assertEqual(
            tuple(receipt.__dataclass_fields__),
            ("worker_id", "run_id", "challenge_digest", "image_digest", "status"),
        )
        with self.assertRaises(FrozenInstanceError):
            receipt.status = "FAIL"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            cast(Any, type(receipt))(
                "worker-1", "run-1", _CHALLENGE_DIGEST, _IMAGE_DIGEST, "FAIL"
            )

    def test_rejects_every_attestation_control_that_is_not_true(self) -> None:
        for field in (
            "network_isolated",
            "root_read_only",
            "workspace_disposable",
            "credentials_absent",
            "kernel_credential_absent",
            "source_read_only",
            "resource_limited",
        ):
            attestation = _attestation()
            object.__setattr__(attestation, field, False)
            with (
                self.subTest(field=field),
                self.assertRaises(PrimeWorkerBoundaryError),
            ):
                verify_prime_worker_boundary(
                    _profile(),
                    _request(),
                    _lease(),
                    attestation,
                    _cleanup(),
                )

    def test_rejects_exact_identity_mismatches(self) -> None:
        cases = (
            ("worker", _lease(worker_id="worker-2"), _attestation(), _cleanup()),
            ("run", _lease(run_id="run-2"), _attestation(), _cleanup()),
            (
                "challenge",
                _lease(challenge_digest="sha256:" + "c" * 64),
                _attestation(),
                _cleanup(),
            ),
            (
                "image",
                _lease(),
                _attestation(image_digest="sha256:" + "c" * 64),
                _cleanup(),
            ),
        )

        for name, lease, attestation, cleanup in cases:
            with (
                self.subTest(name=name),
                self.assertRaises(PrimeWorkerBoundaryError),
            ):
                verify_prime_worker_boundary(
                    _profile(), _request(), lease, attestation, cleanup
                )

    def test_rejects_missing_or_not_destroyed_cleanup(self) -> None:
        for cleanup in (None, _cleanup(destroyed=False)):
            with (
                self.subTest(cleanup=cleanup),
                self.assertRaises(PrimeWorkerBoundaryError),
            ):
                verify_prime_worker_boundary(
                    _profile(),
                    _request(),
                    _lease(),
                    _attestation(),
                    cast(RestrictedWorkerCleanupReceipt, cleanup),
                )

    def test_rejects_profile_request_image_mismatch(self) -> None:
        with self.assertRaises(PrimeWorkerBoundaryError):
            verify_prime_worker_boundary(
                _profile(image_digest="sha256:" + "c" * 64),
                _request(),
                _lease(),
                _attestation(),
                _cleanup(),
            )

    def test_rejects_a_non_prime_role_even_when_all_receipts_match(self) -> None:
        with self.assertRaises(PrimeWorkerBoundaryError):
            verify_prime_worker_boundary(
                _profile(),
                _request(role_id="other.role"),
                _lease(),
                _attestation(),
                _cleanup(),
            )
