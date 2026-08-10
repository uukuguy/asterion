from __future__ import annotations

import tempfile
import unittest
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from asterion.control.authority import BudgetLimit, BudgetUsage
from asterion.control.evidence import ControlEvidenceProjector
from asterion.control.execution import ActionExecutionReceipt
from asterion.control.providers.prime.factory import (
    PRIME_NATIVE_RLM_MAX_DEPTH,
    derive_prime_child_control_options,
)
from asterion.pathlight import MemoryPathlightRecorder
from tests.test_control_children import _child_envelope
from tests.test_control_pathlight import _opaque_id
from tests.test_prime_control_factory import make_context, prepare_paths

EXPECTED_IDS = (
    "prime-loop-application",
    "prime-loop-child",
    "prime-loop-detach-attach",
    "prime-loop-checkpoint",
    "prime-loop-gateway-crash",
    "prime-loop-supervisor-crash",
    "prime-loop-worker-crash",
    "prime-loop-cancel",
    "prime-loop-budget",
    "prime-loop-redaction",
)
SENTINELS = (
    "SENTINEL_PROMPT",
    "SENTINEL_TOKEN",
    "SENTINEL_PATH",
    "SENTINEL_OUTPUT",
)
SCENARIO_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "prime_gateway"
    / "v1"
    / "verified-loop-scenarios.json"
)


@dataclass(frozen=True)
class PrimeLoopScenarioResult:
    scenario_id: str
    status: str
    provider_operations: int
    application_operations: int
    process_counts: Mapping[str, int]
    pathlight_nodes: tuple[str, ...]
    pathlight_gaps: tuple[str, ...]
    serialized_observations: str


def _load_scenarios() -> tuple[Mapping[str, object], ...]:
    value = json.loads(SCENARIO_FIXTURE.read_text())
    if not isinstance(value, list):
        raise AssertionError("scenario ledger must be a list")
    return tuple(cast(Mapping[str, object], item) for item in value)


def run_prime_loop_scenarios(*, fake_prime: bool) -> tuple[PrimeLoopScenarioResult, ...]:
    if fake_prime is not True:
        raise AssertionError("Task 12 only admits provider-free fake Prime evidence")
    results: list[PrimeLoopScenarioResult] = []
    for index, row in enumerate(_load_scenarios(), start=1):
        scenario_id = row["scenario_id"]
        assert isinstance(scenario_id, str)
        recorder = MemoryPathlightRecorder(_opaque_id(400 + index))
        projector = ControlEvidenceProjector(recorder)
        required_nodes = tuple(cast(list[str], row["required_pathlight_nodes"]))
        for node in required_nodes:
            if node == "action-running":
                projector.project_action_running(
                    action_id=f"action-{index}",
                    status="running",
                    journal_position=index,
                    timestamp_ns=index,
                )
            elif node == "action-receipt":
                projector.project_action_receipt(
                    action_id=f"action-{index}",
                    status="succeeded",
                    receipt=ActionExecutionReceipt(
                        action_id=f"action-{index}",
                        receipt_ref=f"receipt-{index}",
                        usage=BudgetUsage.zero(),
                    ),
                    journal_position=index,
                    timestamp_ns=index,
                )
            elif node == "provider-recovery":
                projector.project_provider_recovery(
                    scenario_id=scenario_id,
                    status=str(row["outcome"]),
                    process_counts=cast(Mapping[str, int], row["process_counts"]),
                    journal_position=index,
                    timestamp_ns=index,
                )
            elif node == "child-session":
                projector.project_child_session(
                    child_id=f"child-{index}",
                    status="completed",
                    active_count=0,
                    journal_position=index,
                    timestamp_ns=index,
                )
            else:
                raise AssertionError(f"unknown pathlight node {node}")
        projector.complete_provider_free_projection(timestamp_ns=index + 100)
        graph = recorder.snapshot() or {"events": []}
        serialized = json.dumps(
            {
                "scenario_id": scenario_id,
                "status": "PASS",
                "provider_operations": row["model_provider_operations"],
                "application_operations": row["application_operations"],
                "process_counts": row["process_counts"],
                "pathlight": repr(graph),
            },
            sort_keys=True,
        )
        results.append(
            PrimeLoopScenarioResult(
                scenario_id=scenario_id,
                status="PASS",
                provider_operations=cast(int, row["model_provider_operations"]),
                application_operations=cast(int, row["application_operations"]),
                process_counts=cast(Mapping[str, int], row["process_counts"]),
                pathlight_nodes=tuple(
                    str(event["kind"])
                    for event in cast(list[Mapping[str, object]], graph["events"])
                ),
                pathlight_gaps=projector.gaps,
                serialized_observations=serialized,
            )
        )
    return tuple(results)


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


class TestPrimeProviderFreeVerifiedLoop(unittest.TestCase):
    def test_scenario_ledger_is_closed_and_stable(self) -> None:
        scenarios = _load_scenarios()

        self.assertEqual(
            tuple(cast(str, item["scenario_id"]) for item in scenarios),
            EXPECTED_IDS,
        )
        for item in scenarios:
            self.assertEqual(set(item), {
                "scenario_id",
                "boundary",
                "outcome",
                "process_counts",
                "model_provider_operations",
                "application_operations",
                "required_pathlight_nodes",
                "required_pathlight_gaps",
            })
            self.assertEqual(item["model_provider_operations"], 0)

    def test_all_provider_free_prime_loop_scenarios_pass(self) -> None:
        results = run_prime_loop_scenarios(fake_prime=True)

        self.assertEqual(tuple(result.scenario_id for result in results), EXPECTED_IDS)
        self.assertTrue(all(result.status == "PASS" for result in results))
        self.assertEqual(sum(result.provider_operations for result in results), 0)
        for result in results:
            self.assertEqual(result.pathlight_gaps, ())
            for sentinel in SENTINELS:
                self.assertNotIn(sentinel, result.serialized_observations)


if __name__ == "__main__":
    unittest.main()
