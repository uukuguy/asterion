from __future__ import annotations

import asyncio
import contextlib
import io
import os
from pathlib import Path
import tempfile
from types import MappingProxyType
from typing import TYPE_CHECKING
import unittest
from unittest.mock import patch

from asterion.runtime.host import CancellationSignal
from asterion.runtimes.pi_extensions import PiExtensionBinding

if TYPE_CHECKING:
    from asterion.applications.prime.p7.ipython_host import IpythonWorkerResult


class _Signal(CancellationSignal):
    def __init__(self, cancelled: bool = False) -> None:
        self.value = cancelled

    @property
    def cancelled(self) -> bool:
        return self.value


class _Client:
    def observe(self) -> dict[str, object]:
        return {"observation": [[1, 2], [3, 4]]}

    def status(self) -> dict[str, object]:
        return {"levels_completed": 0}

    def act(self, actions: list[dict[str, object]]) -> dict[str, object]:
        return {"actions": len(actions)}


class _MemoryWorker:
    def __init__(self) -> None:
        self.namespace: dict[str, object] | None = None
        self.started = 0
        self.closed = 0

    async def start(self, p7_client: object, *, signal: CancellationSignal) -> None:
        from asterion.applications.prime.p7.ipython_host import P7ClientFacade

        if type(p7_client) is not P7ClientFacade:
            raise ValueError("unexpected client")
        self.started += 1
        module = p7_client
        allowed_builtins = MappingProxyType(
            {
                "__import__": lambda name, *_args, **_kwargs: (
                    module
                    if name == "p7_client"
                    else (_ for _ in ()).throw(ImportError("module unavailable"))
                ),
                "len": len,
                "print": print,
                "range": range,
            }
        )
        self.namespace = {"__builtins__": allowed_builtins, "p7_client": module}

    async def execute_cell(
        self, code: str, *, signal: CancellationSignal
    ) -> IpythonWorkerResult:
        from asterion.applications.prime.p7.ipython_host import IpythonWorkerResult

        if self.namespace is None:
            raise RuntimeError("not started")
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                exec(compile(code, "<ipython-cell>", "exec"), self.namespace)
        except BaseException:
            return IpythonWorkerResult("error", "SENTINEL-RAW-TRACE")
        return IpythonWorkerResult("ok", output.getvalue())

    async def close(self) -> None:
        self.closed += 1


class _LostWorker(_MemoryWorker):
    async def execute_cell(
        self, code: str, *, signal: CancellationSignal
    ) -> IpythonWorkerResult:
        raise RuntimeError("SENTINEL-WORKER /private/path")


class _ResultWorker(_MemoryWorker):
    def __init__(self, status: str, output: str) -> None:
        super().__init__()
        self.status = status
        self.output = output

    async def execute_cell(
        self, code: str, *, signal: CancellationSignal
    ) -> IpythonWorkerResult:
        from asterion.applications.prime.p7.ipython_host import IpythonWorkerResult

        return IpythonWorkerResult(self.status, self.output)  # type: ignore[arg-type]


class _CancellingWorker(_MemoryWorker):
    async def execute_cell(
        self, code: str, *, signal: CancellationSignal
    ) -> IpythonWorkerResult:
        raise asyncio.CancelledError("SENTINEL-CANCEL /private/path")


class _BlockingWorker(_MemoryWorker):
    async def execute_cell(
        self, code: str, *, signal: CancellationSignal
    ) -> IpythonWorkerResult:
        await asyncio.Future()
        raise AssertionError("unreachable")


class _CancellationResistantWorker(_MemoryWorker):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def execute_cell(
        self, code: str, *, signal: CancellationSignal
    ) -> IpythonWorkerResult:
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            await self.release.wait()
        raise RuntimeError("released")

    async def close(self) -> None:
        self.closed += 1
        self.release.set()


class _NeverClosingWorker(_LostWorker):
    def __init__(self) -> None:
        super().__init__()
        self.release_close = asyncio.Event()

    async def close(self) -> None:
        self.closed += 1
        try:
            await self.release_close.wait()
        except asyncio.CancelledError:
            await self.release_close.wait()


