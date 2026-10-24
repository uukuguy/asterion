"""Application context bounds stay independent of the DCI comparison levels."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from asterion.runtime.context_policy import ContextPolicyError, parse_context_policy


_EXTENSION = (
    Path(__file__).parents[1]
    / "src/asterion/runtimes/resources/context-policy-extension.mjs"
)


class ContextPolicyTests(unittest.TestCase):
    def test_accepts_each_independent_bound_set(self) -> None:
        cases = (
            {"tool_result_chars": 20000},
            {"compact_chars": 240000, "retain_turns": 12},
            {
                "compact_chars": 240000,
                "retain_turns": 12,
                "summary_failures": 3,
                "summary_tokens": 20000,
                "tool_result_chars": 20000,
            },
        )
        for payload in cases:
            with self.subTest(payload=payload):
                encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                self.assertEqual(dict(parse_context_policy(encoded)), payload)

    def test_rejects_research_levels_and_incomplete_bounds(self) -> None:
        for value in (
            "level3",
            "{}",
            '{"tool_result_chars": 20000}',
            '{"compact_chars":240000}',
            '{"summary_failures":3,"summary_tokens":20000}',
            '{"profile":"level4"}',
            '{"tool_result_chars":0}',
        ):
            with self.subTest(value=value):
                with self.assertRaises(ContextPolicyError):
                    parse_context_policy(value)
        self.assertIsNone(parse_context_policy(None))

    def test_extension_applies_the_same_bounds(self) -> None:
        policy = '{"compact_chars":9,"retain_turns":2,"tool_result_chars":5}'
        script = (
            "import { parseContextPolicy, truncateText } from "
            f"{json.dumps(_EXTENSION.as_uri())};\n"
            "const policy = parseContextPolicy(process.argv[1]);\n"
            "if (JSON.stringify(policy) !== process.argv[1]) "
            "throw new Error(JSON.stringify(policy));\n"
            "if (truncateText('hello', 5) !== 'hello') throw new Error('short');\n"
            "const long = truncateText('a'.repeat(100), 80);\n"
            "if (long.length !== 80 || !long.endsWith('[tool result truncated]')) "
            "throw new Error(long);\n"
            "let rejected = false;\n"
            "try { parseContextPolicy('level3'); } catch { rejected = true; }\n"
            "if (!rejected) throw new Error('level accepted');\n"
        )
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script, policy],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
