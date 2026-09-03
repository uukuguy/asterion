"""Provider-free protocol tests for the sealed P3 recursive-review launcher."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import subprocess
import unittest

from asterion.applications.prime_agent.operator.recursive_code_review_release import (
    RECURSIVE_CODE_REVIEW_MAX_FRAME_BYTES,
    RecursiveCodeReviewReleaseError,
    canonical_recursive_code_review_frame,
    parse_recursive_code_review_frames,
)
from asterion.applications.prime_agent.recursive_workflow_receipt import (
    RecursiveWorkflowReceiptError,
    verify_real_recursive_workflow_trace,
)
from asterion.applications.prime_agent.operator.recursive_code_review_workload import (
    RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS,
    RECURSIVE_CODE_REVIEW_P3_FOLLOW_UP_ROLE_ID,
    RECURSIVE_CODE_REVIEW_P3_ROLE_ID,
    RECURSIVE_CODE_REVIEW_P3_SCENARIO_ID,
    RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST,
)


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "src/asterion/applications/prime_agent/operator/recursive_code_review_image"
_DIGESTS = tuple("sha256:" + character * 64 for character in "abcdef0123456789")


def _frame(sequence: int, kind: str, payload: dict[str, object]) -> bytes:
    return canonical_recursive_code_review_frame(
        worker_id="worker-p3",
        run_id="run-p3",
        challenge_digest=_DIGESTS[0],
        workload_digest=RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST,
        sequence=sequence,
        kind=kind,
        payload=payload,
    )


def _frames() -> tuple[bytes, ...]:
    implementation, reviewer = RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS
    return (
        _frame(0, "self-check", {"credentials_absent": True, "effective_capabilities": 0, "effective_user_id": 65534, "no_new_privileges": 1, "nonloopback_network_absent": True, "root_read_only": True, "seccomp_mode": 2, "workspace_only_writable": True}),
        _frame(1, "release", {"child_role_ids": list(RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS), "role_id": RECURSIVE_CODE_REVIEW_P3_ROLE_ID, "scenario_id": RECURSIVE_CODE_REVIEW_P3_SCENARIO_ID}),
        _frame(2, "root-artifact", {"root_artifact_sha256": _DIGESTS[1], "root_work_before_children": True}),
        _frame(3, "child-admitted", {"child_role_id": implementation, "child_role_sha256": _DIGESTS[2], "child_usage_sha256": _DIGESTS[3]}),
        _frame(4, "child-result", {"child_result_sha256": _DIGESTS[4], "child_role_id": implementation, "ipython_action_count": 1}),
        _frame(5, "child-admitted", {"child_role_id": reviewer, "child_role_sha256": _DIGESTS[5], "child_usage_sha256": _DIGESTS[6]}),
        _frame(6, "child-result", {"child_result_sha256": _DIGESTS[7], "child_role_id": reviewer, "ipython_action_count": 1}),
        _frame(7, "follow-up", {"follow_up_digest": _DIGESTS[8], "target_role_id": RECURSIVE_CODE_REVIEW_P3_FOLLOW_UP_ROLE_ID}),
        _frame(8, "follow-up-result", {"child_result_sha256": _DIGESTS[9], "child_role_id": RECURSIVE_CODE_REVIEW_P3_FOLLOW_UP_ROLE_ID, "follow_up_digest": _DIGESTS[8], "ipython_action_count": 1}),
        _frame(9, "aggregation", {"aggregation_sha256": _DIGESTS[9], "model_sha256": _DIGESTS[10], "oracle_sha256": _DIGESTS[11], "usage_sha256": _DIGESTS[12]}),
        _frame(10, "child-deleted", {"child_role_id": implementation}),
        _frame(11, "child-deleted", {"child_role_id": reviewer}),
        _frame(12, "completed", {"disposed": True, "reaped": True, "revoked": True}),
    )


def _stream() -> bytes:
    return b"\n".join(_frames()) + b"\n"


class TestRecursiveCodeReviewLauncherProtocol(unittest.TestCase):
    def test_parses_only_the_full_causal_sequence(self) -> None:
        trace = parse_recursive_code_review_frames(_stream())

        self.assertEqual(trace.workload_sha256, RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST)
        self.assertEqual(trace.root_artifact_sha256, _DIGESTS[1])
        self.assertEqual(trace.root_to_child_message_count, 2)
        self.assertEqual(trace.child_to_root_result_count, 3)
        self.assertEqual(trace.follow_up_count, 1)
        self.assertEqual(trace.root_deleted_child_count, 2)
        self.assertTrue(trace.root_work_before_children)
        self.assertTrue(trace.root_continued_locally)
        self.assertEqual(trace.follow_up_result_digest, _DIGESTS[9])
        self.assertEqual(trace.follow_up_ipython_action_count, 1)

    def test_static_fixture_trace_cannot_issue_bounded_real_evidence(self) -> None:
        launched = subprocess.run(
            ["node", str(IMAGE / "launcher.mjs")],
            check=True,
            capture_output=True,
        )
        diagnostic = parse_recursive_code_review_frames(launched.stdout)

        with self.assertRaises(RecursiveWorkflowReceiptError):
            verify_real_recursive_workflow_trace(diagnostic)

    def test_rejects_wrong_order_identity_cap_deadline_and_second_terminal(self) -> None:
        cases = (
            b"\n".join(_frames()[3:]) + b"\n",
            b"\n".join(_frames()[:3] + (_frame(3, "child-admitted", {"child_role_id": "prime.ipython-coding", "child_role_sha256": _DIGESTS[2], "child_usage_sha256": _DIGESTS[3]}),)) + b"\n",
            b"x" * (RECURSIVE_CODE_REVIEW_MAX_FRAME_BYTES + 1),
            b"\n".join(_frames() + (_frames()[-1],)) + b"\n",
        )
        for data in cases:
            with self.subTest(data=data[:32]), self.assertRaises(RecursiveCodeReviewReleaseError):
                parse_recursive_code_review_frames(data)
        with self.assertRaises(RecursiveCodeReviewReleaseError):
            parse_recursive_code_review_frames(_stream(), clock=iter((0.0, 2.0)).__next__)

    def test_rejects_missing_digest_or_ipython_evidence_for_second_child_result(self) -> None:
        frames = list(_frames())
        frames[8] = _frame(8, "follow-up-result", {"child_role_id": RECURSIVE_CODE_REVIEW_P3_FOLLOW_UP_ROLE_ID, "follow_up_digest": _DIGESTS[8]})
        with self.assertRaises(RecursiveCodeReviewReleaseError):
            parse_recursive_code_review_frames(b"\n".join(frames) + b"\n")

    def test_requires_one_canonical_newline_at_eof(self) -> None:
        for data in (b"\n".join(_frames()), _stream() + b"\n", _stream() + b" "):
            with self.subTest(data=data[-4:]), self.assertRaises(RecursiveCodeReviewReleaseError):
                parse_recursive_code_review_frames(data)

    def test_errors_and_trace_redact_private_values(self) -> None:
        with self.assertRaises(RecursiveCodeReviewReleaseError) as raised:
            parse_recursive_code_review_frames(b"PRIVATE_REVIEW_TEXT")
        self.assertNotIn("PRIVATE_REVIEW_TEXT", str(raised.exception))
        trace = parse_recursive_code_review_frames(_stream())
        self.assertNotIn(_DIGESTS[1], repr(trace))

    def test_image_is_input_free_and_emits_only_canonical_frames(self) -> None:
        launcher = (IMAGE / "launcher.mjs").read_text(encoding="utf-8")
        dockerfile = (IMAGE / "Dockerfile").read_text(encoding="utf-8")
        for required in ("recursive-workflow", "IPython", "RLM", "child-admitted", "completed"):
            self.assertIn(required, launcher)
        for forbidden in ("stdin", "argv", "process.env", "prompt", "source", "child_process", "spawn(", "exec(", "config", "command"):
            self.assertNotIn(forbidden, launcher.lower())
        self.assertIn("launcher.mjs", dockerfile)
        self.assertEqual(sha256((IMAGE / "fixture-lock.json").read_bytes()).hexdigest(), (IMAGE / "fixture-lock.sha256").read_text(encoding="ascii").strip())
        launched = subprocess.run(["node", str(IMAGE / "launcher.mjs")], check=True, capture_output=True, text=True)
        self.assertEqual(launched.stderr, "")
        trace = parse_recursive_code_review_frames(launched.stdout.encode())
        self.assertEqual(trace.workload_sha256, RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST)
