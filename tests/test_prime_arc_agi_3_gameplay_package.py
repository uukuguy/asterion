"""Scoreless gameplay contract and selected implementation boundary tests."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from hashlib import sha256
import json
import unittest

from asterion.applications.prime.p7.prompt import P7_LEGACY_SOLVE_PROMPT, P7_SOLVE_PROMPT
from asterion.capabilities.execution import CapabilityInvocation
from asterion.runtime.host import RunEvent, RuntimeManifest


def evidence(**changes):
    from asterion.capabilities.prime_arc_agi_3_gameplay.host import (
        PrimeArcAgi3GameplayEvidence,
    )

    values = dict(
        run_id="gameplay-run",
        game_id="ls20-9607627b",
        guid="PRIVATE-GUID",
        win_levels=2,
        action_cap=100,
        completed_level_count=2,
        primitive_action_count=12,
        sdk_state="WIN",
        terminal_reason="game-won",
        trace_sha256="sha256:" + "a" * 64,
    )
    values.update(changes)
    return PrimeArcAgi3GameplayEvidence.create(**values)


class Runtime:
    manifest = RuntimeManifest("asterion.prime", ("prime.tool.ipython",))

    def __init__(self, value, *, artifact_id="prime.p7-gameplay-run.evidence"):
        self.value = value
        self.artifact_id = artifact_id
        self.requests = []

    async def run(self, request, *, signal=None):
        self.requests.append(request)
        yield RunEvent(
            request.run_id, 1, "run.started", {"capabilities": ["prime.tool.ipython"]}
        )
        yield RunEvent(
            request.run_id,
            2,
            "artifact.created",
            {
                "artifact": {
                    "artifact_id": self.artifact_id,
                    "kind": "p7-gameplay-run",
                    "media_type": "application/vnd.asterion.prime.p7-gameplay-run+json",
                    "sha256": self.value.evidence_sha256.removeprefix("sha256:"),
                }
            },
        )
        yield RunEvent(request.run_id, 3, "run.completed", {"status": "completed"})


class Accessor:
    def __init__(self, value):
        self.value = value

    def get_evidence(self, *, run_id, evidence_sha256):
        return self.value


def execute(
    value,
    *,
    accessor=None,
    artifact_id="prime.p7-gameplay-run.evidence",
    prompt=P7_SOLVE_PROMPT,
    runtime=None,
):
    from asterion.capabilities.prime_arc_agi_3_gameplay.provider import (
        CAPABILITY_REF,
        PrimeArcAgi3GameplayImplementation,
    )

    runtime = runtime or Runtime(value, artifact_id=artifact_id)
    invocation = CapabilityInvocation(
        capability_ref=CAPABILITY_REF,
        manifest={
            "kind": "capability",
            "capability_id": CAPABILITY_REF.capability_id,
            "version": "1.0.0",
        },
        run_id=value.run_id,
        input_text=prompt,
        upstream_artifacts=(),
        runtime=runtime,
        host_services={"prime.arc-run-evidence": accessor or Accessor(value)},
    )
    return asyncio.run(PrimeArcAgi3GameplayImplementation().execute(invocation))


class TestGameplayEvidence(unittest.TestCase):
    def test_only_shared_application_prompt_digest_is_admitted(self):
        from asterion.capabilities.prime_arc_agi_3_gameplay.provider import (
            P7_LEGACY_SOLVE_PROMPT_SHA256, P7_SOLVE_PROMPT_SHA256, _matches_p7_prompt,
        )

        domain = b"asterion.prime-p7-solve-prompt/v1\0"
        self.assertEqual(
            P7_SOLVE_PROMPT_SHA256,
            sha256(domain + P7_SOLVE_PROMPT.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            P7_LEGACY_SOLVE_PROMPT_SHA256,
            sha256(domain + P7_LEGACY_SOLVE_PROMPT.encode("utf-8")).hexdigest(),
        )
        self.assertTrue(_matches_p7_prompt(P7_LEGACY_SOLVE_PROMPT))

    def test_package_exists(self):
        from importlib.util import find_spec

        self.assertIsNotNone(
            find_spec("asterion.capabilities.prime_arc_agi_3_gameplay")
        )

    def test_sealed_immutable_and_public_safe(self):
        value = evidence()
        with self.assertRaises(FrozenInstanceError):
            value.guid = "changed"
        artifact = execute(value).artifacts[0]
        public = json.dumps(dict(artifact["value"]))
        self.assertEqual(artifact["value"]["outcome"], "game-won")
        self.assertEqual(artifact["value"]["game_id"], "ls20-9607627b")
        for secret in (
            "PRIVATE-GUID",
            "guid",
            "frame",
            "baseline",
            "partial_game_score",
            "trace_sha256",
        ):
            self.assertNotIn(secret, public)
        self.assertNotIn("PRIVATE-GUID", repr(value))

    def test_failed_zero_progress_is_honest(self):
        for state, reason, count in (
            ("NOT_FINISHED", "action-cap", 100),
            ("GAME_OVER", "game-over", 12),
            ("NOT_PLAYED", "engine-uncertain", 0),
        ):
            with self.subTest(reason=reason):
                value = evidence(
                    sdk_state=state,
                    terminal_reason=reason,
                    completed_level_count=0,
                    primitive_action_count=count,
                )
                self.assertEqual(
                    execute(value).artifacts[0]["value"]["outcome"], "failed"
                )

    def test_invalid_evidence_rejected(self):
        from asterion.capabilities.prime_arc_agi_3_gameplay.host import (
            PrimeArcAgi3GameplayEvidenceError,
        )

        for change in (
            {"completed_level_count": 1},
            {"sdk_state": "NOT_FINISHED"},
            {"primitive_action_count": 101},
            {"win_levels": True},
            {"game_id": "ls20"},
            {"guid": ""},
            {"trace_sha256": "bad"},
            {"terminal_reason": "unknown"},
        ):
            with (
                self.subTest(change=change),
                self.assertRaises(PrimeArcAgi3GameplayEvidenceError),
            ):
                evidence(**change)

    def test_mismatch_tampering_and_old_artifact_rejected(self):
        from asterion.capability_sdk import CapabilityExecutionError

        value = evidence()
        forged = evidence()
        object.__setattr__(forged, "guid", "tampered")
        for accessor in (
            Accessor(forged),
            Accessor(evidence(run_id="other-run")),
            Accessor(evidence(primitive_action_count=13)),
        ):
            with (
                self.subTest(accessor=accessor),
                self.assertRaises(CapabilityExecutionError),
            ):
                execute(value, accessor=accessor)
        with self.assertRaises(CapabilityExecutionError):
            execute(value, artifact_id="prime.p7-solving.receipt")
        with self.assertRaises(CapabilityExecutionError):
            execute(value, prompt="arbitrary task")

    def test_canonical_digest_and_extra_fields(self):
        from asterion.capabilities.prime_arc_agi_3_gameplay.host import (
            validate_prime_arc_agi_3_gameplay_evidence,
            PrimeArcAgi3GameplayEvidenceError,
        )

        value = evidence()
        unsigned = {
            key: item for key, item in vars(value).items() if key != "evidence_sha256"
        }
        expected = (
            "sha256:"
            + sha256(
                json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        self.assertEqual(value.evidence_sha256, expected)
        self.assertEqual(evidence().evidence_sha256, expected)
        object.__setattr__(value, "frame", "PRIVATE-FRAME")
        with self.assertRaises(PrimeArcAgi3GameplayEvidenceError):
            validate_prime_arc_agi_3_gameplay_evidence(value)

    def test_cancelled_stream_and_missing_service(self):
        from asterion.capability_sdk import CapabilityExecutionError

        class CancelledRuntime(Runtime):
            async def run(self, request, *, signal=None):
                yield RunEvent(
                    request.run_id,
                    1,
                    "run.started",
                    {"capabilities": ["prime.tool.ipython"]},
                )
                yield RunEvent(
                    request.run_id, 2, "run.completed", {"status": "cancelled"}
                )

        value = evidence()
        with self.assertRaises(asyncio.CancelledError):
            execute(value, runtime=CancelledRuntime(value))
        runtime = Runtime(value)
        with self.assertRaises(CapabilityExecutionError):
            execute(value, runtime=runtime, accessor=object())
        self.assertEqual(runtime.requests, [])

    def test_accessor_exception_is_redacted(self):
        import traceback
        from asterion.capability_sdk import CapabilityExecutionError

        class FailingAccessor:
            def get_evidence(self, **kwargs):
                raise ValueError("PRIVATE-FRAME PRIVATE-GUID")

        try:
            execute(evidence(), accessor=FailingAccessor())
        except CapabilityExecutionError:
            rendered = traceback.format_exc()
            self.assertNotIn("PRIVATE-FRAME", rendered)
            self.assertNotIn("PRIVATE-GUID", rendered)
        else:
            self.fail("expected rejection")

    def test_registered_manifest_is_distinct(self):
        from asterion.applications.first_party_packages import (
            builtin_capability_registrations,
        )
        from asterion.capabilities.prime_arc_agi_3_gameplay.provider import (
            create_prime_arc_agi_3_gameplay_package,
        )

        package = create_prime_arc_agi_3_gameplay_package()
        self.assertEqual(package.package_ref.package_id, "prime-arc-agi-3-gameplay")
        self.assertEqual(len(package.implementations), 1)
        self.assertTrue(
            any(
                row.package_ref == package.package_ref
                for row in builtin_capability_registrations()
            )
        )


if __name__ == "__main__":
    unittest.main()
