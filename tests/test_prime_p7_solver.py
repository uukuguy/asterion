"""Application research and sequential broker boundaries, provider free."""

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.score import digest
from asterion.applications.prime.p7.score import canonical_bytes
from asterion.applications.prime.p7.solver import Solver
from tests.test_prime_p7_native_broker import _Engine


class _Kernel:
    generation = 1

    def __init__(self):
        self.exports = {}

    def export(self, name, value, kind="json"):
        eid = digest(
            {"name": name, "kind": kind, "value": value, "source_call_id": "cell-1"}
        )
        self.exports[eid] = SimpleNamespace(
            export_id=eid,
            name=name,
            kind=kind,
            value=copy.deepcopy(value),
            source_call_id="cell-1",
        )
        return eid

    def read_export(self, eid):
        return self.exports[eid]


class _Control:
    def __init__(self):
        self.state = "running"

    def poll(self, *args):
        return self.snapshot()

    def snapshot(self):
        return {"state": self.state}

    def action_allowed(self):
        return self.state == "running"

    def enter(self, operation):
        return self.action_allowed()

    def leave(self, operation):
        pass


def draft(source_ids=()):
    return {
        "worldmap": {
            "description_zh": "移动模型，目标待验证。",
            "state_summary": "位于起点",
            "rules": ["ACTION1 改变位置"],
            "unknowns": ["目标未知"],
            "competing_hypotheses": [],
        },
        "task": {
            "goal": "移动",
            "obstacles": [],
            "question": "移动规律？",
            "next_operation": "probe",
            "public_basis": "当前真实观察",
        },
        "model": {
            "source_export_ids": list(source_ids),
            "coverage": "局部",
            "assumptions": [],
        },
        "reports": [],
        "evidence_sequences": [0],
        "correction": {"changed": [], "retained": []},
    }


class P7SolverFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.engine = _Engine()
        self.broker = ArcBroker(engine=self.engine)
        self.broker.bind_history("run-1")
        self.kernel, self.control, self.events = _Kernel(), _Control(), []
        self.solver = Solver(
            broker=self.broker,
            kernel=self.kernel,
            control=self.control,
            workspace_root=Path(self.directory.name),
            run_id="run-1",
            attempt_id="attempt-1",
            event_sink=lambda kind, payload: self.events.append((kind, payload)),
        )

    def plan(self, values=(1, 2, 3)):
        context = self.solver.current_context()
        return {
            "plan_id": "plan-1",
            "start": context["observation_ref"],
            "workspace_revision": context["workspace_revision"],
            "goal": "移动",
            "purpose": "probe",
            "assumptions": [],
            "steps": [
                {
                    "action": {"name": "ACTION1", "data": {}},
                    "expect": {
                        "cells": [{"x": 0, "y": 0, "value": value}],
                        "levels_completed": 0,
                    },
                }
                for value in values
            ],
        }

    def revise(self, solver=None):
        solver = self.solver if solver is None else solver
        value = draft()
        value["evidence_sequences"] = [
            solver.current_context()["observation_ref"]["sequence"]
        ]
        return solver.workspace(
            {
                "op": "revise",
                "base_revision": solver.current_context()["workspace_revision"],
                **{
                    key: value[key]
                    for key in ("worldmap", "task", "evidence_sequences", "correction")
                },
            }
        )


