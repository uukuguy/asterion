from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import cast
from unittest.mock import patch

from asterion.capabilities.dci.implementation.config import (
    DciPaths,
    DciPiPaths,
    DciRuntimeOptions,
)
from asterion.capabilities.dci.implementation.evaluation.artifacts import (
    DciRunRecorder,
)
from asterion.capabilities.dci.implementation.evaluation.benchmark import (
    BenchmarkRequest,
    DciBenchmarkError,
    _prepare,
)
from asterion.capabilities.dci.implementation.evaluation.judge import JudgeConfig
from asterion.capabilities.dci.implementation.runtime.run import DciRunRequest
from asterion.pathlight import (
    DashboardSnapshot,
    map_opik_exports,
    trace_graph_from_mapping,
)
from asterion.workflow_evidence import read_workflow_observation_bundle

from asterion.capabilities.dci.implementation.research.query_planning import (
    BASELINE_QUERY_PLAN,
    DECOMPOSED_QUERY_PLAN,
    QueryPlanningContract,
    QueryPlanningError,
    materialize_query_planning_prompt,
    query_planning_contract_sha256,
    resolve_query_planning_contract,
    validate_materialized_query_planning_prompt,
)


class QueryPlanningContractTests(unittest.TestCase):
    def test_candidate_contract_is_exact_and_public_identity_is_body_free(self) -> None:
        baseline = resolve_query_planning_contract(BASELINE_QUERY_PLAN)
        candidate = resolve_query_planning_contract(DECOMPOSED_QUERY_PLAN)

        self.assertNotEqual(
            query_planning_contract_sha256(baseline),
            query_planning_contract_sha256(candidate),
        )
        public = candidate.public_identity()
        self.assertEqual(set(public), {"contract_id", "contract_sha256"})
        self.assertNotIn("SENTINEL_PROMPT_BODY", json.dumps(public))
        self.assertNotIn(candidate._append_system_prompt, json.dumps(public))

    def test_candidate_encodes_the_pre_registered_local_query_plan(self) -> None:
        candidate = resolve_query_planning_contract(DECOMPOSED_QUERY_PLAN)
        body = candidate._append_system_prompt.lower()

        for required in (
            "entities",
            "concepts",
            "relationships",
            "constraints",
            "complementary subqueries",
            "separate search round",
            "merge",
            "deduplicate",
            "validate",
            "rerank",
            "maximum 20",
        ):
            with self.subTest(required=required):
                self.assertIn(required, body)
        self.assertIn("do not use web", body)
        self.assertIn("do not spawn subagents", body)

    def test_unknown_or_forged_contract_is_rejected(self) -> None:
        with self.assertRaises(QueryPlanningError):
            resolve_query_planning_contract("dci.query-plan/unknown/v1")
        forged = QueryPlanningContract(
            contract_id=DECOMPOSED_QUERY_PLAN,
            _append_system_prompt="SENTINEL_PROMPT_BODY",
        )
        with self.assertRaises(QueryPlanningError):
            query_planning_contract_sha256(forged)


class QueryPlanningPromptMaterializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        os.chmod(self.root, 0o700)

    def test_private_candidate_prompt_requires_0700_root_and_writes_0400(self) -> None:
        path = materialize_query_planning_prompt(DECOMPOSED_QUERY_PLAN, self.root)

        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400)
        self.assertEqual(path.parent, self.root)
        self.assertIn(query_planning_contract_sha256(resolve_query_planning_contract(DECOMPOSED_QUERY_PLAN)), path.name)
        validate_materialized_query_planning_prompt(DECOMPOSED_QUERY_PLAN, path)

    def test_materialization_is_idempotent_but_conflicts_fail_closed(self) -> None:
        first = materialize_query_planning_prompt(DECOMPOSED_QUERY_PLAN, self.root)
        self.assertEqual(
            materialize_query_planning_prompt(DECOMPOSED_QUERY_PLAN, self.root), first
        )
        os.chmod(first, 0o600)
        first.write_text("SENTINEL_PROMPT_BODY", encoding="utf-8")
        os.chmod(first, 0o400)
        with self.assertRaises(QueryPlanningError):
            materialize_query_planning_prompt(DECOMPOSED_QUERY_PLAN, self.root)

    def test_materialization_rejects_unsafe_root_and_target_forms(self) -> None:
        for mode in (0o755, 0o600):
            with self.subTest(mode=oct(mode)):
                os.chmod(self.root, mode)
                with self.assertRaises(QueryPlanningError):
                    materialize_query_planning_prompt(DECOMPOSED_QUERY_PLAN, self.root)
                os.chmod(self.root, 0o700)

        destination = self.root / (
            "query-planning-"
            + query_planning_contract_sha256(
                resolve_query_planning_contract(DECOMPOSED_QUERY_PLAN)
            )
            + ".txt"
        )
        try:
            destination.symlink_to(self.root / "elsewhere")
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        with self.assertRaises(QueryPlanningError):
            materialize_query_planning_prompt(DECOMPOSED_QUERY_PLAN, self.root)

    def test_materialization_rejects_unowned_root(self) -> None:
        with patch(
            "asterion.capabilities.dci.implementation.research.query_planning.os.geteuid",
            return_value=os.geteuid() + 1,
        ):
            with self.assertRaises(QueryPlanningError):
                materialize_query_planning_prompt(DECOMPOSED_QUERY_PLAN, self.root)

    def test_validation_rejects_replaced_public_or_non_regular_file(self) -> None:
        path = materialize_query_planning_prompt(DECOMPOSED_QUERY_PLAN, self.root)
        os.chmod(path, 0o600)
        with self.assertRaises(QueryPlanningError):
            validate_materialized_query_planning_prompt(DECOMPOSED_QUERY_PLAN, path)

        os.chmod(path, 0o400)
        path.unlink()
        try:
            os.mkfifo(path, 0o400)
        except OSError as error:
            self.skipTest(f"FIFOs unavailable: {error}")
        with self.assertRaises(QueryPlanningError):
            validate_materialized_query_planning_prompt(DECOMPOSED_QUERY_PLAN, path)

    def test_baseline_never_materializes_an_override(self) -> None:
        with self.assertRaises(QueryPlanningError):
            materialize_query_planning_prompt(BASELINE_QUERY_PLAN, self.root)


class QueryPlanningPublicEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.root.chmod(0o700)
        self.dataset = self.root / "dataset.jsonl"
        self.dataset.write_text(
            '{"query_id":"q-1","query":"SENTINEL_QUESTION","gold_docs":["a.txt"]}\n',
            encoding="utf-8",
        )
        private_root = self.root / "SENTINEL_PRIVATE_PROMPT_ROOT"
        private_root.mkdir(mode=0o700)
        private_root.chmod(0o700)
        self.prompt = materialize_query_planning_prompt(
            DECOMPOSED_QUERY_PLAN, private_root
        )
        self.contract = resolve_query_planning_contract(DECOMPOSED_QUERY_PLAN)

    def _request(self, identity: object) -> BenchmarkRequest:
        return BenchmarkRequest(
            dataset=self.dataset,
            output_root=self.root / "output",
            cwd=self.root,
            judge_config=JudgeConfig(),
            runtime_options=DciRuntimeOptions(provider=None, model=None),
            mode="ir",
            append_system_prompt_file=self.prompt,
            query_planning_identity=cast(Mapping[str, str] | None, identity),
        )

    def test_candidate_batch_and_row_identity_only_publish_query_contract(self) -> None:
        _rows, _output, config, items, _snapshots = _prepare(
            self._request(self.contract.public_identity())
        )

        public = json.dumps({"config": config, "items": items}, sort_keys=True)
        self.assertNotIn(self.contract._append_system_prompt, public)
        self.assertNotIn("SENTINEL_PRIVATE_PROMPT_ROOT", public)
        expected = self.contract.public_identity()
        prompt_resources = cast(dict[str, object], config["prompt_resources"])
        item_identity = cast(dict[str, object], items[0]["identity"])
        self.assertEqual(
            prompt_resources["append_system_prompt_file"], expected
        )
        self.assertEqual(
            item_identity["prompt_resources"],
            config["prompt_resources"],
        )
        self.assertEqual(
            item_identity["query_planning"],
            expected,
        )

    def test_missing_or_mismatched_candidate_identity_fails_closed(self) -> None:
        for identity in (
            None,
            {
                "contract_id": DECOMPOSED_QUERY_PLAN,
                "contract_sha256": "0" * 64,
            },
            resolve_query_planning_contract(BASELINE_QUERY_PLAN).public_identity(),
        ):
            with self.subTest(identity=identity), self.assertRaises(DciBenchmarkError):
                _prepare(self._request(identity))

    def test_candidate_public_conversation_excludes_private_prompt_body_and_path(self) -> None:
        pi_root = self.root / "pi"
        package_dir = pi_root / "package"
        agent_dir = pi_root / "agent"
        package_dir.mkdir(parents=True)
        agent_dir.mkdir()
        paths = DciPaths(
            repo_root=self.root,
            pi=DciPiPaths(
                repo_dir=pi_root,
                package_dir=package_dir,
                agent_dir=agent_dir,
            ),
            output_root=self.root,
        )
        output_dir = self.root / "run"
        recorder = DciRunRecorder(
            output_dir=output_dir,
            paths=paths,
            request=DciRunRequest(
                run_id="candidate-public-evidence",
                question="SENTINEL_QUESTION",
                cwd=self.root,
                tools="read",
                append_system_prompt_file=self.prompt,
                query_planning_identity=self.contract.public_identity(),
            ),
        )
        self.addCleanup(recorder.close)

        full = json.loads(
            (output_dir / "conversation_full.json").read_text(encoding="utf-8")
        )
        public = (output_dir / "conversation.json").read_text(encoding="utf-8")

        self.assertEqual(
            full["messages"][0]["content"][0]["text"],
            self.contract._append_system_prompt.rstrip(),
        )
        self.assertIn("SENTINEL_PRIVATE_PROMPT_ROOT", str(full))
        self.assertNotIn("BRIGHT QUERY-PLANNING VARIANT", public)
        self.assertNotIn("SENTINEL_PRIVATE_PROMPT_ROOT", public)

        events: tuple[dict[str, object], ...] = (
            {"type": "agent_start"},
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "answer"}],
                    "stopReason": "stop",
                    "usage": {"input": 1, "output": 1},
                },
            },
            {"type": "agent_end"},
        )
        for event in events:
            recorder.record_event(event)
        recorder.finalize(status="completed", final_text="answer", release_lock=False)
        recorder.persist_workflow_evidence()
        workflow_path = output_dir / "workflow-evidence.json"
        workflow_document = json.loads(workflow_path.read_text(encoding="utf-8"))
        workflow = read_workflow_observation_bundle(workflow_path)
        trace = trace_graph_from_mapping(workflow_document["pathlight_traces"][0])
        opik = map_opik_exports(traces=(trace,))
        dashboard = DashboardSnapshot.build(workflow_bundles=(workflow,))

        for projection in (
            workflow_path.read_text(encoding="utf-8"),
            json.dumps([item.to_mapping() for item in opik], sort_keys=True),
            json.dumps(dashboard.to_mapping(), sort_keys=True),
        ):
            with self.subTest(projection=projection[:20]):
                self.assertNotIn("BRIGHT QUERY-PLANNING VARIANT", projection)
                self.assertNotIn("SENTINEL_PRIVATE_PROMPT_ROOT", projection)


if __name__ == "__main__":
    unittest.main()
