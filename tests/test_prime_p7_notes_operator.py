"""The actual task instructions survive model-only research memory projection."""
import json
import unittest

from asterion.applications.prime.p7 import prompt


class TestP7NotesOperator(unittest.TestCase):
    def test_initial_context_captures_instructions_before_reading_observation(self):
        calls = []

        class Host:
            def set_memory_instructions(self, text):
                calls.append(('instructions', text))

            def actor_context(self):
                calls.append(('observation', None))
                return {'observation_ref': {'sequence': 7}}

        instructions = 'Current task and operator-specific target must survive.'
        result = prompt.initial_research_prompt(Host(), instructions)
        self.assertEqual(calls, [('instructions', instructions), ('observation', None)])
        self.assertTrue(result.startswith(instructions))
        self.assertEqual(json.loads(result.split('\n')[-1]),
                         {'observation_ref': {'sequence': 7}})

    def test_notes_guidance_uses_current_free_text_without_legacy_ceremony(self):
        text = prompt.build_notes_prompt()
        for contract in ('observation_ref', 'base_revision', "op:'notes'",
                         'notes_history', 'needs_revision', 'RESET', 'unknown'):
            with self.subTest(contract=contract):
                self.assertIn(contract, text)
        self.assertNotIn("开始就做一次轻量 p7_workspace({op:'revise'", text)
        self.assertNotIn('Draft 固定字段如下', text)
        self.assertIn(prompt.ACTOR_FRAME_INSTRUCTION, text)
