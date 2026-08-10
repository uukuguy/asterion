from __future__ import annotations

import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from asterion.control.authority import BudgetLimit
from asterion.control.providers.prime.factory import (
    PRIME_NATIVE_RLM_MAX_DEPTH,
    derive_prime_child_control_options,
)
from tests.test_control_children import _child_envelope
from tests.test_prime_control_factory import make_context, prepare_paths


class TestPrimeVerifiedLoopChildBoundary(unittest.TestCase):
    def test_hostile_parent_options_are_redacted(self) -> None:
        class HostileOptions(Mapping[str, str]):
            def __getitem__(self, key: str) -> str:
                raise RuntimeError(f"SENTINEL:{key}")

            def __iter__(self):
                raise RuntimeError("SENTINEL")

            def __len__(self) -> int:
                raise RuntimeError("SENTINEL")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError) as raised:
                derive_prime_child_control_options(
                    HostileOptions(), child_root=root,
                    child_session_id="child-session-child-1",
                    child_authority=_child_envelope(authority_id="child:child-1"),
                    generation=1,
                )
            self.assertEqual(str(raised.exception), "Prime child control options are invalid")
            self.assertNotIn("SENTINEL", str(raised.exception))

    def test_prime_child_options_are_distinct_narrowed_and_native_rlm_constant_is_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)
            parent = make_context(root)
            child_root = root / "children" / "child-1"
            child_root.mkdir(parents=True, mode=0o700)
            child_authority = _child_envelope(
                authority_id="child:child-1",
                budget_limit=BudgetLimit(25, 0, 50, 50, 10),
                max_recursion_depth=0,
                max_action_deadline_ms=500,
            )

            options = derive_prime_child_control_options(
                parent.options,
                child_root=child_root,
                child_session_id="child-session-child-1",
                child_authority=child_authority,
                generation=1,
            )

            self.assertEqual(PRIME_NATIVE_RLM_MAX_DEPTH, 0)
            self.assertEqual(options["session_id"], "child-session-child-1")
            self.assertEqual(options["authority_id"], "child:child-1")
            self.assertEqual(options["generation"], "1")
            self.assertEqual(options["max_controller_tokens"], "25")
            self.assertEqual(options["timeout_ms"], "500")
            self.assertNotEqual(options["session_dir"], parent.options["session_dir"])
            self.assertNotEqual(options["gateway_root"], parent.options["gateway_root"])
            self.assertTrue(options["session_dir"].startswith(str(child_root)))
            self.assertTrue(options["gateway_root"].startswith(str(child_root)))
            self.assertTrue(options["agent_dir"].startswith(str(child_root)))
            self.assertEqual(options["prime_socket_path"], parent.options["prime_socket_path"])
            self.assertEqual(options["model"], parent.options["model"])
            self.assertEqual(options["workspace"], parent.options["workspace"])
            self.assertEqual(options["prime_source_root"], parent.options["prime_source_root"])
            self.assertEqual(options["artifact_lock_path"], parent.options["artifact_lock_path"])

    def test_prime_child_options_reject_zero_caps_that_prime_descriptor_cannot_accept(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)
            parent = make_context(root)
            child_root = root / "children" / "child-1"
            child_root.mkdir(parents=True, mode=0o700)

            with self.assertRaises(ValueError):
                derive_prime_child_control_options(
                    parent.options,
                    child_root=child_root,
                    child_session_id="child-session-child-1",
                    child_authority=_child_envelope(
                        authority_id="child:child-1",
                        budget_limit=BudgetLimit(0, 0, 50, 50, 10),
                    ),
                    generation=1,
                )
            with self.assertRaises(ValueError):
                derive_prime_child_control_options(
                    parent.options,
                    child_root=child_root,
                    child_session_id="child-session-child-1",
                    child_authority=_child_envelope(authority_id="child:child-1"),
                    generation=0,
                )


if __name__ == "__main__":
    unittest.main()
