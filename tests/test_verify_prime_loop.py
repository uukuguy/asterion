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
    def test_native_rlm_environment_prefers_explicit_dotenv_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "ASTERION_PRIME_EXPERIMENT_MODEL=deepseek-v4-flash\n"
                "DEEPSEEK_API_KEY=current-private-key\n",
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


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value))
    return path


if __name__ == "__main__":
    unittest.main()
