from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime.p7.solver_control import (
    SCHEMA, SolverControl, read_control_ack, write_control_request,
)


class TestP7SolverControl(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'run-test'
        self.root.mkdir()
        self.now = 0
        self.control = SolverControl(self.root, self.root.name, 10, clock=lambda: self.now)
        self.hash = 'sha256:' + 'a' * 64

    def wire(self, operation, sequence, command):
        return write_control_request(self.root, run_id=self.root.name,
            command_id=command, request_sequence=sequence, operation=operation)

    def test_pause_waits_for_real_action_boundary_and_blocks_new_work(self):
        self.assertTrue(self.control.enter('action'))
        request = self.wire('pause', 1, 'pause-1')
        self.assertEqual(self.wire('pause', 1, 'pause-1'), request)
        paused = self.control.poll(4, self.hash)
        self.assertEqual(paused['state'], 'pause_requested')
        self.assertFalse(self.control.enter('cell'))
        self.assertFalse(self.control.action_allowed())
        self.control.leave('action')
        ack = read_control_ack(self.root, run_id=self.root.name)
        self.assertEqual(ack['state'], 'paused')
        self.assertEqual((ack['command_id'], ack['request_sequence']), ('pause-1', 1))
        self.assertEqual(ack['source_action_sequence'], 4)
        self.wire('resume', 2, 'resume-1')
        self.assertEqual(self.control.poll(4, self.hash)['state'], 'running')
        self.assertTrue(self.control.enter('cell'))
        self.control.leave('cell')
        self.now = 10
        self.assertFalse(self.control.action_allowed())
        self.assertEqual(self.control.snapshot()['reason'], 'deadline_expired')
        self.wire('resume', 3, 'resume-expired')
        self.assertEqual(self.control.poll(4, self.hash)['state'], 'stop_requested')

    def test_stale_identity_conflict_and_closed_data_reject(self):
        self.wire('pause', 1, 'command-1')
        self.control.poll(0, self.hash)
        for kwargs in ({'request_sequence': 1, 'command_id': 'command-2'},
                       {'request_sequence': 2, 'command_id': 'command-1'},
                       {'request_sequence': True, 'command_id': 'command-2'},
                       {'request_sequence': 2, 'command_id': '/private/SENTINEL'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                write_control_request(self.root, run_id=self.root.name, operation='resume', **kwargs)
        request = json.loads((self.root / 'control-request.json').read_text())
        for changed in ({'operation': []}, {'prompt': 'SENTINEL'}, {'run_id': 'wrong-run'}):
            with self.subTest(changed=changed):
                (self.root / 'control-request.json').write_text(json.dumps({**request, **changed}))
                with self.assertRaises(ValueError):
                    self.control.poll(0, self.hash)
        self.assertNotIn('SENTINEL', (self.root / 'control-ack.json').read_text())

    def test_duplicate_keys_symlinks_and_wrong_ack_are_not_accepted(self):
        path = self.root / 'control-ack.json'
        path.write_text('{"schema":"x","schema":"y"}')
        with self.assertRaises(ValueError):
            read_control_ack(self.root, run_id=self.root.name)
        path.unlink()
        external = self.root.parent / 'external'
        external.write_text('SENTINEL')
        path.symlink_to(external)
        with self.assertRaises(ValueError):
            self.control.poll(0, self.hash)
        self.assertEqual(external.read_text(), 'SENTINEL')
        path.unlink()
        self.control.poll(0, self.hash)
        ack = read_control_ack(self.root, run_id=self.root.name)
        self.assertEqual(ack['schema'], SCHEMA)
        path.write_text(json.dumps({**ack, 'state': []}))
        with self.assertRaises(ValueError):
            read_control_ack(self.root, run_id=self.root.name)

    def test_cell_pause_and_stop_never_claim_cleanup_or_extend_deadline(self):
        self.assertTrue(self.control.enter('cell'))
        self.control.request('pause', 'pause-cell')
        self.assertEqual(self.control.snapshot()['state'], 'pause_requested')
        self.control.leave('cell')
        self.assertEqual(self.control.snapshot()['state'], 'paused')
        self.control.request('stop', 'stop')
        self.assertFalse(self.control.enter('action'))
        self.assertEqual(self.control.snapshot()['state'], 'stop_requested')
        self.control.request('resume', 'resume')
        self.assertEqual(self.control.snapshot()['state'], 'stop_requested')
