"""Generic Prime preset runtime bridge tests."""

from __future__ import annotations

import asyncio
import unittest

from asterion.runtime.host import CancellationSignal, RunEvent, RunRequest
from asterion.runtimes.prime_agent import (
    PRIME_IPYTHON_CAPABILITY,
    PrimeAgentRuntimeError,
    PrimePresetExecutionProfile,
    PrimePresetRuntimeClient,
)
from asterion.runtimes.prime_agent_host import (
    PrimePresetExecutionCancelled,
    PrimePresetExecutionContractError,
    PrimePresetExecutionRequest,
    PrimePresetExecutionResult,
)


class _PresetService:
    def __init__(self, result: PrimePresetExecutionResult | BaseException) -> None:
        self.result = result
        self.requests: list[PrimePresetExecutionRequest] = []

    async def execute(
        self,
        request: PrimePresetExecutionRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> PrimePresetExecutionResult:
        del signal
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class _CancelledSignal(CancellationSignal):
    @property
    def cancelled(self) -> bool:
        return True


PROFILE = PrimePresetExecutionProfile(
    input_preset="solve-first-public-level",
    scope="p7-solving",
    promotion="unpromoted",
    artifact_id="prime.p7-solving.receipt",
    kind="p7-solving",
    media_type="application/vnd.asterion.prime.p7-solving-receipt+json",
)


class TestPrimePresetRuntime(unittest.TestCase):
    def _request(self, *, run_id: str = "runtime/v1 run") -> RunRequest:
        return RunRequest(
            run_id=run_id,
            input_text=PROFILE.input_preset,
            requested_capabilities=(PRIME_IPYTHON_CAPABILITY,),
        )

    async def _collect(
        self,
        service: _PresetService,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> tuple[RunEvent, ...]:
        runtime = PrimePresetRuntimeClient(service, profile=PROFILE)
        return tuple([event async for event in runtime.run(request, signal=signal)])

    def test_projects_a_preset_receipt_as_the_safe_three_event_stream(self) -> None:
        run_id = "runtime/v1 run"
        service = _PresetService(
            PrimePresetExecutionResult(
                run_id=run_id,
                receipt_sha256="sha256:" + "a" * 64,
                scope="p7-solving",
                promotion="unpromoted",
            )
        )

        events = asyncio.run(self._collect(service, self._request(run_id=run_id)))

        self.assertEqual(
            events,
            (
                RunEvent(
                    run_id=run_id,
                    sequence=1,
                    type="run.started",
                    payload={"capabilities": [PRIME_IPYTHON_CAPABILITY]},
                ),
                RunEvent(
                    run_id=run_id,
                    sequence=2,
                    type="artifact.created",
                    payload={
                        "artifact": {
                            "artifact_id": "prime.p7-solving.receipt",
                            "kind": "p7-solving",
                            "media_type": "application/vnd.asterion.prime.p7-solving-receipt+json",
                            "sha256": "a" * 64,
                        }
                    },
                ),
                RunEvent(
                    run_id=run_id,
                    sequence=3,
                    type="run.completed",
                    payload={"status": "completed"},
                ),
            ),
        )
        self.assertEqual(
            service.requests,
            [PrimePresetExecutionRequest(run_id, PROFILE.input_preset)],
        )

    def test_host_values_reject_malformed_preset_results(self) -> None:
        with self.assertRaises(PrimePresetExecutionContractError):
            PrimePresetExecutionRequest("run", "wrong preset")
        cases = (
            {"run_id": "", "receipt_sha256": "sha256:" + "a" * 64, "scope": "p7-solving", "promotion": "unpromoted"},
            {"run_id": "run", "receipt_sha256": "not-a-digest", "scope": "p7-solving", "promotion": "unpromoted"},
            {"run_id": "run", "receipt_sha256": "sha256:" + "a" * 64, "scope": "P7", "promotion": "unpromoted"},
            {"run_id": "run", "receipt_sha256": "sha256:" + "a" * 64, "scope": "p7-solving", "promotion": "promoted"},
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(PrimePresetExecutionContractError):
                PrimePresetExecutionResult(**value)

    def test_rejects_undeclared_requests_before_calling_the_service(self) -> None:
        service = _PresetService(
            PrimePresetExecutionResult(
                run_id="unused",
                receipt_sha256="sha256:" + "a" * 64,
                scope="p7-solving",
                promotion="unpromoted",
            )
        )
        cases = (
            RunRequest(
                run_id="runtime/v1 run",
                input_text="wrong-preset",
                requested_capabilities=(PRIME_IPYTHON_CAPABILITY,),
            ),
            RunRequest(
                run_id="runtime/v1 run",
                input_text=PROFILE.input_preset,
                requested_capabilities=("prime.tool.extra", PRIME_IPYTHON_CAPABILITY),
            ),
            RunRequest(
                run_id="runtime/v1 run",
                input_text=PROFILE.input_preset,
                requested_capabilities=(PRIME_IPYTHON_CAPABILITY,),
                deadline_ms=1,
            ),
        )
        for request in cases:
            with self.subTest(request=request), self.assertRaisesRegex(
                PrimeAgentRuntimeError, "not declared"
            ):
                asyncio.run(self._collect(service, request))
        self.assertEqual(service.requests, [])

    def test_projects_mismatched_host_results_as_safe_failure(self) -> None:
        valid = dict(
            run_id="runtime/v1 run",
            receipt_sha256="sha256:" + "a" * 64,
            scope="p7-solving",
            promotion="unpromoted",
        )

        def unchecked(**changes: str) -> PrimePresetExecutionResult:
            result = object.__new__(PrimePresetExecutionResult)
            for field, value in {**valid, **changes}.items():
                object.__setattr__(result, field, value)
            return result

        for result in (
            PrimePresetExecutionResult(
                run_id="other", receipt_sha256="sha256:" + "a" * 64, scope="p7-solving", promotion="unpromoted"
            ),
            PrimePresetExecutionResult(
                run_id="runtime/v1 run", receipt_sha256="sha256:" + "a" * 64, scope="other", promotion="unpromoted"
            ),
            unchecked(promotion="promoted"),
        ):
            with self.subTest(result=result):
                events = asyncio.run(self._collect(_PresetService(result), self._request()))
                self.assertEqual(tuple(event.type for event in events), ("run.started", "run.failed"))

    def test_precancelled_signal_projects_the_cancelled_two_event_stream(self) -> None:
        service = _PresetService(RuntimeError("must not run"))

        events = asyncio.run(
            self._collect(service, self._request(), signal=_CancelledSignal())
        )

        self.assertEqual(tuple(event.type for event in events), ("run.started", "run.completed"))
        self.assertEqual(events[-1].payload, {"status": "cancelled"})
        self.assertEqual(service.requests, [])

    def test_service_cancellation_projects_the_cancelled_two_event_stream(self) -> None:
        events = asyncio.run(
            self._collect(_PresetService(PrimePresetExecutionCancelled()), self._request())
        )

        self.assertEqual(
            events,
            (
                RunEvent(
                    run_id="runtime/v1 run",
                    sequence=1,
                    type="run.started",
                    payload={"capabilities": [PRIME_IPYTHON_CAPABILITY]},
                ),
                RunEvent(
                    run_id="runtime/v1 run",
                    sequence=2,
                    type="run.completed",
                    payload={"status": "cancelled"},
                ),
            ),
        )

    def test_projects_a_forged_malformed_result_as_safe_failure(self) -> None:
        forged = object.__new__(PrimePresetExecutionResult)
        for field, value in {
            "run_id": "runtime/v1 run",
            "receipt_sha256": "not-a-digest",
            "scope": "p7-solving",
            "promotion": "unpromoted",
        }.items():
            object.__setattr__(forged, field, value)

        events = asyncio.run(self._collect(_PresetService(forged), self._request()))

        self.assertEqual(
            events,
            (
                RunEvent(
                    run_id="runtime/v1 run",
                    sequence=1,
                    type="run.started",
                    payload={"capabilities": [PRIME_IPYTHON_CAPABILITY]},
                ),
                RunEvent(
                    run_id="runtime/v1 run",
                    sequence=2,
                    type="run.failed",
                    payload={
                        "code": "verification-failed",
                        "message": "Prime verification failed",
                    },
                ),
            ),
        )

    def test_service_exception_projects_the_safe_failed_stream(self) -> None:
        sentinel = "SENTINEL-PRESET-HOST-SECRET"
        events = asyncio.run(
            self._collect(_PresetService(RuntimeError(sentinel)), self._request())
        )

        self.assertEqual(tuple(event.type for event in events), ("run.started", "run.failed"))
        self.assertNotIn(sentinel, repr(events))
