"""Provider-free protocol tests for the sealed P2 launcher release."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import unittest

from asterion.applications.prime_agent.operator.programmatic_long_context_release import (
    PROGRAMMATIC_LONG_CONTEXT_MAX_FRAME_BYTES,
    ProgrammaticLongContextRelease,
    ProgrammaticLongContextReleaseError,
    canonical_programmatic_long_context_frame,
)
from asterion.applications.prime_agent.operator.programmatic_long_context_workload import (
    PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_RECORD_COUNT,
    PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_SHA256,
    PROGRAMMATIC_LONG_CONTEXT_P2_ORACLE_SHA256,
    PROGRAMMATIC_LONG_CONTEXT_P2_ROLE_ID,
    PROGRAMMATIC_LONG_CONTEXT_P2_SCENARIO_ID,
    PROGRAMMATIC_LONG_CONTEXT_P2_SELECTED_RECORD_COUNT,
    PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
)


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "src/asterion/applications/prime_agent/operator/programmatic_long_context_image"
_DIGEST = "sha256:" + "a" * 64
_AGGREGATE = "sha256:" + "b" * 64


def _frame(sequence: int, kind: str, payload: dict[str, object]) -> bytes:
    return canonical_programmatic_long_context_frame(
        worker_id="worker-p2",
        run_id="run-p2",
        challenge_digest=_DIGEST,
        workload_digest=PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
        sequence=sequence,
        kind=kind,
        payload=payload,
    )


def _valid_frames() -> tuple[bytes, ...]:
    return (
        _frame(0, "self-check", {"credentials_absent": True, "effective_capabilities": 0, "effective_user_id": 65534, "no_new_privileges": 1, "nonloopback_network_absent": True, "root_read_only": True, "seccomp_mode": 2, "workspace_only_writable": True}),
        _frame(1, "release", {"role_id": "prime.programmatic-long-context", "scenario_id": "prime.programmatic-long-context/v1"}),
        _frame(2, "model-response", {"program_sha256": _DIGEST, "response_sha256": _DIGEST}),
        _frame(3, "ipython", {"active_tool_names": ["ipython"], "ipython_cell_executed": True, "tool_call_count": 1}),
        _frame(4, "oracle", {"aggregate_sha256": _AGGREGATE, "oracle_passed": True}),
        _frame(5, "session-disposed", {"session_disposed": True}),
        _frame(6, "completed", {"active_tool_names": ["ipython"], "aggregate_sha256": _AGGREGATE, "ipython_cell_executed": True, "oracle_passed": True, "program_sha256": _DIGEST, "response_sha256": _DIGEST, "session_disposed": True, "tool_call_count": 1}),
    )


class TestProgrammaticLongContextLauncherProtocol(unittest.TestCase):
    def test_accepts_one_sealed_sequence_and_returns_safe_completion(self) -> None:
        release = ProgrammaticLongContextRelease("worker-p2", "run-p2", _DIGEST)
        result: dict[str, object] = {}
        for frame in _valid_frames():
            result = release.consume(frame)
        self.assertEqual(result["terminal"], "completed")
        self.assertEqual(result["active_tool_names"], ["ipython"])
        self.assertEqual(result["workload_digest"], PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST)
        self.assertEqual(result["role_id"], PROGRAMMATIC_LONG_CONTEXT_P2_ROLE_ID)
        self.assertEqual(result["scenario_id"], PROGRAMMATIC_LONG_CONTEXT_P2_SCENARIO_ID)
        self.assertEqual(result["corpus_sha256"], PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_SHA256)
        self.assertEqual(result["corpus_record_count"], PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_RECORD_COUNT)
        self.assertEqual(result["selected_record_count"], PROGRAMMATIC_LONG_CONTEXT_P2_SELECTED_RECORD_COUNT)
        self.assertEqual(result["oracle_sha256"], PROGRAMMATIC_LONG_CONTEXT_P2_ORACLE_SHA256)
        self.assertEqual(result["format"], "asterion.prime-programmatic-long-context-result/v1")
        self.assertNotIn("prompt", result)
        self.assertNotIn("program", result)
        self.assertNotIn("path", result)

    def test_rejects_identity_order_caps_deadline_and_second_terminal(self) -> None:
        cases = {
            "identity": _frame(0, "self-check", {"credentials_absent": True}),
            "ordering": _valid_frames()[1],
            "response-program": _frame(2, "model-response", {"program_sha256": _AGGREGATE, "response_sha256": _DIGEST}),
            "oversized": b"x" * (PROGRAMMATIC_LONG_CONTEXT_MAX_FRAME_BYTES + 1),
        }
        for name, frame in cases.items():
            with self.subTest(name=name), self.assertRaises(ProgrammaticLongContextReleaseError):
                ProgrammaticLongContextRelease("worker-p2", "run-p2", _DIGEST).consume(frame)
        clock = iter((0.0, 2.0))
        with self.assertRaises(ProgrammaticLongContextReleaseError):
            ProgrammaticLongContextRelease("worker-p2", "run-p2", _DIGEST, clock=lambda: next(clock)).consume(_valid_frames()[0])
        release = ProgrammaticLongContextRelease("worker-p2", "run-p2", _DIGEST)
        for frame in _valid_frames():
            release.consume(frame)
        with self.assertRaises(ProgrammaticLongContextReleaseError):
            release.consume(_valid_frames()[-1])

    def test_frame_bytes_are_canonical_and_no_p1_workload_is_admitted(self) -> None:
        frame = _valid_frames()[0]
        self.assertEqual(frame, json.dumps(json.loads(frame), sort_keys=True, separators=(",", ":")).encode())
        self.assertIn(PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST.encode(), frame)
        self.assertEqual(_DIGEST, "sha256:" + "a" * 64)

    def test_image_is_fixed_and_static_source_has_no_generic_execution_surface(self) -> None:
        launcher = (IMAGE / "launcher.mjs").read_text(encoding="utf-8")
        dockerfile = (IMAGE / "Dockerfile").read_text(encoding="utf-8")
        for required in ("programmatic-long-context", "self-check", "model-response", "session-disposed", "IPython"):
            with self.subTest(required=required):
                self.assertIn(required, launcher)
        for forbidden in ("child_process", "spawn(", "exec(", "process.env", "argv", "prompt", "source", "subprocess"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, launcher.lower())
        self.assertIn("launcher.mjs", dockerfile)
        self.assertIn("fixture", dockerfile)
        self.assertIn("corpus", dockerfile)
        self.assertIn("oracle", dockerfile)
        self.assertEqual(sha256((IMAGE / "fixture-lock.json").read_bytes()).hexdigest(), (IMAGE / "fixture-lock.sha256").read_text(encoding="ascii").strip())

    def test_image_launcher_emits_the_one_fixed_canonical_sequence(self) -> None:
        launched = subprocess.run(
            ["node", str(IMAGE / "launcher.mjs")],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(launched.stderr, "")
        frames = tuple(launched.stdout.encode().splitlines())
        self.assertEqual(len(frames), 7)
        release = ProgrammaticLongContextRelease(
            "prime-p2-image-worker", "prime-p2-image-run", "sha256:" + "c" * 64
        )
        terminal: dict[str, object] = {}
        for frame in frames:
            terminal = release.consume(frame)
        self.assertEqual(terminal["terminal"], "completed")
        self.assertEqual(terminal["tool_call_count"], 1)
