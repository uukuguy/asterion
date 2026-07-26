"""Tests for one-use, multi-scope DCI full-execution authority."""

from __future__ import annotations

import hashlib
import inspect
import io
import json
import math
import os
import stat
import tempfile
import traceback
import unittest
import asyncio
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock, patch

from asterion.dci import cli as cli_module
from asterion.dci import experiment_profiles as profiles
from asterion.dci import paper_benchmarks
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
    DatasetInputBinding,
    canonical_sha256,
    resolve_paper_benchmark,
    resolve_paper_experiment_scope,
)
from asterion.dci.verification import paper_reproduce_main


class AlwaysEqualStr(str):
    def __eq__(self, other: object) -> bool:
        del other
        return True

    __hash__ = str.__hash__


def receipt_ledger(receipt: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], receipt["ledger"])


def query_ids(count: int) -> tuple[str, ...]:
    return tuple(f"q-{index}" for index in range(1, count + 1))


def fixture_dataset_binding(
    scope_id: str,
    *,
    raw_content_sha256: str = "a" * 64,
    device: int = 1,
    inode: int = 2,
) -> DatasetInputBinding:
    benchmark = resolve_paper_benchmark(
        resolve_paper_experiment_scope(scope_id).dataset_id
    )
    return DatasetInputBinding(
        raw_content_sha256=raw_content_sha256,
        paper_benchmark_identity_sha256=benchmark.identity_sha256,
        device=device,
        inode=inode,
    )


def fixture_dataset_bindings(
    scope_ids: tuple[str, ...],
) -> tuple[DatasetInputBinding, ...]:
    return tuple(
        fixture_dataset_binding(scope_id, device=1, inode=index)
        for index, scope_id in enumerate(scope_ids, 2)
    )


def dataset_binding_for_path(path: Path, scope_id: str) -> DatasetInputBinding:
    metadata = path.stat()
    return fixture_dataset_binding(
        scope_id,
        raw_content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )


def reproduction_output(scope_id: str, *, identity: int = 1) -> dict[str, object]:
    return {
        "scope_id": scope_id,
        "output_root_device": identity,
        "output_root_inode": identity,
        "manifest_artifact": hashlib.sha256(scope_id.encode()).hexdigest() + ".json",
        "manifest_identity_sha256": hashlib.sha256(
            f"manifest:{scope_id}".encode()
        ).hexdigest(),
    }


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
    dataset_input_bindings: tuple[DatasetInputBinding, ...] | None = None,
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
    expected_judge_operations = sum(
        len(query_ids_by_scope[scope])
        for scope in scopes
        if resolve_paper_benchmark(
            resolve_paper_experiment_scope(scope).dataset_id
        ).mode
        == "qa"
    )
    if dataset_input_bindings is None:
        if selected_query_ids is not None and len(scopes) == 1:
            dataset = output_root.parent / "dataset.jsonl"
            dataset.write_text(
                "".join(
                    json.dumps(
                        {
                            "query_id": query_id,
                            "query": f"question {index}",
                            "answer": "gold",
                        }
                    )
                    + "\n"
                    for index, query_id in enumerate(
                        selected_query_ids,
                        1,
                    )
                ),
                encoding="utf-8",
            )
            dataset_input_bindings = (
                dataset_binding_for_path(dataset, scopes[0]),
            )
        else:
            dataset_input_bindings = tuple(
                fixture_dataset_binding(
                    scope,
                    device=1,
                    inode=index,
                )
                for index, scope in enumerate(scopes, 2)
            )
    return authorize_full_execution(
        profile=resolve_experiment_profile("paper-reference/pi"),
        scope_ids=scopes,
        dataset_input_bindings=dataset_input_bindings,
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
        planned_judge_operations=expected_judge_operations,
        output_root=output_root,
        max_agent_operations=max_agents,
        max_judge_operations=max_judges,
        max_cost_usd=max_cost,
        max_agent_cost_per_operation_usd=max_agent_cost,
        max_judge_cost_per_operation_usd=max_judge_cost,
        invocation_authorized=True,
    )


