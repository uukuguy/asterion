"""Tests for immutable, evidence-closed Pathlight diagnoses."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.pathlight import PathlightError
from asterion.pathlight._private_file import PrivateFileError
from asterion.pathlight.diagnosis import (
    DIAGNOSIS_BUNDLE_FILENAME,
    DiagnosisBundle,
    Finding,
    Proposal,
    read_diagnosis_bundle,
    validate_diagnosis_bundle,
    validate_finding,
    validate_proposal,
    write_diagnosis_bundle,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _observed() -> Finding:
    return Finding(
        "observed", _digest("subject"), (_digest("evaluation"),), (), "confirmed", _digest("observed")
    )


def _hypothesis(observed: Finding) -> Finding:
    return Finding(
        "hypothesis", _digest("subject"), (observed.finding_sha256,), (), "medium", _digest("hypothesis")
    )


def _bundle() -> DiagnosisBundle:
    observed = _observed()
    hypothesis = _hypothesis(observed)
    proposal = Proposal(
        hypothesis.finding_sha256,
        _digest("change"), _digest("scope"), _digest("success"), _digest("stop"), _digest("budget"),
    )
    return DiagnosisBundle.build(
        experiment_bundle_sha256s=(_digest("experiment"),),
        evaluation_sha256s=(_digest("evaluation"),),
        findings=(hypothesis, observed),
        proposals=(proposal,),
    )


class TestPathlightDiagnosis(unittest.TestCase):
    def test_proposal_is_digest_only_and_never_authority(self) -> None:
        finding = Finding(
            category="hypothesis",
            subject_sha256=_digest("bright-cohort"),
            evidence_sha256s=(_digest("observation-a"),),
            counterevidence_sha256s=(),
            confidence="medium",
            finding_code_sha256=_digest("retrieval-scale-noise"),
        )
        proposal = Proposal(
            finding_sha256=finding.finding_sha256,
            change_sha256=_digest("query-decomposition-only"),
            scope_sha256=_digest("fixed-cases"),
            success_criteria_sha256=_digest("ndcg-plus-cost-cap"),
            stop_criteria_sha256=_digest("two-infra-failures"),
            budget_sha256=_digest("max-80-agent-ops-usd-8"),
        )
        self.assertTrue(proposal.requires_operator_authorization)
        self.assertFalse(proposal.execution_authorized)
        self.assertNotIn("query-decomposition-only", json.dumps(proposal.to_mapping()))

    def test_diagnosis_refuses_hypothesis_without_observed_support(self) -> None:
        unsupported_hypothesis = Finding(
            "hypothesis", _digest("subject"), (_digest("unobserved"),), (), "low", _digest("code")
        )
        with self.assertRaises(PathlightError):
            DiagnosisBundle.build(
                experiment_bundle_sha256s=(_digest("experiment-bundle"),),
                evaluation_sha256s=(_digest("evaluation"),),
                findings=(unsupported_hypothesis,),
                proposals=(),
            )

    def test_diagnosis_canonicalizes_closed_registries_and_references(self) -> None:
        bundle = _bundle()
        self.assertEqual(bundle.experiment_bundle_sha256s, (_digest("experiment"),))
        self.assertEqual(bundle.evaluation_sha256s, (_digest("evaluation"),))
        self.assertEqual(
            tuple(finding.finding_sha256 for finding in bundle.findings),
            tuple(sorted(finding.finding_sha256 for finding in bundle.findings)),
        )
        self.assertIn(bundle.proposals[0].finding_sha256, {finding.finding_sha256 for finding in bundle.findings if finding.category == "hypothesis"})
        self.assertRegex(bundle.bundle_sha256, r"^[0-9a-f]{64}$")

    def test_diagnosis_refuses_unregistered_or_wrong_kind_evidence(self) -> None:
        observed = _observed()
        unsupported_observed = Finding(
            "observed", _digest("subject"), (_digest("not-registered"),), (), "high", _digest("code")
        )
        missing = Finding(
            "missing-evidence", _digest("subject"), (_digest("not-registered"),), (), "unknown", _digest("missing")
        )
        proposal = Proposal(
            observed.finding_sha256,
            _digest("change"),
            _digest("scope"),
            _digest("success"),
            _digest("stop"),
            _digest("budget"),
        )
        for findings, proposals in (
            ((unsupported_observed,), ()),
            ((missing,), ()),
            ((observed,), (proposal,)),
        ):
            with self.subTest(findings=findings, proposals=proposals), self.assertRaises(PathlightError):
                DiagnosisBundle.build(
                    experiment_bundle_sha256s=(_digest("experiment"),),
                    evaluation_sha256s=(_digest("evaluation"),),
                    findings=findings,
                    proposals=proposals,
                )

    def test_validators_normalize_hostile_payloads_and_tampered_authority(self) -> None:
        class HostileMapping(dict[str, object]):
            def __getitem__(self, key: str) -> object:
                raise RuntimeError("SENTINEL_PRIVATE_FINDING")

        for validator, payload in (
            (validate_finding, HostileMapping()),
            (validate_proposal, HostileMapping()),
            (validate_diagnosis_bundle, HostileMapping()),
        ):
            with self.subTest(validator=validator), self.assertRaisesRegex(PathlightError, r"^Pathlight .+ is invalid$") as raised:
                validator(payload)
            self.assertNotIn("SENTINEL_PRIVATE_FINDING", str(raised.exception))

        proposal = _bundle().proposals[0]
        object.__setattr__(proposal, "execution_authorized", True)
        with self.assertRaises(PathlightError):
            validate_proposal(proposal.to_mapping())

    def test_descriptor_safe_round_trip_and_rejects_unsafe_sources(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / DIAGNOSIS_BUNDLE_FILENAME
            write_diagnosis_bundle(bundle, path)
            self.assertEqual(stat_mode(path), 0o600)
            self.assertEqual(read_diagnosis_bundle(path), bundle)
            with self.assertRaises(PathlightError):
                write_diagnosis_bundle(bundle, path)
            path.chmod(0o644)
            with self.assertRaises(PathlightError):
                read_diagnosis_bundle(path)

    def test_read_rejects_symlink_and_hostile_json_without_echoing_payload(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "target"
            target.mkdir()
            write_diagnosis_bundle(bundle, target / DIAGNOSIS_BUNDLE_FILENAME)
            link = root / DIAGNOSIS_BUNDLE_FILENAME
            link.symlink_to(target / DIAGNOSIS_BUNDLE_FILENAME)
            with self.assertRaisesRegex(PathlightError, "^Pathlight diagnosis source is invalid$") as raised:
                read_diagnosis_bundle(link)
            self.assertNotIn(str(target), str(raised.exception))

    def test_wrapper_normalizes_shared_parent_fifo_and_race_failures(self) -> None:
        path = Path("/private/pathlight-diagnosis.json")
        for boundary in ("parent-symlink", "fifo", "identity-race"):
            with self.subTest(boundary=boundary), patch(
                "asterion.pathlight.diagnosis.read_private_file",
                side_effect=PrivateFileError(f"SENTINEL_PRIVATE_{boundary}"),
            ), self.assertRaisesRegex(
                PathlightError, "^Pathlight diagnosis source is invalid$"
            ) as raised:
                read_diagnosis_bundle(path)
            self.assertNotIn("SENTINEL_PRIVATE", str(raised.exception))


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
