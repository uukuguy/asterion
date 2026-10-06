"""Fresh target cognition quarantines a fixed historical snapshot, not new learning."""

from dataclasses import replace
import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7 import operator
from asterion.applications.prime.p7.experience import load_experience
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.solutions import VerifiedPrefix
from tests import test_prime_p7_experience as experience_fixture
from tests import test_prime_p7_native_provider as native_fixture
from tests.test_prime_p7_model_selection import _profile
from tools.run_prime_p7_guest import launch


MODE = "ASTERION_PRIME_P7_COGNITION_MODE"
POLICY = "ASTERION_PRIME_P7_FRESH_TARGET_POLICY"


def policy_record():
    return {"schema": "asterion.prime-p7-fresh-target/v1", "phase_id": "renewal-1",
            "game_id": "test-1", "seed": 0, "target_level": 2,
            "resume_run_id": "failed-001", "prefix_levels_completed": 1,
            "prefix_action_count": 3, "quarantined_source_run_ids": ["failed-001"]}


class TestFreshTargetPolicy(unittest.TestCase):
    def test_policy_is_closed_explicit_and_bound_to_exact_prefix(self):
        environment = {MODE: "fresh-target", POLICY: json.dumps(policy_record()),
                       "ASTERION_PRIME_P7_RUN_MODE": "witness"}
        policy = operator._resolve_fresh_target_policy(environment, resume_run_id="failed-001")
        self.assertEqual(policy.record(), policy_record())
        game = P7GameSelection("test-1", 0, 2, _metadata_win_levels=2,
                               _metadata_baseline_actions=(3, 5))
        prefix = VerifiedPrefix("test-1", 0, 2, 1, (object(),) * 3, "failed-001", "sha256:" + "a" * 64)
        operator._validate_fresh_target_prefix(policy, game, prefix)
        for value in (replace(prefix, levels_completed=0), replace(prefix, transitions=(object(),)),
                      replace(prefix, source_run_id="other"), replace(prefix, seed=1)):
            with self.subTest(prefix=value), self.assertRaises(operator.P7OperatorError):
                operator._validate_fresh_target_prefix(policy, game, value)
        cases = [{}, {MODE: "fresh-target"}, {POLICY: json.dumps(policy_record())},
                 {**environment, MODE: "invalid"},
                 {**environment, "ASTERION_PRIME_P7_RUN_MODE": "solve"},
                 {**environment, POLICY: json.dumps({**policy_record(), "extra": True})},
                 {**environment, POLICY: json.dumps({**policy_record(), "prefix_action_count": True})},
                 {**environment, POLICY: json.dumps({**policy_record(), "quarantined_source_run_ids": []})}]
        self.assertIsNone(operator._resolve_fresh_target_policy({}, resume_run_id=None))
        for value in cases[1:]:
            with self.subTest(environment=value), self.assertRaises(operator.P7OperatorError):
                operator._resolve_fresh_target_policy(value, resume_run_id="failed-001")

    def test_resume_policy_mismatch_rejects_before_engine_or_model(self):
        policy = operator._resolve_fresh_target_policy({
            MODE: "fresh-target", POLICY: json.dumps(policy_record()),
            "ASTERION_PRIME_P7_RUN_MODE": "witness",
        }, resume_run_id="failed-001")
        game = P7GameSelection("test-1", 0, 2, _metadata_win_levels=2,
                               _metadata_baseline_actions=(3, 5))
        prefix = VerifiedPrefix("test-1", 0, 2, 1, (object(),), "failed-001", "sha256:" + "a" * 64)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            environment = {"ASTERION_PRIME_P7_RUN_MODE": "witness",
                           "ASTERION_PRIME_P7_ATTEMPT_STARTED_MONOTONIC": str(time.monotonic()),
                           "ASTERION_PRIME_P7_ATTEMPT_SECONDS": "900",
                           "ASTERION_PRIME_P7_ATTEMPT_UNIT": "asterion-p7-" + "a" * 32 + ".service",
                           "ASTERION_PRIME_P7_CONSOLE_RUN_ID": "p7-live-20261006123456-" + "a" * 24}
            invocation = operator.P7Invocation(root, environment,
                                                root, (), root, game, resume_run_id="failed-001",
                                                fresh_target_policy=policy)
            with patch("asterion.applications.prime.p7.solutions._read_one", return_value=(prefix, None, game)), \
                 patch("asterion.applications.prime.p7.solutions.load_exact_prefix") as load_prefix, \
                 patch("asterion.applications.prime.p7.operator.live.ArcadeEngine") as engine, \
                 patch("asterion.applications.prime.p7.operator.run_composed_application") as model:
                with self.assertRaisesRegex(operator.P7OperatorError, "fresh target policy"):
                    asyncio.run(operator.run_live(invocation, "current"))
                engine.assert_not_called()
                model.assert_not_called()
                load_prefix.assert_not_called()

    def test_guest_forwards_operator_policy_under_fixed_witness_bounds(self):
        unit = "asterion-p7-" + "a" * 32 + ".service"
        environment = {MODE: "fresh-target", POLICY: json.dumps(policy_record()),
                       "ASTERION_PRIME_P7_RUN_MODE": "witness",
                       "ASTERION_PRIME_P7_CONSOLE_RUN_ID": "p7-live-20261006123456-" + "a" * 24,
                       "ASTERION_PRIME_P7_ATTEMPT_UNIT": unit,
                       "ASTERION_PRIME_P7_ATTEMPT_SECONDS": "900"}
        with patch.dict(os.environ, environment, clear=True), \
             patch("tools.run_prime_p7_guest.Path.is_file", return_value=True), \
             patch("tools.run_prime_p7_guest.os.execvp", side_effect=SystemExit(0)) as call:
            with self.assertRaises(SystemExit):
                launch(unit, 900, ["python3", "-V"])
        self.assertIn("--setenv=" + MODE + "=fresh-target", call.call_args.args[1])
        self.assertIn("--setenv=" + POLICY + "=" + environment[POLICY], call.call_args.args[1])

    def test_model_process_environment_excludes_operator_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            extension = root / "extension.mjs"
            extension.write_text("export default function extension() {}\n")
            trace_root = root / "trace"
            trace_root.mkdir()
            worker = native_fixture._Worker()
            resources = operator.build_p7_operator_resources(
                environment={"ASTERION_PRIME_PI_AGENT_DIR": _profile(directory),
                             "ASTERION_PRIME_PROVIDER": "openai-codex", "ASTERION_PRIME_MODEL": "gpt-6.1-sol",
                             MODE: "fresh-target", POLICY: "SENTINEL_OPERATOR_POLICY"},
                pi_base_command=("/usr/bin/pi", "--mode", "rpc"), extension_path=extension,
                working_directory=root, worker=worker, engine=native_fixture._CompletingEngine(),
                private_trace_root=trace_root,
            )
            try:
                approved = resources.host_services["prime.launch"].approved_environment
                self.assertNotIn(MODE, approved)
                self.assertNotIn(POLICY, approved)
                self.assertNotIn("SENTINEL_OPERATOR_POLICY", json.dumps(dict(approved)))
                self.assertEqual(worker.starts, 0)
            finally:
                asyncio.run(resources.close())


