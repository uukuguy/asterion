"""P6 live candidate path with an in-memory model session, no provider call."""

import asyncio
import tempfile
import inspect
import time
import contextlib
import io
import json
from hashlib import sha256
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from asterion.applications.prime.live_model import (
    bounded_text_limits,
    LiveModelReply,
    LiveModelUsage,
)
from asterion.applications.prime.p6.live import run_live_candidate, run_operator_live
from asterion.applications.prime.p6.operator import P6OperatorError
from asterion.agents.prime import application
from asterion.agents.prime.application import (
    PrimeApplicationSpec, PrimeOperatorContext, prepare_prime_application,
)
from asterion.agents.prime.deadline import TaskDeadline


def _prime(root, *, deadline=None, model="deepseek-flash"):
    context = PrimeOperatorContext(
        executable=Path("/fake/node"), entry=Path("/fake/pi"), cwd=root.absolute(),
        provider="deepseek", model=model, effort="off", environment={},
        task_deadline=deadline if deadline is not None else TaskDeadline(
            deadline_monotonic=time.monotonic() + 120,
            deadline_epoch=time.time() + 120,
        ),
    )
    return prepare_prime_application(
        PrimeApplicationSpec("prime.continual-improvement", "1.0.0", "text-only"),
        context, authorization=bounded_text_limits(),
    )


def _owned_session(session, usage):
    prompt, close = session.prompt, session.close
    reaped = False

    async def measured_prompt(text, *, signal):
        usage.prompts += 1
        try:
            reply = await prompt(text, signal=signal)
        except BaseException:
            usage.blocked = usage.unknown_effect = True
            raise
        usage.input_tokens += reply.usage.input_tokens
        usage.output_tokens += reply.usage.output_tokens
        return reply

    async def owned_close():
        nonlocal reaped
        if not reaped:
            await close()
            reaped = True

    session.prompt, session.close = measured_prompt, owned_close
    return session


class _Session:
    def __init__(self, answer: str):
        self.answer = answer
        self.prompts: list[str] = []
        self.closed = False
        self.opened = False

    async def open(self, *, signal):
        self.opened = True

    async def prompt(self, text: str, *, signal):
        self.prompts.append(text)
        return LiveModelReply(self.answer, LiveModelUsage(1000, 500, 900))

    async def close(self):
        self.closed = True


