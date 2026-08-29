from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

from tools.prime_bounded_loop_experiment import (
    BoundedLoopPrivateResultStore,
    PrimeBoundedLoopError,
    derive_bounded_loop_assertions,
    derive_bounded_loop_causal_digests,
    reduce_native_probe_observation,
    reduce_bounded_loop_evidence,
    write_bounded_loop_receipt,
)


class TestPrimeBoundedLoopEvidence(unittest.TestCase):
    def test_private_result_store_returns_only_closed_public_projection(self) -> None:
        store = BoundedLoopPrivateResultStore()
        publication = store.publish_application_result(
            action_id="action-1",
            provider_id="provider",
            application_id="application",
            version="1.0.0",
            runtime_id="runtime",
            idempotency_key="idempotency-1",
            run_id="run-1",
            result={"private": "SENTINEL_PRIVATE_RESULT"},
        )

        self.assertEqual(publication.action_id, "action-1")
        self.assertEqual(publication.artifact_ids, ())
        self.assertEqual(publication.media_types, ())
        self.assertNotIn("SENTINEL_PRIVATE_RESULT", repr(publication))

    @staticmethod
    def _causal_digests() -> dict[str, str]:
        return {
            "application.invoke": "a" * 64,
            "child.spawn": "b" * 64,
            "checkpoint.create": "c" * 64,
            "session.cancel": "d" * 64,
            "budget.probe": "e" * 64,
        }

    def test_derives_assertions_only_from_closed_control_facts(self) -> None:
        assertions = derive_bounded_loop_assertions(
            session_events=("session.created", "session.recovery-required"),
            action_statuses={
                "application.invoke": "succeeded",
                "child.spawn": "succeeded",
                "checkpoint.create": "succeeded",
                "session.cancel": "cancelled",
                "budget.probe": "rejected",
            },
            detached_attached=True,
            public_redacted=True,
        )
        self.assertTrue(all(assertions.values()))

    def test_hashes_only_complete_observed_control_identities(self) -> None:
        identities = {
            "application.invoke": ("event-application", "action-application"),
            "child.spawn": ("event-child", "action-child"),
            "checkpoint.create": ("event-checkpoint", "action-checkpoint"),
            "session.cancel": ("command-cancel", "event-cancelled"),
            "budget.probe": ("event-budget", "action-budget"),
        }
        digests = derive_bounded_loop_causal_digests(identities)

        self.assertEqual(set(digests), set(identities))
        self.assertTrue(all(len(value) == 64 for value in digests.values()))
        self.assertNotIn("event-application", repr(digests))
        with self.assertRaises(PrimeBoundedLoopError):
            derive_bounded_loop_causal_digests(
                {**identities, "budget.probe": ("event-budget", "")}
            )

    def test_reduces_only_a_complete_native_probe_observation(self) -> None:
        report = reduce_native_probe_observation(
            session_events=("session.created", "session.recovery-required", "session.cancelled"),
            application_receipted=True,
            child_completed=True,
            detached_attached=True,
            checkpoint_recovered=True,
            cancelled=True,
            budget_limited=True,
            usage={"aggregate_tokens": 9},
            causal_identities={
                "application.invoke": ("event-app", "action-app"),
                "child.spawn": ("event-child", "action-child"),
                "checkpoint.create": ("event-checkpoint", "action-checkpoint"),
                "session.cancel": ("command-cancel", "event-cancel"),
                "budget.probe": ("event-budget", "action-budget"),
            },
        )
        self.assertEqual(report["status"], "PASS")

    def test_rejects_open_or_malformed_control_facts(self) -> None:
        with self.assertRaises(PrimeBoundedLoopError):
            derive_bounded_loop_assertions(
                session_events=("session.created",),
                action_statuses={"application.invoke": "succeeded"},
                detached_attached=True,
                public_redacted=True,
            )
        assertions = derive_bounded_loop_assertions(
            session_events=("session.created",),
            action_statuses={
                "application.invoke": "succeeded",
                "child.spawn": "failed",
                "checkpoint.create": "succeeded",
                "session.cancel": "completed",
                "budget.probe": "succeeded",
            },
            detached_attached=False,
            public_redacted=False,
        )
        self.assertEqual(
            assertions,
            {
                "root_created": True,
                "application_receipted": True,
                "child_completed": False,
                "detach_attached": False,
                "checkpoint_recovered": False,
                "cancelled": False,
                "budget_limited": False,
                "public_redacted": False,
            },
        )

    def test_requires_every_phase_one_real_closure_assertion(self) -> None:
        complete = {
            "root_created": True,
            "application_receipted": True,
            "child_completed": True,
            "detach_attached": True,
            "checkpoint_recovered": True,
            "cancelled": True,
            "budget_limited": True,
            "public_redacted": True,
        }
        self.assertEqual(
            reduce_bounded_loop_evidence(
                complete,
                usage={"aggregate_tokens": 1},
                causal_digests=self._causal_digests(),
            ),
            {
                "causal_digests": self._causal_digests(),
                "status": "PASS",
                "terminal": "completed",
                "usage": {"aggregate_tokens": 1},
            },
        )
        for missing in complete:
            with self.subTest(missing=missing):
                incomplete = dict(complete)
                incomplete[missing] = False
                with self.assertRaises(PrimeBoundedLoopError):
                    reduce_bounded_loop_evidence(
                        incomplete,
                        usage={"aggregate_tokens": 1},
                        causal_digests=self._causal_digests(),
                    )

        with self.assertRaises(PrimeBoundedLoopError):
            reduce_bounded_loop_evidence(
                complete,
                usage={"aggregate_tokens": 1},
                causal_digests={"application.invoke": "not-a-digest"},
            )

    def test_receipt_persists_only_closed_public_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = write_bounded_loop_receipt(
                root,
                {
                    "root_created": True, "application_receipted": True,
                    "child_completed": True, "detach_attached": True,
                    "checkpoint_recovered": True, "cancelled": True,
                    "budget_limited": True, "public_redacted": True,
                },
                usage={"aggregate_tokens": 7},
                causal_digests=self._causal_digests(),
            )
            payload = json.loads((root / "bounded-loop-receipt.json").read_text())
        self.assertEqual(receipt, payload)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["causal_digests"], self._causal_digests())
