from __future__ import annotations

import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from asterion.dci.application_executor import EnvironmentDciRunExecutor
from asterion.dci.cli import main as dci_main
from asterion.dci.config import DciRuntimeOptions, resolve_dci_paths
from asterion.dci.pi_rpc import FINAL_ANSWER_RECOVERY_PROMPT
from asterion.dci.prompts import (
    PAPER_REFERENCE_PROMPT_CONTRACT,
    UPSTREAM_GITHUB_PROMPT_CONTRACT,
    resolve_prompt_contract,
)
from asterion.dci.run import (
    DciRunError,
    DciRunRequest,
    DciRunResult,
    request_from_runtime_options,
    resume_request_from_output_dir,
    run_pi_research,
)
from asterion.dci.verification import (
    BASIC_CASES,
    PaperBenchmarkReadiness,
    _basic_request,
    _paper_default_operation_runner,
)


class _EmptyFirstClient:
    instances: list["_EmptyFirstClient"] = []

    def __init__(self, **_kwargs: object) -> None:
        self.recoveries: list[str] = []
        _EmptyFirstClient.instances.append(self)

    def start(self) -> None:
        pass

    def prompt_and_wait(
        self,
        _message: str,
        *,
        final_answer_recovery: str | None = None,
        **_kwargs: object,
    ) -> str:
        if final_answer_recovery is None:
            return ""
        self.recoveries.append(final_answer_recovery)
        return "recovered answer"

    def get_stderr(self) -> str:
        return ""

    def stop(self) -> None:
        pass


def _request(root: Path, *, run_id: str = "safe-recovery") -> DciRunRequest:
    return DciRunRequest(
        run_id=run_id,
        question="answer from the local corpus",
        cwd=root,
        provider="openai-codex",
        model="gpt-test",
        tools="read",
        timeout_seconds=30.0,
        stream_text=False,
    )


class AsterionSafeRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        _EmptyFirstClient.instances.clear()

    def _assert_completed_after_one_recovery(
        self,
        root: Path,
        request: DciRunRequest,
        output_dir: Path,
    ) -> DciRunResult:
        with patch("asterion.dci.run.PiRpcClient", _EmptyFirstClient):
            result = run_pi_research(
                resolve_dci_paths(root), request, output_dir=output_dir
            )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.final_text, "recovered answer")
        self.assertEqual(len(_EmptyFirstClient.instances), 1)
        self.assertEqual(
            _EmptyFirstClient.instances[0].recoveries,
            [FINAL_ANSWER_RECOVERY_PROMPT],
        )
        return result

    def test_standalone_cli_run_selects_safe_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch("asterion.dci.run.PiRpcClient", _EmptyFirstClient):
                status = dci_main(
                    [
                        "run",
                        "answer from the local corpus",
                        "--cwd",
                        str(root),
                        "--output-dir",
                        str(root / "run"),
                    ],
                    repo_root=root,
                    stdout=stdout,
                    stderr=stderr,
                )

        self.assertEqual(status, 0, stderr.getvalue())
        self.assertEqual(
            _EmptyFirstClient.instances[0].recoveries,
            [FINAL_ANSWER_RECOVERY_PROMPT],
        )

    def test_standalone_cli_resume_selects_safe_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output_dir = root / "run"
            failed_request = _request(root)
            with patch("asterion.dci.run.PiRpcClient", _EmptyFirstClient):
                with self.assertRaises(DciRunError):
                    run_pi_research(
                        resolve_dci_paths(root), failed_request, output_dir=output_dir
                    )
            _EmptyFirstClient.instances.clear()
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch("asterion.dci.run.PiRpcClient", _EmptyFirstClient):
                status = dci_main(
                    ["resume", "--output-dir", str(output_dir)],
                    repo_root=root,
                    stdout=stdout,
                    stderr=stderr,
                )

        self.assertEqual(status, 0, stderr.getvalue())
        self.assertEqual(
            _EmptyFirstClient.instances[0].recoveries,
            [FINAL_ANSWER_RECOVERY_PROMPT],
        )

    def test_environment_executor_selects_safe_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = resolve_dci_paths(root)
            executor = EnvironmentDciRunExecutor(repo_root=root)
            with (
                patch("asterion.dci.application_executor.load_asterion_dci_env"),
                patch(
                    "asterion.dci.application_executor.resolve_dci_runtime_options",
                    return_value=DciRuntimeOptions(
                        provider="openai-codex", model="gpt-test", tools="read"
                    ),
                ),
                patch(
                    "asterion.dci.application_executor.resolve_dci_paths",
                    return_value=paths,
                ),
                patch("asterion.dci.run.PiRpcClient", _EmptyFirstClient),
            ):
                result = executor.run(_request(root))

        self.assertEqual(result.status, "completed")
        self.assertEqual(
            _EmptyFirstClient.instances[0].recoveries,
            [FINAL_ANSWER_RECOVERY_PROMPT],
        )

    def test_basic_verification_request_selects_safe_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / BASIC_CASES[0].corpus_subdir).mkdir()
            request = _basic_request(
                BASIC_CASES[0],
                DciRuntimeOptions(provider="openai-codex", model="gpt-test", tools="read"),
                resolve_dci_paths(root),
                root,
            )
            self._assert_completed_after_one_recovery(root, request, root / "basic")

    def test_resume_request_accepts_explicit_safe_recovery_without_persisting_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output_dir = root / "run"
            with patch("asterion.dci.run.PiRpcClient", _EmptyFirstClient):
                with self.assertRaises(DciRunError):
                    run_pi_research(
                        resolve_dci_paths(root), _request(root), output_dir=output_dir
                    )

            resumed = resume_request_from_output_dir(
                output_dir, final_answer_recovery=FINAL_ANSWER_RECOVERY_PROMPT
            )
            self.assertEqual(resumed.final_answer_recovery, FINAL_ANSWER_RECOVERY_PROMPT)
            _EmptyFirstClient.instances.clear()
            self._assert_completed_after_one_recovery(root, resumed, output_dir)

    def test_generic_runtime_and_analysis_resume_keep_no_recovery_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.assertIsNone(
                request_from_runtime_options(
                    DciRuntimeOptions(),
                    run_id="validation-only",
                    question="validation only",
                    cwd=root,
                ).final_answer_recovery
            )
            output_dir = root / "run"
            with patch("asterion.dci.run.PiRpcClient", _EmptyFirstClient):
                with self.assertRaises(DciRunError):
                    run_pi_research(
                        resolve_dci_paths(root), _request(root), output_dir=output_dir
                    )
            self.assertIsNone(resume_request_from_output_dir(output_dir).final_answer_recovery)

    def test_paper_operation_selects_no_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            readiness = PaperBenchmarkReadiness(
                output_root=root / "out",
                provider="openai-codex",
                model="gpt-test",
                judge_identity=(),
                pi_revision="0" * 40,
                pi_tracked_status_sha256="0" * 64,
                resource_digests=(),
                paths=resolve_dci_paths(root),
                runtime_options=DciRuntimeOptions(
                    provider="openai-codex", model="gpt-test", tools="read"
                ),
                judge_config=object(),
                corpus_dir=root,
            )
            with patch(
                "asterion.dci.verification.run_pi_research",
                side_effect=DciRunError("expected"),
            ) as run:
                with self.assertRaises(DciRunError):
                    _paper_default_operation_runner(readiness, "qa-agent")

        self.assertIsNone(run.call_args.args[1].final_answer_recovery)

    def test_paper_and_upstream_contracts_fail_after_an_empty_final(self) -> None:
        for contract_id in (
            PAPER_REFERENCE_PROMPT_CONTRACT,
            UPSTREAM_GITHUB_PROMPT_CONTRACT,
        ):
            with self.subTest(contract=contract_id), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                request = replace(
                    _request(root),
                    final_answer_recovery=resolve_prompt_contract(
                        contract_id
                    ).final_answer_recovery,
                )
                self.assertIsNone(request.final_answer_recovery)
                with patch("asterion.dci.run.PiRpcClient", _EmptyFirstClient):
                    with self.assertRaises(DciRunError):
                        run_pi_research(
                            resolve_dci_paths(root), request, output_dir=root / "run"
                        )
                self.assertEqual(_EmptyFirstClient.instances[0].recoveries, [])
                _EmptyFirstClient.instances.clear()


if __name__ == "__main__":
    unittest.main()
