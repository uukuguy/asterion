from __future__ import annotations

import json
import unittest

from asterion.pathlight.interop import (
    ExportEnvelope,
    ExportReceipt,
    ExternalObservation,
    ProposalCandidate,
    validate_export_envelope,
    validate_export_receipt,
    validate_external_observation,
    validate_proposal_candidate,
)
from asterion.pathlight.protocol import PathlightError


class _HostileMapping(dict[str, object]):
    method_called = False

    def items(self):  # type: ignore[override]
        type(self).method_called = True
        raise RuntimeError("SENTINEL_HOSTILE_MAPPING")


class PathlightInteropContractTests(unittest.TestCase):
    def test_export_envelope_is_content_addressed_and_payload_is_immutable(self) -> None:
        payload = {
            "evaluation_sha256": "b" * 64,
            "metric_contract_sha256": "c" * 64,
            "status": "observed",
            "value_microunits": 750_000,
        }
        envelope = ExportEnvelope(
            connector="opik",
            mapping_version="1.0.0",
            event_kind="evaluation.upsert",
            local_object_sha256="a" * 64,
            payload=payload,
        )
        payload["value_microunits"] = 0

        self.assertEqual(envelope.idempotency_key, envelope.envelope_sha256)
        self.assertEqual(envelope.payload["value_microunits"], 750_000)
        self.assertEqual(
            validate_export_envelope(envelope.to_mapping()), envelope
        )
        self.assertNotIn("SENTINEL", json.dumps(envelope.to_mapping()))

    def test_export_envelope_rejects_private_unknown_or_ambiguous_payloads(self) -> None:
        valid = {
            "connector": "opik",
            "mapping_version": "1.0.0",
            "event_kind": "evaluation.upsert",
            "local_object_sha256": "a" * 64,
        }
        for payload in (
            {"prompt": "SENTINEL_PRIVATE"},
            {"evaluation_sha256": "b" * 64, "provider": "private"},
            {"evaluation_sha256": "b" * 64, "value_microunits": True},
            {"evaluation_sha256": "b" * 64, "status": "unknown"},
            _HostileMapping(evaluation_sha256="b" * 64),
        ):
            with self.subTest(payload=type(payload).__name__), self.assertRaises(
                PathlightError
            ):
                ExportEnvelope(**valid, payload=payload)  # type: ignore[arg-type]
        self.assertFalse(_HostileMapping.method_called)

    def test_export_envelope_validator_rejects_digest_or_field_drift(self) -> None:
        envelope = ExportEnvelope(
            "opik",
            "1.0.0",
            "trace.upsert",
            "a" * 64,
            {"trace_sha256": "a" * 64, "status": "completed"},
        )
        for name, value in (
            ("envelope_sha256", "f" * 64),
            ("idempotency_key", "f" * 64),
            ("extra", 1),
        ):
            mapping = envelope.to_mapping()
            mapping[name] = value
            with self.subTest(name=name), self.assertRaises(PathlightError):
                validate_export_envelope(mapping)

    def test_receipt_state_has_exact_failure_semantics(self) -> None:
        delivered = ExportReceipt(
            envelope_sha256="a" * 64,
            connector="opik",
            status="delivered",
            attempt=1,
            external_object_sha256="b" * 64,
            failure_category=None,
        )
        retry = ExportReceipt(
            envelope_sha256="a" * 64,
            connector="opik",
            status="retryable-failure",
            attempt=2,
            external_object_sha256=None,
            failure_category="rate-limit",
        )
        self.assertEqual(validate_export_receipt(delivered.to_mapping()), delivered)
        self.assertEqual(validate_export_receipt(retry.to_mapping()), retry)
        for status, external, category in (
            ("delivered", None, None),
            ("delivered", "b" * 64, "network"),
            ("retryable-failure", "b" * 64, "network"),
            ("terminal-failure", None, None),
        ):
            with self.subTest(status=status), self.assertRaises(PathlightError):
                ExportReceipt(
                    "a" * 64,
                    "opik",
                    status,  # type: ignore[arg-type]
                    1,
                    external,
                    category,  # type: ignore[arg-type]
                )

    def test_external_observations_and_candidates_never_authorize_execution(self) -> None:
        observation = ExternalObservation(
            connector="opik",
            connector_identity_sha256="a" * 64,
            mapping_version="1.0.0",
            local_subject_sha256="b" * 64,
            external_event_sha256="c" * 64,
            observation_kind="optimization-suggestion",
            payload={"change_sha256": "d" * 64, "status": "proposed"},
        )
        candidate = ProposalCandidate(
            external_observation_sha256=observation.observation_sha256,
            change_sha256="d" * 64,
            scope_sha256="e" * 64,
            success_criteria_sha256="f" * 64,
            stop_criteria_sha256="1" * 64,
            budget_sha256="2" * 64,
        )
        self.assertEqual(
            validate_external_observation(observation.to_mapping()), observation
        )
        self.assertEqual(
            validate_proposal_candidate(candidate.to_mapping()), candidate
        )
        self.assertFalse(candidate.execution_authorized)
        mapping = candidate.to_mapping()
        mapping["execution_authorized"] = True
        with self.assertRaises(PathlightError):
            validate_proposal_candidate(mapping)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
