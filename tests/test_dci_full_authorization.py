"""Tests for one-use, multi-scope DCI full-execution authority."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import stat
import tempfile
import unittest
import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock, patch

from asterion.dci import experiment_profiles as profiles
from asterion.dci.benchmark import (
    BenchmarkRequest,
    DciBenchmarkError,
    run_benchmark,
    run_benchmark_async,
)
from asterion.dci.cli import main as dci_main
from asterion.dci.config import DciRuntimeOptions, resolve_dci_paths
from asterion.dci.experiment_profiles import (
    ExperimentAuthorizationError,
    FullExecutionAuthorization,
    FullExecutionReservation,
    _consumed_authorized_output_identity,
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
from asterion.dci.judge import JudgeConfig
from asterion.dci.paper_benchmarks import (
    canonical_sha256,
    resolve_paper_experiment_scope,
)
from asterion.dci.verification import paper_reproduce_main


def receipt_ledger(receipt: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], receipt["ledger"])


def query_ids(count: int) -> tuple[str, ...]:
    return tuple(f"q-{index}" for index in range(1, count + 1))


def authorize(
    output_root: Path,
    *,
    scopes: tuple[str, ...] = ("bright.biology.main.full",),
    max_agents: int = 2,
    max_judges: int = 1,
    max_cost: float = 10.0,
    max_agent_cost: float = 2.0,
    max_judge_cost: float = 1.0,
    selected_query_ids_by_scope: dict[str, tuple[str, ...]] | None = None,
    selected_query_ids: tuple[str, ...] | None = None,
) -> FullExecutionAuthorization:
    if selected_query_ids_by_scope is not None and selected_query_ids is not None:
        raise ValueError("selected query fixture is ambiguous")
    query_ids_by_scope = {
        scope: (
            selected_query_ids_by_scope.get(scope, ("q-001",))
            if selected_query_ids_by_scope is not None
            else (selected_query_ids or ("q-001",))
        )
        for scope in scopes
    }
    return authorize_full_execution(
        profile=resolve_experiment_profile("paper-reference/pi"),
        scope_ids=scopes,
        bounded_selected_ids_sha256=tuple(
            canonical_sha256(query_ids_by_scope[scope])
            for scope in scopes
        ),
        selected_query_counts=tuple(
            len(query_ids_by_scope[scope]) for scope in scopes
        ),
        planned_agent_operations=sum(
            len(query_ids_by_scope[scope]) for scope in scopes
        ),
        planned_judge_operations=0,
        output_root=output_root,
        max_agent_operations=max_agents,
        max_judge_operations=max_judges,
        max_cost_usd=max_cost,
        max_agent_cost_per_operation_usd=max_agent_cost,
        max_judge_cost_per_operation_usd=max_judge_cost,
        invocation_authorized=True,
    )


class FullExecutionAuthorizationTests(unittest.TestCase):
    def test_bounded_selection_and_manifest_root_are_identity_bound(self) -> None:
        scope_id = "bright.biology.main.full"
        bounded_digest = canonical_sha256(("q-001",))
        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize_full_execution(
                profile=resolve_experiment_profile("paper-reference/pi"),
                scope_ids=(scope_id,),
                bounded_selected_ids_sha256=(bounded_digest,),
                selected_query_counts=(1,),
                planned_agent_operations=1,
                planned_judge_operations=0,
                output_root=Path(temporary) / "private",
                invocation_authorized=True,
                max_agent_operations=1,
                max_judge_operations=1,
                max_cost_usd=1,
                max_agent_cost_per_operation_usd=1,
                max_judge_cost_per_operation_usd=1,
            )
            self.assertEqual(
                profiles._authorized_scope_selection_identity(
                    authority, scope_id
                ),
                (bounded_digest, 1),
            )
            manifest_root, device, inode = (
                profiles._authorized_manifest_output_identity(authority)
            )
            self.assertEqual(
                (manifest_root.stat().st_dev, manifest_root.stat().st_ino),
                (device, inode),
            )
            self.assertEqual(stat.S_IMODE(manifest_root.stat().st_mode), 0o700)
            self.assertNotIn(str(manifest_root), repr(authority))

    def test_rejects_invalid_bounded_selection_plans(self) -> None:
        invalid_cases = {
            "missing bounded digest": {
                "bounded_selected_ids_sha256": (),
                "selected_query_counts": (1,),
            },
            "invalid bounded digest": {
                "bounded_selected_ids_sha256": ("not-a-digest",),
                "selected_query_counts": (1,),
            },
            "zero selected count": {
                "bounded_selected_ids_sha256": (canonical_sha256(("q-001",)),),
                "selected_query_counts": (0,),
            },
            "count exceeds scope": {
                "bounded_selected_ids_sha256": (canonical_sha256(("q-001",)),),
                "selected_query_counts": (104,),
            },
            "agent plan exceeds cap": {
                "bounded_selected_ids_sha256": (canonical_sha256(("q-001",)),),
                "selected_query_counts": (1,),
                "planned_agent_operations": 2,
                "max_agent_operations": 1,
            },
            "judge plan exceeds cap": {
                "bounded_selected_ids_sha256": (canonical_sha256(("q-001",)),),
                "selected_query_counts": (1,),
                "planned_judge_operations": 2,
                "max_judge_operations": 1,
            },
        }
        defaults = {
            "bounded_selected_ids_sha256": (canonical_sha256(("q-001",)),),
            "selected_query_counts": (1,),
            "planned_agent_operations": 1,
            "planned_judge_operations": 0,
            "max_agent_operations": 1,
            "max_judge_operations": 1,
        }
        for label, overrides in invalid_cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                values = defaults | overrides
                with self.assertRaises(ExperimentAuthorizationError):
                    authorize_full_execution(
                        profile=resolve_experiment_profile("paper-reference/pi"),
                        scope_ids=("bright.biology.main.full",),
                        output_root=Path(temporary) / "private",
                        invocation_authorized=True,
                        max_cost_usd=1,
                        max_agent_cost_per_operation_usd=1,
                        max_judge_cost_per_operation_usd=1,
                        **values,
                    )

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

    def test_new_authority_rejects_legacy_parameter_mixing(self) -> None:
        profile = resolve_experiment_profile("paper-reference/pi")
        legacy_values: tuple[dict[str, Any], ...] = (
            {"profile_id": "paper-reference/pi"},
            {"estimated_budget_usd": 1.0},
            {"preflight_profile_sha256": profile.identity_sha256},
            {"invocation_provider": "fixture"},
        )
        for index, legacy in enumerate(legacy_values):
            with self.subTest(legacy=tuple(legacy)), tempfile.TemporaryDirectory() as temporary:
                output_root = Path(temporary) / f"private-{index}"
                with self.assertRaises(ExperimentAuthorizationError):
                    authorize_full_execution(
                        profile=profile,
                        scope_ids=("bright.biology.main.full",),
                        output_root=output_root,
                        max_agent_operations=1,
                        max_judge_operations=1,
                        max_cost_usd=1.0,
                        max_agent_cost_per_operation_usd=0.5,
                        max_judge_cost_per_operation_usd=0.5,
                        invocation_authorized=True,
                        **legacy,
                    )
                self.assertFalse(output_root.exists())

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
            self.assertFalse(hasattr(authority, "output_root"))
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
            manifest = profiles._authorized_manifest_output_identity(
                authority
            )[0]
            consume_full_execution_authorization(authority, scope)
            with self.assertRaises(ExperimentAuthorizationError):
                consume_full_execution_authorization(authority, scope)

            replacement_parent = Path(temporary) / "replacement-parent"
            os.rename(parent, replacement_parent)
            parent.mkdir(mode=0o700)
            with self.assertRaises(ExperimentAuthorizationError):
                authorized_scope_output_root(authority, scope)
            with self.assertRaises(ExperimentAuthorizationError):
                profiles._authorized_manifest_output_identity(authority)
            self.assertFalse(manifest.exists())

        with tempfile.TemporaryDirectory() as temporary:
            scope = "bright.biology.main.full"
            parent = Path(temporary) / "private-parent"
            authority = authorize(parent)
            child = authorized_scope_output_root(authority, scope)
            manifest = profiles._authorized_manifest_output_identity(
                authority
            )[0]
            os.rename(child, parent / "old-child")
            child.mkdir(mode=0o700)
            with self.assertRaises(ExperimentAuthorizationError):
                authorized_scope_output_root(authority, scope)
            os.rename(manifest, parent / "old-manifest")
            manifest.mkdir(mode=0o700)
            with self.assertRaises(ExperimentAuthorizationError):
                profiles._authorized_manifest_output_identity(authority)

    def test_output_root_rejects_existing_and_intermediate_symlink_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            existing = base / "existing"
            existing.mkdir()
            with self.assertRaises(ExperimentAuthorizationError):
                authorize(existing)

            target = base / "target"
            target.mkdir()
            intermediate = base / "intermediate"
            intermediate.symlink_to(target, target_is_directory=True)
            redirected = intermediate / "private"
            with self.assertRaises(ExperimentAuthorizationError) as raised:
                authorize(redirected)
            self.assertFalse((target / "private").exists())
            self.assertNotIn(str(redirected), str(raised.exception))
            self.assertNotIn(str(target), str(raised.exception))

    def test_output_root_is_cleaned_when_post_creation_identity_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "private"
            with patch(
                "asterion.dci.experiment_profiles.os.fchmod",
                side_effect=OSError("credential-path-sentinel"),
            ):
                with self.assertRaises(ExperimentAuthorizationError) as raised:
                    authorize(output_root)
            self.assertFalse(output_root.exists())
            self.assertNotIn("credential-path-sentinel", str(raised.exception))

    def test_output_root_is_cleaned_when_manifest_creation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "private"
            manifest_child_name = hashlib.sha256(
                b"dci.reproduction-manifests/v1"
            ).hexdigest()
            real_mkdir = os.mkdir

            def fail_manifest_creation(
                path: str,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> None:
                if path == manifest_child_name:
                    raise OSError("credential-path-sentinel")
                real_mkdir(path, mode=mode, dir_fd=dir_fd)

            with patch(
                "asterion.dci.experiment_profiles.os.mkdir",
                side_effect=fail_manifest_creation,
            ):
                with self.assertRaises(ExperimentAuthorizationError) as raised:
                    authorize(output_root)
            self.assertFalse(output_root.exists())
            self.assertNotIn("credential-path-sentinel", str(raised.exception))

    def test_failed_creation_never_cleans_through_a_replaced_root_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            output_root = base / "private"
            moved_root = base / "moved-private"
            replacement_target = base / "replacement-target"
            replacement_target.mkdir()
            manifest_child_name = hashlib.sha256(
                b"dci.reproduction-manifests/v1"
            ).hexdigest()
            replacement_manifest = replacement_target / manifest_child_name
            replacement_manifest.mkdir()
            real_mkdir = os.mkdir

            def replace_root_before_manifest_creation(
                path: str,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> None:
                if path == manifest_child_name:
                    os.rename(output_root, moved_root)
                    output_root.symlink_to(
                        replacement_target,
                        target_is_directory=True,
                    )
                    raise OSError("credential-path-sentinel")
                real_mkdir(path, mode=mode, dir_fd=dir_fd)

            with patch(
                "asterion.dci.experiment_profiles.os.mkdir",
                side_effect=replace_root_before_manifest_creation,
            ):
                with self.assertRaises(ExperimentAuthorizationError) as raised:
                    authorize(output_root)
            self.assertTrue(replacement_manifest.is_dir())
            self.assertTrue(output_root.is_symlink())
            self.assertTrue(moved_root.is_dir())
            self.assertNotIn("credential-path-sentinel", str(raised.exception))

    def test_failures_are_redacted(self) -> None:
        sentinel = "credential-should-never-appear"
        with tempfile.TemporaryDirectory(prefix="private-path-") as temporary:
            private_path = Path(temporary) / sentinel
            authority = authorize(private_path)
            issuance_token = authority._issuance_token
            object.__setattr__(
                authority,
                "bounded_selected_ids_sha256",
                (sentinel,),
            )
            with self.assertRaises(ExperimentAuthorizationError) as raised:
                profiles._authorized_scope_selection_identity(
                    authority, "bright.biology.main.full"
                )
            self.assertNotIn(sentinel, str(raised.exception))
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

    def test_bounded_authority_fields_are_forgery_checked(self) -> None:
        forged_values = {
            "bounded_selected_ids_sha256": ("1" * 64,),
            "selected_query_counts": (2,),
            "planned_agent_operations": 2,
            "planned_judge_operations": 1,
        }
        for field, value in forged_values.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                authority = authorize(Path(temporary) / "private")
                object.__setattr__(authority, field, value)
                with self.assertRaises(ExperimentAuthorizationError) as raised:
                    profiles._authorized_scope_selection_identity(
                        authority, "bright.biology.main.full"
                    )
                self.assertEqual(
                    str(raised.exception),
                    "full execution authorization is invalid",
                )


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

    def test_invalid_actual_cost_cleanup_preserves_the_original_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(Path(temporary) / "private")
            self.consume(authority)
            reservation = reserve_full_execution_operation(
                authority, self.scope_id, "agent"
            )
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "^full execution actual cost is invalid$",
            ):
                try:
                    reconcile_full_execution_operation(
                        authority, reservation, 2.1
                    )
                except ExperimentAuthorizationError:
                    fail_full_execution_operation(authority, reservation)
                    raise
            fail_full_execution_operation(authority, reservation)
            receipt = consumed_full_execution_authorization_snapshot(authority)
            ledger = receipt_ledger(receipt)
            self.assertEqual(ledger["completed_agent_operations"], 1)
            self.assertEqual(ledger["actual_cost_usd"], 2.0)

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

    def test_decimal_budget_accounting_has_no_binary_float_residue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(
                Path(temporary) / "private",
                max_agents=1,
                max_judges=1,
                max_cost=0.3,
                max_agent_cost=0.1,
                max_judge_cost=0.2,
            )
            self.consume(authority)
            agent = reserve_full_execution_operation(
                authority, self.scope_id, "agent"
            )
            judge = reserve_full_execution_operation(
                authority, self.scope_id, "judge"
            )
            reconcile_full_execution_operation(authority, agent, 0.1)
            reconcile_full_execution_operation(authority, judge, 0.2)
            receipt = consumed_full_execution_authorization_snapshot(authority)
            ledger = receipt_ledger(receipt)
            self.assertEqual(ledger["reserved_cost_usd"], 0.0)
            self.assertEqual(ledger["actual_cost_usd"], 0.3)

    def test_unrepresentable_numeric_limits_use_the_safe_public_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "private"
            with self.assertRaises(ExperimentAuthorizationError):
                authorize(output_root, max_cost=10**400)
            self.assertFalse(output_root.exists())

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
                    "bounded_selected_ids_sha256": receipt[
                        "bounded_selected_ids_sha256"
                    ],
                    "selected_query_counts": receipt[
                        "selected_query_counts"
                    ],
                    "planned_agent_operations": receipt[
                        "planned_agent_operations"
                    ],
                    "planned_judge_operations": receipt[
                        "planned_judge_operations"
                    ],
                },
                {
                    "bounded_selected_ids_sha256": [
                        canonical_sha256(("q-001",))
                    ],
                    "selected_query_counts": [1],
                    "planned_agent_operations": 1,
                    "planned_judge_operations": 0,
                },
            )
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
                receipt_ledger(receipt),
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

    def test_finalized_receipt_is_immutable_and_consumed_identity_is_active_only(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(Path(temporary) / "private")
            child = authorized_scope_output_root(authority, self.scope_id)
            child_stat = child.stat()
            manifest = profiles._authorized_manifest_output_identity(
                authority
            )
            self.consume(authority)
            self.assertEqual(
                _consumed_authorized_output_identity(
                    authority, self.scope_id
                )[1:],
                (child_stat.st_dev, child_stat.st_ino),
            )
            receipt = consumed_full_execution_authorization_snapshot(authority)
            with self.assertRaises(ExperimentAuthorizationError):
                cancel_full_execution_authorization(authority)
            with self.assertRaises(ExperimentAuthorizationError):
                _consumed_authorized_output_identity(authority, self.scope_id)
            original_receipt = json.loads(json.dumps(receipt))
            receipt["selected_query_counts"] = [2]
            self.assertEqual(
                consumed_full_execution_authorization_snapshot(authority),
                original_receipt,
            )
            self.assertEqual(
                (manifest[0].stat().st_dev, manifest[0].stat().st_ino),
                manifest[1:],
            )

        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(Path(temporary) / "private")
            self.consume(authority)
            cancel_full_execution_authorization(authority)
            cancel_full_execution_authorization(authority)
            with self.assertRaises(ExperimentAuthorizationError):
                _consumed_authorized_output_identity(authority, self.scope_id)
            with self.assertRaises(ExperimentAuthorizationError):
                profiles._authorized_manifest_output_identity(authority)

    def test_bounded_receipt_fields_are_immutable(self) -> None:
        mutations = {
            "bounded_selected_ids_sha256": lambda receipt: receipt[
                "bounded_selected_ids_sha256"
            ].append("1" * 64),
            "selected_query_counts": lambda receipt: receipt[
                "selected_query_counts"
            ].append(2),
            "planned_agent_operations": lambda receipt: receipt.__setitem__(
                "planned_agent_operations", 2
            ),
            "planned_judge_operations": lambda receipt: receipt.__setitem__(
                "planned_judge_operations", 1
            ),
        }
        for field, mutate in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                authority = authorize(Path(temporary) / "private")
                self.consume(authority)
                receipt = consumed_full_execution_authorization_snapshot(
                    authority
                )
                original_receipt = json.loads(json.dumps(receipt))
                mutate(receipt)
                self.assertEqual(
                    consumed_full_execution_authorization_snapshot(authority),
                    original_receipt,
                )

    def test_reservation_constructor_is_private(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "^FullExecutionReservation is issued only by "
            "reserve_full_execution_operation$",
        ):
            FullExecutionReservation()


class AuthorizedBenchmarkTests(unittest.TestCase):
    scope_id = "bright.biology.main.full"

    def request(
        self,
        root: Path,
        authority: FullExecutionAuthorization,
    ) -> BenchmarkRequest:
        return BenchmarkRequest(
            dataset=root / "must-not-be-read.jsonl",
            output_root=authorized_scope_output_root(authority, self.scope_id),
            cwd=root,
            judge_config=JudgeConfig(base_url="https://judge.example.test/v1"),
            runtime_options=DciRuntimeOptions(provider=None, model=None),
            profile="bright.biology",
            full_execution_authorization=authority,
            experiment_scope_id=self.scope_id,
        )

    def test_requires_exact_authority_scope_and_child_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()

            authority = authorize(root / "missing-authority")
            request = self.request(root, authority)
            with patch("asterion.dci.benchmark._read_input_snapshot") as read:
                with self.assertRaisesRegex(
                    DciBenchmarkError,
                    "^DCI benchmark requires full execution authorization$",
                ):
                    run_benchmark(
                        replace(request, full_execution_authorization=None),
                        paths=Mock(),
                    )
            read.assert_not_called()

            authority = authorize(root / "parent-root")
            request = self.request(root, authority)
            with patch("asterion.dci.benchmark._read_input_snapshot") as read:
                with self.assertRaisesRegex(
                    DciBenchmarkError,
                    "^DCI benchmark authorization root changed$",
                ):
                    run_benchmark(
                        replace(request, output_root=root / "parent-root"),
                        paths=Mock(),
                    )
            read.assert_not_called()

            authority = authorize(
                root / "other-child",
                scopes=(
                    self.scope_id,
                    "bright.earth-science.main.full",
                ),
            )
            request = self.request(root, authority)
            other = authorized_scope_output_root(
                authority, "bright.earth-science.main.full"
            )
            with patch("asterion.dci.benchmark._read_input_snapshot") as read:
                with self.assertRaisesRegex(
                    DciBenchmarkError,
                    "^DCI benchmark authorization root changed$",
                ):
                    run_benchmark(
                        replace(request, output_root=other),
                        paths=Mock(),
                    )
            read.assert_not_called()

    def test_scope_is_consumed_only_after_selected_rows_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            authority = authorize(
                root / "selection-mismatch",
                selected_query_ids=query_ids(1),
            )
            request = self.request(root, authority)
            dataset = root / "dataset.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "query_id": "q-1",
                        "query": "question",
                        "answer": "gold",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            request = replace(
                request,
                dataset=dataset,
                profile="paper-reference/pi",
            )
            with patch(
                "asterion.dci.benchmark._paper_scope_for_rows",
                return_value="bright.earth-science.main.full",
            ):
                with self.assertRaisesRegex(
                    DciBenchmarkError,
                    "^DCI benchmark authorization scope changed$",
                ):
                    run_benchmark(request, paths=Mock())
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "^full execution authorization is inactive$",
            ):
                authorized_scope_output_root(authority, self.scope_id)

            authority = authorize(root / "changed-scope")
            request = self.request(root, authority)
            with patch("asterion.dci.benchmark._read_input_snapshot") as read:
                with self.assertRaisesRegex(
                    DciBenchmarkError,
                    "^DCI benchmark authorization scope changed$",
                ):
                    run_benchmark(
                        replace(
                            request,
                            experiment_scope_id="bright.earth-science.main.full",
                        ),
                        paths=Mock(),
                    )
            read.assert_not_called()

    def test_bounded_selection_drift_fails_before_agent(self) -> None:
        drift_cases = {
            "request limit removed": {
                "limit": None,
                "authority_digest": canonical_sha256(("q-001",)),
                "authority_count": 1,
                "rows": ("q-001", "q-002"),
            },
            "request limit changed": {
                "limit": 2,
                "authority_digest": canonical_sha256(("q-001",)),
                "authority_count": 1,
                "rows": ("q-001", "q-002"),
            },
            "bounded digest forged": {
                "limit": 1,
                "authority_digest": "f" * 64,
                "authority_count": 1,
                "rows": ("q-001", "q-002"),
            },
            "bounded count forged": {
                "limit": 1,
                "authority_digest": canonical_sha256(("q-001",)),
                "authority_count": 2,
                "rows": ("q-001", "q-002"),
            },
            "dataset order changed after preflight": {
                "limit": 1,
                "authority_digest": canonical_sha256(("q-001",)),
                "authority_count": 1,
                "rows": ("q-002", "q-001"),
            },
        }
        for label, case in drift_cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                private_root = root / "private-output-must-not-leak"
                authority = authorize_full_execution(
                    profile=resolve_experiment_profile("paper-reference/pi"),
                    scope_ids=(self.scope_id,),
                    bounded_selected_ids_sha256=(
                        cast(str, case["authority_digest"]),
                    ),
                    selected_query_counts=(cast(int, case["authority_count"]),),
                    planned_agent_operations=cast(int, case["authority_count"]),
                    planned_judge_operations=0,
                    output_root=private_root,
                    max_agent_operations=2,
                    max_judge_operations=1,
                    max_cost_usd=10,
                    max_agent_cost_per_operation_usd=2,
                    max_judge_cost_per_operation_usd=1,
                    invocation_authorized=True,
                )
                dataset = root / "dataset-private-path.jsonl"
                dataset.write_text(
                    "".join(
                        json.dumps(
                            {
                                "query_id": query_id,
                                "query": f"SECRET question for {query_id}",
                                "answer": f"SECRET answer for {query_id}",
                            }
                        )
                        + "\n"
                        for query_id in cast(tuple[str, ...], case["rows"])
                    ),
                    encoding="utf-8",
                )
                request = replace(
                    self.request(root, authority),
                    dataset=dataset,
                    profile="paper-reference/pi",
                    limit=cast(int | None, case["limit"]),
                    analysis=False,
                    figures=False,
                )
                with patch(
                    "asterion.dci.benchmark._paper_scope_for_rows",
                    return_value=self.scope_id,
                ), patch(
                    "asterion.dci.benchmark._run_pi_async"
                ) as agent, patch(
                    "asterion.dci.benchmark.reserve_full_execution_operation"
                ) as reserve:
                    with self.assertRaisesRegex(
                        DciBenchmarkError,
                        "^DCI benchmark authorization selection changed$",
                    ) as raised:
                        run_benchmark(request, paths=resolve_dci_paths(root))
                agent.assert_not_called()
                reserve.assert_not_called()
                rendered = str(raised.exception)
                for forbidden in (
                    "q-001",
                    "q-002",
                    "SECRET",
                    str(root),
                    str(dataset),
                    str(private_root),
                ):
                    self.assertNotIn(forbidden, rendered)
                with self.assertRaisesRegex(
                    ExperimentAuthorizationError,
                    "^full execution authorization is inactive$",
                ):
                    reserve_full_execution_operation(
                        authority, self.scope_id, "agent"
                    )


class AuthorizedBenchmarkBudgetTests(unittest.TestCase):
    scope_id = "bright.biology.main.full"

    def request(
        self,
        root: Path,
        authority: FullExecutionAuthorization,
        *,
        rows: int = 2,
        max_concurrency: int = 1,
    ) -> BenchmarkRequest:
        dataset = root / "dataset.jsonl"
        dataset.write_text(
            "".join(
                json.dumps(
                    {
                        "query_id": f"q-{index}",
                        "query": f"question {index}",
                        "answer": "gold",
                    }
                )
                + "\n"
                for index in range(1, rows + 1)
            ),
            encoding="utf-8",
        )
        return BenchmarkRequest(
            dataset=dataset,
            output_root=authorized_scope_output_root(authority, self.scope_id),
            cwd=root,
            judge_config=JudgeConfig(base_url="https://judge.example.test/v1"),
            runtime_options=DciRuntimeOptions(provider=None, model=None),
            profile="paper-reference/pi",
            max_concurrency=max_concurrency,
            analysis=False,
            figures=False,
            full_execution_authorization=authority,
            experiment_scope_id=self.scope_id,
        )

    def patches(
        self,
        *,
        agent,
        judge,
        agent_cost,
    ):
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(
            patch(
                "asterion.dci.benchmark._paper_scope_for_rows",
                return_value=self.scope_id,
            )
        )
        stack.enter_context(
            patch(
                "asterion.dci.benchmark.resolve_paper_benchmark",
                return_value=Mock(dataset_id="fixture-dataset"),
            )
        )
        stack.enter_context(
            patch("asterion.dci.benchmark._run_pi_async", side_effect=agent)
        )
        stack.enter_context(
            patch(
                "asterion.dci.benchmark._validated_agent_cost",
                side_effect=agent_cost,
            )
        )
        stack.enter_context(
            patch(
                "asterion.dci.benchmark._reusable_judge_verdict",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "asterion.dci.benchmark.evaluate_run_directory_async",
                side_effect=judge,
            )
        )
        stack.enter_context(
            patch(
                "asterion.dci.benchmark._native_evidence_fingerprint",
                return_value="0" * 64,
            )
        )
        stack.enter_context(
            patch("asterion.dci.benchmark._publish_aggregates")
        )
        return stack

    @staticmethod
    def verdict(*, cost: float = 0.0) -> dict[str, object]:
        return {
            "is_correct": True,
            "judge_request_fingerprint": "fixture-fingerprint",
            "cost_estimate_usd": {"total_cost": cost},
        }

    def test_two_row_agent_plan_above_cap_fails_before_output_or_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output_root = root / "agent-cap"
            with patch("asterion.dci.benchmark._run_pi_async") as agent:
                with self.assertRaisesRegex(
                    ExperimentAuthorizationError,
                    "^full execution bounded operation plan is invalid$",
                ):
                    authorize(
                        output_root,
                        max_agents=1,
                        max_judges=2,
                        selected_query_ids=query_ids(2),
                    )
            agent.assert_not_called()
            self.assertFalse(output_root.exists())

    def test_exact_agent_plan_runs_and_judge_cap_stops_second_judge(self) -> None:
        async def agent(*_args: object, **_kwargs: object) -> None:
            return None

        async def judge(*_args: object, **_kwargs: object) -> dict[str, object]:
            return self.verdict()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            authority = authorize(
                root / "agent-cap",
                max_agents=2,
                max_judges=2,
                selected_query_ids=query_ids(2),
            )
            request = self.request(root, authority)
            with self.patches(agent=agent, judge=judge, agent_cost=lambda *_: 0.0):
                with patch(
                    "asterion.dci.benchmark._run_pi_async",
                    side_effect=agent,
                ) as run, patch(
                    "asterion.dci.benchmark.evaluate_run_directory_async",
                    side_effect=judge,
                ) as evaluate:
                    run_benchmark(request, paths=resolve_dci_paths(root))
            self.assertEqual(run.call_count, 2)
            self.assertEqual(evaluate.call_count, 2)

            authority = authorize(
                root / "judge-cap",
                max_agents=2,
                max_judges=1,
                selected_query_ids=query_ids(2),
            )
            request = self.request(root, authority)
            with self.patches(agent=agent, judge=judge, agent_cost=lambda *_: 0.0):
                with patch(
                    "asterion.dci.benchmark._run_pi_async",
                    side_effect=agent,
                ) as run, patch(
                    "asterion.dci.benchmark.evaluate_run_directory_async",
                    side_effect=judge,
                ) as evaluate:
                    with self.assertRaises(DciBenchmarkError):
                        run_benchmark(request, paths=resolve_dci_paths(root))
            self.assertEqual(run.call_count, 2)
            self.assertEqual(evaluate.call_count, 1)

    def test_usd_cap_stops_before_the_operation_that_would_exceed_it(self) -> None:
        async def agent(*_args: object, **_kwargs: object) -> None:
            return None

        async def judge(*_args: object, **_kwargs: object) -> dict[str, object]:
            return self.verdict(cost=0.5)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            authority = authorize(
                root / "usd-cap",
                max_agents=2,
                max_judges=2,
                max_cost=2.5,
                max_agent_cost=2.0,
                max_judge_cost=1.0,
                selected_query_ids=query_ids(2),
            )
            request = self.request(root, authority)
            with self.patches(agent=agent, judge=judge, agent_cost=lambda *_: 1.5):
                with patch(
                    "asterion.dci.benchmark._run_pi_async",
                    side_effect=agent,
                ) as run, patch(
                    "asterion.dci.benchmark.evaluate_run_directory_async",
                    side_effect=judge,
                ) as evaluate:
                    with self.assertRaisesRegex(
                        DciBenchmarkError,
                        "^full execution USD budget is exhausted$",
                    ):
                        run_benchmark(request, paths=resolve_dci_paths(root))
            self.assertEqual(run.call_count, 1)
            self.assertEqual(evaluate.call_count, 1)

    def test_actual_costs_reconcile_and_excess_cancels_authority(self) -> None:
        async def agent(*_args: object, **_kwargs: object) -> None:
            return None

        async def judge(*_args: object, **_kwargs: object) -> dict[str, object]:
            return self.verdict(cost=0.2)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            authority = authorize(
                root / "reconcile",
                max_agents=1,
                max_judges=1,
                selected_query_ids=query_ids(1),
            )
            request = self.request(root, authority, rows=1)
            with self.patches(agent=agent, judge=judge, agent_cost=lambda *_: 0.4):
                result = run_benchmark(request, paths=resolve_dci_paths(root))
            self.assertEqual(result.counts["total"], 1)
            self.assertEqual(result.counts["failed"], 0)
            receipt = consumed_full_execution_authorization_snapshot(authority)
            ledger = receipt_ledger(receipt)
            self.assertEqual(ledger["actual_cost_usd"], 0.6)

            authority = authorize(
                root / "excess",
                max_agents=2,
                max_judges=2,
                max_agent_cost=0.5,
                selected_query_ids=query_ids(2),
            )
            request = self.request(root, authority)
            with self.patches(agent=agent, judge=judge, agent_cost=lambda *_: 0.6):
                with patch(
                    "asterion.dci.benchmark._run_pi_async",
                    side_effect=agent,
                ) as run, patch(
                    "asterion.dci.benchmark.evaluate_run_directory_async",
                    side_effect=judge,
                ) as evaluate:
                    with self.assertRaises(DciBenchmarkError):
                        run_benchmark(request, paths=resolve_dci_paths(root))
            self.assertEqual(run.call_count, 1)
            evaluate.assert_not_called()

    def test_missing_or_malformed_agent_cost_evidence_fails_closed(self) -> None:
        from asterion.dci.benchmark import _validated_agent_cost_from_state

        messages = [
            {
                "event": "message_end",
                "message": {
                    "role": "assistant",
                    "usage": {"cost": {"total": 0.25}},
                },
            }
        ]
        self.assertEqual(
            _validated_agent_cost_from_state({"messages": messages}),
            0.25,
        )
        invalid_values = (
            None,
            True,
            "0.25",
            -0.25,
            float("inf"),
            float("nan"),
        )
        for value in invalid_values:
            with self.subTest(value=value):
                malformed = json.loads(json.dumps(messages))
                malformed[0]["message"]["usage"]["cost"]["total"] = value
                with self.assertRaisesRegex(
                    DciBenchmarkError,
                    "^DCI benchmark Agent cost evidence is invalid$",
                ):
                    _validated_agent_cost_from_state({"messages": malformed})
        for state in (
            {},
            {"messages": []},
            {"messages": [{"event": "message_end", "message": {}}]},
            {
                "messages": [
                    {
                        "event": "message_end",
                        "message": {
                            "role": "assistant",
                            "usage": {},
                        },
                    }
                ]
            },
        ):
            with self.subTest(state=state):
                with self.assertRaisesRegex(
                    DciBenchmarkError,
                    "^DCI benchmark Agent cost evidence is invalid$",
                ):
                    _validated_agent_cost_from_state(state)

    def test_compatible_judge_cache_uses_no_judge_reservation_or_transport(
        self,
    ) -> None:
        async def agent(*_args: object, **_kwargs: object) -> None:
            return None

        async def judge(*_args: object, **_kwargs: object) -> dict[str, object]:
            raise AssertionError("Judge transport must not run for a cache hit")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            authority = authorize(
                root / "judge-cache",
                max_agents=1,
                max_judges=1,
                selected_query_ids=query_ids(1),
            )
            request = self.request(root, authority, rows=1)
            with self.patches(agent=agent, judge=judge, agent_cost=lambda *_: 0.25):
                with patch(
                    "asterion.dci.benchmark._reusable_judge_verdict",
                    return_value=self.verdict(),
                ), patch(
                    "asterion.dci.benchmark.evaluate_run_directory_async",
                    side_effect=judge,
                ) as evaluate:
                    run_benchmark(request, paths=resolve_dci_paths(root))
            evaluate.assert_not_called()
            receipt = consumed_full_execution_authorization_snapshot(authority)
            ledger = receipt_ledger(receipt)
            self.assertEqual(
                ledger["completed_agent_operations"], 1
            )
            self.assertEqual(
                ledger["completed_judge_operations"], 0
            )
            self.assertEqual(ledger["actual_cost_usd"], 0.25)

    def test_external_cancellation_blocks_waiting_rows(self) -> None:
        async def scenario() -> None:
            started = asyncio.Event()
            release = asyncio.Event()
            calls = 0

            async def agent(*_args: object, **_kwargs: object) -> None:
                nonlocal calls
                calls += 1
                started.set()
                await release.wait()

            async def judge(
                *_args: object, **_kwargs: object
            ) -> dict[str, object]:
                return self.verdict()

            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                authority = authorize(
                    root / "cancel",
                    max_agents=2,
                    max_judges=2,
                    selected_query_ids=query_ids(2),
                )
                request = self.request(root, authority, max_concurrency=1)
                with self.patches(
                    agent=agent,
                    judge=judge,
                    agent_cost=lambda *_: 0.0,
                ):
                    task = asyncio.create_task(
                        run_benchmark_async(
                            request,
                            paths=resolve_dci_paths(root),
                        )
                    )
                    await started.wait()
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertEqual(calls, 1)
                with self.assertRaisesRegex(
                    ExperimentAuthorizationError,
                    "^full execution authorization is inactive$",
                ):
                    reserve_full_execution_operation(
                        authority, self.scope_id, "agent"
                    )

        asyncio.run(scenario())


class ReproductionCliTests(unittest.TestCase):
    def _execute_argv(
        self,
        output_root: Path,
        *,
        scopes: tuple[str, ...] = ("bright.biology.main.full",),
        limit: int | None = None,
        max_agent_operations: int | None = None,
        max_judge_operations: int = 1,
    ) -> list[str]:
        if max_agent_operations is None:
            if limit is not None:
                max_agent_operations = limit * len(scopes)
            else:
                try:
                    max_agent_operations = sum(
                        resolve_paper_experiment_scope(scope).selection_count
                        for scope in scopes
                    )
                except ValueError:
                    max_agent_operations = 103 * len(scopes)
        argv = [
            "paper",
            "reproduce",
            "--profile",
            "paper-reference/pi",
            "--output-root",
            str(output_root),
            "--execute",
            "--max-agent-operations",
            str(max_agent_operations),
            "--max-judge-operations",
            str(max_judge_operations),
            "--max-cost-usd",
            "25",
            "--max-agent-cost-per-operation-usd",
            "0.20",
            "--max-judge-cost-per-operation-usd",
            "0.05",
        ]
        if limit is not None:
            argv.extend(("--limit", str(limit)))
        for scope in scopes:
            argv.extend(("--scope", scope))
        return argv

    def _fixture_batch_profiles(self, root: Path) -> dict[str, dict[str, object]]:
        from asterion.dci.paper_benchmarks import resolve_paper_benchmark

        profiles: dict[str, dict[str, object]] = {}
        for name in (
            "bright.biology",
            "bright.earth-science",
            "browsecomp-plus",
        ):
            benchmark = resolve_paper_benchmark(name)
            dataset = root / benchmark.dataset_path
            corpus = root / benchmark.corpus_path
            dataset.parent.mkdir(parents=True, exist_ok=True)
            corpus.mkdir(parents=True, exist_ok=True)
            dataset.write_text('{"query_id":"q1","query":"q","gold_ids":["d"]}\n')
            self.assertIsNotNone(benchmark.batch_profile)
            profiles[cast(str, benchmark.batch_profile)] = {
                "dataset": benchmark.dataset_path,
                "output_root": f"outputs/{name}",
                "corpus": benchmark.corpus_path,
                "mode": benchmark.mode,
                "provider": "openai",
                "model": "gpt-5.4-nano",
                "tools": "read,bash",
                "max_turns": 300,
                "max_concurrency": 1,
                "runtime_context_level": "level3",
                "thinking_level": "high",
                "node_max_old_space_size_mb": 4096,
            }
        return profiles

    def test_plan_mode_is_default_and_needs_no_budget_configuration(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output_root = root / "reproduction"
            with patch(
                "asterion.dci.experiment_profiles.authorize_full_execution"
            ) as authorize, patch(
                "asterion.dci.benchmark.execute_authorized_reproduction",
                create=True,
            ) as execute:
                code = dci_main(
                    [
                        "paper",
                        "reproduce",
                        "--profile",
                        "paper-reference/pi",
                        "--output-root",
                        str(output_root),
                    ],
                    repo_root=root,
                    stdout=stdout,
                    stderr=stderr,
                )
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertIn("Execution requested: no", stdout.getvalue())
            self.assertIn(
                "Agent operations performed: 0", stdout.getvalue()
            )
            self.assertIn(
                "Judge operations performed: 0", stdout.getvalue()
            )
            self.assertFalse(output_root.exists())
            authorize.assert_not_called()
            execute.assert_not_called()

    def test_plan_only_limit_one_is_zero_operation_and_creates_no_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "absent"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "asterion.dci.cli.load_asterion_dci_env"
            ) as load_env, patch(
                "asterion.dci.cli._preflight_scope_selected_ids"
            ) as read_selected_ids, patch(
                "asterion.dci.experiment_profiles.authorize_full_execution"
            ) as authorize:
                code = dci_main(
                    [
                        "paper",
                        "reproduce",
                        "--profile",
                        "paper-reference/pi",
                        "--scope",
                        "bright.robotics.main.full",
                        "--limit",
                        "1",
                        "--output-root",
                        str(output_root),
                    ],
                    stdout=stdout,
                    stderr=stderr,
                )
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertFalse(output_root.exists())
        self.assertIn("Selected queries: 1", stdout.getvalue())
        self.assertIn("Maximum agent operations: 1", stdout.getvalue())
        self.assertIn("Maximum Judge operations: 0", stdout.getvalue())
        self.assertIn("Agent operations performed: 0", stdout.getvalue())
        self.assertIn("Full authorization issued: no", stdout.getvalue())
        load_env.assert_not_called()
        read_selected_ids.assert_not_called()
        authorize.assert_not_called()

    def test_limit_validation_fails_before_authority(self) -> None:
        scope_id = "bright.robotics.main.full"
        cases = (
            ("zero", "0"),
            ("negative", "-1"),
            ("boolean-like", "true"),
            (
                "above-scope-count",
                str(resolve_paper_experiment_scope(scope_id).selection_count + 1),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for label, limit in cases:
                with self.subTest(label=label):
                    output_root = root / label
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with patch(
                        "asterion.dci.cli.load_asterion_dci_env"
                    ) as load_env, patch(
                        "asterion.dci.cli._preflight_scope_selected_ids"
                    ) as read_selected_ids, patch(
                        "asterion.dci.experiment_profiles.authorize_full_execution"
                    ) as authorize:
                        code = dci_main(
                            [
                                "paper",
                                "reproduce",
                                "--profile",
                                "paper-reference/pi",
                                "--scope",
                                scope_id,
                                "--limit",
                                limit,
                                "--output-root",
                                str(output_root),
                            ],
                            repo_root=root,
                            stdout=stdout,
                            stderr=stderr,
                        )
                    self.assertEqual(code, 2)
                    self.assertFalse(output_root.exists())
                    load_env.assert_not_called()
                    read_selected_ids.assert_not_called()
                    authorize.assert_not_called()

    def test_execute_requires_all_limits_and_scope_before_authorization(self) -> None:
        required_flags = (
            "--max-agent-operations",
            "--max-judge-operations",
            "--max-cost-usd",
            "--max-agent-cost-per-operation-usd",
            "--max-judge-cost-per-operation-usd",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for missing in (*required_flags, "--scope"):
                with self.subTest(missing=missing):
                    output_root = root / missing.removeprefix("--")
                    argv = self._execute_argv(output_root)
                    if missing == "--scope":
                        scope_index = argv.index("--scope")
                        del argv[scope_index : scope_index + 2]
                    else:
                        flag_index = argv.index(missing)
                        del argv[flag_index : flag_index + 2]
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with patch(
                        "asterion.dci.experiment_profiles.authorize_full_execution"
                    ) as authorize, patch(
                        "asterion.dci.benchmark.execute_authorized_reproduction",
                        create=True,
                    ) as execute:
                        code = dci_main(
                            argv,
                            repo_root=root,
                            stdout=stdout,
                            stderr=stderr,
                        )
                    self.assertEqual(code, 2)
                    self.assertFalse(output_root.exists())
                    authorize.assert_not_called()
                    execute.assert_not_called()

    def test_execute_without_scope_does_not_fall_back_to_profile_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output_root = root / "no-scope"
            argv = self._execute_argv(output_root)
            scope_index = argv.index("--scope")
            del argv[scope_index : scope_index + 2]
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "asterion.dci.paper_benchmarks.resolve_experiment_scope"
            ) as resolve_scope, patch(
                "asterion.dci.experiment_profiles.authorize_full_execution"
            ) as authorize:
                code = dci_main(
                    argv,
                    repo_root=root,
                    stdout=stdout,
                    stderr=stderr,
                )
        self.assertEqual(code, 2)
        self.assertFalse(output_root.exists())
        resolve_scope.assert_not_called()
        authorize.assert_not_called()

    def test_execute_rejects_invalid_scopes_before_output_creation(self) -> None:
        cases = (
            ("duplicate", ("bright.biology.main.full", "bright.biology.main.full")),
            ("unknown", ("unknown.scope",)),
            ("upstream-only", ("qa.bamboogle.upstream.sample50",)),
            ("unavailable", ("qa.bamboogle.main.full",)),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for label, scopes in cases:
                with self.subTest(label=label):
                    output_root = root / label
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with patch(
                        "asterion.dci.experiment_profiles.authorize_full_execution"
                    ) as authorize, patch(
                        "asterion.dci.benchmark.execute_authorized_reproduction",
                        create=True,
                    ) as execute:
                        code = dci_main(
                            self._execute_argv(output_root, scopes=scopes),
                            repo_root=root,
                            stdout=stdout,
                            stderr=stderr,
                        )
                    self.assertEqual(code, 2)
                    self.assertFalse(output_root.exists())
                    authorize.assert_not_called()
                    execute.assert_not_called()

    def test_execute_rejects_partial_selection_scopes_before_authorization(self) -> None:
        cases = (
            ("beir.arguana.main.random50", "beir.arguana"),
            ("browsecomp-plus.analysis.n100", "bcplus.openai"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            from asterion.dci.paper_benchmarks import resolve_paper_benchmark

            for scope_id, batch_profile in cases:
                with self.subTest(scope=scope_id):
                    benchmark = resolve_paper_benchmark(
                        "beir.arguana"
                        if batch_profile == "beir.arguana"
                        else "browsecomp-plus"
                    )
                    output_root = root / scope_id.replace(".", "_")
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with patch(
                        "asterion.dci.cli._load_batch_profiles",
                        return_value={
                            batch_profile: {
                                "dataset": benchmark.dataset_path,
                                "output_root": f"outputs/{scope_id}",
                                "corpus": benchmark.corpus_path,
                                "mode": benchmark.mode,
                                "provider": "openai",
                                "model": "gpt-5.4-nano",
                                "tools": "read,bash",
                                "max_turns": 300,
                                "max_concurrency": 1,
                                "runtime_context_level": "level3",
                                "thinking_level": "high",
                                "node_max_old_space_size_mb": 4096,
                            }
                        },
                    ), patch(
                        "asterion.dci.cli._preflight_benchmark_host_inputs"
                    ), patch(
                        "asterion.dci.cli._preflight_scope_selected_ids",
                        return_value=("q1",),
                    ), patch(
                        "asterion.dci.cli.validate_dci_run_request"
                    ), patch(
                        "asterion.dci.cli.validate_benchmark_metric_selection"
                    ), patch(
                        "asterion.dci.experiment_profiles.authorize_full_execution"
                    ) as authorize, patch(
                        "asterion.dci.benchmark.execute_authorized_reproduction",
                        create=True,
                    ) as execute:
                        code = dci_main(
                            self._execute_argv(output_root, scopes=(scope_id,)),
                            repo_root=root,
                            stdout=stdout,
                            stderr=stderr,
                        )
                    self.assertEqual(code, 2)
                    self.assertFalse(output_root.exists())
                    authorize.assert_not_called()
                    execute.assert_not_called()

    def test_execute_rejects_profile_incompatible_scope_before_output_creation(
        self,
    ) -> None:
        real_profile = resolve_experiment_profile("paper-reference/pi")
        compatible_scope = "bright.earth-science.main.full"
        compatible_digest = real_profile.selected_ids_sha256[
            real_profile.scope_ids.index(compatible_scope)
        ]
        narrowed_profile = replace(
            real_profile,
            scope_ids=(compatible_scope,),
            selected_ids_sha256=(compatible_digest,),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output_root = root / "incompatible"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "asterion.dci.experiment_profiles.resolve_experiment_profile",
                return_value=narrowed_profile,
            ), patch(
                "asterion.dci.experiment_profiles.authorize_full_execution"
            ) as authorize, patch(
                "asterion.dci.benchmark.execute_authorized_reproduction",
                create=True,
            ) as execute:
                code = dci_main(
                    self._execute_argv(output_root),
                    repo_root=root,
                    stdout=stdout,
                    stderr=stderr,
                )
            self.assertEqual(code, 2)
            self.assertFalse(output_root.exists())
            authorize.assert_not_called()
            execute.assert_not_called()

    def test_execute_rejects_caps_below_bounded_plan(self) -> None:
        scope_id = "browsecomp-plus.main.all830"
        cases = (
            ("agent", 1, 2),
            ("judge", 2, 1),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for label, max_agents, max_judges in cases:
                with self.subTest(label=label):
                    output_root = root / label
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with patch(
                        "asterion.dci.cli.load_asterion_dci_env"
                    ) as load_env, patch(
                        "asterion.dci.cli._preflight_scope_selected_ids"
                    ) as read_selected_ids, patch(
                        "asterion.dci.experiment_profiles.authorize_full_execution"
                    ) as authorize:
                        code = dci_main(
                            self._execute_argv(
                                output_root,
                                scopes=(scope_id,),
                                limit=2,
                                max_agent_operations=max_agents,
                                max_judge_operations=max_judges,
                            ),
                            repo_root=root,
                            stdout=stdout,
                            stderr=stderr,
                        )
                    self.assertEqual(code, 2)
                    self.assertFalse(output_root.exists())
                    load_env.assert_not_called()
                    read_selected_ids.assert_not_called()
                    authorize.assert_not_called()

    def test_execute_authorizes_and_dispatches_exact_same_process_plan(self) -> None:
        original_authorize = authorize_full_execution
        captured: dict[str, Any] = {}

        def authorize_spy(
            *args: Any, **kwargs: Any
        ) -> FullExecutionAuthorization:
            cast(list[str], captured.setdefault("order", [])).append(
                "authorize"
            )
            authority = original_authorize(*args, **kwargs)
            captured["authorize_args"] = args
            captured["authorize_kwargs"] = kwargs
            captured["authority"] = authority
            return authority

        def execute_spy(*args: Any, **kwargs: Any) -> dict[str, object]:
            captured["execute_args"] = args
            captured["execute_kwargs"] = kwargs
            authority = cast(FullExecutionAuthorization, kwargs["authority"])
            items = tuple(kwargs["execution_items"])
            captured["dataset_files"] = tuple(
                item.request.dataset.is_file() for item in items
            )
            captured["corpus_dirs"] = tuple(
                item.request.corpus.is_dir() for item in items
            )
            return {
                "schema": "dci.paper-reproduction-result/v1",
                "profile_id": kwargs["profile"].profile_id,
                "authorized_scope_ids": list(kwargs["scope_ids"]),
                "operation_counts": {
                    "agent": 7,
                    "judge": 0,
                    "total": 7,
                },
                "outputs": [
                    {
                        "scope_id": item.scope_id,
                        "output_root": str(item.request.output_root),
                    }
                    for item in items
                ],
                "receipt": {
                    "schema": "dci.full-execution-authorization-receipt/v1",
                    "profile_id": authority.profile_id,
                },
            }

        def selected_ids_spy(_request: object, _scope: object) -> tuple[str, ...]:
            cast(list[str], captured.setdefault("order", [])).append(
                "selected-ids"
            )
            return ("q1",)

        scopes = ("bright.biology.main.full",)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output_root = root / "reproduction"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "asterion.dci.cli._load_batch_profiles",
                return_value=self._fixture_batch_profiles(root),
            ), patch(
                "asterion.dci.cli._preflight_scope_selected_ids",
                side_effect=selected_ids_spy,
            ), patch(
                "asterion.dci.cli.validate_dci_run_request"
            ) as validate_run, patch(
                "asterion.dci.experiment_profiles.authorize_full_execution",
                side_effect=authorize_spy,
            ) as authorize, patch(
                "asterion.dci.benchmark.execute_authorized_reproduction",
                side_effect=execute_spy,
                create=True,
            ) as execute:
                code = dci_main(
                    self._execute_argv(
                        output_root,
                        scopes=scopes,
                        limit=1,
                    ),
                    repo_root=root,
                    stdout=stdout,
                    stderr=stderr,
                )
        self.assertEqual(code, 0, stderr.getvalue())
        authorize.assert_called_once()
        execute.assert_called_once()
        validate_run.assert_called()
        self.assertEqual(captured["authorize_args"], ())
        self.assertEqual(
            captured["order"],
            ["selected-ids", "authorize"],
        )
        authorize_kwargs = cast(dict[str, Any], captured["authorize_kwargs"])
        self.assertEqual(authorize_kwargs["profile"].profile_id, "paper-reference/pi")
        self.assertEqual(authorize_kwargs["scope_ids"], scopes)
        self.assertEqual(authorize_kwargs["output_root"], output_root)
        self.assertEqual(authorize_kwargs["max_agent_operations"], 1)
        self.assertEqual(authorize_kwargs["max_judge_operations"], 1)
        self.assertEqual(authorize_kwargs["max_cost_usd"], 25.0)
        self.assertEqual(authorize_kwargs["max_agent_cost_per_operation_usd"], 0.2)
        self.assertEqual(authorize_kwargs["max_judge_cost_per_operation_usd"], 0.05)
        self.assertEqual(authorize_kwargs["selected_query_counts"], (1,))
        self.assertEqual(authorize_kwargs["planned_agent_operations"], 1)
        self.assertEqual(authorize_kwargs["planned_judge_operations"], 0)
        self.assertEqual(
            authorize_kwargs["bounded_selected_ids_sha256"],
            (canonical_sha256(("q1",)),),
        )
        authority = cast(FullExecutionAuthorization, captured["authority"])
        execute_kwargs = cast(dict[str, Any], captured["execute_kwargs"])
        self.assertIs(execute_kwargs["authority"], authority)
        self.assertIs(execute_kwargs["profile"], authorize_kwargs["profile"])
        self.assertEqual(execute_kwargs["scope_ids"], scopes)
        self.assertEqual(execute_kwargs["output_root"], output_root)
        items = tuple(execute_kwargs["execution_items"])
        self.assertEqual(tuple(item.scope_id for item in items), scopes)
        self.assertEqual(tuple(item.request.limit for item in items), (1,))
        self.assertEqual(
            tuple(item.request.experiment_scope_id for item in items), scopes
        )
        self.assertTrue(
            all(item.request.full_execution_authorization is authority for item in items)
        )
        self.assertTrue(
            all(item.request.paper_ir_duplicate_handling == "deduplicated" for item in items)
        )
        self.assertTrue(all(cast(tuple[bool, ...], captured["dataset_files"])))
        self.assertTrue(all(cast(tuple[bool, ...], captured["corpus_dirs"])))
        combined = stdout.getvalue() + stderr.getvalue()
        self.assertIn("Execution requested: yes", stdout.getvalue())
        self.assertIn("Agent operations performed: 7", stdout.getvalue())
        self.assertIn("Judge operations performed: 0", stdout.getvalue())
        self.assertNotIn(authority._issuance_token, combined)
        self.assertNotIn(repr(authority), combined)

    def test_execute_applies_limit_per_scope_across_ir_and_qa(self) -> None:
        original_authorize = authorize_full_execution
        captured: dict[str, Any] = {}

        def authorize_spy(
            *args: Any, **kwargs: Any
        ) -> FullExecutionAuthorization:
            authority = original_authorize(*args, **kwargs)
            captured["authorize_kwargs"] = kwargs
            captured["authority"] = authority
            return authority

        def execute_spy(*args: Any, **kwargs: Any) -> dict[str, object]:
            captured["execution_items"] = tuple(kwargs["execution_items"])
            return {
                "schema": "dci.paper-reproduction-result/v1",
                "operation_counts": {"agent": 2, "judge": 1, "total": 3},
                "outputs": [
                    {"scope_id": item.scope_id}
                    for item in kwargs["execution_items"]
                ],
            }

        scopes = (
            "bright.biology.main.full",
            "browsecomp-plus.main.all830",
        )
        source_ids = (
            ("ir-prefix", "ir-later"),
            ("qa-prefix", "qa-later"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output_root = root / "reproduction"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "asterion.dci.cli._load_batch_profiles",
                return_value=self._fixture_batch_profiles(root),
            ), patch(
                "asterion.dci.cli._preflight_scope_selected_ids",
                side_effect=source_ids,
            ), patch(
                "asterion.dci.cli.validate_dci_run_request"
            ), patch(
                "asterion.dci.experiment_profiles.authorize_full_execution",
                side_effect=authorize_spy,
            ), patch(
                "asterion.dci.benchmark.execute_authorized_reproduction",
                side_effect=execute_spy,
                create=True,
            ):
                code = dci_main(
                    self._execute_argv(
                        output_root,
                        scopes=scopes,
                        limit=1,
                        max_judge_operations=1,
                    ),
                    repo_root=root,
                    stdout=stdout,
                    stderr=stderr,
                )
        self.assertEqual(code, 0, stderr.getvalue())
        authorize_kwargs = cast(dict[str, Any], captured["authorize_kwargs"])
        self.assertEqual(authorize_kwargs["selected_query_counts"], (1, 1))
        self.assertEqual(authorize_kwargs["planned_agent_operations"], 2)
        self.assertEqual(authorize_kwargs["planned_judge_operations"], 1)
        self.assertEqual(
            authorize_kwargs["bounded_selected_ids_sha256"],
            (
                canonical_sha256(("ir-prefix",)),
                canonical_sha256(("qa-prefix",)),
            ),
        )
        items = cast(tuple[Any, ...], captured["execution_items"])
        self.assertEqual(tuple(item.request.limit for item in items), (1, 1))

    def test_execute_output_reports_actual_operations_once(self) -> None:
        scopes = ("bright.biology.main.full",)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output_root = root / "reproduction"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "asterion.dci.cli._load_batch_profiles",
                return_value=self._fixture_batch_profiles(root),
            ), patch(
                "asterion.dci.cli._preflight_scope_selected_ids",
                return_value=("q1",),
            ), patch(
                "asterion.dci.cli.validate_dci_run_request"
            ), patch(
                "asterion.dci.benchmark.execute_authorized_reproduction",
                return_value={
                    "schema": "dci.paper-reproduction-result/v1",
                    "operation_counts": {"agent": 3, "judge": 1, "total": 4},
                    "outputs": [{"scope_id": scopes[0]}],
                },
                create=True,
            ):
                code = dci_main(
                    self._execute_argv(
                        output_root,
                        scopes=scopes,
                        limit=1,
                    ),
                    repo_root=root,
                    stdout=stdout,
                    stderr=stderr,
                )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(stdout.getvalue().count("Agent operations performed:"), 1)
        self.assertEqual(stdout.getvalue().count("Judge operations performed:"), 1)
        self.assertIn("Agent operations performed: 3", stdout.getvalue())
        self.assertIn("Judge operations performed: 1", stdout.getvalue())
        self.assertNotIn("Agent operations performed: 0", stdout.getvalue())
        self.assertNotIn("Judge operations performed: 0", stdout.getvalue())

    def test_execute_cancels_authority_when_child_root_lookup_fails(self) -> None:
        captured: dict[str, FullExecutionAuthorization] = {}
        original_authorize = authorize_full_execution
        scope_id = "bright.biology.main.full"

        def authorize_spy(
            *args: Any, **kwargs: Any
        ) -> FullExecutionAuthorization:
            authority = original_authorize(*args, **kwargs)
            captured["authority"] = authority
            return authority

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output_root = root / "reproduction"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "asterion.dci.cli._load_batch_profiles",
                return_value=self._fixture_batch_profiles(root),
            ), patch(
                "asterion.dci.cli._preflight_scope_selected_ids",
                return_value=("q1",),
            ), patch(
                "asterion.dci.cli.validate_dci_run_request"
            ), patch(
                "asterion.dci.experiment_profiles.authorize_full_execution",
                side_effect=authorize_spy,
            ), patch(
                "asterion.dci.experiment_profiles.authorized_scope_output_root",
                side_effect=ExperimentAuthorizationError("safe failure"),
            ):
                code = dci_main(
                    self._execute_argv(
                        output_root,
                        scopes=(scope_id,),
                        limit=1,
                    ),
                    repo_root=root,
                    stdout=stdout,
                    stderr=stderr,
                )
            self.assertEqual(code, 2)
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "inactive|cancelled",
            ):
                reserve_full_execution_operation(
                    captured["authority"], scope_id, "agent"
                )


class LegacyFullAuthorizationTests(unittest.TestCase):
    def test_legacy_helper_delegates_to_default_off_cli_without_authority(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "private"
            with patch(
                "asterion.dci.experiment_profiles.authorize_full_execution"
            ) as authorize, patch(
                "asterion.dci.benchmark.execute_authorized_reproduction",
                create=True,
            ) as execute:
                result = paper_reproduce_main(
                    [
                        "--profile",
                        "paper-reference/pi",
                        "--output-root",
                        str(output_root),
                    ],
                    stdout=stdout,
                    stderr=stderr,
                )
        self.assertEqual(result, 0, stderr.getvalue())
        self.assertIn("Execution requested: no", stdout.getvalue())
        self.assertFalse(output_root.exists())
        authorize.assert_not_called()
        execute.assert_not_called()

    def test_legacy_issue_and_exit_flags_are_rejected_without_authority(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "private"
            with patch(
                "asterion.dci.experiment_profiles.authorize_full_execution"
            ) as authorize:
                result = paper_reproduce_main(
                    [
                        "--profile",
                        "paper-reference/pi",
                        "--output-root",
                        str(output_root),
                        "--estimated-budget-usd",
                        "0",
                        "--authorize-full",
                    ],
                    stdout=stdout,
                    stderr=stderr,
                )
        self.assertEqual(result, 2)
        self.assertEqual(stderr.getvalue(), "DCI paper command failed\n")
        self.assertFalse(output_root.exists())
        authorize.assert_not_called()
