"""Tests for the LLM-facing semantic game-cognition contract."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime.p7.semantic_cognition import (
    CognitionError,
    SemanticCognitionStore,
)


class SemanticCognitionTests(unittest.TestCase):
    def _store(self, root: Path) -> SemanticCognitionStore:
        return SemanticCognitionStore(
            root, game_id="synthetic-game", seed=0, win_levels=2, level=0,
        )

    @staticmethod
    def _write_raw(root: Path, payload: dict) -> None:
        path = root / ".asterion-private" / "prime-p7-live" / "semantic-cognition.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_llm_proposes_semantic_hypotheses_without_route_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            accepted = store.propose({
                "claims": [
                    {
                        "id": "type-maze",
                        "kind": "game_type",
                        "subject": "board",
                        "claim": "This resembles a two-dimensional maze game.",
                        "reason": "The frame contains traversable regions and boundaries.",
                        "falsifier": "No action can move a controllable object through the regions.",
                        "next_test": "Test one directional action on the suspected player.",
                    },
                    {
                        "id": "role-player-7",
                        "kind": "object_role",
                        "subject": "color-7-component",
                        "claim": "The small color-7 component may be the player.",
                        "reason": "It is isolated from the large background region.",
                        "falsifier": "A different component moves while color 7 never changes.",
                        "next_test": "Apply a directional action and observe which component moves.",
                    },
                ],
            })
            self.assertEqual(accepted, 2)
            report = store.report()
            self.assertEqual(report["schema"], "asterion.prime.p7-semantic-cognition/v1")
            self.assertEqual(report["claims"]["undetermined"][0]["status"], "undetermined")
            self.assertEqual(report["execution_authority"], "none")
            encoded = json.dumps(report, ensure_ascii=False)
            self.assertNotIn("route", encoded.lower())
            self.assertNotIn('"data"', encoded)
            self.assertNotIn('"x"', encoded)

    def test_proposal_accepts_descriptive_envelope_and_updates_same_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            store.propose({
                "scope": {"level": 0}, "status": "working", "description": "initial pass",
                "claims": [{
                    "id": "control-updated", "kind": "control", "subject": "ACTION2",
                    "claim": "ACTION2 may move the actor.", "reason": "The actor is isolated.",
                    "falsifier": "No actor movement occurs.", "next_test": "Apply ACTION2.",
                }],
            })
            accepted = store.propose({
                "scope": {"level": 0}, "status": "refined", "claims": [{
                    "id": "control-updated", "kind": "control", "subject": "ACTION2",
                    "claim": "ACTION2 moves the actor toward the goal.", "reason": "The latest frame suggests alignment.",
                    "falsifier": "The actor moves away from the goal.", "next_test": "Repeat ACTION2.",
                    "confidence": 0.8,
                }],
            })
            self.assertEqual(accepted, 1)
            claim = next(item for item in store.report()["claims"]["undetermined"] if item["id"] == "control-updated")
            self.assertEqual(claim["subject"], "ACTION2")
            self.assertEqual(claim["claim"], "ACTION2 moves the actor toward the goal.")
            self.assertEqual(claim["confidence"], 0.8)

    def test_proposal_rejects_core_identity_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            store.propose({"claims": [{
                "id": "identity-bound", "kind": "control", "subject": "ACTION1",
                "claim": "ACTION1 moves.", "reason": "Available.", "falsifier": "No movement.", "next_test": "Apply.",
            }]})
            with self.assertRaises(CognitionError):
                store.propose({"claims": [{
                    "id": "identity-bound", "kind": "object_role", "subject": "ACTION1",
                    "claim": "ACTION1 is an object.", "reason": "Changed interpretation.", "falsifier": "It moves.", "next_test": "Observe.",
                }]})

    def test_confidence_is_non_authoritative_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            accepted = store.propose({
                "claims": [{
                    "id": "high-confidence-picture",
                    "kind": "game_type",
                    "subject": "initial-frame",
                    "claim": "The initial frame is a discrete game scene.",
                    "reason": "The runtime returned a settled frame.",
                    "falsifier": "The frame is not stable game state.",
                    "next_test": "Compare it after one primitive action.",
                    "confidence": 0.9,
                }],
            })
            self.assertEqual(accepted, 1)
            claim = store.report()["claims"]["undetermined"][0]
            self.assertEqual(claim["confidence"], 0.9)
            self.assertEqual(claim["status"], "undetermined")
            self.assertEqual(store.report()["execution_authority"], "none")

            with self.assertRaises(CognitionError):
                store.propose({
                    "claims": [{
                        "id": "invalid-confidence",
                        "kind": "rule",
                        "subject": "unknown",
                        "claim": "A rule may exist.",
                        "reason": "It is a hypothesis.",
                        "falsifier": "No rule is observed.",
                        "next_test": "Try one action.",
                        "confidence": 1.1,
                    }],
                })

    def test_llm_cannot_claim_certainty_or_submit_executable_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            with self.assertRaises(CognitionError):
                store.propose({
                    "claims": [{
                        "id": "bad",
                        "kind": "control",
                        "subject": "ACTION1",
                        "claim": "ACTION1 moves up.",
                        "status": "certain",
                        "plan": [{"name": "ACTION1"}],
                    }],
                })

    def test_llm_cannot_forge_evidence_and_rejection_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            with self.assertRaises(CognitionError):
                store.propose({"claims": [
                    {
                        "id": "valid",
                        "kind": "game_type",
                        "subject": "board",
                        "claim": "The board resembles a maze.",
                        "reason": "It contains bounded regions.",
                        "falsifier": "No controllable movement exists.",
                        "next_test": "Try one directional action.",
                    },
                    {
                        "id": "forged",
                        "kind": "control",
                        "subject": "ACTION1",
                        "claim": "ACTION1 moves up.",
                        "reason": "This is a guess.",
                        "falsifier": "The object does not move up.",
                        "next_test": "Try ACTION1.",
                        "evidence": [{"reference": "fake", "explanation": "fake", "status": "certain"}],
                    },
                ]})
            self.assertFalse(store.report()["claims"]["undetermined"])

    def test_evidence_updates_claims_and_preserves_counterexamples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            store.propose({
                "claims": [{
                    "id": "control-action2",
                    "kind": "control",
                    "subject": "ACTION2",
                    "claim": "ACTION2 moves the suspected player right.",
                    "reason": "The action is available and the player is near an open cell.",
                    "falsifier": "The suspected player moves in another direction.",
                    "next_test": "Execute ACTION2 once on the current frame.",
                }],
            })
            store.resolve(
                "control-action2", status="certain",
                evidence="run-a/frame-1", explanation="The same object moved right.",
            )
            store.resolve(
                "control-action2", status="falsified",
                evidence="run-b/frame-2", explanation="The object did not move right.",
            )
            claim = next(item for item in store.report()["claims"]["falsified"] if item["id"] == "control-action2")
            self.assertEqual(claim["status"], "falsified")
            self.assertEqual(claim["evidence_count"], 2)
            self.assertEqual(claim["counterexample_count"], 1)

    def test_duplicate_evidence_reference_is_rejected_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            store.propose({
                "claims": [{
                    "id": "control-action1",
                    "kind": "control",
                    "subject": "ACTION1",
                    "claim": "ACTION1 moves the suspected player up.",
                    "reason": "The action is available.",
                    "falsifier": "The player does not move up.",
                    "next_test": "Execute ACTION1 once.",
                }],
            })
            store.resolve(
                "control-action1", status="certain",
                evidence="run-a/frame-1", explanation="The player moved up.",
            )
            with self.assertRaises(CognitionError):
                store.resolve(
                    "control-action1", status="falsified",
                    evidence="run-a/frame-1", explanation="A duplicate frame reference.",
                )
            claim = next(item for item in store.report()["claims"]["certain"] if item["id"] == "control-action1")
            self.assertEqual(claim["evidence_count"], 1)
            self.assertEqual(claim["status"], "certain")

    def test_persisted_resolved_status_requires_matching_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = {"game_id": "synthetic-game", "seed": 0, "win_levels": 2, "level": 0}
            claim_base = {
                "kind": "control",
                "subject": "ACTION1",
                "claim": "ACTION1 moves up.",
                "reason": "A directional action is available.",
                "falsifier": "The player does not move up.",
                "next_test": "Execute ACTION1 once.",
            }
            self._write_raw(root, {
                "schema": "asterion.prime.p7-semantic-cognition/v1",
                "records": {
                    "synthetic-game|0|2|0": {
                        "identity": identity,
                        "claims": {
                            "bare-certain": {**claim_base, "id": "bare-certain", "status": "certain", "evidence": []},
                            "wrong-evidence": {
                                **claim_base,
                                "id": "wrong-evidence",
                                "status": "falsified",
                                "evidence": [{
                                    "reference": "runtime/frame-1",
                                    "explanation": "The action moved up.",
                                    "status": "certain",
                                }],
                            },
                            "valid-open": {**claim_base, "id": "valid-open", "status": "undetermined", "evidence": []},
                        },
                        "protocol": None,
                    },
                },
            })
            report = self._store(root).report()
            self.assertEqual([item["id"] for item in report["claims"]["certain"]], [])
            self.assertEqual([item["id"] for item in report["claims"]["falsified"]], [])
            self.assertEqual([item["id"] for item in report["claims"]["undetermined"]], ["valid-open"])

    def test_persisted_protocol_certainty_requires_runtime_evidence(self) -> None:
        identity = {"game_id": "synthetic-game", "seed": 0, "win_levels": 2, "level": 0}
        for evidence in (
            [],
            [{"reference": "manual.levels_completed", "explanation": "A hand edit.", "status": "certain"}],
        ):
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._write_raw(root, {
                    "schema": "asterion.prime.p7-semantic-cognition/v1",
                    "records": {
                        "synthetic-game|0|2|0": {
                            "identity": identity,
                            "claims": {},
                            "protocol": {
                                "status": "certain",
                                "claim": "The runtime reports completion.",
                                "subject": "protocol.level_completion",
                                "level_completed": 1,
                                "evidence": evidence,
                            },
                        },
                    },
                })
                report = self._store(root).report()
                self.assertEqual(report["success_condition"]["protocol"]["status"], "undetermined")

    def test_seed_protocol_claim_is_idempotent_for_runtime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            store.seed_protocol_claims(level_completed=1)
            store.seed_protocol_claims(level_completed=1)
            protocol = store.report()["success_condition"]["protocol"]
            self.assertEqual(protocol["evidence_count"], 1)

    def test_protocol_claims_are_separate_from_puzzle_goal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            store.seed_protocol_claims(level_completed=1)
            store.propose({
                "claims": [{
                    "id": "goal-touch-special",
                    "kind": "success_condition",
                    "subject": "suspected-player-and-goal",
                    "claim": "The player reaching the special region completes L1.",
                    "reason": "The region is visually distinct.",
                    "falsifier": "The level advances without contact or contact has no effect.",
                    "next_test": "Test a move into the special region.",
                }],
            })
            report = store.report()
            self.assertEqual(report["success_condition"]["protocol"]["status"], "certain")
            self.assertEqual(report["success_condition"]["puzzle"][0]["status"], "undetermined")

    def test_same_identity_reload_keeps_semantics_but_never_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            store.propose({
                "claims": [{
                    "id": "strategy-safe-exploration",
                    "kind": "strategy",
                    "subject": "L1",
                    "claim": "Probe movement before attempting a long route.",
                    "reason": "The object roles are still unknown.",
                    "falsifier": "The board exposes a direct confirmed goal action.",
                    "next_test": "Choose the safest movement probe.",
                }],
            })
            reloaded = self._store(root)
            report = reloaded.report()
            self.assertTrue(report["claims"]["undetermined"])
            self.assertEqual(report["execution_authority"], "none")
            self.assertEqual(report["scope"]["level"], 0)
            other = SemanticCognitionStore(root, "other-game", 0, 2, level=0)
            self.assertFalse(other.report()["claims"]["undetermined"])


if __name__ == "__main__":
    unittest.main()
