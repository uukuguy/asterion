from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from asterion.applications.dci_agent_lite.benchmark_executor import (
    RealDciBenchmarkExecutor,
)
from asterion.applications.dci_agent_lite.benchmark_host import DciBenchmarkHost
from asterion.applications.dci_agent_lite.benchmark_instances import (
    select_benchmark_instance,
)
from asterion.applications.dci_agent_lite.benchmark_source_lock import (
    resolve_benchmark_source_lock,
    write_benchmark_source_lock,
)
from asterion.applications.dci_agent_lite.operator_config import (
    load_operator_config,
)
from asterion.capabilities.dci.implementation.config import (
    DciRuntimeOptions,
    resolve_dci_paths,
)
from asterion.capabilities.dci.implementation.evaluation.judge import JudgeConfig
from asterion.capabilities.dci.implementation.runtime.run import (
    DciRunResult,
    run_pi_research as _real_run_pi_research,
)


class _FixtureClient:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass

    def prompt_and_wait(self, _message: str, *, on_event, **_kwargs: object) -> str:
        for event in (
            {"type": "response", "id": "fixture", "success": True},
            {"type": "agent_start"},
            {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "text_delta",
                    "delta": "PRIVATE-AGENT-ANSWER",
                },
            },
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "stopReason": "stop",
                    "usage": {
                        "input": 1,
                        "output": 1,
                        "cacheRead": 0,
                        "cacheWrite": 0,
                        "cost": {
                            "input": 0.0,
                            "output": 0.0,
                            "cacheRead": 0.0,
                            "cacheWrite": 0.0,
                            "total": 0.0,
                        },
                    },
                    "content": [{"type": "text", "text": "PRIVATE-AGENT-ANSWER"}],
                },
            },
            {"type": "agent_end"},
        ):
            on_event(event)
        return "PRIVATE-AGENT-ANSWER"

    def get_stderr(self) -> str:
        return ""

    def get_entries(self, *, since=None):
        del since
        state = {
            "accumulatedOriginalToolCharacters": 0,
            "truncatedResults": 0,
            "compactionCount": 0,
            "preservedTurns": None,
            "compactionPending": False,
            "summaryAttempts": 0,
            "summarySuccesses": 0,
            "consecutiveSummaryFailures": 0,
            "summarySuppressed": False,
        }
        wrapper = {
            "parentId": None,
            "timestamp": "2026-07-30T00:00:00Z",
            "type": "custom",
        }
        return [
            {
                **wrapper,
                "id": "telemetry-1",
                "customType": "dci-context-telemetry",
                "data": {
                    "schema": "dci.context-telemetry/v2",
                    "event": "startup",
                    "profile": "level3",
                    "contractVersion": "dci.context-profile/v1",
                    "extensionVersion": "0.3.0",
                    **state,
                },
            },
            {
                **wrapper,
                "id": "state-1",
                "customType": "dci-context-state",
                "data": {
                    "schema": "dci.context-state/v2",
                    "profile": "level3",
                    "contractVersion": "dci.context-profile/v1",
                    "state": state,
                },
            },
        ]

    def stop(self) -> None:
        pass


def _recorded_agent(paths, request, **kwargs) -> DciRunResult:
    del paths
    with patch(
        "asterion.capabilities.dci.implementation.runtime.run.PiRpcClient",
        _FixtureClient,
    ):
        return _real_run_pi_research(
            resolve_dci_paths(Path(request.cwd)),
            request,
            **kwargs,
        )


