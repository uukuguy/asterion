from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import unittest
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from asterion.control.parity import validate_parity_ledger
from asterion.applications.prime_agent.long_session_continuity_receipt import (
    long_session_continuity_observation_from_public_report,
    verify_long_session_continuity_receipt,
)
from asterion.control.parity_testing import ParityScenarioRegistryError
from asterion.control.providers.prime.parity_testing import (
    PRIME_SESSION_CONTEXT_ARTIFACT_LOCK,
    PRIME_SESSION_CONTEXT_BOUNDED_SCENARIO_IDS,
    PRIME_SESSION_CONTEXT_BOUNDED_PASS_CHECK_IDS,
    PRIME_SESSION_CONTEXT_BOUNDED_VERIFICATION_COMMAND_ID,
    PRIME_SESSION_CONTEXT_PROVIDER_FREE_SCENARIO_IDS,
    PRIME_SESSION_CONTEXT_SCENARIO_IDS,
    PRIME_SESSION_CONTEXT_SCENARIO_MATRIX,
    PRIME_SESSION_CONTEXT_SOURCE_COMMIT,
    PRIME_SESSION_CONTEXT_VERIFICATION_COMMAND_ID,
    PrimeSessionContextScenarioObservation,
    build_prime_session_context_observation,
    register_prime_session_context_scenarios,
)
from tools.verify_prime_loop import resolve_bounded_prime_environment
from asterion.control.parity_testing import ParityScenarioRegistry
from tools.setup_prime_agent import verify_prime_source


ROOT = Path(__file__).resolve().parents[1]
LEDGER = (
    ROOT
    / "tests"
    / "fixtures"
    / "prime-parity"
    / "v1"
    / "prime-agent-0.7.1.json"
)
PROVIDER_ID = "asterion.prime-gateway"


