"""Provider-free tests for the P1 host-owned completion reducer."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from hashlib import sha256
import inspect
import unittest

from asterion.applications.prime_agent.operator.ipython_host_supervisor import (
    IpythonHostCompletionInputs,
    IpythonHostModelReceipt,
    IpythonHostSupervisorError,
    IpythonHostWorkspaceSnapshot,
    inspect_answer_source,
    mint_ipython_host_completion,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


_ANSWER_SOURCE = b"def answer() -> int:\n    return 42\n"
_ANSWER_DIGEST = "sha256:" + sha256(_ANSWER_SOURCE).hexdigest()


def _receipt(**changes: object) -> IpythonHostModelReceipt:
    values: dict[str, object] = {
        "session_id": "session-1",
        "run_id": "run-1",
        "worker_id": "worker-1",
        "challenge_digest": _digest("a"),
        "bounded_model_digest": _digest("b"),
        "sent_cell_digest": _ANSWER_DIGEST,
        "request_count": 1,
        "input_bytes": 16,
        "output_bytes": 16,
        "status": "revoked",
    }
    values.update(changes)
    return IpythonHostModelReceipt(**values)  # type: ignore[arg-type]


def _inputs(**changes: object) -> IpythonHostCompletionInputs:
    oracle = inspect_answer_source(_ANSWER_SOURCE)
    values: dict[str, object] = {
        "model_receipt": _receipt(sent_cell_digest=oracle.source_digest),
        "pre_snapshot": IpythonHostWorkspaceSnapshot(_digest("d"), True),
        "post_snapshot": IpythonHostWorkspaceSnapshot(oracle.source_digest, True),
        "oracle": oracle,
        "tool_names": ("ipython",),
        "cleanup_verified": True,
        "absence_verified": True,
    }
    values.update(changes)
    return IpythonHostCompletionInputs(**values)  # type: ignore[arg-type]


class TestIpythonHostSupervisor(unittest.TestCase):
    def test_ast_oracle_accepts_only_the_fixed_data_only_answer_contract(self) -> None:
        accepted = inspect_answer_source(b"def answer() -> int:\n    return 42\n")
        self.assertTrue(accepted.passed)

        for source in (
            b"def answer():\n    return 41\n",
            b"import os\ndef answer():\n    return 42\n",
            b"def answer():\n    return int('42')\n",
            b"def answer(value):\n    return 42\n",
            b"def answer():\n    return 42\nanswer()\n",
            b"def answer():\n    return True\n",
            b"def answer():\n    return 42\x00",
            "def answer(): return 42",
        ):
            with self.subTest(source=source):
                self.assertFalse(inspect_answer_source(source).passed)

    def test_mints_pass_only_from_complete_host_attested_facts(self) -> None:
        completion = mint_ipython_host_completion(_inputs())

        self.assertEqual(completion.status, "PASS")
        self.assertRegex(completion.evidence_digest, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(tuple(field.name for field in fields(completion)), ("status", "evidence_digest"))
        with self.assertRaises(FrozenInstanceError):
            completion.status = "FAIL"  # type: ignore[misc]

    def test_rejects_every_missing_or_forged_trusted_fact(self) -> None:
        failed_oracle = inspect_answer_source(b"def answer():\n    return 0\n")
        cases = (
            ("unrevoked-model", {"model_receipt": _receipt(status="active")} ),
            ("no-model-call", {"model_receipt": _receipt(request_count=0)}),
            ("non-integer-model-call-count", {"model_receipt": _receipt(request_count=True)}),
            ("no-model-output", {"model_receipt": _receipt(output_bytes=0)}),
            ("boolean-model-output", {"model_receipt": _receipt(output_bytes=True)}),
            ("other-tool", {"tool_names": ("shell",)}),
            ("unlocked-pre", {"pre_snapshot": IpythonHostWorkspaceSnapshot(_digest("d"), False)}),
            ("unchanged", {"pre_snapshot": IpythonHostWorkspaceSnapshot(inspect_answer_source(b"def answer() -> int:\n    return 42\n").source_digest, True)}),
            ("oracle-failed", {"oracle": failed_oracle}),
            ("cell-oracle-mismatch", {"model_receipt": _receipt(sent_cell_digest=_digest("e"))}),
            ("snapshot-oracle-mismatch", {"post_snapshot": IpythonHostWorkspaceSnapshot(_digest("e"), True)}),
            ("cleanup", {"cleanup_verified": False}),
            ("absence", {"absence_verified": False}),
        )
        for name, changes in cases:
            with self.subTest(name=name), self.assertRaises(IpythonHostSupervisorError):
                mint_ipython_host_completion(_inputs(**changes))

    def test_public_surface_cannot_admit_or_expose_worker_output(self) -> None:
        self.assertEqual(
            tuple(field.name for field in fields(IpythonHostCompletionInputs)),
            ("model_receipt", "pre_snapshot", "post_snapshot", "oracle", "tool_names", "cleanup_verified", "absence_verified"),
        )
        self.assertNotIn("stdout", str(inspect.signature(mint_ipython_host_completion)))
        self.assertNotIn("exit", str(inspect.signature(mint_ipython_host_completion)))
        secret_source = b"# SECRET-SOURCE SECRET-CELL SECRET-PROMPT\ndef answer():\n    return 42\n"
        observation = inspect_answer_source(secret_source)
        self.assertNotIn("SECRET", repr(observation))
        self.assertNotIn("SECRET", repr(_inputs(oracle=observation)))
        with self.assertRaises(IpythonHostSupervisorError) as raised:
            mint_ipython_host_completion(_inputs(oracle=observation))
        self.assertNotIn("SECRET", str(raised.exception))
