from __future__ import annotations

import json
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import tools.verify_prime_loop as prime_loop
from tools.verify_prime_loop import (
    PrimeVerificationError,
    load_bounded_authority,
    load_bounded_rlm_authority,
    verify_preflight,
    verify_provider_free,
)


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


@dataclass(frozen=True)
class _ScenarioResult:
    scenario_id: str
    status: str
    provider_operations: int
    application_operations: int


def _authorization(**authority_changes: object) -> dict[str, object]:
    authority: dict[str, object] = {
        "authority_id": "authority-1",
        "revision": 1,
        "allowed_portfolio": [
            {
                "provider_id": "example.provider",
                "application_id": "alpha",
                "version": "1.0.0",
                "runtime_id": "fake.runtime",
            }
        ],
        "allowed_operations": [
            "application.invoke",
            "checkpoint.create",
            "child.cancel",
            "child.message",
            "child.spawn",
            "goal.complete",
            "goal.fail",
        ],
        "budget_limit": {
            "controller_tokens": 100,
            "application_tokens": 100,
            "child_tokens": 100,
            "aggregate_tokens": 300,
            "cost_micros": 1_000,
        },
        "expires_at_ms": 100_000,
        "max_action_deadline_ms": 10_000,
        "max_recursion_depth": 1,
        "max_concurrent_children": 1,
        "execution_domain": "trusted-local",
        "host_service_grants": ["artifact.write"],
        "cancelled": False,
    }
    authority.update(authority_changes)
    return {
        "format": "asterion.prime-bounded-authorization/v1",
        "authority": authority,
    }


