from __future__ import annotations

import hashlib
import json
import urllib.error
import unittest
from unittest.mock import patch

from asterion.capabilities.dci.implementation.evaluation.evaluation import _valid_verdict
from asterion.capabilities.dci.implementation.evaluation.judge import (
    ASTERION_SAFE_JUDGE_CONTRACT,
    PAPER_JUDGE_CONTRACT,
    UPSTREAM_JUDGE_CONTRACT,
    DciJudgeError,
    JudgeConfig,
    JudgeVerdict,
    build_paper_judge_request,
    build_safe_judge_request,
    build_upstream_judge_request,
    build_judge_request_for_contract,
    parse_judge_response_for_contract,
    judge_public_identity,
    judge_request_fingerprint,
    judge_answer_sync,
)


_PAPER_PROMPT = """Judge Prompt
Judge whether the following {Response} to the {Question} is correct or not based on the precise and unambiguous {Correct Answer} below.

Question: __DCI_QUERY__

Response: __DCI_RESPONSE__

Your judgement must be in the format and criteria specified below:

Extracted_final_answer: The final exact answer extracted from the {Response}. Put the extracted answer as `None` if there is no exact, final answer to extract from the response.

Correct Answer: __DCI_CORRECT_ANSWER__

Reasoning: Explain why the extracted_final_answer is correct or incorrect based on {Correct Answer}, focusing only on if there are meaningful differences between {Correct Answer} and the extracted_final_answer. Do not comment on any background to the problem, do not attempt to solve the problem, do not argue for any answer different than {Correct Answer}, focus only on whether the answers match.

Correct: Answer `yes` if extracted_final_answer matches the {Correct Answer} given above, or is within a small margin of error for numerical problems. Answer `no` otherwise, i.e. if there is any inconsistency, ambiguity, non-equivalency, or if the extracted answer is incorrect.

Confidence: The extracted confidence score between 0% and 100% from {Response}. Put 100 if there is no confidence score available.
"""

_UPSTREAM_SYSTEM_PROMPT = (
    "You are grading a question-answer benchmark. "
    "Mark the prediction correct only if it identifies the same final answer as the gold answer. "
    "Ignore case, surrounding punctuation, whitespace, and extra explanation or supporting file paths. "
    "Do not give partial credit. Return exactly one compact JSON object."
)


def _upstream_user_prompt(question: str, gold: str, predicted: str) -> str:
    return (
        f"Question:\n{question}\n\n"
        f"Gold answer:\n{gold}\n\n"
        f"Predicted answer:\n{predicted or '[empty]'}\n\n"
        'Return JSON with keys "is_correct" (boolean), "normalized_prediction" (string), and "reason" (string).'
    )


