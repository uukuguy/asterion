"""Provider-free receipt tests for Prime long-session continuity."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel
from asterion.applications.prime_agent.long_session_continuity_receipt import (
    LongSessionContinuityObservation,
    LongSessionContinuityReceiptError,
    long_session_continuity_observation_from_public_report,
    verify_long_session_continuity_receipt,
)


def _observation(**changes: object) -> LongSessionContinuityObservation:
    values: dict[str, object] = {
        "detached_reattached": True,
        "name_persisted": True,
        "source_resume_roundtrip": True,
        "resume_delete_roundtrip": True,
        "identity_separated": True,
        "public_projection_redacted": True,
    }
    values.update(changes)
    return LongSessionContinuityObservation(**values)  # type: ignore[arg-type]


def _public_report(**changes: object) -> dict[str, object]:
    report: dict[str, object] = {
        "format": "asterion.prime-session-context-observation/v1",
        "app_version": "0.7.1",
        "daemon_protocol": 7,
        "daemon_schema_revision": 14,
        "fake_daemon": False,
        "model_credential_reads": 0,
        "provider_operations": 0,
        "runtime_build_id": "prime-0.7.1",
        "scenario_checks": {
            "prime-parity.session.fork-clone": [
                "prime-fork-clone-roundtrip-passed",
                "source-resume-roundtrip-passed",
            ],
            "prime-parity.session.persistence-naming": [
                "prime-detach-attach-passed",
                "prime-name-roundtrip-passed",
            ],
            "prime-parity.session.resume-delete": [
                "prime-exact-delete-passed",
                "prime-resume-roundtrip-passed",
            ],
            "prime-parity.session.tree-navigation": [
                "prime-tree-navigation-roundtrip-passed",
                "tree-private-content-redaction-passed",
            ],
            "prime-parity.session.delivery": [],
            "prime-parity.session.rich-attachments": [],
            "prime-parity.session.usage-status": [],
        },
    }
    report.update(changes)
    return report


class TestLongSessionContinuityReceipt(unittest.TestCase):
    def test_emits_only_matching_provider_free_receipt(self) -> None:
        receipt = verify_long_session_continuity_receipt(_observation())

        self.assertEqual(receipt.scenario_id, "prime.long-session-continuity/v1")
        self.assertIs(receipt.level, PrimeEvidenceLevel.PROVIDER_FREE)
        self.assertEqual(receipt.status, "PASS")

    def test_rejects_missing_identity_persistence_resume_or_redaction_facts(self) -> None:
        cases: tuple[dict[str, object], ...] = (
            {"detached_reattached": False},
            {"name_persisted": False},
            {"source_resume_roundtrip": False},
            {"resume_delete_roundtrip": False},
            {"identity_separated": False},
            {"public_projection_redacted": False},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(
                LongSessionContinuityReceiptError
            ):
                verify_long_session_continuity_receipt(_observation(**changes))

    def test_accepts_only_exact_provider_free_session_context_projection(self) -> None:
        observation = long_session_continuity_observation_from_public_report(
            _public_report()
        )

        self.assertTrue(observation.identity_separated)
        for changes in (
            {"model_credential_reads": 1},
            {"provider_operations": 1},
            {"fake_daemon": True},
            {"scenario_checks": {}},
            {"unexpected": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(
                LongSessionContinuityReceiptError
            ):
                long_session_continuity_observation_from_public_report(
                    _public_report(**changes)
                )

    def test_rejects_upgrade_and_redacts_private_observation(self) -> None:
        observation = _observation()

        with self.assertRaises(LongSessionContinuityReceiptError):
            verify_long_session_continuity_receipt(
                observation, PrimeEvidenceLevel.BOUNDED_SANDBOXED
            )
        self.assertNotIn("PRIVATE-CONTINUATION", repr(observation))
        with self.assertRaises(FrozenInstanceError):
            observation.name_persisted = False  # type: ignore[misc]
