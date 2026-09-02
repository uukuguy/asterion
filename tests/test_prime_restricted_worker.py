"""Tests for the Prime restricted-worker sandbox contract."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.applications.prime_agent.restricted_worker import (
    PrimeRestrictedWorkerError,
    PrimeRestrictedWorkerProfile,
    validate_prime_restricted_worker,
)


def _profile(**changes: object) -> PrimeRestrictedWorkerProfile:
    values: dict[str, object] = {
        "image_digest": "sha256:" + "a" * 64,
        "network_mode": "none",
        "workspace_mode": "disposable",
        "credential_mode": "absent",
        "max_runtime_seconds": 300,
        "max_output_bytes": 65536,
    }
    values.update(changes)
    return PrimeRestrictedWorkerProfile(**values)  # type: ignore[arg-type]


class TestPrimeRestrictedWorkerProfile(unittest.TestCase):
    def test_profile_requires_closed_sandbox_properties(self) -> None:
        profile = _profile()

        self.assertEqual(validate_prime_restricted_worker(profile), profile)

    def test_profile_is_frozen(self) -> None:
        profile = _profile()

        with self.assertRaises(FrozenInstanceError):
            profile.network_mode = "host"  # type: ignore[misc]

    def test_rejects_non_profile_values(self) -> None:
        with self.assertRaises(PrimeRestrictedWorkerError):
            validate_prime_restricted_worker({})  # type: ignore[arg-type]

    def test_rejects_non_digest_pinned_image(self) -> None:
        for image_digest in (
            "ubuntu:latest",
            "sha256:" + "a" * 63,
            "sha256:" + "g" * 64,
            "SHA256:" + "a" * 64,
        ):
            with self.subTest(image_digest=image_digest), self.assertRaises(
                PrimeRestrictedWorkerError
            ):
                validate_prime_restricted_worker(_profile(image_digest=image_digest))

    def test_rejects_open_sandbox_properties(self) -> None:
        for field, value in (
            ("network_mode", "bridge"),
            ("workspace_mode", "mounted"),
            ("credential_mode", "injected"),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(
                PrimeRestrictedWorkerError
            ):
                validate_prime_restricted_worker(_profile(**{field: value}))

    def test_rejects_non_positive_or_boolean_limits(self) -> None:
        for field, value in (
            ("max_runtime_seconds", 0),
            ("max_runtime_seconds", -1),
            ("max_runtime_seconds", True),
            ("max_output_bytes", 0),
            ("max_output_bytes", -1),
            ("max_output_bytes", True),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(
                PrimeRestrictedWorkerError
            ):
                validate_prime_restricted_worker(_profile(**{field: value}))

    def test_rejects_unexpected_constructor_fields(self) -> None:
        with self.assertRaises(TypeError):
            PrimeRestrictedWorkerProfile(
                image_digest="sha256:" + "a" * 64,
                network_mode="none",
                workspace_mode="disposable",
                credential_mode="absent",
                max_runtime_seconds=300,
                max_output_bytes=65536,
                extra="unsafe",
            )  # type: ignore[call-arg]

    def test_rejects_profile_with_an_unexpected_field(self) -> None:
        profile = _profile()
        object.__setattr__(profile, "unsafe", "value")

        with self.assertRaises(PrimeRestrictedWorkerError):
            validate_prime_restricted_worker(profile)
