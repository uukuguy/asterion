from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.pathlight.interop import (
    ExportEnvelope,
    ExportReceipt,
    ExternalObservation,
    ProposalCandidate,
    read_export_batch,
    read_export_receipts,
    record_export_receipt,
    validate_export_envelope,
    validate_export_receipt,
    validate_external_observation,
    validate_proposal_candidate,
    write_export_batch,
)
from asterion.pathlight.protocol import PathlightError


class _HostileMapping(dict[str, object]):
    method_called = False

    def items(self):  # type: ignore[override]
        type(self).method_called = True
        raise RuntimeError("SENTINEL_HOSTILE_MAPPING")


class PathlightInteropContractTests(unittest.TestCase):
    def _envelope(self, suffix: str) -> ExportEnvelope:
        return ExportEnvelope(
            "opik",
            "1.0.0",
            "trace.upsert",
            suffix * 64,
            {"trace_sha256": suffix * 64, "status": "completed"},
        )

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

    def test_offline_batch_is_private_sorted_deduplicated_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            root.chmod(0o700)
            first = self._envelope("a")
            second = self._envelope("b")

            batch = write_export_batch(root, (second, first, first))
            repeated = write_export_batch(root, (first, second))

            self.assertEqual(batch, repeated)
            self.assertEqual(
                tuple(item.envelope_sha256 for item in batch.envelopes),
                tuple(sorted((first.envelope_sha256, second.envelope_sha256))),
            )
            path = root / batch.filename
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(read_export_batch(path), batch)
            self.assertEqual(tuple(root.iterdir()), (path,))

    def test_offline_batch_rejects_unsafe_roots_and_symlink_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            root = parent / "queue"
            root.mkdir(mode=0o755)
            with self.assertRaises(PathlightError):
                write_export_batch(root, (self._envelope("a"),))
            root.chmod(0o700)
            batch = write_export_batch(root, (self._envelope("a"),))
            link = parent / "batch.json"
            link.symlink_to(root / batch.filename)
            with self.assertRaises(PathlightError):
                read_export_batch(link)

    def test_receipt_ledger_requires_monotonic_attempts_and_terminal_closure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            root.chmod(0o700)
            envelope = self._envelope("a")
            first = ExportReceipt(
                envelope.envelope_sha256,
                "opik",
                "retryable-failure",
                1,
                None,
                "authentication",
            )
            delivered = ExportReceipt(
                envelope.envelope_sha256,
                "opik",
                "delivered",
                2,
                "b" * 64,
                None,
            )

            self.assertEqual(record_export_receipt(root, first), first)
            with self.assertRaises(PathlightError):
                record_export_receipt(root, first)
            self.assertEqual(record_export_receipt(root, delivered), delivered)
            with self.assertRaises(PathlightError):
                record_export_receipt(
                    root,
                    ExportReceipt(
                        envelope.envelope_sha256,
                        "opik",
                        "retryable-failure",
                        3,
                        None,
                        "network",
                    ),
                )
            self.assertEqual(read_export_receipts(root), (first, delivered))
            self.assertTrue(
                all(
                    stat.S_IMODE(path.stat().st_mode) == 0o600
                    for path in root.glob("receipt-*.json")
                )
            )

    def test_queue_root_must_be_owned_by_current_operator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            root.chmod(0o700)
            with patch(
                "asterion.pathlight.interop.os.getuid", return_value=os.getuid() + 1
            ):
                with self.assertRaises(PathlightError):
                    write_export_batch(root, (self._envelope("a"),))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
