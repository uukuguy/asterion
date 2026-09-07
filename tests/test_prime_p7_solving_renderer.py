from __future__ import annotations

import unittest


class _Sink:
    def __init__(self) -> None:
        self.records: list[str] = []

    def write(self, text: str) -> None:
        self.records.append(text)


class _FailingBroker:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def start(self) -> bytes:
        return b"client"

    def seal(self) -> dict[str, object]:
        raise AssertionError("unreachable")

    def replay(self) -> dict[str, object]:
        raise AssertionError("unreachable")

    def presentation(self) -> dict[str, object]:
        raise AssertionError("unreachable")

    def close(self) -> None:
        self.calls.append("broker")
        raise RuntimeError("PRIVATE-BROKER")


class _FailingWorker:
    async def acquire(self, client: bytes) -> None:
        del client

    async def execute_cell(self, code: str) -> dict[str, object]:
        raise AssertionError(code)

    async def cleanup(self) -> None:
        _CLEANUPS.append("worker")
        raise RuntimeError("PRIVATE-WORKER")


class _FailingProvider:
    async def __call__(self, body: bytes) -> bytes:
        return body

    def finalize(self) -> object:
        raise AssertionError("unreachable")

    def callback_counts(self) -> dict[str, int]:
        raise AssertionError("unreachable")

    async def close(self) -> None:
        _CLEANUPS.append("provider")
        raise RuntimeError("PRIVATE-PROVIDER")


class _FailingGateway:
    def __init__(self, original: BaseException) -> None:
        self.original = original

    def bind(self, **_: object) -> None:
        return None

    async def open(self, **_: object) -> None:
        return None

    async def prompt(self, prompt: str) -> object:
        del prompt
        raise self.original

    def terminal_witness(self) -> object:
        raise AssertionError("unreachable")

    async def close(self) -> None:
        _CLEANUPS.append("gateway")
        raise RuntimeError("PRIVATE-GATEWAY")


_CLEANUPS: list[str] = []


class TestPrimeP7SolvingRenderer(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_preserves_original_and_renderer_receipt_are_redacted(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_host import (
            P7SolvingReceiptStore,
            PrimeP7SolvingHostError,
            run_p7_solving_lifecycle,
        )
        from asterion.applications.prime_agent.operator.p7_solving_renderer import (
            P7SolvingPresentation,
            P7SolvingRendererError,
            render_p7_solving_presentation,
        )
        from asterion.capabilities.prime_arc_agi_3_solver.host import (
            PrimeArcAgi3SolveReceipt,
            canonical_solve_receipt_sha256,
        )

        original = PrimeP7SolvingHostError()
        _CLEANUPS.clear()
        with self.assertRaises(PrimeP7SolvingHostError) as caught:
            await run_p7_solving_lifecycle(
                gateway=_FailingGateway(original), provider=_FailingProvider(),
                worker=_FailingWorker(), broker=_FailingBroker(_CLEANUPS),
                receipt_store=P7SolvingReceiptStore(), run_id="p7-cleanup",
                session_id="session-p7-cleanup",
            )
        self.assertIs(caught.exception, original)
        self.assertEqual(_CLEANUPS, ["gateway", "provider", "worker", "broker"])
        self.assertNotIn("PRIVATE-", str(caught.exception))

        value = P7SolvingPresentation(
            question="First public level", initial_grid=(((0, 1), (2, 3)),),
            completion_grid=(((3, 2), (1, 0)),),
            applied_actions=("ACTION1", "ACTION6 x=2 y=3"), action_count=2,
            model_callback_count=5, tool_callback_count=2, levels_completed=1,
            terminal_reason="level-completed", partial_game_score="3.571429",
        )
        sink = _Sink()
        render_p7_solving_presentation(value, sink)
        rendered = "\n".join(sink.records)
        for label in ("Question", "Action answer", "Solved level", "Partial score"):
            self.assertIn(label, rendered)
        self.assertNotIn("/", rendered)

        invalid = []
        for field, replacement in (
            ("initial_grid", (((0, 1), (2,)),)),
            ("completion_grid", (((256,),),)),
            ("initial_grid", (tuple((0,) for _ in range(65)),)),
            ("applied_actions", ("/private/answer",)),
        ):
            forged = object.__new__(P7SolvingPresentation)
            for name, current in vars(value).items():
                object.__setattr__(forged, name, replacement if name == field else current)
            invalid.append(forged)
        extra = object.__new__(P7SolvingPresentation)
        for name, current in vars(value).items():
            object.__setattr__(extra, name, current)
        object.__setattr__(extra, "private_path", "/private/SENTINEL")
        invalid.append(extra)
        for forged in invalid:
            with self.subTest(forged=repr(forged)), self.assertRaises(P7SolvingRendererError):
                render_p7_solving_presentation(forged, _Sink())

        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id="p7-cleanup", completed_level_count=1,
            primitive_action_count=2, partial_game_score="3.571429",
        )
        unsigned = {name: value for name, value in vars(receipt).items() if name != "receipt_sha256"}
        self.assertEqual(receipt.receipt_sha256, canonical_solve_receipt_sha256(unsigned))
        object.__setattr__(receipt, "private_answer", "PRIVATE-RECEIPT-SENTINEL")
        self.assertNotIn("PRIVATE-RECEIPT-SENTINEL", repr(receipt))


if __name__ == "__main__":
    unittest.main()
