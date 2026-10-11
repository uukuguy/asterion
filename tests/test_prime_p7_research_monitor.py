"""Passive telemetry must not change sequential effect admission or evidence."""
import asyncio
from dataclasses import FrozenInstanceError, asdict, replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from asterion.applications.prime.p7.action_journal import ActionJournal
from asterion.applications.prime.p7.broker import ArcBroker, ArcBrokerError
from asterion.applications.prime.p7.game import DEFAULT_GAME
from asterion.applications.prime.p7.research_monitor import ResearchMonitor


class _Engine:
    game_id, seed = DEFAULT_GAME.game_id, DEFAULT_GAME.seed

    def __init__(self, root):
        self.action_journal = ActionJournal(root / 'journal',
            {'run_id': 'run-test', 'game_id': self.game_id, 'seed': self.seed})
        self.calls = 0
        self.levels = 0
        self.on_step = lambda: None
        self.fail = False

    def observe(self):
        return {'frame': [[[self.calls % 16]]], 'available_actions': ['ACTION1'],
                'levels_completed': self.levels, 'win_levels': DEFAULT_GAME.win_levels,
                'state': 'NOT_FINISHED'}

    def step(self, name):
        self.calls += 1
        self.on_step()
        if self.fail:
            raise TimeoutError('no engine reply')
        return self.observe()


class TestResearchMonitor(unittest.TestCase):
    def test_cache_and_cost_are_preserved_in_safe_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            monitor = ResearchMonitor(root, 'run-test', ArcBroker(engine=_Engine(root)), self.owner())
            monitor.event('usage.reported', dict(input_tokens=100, output_tokens=5,
                uncached_input_tokens=10, cache_read_tokens=80, cache_write_tokens=10,
                reported_cost=dict(currency='USD', total=0.012, source='pi_sdk_estimate')))
            record = json.loads((root / 'research-status.json').read_text())
            self.assertEqual(record['cache_read_tokens'], 80)
            self.assertEqual(record['cache_read_ratio'], 0.8)
            self.assertEqual(record['reported_cost']['total'], 0.012)
            monitor.event('usage.reported', dict(input_tokens=20, output_tokens=2))
            record = json.loads((root / 'research-status.json').read_text())
            self.assertEqual(record['input_tokens'], 120)
            self.assertIsNone(record['cache_read_tokens'])
            self.assertIsNone(record['reported_cost'])
            self.assertEqual(record['reported_cost_covered_events'], 1)

    def owner(self):
        return SimpleNamespace(runtime_observation=lambda: {})

    def sample_heartbeat(self, monitor):
        async def once():
            stopped = asyncio.Event()
            def poll():
                stopped.set()
                return {'state': 'running'}
            await monitor.heartbeat(stopped, SimpleNamespace(cancelled=False),
                                    SimpleNamespace(poll=poll))
        asyncio.run(once())

    def test_inflight_sampling_preserves_broker_and_transaction(self):
        for mode in ('initial', 'sample', 'event', 'heartbeat'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                engine = _Engine(root)
                broker = ArcBroker(engine=engine)
                monitor = None if mode == 'initial' else ResearchMonitor(
                    root, 'run-test', broker, self.owner())
                sampled = []
                def during_step():
                    pending = engine.action_journal.snapshot()
                    self.assertEqual(pending['phase'], 'entered')
                    current, journal = broker._current, broker.journal
                    if mode == 'initial':
                        ResearchMonitor(root, 'run-test', broker, self.owner())
                    elif mode == 'event':
                        monitor.event('usage.reported', {'input_tokens': 2,
                            'prompt': 'SECRET_SENTINEL'})
                    elif mode == 'heartbeat':
                        self.sample_heartbeat(monitor)
                    else:
                        monitor.sample()
                    sampled.append((broker._terminal_reason, broker.processing_diagnostic))
                    self.assertEqual(engine.action_journal.snapshot(), pending)
                    self.assertIs(broker._current, current)
                    self.assertEqual(broker.journal, journal)
                    record = json.loads((root / 'research-status.json').read_text())
                    self.assertEqual(record['primitive_actions'], 1)
                    self.assertNotIn('SECRET_SENTINEL', json.dumps(record))
                engine.on_step = during_step
                broker.act(('ACTION1',))
                self.assertEqual(sampled, [('active', None)])
                self.assertEqual(engine.action_journal.snapshot()['phase'], 'committed')
                self.assertEqual(broker.status().terminal_reason, 'active')
                self.assertIsNone(broker.processing_diagnostic)

    def test_unknown_outcome_remains_blocked_after_passive_sampling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            engine = _Engine(root)
            broker = ArcBroker(engine=engine)
            monitor = ResearchMonitor(root, 'run-test', broker, self.owner())
            broker.act(('ACTION1',))
            broker.act(('RESET',))
            engine.fail = True
            with self.assertRaises(ArcBrokerError):
                broker.act(('ACTION1',))
            pending = engine.action_journal.snapshot()
            diagnostic = broker.processing_diagnostic
            self.assertEqual(broker._terminal_reason, 'engine-uncertain')
            self.assertFalse(pending['outcome_known'])
            monitor.sample()
            self.assertEqual(engine.action_journal.snapshot(), pending)
            self.assertEqual(broker.processing_diagnostic, diagnostic)
            self.assertEqual(broker._terminal_reason, 'engine-uncertain')
            record = json.loads((root / 'research-status.json').read_text())
            self.assertEqual((record['primitive_actions'], record['levels_completed'],
                              record['resets']), (3, 0, 1))
            self.assertEqual(asdict(broker.accounting_snapshot()),
                             {'primitive_actions': 3, 'levels_completed': 0, 'resets': 1})
            for operation in (broker.status, broker.observe, lambda: broker.act(('ACTION1',))):
                with self.assertRaises(ArcBrokerError):
                    operation()
            self.assertEqual(engine.calls, 3)

    def test_accounting_is_immutable_in_finite_and_supervised_runs(self):
        for supervised in (False, True):
            with self.subTest(supervised=supervised), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                engine = _Engine(root)
                broker = ArcBroker(engine=engine,
                    game=replace(DEFAULT_GAME, supervised_research=supervised))
                initial = broker.accounting_snapshot()
                self.assertEqual(asdict(initial),
                    {'primitive_actions': 0, 'levels_completed': 0, 'resets': 0})
                with self.assertRaises(FrozenInstanceError):
                    initial.primitive_actions = 9
                broker.act(('ACTION1',))
                broker.act(('RESET',))
                engine.levels = 1
                broker.act(('ACTION1',))
                self.assertEqual(asdict(broker.accounting_snapshot()),
                    {'primitive_actions': 3, 'levels_completed': 1, 'resets': 1})
                self.assertEqual(initial.primitive_actions, 0)
                terminal = broker.terminal_snapshot().status
                self.assertEqual(terminal.terminal_reason, 'level-completed')
                self.assertEqual(broker.accounting_snapshot().primitive_actions,
                                 terminal.primitive_actions)
                with self.assertRaises(ArcBrokerError):
                    broker.act(('ACTION1',))
