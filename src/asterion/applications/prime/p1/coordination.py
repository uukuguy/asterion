"""Private, one-run barriers between the P1 runtime and its operator owner."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
import math
import time
from typing import Any, TypeVar

from asterion.capabilities.prime_ipython_coding_native.host import (
    P1Finalization,
    P1PendingClassification,
    P1RuntimeHostError,
    P1StageMilestone,
    P1StageTwoRelease,
)

T = TypeVar("T")


def consume_task_result(task: asyncio.Future[T]) -> None:
    """Drain private exceptions even when an owner outlives the shutdown bound."""
    if task.done():
        try:
            task.exception()
        except BaseException:
            pass


async def wait_task_until(
    task: asyncio.Future[T], deadline: float, *, cancel: bool = False
) -> bool:
    """Wait only to an absolute bound, including cancellation-resistant owners."""
    task.add_done_callback(consume_task_result)
    while not task.done() and time.monotonic() < deadline:
        if cancel:
            task.cancel()
        try:
            await asyncio.wait(
                (task,), timeout=min(0.05, max(0, deadline - time.monotonic()))
            )
        except asyncio.CancelledError:
            # Teardown stays owned through repeated external cancellation.
            cancel = True
    if not task.done():
        task.cancel()
        return False
    return True


class P1CoordinationError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("P1 coordination failed")


@dataclass(frozen=True, slots=True)
class P1OwnerCleanup:
    """Operator observations, issued only after every close has returned."""

    host_closed: bool
    backend_closed: bool
    worker_closed: bool
    bridge_closed: bool
    private_store_removed: bool

    @property
    def complete(self) -> bool:
        return all(
            value is True
            for value in (
                self.host_closed,
                self.backend_closed,
                self.worker_closed,
                self.bridge_closed,
                self.private_store_removed,
            )
        )


class P1Coordination:
    """Keep futures private so a consumer cannot cancel or forge milestones."""

    def __init__(self, *, run_id: str, deadline: float) -> None:
        if not run_id or not math.isfinite(deadline) or deadline <= time.monotonic():
            raise P1CoordinationError()
        self.run_id = run_id
        self.deadline = deadline
        loop = asyncio.get_running_loop()
        self._stage_one_ready: asyncio.Future[P1StageMilestone] = loop.create_future()
        self._stage_two_ready: asyncio.Future[P1StageMilestone] = loop.create_future()
        self._stage_two_release: asyncio.Future[P1StageTwoRelease] = (
            loop.create_future()
        )
        self._execution_stopped: asyncio.Future[P1PendingClassification] = (
            loop.create_future()
        )
        self._finalization_ready: asyncio.Future[P1Finalization] = loop.create_future()
        self._stop_requested: asyncio.Future[None] = loop.create_future()
        self._pending: P1PendingClassification = "completed"
        self._effects: set[asyncio.Future[Any]] = set()
        self.shutdown_deadline: float | None = None

    def __repr__(self) -> str:
        return "<P1Coordination>"

    @property
    def pending(self) -> P1PendingClassification:
        return self._pending

    @property
    def stopped(self) -> bool:
        return self._execution_stopped.done()

    @property
    def cancelled(self) -> bool:
        return self._pending == "cancelled"

    def check(self, run_id: str) -> None:
        if run_id != self.run_id:
            raise P1CoordinationError()
        if self._stop_requested.done():
            if self._pending == "cancelled":
                raise asyncio.CancelledError()
            raise P1RuntimeHostError(
                "budget-limited"
                if self._pending == "budget-limited"
                else "recovery-required"
            )
        if time.monotonic() >= self.deadline:
            self.request_stop("budget-limited")
            raise P1RuntimeHostError("budget-limited")

    def request_stop(self, classification: P1PendingClassification) -> None:
        if classification not in {"cancelled", "budget-limited", "recovery-required"}:
            raise P1CoordinationError()
        if not self._stop_requested.done():
            # A runtime-observed failure is authoritative once execution stopped.
            if not self.stopped or self._pending == "completed":
                self._pending = classification
            self._stop_requested.set_result(None)

    def publish(self, run_id: str, milestone: P1StageMilestone) -> None:
        self.check(run_id)
        if type(milestone) is not P1StageMilestone or self.stopped:
            raise P1CoordinationError()
        target = (
            self._stage_one_ready
            if milestone.stage == "stage-one"
            else self._stage_two_ready
        )
        if target.done() or (
            milestone.stage == "stage-two" and not self._stage_two_release.done()
        ):
            raise P1CoordinationError()
        target.set_result(milestone)

    def release_stage_two(self, release: P1StageTwoRelease) -> None:
        self.check(self.run_id)
        if (
            type(release) is not P1StageTwoRelease
            or not self._stage_one_ready.done()
            or self._stage_two_release.done()
            or self.stopped
        ):
            raise P1CoordinationError()
        self._stage_two_release.set_result(release)

    async def wait_release(
        self, run_id: str, stage_one: P1StageMilestone
    ) -> P1StageTwoRelease:
        if (
            not self._stage_one_ready.done()
            or self._stage_one_ready.result() is not stage_one
        ):
            raise P1CoordinationError()
        self.check(run_id)
        await asyncio.wait(
            (self._stage_two_release, self._stop_requested),
            timeout=max(0, self.deadline - time.monotonic()),
            return_when=asyncio.FIRST_COMPLETED,
        )
        self.check(run_id)
        if not self._stage_two_release.done():
            raise P1RuntimeHostError("budget-limited")
        return self._stage_two_release.result()

    def report_stopped(self, run_id: str, pending: P1PendingClassification) -> None:
        if run_id != self.run_id or self.stopped:
            raise P1CoordinationError()
        if pending != "completed" or self._pending == "completed":
            self._pending = pending
        self._execution_stopped.set_result(self._pending)

    async def wait_milestone(
        self, stage: str, runner: asyncio.Task[object]
    ) -> P1StageMilestone:
        milestone = (
            self._stage_one_ready if stage == "stage-one" else self._stage_two_ready
        )
        return await _wait_milestone_or_stopped(milestone, self, runner)

    async def wait_stopped(
        self, runner: asyncio.Task[object], *, timeout: float
    ) -> bool:
        await asyncio.wait(
            (self._execution_stopped, runner),
            timeout=max(0, timeout),
            return_when=asyncio.FIRST_COMPLETED,
        )
        return self.stopped

    async def effect(self, awaitable: Awaitable[T], *, run_id: str) -> T:
        """Own an effect task and settle it before another owner can close."""
        task = asyncio.ensure_future(awaitable)
        task.add_done_callback(consume_task_result)
        self._effects.add(task)
        try:
            self.check(run_id)
            await asyncio.wait(
                (task, self._stop_requested),
                timeout=max(0, self.deadline - time.monotonic()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            self.check(run_id)
            if not task.done():
                raise P1RuntimeHostError("budget-limited")
            return task.result()
        finally:
            if not task.done():
                deadline = self.shutdown_deadline or (time.monotonic() + 0.25)
                if not await wait_task_until(task, deadline, cancel=True):
                    raise P1CoordinationError()
            self._effects.discard(task)

    async def abort_effects(self) -> bool:
        deadline = self.shutdown_deadline or (time.monotonic() + 0.25)
        complete = True
        for task in tuple(self._effects):
            if not await wait_task_until(task, deadline, cancel=True):
                complete = False
            else:
                self._effects.discard(task)
        return complete

    def release_finalization(
        self, finalization: P1Finalization, cleanup: P1OwnerCleanup
    ) -> None:
        if (
            type(cleanup) is not P1OwnerCleanup
            or not cleanup.complete
            or not self.stopped
            or self._finalization_ready.done()
            or finalization.classification != self._pending
        ):
            raise P1CoordinationError()
        self._finalization_ready.set_result(finalization)

    async def wait_finalization(self, run_id: str) -> P1Finalization:
        if run_id != self.run_id or not self.stopped:
            raise P1CoordinationError()
        # Cleanup has its own bounded operator deadline and survives cancellation.
        return await asyncio.shield(self._finalization_ready)


async def _wait_milestone_or_stopped(
    milestone: asyncio.Future[T],
    coordination: P1Coordination,
    runner: asyncio.Task[object],
) -> T:
    await asyncio.wait(
        (
            milestone,
            coordination._execution_stopped,
            coordination._stop_requested,
            runner,
        ),
        timeout=max(0, coordination.deadline - time.monotonic()),
        return_when=asyncio.FIRST_COMPLETED,
    )
    coordination.check(coordination.run_id)
    if runner.done() or (coordination.stopped and coordination.pending != "completed"):
        raise P1CoordinationError()
    if milestone.done():
        return milestone.result()
    raise P1CoordinationError()
