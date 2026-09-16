"""Cross-language parity for the Asterion-owned summarization material.

The native side owns the prompt text and the assembly rule; the extension
composes the same request from the material it receives on the witness arm
frame. This module holds the two implementations to the recorded bytes: the
Python construction must reproduce the fixture, and the extension's TypeScript
test asserts the same fixture from the same material.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from asterion.agents.prime.context import PROJECTION, encode_prime_context_v1
from asterion.agents.prime.summarization import (
    MATERIAL_KEYS,
    MATERIAL_VERSION,
    build_instruction,
    build_summarization_material,
    compose_request_text,
    main_completion_tokens,
    turn_prefix_completion_tokens,
)


_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "asterion_prime_p1"
    / "v1"
    / "summarization-parity.json"
)


class TestPrimeSummarization(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    def test_material_matches_the_recorded_fixture(self) -> None:
        material = build_summarization_material()
        self.assertEqual(sorted(material), sorted(MATERIAL_KEYS))
        self.assertEqual(material, self.fixture["material"])
        self.assertEqual(material["version"], MATERIAL_VERSION)

    def test_recorded_requests_are_reproduced_byte_for_byte(self) -> None:
        material = build_summarization_material()
        for case in self.fixture["cases"]:
            with self.subTest(case=case["name"]):
                instruction = build_instruction(
                    custom_instructions=case["custom_instructions"],
                    previous_summary=case["previous_summary"],
                )
                self.assertEqual(instruction, case["instruction"])
                text = compose_request_text(
                    conversation=case["conversation"],
                    instruction=instruction,
                    previous_summary=case["previous_summary"],
                )
                encoded = encode_prime_context_v1(
                    {
                        "format": PROJECTION,
                        "system_prompt": material["system_prompt"],
                        "messages": [
                            {"role": "user", "content": [{"type": "text", "text": text}]}
                        ],
                    }
                ).decode()
                self.assertEqual(encoded, case["request_canonical_json"])
                self.assertEqual(
                    hashlib.sha256(encoded.encode()).hexdigest(), case["sha256"]
                )

    def test_completion_arithmetic_matches_the_recorded_bound(self) -> None:
        completion = self.fixture["completion"]
        reserve = completion["reserve_tokens"]
        self.assertEqual(main_completion_tokens(reserve), completion["main"])
        self.assertEqual(
            turn_prefix_completion_tokens(reserve), completion["turn_prefix"]
        )
        # The operator's reservation cap for both branches is the main bound.
        self.assertEqual(main_completion_tokens(4_096), 3_276)
        self.assertEqual(turn_prefix_completion_tokens(4_096), 2_048)

    def test_templates_never_rescan_inserted_private_text(self) -> None:
        """A conversation carrying another template's marker must stay inert."""

        conversation = "text {previous_summary} and {instructions} here"
        previous = "prior {conversation} summary"
        instruction = build_instruction(
            custom_instructions="remember {conversation}", previous_summary=previous
        )
        text = compose_request_text(
            conversation=conversation, instruction=instruction, previous_summary=previous
        )
        # Both private strings are inserted literally and the blocks stay in the
        # fixed order; nothing in them was re-substituted into a wrapper.
        self.assertTrue(
            text.startswith(
                "<conversation>\n"
                + conversation
                + "\n</conversation>\n\n<previous-summary>\n"
                + previous
                + "\n</previous-summary>\n\n"
            ),
            text[:400],
        )
        self.assertTrue(text.endswith("remember {conversation}\n</user-instructions>"))

    def test_material_rejects_a_template_carrying_a_foreign_marker(self) -> None:
        from asterion.agents.prime.context import _validate_summarization

        material = build_summarization_material()
        with self.assertRaises(ValueError):
            _validate_summarization(
                {
                    **material,
                    "initial_instruction": material["initial_instruction"]
                    + " {conversation}",
                }
            )
        with self.assertRaises(ValueError):
            _validate_summarization(
                {**material, "conversation_block": "<conversation>{conversation}{conversation}"}
            )
        with self.assertRaises(ValueError):
            _validate_summarization({**material, "version": "other"})
        with self.assertRaises(ValueError):
            _validate_summarization({**material, "system_prompt": ""})
        with self.assertRaises(ValueError):
            _validate_summarization(
                {key: value for key, value in material.items() if key != "version"}
            )


if __name__ == "__main__":
    unittest.main()
