"""prime-*-native packages cite a Prime receipt and do not execute Prime."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
import unittest

from asterion.agents.prime.application import prepare_prime_application
from asterion.capabilities.execution import (
    CapabilityExecutionError,
    CapabilityInvocation,
)
from asterion.capabilities.prime_bounded_autonomy_native.provider import (
    CAPABILITY_REF as P5_CAPABILITY,
    P5_ARTIFACT_ID,
    P5_RECEIPT_MEDIA_TYPE,
    create_prime_bounded_autonomy_native_package,
)
from asterion.capabilities.prime_continual_improvement_native.provider import (
    CAPABILITY_REF as P6_CAPABILITY,
    P6_ARTIFACT_ID,
    P6_RECEIPT_MEDIA_TYPE,
    create_prime_continual_improvement_native_package,
)
from asterion.capabilities.prime_ipython_coding_native.provider import (
    CAPABILITY_REF as P1_CAPABILITY,
    P1_ARTIFACT_ID,
    P1_RECEIPT_MEDIA_TYPE,
    create_prime_ipython_coding_native_package,
)
from asterion.capabilities.prime_long_session_continuity_native.provider import (
    CAPABILITY_REF as P4_CAPABILITY,
    P4_ARTIFACT_ID,
    P4_RECEIPT_MEDIA_TYPE,
    create_prime_long_session_continuity_native_package,
)
from asterion.capabilities.prime_programmatic_long_context_native.provider import (
    CAPABILITY_REF as P2_CAPABILITY,
    P2_ARTIFACT_ID,
    P2_RECEIPT_MEDIA_TYPE,
    create_prime_programmatic_long_context_native_package,
)
from asterion.capabilities.prime_recursive_workflow_native.provider import (
    CAPABILITY_REF as P3_CAPABILITY,
    P3_ARTIFACT_ID,
    P3_RECEIPT_MEDIA_TYPE,
    create_prime_recursive_workflow_native_package,
)


SOURCE = Path(__file__).resolve().parents[1] / "src" / "asterion" / "capabilities"
PACKAGE_SOURCES = (
    "prime_native_receipt.py",
    "prime_ipython_coding_native/provider.py",
    "prime_programmatic_long_context_native/provider.py",
    "prime_recursive_workflow_native/provider.py",
    "prime_long_session_continuity_native/provider.py",
    "prime_bounded_autonomy_native/provider.py",
    "prime_continual_improvement_native/provider.py",
)
CASES = (
    (
        create_prime_ipython_coding_native_package,
        P1_CAPABILITY,
        P1_ARTIFACT_ID,
        P1_RECEIPT_MEDIA_TYPE,
        "p1-cite",
    ),
    (
        create_prime_programmatic_long_context_native_package,
        P2_CAPABILITY,
        P2_ARTIFACT_ID,
        P2_RECEIPT_MEDIA_TYPE,
        "p2-cite",
    ),
    (
        create_prime_recursive_workflow_native_package,
        P3_CAPABILITY,
        P3_ARTIFACT_ID,
        P3_RECEIPT_MEDIA_TYPE,
        "p3-cite",
    ),
    (
        create_prime_long_session_continuity_native_package,
        P4_CAPABILITY,
        P4_ARTIFACT_ID,
        P4_RECEIPT_MEDIA_TYPE,
        "p4-cite",
    ),
    (
        create_prime_bounded_autonomy_native_package,
        P5_CAPABILITY,
        P5_ARTIFACT_ID,
        P5_RECEIPT_MEDIA_TYPE,
        "p5-cite",
    ),
    (
        create_prime_continual_improvement_native_package,
        P6_CAPABILITY,
        P6_ARTIFACT_ID,
        P6_RECEIPT_MEDIA_TYPE,
        "p6-cite",
    ),
)


class _Runtime:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, request, signal=None):
        del request, signal
        self.calls += 1
        raise AssertionError("citation package executed Prime")
        yield


def _citation(media_type: str, run_id: str, digest: str) -> str:
    return json.dumps(
        {"media_type": media_type, "run_id": run_id, "sha256": digest},
        sort_keys=True,
        separators=(",", ":"),
    )


class PrimeNativeCitationTests(unittest.TestCase):
    def test_packages_record_media_type_digest_and_run_identity(self) -> None:
        digest = "ab" * 32
        for factory, capability, artifact_id, media_type, run_id in CASES:
            with self.subTest(run_id=run_id):
                package = factory()
                implementation = package.implementations[0].implementation
                runtime = _Runtime()
                result = asyncio.run(
                    implementation.execute(
                        CapabilityInvocation(
                            capability_ref=capability,
                            manifest={},
                            run_id=run_id,
                            input_text=_citation(media_type, run_id, digest),
                            upstream_artifacts=(),
                            runtime=runtime,
                            host_services={},
                        )
                    )
                )
                self.assertEqual(runtime.calls, 0)
                self.assertEqual(len(result.artifacts), 1)
                artifact = result.artifacts[0]
                self.assertEqual(artifact["artifact_id"], artifact_id)
                self.assertEqual(artifact["media_type"], media_type)
                self.assertEqual(
                    artifact["value"],
                    {
                        "media_type": media_type,
                        "run_id": run_id,
                        "sha256": digest,
                    },
                )

                with self.assertRaises(CapabilityExecutionError):
                    asyncio.run(
                        implementation.execute(
                            CapabilityInvocation(
                                capability_ref=capability,
                                manifest={},
                                run_id=run_id,
                                input_text="fixed-small-verification",
                                upstream_artifacts=(),
                                runtime=runtime,
                                host_services={},
                            )
                        )
                    )
                self.assertEqual(runtime.calls, 0)

    def test_packages_do_not_contain_a_prime_implementation(self) -> None:
        self.assertTrue(callable(prepare_prime_application))
        offenders: list[str] = []
        for relative in PACKAGE_SOURCES:
            path = SOURCE / relative
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "run":
                    offenders.append(f"{relative} calls run")
                if isinstance(node, ast.Name) and node.id == "prepare_prime_application":
                    offenders.append(f"{relative} names prepare_prime_application")
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith(
                        (
                            "asterion.agents.prime.application",
                            "asterion.runtimes",
                        )
                    ):
                        offenders.append(f"{relative} imports {node.module}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
