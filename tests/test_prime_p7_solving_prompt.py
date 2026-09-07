from __future__ import annotations

import re
import unittest


class TestPrimeP7SolvingPrompt(unittest.TestCase):
    def test_guidance_is_source_locked_and_uses_the_public_protocol(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_prompt import (
            P7_SOLVING_GUIDANCE_LOCK,
            P7_SOLVING_PROMPT,
            validate_p7_solving_prompt,
        )

        validate_p7_solving_prompt(P7_SOLVING_PROMPT)
        lowered = P7_SOLVING_PROMPT.lower()
        for required in (
            "import only p7_client",
            "p7_client.observe()",
            "p7_client.status()",
            "p7_client.act(actions)",
            '{"name": "action1", "data": {}}',
            "action1 up",
            "action2 down",
            "action3 left",
            "action4 right",
            "programmatically",
            "objects",
            "colors",
            "components",
            "differences",
            "one- or two-step exploratory batches",
            "world model",
            "complete post-batch view",
            "avoid repeating",
            'terminal == "level_solved"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, lowered)
        for forbidden in (
            r"ls20|9607627b",
            r"\(\s*\d{1,2}\s*,\s*\d{1,2}\s*\)",
            r"3\s*,\s*3\s*,\s*3\s*,\s*1\s*,\s*1\s*,\s*1\s*,\s*1\s*,\s*4\s*,\s*4\s*,\s*4\s*,\s*1\s*,\s*1\s*,\s*1",
            r"(?:^|\s)/(?:workspace|prime|tmp|users)(?:/|\s|$)",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertIsNone(re.search(forbidden, P7_SOLVING_PROMPT, re.IGNORECASE))
        self.assertEqual(
            set(P7_SOLVING_GUIDANCE_LOCK),
            {"format", "license_sha256", "prompt_sha256", "upstream_commit"},
        )
        self.assertEqual(
            P7_SOLVING_GUIDANCE_LOCK["upstream_commit"],
            "398d4dd63cf01d00adbea41c13437ba0b8ad40fc",
        )
        self.assertEqual(
            P7_SOLVING_GUIDANCE_LOCK["license_sha256"],
            "sha256:bf446b52c755dc80e8661ad171edbdec85d2df1307349fbf2dd2e91405166fd9",
        )
        self.assertRegex(P7_SOLVING_GUIDANCE_LOCK["prompt_sha256"], r"\Asha256:[0-9a-f]{64}\Z")


if __name__ == "__main__":
    unittest.main()
