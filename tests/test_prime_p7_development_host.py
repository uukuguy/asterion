from __future__ import annotations

from hashlib import sha256
import json
import unittest


def _digest(char: str) -> str:
    return "sha256:" + char * 64


def _stage(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _stage_digest(raw: bytes) -> str:
    return "sha256:" + sha256(raw).hexdigest()


def _witness() -> dict[str, object]:
    return {
        "identity": {
            "run_id": "run",
            "session_id": "session",
            "runtime_id": "prime.agent",
            "generation": 1,
        },
        "result": {
            "lifecycle": "completed",
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            "assistant": {"completed": True, "stop_reason": "stop"},
            "observations": {
                "active_tool_names": ["ipython"],
                "compact_count": 0,
                "model_callback_count": 6,
                "rlm_child_count": 0,
                "tool_call_count": 3,
            },
        },
        "cumulative": {"model_callback_count": 6, "tool_callback_count": 3},
    }


class TestP7DevelopmentHost(unittest.TestCase):
    def test_receipt_uses_the_sealed_score_digest(self) -> None:
        from asterion.applications.prime_agent.operator.p7_development_host import _receipt

        score = _digest("b")
        receipt = _receipt(
            "run",
            "session",
            type("Worker", (), {"daemon_id": "a" * 64, "image_digest": _digest("c")})(),
            b"{}",
            b"[]",
            b"{}",
            {"transcript_sha256": _digest("d"), "score_sha256": score},
            {"replay_sha256": _digest("e"), "score_sha256": score},
            {"input_tokens": 1, "output_tokens": 2, "cost_microunits": 99},
            4,
            {"terminal": True, "terminal_reason": "engine-terminal"},
        )
        self.assertEqual(receipt.score_sha256, score)

    def test_witness_is_closed_and_binds_provider_token_usage(self) -> None:
        from asterion.applications.prime_agent.operator.p7_development_host import _witness as validate

        provider_usage = {"input_tokens": 1, "output_tokens": 2, "cost_microunits": 99}
        validate(_witness(), "run", "session", provider_usage)
        for invalid in (
            {**_witness(), "extra": True},
            {**_witness(), "result": {**_witness()["result"], "assistant": {"completed": 1, "stop_reason": "stop"}}},  # type: ignore[index]
            {**_witness(), "result": {**_witness()["result"], "usage": {"input_tokens": 2, "output_tokens": 2, "total_tokens": 4}}},  # type: ignore[index]
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate(invalid, "run", "session", provider_usage)

    def test_broker_rejects_score_mismatch(self) -> None:
        from asterion.applications.prime_agent.operator.p7_development_host import _broker

        initial = _stage({"observation": {"state": "play"}})
        actions = _stage([{"action_id": 1, "observation": {"state": "play"}}] * 4)
        status = _stage({"terminal": True, "terminal_reason": "engine-terminal"})
        seal = {"transcript_sha256": _digest("a"), "score_sha256": _digest("b"), "initial_sha256": _stage_digest(initial), "actions_sha256": _stage_digest(actions), "status_sha256": _stage_digest(status), "terminal_reason": "engine-terminal", "action_count": 4}
        _broker(
            seal,
            {"replay_sha256": _digest("a"), "score_sha256": _digest("b"), "initial_sha256": _stage_digest(initial), "actions_sha256": _stage_digest(actions), "status_sha256": _stage_digest(status), "terminal_reason": "engine-terminal", "action_count": 4},
            initial, actions, status,
        )
        replay = {"replay_sha256": _digest("a"), "score_sha256": _digest("c"), "initial_sha256": _stage_digest(initial), "actions_sha256": _stage_digest(actions), "status_sha256": _stage_digest(status), "terminal_reason": "engine-terminal", "action_count": 4}
        with self.assertRaises(ValueError):
            _broker(seal, replay, initial, actions, status)

    def test_broker_rejects_tampered_stage_bytes_and_terminal_contradiction(self) -> None:
        from asterion.applications.prime_agent.operator.p7_development_host import _broker, _status

        initial = _stage({"observation": {"state": "play"}})
        actions = _stage([{"action_id": 1, "observation": {"state": "play"}}] * 4)
        status = _stage({"terminal": False, "terminal_reason": "action-limit"})
        seal = {"transcript_sha256": _digest("a"), "score_sha256": _digest("b"), "initial_sha256": _stage_digest(initial), "actions_sha256": _stage_digest(actions), "status_sha256": _stage_digest(status), "terminal_reason": "action-limit", "action_count": 4}
        replay = {"replay_sha256": _digest("a"), "score_sha256": _digest("b"), "initial_sha256": _stage_digest(initial), "actions_sha256": _stage_digest(actions), "status_sha256": _stage_digest(status), "terminal_reason": "action-limit", "action_count": 4}
        with self.assertRaises(ValueError):
            _broker(seal, replay, _stage({"observation": {"state": "tampered"}}), actions, status)
        with self.assertRaises(ValueError):
            _status(_stage({"terminal": False, "terminal_reason": "engine-terminal"}))