def _pinned_prime_source_root() -> Path:
    configured = os.environ.get("ASTERION_PRIME_SOURCE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (ROOT / "3th-party" / "prime-agent").resolve()


PINNED_SOURCE = _pinned_prime_source_root()
REAL_HARNESS = (
    ROOT
    / "tests"
    / "fixtures"
    / "prime_gateway"
    / "v1"
    / "real-prime-session-context.mjs"
)
MAKEFILE = ROOT / "Makefile"

EXPECTED_MATRIX = {
    "prime-parity.session.branch-summaries-labels": {
        "boundary": "bounded-provider",
        "feature_ids": ("session.branch-summaries-labels",),
        "assertion_ids": (
            "branch-identity-retained",
            "label-set-clear-exact-entry",
            "summary-admitted-budgeted",
            "summary-label-text-private",
        ),
        "fault_ids": (
            "cancel-during-summary",
            "label-replay-conflict",
            "restart-after-summary-result",
            "restart-before-summary-result",
            "stale-entry",
        ),
    },
    "prime-parity.session.compaction": {
        "boundary": "bounded-provider",
        "feature_ids": ("session.compaction",),
        "assertion_ids": (
            "auto-compaction-disabled",
            "budget-admitted-before-model-call",
            "context-usage-monotonic",
            "private-summary",
            "resumable-compacted-context",
        ),
        "fault_ids": (
            "bounded-provider-failure",
            "cancel-during-compaction",
            "restart-after-compaction-result",
            "restart-before-compaction-result",
        ),
    },
    "prime-parity.session.delivery": {
        "boundary": "real-prime-provider-free",
        "feature_ids": ("session.delivery",),
        "assertion_ids": (
            "cancel-before-ownership",
            "direct-idle-ownership",
            "follow-up-next-turn",
            "input-id-exactly-once",
            "steer-current-turn",
        ),
        "fault_ids": (
            "cancel-before-ownership",
            "replay-direct",
            "replay-follow-up",
            "replay-steer",
            "restart-after-admission",
        ),
    },
    "prime-parity.session.fork-clone": {
        "boundary": "real-prime-provider-free",
        "feature_ids": ("session.fork-clone",),
        "assertion_ids": (
            "clone-equals-leaf-fork-at",
            "fork-requested-entry",
            "new-binding-atomically-committed",
            "source-remains-resumable",
        ),
        "fault_ids": (
            "missing-leaf",
            "response-binding-conflict",
            "restart-after-clone-binding",
            "restart-after-clone-result",
            "restart-after-fork-binding",
            "restart-after-fork-result",
        ),
    },
    "prime-parity.session.persistence-naming": {
        "boundary": "real-prime-provider-free",
        "feature_ids": ("session.persistence-naming",),
        "assertion_ids": (
            "active-transcript-continuation-identities-separated",
            "duplicate-rename-idempotent",
            "name-persists-detach-restart",
            "public-name-digest-only",
        ),
        "fault_ids": (
            "conflicting-rename-replay",
            "restart-after-daemon-result-before-commit",
        ),
    },
    "prime-parity.session.resume-delete": {
        "boundary": "real-prime-provider-free",
        "feature_ids": ("session.resume-delete",),
        "assertion_ids": (
            "active-continuation-delete-rejected",
            "exact-continuation-resumed",
            "inactive-exact-artifact-deleted",
            "public-paths-absent",
        ),
        "fault_ids": (
            "delete-after-side-effect-before-commit",
            "restart-after-switch",
            "selector-swap",
            "symlink-replacement",
        ),
    },
    "prime-parity.session.rich-attachments": {
        "boundary": "real-prime-provider-free",
        "feature_ids": ("session.rich-attachments",),
        "assertion_ids": (
            "attachment-causal-to-exact-input",
            "body-private",
            "prime-receives-verified-bytes-once",
            "typed-digest-size-projection",
        ),
        "fault_ids": (
            "body-swap",
            "digest-mismatch",
            "media-mismatch",
            "restart-after-attachment-bind",
            "restart-after-prompt-admission",
            "size-mismatch",
        ),
    },
    "prime-parity.session.tree-navigation": {
        "boundary": "real-prime-provider-free",
        "feature_ids": ("session.tree-navigation",),
        "assertion_ids": (
            "canonical-topology-projected",
            "deterministic-active-leaf",
            "exact-entry-scope",
            "raw-message-label-absent",
        ),
        "fault_ids": (
            "foreign-entry-id",
            "restart-after-navigation",
            "stale-continuation",
        ),
    },
    "prime-parity.session.usage-status": {
        "boundary": "real-prime-provider-free",
        "feature_ids": ("session.usage-status",),
        "assertion_ids": (
            "current-identity",
            "nonnegative-monotonic-counts",
            "private-provider-fields-absent",
            "safe-status-vocabulary",
        ),
        "fault_ids": (
            "malformed-stats",
            "overflow-stats",
            "restart-during-read",
            "stale-generation",
        ),
    },
}

SAFE_CHECKS = {
    "prime-parity.session.branch-summaries-labels": (
        "bounded-authority-absent",
        "gateway-branch-summary-faults-passed",
        "pinned-prime-preflight-passed",
    ),
    "prime-parity.session.compaction": (
        "bounded-authority-absent",
        "gateway-compaction-faults-passed",
        "pinned-prime-preflight-passed",
    ),
    "prime-parity.session.delivery": (
        "daemon-input-admission-capability-passed",
        "gateway-delivery-faults-passed",
        "prime-queue-code-path-passed",
    ),
    "prime-parity.session.fork-clone": (
        "gateway-fork-clone-faults-passed",
        "prime-fork-clone-roundtrip-passed",
        "source-resume-roundtrip-passed",
    ),
    "prime-parity.session.persistence-naming": (
        "gateway-naming-faults-passed",
        "prime-detach-attach-passed",
        "prime-name-roundtrip-passed",
    ),
    "prime-parity.session.resume-delete": (
        "gateway-resume-delete-faults-passed",
        "prime-exact-delete-passed",
        "prime-resume-roundtrip-passed",
    ),
    "prime-parity.session.rich-attachments": (
        "gateway-attachment-faults-passed",
        "prime-image-code-path-passed",
        "private-body-redaction-passed",
    ),
    "prime-parity.session.tree-navigation": (
        "gateway-navigation-faults-passed",
        "prime-tree-navigation-roundtrip-passed",
        "tree-private-content-redaction-passed",
    ),
    "prime-parity.session.usage-status": (
        "gateway-status-faults-passed",
        "prime-status-roundtrip-passed",
        "status-private-fields-redacted",
    ),
}


def _ledger():
    return validate_parity_ledger(json.loads(LEDGER.read_text(encoding="utf-8")))


def _ledger_rows(
    ledger: Mapping[str, object], key: str
) -> tuple[Mapping[str, object], ...]:
    value = ledger[key]
    if not isinstance(value, tuple) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise AssertionError("validated parity ledger rows are invalid")
    return tuple(item for item in value if isinstance(item, Mapping))


def _observations() -> tuple[PrimeSessionContextScenarioObservation, ...]:
    return tuple(
        build_prime_session_context_observation(
            scenario_id=scenario_id,
            status="PASS",
            checks=(
                PRIME_SESSION_CONTEXT_BOUNDED_PASS_CHECK_IDS[scenario_id]
                if scenario_id in PRIME_SESSION_CONTEXT_BOUNDED_SCENARIO_IDS
                else SAFE_CHECKS[scenario_id]
            ),
            real_prime_runtime=True,
            fake_daemon=False,
            provider_operations=(
                2
                if scenario_id in PRIME_SESSION_CONTEXT_BOUNDED_SCENARIO_IDS
                else 0
            ),
            model_credential_reads=(
                1
                if scenario_id in PRIME_SESSION_CONTEXT_BOUNDED_SCENARIO_IDS
                else 0
            ),
        )
        for scenario_id in PRIME_SESSION_CONTEXT_SCENARIO_IDS
    )


def _closed_environment(private_home: Path) -> dict[str, str]:
    environment = {
        key: value
        for key in ("PATH", "SystemRoot", "TEMP", "TMP", "TMPDIR")
        if (value := os.environ.get(key)) is not None
    }
    environment["HOME"] = str(private_home)
    environment["PRIME_AGENT_CODING_AGENT_DIR"] = str(
        private_home.parent / "agent"
    )
    return environment


def _node_22() -> Path | None:
    configured = os.environ.get("ASTERION_PRIME_NODE")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    try:
        npm_environment = {
            key: value
            for key in ("HOME", "PATH", "SystemRoot", "TEMP", "TMP", "TMPDIR")
            if (value := os.environ.get(key)) is not None
        }
        completed = subprocess.run(
            (
                "npm",
                "exec",
                "--offline",
                "--yes",
                "--package=node@22",
                "--",
                "which",
                "node",
            ),
            cwd=ROOT,
            env=npm_environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            candidates.append(Path(completed.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in candidates:
        try:
            version = subprocess.run(
                (str(candidate), "--version"),
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if version.returncode == 0 and version.stdout.startswith("v22."):
                return candidate.resolve()
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def _safe_command_journal_state(agent_dir: Path, socket_path: Path) -> str:
    """Reduce one private command journal to a fixed diagnostic category."""
    try:
        key = hashlib.sha256(str(socket_path).encode("utf-8")).hexdigest()[:12]
        journal = agent_dir / "daemon-workers" / key / "command-journal.jsonl"
        records = [
            json.loads(line)
            for line in journal.read_text(encoding="utf-8").splitlines()
            if line
        ]
        command_id = "asterion-session-context-context-bounded-compact-compact"
        target_key = next(
            (
                record.get("key")
                for record in records
                if isinstance(record, dict)
                and record.get("type") == "received"
                and record.get("commandId") == command_id
                and isinstance(record.get("key"), str)
            ),
            None,
        )
        if target_key is None:
            return "absent"
        types = {
            record.get("type")
            for record in records
            if isinstance(record, dict) and record.get("key") == target_key
        }
        if "acknowledged" in types:
            return "acknowledged"
        if "result" in types:
            return "complete"
        if "received" in types:
            return "pending"
        return "absent"
    except (OSError, UnicodeError, ValueError, TypeError):
        return "unavailable"


class TestPrimeSessionContextParity(unittest.TestCase):
    def test_safe_command_journal_state_follows_the_durable_key(self) -> None:
        command_id = (
            "asterion-session-context-context-bounded-compact-compact"
        )
        client_id = "bounded-test-client"
        key = json.dumps([client_id, command_id], separators=(",", ":"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            socket_path = root / "prime.sock"
            digest = hashlib.sha256(str(socket_path).encode("utf-8")).hexdigest()[:12]
            journal = (
                root / "agent" / "daemon-workers" / digest / "command-journal.jsonl"
            )
            journal.parent.mkdir(parents=True)
            records = [
                {
                    "version": 1,
                    "type": "received",
                    "key": key,
                    "clientId": client_id,
                    "commandId": command_id,
                    "commandType": "compact",
                },
                {
                    "version": 1,
                    "type": "result",
                    "key": key,
                    "response": {"type": "response"},
                },
                {"version": 1, "type": "acknowledged", "key": key},
            ]
            expected = ("pending", "complete", "acknowledged")
            for size, category in enumerate(expected, start=1):
                with self.subTest(category=category):
                    journal.write_text(
                        "\n".join(json.dumps(record) for record in records[:size])
                        + "\n",
                        encoding="utf-8",
                    )
                    self.assertEqual(
                        _safe_command_journal_state(root / "agent", socket_path),
                        category,
                    )

    def test_ledger_and_runner_matrix_are_the_exact_approved_contract(self) -> None:
        ledger = _ledger()
        scenarios = {
            str(item["scenario_id"]): {
                "boundary": item["boundary"],
                "feature_ids": item["feature_ids"],
                "assertion_ids": item["assertion_ids"],
                "fault_ids": item["fault_ids"],
            }
            for item in _ledger_rows(ledger, "scenarios")
            if str(item["scenario_id"]).startswith("prime-parity.session.")
        }

        self.assertEqual(scenarios, EXPECTED_MATRIX)
        self.assertEqual(PRIME_SESSION_CONTEXT_SCENARIO_MATRIX, EXPECTED_MATRIX)
        self.assertEqual(tuple(scenarios), PRIME_SESSION_CONTEXT_SCENARIO_IDS)
        self.assertEqual(len(PRIME_SESSION_CONTEXT_PROVIDER_FREE_SCENARIO_IDS), 7)
        self.assertEqual(len(PRIME_SESSION_CONTEXT_BOUNDED_SCENARIO_IDS), 2)

    def test_all_nine_runners_register_with_their_exact_verified_boundaries(
        self,
    ) -> None:
        registry = ParityScenarioRegistry(_ledger(), provider_id=PROVIDER_ID)
        observations = _observations()

        register_prime_session_context_scenarios(
            registry,
            observations,
            provider_factory=lambda: object(),
        )
        report = asyncio.run(registry.run(PRIME_SESSION_CONTEXT_SCENARIO_IDS))

        self.assertEqual(
            registry.registered_scenario_ids,
            PRIME_SESSION_CONTEXT_SCENARIO_IDS,
        )
        self.assertEqual(report.passed_scenario_ids, PRIME_SESSION_CONTEXT_SCENARIO_IDS)
        self.assertEqual(report.blocking_scenario_ids, ())
        result_by_id = {result.scenario_id: result for result in report.results}
        for observation in observations:
            with self.subTest(scenario_id=observation.scenario_id):
                self.assertEqual(
                    result_by_id[observation.scenario_id].evidence_id,
                    observation.evidence_id,
                )
        self.assertEqual(
            {result.status for result in report.results},
            {"pass"},
        )

    def test_bounded_evidence_can_pass_only_after_a_real_provider_operation(
        self,
    ) -> None:
        scenario_id = "prime-parity.session.compaction"
        observation = build_prime_session_context_observation(
            scenario_id=scenario_id,
            status="PASS",
            checks=PRIME_SESSION_CONTEXT_BOUNDED_PASS_CHECK_IDS[scenario_id],
            real_prime_runtime=True,
            fake_daemon=False,
            provider_operations=1,
            model_credential_reads=0,
        )
        self.assertEqual(
            observation.command_id,
            PRIME_SESSION_CONTEXT_BOUNDED_VERIFICATION_COMMAND_ID,
        )
        registry = ParityScenarioRegistry(_ledger(), provider_id=PROVIDER_ID)
        observations = tuple(
            observation if item.scenario_id == scenario_id else item
            for item in _observations()
        )
        register_prime_session_context_scenarios(
            registry,
            observations,
            provider_factory=lambda: object(),
        )
        report = asyncio.run(registry.run((scenario_id,)))
        self.assertEqual(report.passed_scenario_ids, (scenario_id,))

        with self.assertRaises(ParityScenarioRegistryError):
            build_prime_session_context_observation(
                scenario_id=scenario_id,
                status="PASS",
                checks=PRIME_SESSION_CONTEXT_BOUNDED_PASS_CHECK_IDS[scenario_id],
                real_prime_runtime=True,
                fake_daemon=False,
                provider_operations=0,
                model_credential_reads=0,
            )

    def test_evidence_binds_source_lock_scenario_provider_matrix_and_command(
        self,
    ) -> None:
        for observation in _observations():
            payload = json.loads(observation.serialized_observations)
            expected_command = (
                PRIME_SESSION_CONTEXT_BOUNDED_VERIFICATION_COMMAND_ID
                if observation.scenario_id
                in PRIME_SESSION_CONTEXT_BOUNDED_SCENARIO_IDS
                else PRIME_SESSION_CONTEXT_VERIFICATION_COMMAND_ID
            )
            with self.subTest(scenario_id=observation.scenario_id):
                self.assertEqual(
                    payload["artifact_lock"], PRIME_SESSION_CONTEXT_ARTIFACT_LOCK
                )
                self.assertEqual(
                    payload["source_commit"], PRIME_SESSION_CONTEXT_SOURCE_COMMIT
                )
                self.assertEqual(payload["scenario_id"], observation.scenario_id)
                self.assertEqual(payload["provider_id"], PROVIDER_ID)
                self.assertEqual(payload["command_id"], expected_command)
                self.assertEqual(
                    tuple(payload["assertion_ids"]),
                    EXPECTED_MATRIX[observation.scenario_id]["assertion_ids"],
                )
                self.assertEqual(
                    tuple(payload["fault_ids"]),
                    EXPECTED_MATRIX[observation.scenario_id]["fault_ids"],
                )
                self.assertNotIn(str(ROOT), observation.serialized_observations)

    def test_named_verification_command_is_an_executable_make_target(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")

        self.assertEqual(
            makefile.count(
                f"\n{PRIME_SESSION_CONTEXT_VERIFICATION_COMMAND_ID}:\n"
            ),
            1,
        )
        self.assertIn("tests.test_prime_session_context_parity", makefile)
        self.assertIn("npm --prefix packages/typescript/prime-gateway test", makefile)

    def test_bounded_model_alias_is_normalized_only_at_the_prime_boundary(self) -> None:
        source = REAL_HARNESS.read_text(encoding="utf-8")
        self.assertIn('boundedModel === "deepseek-v4-flash-0731"', source)
        self.assertIn('"deepseek-v4-flash"', source)

    def test_fake_daemon_is_diagnostic_only_and_has_no_evidence_id(self) -> None:
        first = _observations()[0]
        diagnostic = build_prime_session_context_observation(
            scenario_id=first.scenario_id,
            status="PASS",
            checks=SAFE_CHECKS[first.scenario_id],
            real_prime_runtime=False,
            fake_daemon=True,
            provider_operations=0,
            model_credential_reads=0,
        )
        observations = (diagnostic, *_observations()[1:])
        registry = ParityScenarioRegistry(_ledger(), provider_id=PROVIDER_ID)

        self.assertIsNone(diagnostic.evidence_id)
        with self.assertRaises(ParityScenarioRegistryError):
            register_prime_session_context_scenarios(
                registry,
                observations,
                provider_factory=lambda: object(),
            )
        self.assertEqual(registry.registered_scenario_ids, ())

    def test_adapter_rejects_any_provenance_or_digest_drift_atomically(self) -> None:
        base = _observations()
        mutations = (
            base[:-1],
            (replace(base[0], provider_operations=3), *base[1:]),
            (replace(base[0], model_credential_reads=2), *base[1:]),
            (replace(base[0], source_commit="0" * 40), *base[1:]),
            (replace(base[0], evidence_id="evidence.session-context.forged"), *base[1:]),
            (
                replace(
                    base[0],
                    serialized_observations=base[0].serialized_observations
                    + "SENTINEL_SECRET",
                ),
                *base[1:],
            ),
        )
        for observations in mutations:
            registry = ParityScenarioRegistry(_ledger(), provider_id=PROVIDER_ID)
            with self.subTest(size=len(observations)), self.assertRaises(
                ParityScenarioRegistryError
            ):
                register_prime_session_context_scenarios(
                    registry,
                    observations,
                    provider_factory=lambda: object(),
                )
            self.assertEqual(registry.registered_scenario_ids, ())

    @unittest.skipUnless(
        PINNED_SOURCE.is_dir() and REAL_HARNESS.is_file(),
        "external pinned Prime session/context harness is unavailable",
    )
    def test_real_prime_provider_free_scenarios_match_committed_evidence(
        self,
    ) -> None:
        bounded = os.environ.get("ASTERION_PRIME_SESSION_CONTEXT_BOUNDED") == "1"
        node = _node_22()
        if node is None:
            self.skipTest("an offline pinned Node 22 executable is unavailable")
        verify_prime_source(PINNED_SOURCE, node_executable=str(node))
        daemon_entry = (
            PINNED_SOURCE / "packages" / "coding-agent" / "dist" / "bundle" / "cli.js"
        )
        if not daemon_entry.is_file():
            self.skipTest("the pinned Prime daemon bundle is unavailable")

        with tempfile.TemporaryDirectory(
            prefix="asterion-prime-session-context-", dir="/tmp"
        ) as temporary:
            private_root = Path(temporary)
            home = private_root / "home"
            agent_dir = private_root / "agent"
            session_dir = private_root / "sessions"
            workspace = private_root / "workspace"
            for directory in (home, agent_dir, session_dir, workspace):
                directory.mkdir(mode=0o700)
            socket_path = private_root / "prime.sock"
            environment = _closed_environment(home)
            if bounded:
                try:
                    environment.update(resolve_bounded_prime_environment())
                except Exception:
                    self.fail("the bounded Prime session/context environment is unavailable")
                environment["HOME"] = str(home)
                model = environment.get("ASTERION_PRIME_EXPERIMENT_MODEL")
                if not isinstance(model, str) or not model:
                    self.fail("the bounded Prime session/context model is unavailable")
                environment["ASTERION_PRIME_SESSION_CONTEXT_BOUNDED_MODEL"] = model
            daemon = subprocess.Popen(
                (
                    str(node),
                    str(daemon_entry),
                    "--mode",
                    "daemon",
                    "--daemon-socket",
                    str(socket_path),
                ),
                cwd=PINNED_SOURCE,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if socket_path.exists():
                        break
                    if daemon.poll() is not None:
                        self.fail("the pinned Prime daemon did not start")
                    time.sleep(0.025)
                else:
                    self.fail("the pinned Prime daemon did not become ready")

                upstream = subprocess.run(
                    (
                        str(node),
                        "node_modules/vitest/vitest.mjs",
                        "run",
                        "packages/coding-agent/test/suite/agent-session-queue.test.ts",
                        "-t",
                        (
                            "S1: delivers mid-run steering, follow-up, command, "
                            "and custom inputs in order"
                        ),
                        "--reporter=dot",
                    ),
                    cwd=PINNED_SOURCE,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(
                    upstream.returncode,
                    0,
                    "the pinned Prime queue/image code-path check failed",
                )
                completed = subprocess.run(
                    (
                        str(node),
                        str(REAL_HARNESS),
                        str(socket_path),
                        str(PINNED_SOURCE.resolve()),
                        str(workspace),
                        str(agent_dir),
                        str(session_dir),
                    ),
                    cwd=ROOT,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=180 if bounded else 60,
                )
                safe_harness_reasons = tuple(
                    reason
                    for reason in (
                        "real Prime resident creation failed",
                        "real Prime resident identity failed",
                        "real Prime resident identity read failed",
                        "real Prime resident identity disagreement",
                        "real Prime bounded model selection failed",
                        "real Prime fixture open path mismatched",
                        "real Prime fixture open transcript mismatched",
                        "real Prime fixture identity read failed",
                        "real Prime fixture identity disagreement",
                        "real Prime fixture release failed",
                        "real Prime identity separation failed",
                        "real Prime name acknowledgement failed",
                        "real Prime name projection failed",
                        "real Prime resume acknowledgement failed",
                        "real Prime resume daemon rejected",
                        "real Prime resume header identity mismatched",
                        "real Prime resume postcondition failed",
                        "real Prime resume retained initial identity",
                        "real Prime create summary identity mismatched header",
                        "real Prime resume state identity mismatched",
                        "real Prime resume state path mismatched",
                        "real Prime tree projection failed",
                        "real Prime tree custom entry failed",
                        "real Prime label projection failed",
                        "real Prime navigation acknowledgement failed",
                        "real Prime tree navigation failed",
                        "real Prime tree navigation source mismatched",
                        "real Prime tree navigation result mismatched",
                        "real Prime tree navigation target mismatched",
                        "real Prime status projection failed",
                        "real Prime fork acknowledgement failed",
                        "real Prime fork source resume failed",
                        "real Prime clone source leaf failed",
                        "real Prime clone daemon rejected",
                        "real Prime clone retained source identity",
                        "real Prime clone identity disagreement",
                        "real Prime clone retained source path",
                        "real Prime clone postcondition failed",
                        "real Prime clone roundtrip failed",
                        "real Prime clone selected leaf failed",
                        "real Prime clone source resume failed",
                        "real Prime exact deletion failed",
                        "real Prime image fixture resume failed",
                        "real Prime image projection failed",
                        "real Prime prompt cancellation failed",
                        "real Prime bounded compaction failed-failed",
                        "real Prime bounded compaction failed-cancelled",
                        "real Prime bounded compaction failed-rejected",
                        "real Prime bounded compaction failed-uncertain",
                        "real Prime bounded compaction unacknowledged",
                        "real Prime bounded branch summary failed-failed",
                        "real Prime bounded branch summary failed-cancelled",
                        "real Prime bounded branch summary failed-rejected",
                        "real Prime bounded branch summary failed-uncertain",
                        "real Prime bounded branch summary unacknowledged",
                    )
                    if reason in completed.stderr
                )
                if not safe_harness_reasons:
                    safe_harness_reasons = tuple(
                        code
                        for code in (
                            "ERR_MODULE_NOT_FOUND",
                            "PrimeDaemonProtocolError",
                            "PrimeSessionError",
                            "SyntaxError",
                            "TypeError",
                        )
                        if code in completed.stderr
                    )
                location = re.search(
                    r"real-prime-session-context\.mjs:(\d+):(\d+)",
                    completed.stderr,
                )
                safe_location = (
                    f"@{location.group(1)}:{location.group(2)}"
                    if location is not None
                    else ""
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    "the real Prime session/context harness failed: "
                    + (safe_harness_reasons[0] if safe_harness_reasons else "unknown")
                    + safe_location
                    + (
                        " journal=" + _safe_command_journal_state(agent_dir, socket_path)
                        if bounded
                        else ""
                    ),
                )
                payload = json.loads(completed.stdout)
            finally:
                if daemon.poll() is None:
                    daemon.terminate()
                    try:
                        daemon.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        daemon.kill()
                        daemon.wait(timeout=5)

        self.assertEqual(
            set(payload),
            {
                "app_version",
                "daemon_protocol",
                "daemon_schema_revision",
                "fake_daemon",
                "format",
                "model_credential_reads",
                "provider_operations",
                "runtime_build_id",
                "scenario_checks",
            },
        )
        self.assertEqual(
            payload["format"],
            "asterion.prime-session-context-observation/v1",
        )
        self.assertEqual(payload["app_version"], "0.7.1")
        self.assertEqual(payload["daemon_protocol"], 7)
        self.assertEqual(payload["daemon_schema_revision"], 14)
        self.assertIs(payload["fake_daemon"], False)
        self.assertEqual(payload["model_credential_reads"], 1 if bounded else 0)
        self.assertEqual(payload["provider_operations"], 2 if bounded else 0)
        self.assertIsInstance(payload["runtime_build_id"], str)
        self.assertTrue(payload["runtime_build_id"])
        self.assertNotIn(str(PINNED_SOURCE), completed.stdout)
        for sentinel in (
            "PRIVATE_IMAGE_TEXT",
            "PRIVATE_SESSION_NAME",
            "PRIVATE_TREE_BODY",
            "PRIVATE_TREE_LABEL",
        ):
            self.assertNotIn(sentinel, completed.stdout)

        if not bounded:
            continuity = long_session_continuity_observation_from_public_report(
                payload
            )
            self.assertEqual(
                verify_long_session_continuity_receipt(continuity).scenario_id,
                "prime.long-session-continuity/v1",
            )

        observed_checks = payload["scenario_checks"]
        expected_scenario_ids = (
            (*PRIME_SESSION_CONTEXT_PROVIDER_FREE_SCENARIO_IDS,
             *PRIME_SESSION_CONTEXT_BOUNDED_SCENARIO_IDS)
            if bounded
            else PRIME_SESSION_CONTEXT_PROVIDER_FREE_SCENARIO_IDS
        )
        self.assertEqual(tuple(observed_checks), expected_scenario_ids)
        for scenario_id in expected_scenario_ids:
            with self.subTest(scenario_id=scenario_id):
                self.assertTrue(
                    set(observed_checks[scenario_id]).issubset(
                        (
                            PRIME_SESSION_CONTEXT_BOUNDED_PASS_CHECK_IDS[scenario_id]
                            if scenario_id in PRIME_SESSION_CONTEXT_BOUNDED_SCENARIO_IDS
                            else SAFE_CHECKS[scenario_id]
                        )
                    )
                )

        if bounded:
            return

        observations = _observations()
        ledger = _ledger()
        evidence_ids = {
            str(record["evidence_id"])
            for record in _ledger_rows(ledger, "evidence")
        }
        self.assertTrue(
            all(
                observation.evidence_id in evidence_ids
                for observation in observations
            )
        )
        registry = ParityScenarioRegistry(ledger, provider_id=PROVIDER_ID)
        register_prime_session_context_scenarios(
            registry,
            observations,
            provider_factory=lambda: object(),
        )
        report = asyncio.run(
            registry.run(PRIME_SESSION_CONTEXT_PROVIDER_FREE_SCENARIO_IDS)
        )
        self.assertEqual(
            report.passed_scenario_ids,
            PRIME_SESSION_CONTEXT_PROVIDER_FREE_SCENARIO_IDS,
        )

    def test_ledger_promotes_each_result_only_with_its_exact_evidence(self) -> None:
        ledger = _ledger()
        observations = {item.scenario_id: item for item in _observations()}
        evidence = {
            str(item["evidence_id"]): item
            for item in _ledger_rows(ledger, "evidence")
        }
        features = {
            str(item["feature_id"]): item
            for item in _ledger_rows(ledger, "features")
            if item["domain_id"] == "session.context"
        }

        self.assertEqual(len(features), 9)
        for scenario_id, contract in EXPECTED_MATRIX.items():
            observation = observations[scenario_id]
            feature_id = contract["feature_ids"][0]
            result = next(
                item
                for item in _ledger_rows(
                    features[feature_id], "provider_results"
                )
                if item["provider_id"] == PROVIDER_ID
            )
            expected_status = (
                "bounded-pass"
                if scenario_id in PRIME_SESSION_CONTEXT_BOUNDED_SCENARIO_IDS
                else "provider-free-pass"
            )
            with self.subTest(scenario_id=scenario_id):
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(result["evidence_ids"], (observation.evidence_id,))
                evidence_id = observation.evidence_id
                self.assertIsNotNone(evidence_id)
                assert evidence_id is not None
                record = evidence[evidence_id]
                self.assertEqual(record["scenario_ids"], (scenario_id,))
                self.assertEqual(record["feature_ids"], (feature_id,))
                self.assertEqual(record["boundary"], contract["boundary"])


if __name__ == "__main__":
    unittest.main()