class TestFreshTargetExperience(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def source(self, name="failed-001"):
        return experience_fixture.TestExperience.source(self, name)

    def load(self):
        return load_experience(self.root, game_id="test-1", seed=0, win_levels=2,
                               model_id="gpt-6.1-sol", current_run_id="current",
                               fresh_target_policy=policy_record())

    def test_old_positive_content_blocked_raw_evidence_retained_and_new_learning_reused(self):
        run, _ = self.source("failed-001")
        before = {path: path.read_bytes() for path in run.rglob("*") if path.is_file()}
        bundle = self.load()
        self.assertIsNone(bundle.context()["latest"])
        self.assertNotIn("did not open", json.dumps(bundle.context()))
        self.assertEqual(bundle.context()["available_count"], 1)
        self.assertEqual(bundle.read("", "index")["total"], 1)
        for kind in ("research", "artifact", "cells"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "quarantined"):
                bundle.read("failed-001", kind)
        self.assertEqual(bundle.read("failed-001", "history")["items"], [])
        self.assertEqual(bundle.read("failed-001", "frame")["items"], [])
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.source("new-round-001")
        fresh = self.load()
        self.assertEqual(fresh.context()["latest"]["source_run_id"], "new-round-001")
        self.assertTrue(fresh.read("new-round-001", "research")["items"])
        current = self.root / "current"
        current.mkdir()
        fresh.bind(current)
        manifest = json.loads((current / "research" / "experience-manifest.json").read_text())
        self.assertEqual(manifest["fresh_target_policy"], policy_record())

    def test_quarantined_frame_and_animation_keep_authenticated_raw_evidence(self):
        experience_fixture.TestExperience.test_legacy_animation_bypasses_metadata_totals_and_reads_only_requested_page(self)


if __name__ == "__main__":
    unittest.main()