class DciBenchmarkBamboogleE2ETests(unittest.TestCase):
    def test_host_runs_one_real_engine_case_and_resume_reuses_evidence(self) -> None:
        sentinel = "PRIVATE-QUESTION-SENTINEL"
        instance = select_benchmark_instance("dci.qa.bamboogle.github-sample50@1.0.0")
        agent_errors = []

        def agent(*args, **kwargs):
            try:
                return _recorded_agent(*args, **kwargs)
            except BaseException as error:
                agent_errors.append(repr(error))
                raise

        agent_calls = Mock(side_effect=agent)

        def judge(*_args, **kwargs):
            config = kwargs["config"]
            contract_id = kwargs["contract_id"]
            return {
                **config.public_dict(),
                "judge_contract": contract_id,
                "judged_at": "2026-07-30T00:00:00+00:00",
                "attempts": 1,
                "is_correct": True,
                "judge_request_fingerprint": "a" * 64,
                "normalized_prediction": "PRIVATE-AGENT-ANSWER",
                "reason": "fixture",
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
                "cost_estimate_usd": {
                    "input_cost": 0.0,
                    "cached_input_cost": 0.0,
                    "output_cost": 0.0,
                    "total_cost": 0.0,
                },
            }

        judge_calls = Mock(side_effect=judge)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            resources = root / "resources"
            dataset = (
                resources / "data" / "dci-bench" / "data" / "bamboogle" / "test.jsonl"
            )
            dataset.parent.mkdir(parents=True)
            dataset.write_text(
                json.dumps(
                    {
                        "query_id": "q-1",
                        "query": sentinel,
                        "answer": "PRIVATE-GOLD",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (resources / "corpus" / "wiki_corpus").mkdir(parents=True)
            config = load_operator_config(
                root,
                environment={
                    "ASTERION_DCI_RESOURCE_ROOT": str(resources),
                    "DCI_EVAL_JUDGE_API_KEY": "PRIVATE-JUDGE-KEY",
                },
            )
            lock_path = root / "source-lock.json"
            write_benchmark_source_lock(
                resolve_benchmark_source_lock(instance),
                lock_path,
            )
            evidence_root = root / "evidence"

            def execute(resume_run_id: str | None):
                host = DciBenchmarkHost(
                    instance=instance,
                    operator_config=config,
                    executor_factory=lambda _instance: RealDciBenchmarkExecutor(
                        paths=resolve_dci_paths(root, environment={}),
                        runtime_options=DciRuntimeOptions(
                            provider="openai",
                            model="gpt-5.4-nano",
                            tools="read,bash",
                            runtime_context_level="level3",
                        ),
                        judge_config=JudgeConfig(
                            base_url="https://api.openai.com/v1",
                            api="responses",
                            model="gpt-5.4-nano",
                            api_key_env="OPENAI_API_KEY",
                            api_key="PRIVATE-JUDGE-KEY",
                        ),
                        readiness_probe=lambda *_args: None,
                    ),
                )
                metadata = host.discover_metadata(
                    application_ref=instance.application_ref,
                    suite_ref=instance.suite_ref,
                )
                source_lock = host.resolve_source_lock(lock_path)
                payloads = host.open_selected_payloads(metadata, source_lock)
                resolved = host.resolve_application(
                    payloads,
                    application_ref=instance.application_ref,
                    suite_ref=instance.suite_ref,
                )
                host.create_plan(
                    resolved,
                    application_ref=instance.application_ref,
                    suite_ref=instance.suite_ref,
                    case_limit=1,
                    execute=False,
                    authorization=None,
                    resume_run_id=None,
                )
                authorization = host.authorize_execution(
                    application_ref=instance.application_ref,
                    suite_ref=instance.suite_ref,
                    case_limit=1,
                    evidence_root=evidence_root,
                    resume_run_id=resume_run_id,
                )
                plan = host.create_plan(
                    resolved,
                    application_ref=instance.application_ref,
                    suite_ref=instance.suite_ref,
                    case_limit=1,
                    execute=True,
                    authorization=authorization,
                    resume_run_id=resume_run_id,
                )
                providers = host.load_selected_providers(payloads, authorization)
                return plan, host.run(
                    plan,
                    providers,
                    evidence_root=evidence_root,
                )

            with (
                patch(
                    "asterion.capabilities.dci.implementation.evaluation.benchmark.run_pi_research",
                    agent_calls,
                ),
                patch(
                    "asterion.capabilities.dci.implementation.evaluation.evaluation.judge_answer_sync",
                    judge_calls,
                ),
            ):
                first_plan, first = execute(None)
                second_plan, second = execute(first_plan.run_id)

            generic_evidence = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (evidence_root / "runs").rglob("*.json")
            )
        self.assertEqual(
            first.status,
            "completed",
            (
                first,
                agent_calls.call_count,
                judge_calls.call_count,
                agent_errors,
            ),
        )
        self.assertEqual(second.status, "completed")
        self.assertEqual(second_plan.run_id, first_plan.run_id)
        self.assertEqual(agent_calls.call_count, 1)
        self.assertEqual(judge_calls.call_count, 1)
        self.assertNotIn(sentinel, generic_evidence)
        self.assertNotIn("PRIVATE-JUDGE-KEY", generic_evidence)
        self.assertNotIn("PRIVATE-AGENT-ANSWER", generic_evidence)


if __name__ == "__main__":
    unittest.main()
