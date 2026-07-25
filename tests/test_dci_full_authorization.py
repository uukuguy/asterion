"""Tests for one-use, multi-scope DCI full-execution authority."""

from __future__ import annotations

import io
import json
import math
import os
import stat
import tempfile
import unittest
from pathlib import Path

from asterion.dci.experiment_profiles import (
    ExperimentAuthorizationError,
    FullExecutionAuthorization,
    FullExecutionReservation,
    authorized_scope_output_root,
    authorize_full_execution,
    consume_full_execution_authorization,
    cancel_full_execution_authorization,
    consumed_full_execution_authorization_snapshot,
    fail_full_execution_operation,
    reconcile_full_execution_operation,
    reserve_full_execution_operation,
    resolve_experiment_profile,
)
from asterion.dci.verification import paper_reproduce_main


def authorize(
    output_root: Path,
    *,
    scopes: tuple[str, ...] = ("bright.biology.main.full",),
    max_agents: int = 2,
    max_judges: int = 1,
    max_cost: float = 10.0,
    max_agent_cost: float = 2.0,
    max_judge_cost: float = 1.0,
) -> FullExecutionAuthorization:
    return authorize_full_execution(
        profile=resolve_experiment_profile("paper-reference/pi"),
        scope_ids=scopes,
        output_root=output_root,
        max_agent_operations=max_agents,
        max_judge_operations=max_judges,
        max_cost_usd=max_cost,
        max_agent_cost_per_operation_usd=max_agent_cost,
        max_judge_cost_per_operation_usd=max_judge_cost,
        invocation_authorized=True,
    )


class FullExecutionAuthorizationTests(unittest.TestCase):
    def test_requires_exact_positive_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "private-parent"
            for value in (0, -1, True, 1.5):
                with self.subTest(kind="operation", value=value):
                    with self.assertRaises(ExperimentAuthorizationError):
                        authorize(parent, max_agents=value)  # type: ignore[arg-type]
                    with self.assertRaises(ExperimentAuthorizationError):
                        authorize(parent, max_judges=value)  # type: ignore[arg-type]
            for value in (0.0, -1.0, float("inf"), float("-inf"), math.nan, True):
                for limit_name in (
                    "max_cost",
                    "max_agent_cost",
                    "max_judge_cost",
                ):
                    with self.subTest(kind=limit_name, value=value):
                        limits = {limit_name: value}
                        with self.assertRaises(ExperimentAuthorizationError):
                            authorize(parent, **limits)  # type: ignore[arg-type]
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "^full execution requires explicit scopes$",
            ):
                authorize(parent, scopes=())

    def test_constructor_is_private(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "^FullExecutionAuthorization is issued only by authorize_full_execution$",
        ):
            FullExecutionAuthorization()

    def test_scopes_bind_distinct_private_child_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "private-parent"
            authority = authorize(
                parent,
                scopes=(
                    "bright.biology.main.full",
                    "bright.earth-science.main.full",
                ),
            )
            biology = authorized_scope_output_root(
                authority, "bright.biology.main.full"
            )
            earth = authorized_scope_output_root(
                authority, "bright.earth-science.main.full"
            )
            self.assertNotEqual(biology, earth)
            self.assertEqual(stat.S_IMODE(biology.stat().st_mode), 0o700)
            self.assertNotIn(str(parent), repr(authority))
            with self.assertRaises(ExperimentAuthorizationError):
                authorized_scope_output_root(authority, "not.selected")

    def test_scope_replay_and_inode_replacement_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scope = "bright.biology.main.full"
            parent = Path(temporary) / "private-parent"
            authority = authorize(parent)
            consume_full_execution_authorization(authority, scope)
            with self.assertRaises(ExperimentAuthorizationError):
                consume_full_execution_authorization(authority, scope)

            replacement_parent = Path(temporary) / "replacement-parent"
            os.rename(parent, replacement_parent)
            parent.mkdir(mode=0o700)
            with self.assertRaises(ExperimentAuthorizationError):
                authorized_scope_output_root(authority, scope)

        with tempfile.TemporaryDirectory() as temporary:
            scope = "bright.biology.main.full"
            parent = Path(temporary) / "private-parent"
            authority = authorize(parent)
            child = authorized_scope_output_root(authority, scope)
            os.rename(child, parent / "old-child")
            child.mkdir(mode=0o700)
            with self.assertRaises(ExperimentAuthorizationError):
                authorized_scope_output_root(authority, scope)

    def test_failures_are_redacted(self) -> None:
        sentinel = "credential-should-never-appear"
        with tempfile.TemporaryDirectory(prefix="private-path-") as temporary:
            private_path = Path(temporary) / sentinel
            authority = authorize(private_path)
            issuance_token = authority._issuance_token
            object.__setattr__(authority, "profile_sha256", sentinel)
            with self.assertRaises(ExperimentAuthorizationError) as raised:
                authorized_scope_output_root(
                    authority, "bright.biology.main.full"
                )
            message = str(raised.exception)
            self.assertNotIn(sentinel, message)
            self.assertNotIn(str(private_path), message)
            self.assertNotIn(str(private_path), repr(authority))
            self.assertNotIn(issuance_token, repr(authority))