class FullExecutionAuthorizationTests(unittest.TestCase):
    def test_dataset_input_binding_is_frozen_and_validated(self) -> None:
        binding_type = getattr(paper_benchmarks, "DatasetInputBinding", None)
        self.assertIsNotNone(binding_type)
        if binding_type is None:
            return
        binding = binding_type(
            raw_content_sha256="a" * 64,
            paper_benchmark_identity_sha256="b" * 64,
            device=1,
            inode=2,
        )
        self.assertEqual(binding.raw_content_sha256, "a" * 64)
        with self.assertRaises(FrozenInstanceError):
            binding.inode = 3
        invalid_cases = (
            {"raw_content_sha256": "not-a-digest"},
            {"paper_benchmark_identity_sha256": "not-a-digest"},
            {"raw_content_sha256": AlwaysEqualStr("a" * 64)},
            {
                "paper_benchmark_identity_sha256": AlwaysEqualStr(
                    "b" * 64
                )
            },
            {"device": -1},
            {"inode": 0},
        )
        defaults = {
            "raw_content_sha256": "a" * 64,
            "paper_benchmark_identity_sha256": "b" * 64,
            "device": 1,
            "inode": 2,
        }
        for changes in invalid_cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(
                ValueError,
                "^DCI dataset input binding is invalid$",
            ):
                binding_type(**(defaults | changes))

    def test_paper_dataset_reader_binds_exact_descriptor_and_raw_bytes(
        self,
    ) -> None:
        reader = getattr(
            paper_benchmarks,
            "read_paper_benchmark_dataset",
            None,
        )
        self.assertIsNotNone(reader)
        if reader is None:
            return
        with tempfile.TemporaryDirectory() as temporary:
            dataset = Path(temporary).resolve() / "dataset.jsonl"
            raw = b'{"query_id":"q-001","query":"sentinel body","gold_ids":["d"]}\n'
            dataset.write_bytes(raw)
            benchmark = resolve_paper_benchmark("bright.biology")
            loaded, binding = reader(dataset, benchmark)
            metadata = dataset.stat()
        self.assertEqual(loaded, raw)
        self.assertEqual(
            binding,
            DatasetInputBinding(
                raw_content_sha256=hashlib.sha256(raw).hexdigest(),
                paper_benchmark_identity_sha256=benchmark.identity_sha256,
                device=metadata.st_dev,
                inode=metadata.st_ino,
            ),
        )

    def test_dataset_reader_rejects_symlinked_parent_and_closes_all_fds(
        self,
    ) -> None:
        benchmark = resolve_paper_benchmark("bright.biology")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real"
            real_parent.mkdir()
            dataset = real_parent / "dataset.jsonl"
            dataset.write_text('{"query_id":"q-001","query":"body"}\n')
            linked_parent = root / "linked"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaises((OSError, ValueError)):
                paper_benchmarks.read_paper_benchmark_dataset(
                    linked_parent / dataset.name,
                    benchmark,
                )

            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            nested_dataset = nested / "dataset.jsonl"
            nested_dataset.write_text(
                '{"query_id":"q-001","query":"body"}\n'
            )
            opened_descriptors: list[int] = []
            real_open = os.open

            def tracking_open(
                path: (
                    str
                    | bytes
                    | os.PathLike[str]
                    | os.PathLike[bytes]
                ),
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                if dir_fd is None:
                    descriptor = real_open(path, flags, mode)
                else:
                    descriptor = real_open(
                        path,
                        flags,
                        mode,
                        dir_fd=dir_fd,
                    )
                opened_descriptors.append(descriptor)
                return descriptor

            with patch.object(
                paper_benchmarks.os,
                "open",
                side_effect=tracking_open,
            ), patch.object(
                paper_benchmarks,
                "_read_paper_dataset_descriptor",
                side_effect=OSError("SENTINEL read fault"),
            ):
                with self.assertRaises(OSError):
                    paper_benchmarks.read_paper_benchmark_dataset(
                        nested_dataset,
                        benchmark,
                    )
            self.assertGreaterEqual(len(opened_descriptors), 3)
            for descriptor in opened_descriptors:
                with self.subTest(descriptor=descriptor), self.assertRaises(
                    OSError
                ):
                    os.fstat(descriptor)

    def test_dataset_input_bindings_are_scope_bound_and_consumption_gated(
        self,
    ) -> None:
        self.assertIn(
            "dataset_input_bindings",
            inspect.signature(authorize_full_execution).parameters,
        )
        if (
            "dataset_input_bindings"
            not in inspect.signature(authorize_full_execution).parameters
        ):
            return
        scopes = (
            "bright.biology.main.full",
            "bright.earth-science.main.full",
        )
        bindings = tuple(
            fixture_dataset_binding(scope, device=10, inode=index)
            for index, scope in enumerate(scopes, 20)
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authority = authorize_full_execution(
                profile=resolve_experiment_profile("paper-reference/pi"),
                scope_ids=scopes,
                dataset_input_bindings=bindings,
                bounded_selected_ids_sha256=(
                    canonical_sha256(("q-001",)),
                    canonical_sha256(("q-002",)),
                ),
                selected_query_counts=(1, 1),
                planned_agent_operations=2,
                planned_judge_operations=0,
                output_root=root / "private",
                invocation_authorized=True,
                max_agent_operations=2,
                max_judge_operations=1,
                max_cost_usd=1,
                max_agent_cost_per_operation_usd=1,
                max_judge_cost_per_operation_usd=1,
            )
            self.assertEqual(authority.dataset_input_bindings, bindings)
            for scope, binding in zip(scopes, bindings, strict=True):
                public_binding = authority.dataset_input_bindings[
                    scopes.index(scope)
                ]
                self.assertIsNot(public_binding, binding)
                private_copy = (
                    profiles._authorized_scope_dataset_input_binding(
                        authority, scope
                    )
                )
                self.assertEqual(private_copy, binding)
                self.assertIsNot(private_copy, binding)
                self.assertIsNot(
                    private_copy,
                    public_binding,
                )

            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "^full execution dataset input binding is invalid$",
            ):
                consume_full_execution_authorization(authority, scopes[0])
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "^full execution dataset input binding is invalid$",
            ):
                consume_full_execution_authorization(
                    authority,
                    scopes[0],
                    fixture_dataset_binding(scopes[0], device=10, inode=99),
                )
            consume_full_execution_authorization(
                authority,
                scopes[0],
                bindings[0],
            )

            forged = tuple(
                fixture_dataset_binding(scope, device=10, inode=index + 100)
                for index, scope in enumerate(scopes, 20)
            )
            object.__setattr__(authority, "dataset_input_bindings", forged)
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "^full execution authorization is invalid$",
            ):
                profiles._authorized_scope_dataset_input_binding(
                    authority, scopes[1]
                )

    def test_public_and_accessor_binding_mutations_never_change_private_state(
        self,
    ) -> None:
        scope_id = "bright.biology.main.full"
        mutations: tuple[tuple[str, object], ...] = (
            ("raw_content_sha256", "b" * 64),
            ("paper_benchmark_identity_sha256", "c" * 64),
            ("device", 999),
            ("inode", 999),
            ("raw_content_sha256", AlwaysEqualStr("0" * 64)),
            (
                "paper_benchmark_identity_sha256",
                AlwaysEqualStr("0" * 64),
            ),
        )
        for field, value in mutations:
            with self.subTest(field=field, value_type=type(value).__name__):
                with tempfile.TemporaryDirectory() as temporary:
                    authority = authorize(Path(temporary) / "private")
                    public_binding = authority.dataset_input_bindings[0]
                    object.__setattr__(public_binding, field, value)
                    with self.assertRaisesRegex(
                        ExperimentAuthorizationError,
                        "^full execution authorization is invalid$",
                    ):
                        profiles._authorized_scope_dataset_input_binding(
                            authority,
                            scope_id,
                        )

        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(Path(temporary) / "private")
            first = profiles._authorized_scope_dataset_input_binding(
                authority,
                scope_id,
            )
            original = replace(first)
            object.__setattr__(first, "inode", 999)
            second = profiles._authorized_scope_dataset_input_binding(
                authority,
                scope_id,
            )
            self.assertEqual(second, original)
            self.assertIsNot(first, second)
            consume_full_execution_authorization(
                authority,
                scope_id,
                second,
            )

    def test_consume_rejects_hostile_binding_fields(self) -> None:
        scope_id = "bright.biology.main.full"
        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize(Path(temporary) / "private")
            forged = fixture_dataset_binding(scope_id)
            object.__setattr__(
                forged,
                "raw_content_sha256",
                AlwaysEqualStr("0" * 64),
            )
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "^full execution dataset input binding is invalid$",
            ):
                consume_full_execution_authorization(
                    authority,
                    scope_id,
                    forged,
                )

    def test_invalid_dataset_input_bindings_fail_before_output_creation(
        self,
    ) -> None:
        self.assertIn(
            "dataset_input_bindings",
            inspect.signature(authorize_full_execution).parameters,
        )
        if (
            "dataset_input_bindings"
            not in inspect.signature(authorize_full_execution).parameters
        ):
            return
        scope_id = "bright.biology.main.full"
        valid = fixture_dataset_binding(scope_id)

        def forged_binding(**changes: object) -> DatasetInputBinding:
            binding = object.__new__(DatasetInputBinding)
            values = {
                "raw_content_sha256": valid.raw_content_sha256,
                "paper_benchmark_identity_sha256": (
                    valid.paper_benchmark_identity_sha256
                ),
                "device": valid.device,
                "inode": valid.inode,
            }
            values.update(changes)
            for field, value in values.items():
                object.__setattr__(binding, field, value)
            return binding

        invalid_cases = {
            "missing": (),
            "raw digest": (
                forged_binding(raw_content_sha256="sentinel-private-body"),
            ),
            "benchmark digest": (
                forged_binding(paper_benchmark_identity_sha256="f" * 64),
            ),
            "descriptor": (forged_binding(device=-1, inode=0),),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for label, bindings in invalid_cases.items():
                with self.subTest(label=label):
                    output_root = root / label.replace(" ", "-")
                    with self.assertRaisesRegex(
                        ExperimentAuthorizationError,
                        "^full execution dataset input binding is invalid$",
                    ):
                        authorize_full_execution(
                            profile=resolve_experiment_profile(
                                "paper-reference/pi"
                            ),
                            scope_ids=(scope_id,),
                            dataset_input_bindings=bindings,
                            bounded_selected_ids_sha256=(
                                canonical_sha256(("q-001",)),
                            ),
                            selected_query_counts=(1,),
                            planned_agent_operations=1,
                            planned_judge_operations=0,
                            output_root=output_root,
                            invocation_authorized=True,
                            max_agent_operations=1,
                            max_judge_operations=1,
                            max_cost_usd=1,
                            max_agent_cost_per_operation_usd=1,
                            max_judge_cost_per_operation_usd=1,
                        )
                    self.assertFalse(output_root.exists())

    def test_requires_exact_scope_derived_judge_operation_plan(self) -> None:
        invalid_cases = {
            "QA understated": {
                "scope_ids": ("browsecomp-plus.main.all830",),
                "selected_query_counts": (1,),
                "planned_judge_operations": 0,
                "max_judge_operations": 2,
            },
            "QA overstated": {
                "scope_ids": ("browsecomp-plus.main.all830",),
                "selected_query_counts": (1,),
                "planned_judge_operations": 2,
                "max_judge_operations": 2,
            },
            "IR nonzero": {
                "scope_ids": ("bright.biology.main.full",),
                "selected_query_counts": (1,),
                "planned_judge_operations": 1,
                "max_judge_operations": 2,
            },
            "mixed scope mismatch": {
                "scope_ids": (
                    "bright.biology.main.full",
                    "browsecomp-plus.main.all830",
                ),
                "selected_query_counts": (2, 3),
                "planned_judge_operations": 2,
                "max_judge_operations": 3,
            },
            "exact plan exceeds Judge cap": {
                "scope_ids": ("browsecomp-plus.main.all830",),
                "selected_query_counts": (2,),
                "planned_judge_operations": 2,
                "max_judge_operations": 1,
            },
        }
        for label, case in invalid_cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                output_root = Path(temporary) / "private-output-must-not-exist"
                selected_counts = cast(
                    tuple[int, ...], case["selected_query_counts"]
                )
                scope_ids = cast(tuple[str, ...], case["scope_ids"])
                with self.assertRaisesRegex(
                    ExperimentAuthorizationError,
                    "^full execution bounded operation plan is invalid$",
                ) as raised:
                    authorize_full_execution(
                        profile=resolve_experiment_profile("paper-reference/pi"),
                        scope_ids=scope_ids,
                        dataset_input_bindings=fixture_dataset_bindings(
                            scope_ids
                        ),
                        bounded_selected_ids_sha256=tuple(
                            canonical_sha256(query_ids(count))
                            for count in selected_counts
                        ),
                        selected_query_counts=selected_counts,
                        planned_agent_operations=sum(selected_counts),
                        planned_judge_operations=cast(
                            int, case["planned_judge_operations"]
                        ),
                        output_root=output_root,
                        max_agent_operations=sum(selected_counts),
                        max_judge_operations=cast(
                            int, case["max_judge_operations"]
                        ),
                        max_cost_usd=10,
                        max_agent_cost_per_operation_usd=2,
                        max_judge_cost_per_operation_usd=1,
                        invocation_authorized=True,
                    )
                self.assertEqual(
                    str(raised.exception),
                    "full execution bounded operation plan is invalid",
                )
                self.assertFalse(output_root.exists())

        valid_cases = {
            "QA exact": {
                "scope_ids": ("browsecomp-plus.main.all830",),
                "selected_query_counts": (2,),
                "planned_judge_operations": 2,
            },
            "IR exact": {
                "scope_ids": ("bright.biology.main.full",),
                "selected_query_counts": (2,),
                "planned_judge_operations": 0,
            },
            "mixed exact": {
                "scope_ids": (
                    "bright.biology.main.full",
                    "browsecomp-plus.main.all830",
                ),
                "selected_query_counts": (2, 3),
                "planned_judge_operations": 3,
            },
        }
        for label, case in valid_cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                selected_counts = cast(
                    tuple[int, ...], case["selected_query_counts"]
                )
                scope_ids = cast(tuple[str, ...], case["scope_ids"])
                authority = authorize_full_execution(
                    profile=resolve_experiment_profile("paper-reference/pi"),
                    scope_ids=scope_ids,
                    dataset_input_bindings=fixture_dataset_bindings(scope_ids),
                    bounded_selected_ids_sha256=tuple(
                        canonical_sha256(query_ids(count))
                        for count in selected_counts
                    ),
                    selected_query_counts=selected_counts,
                    planned_agent_operations=sum(selected_counts),
                    planned_judge_operations=cast(
                        int, case["planned_judge_operations"]
                    ),
                    output_root=Path(temporary) / "private",
                    max_agent_operations=sum(selected_counts),
                    max_judge_operations=max(
                        1, cast(int, case["planned_judge_operations"])
                    ),
                    max_cost_usd=10,
                    max_agent_cost_per_operation_usd=2,
                    max_judge_cost_per_operation_usd=1,
                    invocation_authorized=True,
                )
                self.assertEqual(
                    authority.planned_judge_operations,
                    case["planned_judge_operations"],
                )

    def test_legacy_omitted_plans_default_to_exact_scope_derived_counts(self) -> None:
        profile = resolve_experiment_profile("paper-reference/pi")
        scope_id = "browsecomp-plus.main.all830"
        selected_digest = dict(
            zip(profile.scope_ids, profile.selected_ids_sha256, strict=True)
        )[scope_id]
        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize_full_execution(
                profile_id=profile.profile_id,
                output_root=Path(temporary) / "private",
                estimated_budget_usd=10,
                invocation_authorized=True,
                preflight_profile_sha256=profile.identity_sha256,
                preflight_dataset_inventory_sha256=(
                    profile.dataset_inventory_sha256
                ),
                preflight_experiment_scopes_sha256=(
                    profile.experiment_scopes_sha256
                ),
                preflight_scope_ids=(scope_id,),
                preflight_selected_ids_sha256=(selected_digest,),
                dataset_input_bindings=fixture_dataset_bindings((scope_id,)),
                bounded_selected_ids_sha256=(canonical_sha256(("q-001",)),),
                selected_query_counts=(1,),
                max_agent_operations=1,
                max_judge_operations=1,
                max_agent_cost_per_operation_usd=2,
                max_judge_cost_per_operation_usd=1,
            )
        self.assertEqual(authority.planned_agent_operations, 1)
        self.assertEqual(authority.planned_judge_operations, 1)

    def test_bounded_selection_and_manifest_root_are_identity_bound(self) -> None:
        scope_id = "bright.biology.main.full"
        bounded_digest = canonical_sha256(("q-001",))
        with tempfile.TemporaryDirectory() as temporary:
            authority = authorize_full_execution(
                profile=resolve_experiment_profile("paper-reference/pi"),
                scope_ids=(scope_id,),
                dataset_input_bindings=fixture_dataset_bindings((scope_id,)),
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
                        dataset_input_bindings=fixture_dataset_bindings(
                            ("bright.biology.main.full",)
                        ),
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
            binding = profiles._authorized_scope_dataset_input_binding(
                authority,
                scope,
            )
            consume_full_execution_authorization(authority, scope, binding)
            with self.assertRaises(ExperimentAuthorizationError):
                consume_full_execution_authorization(
                    authority,
                    scope,
                    binding,
                )

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
        consume_full_execution_authorization(
            authority,
            self.scope_id,
            profiles._authorized_scope_dataset_input_binding(
                authority,
                self.scope_id,
            ),
        )

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
                self.assertNotIn("dataset_input_bindings", receipt)
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

    def test_benchmark_request_preserves_legacy_sixth_positional_limit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = BenchmarkRequest(
                root / "dataset.jsonl",
                root / "output",
                root,
                JudgeConfig(base_url="https://judge.example.test/v1"),
                DciRuntimeOptions(provider=None, model=None),
                7,
            )
        self.assertEqual(request.limit, 7)
        self.assertIsNone(request.dataset_input_binding)

    def request(
        self,
        root: Path,
        authority: FullExecutionAuthorization,
    ) -> BenchmarkRequest:
        return BenchmarkRequest(
            dataset=root / "must-not-be-read.jsonl",
            dataset_input_binding=(
                profiles._authorized_scope_dataset_input_binding(
                    authority,
                    self.scope_id,
                )
            ),
            output_root=authorized_scope_output_root(authority, self.scope_id),
            cwd=root,
            judge_config=JudgeConfig(base_url="https://judge.example.test/v1"),
            runtime_options=DciRuntimeOptions(provider=None, model=None),
            profile="bright.biology",
            full_execution_authorization=authority,
            experiment_scope_id=self.scope_id,
        )

    def _bound_request(
        self,
        root: Path,
        *,
        scope_id: str,
        rows: tuple[dict[str, object], ...],
        mode: str,
        limit: int = 1,
    ) -> tuple[
        FullExecutionAuthorization,
        BenchmarkRequest,
        Path,
        bytes,
    ]:
        dataset = root / "dataset.jsonl"
        raw = b"".join(
            json.dumps(row, separators=(",", ":")).encode("utf-8") + b"\n"
            for row in rows
        )
        dataset.write_bytes(raw)
        binding = dataset_binding_for_path(dataset, scope_id)
        benchmark = resolve_paper_benchmark(
            resolve_paper_experiment_scope(scope_id).dataset_id
        )
        authority = authorize_full_execution(
            profile=resolve_experiment_profile("paper-reference/pi"),
            scope_ids=(scope_id,),
            dataset_input_bindings=(binding,),
            bounded_selected_ids_sha256=(
                canonical_sha256((cast(str, rows[0]["query_id"]),)),
            ),
            selected_query_counts=(1,),
            planned_agent_operations=1,
            planned_judge_operations=1 if benchmark.mode == "qa" else 0,
            output_root=root / "private",
            max_agent_operations=1,
            max_judge_operations=1,
            max_cost_usd=1,
            max_agent_cost_per_operation_usd=1,
            max_judge_cost_per_operation_usd=1,
            invocation_authorized=True,
        )
        request = BenchmarkRequest(
            dataset=dataset,
            dataset_input_binding=binding,
            output_root=authorized_scope_output_root(authority, scope_id),
            cwd=root,
            judge_config=JudgeConfig(
                base_url="https://judge.example.test/v1"
            ),
            runtime_options=DciRuntimeOptions(provider=None, model=None),
            limit=limit,
            mode=mode,
            profile="paper-reference/pi",
            analysis=False,
            figures=False,
            full_execution_authorization=authority,
            experiment_scope_id=scope_id,
            paper_ir_duplicate_handling=(
                "deduplicated" if mode == "ir" else None
            ),
        )
        return authority, request, dataset, raw

    def test_dataset_content_and_descriptor_drift_fail_before_agent(
        self,
    ) -> None:
        self.assertIn(
            "dataset_input_binding",
            BenchmarkRequest.__dataclass_fields__,
        )
        if "dataset_input_binding" not in BenchmarkRequest.__dataclass_fields__:
            return
        cases = {
            "same-ID query body": (
                "ir",
                (
                    {
                        "query_id": "q-001",
                        "query": "original query",
                        "gold_ids": ["doc-1"],
                    },
                    {
                        "query_id": "q-002",
                        "query": "unselected query",
                        "gold_ids": ["doc-2"],
                    },
                ),
                lambda rows: rows[0].__setitem__(
                    "query", "SENTINEL changed query"
                ),
            ),
            "QA answer": (
                "qa",
                (
                    {
                        "query_id": "q-001",
                        "query": "original query",
                        "answer": "original answer",
                    },
                ),
                lambda rows: rows[0].__setitem__(
                    "answer", "SENTINEL changed answer"
                ),
            ),
            "IR gold IDs": (
                "ir",
                (
                    {
                        "query_id": "q-001",
                        "query": "original query",
                        "gold_ids": ["doc-1"],
                    },
                ),
                lambda rows: rows[0].__setitem__(
                    "gold_ids", ["SENTINEL-doc"]
                ),
            ),
            "unselected row under limit one": (
                "ir",
                (
                    {
                        "query_id": "q-001",
                        "query": "selected query",
                        "gold_ids": ["doc-1"],
                    },
                    {
                        "query_id": "q-002",
                        "query": "unselected query",
                        "gold_ids": ["doc-2"],
                    },
                ),
                lambda rows: rows[1].__setitem__(
                    "query", "SENTINEL unselected mutation"
                ),
            ),
        }
        for label, (dataset_mode, source_rows, mutate) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                scope_id = (
                    "browsecomp-plus.main.all830"
                    if dataset_mode == "qa"
                    else self.scope_id
                )
                authority, request, dataset, _raw = self._bound_request(
                    root,
                    scope_id=scope_id,
                    rows=source_rows,
                    mode="qa",
                )
                changed_rows = [dict(row) for row in source_rows]
                mutate(changed_rows)
                dataset.write_bytes(
                    b"".join(
                        json.dumps(row, separators=(",", ":")).encode("utf-8")
                        + b"\n"
                        for row in changed_rows
                    )
                )
                with patch(
                    "asterion.dci.benchmark._paper_scope_for_rows",
                    return_value=scope_id,
                ), patch(
                    "asterion.dci.benchmark._run_pi_async"
                ) as agent, patch(
                    "asterion.dci.benchmark.reserve_full_execution_operation"
                ) as reserve:
                    with self.assertRaisesRegex(
                        DciBenchmarkError,
                        "^DCI benchmark authorization dataset changed$",
                    ) as raised:
                        run_benchmark(request, paths=resolve_dci_paths(root))
                agent.assert_not_called()
                reserve.assert_not_called()
                self.assertNotIn("SENTINEL", str(raised.exception))
                with self.assertRaisesRegex(
                    ExperimentAuthorizationError,
                    "^full execution authorization is inactive$",
                ):
                    reserve_full_execution_operation(
                        authority, scope_id, "agent"
                    )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            authority, request, dataset, raw = self._bound_request(
                root,
                scope_id=self.scope_id,
                rows=(
                    {
                        "query_id": "q-001",
                        "query": "same bytes",
                        "gold_ids": ["doc-1"],
                    },
                ),
                mode="qa",
            )
            original_inode = dataset.stat().st_ino
            replacement = root / "replacement.jsonl"
            replacement.write_bytes(raw)
            os.replace(replacement, dataset)
            self.assertNotEqual(dataset.stat().st_ino, original_inode)
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
                    "^DCI benchmark authorization dataset changed$",
                ):
                    run_benchmark(request, paths=resolve_dci_paths(root))
            agent.assert_not_called()
            reserve.assert_not_called()
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "^full execution authorization is inactive$",
            ):
                reserve_full_execution_operation(
                    authority, self.scope_id, "agent"
                )

    def test_missing_or_forged_request_binding_fails_before_input(
        self,
    ) -> None:
        self.assertIn(
            "dataset_input_binding",
            BenchmarkRequest.__dataclass_fields__,
        )
        if "dataset_input_binding" not in BenchmarkRequest.__dataclass_fields__:
            return
        for label in ("missing", "forged"):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                authority, request, _dataset, _raw = self._bound_request(
                    root,
                    scope_id=self.scope_id,
                    rows=(
                        {
                            "query_id": "q-001",
                            "query": "private query",
                            "gold_ids": ["doc-1"],
                        },
                    ),
                    mode="qa",
                )
                binding = request.dataset_input_binding
                self.assertIsNotNone(binding)
                changed = (
                    None
                    if label == "missing"
                    else replace(cast(DatasetInputBinding, binding), inode=999999)
                )
                with patch(
                    "asterion.dci.benchmark.read_paper_benchmark_dataset",
                    create=True,
                ) as read_dataset, patch(
                    "asterion.dci.benchmark._run_pi_async"
                ) as agent, patch(
                    "asterion.dci.benchmark.reserve_full_execution_operation"
                ) as reserve:
                    with self.assertRaisesRegex(
                        DciBenchmarkError,
                        "^DCI benchmark authorization dataset changed$",
                    ):
                        run_benchmark(
                            replace(
                                request,
                                dataset_input_binding=changed,
                            ),
                            paths=resolve_dci_paths(root),
                        )
                read_dataset.assert_not_called()
                agent.assert_not_called()
                reserve.assert_not_called()
                with self.assertRaisesRegex(
                    ExperimentAuthorizationError,
                    "^full execution authorization is inactive$",
                ):
                    reserve_full_execution_operation(
                        authority, self.scope_id, "agent"
                    )

    def test_hostile_request_binding_never_consumes_or_reserves(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            authority, request, _dataset, _raw = self._bound_request(
                root,
                scope_id=self.scope_id,
                rows=(
                    {
                        "query_id": "q-001",
                        "query": "private query",
                        "gold_ids": ["doc-1"],
                    },
                ),
                mode="ir",
            )
            self.assertIsNotNone(request.dataset_input_binding)
            object.__setattr__(
                cast(DatasetInputBinding, request.dataset_input_binding),
                "raw_content_sha256",
                AlwaysEqualStr("0" * 64),
            )
            with patch(
                "asterion.dci.benchmark._paper_scope_for_rows",
                return_value=self.scope_id,
            ), patch(
                "asterion.dci.benchmark.require_af320_executable_scope"
            ) as consume, patch(
                "asterion.dci.benchmark.reserve_full_execution_operation"
            ) as reserve, patch(
                "asterion.dci.benchmark._run_pi_async"
            ) as agent:
                with self.assertRaisesRegex(
                    DciBenchmarkError,
                    "^DCI benchmark authorization dataset changed$",
                ):
                    run_benchmark(
                        request,
                        paths=resolve_dci_paths(root),
                    )
            consume.assert_not_called()
            reserve.assert_not_called()
            agent.assert_not_called()
            with self.assertRaisesRegex(
                ExperimentAuthorizationError,
                "^full execution authorization is (?:invalid|inactive)$",
            ):
                reserve_full_execution_operation(
                    authority,
                    self.scope_id,
                    "agent",
                )

    def test_runner_dataset_io_errors_cancel_before_reservation(
        self,
    ) -> None:
        self.assertIn(
            "dataset_input_binding",
            BenchmarkRequest.__dataclass_fields__,
        )
        if "dataset_input_binding" not in BenchmarkRequest.__dataclass_fields__:
            return
        for failure in ("open", "read"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                authority, request, _dataset, _raw = self._bound_request(
                    root,
                    scope_id=self.scope_id,
                    rows=(
                        {
                            "query_id": "q-001",
                            "query": "private query",
                            "gold_ids": ["doc-1"],
                        },
                    ),
                    mode="qa",
                )
                target = (
                    "asterion.dci.paper_benchmarks._open_paper_dataset_descriptor"
                    if failure == "open"
                    else "asterion.dci.paper_benchmarks._read_paper_dataset_descriptor"
                )
                with patch(
                    target,
                    side_effect=OSError("SENTINEL private dataset race"),
                ), patch(
                    "asterion.dci.benchmark._run_pi_async"
                ) as agent, patch(
                    "asterion.dci.benchmark.reserve_full_execution_operation"
                ) as reserve:
                    with self.assertRaisesRegex(
                        DciBenchmarkError,
                        "^DCI benchmark dataset is unavailable$",
                    ) as raised:
                        run_benchmark(request, paths=resolve_dci_paths(root))
                agent.assert_not_called()
                reserve.assert_not_called()
                self.assertNotIn("SENTINEL", str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)
                rendered = "".join(
                    traceback.format_exception(raised.exception)
                )
                self.assertNotIn("SENTINEL", rendered)
                with self.assertRaisesRegex(
                    ExperimentAuthorizationError,
                    "^full execution authorization is inactive$",
                ):
                    reserve_full_execution_operation(
                        authority, self.scope_id, "agent"
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
                dataset_binding = dataset_binding_for_path(
                    dataset,
                    self.scope_id,
                )
                authority = authorize_full_execution(
                    profile=resolve_experiment_profile("paper-reference/pi"),
                    scope_ids=(self.scope_id,),
                    dataset_input_bindings=(dataset_binding,),
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
                request = replace(
                    self.request(root, authority),
                    dataset=dataset,
                    dataset_input_binding=dataset_binding,
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
            dataset_input_binding=(
                profiles._authorized_scope_dataset_input_binding(
                    authority,
                    self.scope_id,
                )
            ),
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

    def _preflight_result(
        self,
        request: BenchmarkRequest,
        scope_id: str,
        selected_ids: tuple[str, ...],
    ) -> tuple[tuple[str, ...], DatasetInputBinding]:
        return (
            selected_ids,
            dataset_binding_for_path(request.dataset, scope_id),
        )

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
                "asterion.dci.paper_benchmarks.read_paper_benchmark_dataset"
            ) as read_dataset, patch(
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
        read_dataset.assert_not_called()
        authorize.assert_not_called()

    def test_preflight_io_errors_are_redacted_before_authority_or_output(
        self,
    ) -> None:
        cases = (
            (
                "open",
                "asterion.dci.paper_benchmarks._open_paper_dataset_descriptor",
            ),
            (
                "read",
                "asterion.dci.paper_benchmarks._read_paper_dataset_descriptor",
            ),
            ("corpus", "asterion.dci.cli.os.scandir"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for label, target in cases:
                with self.subTest(label=label):
                    output_root = root / f"must-not-exist-{label}"
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with patch(
                        "asterion.dci.cli._load_batch_profiles",
                        return_value=self._fixture_batch_profiles(root),
                    ), patch(
                        target,
                        side_effect=OSError(
                            "SENTINEL /private/dataset body answer gold_ids"
                        ),
                    ) as failed_io, patch(
                        "asterion.dci.cli.validate_dci_run_request"
                    ), patch(
                        "asterion.dci.cli.validate_benchmark_metric_selection"
                    ), patch(
                        "asterion.dci.experiment_profiles.authorize_full_execution"
                    ) as authorize:
                        code = dci_main(
                            self._execute_argv(
                                output_root,
                                limit=1,
                            ),
                            repo_root=root,
                            stdout=stdout,
                            stderr=stderr,
                        )
                    self.assertEqual(code, 2)
                    failed_io.assert_called()
                    authorize.assert_not_called()
                    self.assertFalse(output_root.exists())
                    rendered = stdout.getvalue() + stderr.getvalue()
                    for forbidden in (
                        "SENTINEL",
                        "/private/dataset",
                        "body",
                        "answer",
                        "gold_ids",
                    ):
                        self.assertNotIn(forbidden, rendered)

    def test_preflight_translated_errors_have_no_sensitive_exception_chain(
        self,
    ) -> None:
        scope_id = "bright.biology.main.full"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            batch_profiles = self._fixture_batch_profiles(root)
            profile = batch_profiles["bright.biology"]
            request = BenchmarkRequest(
                dataset=root / cast(str, profile["dataset"]),
                output_root=root / "output",
                cwd=root,
                judge_config=JudgeConfig(
                    base_url="https://judge.example.test/v1"
                ),
                runtime_options=DciRuntimeOptions(
                    provider=None,
                    model=None,
                ),
                corpus=root / cast(str, profile["corpus"]),
                profile="bright.biology",
            )
            cases = (
                (
                    "open",
                    "asterion.dci.paper_benchmarks."
                    "_open_paper_dataset_descriptor",
                    lambda: cli_module._preflight_scope_selected_ids(
                        request,
                        scope_id,
                    ),
                ),
                (
                    "read",
                    "asterion.dci.paper_benchmarks."
                    "_read_paper_dataset_descriptor",
                    lambda: cli_module._preflight_scope_selected_ids(
                        request,
                        scope_id,
                    ),
                ),
                (
                    "corpus",
                    "asterion.dci.cli.os.scandir",
                    lambda: cli_module._preflight_benchmark_host_inputs(
                        request
                    ),
                ),
            )
            for label, target, invoke in cases:
                with self.subTest(label=label), patch(
                    target,
                    side_effect=OSError(
                        "SENTINEL /private/dataset answer gold_ids"
                    ),
                ):
                    with self.assertRaises(ValueError) as raised:
                        invoke()
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)
                rendered = "".join(
                    traceback.format_exception(raised.exception)
                )
                for forbidden in (
                    "SENTINEL",
                    "/private/dataset",
                    "answer",
                    "gold_ids",
                ):
                    self.assertNotIn(forbidden, rendered)

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
                    reproduction_output(item.scope_id, identity=index)
                    for index, item in enumerate(items, 1)
                ],
                "receipt": {
                    "schema": "dci.full-execution-authorization-receipt/v1",
                    "profile_id": authority.profile_id,
                },
            }

        def selected_ids_spy(
            request: BenchmarkRequest,
            scope: str,
        ) -> tuple[tuple[str, ...], DatasetInputBinding]:
            cast(list[str], captured.setdefault("order", [])).append(
                "selected-ids"
            )
            return self._preflight_result(request, scope, ("q1",))

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
        dataset_bindings = cast(
            tuple[DatasetInputBinding, ...],
            authorize_kwargs["dataset_input_bindings"],
        )
        self.assertEqual(len(dataset_bindings), 1)
        authority = cast(FullExecutionAuthorization, captured["authority"])
        self.assertEqual(
            authority.dataset_input_bindings[0],
            dataset_bindings[0],
        )
        self.assertIsNot(
            authority.dataset_input_bindings[0],
            dataset_bindings[0],
        )
        execute_kwargs = cast(dict[str, Any], captured["execute_kwargs"])
        self.assertIs(execute_kwargs["authority"], authority)
        self.assertIs(execute_kwargs["profile"], authorize_kwargs["profile"])
        self.assertEqual(execute_kwargs["scope_ids"], scopes)
        self.assertEqual(execute_kwargs["output_root"], output_root)
        items = tuple(execute_kwargs["execution_items"])
        self.assertEqual(tuple(item.scope_id for item in items), scopes)
        self.assertEqual(tuple(item.request.limit for item in items), (1,))
        self.assertIs(
            items[0].request.dataset_input_binding,
            dataset_bindings[0],
        )
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
                    reproduction_output(item.scope_id, identity=index)
                    for index, item in enumerate(kwargs["execution_items"], 1)
                ],
            }

        scopes = (
            "bright.biology.main.full",
            "browsecomp-plus.main.all830",
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
                side_effect=lambda request, scope: self._preflight_result(
                    request,
                    scope,
                    (
                        ("ir-prefix", "ir-later")
                        if scope == scopes[0]
                        else ("qa-prefix", "qa-later")
                    ),
                ),
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
                side_effect=lambda request, scope: self._preflight_result(
                    request,
                    scope,
                    ("q1",),
                ),
            ), patch(
                "asterion.dci.cli.validate_dci_run_request"
            ), patch(
                "asterion.dci.benchmark.execute_authorized_reproduction",
                return_value={
                    "schema": "dci.paper-reproduction-result/v1",
                    "operation_counts": {"agent": 3, "judge": 1, "total": 4},
                    "outputs": [reproduction_output(scopes[0])],
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

    def test_execution_result_prints_only_body_free_manifest_evidence(self) -> None:
        stdout = io.StringIO()
        scope_id = "bright.biology.main.full"
        artifact = hashlib.sha256(scope_id.encode()).hexdigest() + ".json"
        cli_module._write_reproduction_execution_result(
            stdout,
            {
                "operation_counts": {"agent": 3, "judge": 1, "total": 4},
                "outputs": [
                    {
                        "scope_id": scope_id,
                        "output_root_device": 123,
                        "output_root_inode": 456,
                        "manifest_artifact": artifact,
                        "manifest_identity_sha256": "a" * 64,
                    }
                ],
            },
        )

        rendered = stdout.getvalue()
        self.assertIn(f"manifest_scope={scope_id}\n", rendered)
        self.assertIn(f"manifest_artifact={artifact}\n", rendered)
        self.assertIn(f"manifest_identity_sha256={'a' * 64}\n", rendered)
        for sentinel in (
            "output_root_device",
            "output_root_inode",
            "/private/sentinel",
            "fixture-query-id",
            "SECRET prompt body",
        ):
            self.assertNotIn(sentinel, rendered)

    def test_execution_result_rejects_malformed_manifest_evidence(self) -> None:
        scope_id = "bright.biology.main.full"
        artifact = hashlib.sha256(scope_id.encode()).hexdigest() + ".json"
        valid_output = {
            "scope_id": scope_id,
            "output_root_device": 123,
            "output_root_inode": 456,
            "manifest_artifact": artifact,
            "manifest_identity_sha256": "a" * 64,
        }
        invalid_outputs = {
            "absolute artifact": {**valid_output, "manifest_artifact": "/tmp/a.json"},
            "separator artifact": {
                **valid_output,
                "manifest_artifact": "private/a.json",
            },
            "traversal artifact": {
                **valid_output,
                "manifest_artifact": "../a.json",
            },
            "malformed artifact": {
                **valid_output,
                "manifest_artifact": "A" * 64 + ".json",
            },
            "malformed digest": {
                **valid_output,
                "manifest_identity_sha256": "not-a-digest",
            },
            "extra private path": {
                **valid_output,
                "private_path": "/private/sentinel",
            },
            "extra query body": {
                **valid_output,
                "query": "fixture-query-id SECRET prompt body",
            },
        }
        for label, output in invalid_outputs.items():
            with self.subTest(label=label):
                stdout = io.StringIO()
                with self.assertRaises(ValueError):
                    cli_module._write_reproduction_execution_result(
                        stdout,
                        {
                            "operation_counts": {
                                "agent": 3,
                                "judge": 1,
                                "total": 4,
                            },
                            "outputs": [output],
                        },
                    )
                self.assertEqual(stdout.getvalue(), "")

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
                side_effect=lambda request, scope: self._preflight_result(
                    request,
                    scope,
                    ("q1",),
                ),
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
