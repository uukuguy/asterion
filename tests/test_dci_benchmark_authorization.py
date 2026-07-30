from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from asterion.applications.dci_agent_lite.benchmark_authorization import (
    DciBenchmarkAuthorizationError,
    DciBenchmarkExecutionAuthorizer,
)
from asterion.applications.dci_agent_lite.benchmark_instances import (
    select_benchmark_instance,
)
from asterion.benchmarks import ApplicationRef
from asterion.capability_packages import (
    BenchmarkSuiteRef,
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
)


LOCK = CapabilitySourceLock(
    entries=(
        CapabilitySourceLockEntry(
            package_ref=CapabilityPackageRef("dci", "1.0.0"),
            payload_sha256="a" * 64,
            source_id="dci.builtin",
        ),
    )
)


class DciBenchmarkAuthorizationTests(unittest.TestCase):
    def test_exact_claim_authorizes_once_and_is_body_free(self) -> None:
        instance = select_benchmark_instance("dci.local-fixture@1.0.0")
        authorizer = DciBenchmarkExecutionAuthorizer(instance)
        with tempfile.TemporaryDirectory() as temp:
            claim = authorizer.issue(
                case_limit=1,
                package_locks=(LOCK,),
                evidence_root=Path(temp).resolve(),
                resume_run_id=None,
            )

        run_id = authorizer.authorize_benchmark_execution(
            claim,
            application_ref=instance.application_ref,
            suite_ref=instance.suite_ref,
            case_limit=1,
        )

        self.assertTrue(run_id.startswith("run-"))
        self.assertEqual(repr(claim), "DciBenchmarkExecutionAuthorization()")
        with self.assertRaises(TypeError):
            json.dumps(claim)
        with self.assertRaises(DciBenchmarkAuthorizationError):
            authorizer.authorize_benchmark_execution(
                claim,
                application_ref=instance.application_ref,
                suite_ref=instance.suite_ref,
                case_limit=1,
            )

    def test_forged_or_mutated_claims_fail_before_provider_stage(self) -> None:
        instance = select_benchmark_instance("dci.local-fixture@1.0.0")
        authorizer = DciBenchmarkExecutionAuthorizer(instance)
        with tempfile.TemporaryDirectory() as temp:
            claim = authorizer.issue(
                case_limit=1,
                package_locks=(LOCK,),
                evidence_root=Path(temp).resolve(),
                resume_run_id=None,
            )
        mutations = (
            replace(claim, case_limit=2),
            replace(
                claim,
                application_ref=ApplicationRef(
                    "dci.complete-application",
                    "1.0.0",
                ),
            ),
            replace(
                claim,
                suite_ref=BenchmarkSuiteRef(
                    "dci.qa.bamboogle.github-sample50",
                    "1.0.0",
                ),
            ),
            replace(claim, package_locks=()),
            replace(claim, issuer_nonce=object()),
        )

        for mutated in mutations:
            with self.subTest(mutated=repr(mutated)):
                with self.assertRaises(
                    DciBenchmarkAuthorizationError
                ) as raised:
                    authorizer.authorize_benchmark_execution(
                        mutated,
                        application_ref=mutated.application_ref,
                        suite_ref=mutated.suite_ref,
                        case_limit=mutated.case_limit,
                    )
                self.assertEqual(
                    str(raised.exception),
                    "DCI benchmark authorization is invalid",
                )

    def test_resume_claim_reuses_only_the_exact_run_id(self) -> None:
        instance = select_benchmark_instance("dci.local-fixture@1.0.0")
        authorizer = DciBenchmarkExecutionAuthorizer(instance)
        with tempfile.TemporaryDirectory() as temp:
            claim = authorizer.issue(
                case_limit=1,
                package_locks=(LOCK,),
                evidence_root=Path(temp).resolve(),
                resume_run_id="run-existing",
            )

        self.assertEqual(
            authorizer.authorize_benchmark_execution(
                claim,
                application_ref=instance.application_ref,
                suite_ref=instance.suite_ref,
                case_limit=1,
            ),
            "run-existing",
        )


if __name__ == "__main__":
    unittest.main()