class _DockerLifecycleTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.count = 0
        self.value: int | None = None

    async def create_solving(self, **_: object) -> str:
        self.calls.append("create")
        self.count = 0
        return "a" * 64

    async def execute_solving(
        self, _container: str, code: str, _control: object
    ) -> dict[str, object]:
        self.calls.append("execute")
        self.count += 1
        if code == "value = 40":
            self.value = 40
            output = ""
        elif code == "print(value + 2)" and self.value is not None:
            output = f"{self.value + 2}\n"
        else:
            return {"cell_count": self.count, "is_error": True, "output": "raw"}
        return {"cell_count": self.count, "is_error": False, "output": output}

    async def remove_solving(self, *_: object) -> None:
        self.calls.append("remove")

    async def assert_solving_absent(self, *_: object) -> None:
        self.calls.append("absent")


class TestPersistentIpythonHost(unittest.IsolatedAsyncioTestCase):
    def test_native_host_has_no_legacy_product_import(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "src/asterion/applications/prime/p7/ipython_host.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("asterion.applications.prime_agent", source)

    def test_built_artifact_satisfies_task3_binding_preflight(self) -> None:
        artifact = (
            Path(__file__).parents[1]
            / "packages/typescript/asterion-prime-extension/dist/ipython-extension.mjs"
        ).resolve()
        descriptor, writer = os.pipe()
        lease = None
        try:
            binding = PiExtensionBinding(
                extension_id="prime.ipython",
                path=artifact,
                capabilities=("prime.tool.ipython",),
                inherited_fds=(descriptor,),
                environment={"ASTERION_PRIME_IPYTHON_FD": str(descriptor)},
            )
            lease = binding.preflight()
            lease.validate_launch()
            self.assertEqual(lease.command_args()[0], "--extension")
        finally:
            if lease is not None:
                lease.close()
            os.close(descriptor)
            os.close(writer)

    async def test_state_persists_across_cells(self) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            PersistentIpythonHost,
            p7_client_facade,
        )

        worker = _MemoryWorker()
        host = PersistentIpythonHost(
            worker=worker, p7_client=p7_client_facade(_Client())
        )
        first = await host.execute("c1", "value = 40", _Signal())
        second = await host.execute("c2", "print(value + 2)", _Signal())
        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "ok")
        self.assertEqual(second.call_id, "c2")
        self.assertEqual(second.content[0]["text"], "42\n")
        self.assertEqual(worker.started, 1)

    async def test_worker_sees_only_injected_p7_client_surface(self) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            PersistentIpythonHost,
            p7_client_facade,
        )

        worker = _MemoryWorker()
        host = PersistentIpythonHost(
            worker=worker, p7_client=p7_client_facade(_Client())
        )
        result = await host.execute(
            "c1",
            "import p7_client\nprint(sorted(name for name in dir(p7_client) if not name.startswith('_')))",
            _Signal(),
        )
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.content[0]["text"], "IPython cell result is uncertain")
        assert worker.namespace is not None
        client = worker.namespace["p7_client"]
        self.assertEqual(
            sorted(name for name in dir(client) if not name.startswith("_")),
            ["act", "observe", "status"],
        )
        self.assertNotIn("_Client", repr(client))

    async def test_worker_error_and_loss_are_redacted_and_fail_closed(self) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            PersistentIpythonHost,
            p7_client_facade,
        )

        failed_worker = _MemoryWorker()
        failed = PersistentIpythonHost(
            worker=failed_worker, p7_client=p7_client_facade(_Client())
        )
        error = await failed.execute("c1", "import os", _Signal())
        self.assertEqual(error.status, "uncertain")
        self.assertEqual(error.content[0]["text"], "IPython cell result is uncertain")
        self.assertEqual(failed_worker.closed, 1)
        self.assertEqual(
            (await failed.execute("c1-followup", "print(42)", _Signal())).status,
            "uncertain",
        )

        lost = PersistentIpythonHost(
            worker=_LostWorker(), p7_client=p7_client_facade(_Client())
        )
        uncertain = await lost.execute("c2", "SENTINEL-CODE", _Signal())
        self.assertEqual(uncertain.status, "uncertain")
        rendered = repr((lost, uncertain))
        for secret in ("SENTINEL", "/private/path", "import os"):
            self.assertNotIn(secret, rendered)

    async def test_non_ok_result_output_is_discarded_and_latches_loss(self) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            PersistentIpythonHost,
            p7_client_facade,
        )

        for worker_status in ("error", "uncertain"):
            with self.subTest(worker_status=worker_status):
                worker = _ResultWorker(
                    worker_status, "SENTINEL-RAW-WORKER /private/path"
                )
                host = PersistentIpythonHost(
                    worker=worker, p7_client=p7_client_facade(_Client())
                )
                result = await host.execute(
                    f"c-{worker_status}", "p7_client.act([])", _Signal()
                )
                self.assertEqual(result.status, "uncertain")
                self.assertEqual(worker.closed, 1)
                self.assertNotIn("SENTINEL", repr(result))
                followup = await host.execute(
                    f"c-{worker_status}-next", "print(42)", _Signal()
                )
                self.assertEqual(followup.status, "uncertain")

    async def test_lone_surrogate_output_is_redacted_uncertain_and_lost(self) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            PersistentIpythonHost,
            p7_client_facade,
        )

        worker = _ResultWorker("ok", "\ud800SENTINEL")
        host = PersistentIpythonHost(
            worker=worker, p7_client=p7_client_facade(_Client())
        )
        result = await host.execute("c-surrogate", "print(42)", _Signal())
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(worker.closed, 1)
        self.assertNotIn("SENTINEL", repr(result))
        self.assertEqual(
            (await host.execute("c-next", "print(1)", _Signal())).status,
            "uncertain",
        )

    async def test_cancellation_before_dispatch_is_error(self) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            PersistentIpythonHost,
            p7_client_facade,
        )

        worker = _MemoryWorker()
        result = await PersistentIpythonHost(
            worker=worker, p7_client=p7_client_facade(_Client())
        ).execute("c1", "print('SENTINEL')", _Signal(True))
        self.assertEqual(result.status, "error")
        self.assertEqual(worker.started, 0)

    async def test_timeout_after_dispatch_is_uncertain_and_closes_worker(self) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            PersistentIpythonHost,
            p7_client_facade,
        )

        worker = _BlockingWorker()
        host = PersistentIpythonHost(
            worker=worker,
            p7_client=p7_client_facade(_Client()),
            deadline_seconds=0.01,
        )
        result = await host.execute("c1", "p7_client.act([])", _Signal())
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(worker.closed, 1)
        followup = await host.execute("c2", "print(42)", _Signal())
        self.assertEqual(followup.status, "uncertain")

    async def test_cancellation_resistant_task_is_bounded_then_cleaned(self) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            PersistentIpythonHost,
            p7_client_facade,
        )

        worker = _CancellationResistantWorker()
        host = PersistentIpythonHost(
            worker=worker,
            p7_client=p7_client_facade(_Client()),
            deadline_seconds=0.01,
        )
        result = await asyncio.wait_for(
            host.execute("c1", "p7_client.act([])", _Signal()), timeout=1
        )
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(worker.closed, 1)

    async def test_close_that_suppresses_cancellation_is_reaped_with_finite_bound(
        self,
    ) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            PersistentIpythonHost,
            p7_client_facade,
        )

        worker = _NeverClosingWorker()
        host = PersistentIpythonHost(
            worker=worker,
            p7_client=p7_client_facade(_Client()),
            cleanup_seconds=0.01,
        )
        result = await asyncio.wait_for(
            host.execute("c1", "p7_client.act([])", _Signal()), timeout=1
        )
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(worker.closed, 1)
        worker.release_close.set()
        await asyncio.sleep(0.01)

    async def test_worker_cancellation_is_normalized_without_raw_context(self) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            PersistentIpythonHost,
            p7_client_facade,
        )

        host = PersistentIpythonHost(
            worker=_CancellingWorker(), p7_client=p7_client_facade(_Client())
        )
        with self.assertRaises(asyncio.CancelledError) as raised:
            await host.execute("c1", "p7_client.act([])", _Signal())
        self.assertEqual(raised.exception.args, ())
        self.assertIsNone(raised.exception.__context__)

    async def test_caller_cancellation_is_normalized_and_reaps_dispatch(self) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            PersistentIpythonHost,
            p7_client_facade,
        )

        worker = _BlockingWorker()
        host = PersistentIpythonHost(
            worker=worker, p7_client=p7_client_facade(_Client())
        )
        running = asyncio.create_task(
            host.execute("c1", "p7_client.act([])", _Signal())
        )
        await asyncio.sleep(0.01)
        running.cancel("SENTINEL-CANCEL /private/path")
        with self.assertRaises(asyncio.CancelledError) as raised:
            await running
        self.assertEqual(raised.exception.args, ())
        self.assertIsNone(raised.exception.__context__)
        self.assertEqual(worker.closed, 1)

    def test_timing_controls_must_be_finite_and_positive(self) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            PersistentIpythonHost,
            PersistentIpythonHostError,
            p7_client_facade,
        )

        for field in ("deadline_seconds", "cleanup_seconds"):
            for invalid in (float("nan"), float("inf"), float("-inf"), 0.0, -1.0):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(PersistentIpythonHostError):
                        if field == "deadline_seconds":
                            PersistentIpythonHost(
                                worker=_MemoryWorker(),
                                p7_client=p7_client_facade(_Client()),
                                deadline_seconds=invalid,
                            )
                        else:
                            PersistentIpythonHost(
                                worker=_MemoryWorker(),
                                p7_client=p7_client_facade(_Client()),
                                cleanup_seconds=invalid,
                            )

    async def test_caps_and_duplicate_call_ids_fail_before_dispatch(self) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            PersistentIpythonHost,
            p7_client_facade,
        )

        worker = _MemoryWorker()
        host = PersistentIpythonHost(
            worker=worker,
            p7_client=p7_client_facade(_Client()),
            max_code_bytes=8,
            max_output_bytes=2,
        )
        rejected = await host.execute("c1", "print(42)", _Signal())
        self.assertEqual(rejected.status, "error")
        self.assertEqual(worker.started, 0)

        accepted = PersistentIpythonHost(
            worker=worker, p7_client=p7_client_facade(_Client())
        )
        self.assertEqual((await accepted.execute("same", "value = 1", _Signal())).status, "ok")
        duplicate = await accepted.execute("same", "value = 2", _Signal())
        self.assertEqual(duplicate.status, "error")

    @unittest.skip(
        "legacy P7SolvingDockerWorker was removed; the existing-worker adapter "
        "now binds native workers only and this docker-path test awaits a native worker replacement"
    )
    async def test_production_factory_adapts_existing_restricted_worker(self) -> None:
        from asterion.applications.prime.p7.ipython_host import (
            create_restricted_persistent_ipython_host,
        )
        from asterion.applications.prime_agent.operator.p7_solving_docker import (
            P7SolvingDockerWorker,
        )

        client = b"def observe(): return {}\ndef status(): return {}\ndef act(actions): return {}\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, broker = root / "workspace", root / "broker"
            workspace.mkdir()
            broker.mkdir()
            transport = _DockerLifecycleTransport()
            worker = P7SolvingDockerWorker(
                image_digest="sha256:" + "a" * 64,
                transport=transport,
                workspace=str(workspace),
                broker_private_dir=str(broker),
                broker_model_socket=str(broker / "model.sock"),
            )
            host = create_restricted_persistent_ipython_host(
                worker=worker,
                p7_client_module=client,
            )
            with patch(
                "asterion.applications.prime_agent.operator.p7_solving_docker.os.fchown"
            ):
                first = await host.execute("c1", "value = 40", _Signal())
                second = await host.execute("c2", "print(value + 2)", _Signal())
                await host.close()
            self.assertEqual(first.status, "ok")
            self.assertEqual(second.content[0]["text"], "42\n")
            self.assertEqual(
                transport.calls,
                ["create", "execute", "execute", "remove", "absent"],
            )


if __name__ == "__main__":
    unittest.main()
