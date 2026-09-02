"""Tests for the domain-neutral restricted-worker lease contract."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any, cast
import unittest

from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerCleanupReceipt,
    RestrictedWorkerError,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
    verify_restricted_worker_receipts,
)


_IMAGE_DIGEST = "sha256:" + "a" * 64
_CHALLENGE_DIGEST = "sha256:" + "b" * 64


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


class TestRestrictedWorkerValues(unittest.TestCase):
    def test_receipt_verification_accepts_one_bound_lifecycle(self) -> None:
        self.assertIsNone(
            verify_restricted_worker_receipts(
                _request(), _lease(), _attestation(), _cleanup()
            )
        )

    def test_receipt_verification_rejects_mismatched_lifecycle_identities(self) -> None:
        cases = (
            (
                "request and lease run",
                _request(),
                _lease(run_id="run-2"),
                _attestation(),
                _cleanup(),
            ),
            (
                "request and lease challenge",
                _request(),
                _lease(challenge_digest="sha256:" + "c" * 64),
                _attestation(),
                _cleanup(),
            ),
            (
                "lease and attestation worker",
                _request(),
                _lease(),
                _attestation(worker_id="worker-2"),
                _cleanup(),
            ),
            (
                "lease and attestation run",
                _request(),
                _lease(),
                _attestation(run_id="run-2"),
                _cleanup(),
            ),
            (
                "lease and attestation challenge",
                _request(),
                _lease(),
                _attestation(challenge_digest="sha256:" + "c" * 64),
                _cleanup(),
            ),
            (
                "request and attestation image",
                _request(),
                _lease(),
                _attestation(image_digest="sha256:" + "c" * 64),
                _cleanup(),
            ),
            (
                "lease and cleanup worker",
                _request(),
                _lease(),
                _attestation(),
                _cleanup(worker_id="worker-2"),
            ),
            (
                "lease and cleanup run",
                _request(),
                _lease(),
                _attestation(),
                _cleanup(run_id="run-2"),
            ),
            (
                "lease and cleanup challenge",
                _request(),
                _lease(),
                _attestation(),
                _cleanup(challenge_digest="sha256:" + "c" * 64),
            ),
        )

        for name, request, lease, attestation, cleanup in cases:
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(
                    RestrictedWorkerError, "restricted worker value is invalid"
                ),
            ):
                verify_restricted_worker_receipts(request, lease, attestation, cleanup)

    def test_receipt_verification_rejects_cleanup_not_destroyed(self) -> None:
        with self.assertRaisesRegex(
            RestrictedWorkerError, "restricted worker value is invalid"
        ):
            verify_restricted_worker_receipts(
                _request(), _lease(), _attestation(), _cleanup(destroyed=False)
            )

    def test_request_accepts_only_bounded_public_metadata(self) -> None:
        request = _request()

        self.assertEqual(request.role_id, "prime.ipython-coding")
        self.assertEqual(
            tuple(request.__dataclass_fields__),
            (
                "role_id",
                "image_digest",
                "run_id",
                "challenge_digest",
                "max_runtime_seconds",
                "max_output_bytes",
            ),
        )

    def test_values_are_immutable(self) -> None:
        values = (
            _request(),
            _lease(),
            _attestation(),
            RestrictedWorkerCleanupReceipt(
                "worker-1", "run-1", _CHALLENGE_DIGEST, True
            ),
        )

        for value in values:
            with (
                self.subTest(value=type(value).__name__),
                self.assertRaises(FrozenInstanceError),
            ):
                value.run_id = "run-2"  # type: ignore[misc]

    def test_rejects_invalid_identifiers_and_digests_without_echoing_them(self) -> None:
        invalid_values = ("", " run-1", "run-1 ", "RUN-1", "run_1", "run/1")
        for field in ("role_id", "run_id"):
            for value in invalid_values:
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaisesRegex(
                        RestrictedWorkerError, "restricted worker value is invalid"
                    ),
                ):
                    _request(**{field: value})
        for field in ("image_digest", "challenge_digest"):
            for value in ("latest", "sha256:" + "a" * 63, "sha256:" + "A" * 64):
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaisesRegex(
                        RestrictedWorkerError, "restricted worker value is invalid"
                    ),
                ):
                    _request(**{field: value})

    def test_rejects_boolean_or_non_positive_limits(self) -> None:
        for field in ("max_runtime_seconds", "max_output_bytes"):
            for value in (True, 0, -1, 1.5):
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(RestrictedWorkerError),
                ):
                    _request(**{field: value})

    def test_lease_attestation_and_cleanup_fail_closed_on_bad_identities(self) -> None:
        cases = (
            (_lease, "worker_id", "worker/1"),
            (_lease, "challenge_digest", "sha256:" + "a" * 63),
            (_attestation, "run_id", "run/1"),
            (_attestation, "image_digest", "latest"),
            (
                RestrictedWorkerCleanupReceipt,
                "worker_id",
                "worker/1",
            ),
            (
                RestrictedWorkerCleanupReceipt,
                "challenge_digest",
                "sha256:" + "a" * 63,
            ),
        )
        for constructor, field, value in cases:
            with (
                self.subTest(constructor=constructor, field=field),
                self.assertRaises(RestrictedWorkerError),
            ):
                if constructor is RestrictedWorkerCleanupReceipt:
                    values: dict[str, Any] = {
                        "worker_id": "worker-1",
                        "run_id": "run-1",
                        "challenge_digest": _CHALLENGE_DIGEST,
                        "destroyed": True,
                    }
                    values[field] = value
                    cast(Any, constructor)(**values)
                else:
                    cast(Any, constructor)(**{field: value})

    def test_attestation_requires_every_isolation_control(self) -> None:
        for field in (
            "network_isolated",
            "root_read_only",
            "workspace_disposable",
            "credentials_absent",
            "kernel_credential_absent",
            "source_read_only",
            "resource_limited",
        ):
            with self.subTest(field=field), self.assertRaises(RestrictedWorkerError):
                _attestation(**{field: False})

    def test_rejects_unknown_constructor_fields(self) -> None:
        values = {
            "role_id": "prime.ipython-coding",
            "image_digest": _IMAGE_DIGEST,
            "run_id": "run-1",
            "challenge_digest": _CHALLENGE_DIGEST,
            "max_runtime_seconds": 300,
            "max_output_bytes": 65536,
            "command": "unsafe",
        }
        with self.assertRaises(TypeError):
            RestrictedWorkerRequest(**cast(Any, values))

    def test_invalid_value_errors_redact_the_supplied_text(self) -> None:
        sentinel = "sentinel-secret/path"

        with self.assertRaises(RestrictedWorkerError) as raised:
            _request(run_id=sentinel)

        self.assertNotIn(sentinel, repr(raised.exception))

    def test_public_values_do_not_expose_forbidden_control_surfaces(self) -> None:
        forbidden = {
            "command",
            "environment",
            "env",
            "host_path",
            "mount_path",
            "image_tag",
            "model",
            "provider",
            "credential",
            "secret",
        }
        for value in (_request(), _lease(), _attestation()):
            with self.subTest(value=type(value).__name__):
                self.assertTrue(forbidden.isdisjoint(value.__dataclass_fields__))
