"""Adversarial checks against the actual P5 host evidence reducer."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from asterion.applications.prime_agent.operator import p5_development_host as host
from tests.test_prime_p5_development_host import _Gateway, _Provider, _Worker


async def _run(
    worker: object,
    *,
    gateway: object | None = None,
    goal: str = "prime.bounded-autonomy/v1",
):
    return await host.run_p5_development_lifecycle(
        gateway=_Gateway() if gateway is None else gateway,
        provider=_Provider(),
        worker=worker,
        run_id="run",
        session_id="session",
        container_id="untrusted-caller-id",
        goal_id=goal,
    )


class TestP5EvidenceBoundaries(unittest.TestCase):
    def test_cleanup_finishes_absence_audit_then_propagates_cancellation(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_docker import (
            P5DevelopmentDockerWorkerService,
        )
        from tests.test_prime_p5_development_docker import _Transport

        async def exercise() -> None:
            started, release = asyncio.Event(), asyncio.Event()

            class DelayedRemove(_Transport):
                async def remove_p5(self, *_: object) -> None:
                    started.set()
                    await release.wait()
                    self.removed = True

            transport = DelayedRemove()
            worker = P5DevelopmentDockerWorkerService(
                image_digest="sha256:" + "a" * 64,
                transport=transport,
                run_id="run",
                session_id="session",
                goal_id="goal",
            )
            await worker.acquire()
            task = asyncio.create_task(worker.cleanup())
            await started.wait()
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(transport.removed)
            self.assertTrue(transport.absent)

        asyncio.run(exercise())

    def test_wrong_clamp_cannot_get_success_from_bound_artifact(self) -> None:
        class WrongClamp(_Worker):
            async def snapshot(self):
                if self.cells == 2:
                    return {
                        "solution.py": b"def clamp(value, lower, upper):\n    return min(max(upper, upper), upper)\n"
                    }
                return await super().snapshot()

        with self.assertRaises(host.PrimeP5DevelopmentHostError):
            asyncio.run(_run(WrongClamp()))

    def test_function_definition_effects_are_rejected(self) -> None:
        for source in (
            b"@arbitrary\ndef clamp(value, lower, upper):\n    return min(max(value, lower), upper)\n",
            b"def clamp(value, lower, upper=arbitrary()):\n    return min(max(value, lower), upper)\n",
            b"def clamp(value, lower, upper) -> arbitrary():\n    return min(max(value, lower), upper)\n",
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                host.validate_p5_development_snapshot(source, repaired=True)

    def test_changed_artifact_bindings_fail_before_quality_evaluation(self) -> None:
        for field, wrong in (
            ("run_id", "another-run"),
            ("goal_id", "another-goal"),
            ("goal_sha256", "sha256:" + "0" * 64),
            ("source_sha256", "sha256:" + "0" * 64),
            ("stage", 2),
            ("stage", True),
        ):

            class Tampered(_Worker):
                async def artifact(self):
                    value = json.loads(await super().artifact())
                    value[field] = wrong
                    return json.dumps(
                        value, sort_keys=True, separators=(",", ":")
                    ).encode()

            with (
                self.subTest(field=field, wrong=wrong),
                patch.object(host, "_gates", wraps=host._gates) as gates,
            ):
                with self.assertRaises(host.PrimeP5DevelopmentHostError):
                    asyncio.run(_run(Tampered()))
                self.assertEqual(gates.call_count, 0)

    def test_unchanged_source_never_runs_second_quality_gate(self) -> None:
        class Unchanged(_Worker):
            async def snapshot(self):
                return {"solution.py": host._INITIAL_SOURCE}

        with patch.object(host, "_gates", wraps=host._gates) as gates:
            with self.assertRaises(host.PrimeP5DevelopmentHostError):
                asyncio.run(_run(Unchanged()))
            self.assertEqual(gates.call_count, 1)

    def test_missing_or_changed_daemon_identity_is_rejected(self) -> None:
        class Missing(_Worker):
            daemon_id = None

        class Changed(_Worker):
            @property
            def daemon_id(self):
                return ("b" if self.cells == 2 else "a") * 64

        for worker in (Missing(), Changed()):
            with (
                self.subTest(worker=type(worker).__name__),
                self.assertRaises(host.PrimeP5DevelopmentHostError),
            ):
                asyncio.run(_run(worker))

    def test_unrelated_goal_rejected_before_acquisition(self) -> None:
        class Unopened(_Worker):
            async def acquire(self):
                raise AssertionError("must not acquire for an unrelated goal")

        with self.assertRaises(host.PrimeP5DevelopmentHostError):
            asyncio.run(_run(Unopened(), goal="another-goal"))


if __name__ == "__main__":
    unittest.main()
