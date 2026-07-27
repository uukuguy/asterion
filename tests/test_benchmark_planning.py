"""Tests for pure, bounded, deterministic benchmark planning."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from inspect import signature
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from asterion.benchmarks.model import ApplicationRef, ResolvedCapability
from asterion.benchmarks.planning import (
    BenchmarkPlanningError,
    BenchmarkPlanRequest,
    ResolvedApplicationMetadata,
    create_benchmark_plan,
    render_benchmark_plan,
)
from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages import (
    BenchmarkSuiteRef,
    CapabilityPackageManifest,
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
    PortableCapabilityPayload,
)


_FIXTURE = Path(__file__).parent / "fixtures/benchmarks/valid-suite.json"
_APPLICATION_REF = ApplicationRef("example.application", "1.0.0")
_SUITE_REF = BenchmarkSuiteRef("example.synthetic-suite", "1.0.0")
_OWNER_REF = CapabilityPackageRef("example.benchmark-package", "1.0.0")
_SUPPORT_REF = CapabilityPackageRef("example.support-package", "1.0.0")
_CAPABILITY_A = CapabilityRef("example.capability-a", "1.0.0")
_CAPABILITY_B = CapabilityRef("example.capability-b", "1.0.0")
_SUPPORT_CAPABILITY = CapabilityRef("example.support-capability", "1.0.0")
_RUN_UUID = UUID("12345678-1234-5678-1234-567812345678")


class BenchmarkPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _payload(
        self,
        root: Path,
        *,
        package_ref: CapabilityPackageRef = _OWNER_REF,
        digest_character: str = "a",
    ) -> PortableCapabilityPayload:
        if package_ref == _OWNER_REF:
            suite_root = root / "benchmark-suites"
            suite_root.mkdir(parents=True)
            shutil.copyfile(_FIXTURE, suite_root / "suite.json")
            capabilities = (_CAPABILITY_A, _CAPABILITY_B)
            suites = (_SUITE_REF,)
        else:
            root.mkdir(parents=True)
            capabilities = (_SUPPORT_CAPABILITY,)
            suites = ()
        return PortableCapabilityPayload(
            manifest=CapabilityPackageManifest(
                package_ref=package_ref,
                capabilities=capabilities,
                benchmark_suites=suites,
                resources=(),
            ),
            payload_sha256=digest_character * 64,
            resource_root=root,
        )

    def _lock(
        self,
        package_ref: CapabilityPackageRef,
        source_id: str,
        digest_character: str,
    ) -> CapabilitySourceLock:
        return CapabilitySourceLock(
            entries=(
                CapabilitySourceLockEntry(
                    package_ref=package_ref,
                    payload_sha256=digest_character * 64,
                    source_id=source_id,
                ),
            )
        )

    def _application(
        self,
        capability_root: Path,
        *,
        locks: tuple[CapabilitySourceLock, ...] | None = None,
    ) -> ResolvedApplicationMetadata:
        capabilities = (
            ResolvedCapability(
                ref=_CAPABILITY_B,
                source=capability_root / "private-b.json",
                manifest={
                    "capability_id": _CAPABILITY_B.capability_id,
                    "version": _CAPABILITY_B.version,
                },
            ),
            ResolvedCapability(
                ref=_CAPABILITY_A,
                source=capability_root / "private-a.json",
                manifest={
                    "capability_id": _CAPABILITY_A.capability_id,
                    "version": _CAPABILITY_A.version,
                },
            ),
        )
        return ResolvedApplicationMetadata(
            application_ref=_APPLICATION_REF,
            capabilities=capabilities,
            package_locks=(
                (
                    self._lock(
                        _SUPPORT_REF,
                        "example.support-source",
                        "b",
                    ),
                    self._lock(
                        _OWNER_REF,
                        "example.benchmark-source",
                        "a",
                    ),
                )
                if locks is None
                else locks
            ),
        )

    def _request(self, case_limit: int | None = None) -> BenchmarkPlanRequest:
        return BenchmarkPlanRequest(
            application_ref=_APPLICATION_REF,
            suite_ref=_SUITE_REF,
            case_limit=case_limit,
        )

    def _payloads(
        self,
        root: Path,
    ) -> tuple[PortableCapabilityPayload, PortableCapabilityPayload]:
        return (
            self._payload(
                root / "support",
                package_ref=_SUPPORT_REF,
                digest_character="b",
            ),
            self._payload(root / "owner"),
        )

    def test_omitted_limit_uses_finite_suite_default_and_copies_exact_locks(
        self,
    ) -> None:
        application = self._application(self.root / "private-capabilities")

        with patch(
            "asterion.benchmarks.planning.uuid4",
            return_value=_RUN_UUID,
        ) as new_uuid:
            plan = create_benchmark_plan(
                self._request(),
                application,
                self._payloads(self.root / "payloads"),
            )

        self.assertEqual(plan.case_limit, 8)
        self.assertEqual(plan.run_id, f"benchmark-{_RUN_UUID.hex}")
        self.assertEqual(
            tuple(task.task.task_id for task in plan.tasks),
            ("example.task-a", "example.task-b"),
        )
        self.assertEqual(
            {
                entry.package_ref: (
                    entry.payload_sha256,
                    entry.source_id,
                )
                for lock in plan.package_locks
                for entry in lock.entries
            },
            {
                _OWNER_REF: (
                    "a" * 64,
                    "example.benchmark-source",
                ),
                _SUPPORT_REF: (
                    "b" * 64,
                    "example.support-source",
                ),
            },
        )
        new_uuid.assert_called_once_with()

    def test_rejects_nonpositive_boolean_and_above_suite_limits(self) -> None:
        application = self._application(self.root / "private-capabilities")
        payloads = self._payloads(self.root / "payloads")

        for value in (0, -1, False, 9):
            with (
                self.subTest(case_limit=value),
                patch(
                    "asterion.benchmarks.planning.uuid4",
                    side_effect=AssertionError(
                        "run identity allocated for invalid plan"
                    ),
                ) as new_uuid,
                self.assertRaisesRegex(
                    BenchmarkPlanningError,
                    "^benchmark case limit is invalid$",
                ),
            ):
                create_benchmark_plan(
                    self._request(value),
                    application,
                    payloads,
                )
            new_uuid.assert_not_called()

    def test_rendering_is_byte_stable_across_enumeration_and_locations(
        self,
    ) -> None:
        left_application = self._application(
            self.root / "first/private/capabilities",
        )
        right_application = self._application(
            self.root / "second/other/private/capabilities",
            locks=tuple(reversed(left_application.package_locks)),
        )
        left_payloads = self._payloads(self.root / "first/payloads")
        right_payloads = tuple(
            reversed(self._payloads(self.root / "second/payloads"))
        )

        with patch(
            "asterion.benchmarks.planning.uuid4",
            return_value=_RUN_UUID,
        ):
            left = create_benchmark_plan(
                self._request(3),
                left_application,
                left_payloads,
            )
            right = create_benchmark_plan(
                self._request(3),
                right_application,
                right_payloads,
            )

        left_rendered = render_benchmark_plan(left)
        right_rendered = render_benchmark_plan(right)
        self.assertEqual(
            left_rendered.encode("utf-8"),
            right_rendered.encode("utf-8"),
        )
        self.assertEqual(
            left_rendered,
            (
                '{"application":"example.application@1.0.0","case_limit":3,'
                '"run_id":"benchmark-12345678123456781234567812345678",'
                '"suite":"example.synthetic-suite@1.0.0","tasks":['
                '{"binding_id":"example.binding-a",'
                '"capability":"example.capability-a@1.0.0","ordinal":1,'
                '"task_id":"example.task-a"},'
                '{"binding_id":"example.binding-b",'
                '"capability":"example.capability-b@1.0.0","ordinal":2,'
                '"task_id":"example.task-b"}]}\n'
            ),
        )
        for private_path in (
            left_application.capabilities[0].source,
            right_application.capabilities[0].source,
            left_payloads[0].resource_root,
            right_payloads[0].resource_root,
        ):
            self.assertNotIn(str(private_path), left_rendered)

    def test_planning_creates_no_directory_or_accepts_implementation_authority(
        self,
    ) -> None:
        application = self._application(self.root / "private-capabilities")
        payloads = self._payloads(self.root / "payloads")

        with (
            patch.object(
                Path,
                "mkdir",
                side_effect=AssertionError(
                    "output directory created during planning"
                ),
            ) as mkdir_spy,
            patch(
                "asterion.benchmarks.planning.uuid4",
                return_value=_RUN_UUID,
            ),
        ):
            plan = create_benchmark_plan(
                self._request(2),
                application,
                payloads,
            )

        self.assertEqual(plan.case_limit, 2)
        mkdir_spy.assert_not_called()
        self.assertEqual(
            tuple(signature(create_benchmark_plan).parameters),
            ("request", "application", "payloads"),
        )

    def test_planning_rejects_nonexact_application_or_package_locks(
        self,
    ) -> None:
        payloads = self._payloads(self.root / "payloads")
        valid = self._application(self.root / "private-capabilities")
        wrong_digest = self._application(
            self.root / "private-capabilities",
            locks=(
                self._lock(
                    _OWNER_REF,
                    "example.benchmark-source",
                    "c",
                ),
                self._lock(
                    _SUPPORT_REF,
                    "example.support-source",
                    "b",
                ),
            ),
        )
        missing_support = self._application(
            self.root / "private-capabilities",
            locks=(
                self._lock(
                    _OWNER_REF,
                    "example.benchmark-source",
                    "a",
                ),
            ),
        )
        cases = {
            "application identity mismatch": (
                BenchmarkPlanRequest(
                    application_ref=ApplicationRef(
                        "example.other-application",
                        "1.0.0",
                    ),
                    suite_ref=_SUITE_REF,
                    case_limit=2,
                ),
                valid,
            ),
            "payload digest mismatch": (self._request(2), wrong_digest),
            "missing exact package lock": (self._request(2), missing_support),
        }

        for name, (request, application) in cases.items():
            with (
                self.subTest(name=name),
                patch(
                    "asterion.benchmarks.planning.uuid4",
                    side_effect=AssertionError(
                        "run identity allocated for invalid plan"
                    ),
                ) as new_uuid,
                self.assertRaises(BenchmarkPlanningError),
            ):
                create_benchmark_plan(request, application, payloads)
            new_uuid.assert_not_called()


if __name__ == "__main__":
    unittest.main()
