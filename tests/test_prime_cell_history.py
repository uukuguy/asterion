"""Current-workspace computation evidence, independent of any application."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.agents.prime.ipython import (
    KernelBootstrap, KernelLimits, PersistentIpythonHost, PersistentIpythonHostError,
)
from asterion.agents.prime.ipython_worker import SubprocessPythonWorker


class Signal:
    cancelled = False


class TestPrimeCellHistory(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.hosts = []

    async def asyncTearDown(self):
        for host in self.hosts:
            await host.close()
        self.directory.cleanup()

    def host(self, root=None, limits=None):
        host = PersistentIpythonHost(SubprocessPythonWorker(),
            KernelBootstrap({}, {}, root or self.root), limits or KernelLimits())
        self.hosts.append(host)
        return host

    async def test_source_and_python_error_readback_are_automatic_paged_and_durable(self):
        host = self.host()
        source = "counter = 1\nprint('真实结果')\nraise ValueError('ordinary failure')"
        result = await host.execute('first', source, Signal())
        self.assertEqual(result.status, 'error')
        directory = host.cell_history()
        self.assertEqual(directory['total'], 1)
        item = directory['items'][0]
        self.assertEqual(item['status'], 'python-error')
        self.assertTrue(item['output_available'])
        self.assertFalse(item['output_truncated'])
        cell_id = item['cell_id']
        first = host.cell_read(cell_id, 'source', 0, 9)
        second = host.cell_read(cell_id, 'source', first['next_start'], 4096)
        self.assertEqual(first['text'] + second['text'], source)
        self.assertFalse(second['source_truncated'])
        self.assertIn('ValueError: ordinary failure', host.cell_read(cell_id, 'output')['text'])
        self.assertEqual(host.cell_history(), directory)
        await host.close()
        restored = self.host()
        self.assertEqual(restored.cell_read(cell_id, 'source')['text'], source)
        unrelated = self.host(self.root / 'other')
        with self.assertRaises(PersistentIpythonHostError):
            unrelated.cell_read(cell_id)

    async def test_inspect_source_survives_redefinition_and_explicit_restore(self):
        host = self.host()
        original = 'def value():\n    return 1\n'
        changed = 'def value():\n    return 2\n'
        await host.execute('a', original + 'old = value', Signal())
        await host.execute('b', changed, Signal())
        result = await host.execute('c',
            'import inspect\nassert inspect.getsource(old) == '+repr(original)+'\n'
            'assert inspect.getsource(value) == '+repr(changed), Signal())
        self.assertEqual(result.status, 'ok', result)
        exported = await host.execute('d', 'prime_workspace.export("source", '+repr(original)+')', Signal())
        ref = json.loads(exported.content[0]['text'])['kernel_exports'][0]['export_id']
        fresh = self.host()
        await fresh.restore((host.read_export(ref),), {}, Signal())
        result = await fresh.execute('e', 'import inspect\nassert inspect.getsource(value) == '+repr(original), Signal())
        self.assertEqual(result.status, 'ok', result)

    async def test_worker_truncation_is_explicit_in_archive_and_tool_result(self):
        host = self.host(limits=KernelLimits(max_output_bytes=1024))
        result = await host.execute('large', "print('界' * 2000)", Signal())
        self.assertEqual(result.status, 'ok')
        self.assertTrue(json.loads(result.content[0]['text'])['stdout_truncated'])
        item = host.cell_history()['items'][0]
        self.assertTrue(item['output_truncated'])
        self.assertLessEqual(item['output_bytes'], 1024)
        self.assertTrue(host.cell_read(item['cell_id'], 'output')['output_truncated'])

    async def test_lost_cell_keeps_source_without_fabricating_output(self):
        host = self.host()
        result = await host.execute('exit', 'import os\nos._exit(0)', Signal())
        self.assertEqual(result.status, 'uncertain')
        item = host.cell_history()['items'][0]
        self.assertEqual(item['status'], 'lost')
        self.assertFalse(item['output_available'])
        self.assertIsNone(host.cell_read(item['cell_id'], 'output')['text'])

    async def test_invalid_pages_and_symlinks_do_not_escape_workspace(self):
        host = self.host()
        await host.execute('a', '1', Signal())
        item = host.cell_history()['items'][0]
        for args in [('../secret',), (item['cell_id'], 'unknown'), (item['cell_id'], 'source', -1),
                     (item['cell_id'], 'source', 0, 16385)]:
            with self.subTest(args=args), self.assertRaises(PersistentIpythonHostError):
                host.cell_read(*args)
        with self.assertRaises(PersistentIpythonHostError):
            host.cell_history(0, 65)
        record = self.root / 'cells' / (item['cell_id'][5:] + '.json')
        record.unlink()
        secret = self.root / 'secret'
        secret.write_text('PRIVATE_HISTORY_SENTINEL')
        record.symlink_to(secret)
        with self.assertRaises(PersistentIpythonHostError) as error:
            host.cell_read(item['cell_id'])
        self.assertNotIn('PRIVATE_HISTORY_SENTINEL', str(error.exception))

    async def test_capacity_keeps_existing_record_and_rejects_before_execution(self):
        host = self.host(limits=KernelLimits(max_history_records=1))
        await host.execute('a', 'old = 1', Signal())
        result = await host.execute('b', "from pathlib import Path\nPath('unexpected').touch()", Signal())
        self.assertEqual(result.status, 'error')
        self.assertFalse((self.root / 'unexpected').exists())
        self.assertEqual(host.cell_history()['total'], 1)
        self.assertFalse(host.lost)
        self.assertEqual(host.cell_read(host.cell_history()['items'][0]['cell_id'])['text'], 'old = 1')

    async def test_cancelled_cell_preserves_source_and_unavailable_output(self):
        host = self.host()
        task = asyncio.create_task(host.execute('cancel', 'while True: pass', Signal()))
        for _ in range(100):
            if host.cell_history()['total']:
                break
            await asyncio.sleep(0.01)
        pending = host.cell_history()['items'][0]
        self.assertEqual(pending['status'], 'pending')
        self.assertIsNone(host.cell_read(pending['cell_id'], 'output')['text'])
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        item = host.cell_history()['items'][0]
        self.assertEqual(item['status'], 'interrupted')
        self.assertFalse(item['output_available'])

    async def test_archive_failure_does_not_reclassify_success_or_publish_fake_output(self):
        host = self.host()
        with patch.object(host._history, 'finish', side_effect=OSError('PRIVATE_STORAGE_SENTINEL')):
            result = await host.execute('executed', 'n = 7\nprint(n)', Signal())
        self.assertEqual(result.status, 'ok')
        self.assertFalse(host.lost)
        page = host.cell_history()
        self.assertEqual(page['history_error'], 'history-write-unavailable')
        self.assertNotIn('PRIVATE_STORAGE_SENTINEL', repr(page))
        self.assertFalse(page['items'][0]['output_available'])
