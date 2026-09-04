"""Provider-free tests for the P1 host-owned completion supervisor."""

from __future__ import annotations

from hashlib import sha256
import unittest
from unittest.mock import patch

import asterion.applications.prime_agent.operator.ipython_host_supervisor as subject
from asterion.applications.prime_agent.operator.ipython_host_supervisor import (
    IpythonHostCompletion,
    IpythonHostExpectedIdentity,
    IpythonHostSupervisor,
    IpythonHostSupervisorError,
    inspect_answer_source,
)


_INITIAL = b"def answer() -> int:\n    return 0\n"
_FINAL = b"def answer() -> int:\n    return 42\n"
_CELL = b"def answer() -> int:\n    return 42\n\n"


def _identity(**changes: object) -> IpythonHostExpectedIdentity:
    values: dict[str, object] = {
        "assembly_id": "prime-p1",
        "package_id": "prime-agent",
        "implementation_id": "prime-ipython",
        "image_digest": "sha256:" + "a" * 64,
        "workload_id": "prime-p1-answer-42",
        "oracle_id": "prime-answer-42-ast-v1",
    }
    values.update(changes)
    return IpythonHostExpectedIdentity(**values)  # type: ignore[arg-type]


def _complete(supervisor: IpythonHostSupervisor) -> IpythonHostCompletion:
    initial = supervisor._attest_snapshot(_INITIAL, is_regular_file=True)
    cell = supervisor._attest_brokered_cell(
        identity=supervisor._expected,
        cell=_CELL,
        bounded_model_digest="sha256:" + "b" * 64,
        request_count=1,
        input_bytes=1,
        output_bytes=1,
    )
    post = supervisor._attest_snapshot(_FINAL, is_regular_file=True)
    supervisor.record_initial_snapshot(initial)
    supervisor.record_brokered_cell(cell)
    supervisor.record_post_snapshot(post)
    supervisor.record_broker_revoked(cell)
    supervisor.record_cleanup(cleanup_verified=True, absence_verified=True)
    return supervisor.complete(supervisor._attest_oracle(_FINAL))


class _HostileEquality:
    def __eq__(self, other: object) -> bool:
        raise RuntimeError("untrusted equality")

    def __repr__(self) -> str:
        raise RuntimeError("untrusted repr")


class TestIpythonHostSupervisor(unittest.TestCase):
    def test_ordered_host_supervisor_mints_a_body_free_pass(self) -> None:
        completion = _complete(IpythonHostSupervisor(_identity()))
        self.assertEqual(completion.status, "PASS")
        self.assertRegex(completion.evidence_digest, r"^sha256:[0-9a-f]{64}$")
        with self.assertRaises(TypeError):
            IpythonHostCompletion("PASS", completion.evidence_digest)  # type: ignore[call-arg]

    def test_rejects_initially_passing_source_and_out_of_order_stages(self) -> None:
        supervisor = IpythonHostSupervisor(_identity())
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor.record_initial_snapshot(
                supervisor._attest_snapshot(_FINAL, is_regular_file=True)
            )
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor.record_cleanup(cleanup_verified=True, absence_verified=True)

    def test_binds_expected_identity_and_rejects_cancellation(self) -> None:
        supervisor = IpythonHostSupervisor(_identity())
        supervisor.record_initial_snapshot(
            supervisor._attest_snapshot(_INITIAL, is_regular_file=True)
        )
        for identity, cancelled in (
            (_identity(workload_id="other-workload"), False),
            (_identity(), True),
        ):
            with self.assertRaises(IpythonHostSupervisorError):
                supervisor.record_brokered_cell(
                    supervisor._attest_brokered_cell(
                        identity=identity,
                        cell=_CELL,
                        bounded_model_digest="sha256:" + "b" * 64,
                        request_count=1,
                        input_bytes=1,
                        output_bytes=1,
                        cancelled=cancelled,
                    )
                )

    def test_cell_digest_is_distinct_from_final_source_digest(self) -> None:
        completion = _complete(IpythonHostSupervisor(_identity()))
        self.assertNotEqual(sha256(_CELL).hexdigest(), sha256(_FINAL).hexdigest())
        self.assertEqual(completion.status, "PASS")

    def test_rejects_false_regular_file_post_attestation(self) -> None:
        supervisor = IpythonHostSupervisor(_identity())
        supervisor.record_initial_snapshot(
            supervisor._attest_snapshot(_INITIAL, is_regular_file=True)
        )
        cell = supervisor._attest_brokered_cell(
            identity=_identity(),
            cell=_CELL,
            bounded_model_digest="sha256:" + "b" * 64,
            request_count=1,
            input_bytes=1,
            output_bytes=1,
        )
        supervisor.record_brokered_cell(cell)
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor.record_post_snapshot(
                supervisor._attest_snapshot(_FINAL, is_regular_file=False)
            )

    def test_oracle_strictly_decodes_utf8_and_checks_size_before_hashing(self) -> None:
        self.assertFalse(
            inspect_answer_source(
                b"# coding: latin-1\n# \xe9\ndef answer() -> int:\n    return 42\n"
            )
        )
        with patch.object(subject, "_sha256", side_effect=AssertionError("hashed")):
            self.assertFalse(inspect_answer_source(b"x" * (16 * 1024 + 1)))

    def test_evidence_digest_covers_all_public_evidence_facts(self) -> None:
        baseline = _complete(IpythonHostSupervisor(_identity())).evidence_digest
        changed = _complete(
            IpythonHostSupervisor(_identity(oracle_id="prime-answer-42-ast-v2"))
        ).evidence_digest
        self.assertNotEqual(baseline, changed)

    def test_public_api_does_not_offer_generic_receipts_snapshots_or_reducer(
        self,
    ) -> None:
        for name in (
            "mint_ipython_host_completion",
            "IpythonHostCompletionInputs",
            "IpythonHostModelReceipt",
            "IpythonHostWorkspaceSnapshot",
        ):
            self.assertFalse(hasattr(subject, name))

    def test_malformed_and_hostile_inputs_become_body_free_errors(self) -> None:
        with self.assertRaises(IpythonHostSupervisorError) as raised:
            IpythonHostSupervisor(_HostileEquality())
        self.assertEqual(str(raised.exception), "ipython host completion is invalid")
        with self.assertRaises(IpythonHostSupervisorError) as raised:
            IpythonHostSupervisor(_identity()).record_initial_snapshot(
                _HostileEquality()
            )
        self.assertEqual(str(raised.exception), "ipython host completion is invalid")
