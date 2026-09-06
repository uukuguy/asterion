from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest


def _digest(char: str) -> str:
    return "sha256:" + char * 64


class TestP7DevelopmentReceipt(unittest.TestCase):
    def _receipt(self, **changes: object) -> object:
        from asterion.applications.prime_agent.operator import p7_development_workload as workload
        from asterion.applications.prime_agent.operator.p7_development_receipt import P7DevelopmentReceipt

        values: dict[str, object] = {
            "workload_sha256": workload.P7_DEVELOPMENT_WORKLOAD_DIGEST,
            "schema_sha256": workload.P7_DEVELOPMENT_SCHEMA_DIGEST,
            "model_sha256": workload.P7_DEVELOPMENT_MODEL_DIGEST,
            "oracle_sha256": workload.P7_DEVELOPMENT_ORACLE_DIGEST,
            "resource_sha256": workload.P7_DEVELOPMENT_RESOURCE_DIGEST,
            "run_sha256": _digest("1"), "session_sha256": _digest("2"), "container_sha256": _digest("3"),
            "image_sha256": _digest("4"), "initial_observation_sha256": _digest("5"),
            "action_chain_sha256": _digest("6"), "terminal_sha256": _digest("7"), "score_sha256": _digest("8"),
            "replay_sha256": _digest("9"), "usage_sha256": _digest("a"), "broker_sha256": _digest("b"), "cleanup_sha256": _digest("c"),
            "tool_names": ("ipython",), "game_count": 1, "action_count": 4, "prompt_count": 3,
            "provider_callback_count": 6, "ipython_call_count": 3, "terminal_reason": "action-limit",
            "terminal": True, "cleanup_complete": True,
        }
        values.update(changes)
        return P7DevelopmentReceipt(**values)

    def test_accepts_a_closed_finite_episode_and_exposes_only_a_digest(self) -> None:
        from asterion.applications.prime_agent.operator.p7_development_receipt import p7_development_public_trace_digest, validate_p7_development_receipt

        receipt = self._receipt()
        validate_p7_development_receipt(receipt)
        self.assertRegex(p7_development_public_trace_digest(receipt), r"\Asha256:[0-9a-f]{64}\Z")
        self.assertEqual(repr(receipt), "P7DevelopmentReceipt(redacted)")

    def test_rejects_mutation_private_data_and_noncanonical_closure(self) -> None:
        from asterion.applications.prime_agent.operator.p7_development_receipt import P7DevelopmentReceiptError, validate_p7_development_receipt

        for receipt in (self._receipt(action_count=5), self._receipt(action_count=True), self._receipt(terminal_reason="won"), self._receipt(cleanup_complete=False), self._receipt(workload_sha256=_digest("0"))):
            with self.subTest(receipt=receipt), self.assertRaises(P7DevelopmentReceiptError):
                validate_p7_development_receipt(receipt)
        receipt = self._receipt()
        object.__setattr__(receipt, "secret", "P7-PRIVATE-SENTINEL")
        with self.assertRaises(P7DevelopmentReceiptError):
            validate_p7_development_receipt(receipt)
        self.assertNotIn("P7-PRIVATE-SENTINEL", repr(receipt))
        with self.assertRaises(FrozenInstanceError):
            receipt.terminal = False  # type: ignore[misc]