class FullExecutionBudgetTests(unittest.TestCase):
    scope_id = "bright.biology.main.full"

    def consume(self, authority: FullExecutionAuthorization) -> None:
        consume_full_execution_authorization(authority, self.scope_id)

    def test_reservation_requires_consumed_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(Path(temporary) / "private")
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "^full execution authorization scope is not consumed$",
            ):
                reserve_full_execution_operation(
                    authority, self.scope_id, "agent"
                )
            self.consume(authority)
            reservation = reserve_full_execution_operation(
                authority, self.scope_id, "agent"
            )
            reconcile_full_execution_operation(authority, reservation, 0.5)

    def test_operation_count_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(Path(temporary) / "private", max_agents=1)
            self.consume(authority)
            first = reserve_full_execution_operation(
                authority, self.scope_id, "agent"
            )
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "^full execution Agent operation budget is exhausted$",
            ):
                reserve_full_execution_operation(authority, self.scope_id, "agent")
            reconcile_full_execution_operation(authority, first, 0.5)

    def test_invalid_kinds_and_actual_costs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(Path(temporary) / "private")
            self.consume(authority)
            with self.assertRaises(ExperimentAuthorizationError):
                reserve_full_execution_operation(authority, self.scope_id, "tool")

        for value in (-0.1, math.inf, -math.inf, math.nan, True):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                authority = authorize(
                    Path(temporary) / "private", max_agents=3
                )
                self.consume(authority)
                offending = reserve_full_execution_operation(
                    authority, self.scope_id, "agent"
                )
                later = reserve_full_execution_operation(
                    authority, self.scope_id, "agent"
                )
                with self.assertRaises(ExperimentAuthorizationError):
                    reconcile_full_execution_operation(
                        authority, offending, value
                    )
                with self.assertRaises(ExperimentAuthorizationError):
                    reconcile_full_execution_operation(
                        authority, offending, 0.1
                    )
                reconcile_full_execution_operation(authority, later, 0.5)
                with self.assertRaisesRegex(
                    ExperimentAuthorizationError,
                    "^full execution authorization is inactive$",
                ):
                    reserve_full_execution_operation(
                        authority, self.scope_id, "agent"
                    )

        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(
                Path(temporary) / "private", max_agents=3
            )
            self.consume(authority)
            offending = reserve_full_execution_operation(
                authority, self.scope_id, "agent"
            )
            later = reserve_full_execution_operation(
                authority, self.scope_id, "agent"
            )
            with self.assertRaises(ExperimentAuthorizationError):
                reconcile_full_execution_operation(authority, offending, 2.1)
            with self.assertRaises(ExperimentAuthorizationError):
                reconcile_full_execution_operation(authority, offending, 1.0)
            reconcile_full_execution_operation(authority, later, 1.0)
            with self.assertRaises(ExperimentAuthorizationError):
                reserve_full_execution_operation(
                    authority, self.scope_id, "agent"
                )

    def test_reservations_are_bound_to_their_original_scope_and_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(
                Path(temporary) / "private",
                scopes=(
                    "bright.biology.main.full",
                    "bright.earth-science.main.full",
                ),
            )
            self.consume(authority)
            reservation = reserve_full_execution_operation(
                authority, self.scope_id, "agent"
            )
            object.__setattr__(
                reservation, "scope_id", "bright.earth-science.main.full"
            )
            with self.assertRaises(ExperimentAuthorizationError):
                reconcile_full_execution_operation(authority, reservation, 0.5)
            rendered = repr(reservation)
            self.assertNotIn("_authorization_token", rendered)
            self.assertNotIn("_reservation_token", rendered)
            self.assertNotIn(reservation._authorization_token, rendered)
            self.assertNotIn(reservation._reservation_token, rendered)

    def test_cross_authority_and_reservation_replay_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first_authority = authorize(Path(temporary) / "first")
            second_authority = authorize(Path(temporary) / "second")
            self.consume(first_authority)
            self.consume(second_authority)
            reservation = reserve_full_execution_operation(
                first_authority, self.scope_id, "agent"
            )
            with self.assertRaises(ExperimentAuthorizationError) as raised:
                reconcile_full_execution_operation(
                    second_authority, reservation, 0.5
                )
            self.assertNotIn(str(Path(temporary)), str(raised.exception))
            self.assertNotIn(
                reservation._reservation_token, str(raised.exception)
            )
            reconcile_full_execution_operation(
                first_authority, reservation, 0.5
            )
            with self.assertRaises(ExperimentAuthorizationError):
                reconcile_full_execution_operation(
                    first_authority, reservation, 0.5
                )

    def test_active_reservations_cannot_exceed_total_usd_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(
                Path(temporary) / "private",
                max_agents=2,
                max_cost=3.0,
                max_agent_cost=2.0,
            )
            self.consume(authority)
            reserve_full_execution_operation(authority, self.scope_id, "agent")
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "^full execution USD budget is exhausted$",
            ):
                reserve_full_execution_operation(authority, self.scope_id, "agent")

    def test_failure_and_cancellation_preserve_potential_spend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(
                Path(temporary) / "private", max_agents=2, max_cost=4.0
            )
            self.consume(authority)
            first = reserve_full_execution_operation(authority, self.scope_id, "agent")
            later = reserve_full_execution_operation(authority, self.scope_id, "agent")
            fail_full_execution_operation(authority, first)
            fail_full_execution_operation(authority, later)
            with self.assertRaises(ExperimentAuthorizationError):
                fail_full_execution_operation(authority, later)

        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(
                Path(temporary) / "private", max_agents=2
            )
            self.consume(authority)
            completed = reserve_full_execution_operation(
                authority, self.scope_id, "agent"
            )
            failed = reserve_full_execution_operation(
                authority, self.scope_id, "agent"
            )
            cancel_full_execution_authorization(authority)
            with self.assertRaises(ExperimentAuthorizationError):
                reserve_full_execution_operation(authority, self.scope_id, "agent")
            reconcile_full_execution_operation(authority, completed, 0.1)
            fail_full_execution_operation(authority, failed)
            cancel_full_execution_authorization(authority)

    def test_receipt_waits_for_drain_and_contains_exact_body_free_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "private"
            authority = authorize(
                parent,
                max_agents=3,
                max_judges=2,
                max_cost=9.0,
                max_agent_cost=2.5,
                max_judge_cost=1.25,
            )
            self.consume(authority)
            agent = reserve_full_execution_operation(
                authority, self.scope_id, "agent"
            )
            judge = reserve_full_execution_operation(
                authority, self.scope_id, "judge"
            )
            with self.assertRaises(ExperimentAuthorizationError):
                consumed_full_execution_authorization_snapshot(authority)
            reconcile_full_execution_operation(authority, agent, 1.5)
            fail_full_execution_operation(authority, judge)
            receipt = consumed_full_execution_authorization_snapshot(authority)
            self.assertEqual(
                {
                    "max_agent_operations": receipt["max_agent_operations"],
                    "max_judge_operations": receipt["max_judge_operations"],
                    "max_cost_usd": receipt["max_cost_usd"],
                    "max_agent_cost_per_operation_usd": receipt[
                        "max_agent_cost_per_operation_usd"
                    ],
                    "max_judge_cost_per_operation_usd": receipt[
                        "max_judge_cost_per_operation_usd"
                    ],
                },
                {
                    "max_agent_operations": 3,
                    "max_judge_operations": 2,
                    "max_cost_usd": 9.0,
                    "max_agent_cost_per_operation_usd": 2.5,
                    "max_judge_cost_per_operation_usd": 1.25,
                },
            )
            self.assertEqual(
                receipt["ledger"],
                {
                    "reserved_agent_operations": 0,
                    "reserved_judge_operations": 0,
                    "completed_agent_operations": 1,
                    "completed_judge_operations": 1,
                    "reserved_cost_usd": 0.0,
                    "actual_cost_usd": 2.75,
                    "cancelled": True,
                    "finalized": True,
                },
            )
            rendered = json.dumps(receipt, sort_keys=True)
            self.assertNotIn(str(parent), rendered)
            self.assertNotIn(authority._issuance_token, rendered)
            self.assertNotIn(agent._reservation_token, rendered)
            self.assertNotIn(judge._reservation_token, rendered)
            self.assertNotIn("token", rendered)
            self.assertNotIn("path", rendered)

    def test_reservation_constructor_is_private(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "^FullExecutionReservation is issued only by "
            "reserve_full_execution_operation$",
        ):
            FullExecutionReservation()


class LegacyFullAuthorizationTests(unittest.TestCase):
    def test_legacy_helper_redacts_authorization_errors(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory(
            prefix="private-credential-sentinel-"
        ) as temporary:
            result = paper_reproduce_main(
                [
                    "--profile",
                    "paper-reference/pi",
                    "--output-root",
                    str(Path(temporary) / "private"),
                    "--estimated-budget-usd",
                    "0",
                    "--authorize-full",
                ],
                stdout=stdout,
                stderr=stderr,
            )
        self.assertEqual(result, 2)
        self.assertEqual(
            stderr.getvalue(),
            "DCI paper reproduction authorization failed\n",
        )
        self.assertNotIn("credential-sentinel", stdout.getvalue())
        self.assertNotIn("credential-sentinel", stderr.getvalue())
