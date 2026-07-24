from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from importlib import resources
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from unittest.mock import Mock, patch

from asterion.dci.benchmark import (
    BenchmarkRequest,
    DciBenchmarkError,
    _prepare,
    run_benchmark,
)
from asterion.dci.cli import main as dci_main
from asterion.dci.config import DciRuntimeOptions, resolve_dci_paths
from asterion.dci.experiment_profiles import (
    experiment_profile_ids,
    experiment_profile_schema_sha256,
    experiment_profiles_sha256,
    resolve_experiment_profile,
)
from asterion.dci.judge import JudgeConfig
from asterion.dci.paper_benchmarks import canonical_sha256
from asterion.dci.pi_rpc import FINAL_ANSWER_RECOVERY_PROMPT
from asterion.dci.prompts import (
    PROMPT_CONTRACTS,
    PromptContractError,
    prompt_contract_sha256,
    resolve_prompt_contract,
)
from asterion.dci.provenance import (
    DCI_COMPLETE_IMPLEMENTATION_RESOURCES,
    dci_complete_implementation_identity,
)
from asterion.dci.run import DciRunResult, run_pi_research as _real_run_pi_research
from asterion.runtime.host import RunEvent


class _FixtureClient:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass

    def prompt_and_wait(self, _message: str, *, on_event, **_kwargs: object) -> str:
        for event in (
            {"type": "response", "id": "py-1", "success": True},
            {"type": "agent_start"},
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": "answer"},
            },
            {"type": "agent_end"},
        ):
            on_event(event)
        return "answer"

    def get_stderr(self) -> str:
        return ""

    def stop(self) -> None:
        pass


def _recorded_run(_paths: object, request: object, **kwargs: object) -> DciRunResult:
    with patch("asterion.dci.run.PiRpcClient", _FixtureClient):
        return _real_run_pi_research(
            resolve_dci_paths(Path(request.cwd)), request, **kwargs
        )


class AsterionDciBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        from asterion.dci import experiment_profiles

        experiment_profiles._profiles.cache_clear()
        self.addCleanup(experiment_profiles._profiles.cache_clear)

    def test_prompt_contracts_match_source_family_golden_fixtures(self) -> None:
        fixture_root = Path(__file__).parent / "fixtures" / "dci_prompts"
        corpus = Path("/__dci_prompt_contract_corpus__")
        query = "__DCI_QUERY__"
        hint = "__DCI_CORPUS_HINT__"
        cases = (
            (
                "dci.paper-prompt/arxiv:2605.05242v1/v1",
                "paper-reference",
                "qa",
                "paper-qa.txt",
                "11466c7e3ce009558cfc23a3c2c6a4f7abb050164de9504e259c7da52fc331f5",
                lambda contract: contract.qa_builder(query, corpus),
            ),
            (
                "dci.upstream-github-prompt/271f37e71f053bf0c99c05ce6d2fb53b841d922e/v1",
                "upstream-github",
                "qa",
                "upstream-github-qa.txt",
                "e6b71b71aeb62fe43f097efe1a207ebe4ad0114d919460c574475e001823991e",
                lambda contract: contract.qa_builder(query, corpus),
            ),
            (
                "dci.upstream-github-prompt/271f37e71f053bf0c99c05ce6d2fb53b841d922e/v1",
                "upstream-github",
                "ir",
                "upstream-github-ir.txt",
                "24b6db054787487eec7286f6b20f416acbcafba8ba45cacc50d1dc4a4231a78c",
                lambda contract: contract.ir_builder(query, corpus, hint),
            ),
            (
                "asterion.dci.prompt/safe/v1",
                "asterion-safe",
                "qa",
                "asterion-safe-qa.txt",
                None,
                lambda contract: contract.qa_builder(query, corpus),
            ),
        )
        qa_hashes: set[str] = set()
        for contract_id, source_family, kind, fixture_name, body_sha256, build in cases:
            with self.subTest(contract=contract_id, kind=kind):
                contract = resolve_prompt_contract(contract_id)
                body = build(contract)
                fixture = (fixture_root / fixture_name).read_text(encoding="utf-8")
                self.assertEqual(contract.source_family, source_family)
                self.assertEqual(body, fixture)
                if body_sha256 is not None:
                    self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), body_sha256)
                self.assertEqual(
                    prompt_contract_sha256(contract, kind),
                    canonical_sha256(
                        {
                            "source_family": source_family,
                            "prompt_kind": kind,
                            "body": fixture,
                        }
                    ),
                )
                if kind == "qa":
                    qa_hashes.add(prompt_contract_sha256(contract, kind))
        self.assertEqual(len(qa_hashes), 3)

    def test_prompt_contract_selection_fails_closed_without_body_disclosure(self) -> None:
        query = "SENTINEL-PRIVATE-QUESTION"
        path = Path("/SENTINEL-PRIVATE-PATH")
        with self.assertRaises(PromptContractError) as raised:
            resolve_prompt_contract("unreported-contract")
        self.assertNotIn(query, str(raised.exception))
        self.assertNotIn(str(path), str(raised.exception))
        paper = resolve_prompt_contract("dci.paper-prompt/arxiv:2605.05242v1/v1")
        with self.assertRaises(PromptContractError) as raised:
            paper.ir_builder(query, path, None)
        self.assertNotIn(query, str(raised.exception))
        self.assertNotIn(str(path), str(raised.exception))
        self.assertEqual(
            set(PROMPT_CONTRACTS),
            {
                "asterion.dci.prompt/safe/v1",
                "dci.paper-prompt/arxiv:2605.05242v1/v1",
                "dci.upstream-github-prompt/271f37e71f053bf0c99c05ce6d2fb53b841d922e/v1",
            },
        )

    def test_benchmark_binds_the_profile_selected_prompt_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            request = replace(
                _request(root),
                profile="asterion-safe/pi",
                corpus=corpus,
            )
            _rows, _output, config, items, _snapshots = _prepare(request)

        contract = resolve_prompt_contract("asterion.dci.prompt/safe/v1")
        expected_sha256 = prompt_contract_sha256(contract, "qa")
        self.assertEqual(config["benchmark_prompt_contract"], contract.contract_id)
        self.assertEqual(config["benchmark_prompt_contract_sha256"], expected_sha256)
        self.assertEqual(items[0]["identity"]["benchmark_prompt_contract"], contract.contract_id)
        self.assertEqual(
            items[0]["identity"]["benchmark_prompt_contract_sha256"],
            expected_sha256,
        )

    def test_benchmark_uses_minimax_invocation_identity_for_profile_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            request = replace(
                _request(root),
                profile="asterion-safe/claude-minimax",
                corpus=corpus,
                runtime_options=DciRuntimeOptions(
                    provider="minimax", model="MiniMax-M2.7"
                ),
            )
            _rows, _output, config, _items, _snapshots = _prepare(request)

        self.assertEqual(
            config["benchmark_prompt_contract"], "asterion.dci.prompt/safe/v1"
        )

    def test_benchmark_rejects_unreported_paper_ir_before_agent_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            corpus = root / "corpus"
            corpus.mkdir()
            dataset = root / "dataset.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "query_id": "q-1",
                        "query": "SENTINEL-PRIVATE-QUESTION",
                        "gold_ids": ["doc.txt"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            request = BenchmarkRequest(
                dataset=dataset,
                output_root=root / "out",
                cwd=root,
                judge_config=JudgeConfig(base_url="https://judge.example.test/v1"),
                runtime_options=DciRuntimeOptions(provider=None, model=None),
                profile="paper-reference/pi",
                corpus=corpus,
                mode="ir",
                limit=1,
            )
            with patch(
                "asterion.dci.benchmark.paper_scope_for_profile", return_value=None
            ), patch("asterion.dci.benchmark.run_pi_research") as run:
                with self.assertRaisesRegex(DciBenchmarkError, "prompt contract") as raised:
                    run_benchmark(request, paths=Mock())

        self.assertNotIn("SENTINEL-PRIVATE-QUESTION", str(raised.exception))
        self.assertNotIn(str(corpus), str(raised.exception))
        run.assert_not_called()

    def test_benchmark_passes_only_the_selected_contract_recovery_to_runs(self) -> None:
        for profile_id, expected_recovery in (
            ("asterion-safe/pi", FINAL_ANSWER_RECOVERY_PROMPT),
            (
                "upstream-github/271f37e71f053bf0c99c05ce6d2fb53b841d922e/pi",
                None,
            ),
        ):
            with self.subTest(profile=profile_id), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory).resolve()
                corpus = root / "corpus"
                corpus.mkdir()
                request = replace(_request(root), profile=profile_id, corpus=corpus)
                captured: list[object] = []

                def recorded(paths: object, native_request: object, **kwargs: object) -> DciRunResult:
                    captured.append(native_request)
                    return _recorded_run(paths, native_request, **kwargs)

                with patch(
                    "asterion.dci.benchmark.run_pi_research", side_effect=recorded
                ), patch(
                    "asterion.dci.evaluation.judge_answer_sync",
                    return_value=_verdict(request.judge_config),
                ):
                    run_benchmark(request, paths=Mock())

                self.assertEqual(len(captured), 1)
                self.assertEqual(
                    captured[0].final_answer_recovery,
                    expected_recovery,
                )

    def test_experiment_profiles_separate_three_provenance_families(self) -> None:
        commit = "271f37e71f053bf0c99c05ce6d2fb53b841d922e"
        self.assertEqual(
            experiment_profile_ids(),
            (
                "asterion-safe/pi",
                "asterion-safe/claude-subscription",
                "asterion-safe/claude-minimax",
                "paper-reference/pi",
                "paper-reference/claude-code",
                f"upstream-github/{commit}/pi",
            ),
        )
        paper = resolve_experiment_profile("paper-reference/pi")
        upstream = resolve_experiment_profile(f"upstream-github/{commit}/pi")
        safe = resolve_experiment_profile("asterion-safe/pi")

        self.assertEqual(paper.source_family, "paper-reference")
        self.assertEqual(paper.source_identity, "arxiv:2605.05242v1")
        self.assertIsNone(paper.compatible_config_key)
        self.assertEqual(
            dict(upstream.source_identity),
            {
                "repository": "DCI-Agent/DCI-Agent-Lite",
                "commit": commit,
            },
        )
        self.assertEqual(safe.source_family, "asterion-safe")
        self.assertEqual(
            safe.source_identity, dci_complete_implementation_identity()
        )
        self.assertEqual(
            {
                paper.implementation_sha256,
                upstream.implementation_sha256,
                safe.implementation_sha256,
            },
            {dci_complete_implementation_identity()},
        )
        self.assertNotEqual(paper.identity_sha256, upstream.identity_sha256)
        self.assertNotEqual(upstream.identity_sha256, safe.identity_sha256)
        self.assertNotEqual(paper.prompt_contract, upstream.prompt_contract)
        self.assertNotEqual(upstream.judge_contract, safe.judge_contract)
        self.assertNotEqual(paper.metric_contracts, safe.metric_contracts)
        self.assertNotEqual(paper.runtime_contract, safe.runtime_contract)
        self.assertNotEqual(paper.context_contract, upstream.context_contract)
        self.assertNotEqual(
            upstream.dataset_selection_contract,
            safe.dataset_selection_contract,
        )
        self.assertIsInstance(paper.paper_unreported_parameters, MappingProxyType)
        with self.assertRaises(TypeError):
            paper.paper_unreported_parameters["unknown"] = "paper-unreported"
        with self.assertRaises(TypeError):
            upstream.source_identity["commit"] = "0" * 40
        self.assertNotIn("prompt_body", json.dumps(paper.to_canonical_dict()))

    def test_profile_resources_use_resolved_non_recursive_implementation_binding(
        self,
    ) -> None:
        from asterion.dci import experiment_profiles

        package = resources.files("asterion.dci.resources")
        schema = json.loads(
            package.joinpath("experiment-profile.schema.json").read_text()
        )
        payload = json.loads(
            package.joinpath("experiment-profiles.json").read_text()
        )
        raw_text = json.dumps(payload, sort_keys=True)

        self.assertEqual(
            experiment_profile_schema_sha256(),
            canonical_sha256(schema),
        )
        self.assertNotIn("implementation_sha256", raw_text)
        self.assertNotIn(dci_complete_implementation_identity(), raw_text)
        self.assertTrue(
            all(
                isinstance(item["implementation_contract"], str)
                for item in payload["profiles"]
            )
        )
        commit = "271f37e71f053bf0c99c05ce6d2fb53b841d922e"
        upstream = next(
            item
            for item in payload["profiles"]
            if item["profile_id"] == f"upstream-github/{commit}/pi"
        )
        self.assertEqual(
            upstream["judge"]["request_shape_sha256"],
            canonical_sha256(
                {
                    "api": "responses",
                    "reasoning_effort": "low",
                    "text_verbosity": "low",
                    "max_output_tokens": 180,
                    "output_keys": [
                        "is_correct",
                        "normalized_prediction",
                        "reason",
                    ],
                }
            ),
        )
        self.assertEqual(
            upstream["judge"]["prompt_contract_sha256"],
            canonical_sha256(
                {
                    "contract": f"dci.upstream-answer-judge/{commit}/v1",
                    "source_identity": {
                        "repository": "DCI-Agent/DCI-Agent-Lite",
                        "commit": commit,
                    },
                }
            ),
        )
        expected_profiles_sha256 = canonical_sha256(
            {
                "schema": "dci.experiment-profiles/v1",
                "profiles": [
                    {
                        "profile_id": profile_id,
                        "identity_sha256": experiment_profiles._profiles()[
                            profile_id
                        ].identity_sha256,
                    }
                    for profile_id in experiment_profile_ids()
                ],
            }
        )
        self.assertEqual(experiment_profiles_sha256(), expected_profiles_sha256)

    def test_profile_identity_tracks_exact_implementation_resource_mutation(
        self,
    ) -> None:
        resources_by_name = {
            name: resources.files("asterion").joinpath(name).read_bytes()
            for name in DCI_COMPLETE_IMPLEMENTATION_RESOURCES
        }
        baseline_implementation = dci_complete_implementation_identity(
            resource_reader=resources_by_name.__getitem__
        )
        profile_resource = "dci/resources/experiment-profiles.json"
        resources_by_name[profile_resource] += b"\n"
        changed_implementation = dci_complete_implementation_identity(
            resource_reader=resources_by_name.__getitem__
        )
        self.assertNotEqual(baseline_implementation, changed_implementation)

        from asterion.dci import experiment_profiles

        with patch.object(
            experiment_profiles,
            "dci_complete_implementation_identity",
            return_value=baseline_implementation,
        ):
            experiment_profiles._profiles.cache_clear()
            baseline_profile = resolve_experiment_profile("asterion-safe/pi")
        with patch.object(
            experiment_profiles,
            "dci_complete_implementation_identity",
            return_value=changed_implementation,
        ):
            experiment_profiles._profiles.cache_clear()
            changed_profile = resolve_experiment_profile("asterion-safe/pi")

        self.assertEqual(
            baseline_profile.implementation_sha256, baseline_implementation
        )
        self.assertEqual(
            changed_profile.implementation_sha256, changed_implementation
        )
        self.assertNotEqual(
            baseline_profile.identity_sha256, changed_profile.identity_sha256
        )

    def test_profile_contract_rejects_cross_family_and_unknown_semantics(
        self,
    ) -> None:
        commit = "271f37e71f053bf0c99c05ce6d2fb53b841d922e"
        mutations = (
            (
                "paper-mixed-github-prompt",
                "paper-reference/pi",
                lambda item: item.__setitem__(
                    "prompt_contract",
                    f"dci.upstream-github-prompt/{commit}/v1",
                ),
            ),
            (
                "paper-mixed-asterion-judge",
                "paper-reference/pi",
                lambda item: item.__setitem__(
                    "judge_contract",
                    "asterion.dci.answer-judge/strict-json/v1",
                ),
            ),
            (
                "paper-mixed-asterion-metric",
                "paper-reference/pi",
                lambda item: item.__setitem__(
                    "metric_contracts",
                    [
                        "asterion.dci.answer-correctness/strict-json/v1",
                        "ndcg@10-binary-deduplicated/v1",
                    ],
                ),
            ),
            (
                "upstream-noncanonical-commit",
                f"upstream-github/{commit}/pi",
                lambda item: item["source_identity"].__setitem__(
                    "commit", commit.upper()
                ),
            ),
            (
                "safe-published-target",
                "asterion-safe/pi",
                lambda item: item["comparison"].__setitem__(
                    "published_target", "DCI-Agent-Lite"
                ),
            ),
            (
                "unknown-paper-unreported-parameter",
                "paper-reference/pi",
                lambda item: item["paper_unreported_parameters"].__setitem__(
                    "unknown", "paper-unreported"
                ),
            ),
        )
        for label, profile_id, mutate in mutations:
            with self.subTest(label=label):
                self._assert_invalid_profile_mutation(profile_id, mutate)

    def test_current_default_alias_is_cli_only_and_never_enters_evidence(
        self,
    ) -> None:
        aliases = (
            ("current-default/pi", "asterion-safe/pi", ()),
            (
                "current-default/claude-subscription",
                "asterion-safe/claude-subscription",
                (),
            ),
            (
                "current-default/claude-minimax",
                "asterion-safe/claude-minimax",
                ("--provider", "minimax", "--model", "minimax-test"),
            ),
        )
        for alias, canonical, invocation in aliases:
            with self.subTest(alias=alias):
                with self.assertRaisesRegex(
                    ValueError, "^DCI experiment profile is invalid$"
                ):
                    resolve_experiment_profile(alias)
                with tempfile.TemporaryDirectory() as temporary_directory:
                    stdout = __import__("io").StringIO()
                    stderr = __import__("io").StringIO()
                    code = dci_main(
                        [
                            "paper",
                            "reproduce",
                            "--profile",
                            alias,
                            "--output-root",
                            str(Path(temporary_directory) / "out"),
                            "--estimated-budget-usd",
                            "1",
                            "--dry-run",
                            *invocation,
                        ],
                        stdout=stdout,
                        stderr=stderr,
                    )
                self.assertEqual(code, 0, stderr.getvalue())
                self.assertIn(f"Profile: {canonical}", stdout.getvalue())
                self.assertNotIn("current-default", stdout.getvalue())

        from asterion.dci.verification import paper_product_contract

        canonical_evidence = json.dumps(
            paper_product_contract(), sort_keys=True
        )
        self.assertNotIn("current-default", canonical_evidence)
        self.assertIn("asterion-safe/pi", canonical_evidence)

    def _assert_invalid_profile_mutation(self, profile_id, mutate) -> None:
        from asterion.dci import experiment_profiles

        package = resources.files("asterion.dci.resources")
        payload = json.loads(
            package.joinpath("experiment-profiles.json").read_text()
        )
        schema = json.loads(
            package.joinpath("experiment-profile.schema.json").read_text()
        )
        item = next(
            item for item in payload["profiles"] if item["profile_id"] == profile_id
        )
        mutate(item)
        with patch.object(
            experiment_profiles,
            "_read_profile_resources",
            return_value=(payload, schema),
        ):
            experiment_profiles._profiles.cache_clear()
            with self.assertRaisesRegex(
                RuntimeError,
                "^DCI experiment profile contract is invalid$",
            ):
                experiment_profiles.experiment_profile_ids()

    def test_batch_evidence_exports_transitive_implementation_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            with patch(
                "asterion.dci.benchmark.run_pi_research", side_effect=_recorded_run
            ), patch(
                "asterion.dci.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                run_benchmark(request, paths=Mock())

            config = json.loads((request.output_root / "config.json").read_text())
            item = json.loads(
                (request.output_root / "q-1/item.json").read_text()
            )
            result = json.loads(
                (request.output_root / "q-1/result.json").read_text()
            )
            summary = json.loads(
                (request.output_root / "summary.json").read_text()
            )
            analysis = json.loads(
                (request.output_root / "analysis.json").read_text()
            )

        expected = dci_complete_implementation_identity()
        self.assertEqual(config["implementation_sha256"], expected)
        self.assertEqual(item["implementation_sha256"], expected)
        self.assertEqual(item["identity"]["implementation_sha256"], expected)
        self.assertEqual(result["implementation_sha256"], expected)
        self.assertEqual(summary["provenance"]["implementation_sha256"], expected)
        self.assertEqual(analysis["provenance"]["implementation_sha256"], expected)

    def test_changed_or_missing_implementation_identity_rejects_before_execution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            resources = {
                name: name.encode()
                for name in DCI_COMPLETE_IMPLEMENTATION_RESOURCES
            }
            first_identity = dci_complete_implementation_identity(
                resource_reader=resources.__getitem__
            )
            resources["dci/artifacts.py"] += b"\x00"
            second_identity = dci_complete_implementation_identity(
                resource_reader=resources.__getitem__
            )
            self.assertNotEqual(first_identity, second_identity)
            with patch(
                "asterion.dci.benchmark.dci_complete_implementation_identity",
                return_value=first_identity,
            ), patch(
                "asterion.dci.benchmark.run_pi_research", side_effect=_recorded_run
            ), patch(
                "asterion.dci.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                run_benchmark(request, paths=Mock())

            with patch(
                "asterion.dci.benchmark.dci_complete_implementation_identity",
                return_value=second_identity,
            ), patch("asterion.dci.benchmark.run_pi_research") as run, patch(
                "asterion.dci.benchmark.evaluate_run_directory_async"
            ) as evaluate:
                with self.assertRaisesRegex(
                    DciBenchmarkError, "configuration is incompatible"
                ):
                    run_benchmark(request, paths=Mock())
            run.assert_not_called()
            evaluate.assert_not_called()

            config_path = request.output_root / "config.json"
            config = json.loads(config_path.read_text())
            valid_config = dict(config)
            config.pop("implementation_sha256")
            config_path.write_text(json.dumps(config))
            with patch(
                "asterion.dci.benchmark.dci_complete_implementation_identity",
                return_value=first_identity,
            ), patch("asterion.dci.benchmark.run_pi_research") as run, patch(
                "asterion.dci.benchmark.evaluate_run_directory_async"
            ) as evaluate:
                with self.assertRaisesRegex(
                    DciBenchmarkError, "configuration evidence is invalid"
                ):
                    run_benchmark(request, paths=Mock())
            run.assert_not_called()
            evaluate.assert_not_called()

            config_path.write_text(json.dumps(valid_config))
            item_path = request.output_root / "q-1/item.json"
            item = json.loads(item_path.read_text())
            valid_item = dict(item)
            item.pop("implementation_sha256")
            item_path.write_text(json.dumps(item))
            with patch(
                "asterion.dci.benchmark.dci_complete_implementation_identity",
                return_value=first_identity,
            ), patch("asterion.dci.benchmark.run_pi_research") as run, patch(
                "asterion.dci.benchmark.evaluate_run_directory_async"
            ) as evaluate:
                with self.assertRaisesRegex(
                    DciBenchmarkError, "item evidence is invalid"
                ):
                    run_benchmark(request, paths=Mock())
            run.assert_not_called()
            evaluate.assert_not_called()

            item_path.write_text(json.dumps(valid_item))
            result_path = request.output_root / "q-1/result.json"
            result = json.loads(result_path.read_text())
            result.pop("implementation_sha256")
            result_path.write_text(json.dumps(result))
            with patch(
                "asterion.dci.benchmark.dci_complete_implementation_identity",
                return_value=first_identity,
            ), patch("asterion.dci.benchmark.run_pi_research") as run, patch(
                "asterion.dci.benchmark.evaluate_run_directory_async"
            ) as evaluate:
                with self.assertRaisesRegex(
                    DciBenchmarkError, "result evidence is invalid"
                ):
                    run_benchmark(request, paths=Mock())
            run.assert_not_called()
            evaluate.assert_not_called()

    def test_persisted_batch_judge_identity_is_prompt_and_request_shape_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            with patch("asterion.dci.run.PiRpcClient", _FixtureClient), patch(
                "asterion.dci.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                run_benchmark(request, paths=resolve_dci_paths(root))

            config = json.loads((request.output_root / "config.json").read_text())

        self.assertRegex(
            config["judge"]["request_shape_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertRegex(
            config["judge"]["prompt_contract_sha256"], r"^[0-9a-f]{64}$"
        )

    def test_limit_slices_sorted_rows_and_rejects_zero(self) -> None:
        """Compatibility evidence name retained for the closed AF-220 climb case."""

        self.test_limit_slices_source_order_rows_and_rejects_zero()

    def test_batch_uses_its_runtime_options_for_every_native_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            dataset = root / "dataset.jsonl"
            dataset.write_text(
                "\n".join(
                    (
                        json.dumps({"query_id": "q-2", "query": "two", "answer": "two"}),
                        json.dumps({"query_id": "q-1", "query": "one", "answer": "one"}),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            request = BenchmarkRequest(
                dataset=dataset,
                output_root=root / "out",
                cwd=root,
                judge_config=JudgeConfig(base_url="https://judge.example.test/v1"),
                runtime_options=DciRuntimeOptions(provider="openai", model="gpt-test"),
            )
            with patch(
                "asterion.dci.benchmark.run_pi_research", side_effect=_recorded_run
            ) as run, patch(
                "asterion.dci.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                    run_benchmark(request, paths=Mock())

        self.assertEqual([call.args[1].run_id for call in run.call_args_list], ["q-2", "q-1"])
        self.assertEqual(
            [(call.args[1].provider, call.args[1].model) for call in run.call_args_list],
            [("openai", "gpt-test"), ("openai", "gpt-test")],
        )

    def test_limit_slices_source_order_rows_and_rejects_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            dataset = root / "dataset.jsonl"
            dataset.write_text(
                "\n".join(
                    (
                        json.dumps({"query_id": "q-2", "query": "two", "answer": "two"}),
                        json.dumps({"query_id": "q-1", "query": "one", "answer": "one"}),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            request = BenchmarkRequest(
                dataset=dataset,
                output_root=root / "out",
                cwd=root,
                judge_config=JudgeConfig(base_url="https://judge.example.test/v1"),
                runtime_options=DciRuntimeOptions(provider="openai", model="gpt-test"),
                limit=1,
            )
            with patch(
                "asterion.dci.benchmark.run_pi_research", side_effect=_recorded_run
            ) as run, patch(
                "asterion.dci.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                    result = run_benchmark(request, paths=Mock())

            self.assertEqual(result.counts["total"], 1)
            self.assertEqual(run.call_args.args[1].run_id, "q-2")

            invalid = BenchmarkRequest(
                dataset=dataset,
                output_root=root / "invalid",
                cwd=root,
                judge_config=JudgeConfig(base_url="https://judge.example.test/v1"),
                runtime_options=DciRuntimeOptions(provider="openai", model="gpt-test"),
                limit=0,
            )
            with self.assertRaisesRegex(DciBenchmarkError, "limit is invalid"):
                run_benchmark(invalid, paths=Mock())
    def test_batch_reuses_the_native_asterion_run_and_writes_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            with patch(
                "asterion.dci.benchmark.run_pi_research", side_effect=_recorded_run
            ) as run, patch(
                "asterion.dci.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                    result = run_benchmark(request, paths=Mock())

            self.assertEqual(run.call_count, 1)
            self.assertTrue((result.output_root / "summary.json").is_file())
            self.assertEqual(result.counts["correct"], 1)

    def test_existing_successful_result_skips_run_and_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            with patch("asterion.dci.run.PiRpcClient", _FixtureClient), patch(
                "asterion.dci.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                run_benchmark(request, paths=resolve_dci_paths(root))
            with patch("asterion.dci.benchmark.run_pi_research") as run:
                with patch("asterion.dci.benchmark.evaluate_run_directory_async") as evaluate:
                    run_benchmark(request, paths=resolve_dci_paths(root))

        run.assert_not_called()
        evaluate.assert_not_called()

    def test_changed_judge_configuration_reevaluates_without_rerunning_pi(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root)
            with patch("asterion.dci.run.PiRpcClient", _FixtureClient), patch(
                "asterion.dci.evaluation.judge_answer_sync",
                return_value=_verdict(request.judge_config),
            ):
                run_benchmark(request, paths=resolve_dci_paths(root))
            changed = replace(
                request,
                judge_config=JudgeConfig(base_url="https://other.example.test/v1"),
            )
            with patch("asterion.dci.benchmark.run_pi_research") as run, patch(
                "asterion.dci.evaluation.judge_answer_sync",
                return_value=_verdict(changed.judge_config, correct=False),
            ) as evaluate:
                run_benchmark(changed, paths=resolve_dci_paths(root))

        run.assert_not_called()
        evaluate.assert_called_once()

    def test_invalid_dataset_identity_fails_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            request = _request(root, query_id="../escape")
            with patch("asterion.dci.benchmark.run_pi_research") as run:
                with self.assertRaisesRegex(DciBenchmarkError, "dataset is invalid"):
                    run_benchmark(request, paths=Mock())

        run.assert_not_called()


def _request(root: Path, *, query_id: str = "q-1") -> BenchmarkRequest:
    dataset = root / "dataset.jsonl"
    dataset.write_text(json.dumps({"query_id": query_id, "query": "question", "answer": "gold"}) + "\n")
    return BenchmarkRequest(
        dataset=dataset,
        output_root=root / "out",
        cwd=root,
        judge_config=JudgeConfig(base_url="https://judge.example.test/v1"),
        runtime_options=DciRuntimeOptions(provider=None, model=None),
    )


def _result(output_dir: Path) -> DciRunResult:
    return DciRunResult(output_dir=output_dir, final_text="answer", events=(RunEvent("r", 1, "run.started", {"capabilities": []}), RunEvent("r", 2, "run.completed", {"status": "completed"})), status="completed")


def _verdict(config: JudgeConfig, *, correct: bool = True) -> dict[str, object]:
    return {
        **config.public_dict(),
        "judged_at": "2026-07-14T00:00:00+00:00",
        "attempts": 1,
        "judge_request_fingerprint": "replaced-by-evaluator",
        "is_correct": correct,
        "normalized_prediction": "answer",
        "reason": "fixture",
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "cost_estimate_usd": {
            "input_cost": 0.0,
            "cached_input_cost": 0.0,
            "output_cost": 0.0,
            "total_cost": 0.0,
        },
    }


if __name__ == "__main__":
    unittest.main()