class TestP6Live(unittest.IsolatedAsyncioTestCase):
    async def _invoke(self, session, root, *, prime=None, **kwargs):
        prime = _prime(root) if prime is None else prime
        with patch.object(
            application, "LiveModelSession",
            side_effect=lambda **material: _owned_session(session, material["usage"]),
        ):
            return await run_live_candidate(prime=prime, private_root=root, **kwargs)

    def test_entry_accepts_prime_owner_without_startup_factory(self):
        parameters = inspect.signature(run_live_candidate).parameters
        self.assertIn("prime", parameters)
        self.assertNotIn("session_factory", parameters)

    async def test_generation_happens_after_runtime_started(self):
        from asterion.applications.prime.p6.runtime_binding import _P6RuntimeSession

        observed = []
        original_run = _P6RuntimeSession.run
        prompt_events = []

        async def observe(runtime, request, *, signal=None):
            async for event in original_run(runtime, request, signal=signal):
                observed.append(event.type)
                yield event

        class OrderedSession(_Session):
            async def prompt(self, text, *, signal):
                prompt_events.append(tuple(observed))
                if signal.cancelled:
                    raise AssertionError("cancelled model effect")
                return await super().prompt(text, signal=signal)

        session = OrderedSession('{"multiplier":3,"offset":1}')
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            _P6RuntimeSession, "run", observe
        ):
            await self._invoke(
                session, Path(temporary),
                root_run_id="p6-live-ordered",
            )
        self.assertIn("run.started", prompt_events[0])

    async def test_pre_cancelled_has_zero_model_file_and_admission_effects(self):
        from asterion.applications.prime.services import CandidateStoreLoop

        class Cancelled:
            cancelled = True

        session = _Session('{"multiplier":3,"offset":1}')
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            CandidateStoreLoop, "admit_candidate", side_effect=AssertionError("admitted")
        ) as admission:
            root = Path(temporary)
            with self.assertRaises(P6OperatorError):
                await self._invoke(
                    session, Path(temporary),
                    root_run_id="p6-live-cancelled",
                    signal=Cancelled(),
                )
            self.assertEqual(session.prompts, [])
            self.assertFalse(session.opened)
            self.assertFalse((root / "candidate.json").exists())
            admission.assert_not_called()

    async def test_model_candidate_is_admitted_evaluated_and_rolled_back(self):
        session = _Session('{"multiplier":3,"offset":1}')
        with tempfile.TemporaryDirectory() as temporary:
            result = await self._invoke(
                session, Path(temporary),
                root_run_id="p6-live-one",
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.terminal_outcome, "rolled-back")
            self.assertEqual(result.rollback_invocation_count, 1)
            self.assertNotEqual(
                result.candidate_revision_digest, result.baseline_snapshot_digest
            )
            self.assertEqual(len(session.prompts), 1)
            self.assertNotIn("-3", session.prompts[0], "holdout inputs reached model")
            self.assertTrue(session.closed)

            self.assertTrue((Path(temporary) / "candidate.json").is_file())
            self.assertTrue((Path(temporary) / "holdout-evidence.json").is_file())
            self.assertEqual(result.model_call_count, 1)
            self.assertEqual(
                (result.input_tokens, result.output_tokens, result.cost_micros),
                (1000, 500, 900),
            )
            self.assertEqual(
                result.private_evidence_sha256,
                sha256(
                    (Path(temporary) / "holdout-evidence.json").read_bytes()
                ).hexdigest(),
            )
            self.assertNotIn("multiplier", repr(result))

    async def test_invalid_candidate_fails_before_admission_and_closes(self):
        session = _Session("PRIVATE invalid candidate")
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(Exception) as caught:
                await self._invoke(
                    session, Path(temporary),
                    root_run_id="p6-live-invalid",
                )
            self.assertNotIn("PRIVATE", str(caught.exception))
            self.assertTrue(session.closed)
            self.assertFalse((Path(temporary) / "candidate.json").exists())

    async def test_non_improving_candidate_rolls_back(self):
        session = _Session('{"multiplier":2,"offset":0}')
        with tempfile.TemporaryDirectory() as temporary:
            result = await self._invoke(
                session, Path(temporary),
                root_run_id="p6-live-regressed",
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.terminal_outcome, "rolled-back")
            self.assertEqual(result.rollback_invocation_count, 1)
            self.assertTrue(session.closed)

    async def test_direct_execution_does_not_require_central_registration(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("asterion.applications.provider.compose_installed_provider",
                  side_effect=AssertionError("central composition")),
            patch("asterion.applications.prime.inventory.prime_application_index",
                  side_effect=AssertionError("central inventory")),
            patch("asterion.applications.prime.inventory.prime_release_application",
                  side_effect=AssertionError("central lookup")),
        ):
            result = await self._invoke(
                _Session('{"multiplier":3,"offset":1}'), Path(temporary),
                root_run_id="p6-direct",
            )
        self.assertEqual(result.terminal_outcome, "rolled-back")
        self.assertEqual(result.rollback_invocation_count, 1)

    async def test_candidate_revision_projects_owner_usage_once(self):
        from asterion.applications.prime.p6 import live

        original_open = live._open_candidate_store_for_run
        coordinators = []

        async def capture(**kwargs):
            loop, coordinator = await original_open(**kwargs)
            coordinators.append(coordinator)
            return loop, coordinator

        for answer in ('{"multiplier":3,"offset":1}', '{"multiplier":2,"offset":0}'):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as temporary:
                prime = _prime(Path(temporary))
                with patch.object(live, "_open_candidate_store_for_run", capture):
                    result = await self._invoke(
                        _Session(answer), Path(temporary), prime=prime,
                        root_run_id="p6-usage",
                    )
                history = coordinators[-1].history()
                self.assertEqual(history[0].proposal_id, "candidate-1")
                self.assertEqual(history[0].usage["aggregate_tokens"], 1500)
                self.assertEqual(history[0].usage["cost_micros"], 900)
                self.assertEqual(history[0].usage["provider_operations"], 1)
                self.assertTrue(all(not any(revision.usage.values()) for revision in history[1:]))
                self.assertEqual(prime._text_usage_summary().cost_micros, 900)
                self.assertEqual(result.cost_micros, 900)

    async def test_generation_failure_never_admits_and_retains_unknown_effect(self):
        from asterion.applications.prime.p6 import live

        class FailedSession(_Session):
            async def prompt(self, text, *, signal):
                self.prompts.append(text)
                raise RuntimeError("PRIVATE-MODEL-PAYLOAD")

        hosts = []
        original_host = live._ComposedCandidateHost

        def host(*args, **kwargs):
            value = original_host(*args, **kwargs)
            hosts.append(value)
            return value

        for answer in (None, "PRIVATE-invalid-candidate"):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                prime = _prime(root)
                session = FailedSession("") if answer is None else _Session(answer)
                with patch.object(live, "_ComposedCandidateHost", host), patch.object(
                    live, "_run_workflow", side_effect=AssertionError("admitted")
                ) as workflow:
                    with self.assertRaises(live.P6OperatorError) as caught:
                        await self._invoke(session, root, prime=prime, root_run_id="p6-failed")
                    workflow.assert_not_called()
                self.assertNotIn("PRIVATE", str(caught.exception))
                self.assertEqual(hosts[-1].effects_state, "unchanged")
                self.assertEqual(hosts[-1].coordinator.snapshot().entries, ())
                self.assertIsNone(hosts[-1].receipt)
                self.assertTrue(session.closed)
                self.assertFalse((root / "candidate.json").exists())
                self.assertEqual(prime._text_usage_summary().unknown_effect, answer is None)

    async def test_cleanup_failure_prevents_admission_and_public_success(self):
        from asterion.applications.prime.p6 import live

        class UnreapedSession(_Session):
            async def close(self):
                raise RuntimeError("PRIVATE-CLEANUP")

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            live, "_run_workflow", side_effect=AssertionError("admitted")
        ) as workflow:
            with self.assertRaises(live.P6OperatorError) as caught:
                await self._invoke(
                    UnreapedSession('{"multiplier":3,"offset":1}'), Path(temporary),
                    root_run_id="p6-cleanup-failed",
                )
            workflow.assert_not_called()
            self.assertFalse((Path(temporary) / "candidate.json").exists())
            self.assertNotIn("PRIVATE", str(caught.exception))

    async def test_model_cancellation_closes_without_candidate_effects(self):
        class CancellingSession(_Session):
            async def prompt(self, text, *, signal):
                raise asyncio.CancelledError()

        session = CancellingSession("")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(asyncio.CancelledError):
                await self._invoke(session, root, root_run_id="p6-model-cancelled")
            self.assertTrue(session.closed)
            self.assertFalse((root / "candidate.json").exists())

    async def test_runtime_cap_never_widens_text_authorization_or_model(self):
        from asterion.applications.prime.p6 import live

        for change in ("wide-cost", "wrong-model"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                prime = _prime(root, model="deepseek-v4-flash" if change == "wrong-model" else "deepseek-flash")
                limits = bounded_text_limits()
                if change == "wide-cost":
                    limits = replace(limits, max_cost_micros=300_000)
                with patch.object(application, "LiveModelSession") as launch:
                    with self.assertRaises(live.P6OperatorError):
                        await run_live_candidate(
                            prime=prime, root_run_id="p6-invalid-grant", private_root=root,
                            limits=limits,
                        )
                    launch.assert_not_called()
                self.assertFalse((root / "candidate.json").exists())

    async def test_generation_and_workflow_share_nonrenewing_deadline(self):
        from asterion.applications.prime.p6 import live

        clock = [100.0]
        deadline = TaskDeadline(
            deadline_monotonic=130.0, deadline_epoch=130.0,
            monotonic_clock=lambda: clock[0], wall_clock=lambda: clock[0],
        )
        original_workflow = live._run_workflow
        coordinators = []

        class SlowSession(_Session):
            async def prompt(self, text, *, signal):
                clock[0] += 20
                return await super().prompt(text, signal=signal)

        async def exhaust_in_workflow(resources, loop, coordinator, signal, **kwargs):
            self.assertEqual(deadline.remaining_seconds(), 10.0)
            self.assertFalse(signal.cancelled)
            coordinators.append(coordinator)
            clock[0] += 11
            self.assertTrue(signal.cancelled)
            return await original_workflow(resources, loop, coordinator, signal, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prime = _prime(root, deadline=deadline)
            with patch.object(live, "_run_workflow", exhaust_in_workflow):
                with self.assertRaises(live.P6OperatorError):
                    await self._invoke(
                        SlowSession('{"multiplier":3,"offset":1}'), root,
                        prime=prime, root_run_id="p6-deadline",
                    )
            self.assertIs(prime.task_deadline, deadline)
            self.assertEqual(deadline.remaining_seconds(), 0.0)
            self.assertEqual(coordinators[0].snapshot().entries, ())
            self.assertFalse((root / "holdout-evidence.json").exists())


class TestP6LiveOperator(unittest.TestCase):
    def test_two_operator_runs_use_distinct_private_children_and_safe_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / "private"
            context = _prime(root)._operator
            output = io.StringIO()
            environment = {
                "ASTERION_PRIME_OPERATOR_ROOT": str(root),
                "ASTERION_PRIME_P6_PRIVATE_ROOT": str(private),
            }
            with (
                patch(
                    "asterion.applications.prime.p6.live.resolve_live_model_context",
                    return_value=context,
                ),
                patch.object(
                    application, "LiveModelSession",
                    side_effect=lambda **material: _owned_session(
                        _Session('{"multiplier":3,"offset":1}'), material["usage"],
                    ),
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(run_operator_live(environment), 0)
                self.assertEqual(run_operator_live(environment), 0)
            records = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(
                [record["status"] for record in records], ["completed", "completed"]
            )
            self.assertEqual([record["model_call_count"] for record in records], [1, 1])
            self.assertEqual([record["cost_micros"] for record in records], [900, 900])
            self.assertEqual(len(list(private.glob("*/candidate.json"))), 2)
            self.assertNotIn("multiplier", output.getvalue())

    def test_operator_preflight_failure_has_generic_public_result(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(
                run_operator_live({"DEEPSEEK_API_KEY": "PRIVATE-CREDENTIAL"}), 2
            )
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "failed", "reason": "p6-live-unavailable"},
        )
