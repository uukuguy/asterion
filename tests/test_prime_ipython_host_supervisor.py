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
        "assembly_id": "prime.capability-program@1.0.0",
        "package_id": "prime-agent@1.0.0",
        "implementation_id": "prime.ipython-coding@1.0.0",
        "image_digest": "sha256:" + "a" * 64,
        "workload_digest": "sha256:f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022",
        "oracle_digest": "sha256:85ee4060b19a5ee375e4c6258f45b1df722f53efd8310f56603b31639fa3c4eb",
        "starter_digest": "sha256:4f8e0bca0f70582bad96caa292823ac29577633bebd9f76257617dc92ab6832f",
        "source_digest": "sha256:486a083f857430c7d6a452ebf881d1b8c46063c128b51162ffdebef0c1f71c7a",
    }
    values.update(changes)
    return IpythonHostExpectedIdentity(**values)  # type: ignore[arg-type]


def _complete(supervisor: IpythonHostSupervisor) -> IpythonHostCompletion:
    initial = supervisor._attest_initial_snapshot(_INITIAL, is_regular_file=True)
    supervisor.record_initial_snapshot(initial)
    cell = supervisor._attest_brokered_cell(
        identity=supervisor._expected,
        cell=_CELL,
        bounded_model_digest="sha256:" + "b" * 64,
        request_count=1,
        input_bytes=1,
        output_bytes=1,
    )
    supervisor.record_brokered_cell(cell)
    post = supervisor._attest_post_snapshot(_FINAL, is_regular_file=True)
    supervisor.record_post_snapshot(post)
    supervisor.record_broker_revoked(supervisor._attest_broker_revocation())
    supervisor.record_cleanup(supervisor._attest_cleanup_and_absence())
    return supervisor.complete(supervisor._attest_final_oracle(_FINAL))


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
                supervisor._attest_initial_snapshot(_FINAL, is_regular_file=True)
            )
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor.record_cleanup(cleanup_verified=True, absence_verified=True)

    def test_initial_snapshot_requires_the_locked_starter_digest(self) -> None:
        supervisor = IpythonHostSupervisor(_identity())
        wrong_starter = b"def answer() -> int:\n    return 1\n"
        self.assertNotEqual(
            "sha256:" + sha256(wrong_starter).hexdigest(),
            _identity().starter_digest,
        )
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor.record_initial_snapshot(
                supervisor._attest_initial_snapshot(
                    wrong_starter, is_regular_file=True
                )
            )

    def test_binds_expected_identity_and_rejects_cancellation(self) -> None:
        supervisor = IpythonHostSupervisor(_identity())
        supervisor.record_initial_snapshot(
            supervisor._attest_initial_snapshot(_INITIAL, is_regular_file=True)
        )
        for identity, cancelled in (
            (_identity(workload_digest="sha256:" + "c" * 64), False),
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

    def test_cancelled_valid_cell_latches_before_rejection(self) -> None:
        supervisor = IpythonHostSupervisor(_identity())
        supervisor.record_initial_snapshot(
            supervisor._attest_initial_snapshot(_INITIAL, is_regular_file=True)
        )
        cancelled = supervisor._attest_brokered_cell(
            identity=_identity(),
            cell=_CELL,
            bounded_model_digest="sha256:" + "b" * 64,
            request_count=1,
            input_bytes=1,
            output_bytes=1,
            cancelled=True,
        )
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor.record_brokered_cell(cancelled)
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor.record_brokered_cell(
                supervisor._attest_brokered_cell(
                    identity=_identity(),
                    cell=_CELL,
                    bounded_model_digest="sha256:" + "b" * 64,
                    request_count=1,
                    input_bytes=1,
                    output_bytes=1,
                )
            )

    def test_cell_digest_is_distinct_from_final_source_digest(self) -> None:
        completion = _complete(IpythonHostSupervisor(_identity()))
        self.assertNotEqual(sha256(_CELL).hexdigest(), sha256(_FINAL).hexdigest())
        self.assertEqual(completion.status, "PASS")

    def test_rejects_false_regular_file_post_attestation(self) -> None:
        supervisor = IpythonHostSupervisor(_identity())
        supervisor.record_initial_snapshot(
            supervisor._attest_initial_snapshot(_INITIAL, is_regular_file=True)
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
                supervisor._attest_post_snapshot(_FINAL, is_regular_file=False)
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
            IpythonHostSupervisor(_identity(image_digest="sha256:" + "d" * 64))
        ).evidence_digest
        self.assertNotEqual(baseline, changed)

    def test_attestations_cannot_be_created_before_their_stage(self) -> None:
        supervisor = IpythonHostSupervisor(_identity())
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor._attest_brokered_cell(
                identity=_identity(), cell=_CELL,
                bounded_model_digest="sha256:" + "b" * 64,
                request_count=1, input_bytes=1, output_bytes=1,
            )
        initial = supervisor._attest_initial_snapshot(_INITIAL, is_regular_file=True)
        supervisor.record_initial_snapshot(initial)
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor._attest_final_oracle(_FINAL)

    def test_final_oracle_requires_revocation_cleanup_and_absence(self) -> None:
        supervisor = IpythonHostSupervisor(_identity())
        initial = supervisor._attest_initial_snapshot(_INITIAL, is_regular_file=True)
        supervisor.record_initial_snapshot(initial)
        cell = supervisor._attest_brokered_cell(
            identity=_identity(), cell=_CELL,
            bounded_model_digest="sha256:" + "b" * 64,
            request_count=1, input_bytes=1, output_bytes=1,
        )
        supervisor.record_brokered_cell(cell)
        post = supervisor._attest_post_snapshot(_FINAL, is_regular_file=True)
        supervisor.record_post_snapshot(post)
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor._attest_final_oracle(_FINAL)

    def test_late_cancellation_latches_and_blocks_completion(self) -> None:
        supervisor = IpythonHostSupervisor(_identity())
        initial = supervisor._attest_initial_snapshot(_INITIAL, is_regular_file=True)
        supervisor.record_initial_snapshot(initial)
        cell = supervisor._attest_brokered_cell(
            identity=_identity(), cell=_CELL,
            bounded_model_digest="sha256:" + "b" * 64,
            request_count=1, input_bytes=1, output_bytes=1,
        )
        supervisor.record_brokered_cell(cell)
        supervisor.cancel()
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor._attest_post_snapshot(_FINAL, is_regular_file=True)

    def test_cancellation_after_final_attestation_blocks_complete(self) -> None:
        supervisor = IpythonHostSupervisor(_identity())
        initial = supervisor._attest_initial_snapshot(_INITIAL, is_regular_file=True)
        supervisor.record_initial_snapshot(initial)
        cell = supervisor._attest_brokered_cell(
            identity=_identity(), cell=_CELL,
            bounded_model_digest="sha256:" + "b" * 64,
            request_count=1, input_bytes=1, output_bytes=1,
        )
        supervisor.record_brokered_cell(cell)
        supervisor.record_post_snapshot(
            supervisor._attest_post_snapshot(_FINAL, is_regular_file=True)
        )
        supervisor.record_broker_revoked(supervisor._attest_broker_revocation())
        supervisor.record_cleanup(supervisor._attest_cleanup_and_absence())
        oracle = supervisor._attest_final_oracle(_FINAL)
        supervisor.cancel()
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor.complete(oracle)

    def test_rejects_caller_selected_identity_aliases_and_versions(self) -> None:
        for changes in (
            {"assembly_id": "prime.capability-program@2.0.0"},
            {"package_id": "prime-agent@9.9.9"},
            {"implementation_id": "prime.ipython-coding@1.2.3"},
            {"workload_digest": "sha256:" + "e" * 64},
            {"oracle_digest": "sha256:" + "e" * 64},
            {"starter_digest": "sha256:" + "e" * 64},
            {"source_digest": "sha256:" + "e" * 64},
        ):
            with self.subTest(changes=changes), self.assertRaises(IpythonHostSupervisorError):
                IpythonHostSupervisor(_identity(**changes))

    def test_completion_is_single_mint_terminal_and_immutable(self) -> None:
        supervisor = IpythonHostSupervisor(_identity())
        completion = _complete(supervisor)
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor.complete(object())
        with self.assertRaises((AttributeError, TypeError)):
            completion._digest = "sha256:" + "0" * 64  # type: ignore[attr-defined]
        for name in (
            "_digest",
            "_IpythonHostCompletion__digest",
            "evidence_digest",
            "new_attribute",
        ):
            with self.subTest(name=name), self.assertRaises(TypeError):
                delattr(completion, name)
        self.assertRegex(completion.evidence_digest, r"^sha256:[0-9a-f]{64}$")

    def test_revocation_and_cleanup_reject_cells_and_raw_booleans(self) -> None:
        supervisor = IpythonHostSupervisor(_identity())
        initial = supervisor._attest_initial_snapshot(_INITIAL, is_regular_file=True)
        supervisor.record_initial_snapshot(initial)
        cell = supervisor._attest_brokered_cell(
            identity=_identity(), cell=_CELL,
            bounded_model_digest="sha256:" + "b" * 64,
            request_count=1, input_bytes=1, output_bytes=1,
        )
        supervisor.record_brokered_cell(cell)
        post = supervisor._attest_post_snapshot(_FINAL, is_regular_file=True)
        supervisor.record_post_snapshot(post)
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor.record_broker_revoked(cell)
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor.record_broker_revoked(True)
        with self.assertRaises(IpythonHostSupervisorError):
            supervisor.record_cleanup(cleanup_verified=True, absence_verified=True)

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

    def test_hostile_identity_fields_become_body_free_errors(self) -> None:
        with self.assertRaises(IpythonHostSupervisorError) as raised:
            IpythonHostSupervisor(_identity(assembly_id=_HostileEquality()))
        self.assertEqual(str(raised.exception), "ipython host completion is invalid")
        with self.assertRaises(IpythonHostSupervisorError) as raised:
            IpythonHostSupervisor(_identity()).record_initial_snapshot(
                _HostileEquality()
            )
        self.assertEqual(str(raised.exception), "ipython host completion is invalid")
