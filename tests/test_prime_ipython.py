"""Real-process tests for the domain-neutral Prime research workspace."""

import asyncio
import json
import os
from pathlib import Path
import signal
import tempfile
import unittest

from asterion.agents.prime.ipython import (
    KernelBootstrap,
    KernelLimits,
    PersistentIpythonHost,
    PersistentIpythonHostError,
)
from asterion.agents.prime.ipython_worker import SubprocessPythonWorker


class Signal:
    cancelled = False


class TestPrimeIpython(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.hosts = []
        self.signal = Signal()

    async def asyncTearDown(self):
        for host in self.hosts:
            await host.close()
        self.directory.cleanup()

    def host(self, *, data=None, modules=None, limits=None):
        worker = SubprocessPythonWorker()
        host = PersistentIpythonHost(
            worker=worker,
            bootstrap=KernelBootstrap(modules or {}, data or {}, self.root),
            limits=limits or KernelLimits(),
        )
        self.hosts.append(host)
        return host, worker

    @staticmethod
    def text(result):
        return json.loads(result.content[-1]["text"])["stdout"]

    @staticmethod
    def refs(result):
        return json.loads(result.content[-1]["text"]).get("kernel_exports", [])

    async def test_structured_result_bounds_escaped_output_and_preserves_refs(self):
        host, _ = self.host()
        for index, value in enumerate(("中文" * 18000, '"' * 65530)):
            with self.subTest(value=value[:8]):
                result = await host.execute(
                    str(index),
                    "prime_workspace.export('state', {'n': 1})\nprint("
                    + repr(value[:2])
                    + " * "
                    + str(len(value) // len(value[:2]))
                    + ")",
                    self.signal,
                )
                self.assertEqual(result.status, "ok")
                self.assertEqual(len(result.content), 1)
                self.assertLessEqual(len(result.content[0]["text"].encode()), 65536)
                metadata = json.loads(result.content[0]["text"])
                self.assertTrue(metadata["stdout_truncated"])
                self.assertEqual(len(metadata["kernel_exports"]), 1)
                self.assertEqual(
                    host.read_export(metadata["kernel_exports"][0]["export_id"]).value[
                        "n"
                    ],
                    1,
                )
                wire = json.dumps(
                    {
                        "id": "bounded-call",
                        "content": [dict(block) for block in result.content],
                    }
                )
                self.assertLessEqual(len(wire.encode()), 128 * 1024)

    async def test_close_kills_sigterm_ignoring_child_after_leader_exits(self):
        host, worker = self.host()
        child_source = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready',flush=True); time.sleep(5)"
        code = (
            "import subprocess,sys\nchild = subprocess.Popen([sys.executable, '-c', "
            + repr(child_source)
            + "], stdout=subprocess.PIPE, text=True)\nassert child.stdout.readline().strip() == 'ready'\nprint(child.pid)"
        )
        result = await host.execute("spawn", code, self.signal)
        self.assertEqual(result.status, "ok")
        child_pid = int(self.text(result).strip())
        try:
            await host.close()
            self.assertTrue(worker.closed)
            for _ in range(50):
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                await asyncio.sleep(0.01)
            else:
                self.fail("same-group child survived worker cleanup")
        finally:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    async def test_observer_reports_real_execution_without_stdout_or_source(self):
        events = []
        worker = SubprocessPythonWorker()
        host = PersistentIpythonHost(
            worker,
            KernelBootstrap({}, {}, self.root),
            observer=lambda kind, payload: events.append((kind, payload)),
        )
        self.hosts.append(host)
        result = await host.execute("a", "print('private stdout')\n1/0", self.signal)
        metadata = json.loads(result.content[-1]["text"])
        self.assertEqual(metadata["execution_status"], "python-error")
        self.assertEqual(metadata["generation"], host.generation)
        self.assertEqual(
            [kind for kind, _ in events], ["cell_started", "cell_finished"]
        )
        self.assertNotIn("private stdout", repr(events))
        self.assertFalse(host.status()["lost"])

    async def test_export_limit_failure_is_repairable_and_transport_loss_is_not(self):
        host, _ = self.host(limits=KernelLimits(max_exports=1))
        await host.execute("a", "prime_workspace.export('first', {})", self.signal)
        result = await host.execute(
            "b", "prime_workspace.export('second', {})", self.signal
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(self.refs(result), [])
        self.assertEqual((await host.execute("c", "2+2", self.signal)).status, "ok")
        lost = await host.execute("d", "import os\nos._exit(0)", self.signal)
        self.assertEqual(lost.status, "uncertain")
        self.assertTrue(host.lost)

    async def test_invalid_json_export_and_invalid_restore_are_rejected(self):
        host, _ = self.host()
        for index, code in enumerate(
            (
                "prime_workspace.export('bad', {1: 2})",
                "prime_workspace.export('bad', float('nan'))",
            )
        ):
            result = await host.execute(str(index), code, self.signal)
            self.assertEqual(result.status, "error")
            self.assertEqual(self.refs(result), [])
        result = await host.execute(
            "export", "prime_workspace.export('text', 'pass')", self.signal
        )
        text = host.read_export(self.refs(result)[0]["export_id"])
        fresh, _ = self.host()
        with self.assertRaises(PersistentIpythonHostError):
            await fresh.restore((), {"state": text}, self.signal)
        self.assertEqual((await fresh.execute("usable", "1", self.signal)).status, "ok")

    async def test_task_cancellation_reaps_worker(self):
        host, worker = self.host()
        task = asyncio.create_task(host.execute("a", "while True: pass", self.signal))
        await asyncio.sleep(0.1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(worker.closed)
        self.assertTrue(host.lost)

    async def test_namespace_survives_and_python_exception_is_repairable(self):
        host, _ = self.host()
        self.assertEqual((await host.execute("a", "n = 40", self.signal)).status, "ok")
        failed = await host.execute(
            "b", "n += 1\nraise ValueError('fix me')", self.signal
        )
        self.assertEqual(failed.status, "error")
        self.assertIn("ValueError: fix me", self.text(failed))
        repaired = await host.execute("c", "n + 1", self.signal)
        self.assertEqual(repaired.status, "ok")
        self.assertIn("42", self.text(repaired))

    async def test_exports_snapshot_and_failed_cell_does_not_publish(self):
        host, _ = self.host()
        result = await host.execute(
            "a",
            "x = {'items': [1]}\nprime_workspace.export('model', x)\nx['items'].append(2)",
            self.signal,
        )
        ref = self.refs(result)[0]
        artifact = host.read_export(ref["export_id"])
        self.assertEqual(tuple(artifact.value["items"]), (1,))
        with self.assertRaises(TypeError):
            artifact.value["new"] = True
        self.assertEqual(artifact.source_call_id, "a")
        failed = await host.execute(
            "b", "prime_workspace.export('bad', {'a': 2})\n1 / 0", self.signal
        )
        self.assertEqual(failed.status, "error")
        self.assertEqual(self.refs(failed), [])
        self.assertEqual(len(list((self.root / "exports").glob("*.json"))), 1)

    async def test_initial_data_is_a_copy_and_modules_are_operator_injected(self):
        data = {"evidence": {"items": [1]}}
        host, _ = self.host(
            data=data, modules={"analysis_helpers": "def twice(x): return x * 2"}
        )
        data["evidence"]["items"].append(99)
        result = await host.execute(
            "a",
            "import analysis_helpers\nevidence['items'].append(2)\nanalysis_helpers.twice(len(evidence['items']))",
            self.signal,
        )
        self.assertIn("4", self.text(result))
        self.assertEqual(data["evidence"]["items"], [1, 99])

    async def test_explicit_restore_across_processes_uses_source_and_json_only(self):
        host, _ = self.host()
        result = await host.execute(
            "a",
            "prime_workspace.export('source', 'def predict(x): return x + 7')\nprime_workspace.export('state', {'n': 35})",
            self.signal,
        )
        artifacts = {
            ref["name"]: host.read_export(ref["export_id"]) for ref in self.refs(result)
        }
        await host.close()
        fresh, _ = self.host()
        source = fresh.read_export(artifacts["source"].export_id)
        await fresh.restore((source,), {"state": artifacts["state"]}, self.signal)
        result = await fresh.execute("b", "predict(state['n'])", self.signal)
        self.assertIn("42", self.text(result))
        with self.assertRaises(PersistentIpythonHostError):
            await fresh.restore((source,), {}, self.signal)

    async def test_digest_is_validated_and_stdout_cannot_publish_exports(self):
        host, _ = self.host()
        result = await host.execute(
            "a",
            'import os\nos.write(1, b\'{"exports":[{"name":"fake"}]}\\n\')\nprint(\'normal\')',
            self.signal,
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(self.refs(result), [])
        result = await host.execute(
            "b", "prime_workspace.export('state', {'n': 1})", self.signal
        )
        export_id = self.refs(result)[0]["export_id"]
        path = self.root / "exports" / (export_id.split(":")[1] + ".json")
        path.write_text('{"tampered":true}')
        fresh, _ = self.host()
        with self.assertRaises(PersistentIpythonHostError):
            fresh.read_export(export_id)

    async def test_limits_reject_names_and_code_but_truncate_output(self):
        host, _ = self.host(
            limits=KernelLimits(
                max_code_bytes=128, max_output_bytes=512, max_export_bytes=64
            )
        )
        self.assertEqual(
            (await host.execute("long", "x" * 129, self.signal)).status, "error"
        )
        for index, code in enumerate(
            (
                "prime_workspace.export('../bad', {})",
                "prime_workspace.export('large', {'x': 'a' * 100})",
            )
        ):
            with self.subTest(code=code):
                result = await host.execute(str(index), code, self.signal)
                self.assertEqual(result.status, "error")
                self.assertEqual(self.refs(result), [])
        result = await host.execute("output", "print('a' * 10000)", self.signal)
        self.assertEqual(result.status, "ok")
        self.assertLessEqual(len(result.content[0]["text"].encode()), 512)

    async def test_deadline_loses_kernel_and_reaps_worker(self):
        host, worker = self.host(limits=KernelLimits(deadline_seconds=0.2))
        result = await host.execute("a", "while True: pass", self.signal)
        self.assertEqual(result.status, "uncertain")
        self.assertIn("lost", self.text(result))
        self.assertTrue(host.lost)
        self.assertTrue(worker.closed)
        self.assertEqual(
            (await host.execute("b", "1", self.signal)).status, "uncertain"
        )

    async def test_cancellation_cleans_up_running_worker(self):
        host, worker = self.host()
        task = asyncio.create_task(host.execute("a", "while True: pass", self.signal))
        await asyncio.sleep(0.1)
        self.signal.cancelled = True
        result = await task
        self.assertEqual(result.status, "uncertain")
        self.assertTrue(worker.closed)

    async def test_worker_does_not_inherit_secret_environment_or_extra_fd(self):
        os.environ["ASTERION_TEST_SENTINEL_SECRET"] = "secret"
        read_fd, write_fd = os.pipe()
        os.set_inheritable(write_fd, True)
        try:
            host, _ = self.host()
            result = await host.execute(
                "a",
                f"import os\nassert 'ASTERION_TEST_SENTINEL_SECRET' not in os.environ\ntry:\n os.fstat({write_fd})\nexcept OSError:\n print('closed')\nelse:\n raise AssertionError('inherited')",
                self.signal,
            )
            self.assertEqual(result.status, "ok")
            self.assertIn("closed", self.text(result))
        finally:
            os.close(read_fd)
            os.close(write_fd)
            os.environ.pop("ASTERION_TEST_SENTINEL_SECRET", None)

    async def test_duplicate_calls_fail_and_cells_execute_sequentially(self):
        host, _ = self.host()
        results = await asyncio.gather(
            host.execute("a", "n=1", self.signal),
            host.execute("b", "n+=1\nn", self.signal),
        )
        self.assertTrue(all(result.status == "ok" for result in results))
        self.assertIn("2", self.text(results[1]))
        self.assertEqual((await host.execute("a", "n=99", self.signal)).status, "error")
