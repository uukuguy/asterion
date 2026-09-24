"""Offline HTTP and filesystem boundaries for closed-card recovery."""
from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7.official import OfficialError
from asterion.applications.prime.p7.official_recovery import recover_official_receipt


def record():
    return dict(schema='asterion.prime.p7-official-recovery/v1',
                status='recovery-required', card_id='card-1', game_ids=['aa-v1', 'bb-v1'],
                selected_game_ids=['aa-v1'], unattempted_game_ids=[],
                guids={'aa-v1': 'private-guid'}, aborted=False, normal_close_confirmed=True)


def card():
    def run(game, guid, actions):
        return dict(id=game, guid=guid, score=0, state='NOT_FINISHED', completed=False,
                    levels_completed=0, actions=actions, resets=0)
    return dict(card_id='card-1', competition_mode=True, score=0.0,
                environments=[dict(id='aa-v1', runs=[run('aa-v1', 'private-guid', 20)]),
                              dict(id='bb-v1', runs=[run('bb-v1', 'server-guid', 0)])],
                opaque='SECRET-SENTINEL', api_key='SECRET-SENTINEL')


class TestOfficialRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.directory = self.root / '.asterion-private/prime-p7-official/run-1'
        self.directory.mkdir(parents=True)
        self.path = self.directory / 'official-recovery.json'
        self.path.write_text(json.dumps(record()))
        self.path.chmod(0o600)

    def recover(self, payload=None):
        response = io.BytesIO(json.dumps(card() if payload is None else payload).encode())
        with patch('asterion.applications.prime.p7.official_recovery._fetch', return_value=response.getvalue()) as fetch:
            result = recover_official_receipt(self.path)
        self.assertEqual(fetch.call_args.args, ('card-1',))
        return result

    def test_receipt_is_bound_redacted_private_and_no_overwrite(self):
        result = self.recover()
        self.assertEqual(result.played_runs, 1)
        receipt = self.directory / 'official-receipt.json'
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(receipt.read_text()), result.to_dict())
        self.assertNotIn('SECRET-SENTINEL', receipt.read_text())
        self.assertNotIn('private-guid', receipt.read_text())
        with self.assertRaisesRegex(OfficialError, '^official recovery unavailable$'):
            self.recover()

    def test_remote_identity_catalog_and_zero_placeholder_rejected(self):
        mutations = [lambda d: d.update(card_id='other'),
                     lambda d: d.update(competition_mode=False),
                     lambda d: d.update(score=float('nan')),
                     lambda d: d['environments'].pop(),
                     lambda d: d['environments'].append(deepcopy(d['environments'][0])),
                     lambda d: d['environments'][0]['runs'][0].update(guid='other'),
                     lambda d: d['environments'][0]['runs'][0].update(actions=True),
                     lambda d: d['environments'][1]['runs'][0].update(actions=1),
                     lambda d: d['environments'][1]['runs'][0].update(resets=1),
                     lambda d: d['environments'][1]['runs'][0].update(state='WIN')]
        for mutation in mutations:
            with self.subTest(mutation=mutations.index(mutation)):
                value = card()
                mutation(value)
                with self.assertRaisesRegex(OfficialError, '^official recovery unavailable$'):
                    self.recover(value)
                self.assertFalse((self.directory / 'official-receipt.json').exists())

    def test_invalid_local_record_rejected_before_http(self):
        for change in ({'normal_close_confirmed':False}, {'aborted':True},
                       {'card_id':'../escape'}, {'unattempted_game_ids':['aa-v1']},
                       {'selected_game_ids':['bb-v1']}, {'game_ids':['bb-v1','aa-v1']}):
            with self.subTest(change=change):
                self.path.write_text(json.dumps({**record(), **change}))
                with patch('asterion.applications.prime.p7.official_recovery._fetch') as fetch:
                    with self.assertRaises(OfficialError):
                        recover_official_receipt(self.path)
                    fetch.assert_not_called()

    def test_arbitrary_path_symlink_and_receipt_symlink_rejected(self):
        outside = self.root / 'official-recovery.json'
        outside.write_text(json.dumps(record()))
        link = self.directory / 'alternate.json'
        link.symlink_to(self.path)
        for path in (outside, link):
            with self.assertRaises(OfficialError):
                recover_official_receipt(path)
        original = self.path.read_text()
        self.path.unlink()
        self.path.symlink_to(outside)
        with self.assertRaises(OfficialError):
            recover_official_receipt(self.path)
        self.path.unlink()
        self.path.write_text(original)
        (self.directory / 'official-receipt.json').symlink_to(outside)
        with self.assertRaises(OfficialError):
            self.recover()
        self.assertEqual(json.loads(outside.read_text()), record())

    def test_transport_is_get_fixed_host_no_redirects(self):
        from asterion.applications.prime.p7.official_recovery import _fetch
        with patch('urllib.request.build_opener') as build:
            build.return_value.open.return_value.__enter__.return_value.read.return_value = b'{}'
            self.assertEqual(_fetch('card-1'), b'{}')
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.full_url, 'https://arcprize.org/api/v3/scorecards/card-1')
        self.assertIsNone(request.data)