class DciJudgeContractTests(unittest.TestCase):
    def test_normalized_verdict_is_frozen_and_contract_bound(self) -> None:
        verdict = JudgeVerdict(
            is_correct=True,
            extracted_final_answer="42",
            reason="matching numeric answer",
            confidence=0.9,
            contract_id="dci.paper-answer-judge/gpt-4.1/v1",
            request_fingerprint="a" * 64,
        )

        self.assertTrue(verdict.is_correct)
        self.assertEqual(verdict.extracted_final_answer, "42")
        self.assertEqual(verdict.confidence, 0.9)
        with self.assertRaises(AttributeError):
            verdict.reason = "mutated"  # type: ignore[misc]

    def test_paper_builder_is_the_exact_appendix_c3_prompt(self) -> None:
        request = build_paper_judge_request(
            question="__DCI_QUERY__",
            gold_answer="__DCI_CORRECT_ANSWER__",
            predicted_answer="__DCI_RESPONSE__",
        )

        self.assertEqual(request, {"prompt": _PAPER_PROMPT})
        self.assertEqual(
            hashlib.sha256(request["prompt"].encode("utf-8")).hexdigest(),
            "47e7ae410ed9f14dc06b8e0f3f18388152b320574f83e3a5a5b7e874ab70c921",
        )
        self.assertIn("small margin of error", request["prompt"])
        self.assertNotIn("epsilon", request["prompt"].lower())

    def test_upstream_builder_is_the_exact_pinned_responses_shape(self) -> None:
        config = JudgeConfig(
            base_url="https://api.openai.com/v1", api="responses", model="gpt-5.4-nano"
        )
        request = build_upstream_judge_request(
            config,
            question="__DCI_QUESTION__",
            gold_answer="__DCI_GOLD_ANSWER__",
            predicted_answer="__DCI_PREDICTED_ANSWER__",
        )

        self.assertEqual(
            request,
            {
                "model": "gpt-5.4-nano",
                "reasoning": {"effort": "low"},
                "text": {"verbosity": "low"},
                "max_output_tokens": 180,
                "input": [
                    {"role": "system", "content": _UPSTREAM_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _upstream_user_prompt(
                            "__DCI_QUESTION__",
                            "__DCI_GOLD_ANSWER__",
                            "__DCI_PREDICTED_ANSWER__",
                        ),
                    },
                ],
            },
        )
        self.assertEqual(
            # Mirrors pinned upstream `json.dumps(payload).encode("utf-8")`,
            # including its default-space serialization.
            hashlib.sha256(json.dumps(request).encode("utf-8")).hexdigest(),
            "94bba921de993375dcb0231308a81075ccac4f53515551e92a59ab3295b75d44",
        )

    def test_evidence_and_reuse_are_bound_to_the_declared_contract(self) -> None:
        config = JudgeConfig(base_url="https://api.openai.com/v1", api="responses")
        safe = judge_public_identity(config, contract_id=ASTERION_SAFE_JUDGE_CONTRACT)
        upstream = judge_public_identity(config, contract_id=UPSTREAM_JUDGE_CONTRACT)
        self.assertEqual(safe["judge_contract"], ASTERION_SAFE_JUDGE_CONTRACT)
        self.assertEqual(upstream["judge_contract"], UPSTREAM_JUDGE_CONTRACT)
        self.assertNotEqual(safe["request_shape_sha256"], upstream["request_shape_sha256"])
        safe_fingerprint = judge_request_fingerprint(
            config=config,
            contract_id=ASTERION_SAFE_JUDGE_CONTRACT,
            question="private question",
            gold_answer="private gold",
            predicted_answer="private prediction",
        )
        upstream_fingerprint = judge_request_fingerprint(
            config=config,
            contract_id=UPSTREAM_JUDGE_CONTRACT,
            question="private question",
            gold_answer="private gold",
            predicted_answer="private prediction",
        )
        self.assertNotEqual(safe_fingerprint, upstream_fingerprint)
        self.assertNotIn("private question", repr(safe))
        verdict = {
            **config.public_dict(),
            "judge_contract": ASTERION_SAFE_JUDGE_CONTRACT,
            "judged_at": "2026-07-25T00:00:00+00:00",
            "attempts": 1,
            "judge_request_fingerprint": safe_fingerprint,
            "is_correct": True,
            "normalized_prediction": "answer",
            "reason": "same",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "cost_estimate_usd": {
                "input_cost": 0.0,
                "cached_input_cost": 0.0,
                "output_cost": 0.0,
                "total_cost": 0.0,
            },
            "evaluation_commit_id": "c" * 64,
        }
        self.assertTrue(
            _valid_verdict(
                verdict,
                safe_fingerprint,
                config,
                judge_contract=ASTERION_SAFE_JUDGE_CONTRACT,
            )
        )
        legacy = dict(verdict)
        legacy.pop("judge_contract")
        self.assertFalse(
            _valid_verdict(
                legacy,
                safe_fingerprint,
                config,
                judge_contract=ASTERION_SAFE_JUDGE_CONTRACT,
            )
        )

    def test_source_transport_boundaries_fail_closed_without_retries(self) -> None:
        config = JudgeConfig(
            base_url="https://api.openai.com/v1", api="responses", model="gpt-5.4-nano"
        )
        with patch(
            "asterion.capabilities.dci.implementation.evaluation.judge._open_judge_request",
            side_effect=urllib.error.URLError("private failure"),
        ) as open_request:
            with self.assertRaisesRegex(DciJudgeError, "transport failed"):
                judge_answer_sync(
                    config=config,
                    question="question",
                    gold_answer="gold",
                    predicted_answer="prediction",
                    contract_id=UPSTREAM_JUDGE_CONTRACT,
                )
        self.assertEqual(open_request.call_count, 1)
        with self.assertRaisesRegex(DciJudgeError, "transport is unreported"):
            judge_answer_sync(
                config=config,
                question="question",
                gold_answer="gold",
                predicted_answer="prediction",
                contract_id=PAPER_JUDGE_CONTRACT,
            )

    def test_contract_dispatcher_never_selects_semantics_from_model(self) -> None:
        config = JudgeConfig(model="gpt-4.1")
        safe = build_judge_request_for_contract(
            ASTERION_SAFE_JUDGE_CONTRACT,
            config,
            question="question",
            gold_answer="gold",
            predicted_answer="prediction",
        )
        upstream = build_judge_request_for_contract(
            UPSTREAM_JUDGE_CONTRACT,
            config,
            question="question",
            gold_answer="gold",
            predicted_answer="prediction",
        )
        paper = build_judge_request_for_contract(
            PAPER_JUDGE_CONTRACT,
            config,
            question="question",
            gold_answer="gold",
            predicted_answer="prediction",
        )

        self.assertEqual(safe, build_safe_judge_request(config, question="question", gold_answer="gold", predicted_answer="prediction"))
        self.assertEqual(upstream["reasoning"], {"effort": "low"})
        self.assertEqual(paper["prompt"].splitlines()[0], "Judge Prompt")

    def test_parsers_reject_cross_contract_shapes_and_keep_raw_payload_private(self) -> None:
        fingerprint = "b" * 64
        paper = parse_judge_response_for_contract(
            PAPER_JUDGE_CONTRACT,
            "Extracted_final_answer: 42\nReasoning: exact numeric match\nCorrect: yes\nConfidence: 95%",
            request_fingerprint=fingerprint,
        )
        self.assertEqual(paper.confidence, 95.0)
        self.assertEqual(paper.extracted_final_answer, "42")
        self.assertEqual(paper.contract_id, PAPER_JUDGE_CONTRACT)
        self.assertEqual(set(paper.__slots__), {
            "is_correct", "extracted_final_answer", "reason", "confidence", "contract_id", "request_fingerprint"
        })

        upstream = parse_judge_response_for_contract(
            UPSTREAM_JUDGE_CONTRACT,
            {"output_text": json.dumps({"is_correct": True, "normalized_prediction": "42", "reason": "same"})},
            request_fingerprint=fingerprint,
        )
        self.assertIsNone(upstream.confidence)
        self.assertEqual(upstream.extracted_final_answer, "42")
        with self.assertRaises(DciJudgeError):
            parse_judge_response_for_contract(
                PAPER_JUDGE_CONTRACT,
                {"output_text": "{}"},
                request_fingerprint=fingerprint,
            )
        with self.assertRaises(DciJudgeError):
            parse_judge_response_for_contract(
                UPSTREAM_JUDGE_CONTRACT,
                "Extracted_final_answer: 42\nReasoning: same\nCorrect: yes\nConfidence: 95",
                request_fingerprint=fingerprint,
            )


if __name__ == "__main__":
    unittest.main()