class TestVerifyPrimeLoop(unittest.TestCase):
    def test_native_rlm_public_usage_exposes_only_finite_counts(self) -> None:
        usage = prime_loop._native_rlm_public_usage(
            {"aggregate_tokens": 9_000, "cost_micros": 0}
        )

        self.assertEqual(
            usage,
            {"aggregate_tokens": 9_000, "cost_micros": 0},
        )
        self.assertEqual(
            prime_loop._native_rlm_public_usage(
                {
                    "controller_tokens": 9_000,
                    "application_tokens": 0,
                    "child_tokens": 0,
                    "aggregate_tokens": 9_000,
                    "cost_micros": 0,
                }
            ),
            {"aggregate_tokens": 9_000, "cost_micros": 0},
        )
        for invalid in (
            {"aggregate_tokens": 0, "cost_micros": 0},
            {"aggregate_tokens": 9_000, "cost_micros": -1},
            {
                "aggregate_tokens": 9_000,
                "cost_micros": 0,
                "raw_output": "SENTINEL_PRIVATE_OUTPUT",
            },
        ):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                PrimeVerificationError,
                "usage is invalid",
            ):
                prime_loop._native_rlm_public_usage(invalid)

    def test_bounded_environment_uses_only_the_selected_private_model_credential(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "ASTERION_PRIME_EXPERIMENT_MODEL=deepseek-v4-flash\n"
                "DEEPSEEK_API_KEY=current-private-key\n"
                "UNRELATED_SECRET=must-not-cross-boundary\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(prime_loop.Path, "cwd", return_value=root),
                mock.patch.dict(os.environ, {"HOME": "/private/home", "PATH": "/private/bin"}, clear=True),
            ):
                environment = prime_loop.resolve_bounded_prime_environment()

        self.assertEqual(environment["ASTERION_PRIME_EXPERIMENT_MODEL"], "deepseek-v4-flash")
        self.assertEqual(environment["DEEPSEEK_API_KEY"], "current-private-key")
        self.assertNotIn("UNRELATED_SECRET", environment)

    def test_bounded_environment_rejects_missing_selected_credential_without_rendering_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "ASTERION_PRIME_EXPERIMENT_MODEL=deepseek-v4-flash\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(prime_loop.Path, "cwd", return_value=root),
                mock.patch.dict(os.environ, {"HOME": "/private/home", "PATH": "/private/bin"}, clear=True),
                self.assertRaises(prime_loop.PrimeExternalLimit) as raised,
            ):
                prime_loop.resolve_bounded_prime_environment()

        self.assertNotIn("DEEPSEEK_API_KEY", str(raised.exception))

    def test_bounded_environment_rejects_unsupported_model_as_external_limited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "ASTERION_PRIME_EXPERIMENT_MODEL=unsupported-private-model\n"
                "DEEPSEEK_API_KEY=current-private-key\n"
            )
            with (
                mock.patch.object(prime_loop.Path, "cwd", return_value=root),
                mock.patch.dict(
                    os.environ,
                    {"HOME": "/private/home", "PATH": "/private/bin"},
                    clear=True,
                ),
                self.assertRaises(prime_loop.PrimeExternalLimit) as raised,
            ):
                prime_loop.resolve_bounded_prime_environment()

        self.assertNotIn("unsupported-private-model", str(raised.exception))

    def test_native_rlm_environment_prefers_explicit_dotenv_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "ASTERION_PRIME_EXPERIMENT_MODEL=deepseek-v4-flash\n"
                "DEEPSEEK_API_KEY=current-private-key\n"
                "PRIME_AGENT_KERNEL_VENV=/private/kernel-venv\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(prime_loop.Path, "cwd", return_value=root),
                mock.patch.dict(
                    os.environ,
                    {
                        "HOME": "/private/home",
                        "PATH": "/private/bin",
                        "DEEPSEEK_API_KEY": "stale-inherited-key",
                    },
                    clear=True,
                ),
            ):
                environment = prime_loop._native_rlm_environment()

        self.assertEqual(environment["DEEPSEEK_API_KEY"], "current-private-key")
        self.assertEqual(environment["ASTERION_PRIME_EXPERIMENT_MODEL"], "deepseek-v4-flash")
        self.assertEqual(environment["PRIME_AGENT_KERNEL_VENV"], "/private/kernel-venv")
        self.assertEqual(environment["HOME"], "/private/home")
        self.assertEqual(environment["PATH"], "/private/bin")

    def test_native_rlm_bounded_uses_defaults_after_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                mock.patch.object(prime_loop, "verify_preflight") as preflight,
                mock.patch.object(prime_loop.Path, "cwd", return_value=root),
                mock.patch(
                    "tools.prime_native_rlm_experiment.prepare_native_rlm_experiment"
                ) as prepare,
            ):
                result = prime_loop.main(
                    [
                        "--level", "native-rlm-bounded",
                        "--source-root", str(root / "source"),
                        "--native-rlm-experiment",
                    ]
                )

            self.assertEqual(result, 2)
            preflight.assert_called_once_with(root / "source")
            prepare.assert_called_once()
            self.assertIsNone(prepare.call_args.args[0])
            self.assertIsNone(prepare.call_args.kwargs["max_cost_micros"])
            self.assertEqual(
                (root / ".asterion-private" / "prime-rlm").stat().st_mode & 0o777,
                0o700,
            )

    def test_bounded_uses_ephemeral_authority_and_default_limits(self) -> None:
        source_root = Path("/private/prime-source")
        with (
            mock.patch.object(
                prime_loop, "_native_rlm_bounded_external_limit",
                return_value={"status": "PASS"},
            ) as native,
            mock.patch.object(
                prime_loop, "_default_native_rlm_evidence_root",
                return_value=Path("/private/evidence"),
            ),
        ):
            report = prime_loop._bounded_external_limit(source_root, None, None)

        self.assertEqual(report["status"], "PASS")
        native.assert_called_once_with(
            source_root, None, None, Path("/private/evidence")
        )

    def test_bounded_validates_explicit_authority_against_default_limit(self) -> None:
        source_root = Path("/private/prime-source")
        authority = Path("/private/authority.json")
        with (
            mock.patch.object(prime_loop, "load_bounded_rlm_authority") as load,
            mock.patch.object(
                prime_loop, "_native_rlm_bounded_external_limit",
                return_value={"status": "PASS"},
            ),
            mock.patch.object(
                prime_loop, "_default_native_rlm_evidence_root",
                return_value=Path("/private/evidence"),
            ),
        ):
            prime_loop._bounded_external_limit(source_root, authority, None)

        load.assert_called_once_with(
            authority, max_cost_micros=prime_loop._DEFAULT_BOUNDED_MAX_COST_MICROS
        )

    def test_native_rlm_bounded_requires_exact_opt_in_before_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stderr = io.StringIO()
            with (
                mock.patch.object(prime_loop, "verify_preflight") as preflight,
                redirect_stderr(stderr),
            ):
                result = prime_loop.main(
                    [
                        "--level", "native-rlm-bounded",
                        "--source-root", str(root),
                        "--authority", str(root / "authority.json"),
                        "--max-cost-micros", "500000",
                        "--private-evidence-root", str(root / "evidence"),
                    ]
                )
            self.assertEqual(result, 1)
            preflight.assert_not_called()

    def test_provider_free_report_requires_all_exact_zero_provider_scenarios(
        self,
    ) -> None:
        results = tuple(
            _ScenarioResult(
                scenario_id=scenario_id,
                status="PASS",
                provider_operations=0,
                application_operations=1 if scenario_id == EXPECTED_IDS[0] else 0,
            )
            for scenario_id in EXPECTED_IDS
        )

        report = verify_provider_free(lambda: results)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["scenario_count"], 10)
        self.assertEqual(report["provider_operations"], 0)
        self.assertEqual(report["application_operations"], 1)

        for mutation in (
            results[:-1],
            (*results[:-1], _ScenarioResult(**{**vars(results[-1]), "status": "FAIL"})),
            (
                *results[:-1],
                _ScenarioResult(**{**vars(results[-1]), "provider_operations": 1}),
            ),
        ):
            with (
                self.subTest(length=len(mutation)),
                self.assertRaises(PrimeVerificationError),
            ):
                verify_provider_free(lambda mutation=mutation: mutation)

    def test_bounded_authority_requires_finite_consistent_trusted_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / "valid.json"
            valid.write_text(json.dumps(_authorization()))

            envelope = load_bounded_authority(
                valid, max_cost_micros=1_000, now_ms=1_000
            )

            self.assertEqual(envelope.authority_id, "authority-1")
            self.assertEqual(envelope.max_recursion_depth, 1)
            self.assertEqual(envelope.max_concurrent_children, 1)

            invalid_values = (
                ("zero-cap", valid, 0),
                ("lower-cap", valid, 999),
                (
                    "restricted",
                    _write(
                        root / "restricted.json",
                        _authorization(execution_domain="restricted"),
                    ),
                    1_000,
                ),
                (
                    "expired",
                    _write(root / "expired.json", _authorization(expires_at_ms=1_000)),
                    1_000,
                ),
                (
                    "too-many-children",
                    _write(
                        root / "children.json",
                        _authorization(max_concurrent_children=2),
                    ),
                    1_000,
                ),
            )
            for name, path, maximum in invalid_values:
                with self.subTest(name=name), self.assertRaises(PrimeVerificationError):
                    load_bounded_authority(path, max_cost_micros=maximum, now_ms=1_000)

    def test_bounded_authority_errors_never_render_private_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authority.json"
            path.write_text("SENTINEL_SECRET")
            with self.assertRaises(PrimeVerificationError) as raised:
                load_bounded_authority(path, max_cost_micros=1, now_ms=1)
            self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
            self.assertNotIn(str(path), str(raised.exception))

    def test_native_rlm_authority_requires_exact_capabilities_and_limits(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rlm_operations = (
                "rlm.child.delete",
                "rlm.child.message",
                "rlm.child.spawn",
            )
            valid_operations = [
                *_authorization()["authority"]["allowed_operations"],
                *rlm_operations,
            ]
            valid = _write(
                root / "valid-rlm.json",
                _authorization(allowed_operations=valid_operations),
            )

            envelope = load_bounded_rlm_authority(
                valid, max_cost_micros=1_000, now_ms=1_000
            )

            self.assertEqual(envelope.max_recursion_depth, 1)
            self.assertEqual(envelope.max_concurrent_children, 1)

            for missing in rlm_operations:
                operations = [item for item in valid_operations if item != missing]
                with self.subTest(missing=missing), self.assertRaises(
                    PrimeVerificationError
                ):
                    load_bounded_rlm_authority(
                        _write(
                            root / f"missing-{missing}.json",
                            _authorization(allowed_operations=operations),
                        ),
                        max_cost_micros=1_000,
                        now_ms=1_000,
                    )

            for name, changes in (
                ("zero-depth", {"max_recursion_depth": 0}),
                ("deep", {"max_recursion_depth": 2}),
                ("zero-children", {"max_concurrent_children": 0}),
                ("many-children", {"max_concurrent_children": 2}),
            ):
                with self.subTest(name=name), self.assertRaises(
                    PrimeVerificationError
                ):
                    load_bounded_rlm_authority(
                        _write(root / f"{name}.json", _authorization(**changes)),
                        max_cost_micros=1_000,
                        now_ms=1_000,
                    )

    def test_preflight_owns_one_foreground_daemon_without_removed_cli_commands(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = Path(directory) / "prime-source"
            package_root = project / "packages/typescript/prime-gateway"
            gateway_entry = package_root / "dist/src/index.js"
            gateway_entry.parent.mkdir(parents=True)
            gateway_entry.write_text("export {};\n")
            bundle = source / "packages/coding-agent/dist/bundle/cli.js"
            bundle.parent.mkdir(parents=True, exist_ok=True)
            bundle.write_text("fixture\n")
            source_report = SimpleNamespace(
                source_commit="a18809e00ea30638584d87b3afea7285a9d7296c",
                package_version="0.7.1",
                daemon_protocol=7,
                daemon_schema_revision=14,
            )
            commands: list[tuple[str, ...]] = []
            popen_calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

            def command_runner(command, cwd, environment):
                commands.append(command)
                if "--input-type=module" in command:
                    handshake_script = command[3]
                    self.assertNotIn("hello.protocol.", handshake_script)
                    self.assertIn("hello.protocolVersion", handshake_script)
                    self.assertIn("hello.runtimeBuildId", handshake_script)
                    payload = {
                        "protocol_name": "prime-agent.daemon",
                        "protocol_version": 7,
                        "schema_id": "protocol-7-schema-14-fixture",
                        "schema_revision": 14,
                        "app_version": "0.7.1",
                        "runtime_build_id": "fixture-build",
                    }
                    return subprocess.CompletedProcess(
                        command, 0, stdout=json.dumps(payload), stderr=""
                    )
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            class FakeProcess:
                def __init__(self) -> None:
                    self.returncode: int | None = None

                def poll(self) -> int | None:
                    return self.returncode

                def terminate(self) -> None:
                    self.returncode = -15

                def wait(self, timeout: float | None = None) -> int:
                    del timeout
                    self.returncode = -15
                    return self.returncode

                def kill(self) -> None:
                    self.returncode = -9

            def popen_runner(command, **kwargs):
                popen_calls.append((command, kwargs))
                Path(command[-1]).touch()
                return FakeProcess()

            with (
                mock.patch.object(
                    prime_loop,
                    "__file__",
                    str(project / "tools/verify_prime_loop.py"),
                ),
                mock.patch.object(
                    prime_loop, "verify_prime_source", return_value=source_report
                ),
                mock.patch.object(
                    prime_loop, "derive_prime_rlm_runtime", return_value=bundle.resolve()
                ),
                mock.patch.object(
                    prime_loop, "_prime_node_executable", return_value=Path("node")
                ),
                mock.patch.object(prime_loop, "_command", side_effect=command_runner),
                mock.patch.object(
                    prime_loop.subprocess, "Popen", side_effect=popen_runner
                ),
                mock.patch.dict(
                    os.environ,
                    {"PATH": os.environ.get("PATH", ""), "OPENAI_API_KEY": "SENTINEL_SECRET"},
                    clear=True,
                ),
            ):
                try:
                    report = verify_preflight(source)
                except prime_loop.PrimeExternalLimit:
                    self.fail("bundle-only Prime preflight was rejected")

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(popen_calls), 1)
        daemon_command, daemon_options = popen_calls[0]
        self.assertEqual(
            daemon_command,
            (
                "node",
                str(bundle.resolve()),
                "--mode",
                "daemon",
                "--daemon-socket",
                daemon_command[-1],
            ),
        )
        daemon_environment = daemon_options["env"]
        self.assertIsInstance(daemon_environment, dict)
        assert isinstance(daemon_environment, dict)
        self.assertNotIn("OPENAI_API_KEY", daemon_environment)
        self.assertNotIn("SENTINEL_SECRET", repr(popen_calls))
        self.assertFalse(
            any(command[1:3] == ("daemon", "start") for command in commands)
        )
        self.assertFalse(any("shutdown" in command for command in commands))

class TestNativeRlmFailureEvidence(unittest.TestCase):
    def test_failure_evidence_distinguishes_confirmed_hard_kill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-cancel-stage:abort\n"
                "asterion-prime-cancel-stage:kill-confirmed\n"
                "asterion-prime-sidecar-failed:session-cancel\n",
                encoding="utf-8",
            )

            self.assertEqual(
                prime_loop._native_rlm_failure_class(stderr),
                "cancel_kill_confirmed",
            )

    def test_failure_evidence_distinguishes_terminal_ledger_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-gateway-cancel-stage:goal-updated\n"
                "asterion-prime-gateway-cancel-stage:terminal-appended\n"
                "asterion-prime-sidecar-failed:session-cancel\n",
                encoding="utf-8",
            )

            self.assertEqual(
                prime_loop._native_rlm_failure_class(stderr),
                "gateway_cancel_terminal_appended",
            )

    def test_failure_evidence_classifies_private_stderr_without_retaining_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stderr = root / "sidecar.stderr.log"
            stderr.write_text("request failed: unauthorized SENTINEL_SECRET", encoding="utf-8")

            prime_loop._write_native_rlm_external_limit_evidence(
                root, "execution", stderr_path=stderr
            )

            evidence = json.loads(
                (root / "native-rlm-external-limit.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["failure_class"], "credential")
            self.assertNotIn("SENTINEL_SECRET", repr(evidence))
            self.assertEqual(
                (root / "native-rlm-external-limit.json").stat().st_mode & 0o777,
                0o600,
            )

    def test_failure_evidence_classifies_safe_sidecar_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text("asterion-prime-sidecar-stage:serve\n", encoding="utf-8")

            self.assertEqual(
                prime_loop._native_rlm_failure_class(stderr), "sidecar_serve"
            )

    def test_failure_evidence_classifies_checkpoint_request_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-sidecar-failed:checkpoint-request\n",
                encoding="utf-8",
            )

            self.assertEqual(
                prime_loop._native_rlm_failure_class(
                    stderr,
                    safe_error=(
                        "Native RLM controlled probe running event-transport "
                        "did not complete"
                    ),
                ),
                "sidecar_checkpoint_request",
            )

    def test_failure_evidence_classifies_private_read_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-sidecar-failed:private.read\n",
                encoding="utf-8",
            )

            self.assertEqual(
                prime_loop._native_rlm_failure_class(stderr),
                "sidecar_private_read",
            )

    def test_failure_evidence_classifies_action_resolution_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-sidecar-failed:action-resolve\n",
                encoding="utf-8",
            )

            self.assertEqual(
                prime_loop._native_rlm_failure_class(stderr),
                "sidecar_action_resolve",
            )

    def test_failure_evidence_classifies_checkpoint_prepare_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-checkpoint-stage:prepare\n",
                encoding="utf-8",
            )

            self.assertEqual(
                prime_loop._native_rlm_failure_class(
                    stderr,
                    safe_error=(
                        "Native RLM controlled probe running event-transport "
                        "did not complete"
                    ),
                ),
                "checkpoint_prepare",
            )

    def test_failure_evidence_prefers_checkpoint_attach_failure_over_prior_stages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-checkpoint-stage:idle\n"
                "asterion-prime-checkpoint-stage:prepare\n"
                "asterion-prime-checkpoint-stage:attach\n"
                "asterion-prime-checkpoint-attach-failed:validation\n",
                encoding="utf-8",
            )

            self.assertEqual(
                prime_loop._native_rlm_failure_class(stderr),
                "checkpoint_attach_validation",
            )

    def test_failure_evidence_classifies_checkpoint_lifecycle_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-checkpoint-stage:stop\n"
                "asterion-prime-checkpoint-lifecycle-failed\n",
                encoding="utf-8",
            )

            self.assertEqual(
                prime_loop._native_rlm_failure_class(stderr),
                "checkpoint_lifecycle",
            )

    def test_failure_evidence_classifies_checkpoint_runtime_stop_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-checkpoint-stage:stop\n"
                "asterion-prime-checkpoint-runtime-stop-failed\n",
                encoding="utf-8",
            )
            self.assertEqual(
                prime_loop._native_rlm_failure_class(stderr),
                "checkpoint_runtime_stop",
            )

    def test_failure_evidence_classifies_checkpoint_stop_substage_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-checkpoint-stop:shim\n"
                "asterion-prime-checkpoint-stop:shutdown\n",
                encoding="utf-8",
            )
            self.assertEqual(
                prime_loop._native_rlm_failure_class(stderr),
                "checkpoint_stop_shutdown",
            )

    def test_failure_evidence_classifies_checkpoint_lifecycle_stage_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-checkpoint-stage:stop\n"
                "asterion-prime-checkpoint-lifecycle:request\n",
                encoding="utf-8",
            )

            self.assertEqual(
                prime_loop._native_rlm_failure_class(stderr),
                "checkpoint_lifecycle_request",
            )

    def test_failure_evidence_records_lifecycle_acceptance_before_restart_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-checkpoint-lifecycle:request\n"
                "asterion-prime-checkpoint-lifecycle:accepted\n",
                encoding="utf-8",
            )

            self.assertEqual(
                prime_loop._native_rlm_failure_class(stderr),
                "checkpoint_lifecycle_accepted",
            )

    def test_failure_evidence_prefers_root_start_failure_over_cleanup_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-gateway-cancel-stage:terminal-appended\n",
                encoding="utf-8",
            )

            self.assertEqual(
                prime_loop._native_rlm_failure_class(
                    stderr,
                    safe_error="Native RLM controlled probe start control did not complete",
                ),
                "root_start",
            )

    def test_failure_evidence_classifies_checkpoint_recovery_field_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-checkpoint-stage:attach\n"
                "asterion-prime-checkpoint-recovery-invalid:summary\n",
                encoding="utf-8",
            )

            self.assertEqual(
                prime_loop._native_rlm_failure_class(stderr),
                "checkpoint_recovery_summary",
            )

    def test_failure_evidence_classifies_skill_dispatch_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-skill-request:dispatch\n", encoding="utf-8"
            )

            self.assertEqual(
                prime_loop._native_rlm_failure_class(
                    stderr,
                    safe_error=(
                        "Native RLM controlled probe checkpoint request "
                        "did not complete"
                    ),
                ),
                "skill_dispatch",
            )

    def test_failure_evidence_classifies_fixed_event_transport(self) -> None:
        self.assertEqual(
            prime_loop._native_rlm_failure_class(
                None,
                safe_error="Native RLM controlled probe running event-transport did not complete",
            ),
            "event_transport",
        )

    def test_failure_evidence_does_not_misclassify_completed_maintenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = Path(directory) / "sidecar.stderr.log"
            stderr.write_text(
                "asterion-prime-checkpoint-stage:capsule\n"
                "asterion-prime-gateway-cancel-stage:terminal-appended\n",
                encoding="utf-8",
            )
            self.assertEqual(
                prime_loop._native_rlm_failure_class(stderr),
                "observation_unclassified",
            )

    def test_failure_evidence_classifies_fixed_control_transition(self) -> None:
        self.assertEqual(
            prime_loop._native_rlm_failure_class(
                None,
                safe_error="Native RLM controlled probe running event-transition did not complete",
            ),
            "event_transition",
        )

    def test_failure_evidence_classifies_controlled_goal_terminal_without_private_content(self) -> None:
        self.assertEqual(
            prime_loop._native_rlm_failure_class(
                None,
                safe_error="Native RLM controlled probe goal terminal did not succeed",
            ),
            "goal_terminal",
        )

    def test_failure_evidence_classifies_safe_action_admission_kind(self) -> None:
        self.assertEqual(
            prime_loop._native_rlm_failure_class(
                None,
                safe_error=(
                    "Native RLM controlled probe running action-admission-child-message "
                    "did not complete"
                ),
            ),
            "action_admission_child_message",
        )


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value))
    return path


if __name__ == "__main__":
    unittest.main()