class TestP7Solver(P7SolverFixture):
    def test_known_local_processing_failure_is_explicit_and_never_redispatched(self):
        from unittest.mock import patch
        from asterion.applications.prime.p7.dynamic_evidence import EvidenceProcessingError
        self.revise()
        plan = self.plan((1,))
        failure = EvidenceProcessingError('evidence-write-failed', action_sequence=1,
                                          outcome_known=True, durable=False)
        with patch.object(self.broker, 'act_checked', side_effect=failure) as dispatch:
            result = self.solver.execute_plan(plan)
            repeated = self.solver.execute_plan(plan)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(result['stop_reason'], 'processing-failed')
        self.assertEqual(repeated['diagnostics'], result['diagnostics'])
        context = self.solver.current_context()
        self.assertFalse(context['environment_result_unknown'])
        self.assertTrue(context['processing_blocked'])
        self.assertTrue(context['diagnostics'][0]['outcome_known'])
        self.assertTrue(any(kind == 'diagnostic' for kind, _ in self.events))

    def test_context_reference_keeps_complete_identity_separate_from_stable_pixels(self):
        from unittest.mock import patch
        complete = {'sequence': 0, 'observation_sha256': 'sha256:' + 'b' * 64,
                    'animation_ref': {'schema': 'asterion.prime.p7-animation/v1',
                                      'sha256': 'sha256:' + 'c' * 64, 'frame_count': 95,
                                      'cell_count': 389120, 'byte_count': 794000}}
        with patch.object(self.broker, 'observation_reference', return_value=complete):
            context = self.solver.current_context()
        self.assertEqual(context['observation_ref']['observation_sha256'], complete['observation_sha256'])
        self.assertEqual(context['observation']['animation_ref'], complete['animation_ref'])
        self.assertEqual(len(context['observation']['frame']), 1)

    def test_first_plan_requires_semantic_revision_without_computation(self):
        self.assertEqual(
            self.solver.execute_plan(self.plan((1,)))["status"], "rejected"
        )
        self.assertEqual(self.engine.calls, [])
        self.assertTrue(self.solver.current_context()["needs_revision"])
        self.assertEqual(self.revise()["status"], "revised")
        self.assertEqual(
            [kind for kind, _ in self.events], ["compute_task", "model_revision"]
        )
        declared = self.events[0][1]
        self.assertEqual(
            (declared["origin"], declared["status"], declared["goal"]),
            ("actor", "declared", "移动"),
        )
        self.assertEqual(
            declared["workspace_revision"],
            self.solver.current_context()["workspace_revision"],
        )
        self.assertFalse(self.solver.current_context()["needs_revision"])
        self.assertEqual(self.solver.execute_plan(self.plan((1,)))["applied_count"], 1)

    def test_mismatch_requires_current_evidence_revision_then_next_plan(self):
        self.revise()
        first = self.solver.execute_plan(self.plan((1, 9, 3)))
        self.assertTrue(first["needs_revision"])
        self.assertEqual(first["revision_reason"], "prediction-mismatch")
        next_plan = self.plan((3,))
        next_plan["plan_id"] = "next-plan"
        self.assertEqual(self.solver.execute_plan(next_plan)["status"], "rejected")
        self.assertEqual(self.revise()["status"], "revised")
        next_plan = self.plan((3,))
        next_plan["plan_id"] = "next-plan"
        self.assertEqual(self.solver.execute_plan(next_plan)["applied_count"], 1)

    def test_matched_feedback_reuses_existing_semantic_revision(self):
        self.revise()
        revision = self.solver.current_context()["workspace_revision"]
        first = self.solver.execute_plan(self.plan((1,)))
        self.assertFalse(first["needs_revision"])
        second = self.plan((2,))
        second["plan_id"] = "matched-next"
        result = self.solver.execute_plan(second)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["workspace_revision"], revision)
        self.assertFalse(result["needs_revision"])

    def test_real_reset_requires_one_fresh_semantic_revision(self):
        self.revise()
        self.solver.execute_plan(self.plan((1,)))
        reset = self.plan((2,))
        reset["plan_id"] = "reset-plan"
        reset["steps"][0]["action"]["name"] = "RESET"
        result = self.solver.execute_plan(reset)
        self.assertEqual(result["stop_reason"], "reset-applied")
        self.assertEqual(result["revision_reason"], "reset-applied")
        self.assertTrue(result["needs_revision"])
        self.revise()
        following = self.plan((3,))
        following["plan_id"] = "after-reset"
        self.assertEqual(self.solver.execute_plan(following)["applied_count"], 1)

    def test_empty_or_stale_publish_does_not_open_the_action_gate(self):
        self.revise()
        self.solver.execute_plan(self.plan((1,)))
        for name, mutate in (
            ("stale", lambda value: None),
            (
                "empty-description",
                lambda value: value["worldmap"].update(description_zh=" "),
            ),
            ("empty-goal", lambda value: value["task"].update(goal=" ")),
        ):
            with self.subTest(name=name):
                value = draft()
                if name != "stale":
                    value["evidence_sequences"] = [1]
                mutate(value)
                eid = self.kernel.export(name, value)
                result = self.solver.workspace(
                    {
                        "op": "publish",
                        "base_revision": self.solver.current_context()[
                            "workspace_revision"
                        ],
                        "draft_export_id": eid,
                    }
                )
                self.assertEqual(result["status"], "published")
                self.assertTrue(result["needs_revision"])
                following = self.plan((2,))
                following["plan_id"] = "blocked-" + name
                rejection = self.solver.execute_plan(following)
                self.assertEqual(rejection["reason"], "worldmap-revision-required")
                self.assertEqual(rejection["observation_ref"]["sequence"], 1)
        self.assertEqual(len(self.engine.calls), 1)

    def test_revise_cannot_wash_out_actual_kernel_loss_or_environment_unknown(self):
        self.kernel.lost = True
        self.solver.kernel_recovered()
        self.assertEqual(self.revise()["status"], "revised")
        self.assertTrue(self.solver.current_context()["requires_calibration"])
        self.assertEqual(
            self.solver.execute_plan(self.plan((1,)))["status"], "rejected"
        )
        self.kernel.lost = False
        self.revise()
        self.engine.raises_on = 1
        self.solver.execute_plan(self.plan((1,)))
        self.revise()
        self.assertEqual(
            self.solver.execute_plan(self.plan((1,)))["status"], "rejected"
        )

    def test_mismatch_stops_suffix_and_duplicate_is_idempotent(self):
        self.revise()
        plan = self.plan((1, 9, 3))
        result = self.solver.execute_plan(plan)
        self.assertEqual(result["applied_count"], 2)
        self.assertEqual(result["stop_reason"], "prediction-mismatch")
        self.assertEqual(len(result["unexecuted_steps"]), 1)
        self.assertEqual(result["feedback"][-1]["counterexample_sequence"], 2)
        self.assertEqual(self.solver.execute_plan(plan), result)
        self.assertEqual(len(self.engine.calls), 2)
        plan["goal"] = "different"
        self.assertEqual(self.solver.execute_plan(plan)["status"], "rejected")

    def test_all_predictions_validate_before_first_action(self):
        self.revise()
        plan = self.plan()
        plan["steps"][2]["expect"]["cells"][0]["x"] = 99
        self.assertEqual(self.solver.execute_plan(plan)["status"], "rejected")
        self.assertEqual(self.engine.calls, [])

    def test_stale_start_and_revision_fail_before_action(self):
        self.revise()
        for field in ("start", "workspace_revision"):
            with self.subTest(field=field):
                plan = self.plan()
                if field == "start":
                    plan["start"]["sequence"] = 8
                else:
                    plan[field] = "revision-other"
                self.assertEqual(self.solver.execute_plan(plan)["status"], "rejected")
        self.assertEqual(self.engine.calls, [])

    def test_pause_and_level_advance_stop_suffix(self):
        self.revise()
        original = self.broker.act_checked

        def action(plan):
            result = original(plan)
            self.control.state = "pause_requested"
            return result

        self.broker.act_checked = action
        result = self.solver.execute_plan(self.plan())
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["stop_reason"], "pause_requested")

    def test_multiple_cells_compare_host_evidence(self):
        self.revise()
        plan = self.plan((1, 2))
        plan["steps"][0]["expect"]["cells"].append({"x": 1, "y": 0, "value": 9})
        result = self.solver.execute_plan(plan)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["feedback"][0]["mismatch_kind"], "state")

    def test_unknown_dispatched_result_is_distinct_from_unexecuted_suffix(self):
        self.revise()
        self.engine.raises_on = 2
        plan = self.plan()
        result = self.solver.execute_plan(plan)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["uncertain_step_index"], 1)
        self.assertEqual(len(result["unexecuted_steps"]), 1)
        self.assertEqual(result["stop_reason"], "environment-result-unknown")
        self.assertIsNone(result["feedback"][-1]["actual"])
        self.assertEqual(self.solver.execute_plan(plan), result)
        self.assertEqual(len(self.engine.calls), 2)
        other = self.plan()
        other["plan_id"] = "must-not-retry-unknown"
        self.assertEqual(self.solver.execute_plan(other)["status"], "rejected")

    def test_level_advance_stops_remaining_steps(self):
        self.revise()
        self.engine.level_after = 1
        plan = self.plan()
        plan["steps"][0]["expect"]["levels_completed"] = 1
        result = self.solver.execute_plan(plan)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["stop_reason"], "level-advanced")
        self.assertTrue(result["needs_revision"])
        self.assertEqual(result["revision_reason"], "level-advanced")

    def test_public_calculation_events_pair_by_host_call_id(self):
        payload = {
            "call_id": "one",
            "generation": "generation-1",
            "execution_status": "ok",
            "elapsed_ms": 1,
        }
        self.solver.kernel_event("cell_started", payload)
        self.solver.kernel_event("cell_finished", payload)
        self.solver.kernel_event("cell_started", {**payload, "call_id": "two"})
        rows = [p for kind, p in self.events if kind == "compute_task"]
        self.assertEqual(rows[0]["task_id"], rows[1]["task_id"])
        self.assertNotEqual(rows[1]["task_id"], rows[2]["task_id"])

    def test_animation_projection_preserves_authoritative_ref_and_fits_actor_bridge(
        self,
    ):
        original = self.engine.observe

        def animated():
            value = original()
            value["frame"] = [
                [[len(self.engine.calls)] * 64 for _ in range(64)] for _ in range(24)
            ]
            return value

        self.engine.observe = animated
        self.broker = ArcBroker(engine=self.engine)
        self.broker.bind_history("animation-run")
        solver = Solver(
            broker=self.broker,
            kernel=self.kernel,
            control=self.control,
            workspace_root=Path(self.directory.name),
            run_id="animation-run",
            attempt_id="animation-attempt",
            event_sink=lambda *args: None,
        )
        context = solver.current_context()
        self.assertEqual(len(context["observation"]["frame"]), 1)
        self.assertEqual(
            context["observation_ref"]["observation_sha256"],
            self.broker.observation_reference()["observation_sha256"],
        )
        self.assertLess(len(canonical_bytes(context)), 64 * 1024)

    def test_large_plan_feedback_preserves_suffix_and_marks_projection_omissions(self):
        self.revise()
        plan = self.plan(tuple(range(1, 21)))
        cells = [{"x": x, "y": y, "value": 1} for y in range(2) for x in range(64)]
        for step in plan["steps"]:
            step["expect"]["cells"] = copy.deepcopy(cells)
        result = self.solver.execute_plan(plan)
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(len(result["unexecuted_steps"]), 19)
        self.assertTrue(result["projection_truncated"])
        self.assertEqual(result["unexecuted_steps"][0]["expect_cells_omitted"], 120)
        self.assertLess(len(canonical_bytes(result)), 64 * 1024)

    def test_final_win_keeps_terminal_events_with_valid_last_level(self):
        from tests.test_prime_p7_native_broker import _FullGameEngine
        from asterion.applications.prime.p7.game import P7GameSelection

        self.broker = ArcBroker(
            engine=_FullGameEngine(), game=P7GameSelection("ls20-9607627b", 0, 7)
        )
        self.broker.bind_history("final-run")
        solver = Solver(
            broker=self.broker,
            kernel=self.kernel,
            control=self.control,
            workspace_root=Path(self.directory.name),
            run_id="final-run",
            attempt_id="final-attempt",
            event_sink=lambda kind, payload: self.events.append((kind, payload)),
        )
        for level in range(1, 8):
            self.revise(solver)
            context = solver.current_context()
            result = solver.execute_plan(
                {
                    "plan_id": "level-" + str(level),
                    "start": context["observation_ref"],
                    "workspace_revision": context["workspace_revision"],
                    "goal": "推进",
                    "purpose": "advance",
                    "assumptions": [],
                    "steps": [
                        {
                            "action": {"name": "ACTION1", "data": {}},
                            "expect": {"levels_completed": level},
                        }
                    ],
                }
            )
        self.assertEqual(result["stop_reason"], "win")
        self.assertEqual(result["observation_ref"]["level"], 7)
        self.assertEqual(self.events[-1][1]["level"], 7)

    def test_kernel_recovery_requires_fresh_publication(self):
        plan = self.plan((1,))
        self.solver.kernel_recovered()
        self.assertEqual(self.solver.execute_plan(plan)["status"], "rejected")
        eid = self.kernel.export("draft", draft())
        published = self.solver.workspace(
            {
                "op": "publish",
                "base_revision": self.solver.current_context()["workspace_revision"],
                "draft_export_id": eid,
            }
        )
        self.assertEqual(published["status"], "published")
        self.assertEqual(self.solver.execute_plan(self.plan((1,)))["applied_count"], 1)
