"""Tests for the host-only bounded model-session contract."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.services.bounded_model_session import (
    BoundedModelSessionError,
    BoundedModelSessionLease,
    BoundedModelSessionRequest,
    BoundedModelSessionService,
)


def _request(**changes: object) -> BoundedModelSessionRequest:
    values: dict[str, object] = {
        "run_id": "run-1",
        "max_requests": 2,
        "max_input_bytes": 32768,
        "max_output_bytes": 32768,
        "deadline_seconds": 300,
    }
    values.update(changes)
    return BoundedModelSessionRequest(**values)  # type: ignore[arg-type]


class TestBoundedModelSessionValues(unittest.TestCase):
    def test_request_accepts_only_bounded_public_metadata(self) -> None:
        request = _request()

        self.assertEqual(request.run_id, "run-1")
        self.assertEqual(
            tuple(request.__dataclass_fields__),
            (
                "run_id",
                "max_requests",
                "max_input_bytes",
                "max_output_bytes",
                "deadline_seconds",
            ),
        )

    def test_request_rejects_boolean_and_non_positive_budgets(self) -> None:
        for field in (
            "max_requests",
            "max_input_bytes",
            "max_output_bytes",
            "deadline_seconds",
        ):
            for value in (True, 0, -1, 1.5):
                with self.subTest(field=field, value=value), self.assertRaises(
                    BoundedModelSessionError
                ):
                    _request(**{field: value})

    def test_request_and_lease_reject_noncanonical_identities(self) -> None:
        for constructor, field in (
            (_request, "run_id"),
            (BoundedModelSessionLease, "run_id"),
            (BoundedModelSessionLease, "session_id"),
        ):
            for value in ("", " run-1", "run-1 ", "RUN-1", "run_1", "run/1"):
                with self.subTest(constructor=constructor, field=field, value=value), self.assertRaises(
                    BoundedModelSessionError
                ):
                    if constructor is BoundedModelSessionLease:
                        values = {"session_id": "session-1", "run_id": "run-1"}
                        values[field] = value
                        constructor(**values)
                    else:
                        constructor(**{field: value})

    def test_values_are_immutable(self) -> None:
        for value in (_request(), BoundedModelSessionLease("session-1", "run-1")):
            with self.subTest(value=type(value).__name__), self.assertRaises(
                FrozenInstanceError
            ):
                value.run_id = "run-2"  # type: ignore[misc]

    def test_errors_and_lease_representation_redact_untrusted_text(self) -> None:
        sentinel = "sentinel-secret/raw-bearer"

        with self.assertRaises(BoundedModelSessionError) as raised:
            _request(run_id=sentinel)

        self.assertNotIn(sentinel, repr(raised.exception))
        self.assertNotIn("secret", repr(BoundedModelSessionLease("session-1", "run-1")))

    def test_public_values_have_no_model_or_network_control_surfaces(self) -> None:
        forbidden = {
            "api_key",
            "bearer",
            "credential",
            "endpoint",
            "model",
            "network",
            "prompt",
            "provider",
            "secret",
            "token",
        }
        for value in (_request(), BoundedModelSessionLease("session-1", "run-1")):
            with self.subTest(value=type(value).__name__):
                self.assertTrue(forbidden.isdisjoint(value.__dataclass_fields__))

    def test_unknown_fields_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            BoundedModelSessionRequest(
                run_id="run-1",
                max_requests=2,
                max_input_bytes=32768,
                max_output_bytes=32768,
                deadline_seconds=300,
                model="unsafe",  # type: ignore[call-arg]
            )

    def test_service_exposes_only_host_lifecycle_operations(self) -> None:
        self.assertEqual(
            {name for name in BoundedModelSessionService.__dict__ if not name.startswith("_")},
            {"open", "revoke"},
        )
