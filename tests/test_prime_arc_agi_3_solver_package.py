"""Public-safe contract tests for the independent P7 solver package."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from hashlib import sha256
from typing import AsyncIterator, cast
import unittest

from asterion.applications.prime.p7.prompt import P7_SOLVE_PROMPT
from asterion.capabilities.prime_arc_agi_3_solver import provider as solver_provider
from asterion.capabilities.execution import CapabilityInvocation
from asterion.capabilities.prime_arc_agi_3_solver.provider import (
    CAPABILITY_REF,
    PrimeArcAgi3SolvingImplementation,
)
from asterion.capabilities.prime_arc_agi_3_solver.host import (
    PrimeArcAgi3SolveReceipt,
    PrimeArcAgi3SolveReceiptError,
    canonical_solve_receipt_sha256,
    validate_prime_arc_agi_3_solve_receipt,
)
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest


class _NativeRuntime:
    def __init__(self, receipt: PrimeArcAgi3SolveReceipt) -> None:
        self.receipt = receipt
        self.requests: list[RunRequest] = []

    @property
    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest("asterion.prime", ("prime.tool.ipython",))

    async def run(
        self, request: RunRequest, *, signal: object = None
    ) -> AsyncIterator[RunEvent]:
        del signal
        self.requests.append(request)
        yield RunEvent(
            request.run_id,
            1,
            "run.started",
            {"capabilities": ["prime.tool.ipython"]},
        )
        yield RunEvent(
            request.run_id,
            2,
            "artifact.created",
            {
                "artifact": {
                    "artifact_id": "prime.p7-solving.receipt",
                    "kind": "p7-solving",
                    "media_type": (
                        "application/vnd.asterion.prime.p7-solving-receipt+json"
                    ),
                    "sha256": self.receipt.receipt_sha256.removeprefix("sha256:"),
                }
            },
        )
        yield RunEvent(request.run_id, 3, "run.completed", {"status": "completed"})


class _ReceiptAccessor:
    def __init__(self, receipt: PrimeArcAgi3SolveReceipt) -> None:
        self.receipt = receipt

    def get_receipt(
        self, *, run_id: str, receipt_sha256: str
    ) -> PrimeArcAgi3SolveReceipt:
        del run_id, receipt_sha256
        return self.receipt


class TestPrimeArcAgi3SolveReceipt(unittest.TestCase):
    def test_only_the_application_owned_p7_prompt_is_admitted(self) -> None:
        domain = b"asterion.prime-p7-solve-prompt/v1\0"
        self.assertEqual(
            solver_provider.P7_SOLVE_PROMPT_SHA256,
            sha256(domain + P7_SOLVE_PROMPT.encode("utf-8")).hexdigest(),
        )
        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id="native-reject",
            completed_level_count=1,
            primitive_action_count=2,
            partial_game_score="1.000000",
        )
        for rejected in (
            "solve this arbitrary puzzle",
            "solve-first-public-level",
            "Use ACTION1 for seeded game ls20-9607627b",
        ):
            with self.subTest(rejected=rejected):
                runtime = _NativeRuntime(receipt)
                invocation = CapabilityInvocation(
                    capability_ref=CAPABILITY_REF,
                    manifest={
                        "kind": "capability",
                        "capability_id": CAPABILITY_REF.capability_id,
                        "version": CAPABILITY_REF.version,
                    },
                    run_id=receipt.run_id,
                    input_text=rejected,
                    upstream_artifacts=(),
                    runtime=runtime,
                    host_services={"prime.private-trace": _ReceiptAccessor(receipt)},
                )

                with self.assertRaisesRegex(
                    Exception, "Prime solver runtime is unavailable"
                ):
                    asyncio.run(PrimeArcAgi3SolvingImplementation().execute(invocation))
                self.assertEqual(runtime.requests, [])

    def test_native_implementation_requires_and_forwards_the_solve_prompt(self) -> None:
        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id="native-solve",
            completed_level_count=1,
            primitive_action_count=2,
            partial_game_score="1.000000",
        )
        runtime = _NativeRuntime(receipt)
        invocation = CapabilityInvocation(
            capability_ref=CAPABILITY_REF,
            manifest={
                "kind": "capability",
                "capability_id": CAPABILITY_REF.capability_id,
                "version": CAPABILITY_REF.version,
            },
            run_id=receipt.run_id,
            input_text=P7_SOLVE_PROMPT,
            upstream_artifacts=(),
            runtime=runtime,
            host_services={"prime.private-trace": _ReceiptAccessor(receipt)},
        )

        result = asyncio.run(PrimeArcAgi3SolvingImplementation().execute(invocation))

        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(runtime.requests[0].input_text, P7_SOLVE_PROMPT)
        self.assertEqual(
            runtime.requests[0].requested_capabilities,
            ("prime.tool.ipython",),
        )

    def test_create_seals_the_exact_canonical_unsigned_receipt(self) -> None:
        unsigned = {
            "run_id": "prime-p7-solve-route",
            "scope": "p7-solving",
            "promotion": "unpromoted",
            "completed_level_count": 1,
            "primitive_action_count": 22,
            "partial_game_score": "3.571429",
        }

        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id=unsigned["run_id"],
            completed_level_count=unsigned["completed_level_count"],
            primitive_action_count=unsigned["primitive_action_count"],
            partial_game_score=unsigned["partial_game_score"],
        )

        self.assertEqual(receipt.scope, "p7-solving")
        self.assertEqual(receipt.promotion, "unpromoted")
        self.assertEqual(
            receipt.receipt_sha256, canonical_solve_receipt_sha256(unsigned)
        )
        with self.assertRaises(FrozenInstanceError):
            receipt.primitive_action_count = 23  # type: ignore[misc]

    def test_rejects_malformed_or_tampered_receipts_at_retrieval_boundary(self) -> None:
        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id="prime-p7-solve-route",
            completed_level_count=1,
            primitive_action_count=22,
            partial_game_score="3.571429",
        )
        for changes in (
            {"receipt_sha256": "sha256:" + "0" * 64},
            {"run_id": "other-run"},
            {"scope": "other"},
            {"promotion": "promoted"},
            {"completed_level_count": 0},
            {"primitive_action_count": 23},
            {"partial_game_score": "3.571430"},
        ):
            with self.subTest(changes=changes):
                forged = object.__new__(PrimeArcAgi3SolveReceipt)
                for name, value in vars(receipt).items():
                    object.__setattr__(forged, name, changes.get(name, value))
                with self.assertRaises(PrimeArcAgi3SolveReceiptError):
                    validate_prime_arc_agi_3_solve_receipt(forged)

    def test_rejects_extra_fields_and_noncanonical_scores(self) -> None:
        cases = (
            {"partial_game_score": "3.57142"},
            {"partial_game_score": "03.571429"},
            {"partial_game_score": "3.5714290"},
            {"primitive_action_count": -1},
        )
        for values in cases:
            with (
                self.subTest(values=values),
                self.assertRaises(PrimeArcAgi3SolveReceiptError),
            ):
                PrimeArcAgi3SolveReceipt.create(
                    run_id="prime-p7-solve-route",
                    completed_level_count=1,
                    primitive_action_count=cast(
                        int, values.get("primitive_action_count", 22)
                    ),
                    partial_game_score=cast(
                        str, values.get("partial_game_score", "3.571429")
                    ),
                )
        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id="prime-p7-solve-route",
            completed_level_count=1,
            primitive_action_count=22,
            partial_game_score="3.571429",
        )
        object.__setattr__(receipt, "private_answer", "SENTINEL")
        with self.assertRaises(PrimeArcAgi3SolveReceiptError):
            validate_prime_arc_agi_3_solve_receipt(receipt)


if __name__ == "__main__":
    unittest.main()
