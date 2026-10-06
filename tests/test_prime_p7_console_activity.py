import json
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_prime_p7_console_session import ConsoleSessionFixture, RUN_ID


SECOND_ID = 'p7-live-20261006101010-' + 'b' * 24
UNITS = ('asterion-p7-' + 'a' * 32 + '.service', 'asterion-p7-' + 'b' * 32 + '.service')
CATALOG = ({'game_id': 'test-1', 'alias': 'test', 'win_levels': 2, 'baseline_actions': (20, 20)},
           {'game_id': 'test-2', 'alias': 'second', 'win_levels': 2, 'baseline_actions': (20, 20)})


class TestConsoleCampaignActivity(ConsoleSessionFixture):
    def campaign(self):
        self.root = self.root.resolve()
        runs = self.root / '.asterion-private' / 'prime-p7-live'
        launches = runs / 'launches'
        launches.mkdir(parents=True)
        active = []
        processes = {}
        for index, (game, run_id, unit) in enumerate(zip(CATALOG, (RUN_ID, SECOND_ID), UNITS), 100):
            (runs / run_id).mkdir()
            args = ['make', 'asterion-prime-p7-level-witness', f"GAME={game['game_id']}",
                    'LEVEL=1', f'ASTERION_PRIME_P7_ATTEMPT_UNIT={unit}']
            active.append({'game': game['game_id'], 'run_id': run_id, 'unit': unit,
                           'host_make_pid': index, 'host_make_pgid': index, 'args': args})
            processes[index] = {'pgid': index, 'command': '/usr/bin/' + ' '.join(args)}
        path = launches / 'parallel-campaign-state.json'
        path.write_text(json.dumps({'active': active, 'stop': False}))
        return runs, path, active, processes

    def test_two_live_campaign_games_require_matching_make_and_running_guest_unit(self):
        from asterion.applications.prime.p7.console_activity import campaign_solving
        runs, path, active, processes = self.campaign()
        def read(pids):
            self.assertEqual(pids, (100, 101))
            return processes
        expected = {'test-1': RUN_ID, 'test-2': SECOND_ID}
        self.assertEqual(campaign_solving(runs, {'test-1', 'test-2'}, frozenset(UNITS), process_reader=read), expected)
        self.assertEqual(campaign_solving(runs, {'test-1', 'test-2'}, frozenset(UNITS[:1]),
                                         process_reader=lambda _: processes), {'test-1': RUN_ID})
        for changed in ({'pgid': 99}, {'command': '/usr/bin/python ' + ' '.join(active[0]['args'][1:])},
                        {'command': processes[100]['command'].replace('GAME=test-1', 'GAME=test-2')}):
            with self.subTest(changed=list(changed)):
                bad = {**processes, 100: {**processes[100], **changed}}
                self.assertEqual(campaign_solving(runs, {'test-1', 'test-2'}, frozenset(UNITS),
                                                 process_reader=lambda _: bad), {'test-2': SECOND_ID})
        (runs / RUN_ID / 'summary.json').write_text('{}')
        self.assertEqual(campaign_solving(runs, {'test-1', 'test-2'}, frozenset(UNITS),
                                         process_reader=lambda _: {100: processes[100]}), {})
        path.write_text(json.dumps({'active': active, 'stop': True}))
        self.assertEqual(campaign_solving(runs, {'test-1', 'test-2'}, frozenset(UNITS),
                                         process_reader=lambda _: processes), {})

    def test_overview_activity_is_additive_only_and_shares_guest_query_cache(self):
        _, _, _, processes = self.campaign()
        calls = []
        def units():
            calls.append(True)
            return {unit: True for unit in UNITS}
        session = self.session(catalog=CATALOG, guest_activity_reader=None, guest_unit_reader=units)
        source = {'games': [dict(game, active_run_id=None, best_run_id=None,
                                runs=[{'run_id': run_id, 'status': 'recording'}])
                            for game, run_id in zip(CATALOG, (RUN_ID, SECOND_ID))]}
        session._overview_reader = SimpleNamespace(build=lambda **_: json.loads(json.dumps(source)))
        with patch('asterion.applications.prime.p7.console_activity.live_make_processes', return_value=processes):
            first = session.overview()
            second = session.overview()
        self.assertEqual(calls, [True])
        self.assertIs(first['guest_busy'], True)
        for game in first['games']:
            self.assertIs(game['solving'], True)
            self.assertEqual(game['solving_run_id'], game['runs'][0]['run_id'])
            self.assertIsNone(game['active_run_id'])
            self.assertIsNone(game['best_run_id'])
        self.assertEqual(first, second)
        source['games'][1]['runs'] = []
        with patch('asterion.applications.prime.p7.console_activity.live_make_processes', return_value=processes):
            missing = session.overview()['games'][1]
        self.assertIs(missing['solving'], False)
        self.assertIsNone(missing['solving_run_id'])

    def test_three_and_four_running_games_are_visible_but_five_fail_closed(self):
        from asterion.applications.prime.p7.console_activity import campaign_solving
        runs, path, active, processes = self.campaign()
        for index in range(2, 5):
            run_id = f'p7-live-20261006101010-{index:024x}'
            unit = f'asterion-p7-{index:032x}.service'
            game = f'test-{index + 1}'
            (runs / run_id).mkdir()
            args = ['make', 'asterion-prime-p7-level-witness', f'GAME={game}',
                    'LEVEL=1', f'ASTERION_PRIME_P7_ATTEMPT_UNIT={unit}']
            pid = 100 + index
            active.append(dict(game=game, run_id=run_id, unit=unit,
                               host_make_pid=pid, host_make_pgid=pid, args=args))
            processes[pid] = {'pgid': pid, 'command': '/usr/bin/' + ' '.join(args)}
        for count in (3, 4, 5):
            with self.subTest(count=count):
                selected = active[:count]
                path.write_text(json.dumps({'active': selected, 'stop': False,
                                            'max_active_guests': count}))
                output = '\n'.join(f"{pid} {value['pgid']} {value['command']}"
                                   for pid, value in processes.items() if pid < 100 + count)
                with patch('asterion.applications.prime.p7.console_activity.subprocess.run',
                           return_value=SimpleNamespace(returncode=0, stdout=output)) as query:
                    actual = campaign_solving(runs, {entry['game'] for entry in selected},
                                              frozenset(entry['unit'] for entry in selected))
                expected = {entry['game']: entry['run_id'] for entry in selected} if count <= 4 else {}
                self.assertEqual(actual, expected)
                self.assertEqual(query.call_count, 1 if count <= 4 else 0)
