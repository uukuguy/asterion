from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
