import contextlib
import io
import json
import os
import random
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request

from experiments import blind_ui
from experiments.blind_session import build_session, save_session

ARMS = ('ZebraArmQx', 'MarmotArmVv', 'OtterArmJk')


def synthetic_session(path):
    a, b, c = ARMS
    comps = {
        'cmpAC': [(f'pairAC{i}', f'Synthetic draft one {i}.', a, f'Synthetic draft two {i}.', c)
                  for i in range(4)],
        'cmpBC': [(f'pairBC{i}', f'Synthetic note three {i}.', b, f'Synthetic note four {i}.', c)
                  for i in range(3)],
    }
    session = build_session(comps, repeat_fraction=0.3, min_gap=2, rng=random.Random(7))
    save_session(path, session)
    return session


class BlindUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.session_path = os.path.join(self.tmp.name, 'session.json')
        self.choices_path = os.path.join(self.tmp.name, 'choices.jsonl')
        self.session = synthetic_session(self.session_path)
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self.tmp.cleanup()

    def start(self):
        server = blind_ui.make_server(self.session_path, self.choices_path, port=0)
        self.servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return f'http://127.0.0.1:{server.server_address[1]}/'

    def get(self, url):
        with urllib.request.urlopen(url) as response:
            headers = '\n'.join(f'{k}: {v}' for k, v in response.getheaders())
            return headers, response.read().decode('utf-8')

    def post(self, url, nonce, choice, reason=''):
        data = urllib.parse.urlencode(dict(nonce=nonce, choice=choice, reason=reason)).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=data)) as response:
            return response.read().decode('utf-8')

    @staticmethod
    def nonce(body):
        marker = 'name="nonce" value="'
        start = body.index(marker) + len(marker)
        return body[start:body.index('"', start)]

    def records(self):
        if not os.path.exists(self.choices_path):
            return []
        with open(self.choices_path, encoding='utf-8') as source:
            return [json.loads(line) for line in source if line.strip()]

    def forbidden(self):
        words = set(ARMS) | {'repeat'}
        for item in self.session:
            p = item.presentation
            words |= {p.key, p.pair_id, item.item_id, item.comparison}
        return words

    def test_no_metadata_in_any_get_and_records_each_item(self):
        url = self.start()
        forbidden = self.forbidden()
        choices = ['left', 'right', 'tie']
        for n, item in enumerate(self.session):
            headers, body = self.get(url)
            for word in forbidden:
                self.assertNotIn(word, body, word)
                self.assertNotIn(word, headers, word)
            self.assertIn(item.presentation.left, body)
            self.post(url, self.nonce(body), choices[n % 3], 'r')
        headers, body = self.get(url)
        self.assertIn('All comparisons recorded', body)
        for word in forbidden:
            self.assertNotIn(word, body)
        records = self.records()
        self.assertEqual([r['item_id'] for r in records], [i.item_id for i in self.session])
        for n, (record, item) in enumerate(zip(records, self.session)):
            p = item.presentation
            choice = choices[n % 3]
            expected = {'left': p._left_arm, 'right': p._right_arm, 'tie': 'tie'}[choice]
            self.assertEqual(record['winner'], expected)
            self.assertEqual(record['comparison'], item.comparison)

    def test_stale_nonce_records_nothing(self):
        url = self.start()
        _, body = self.get(url)
        nonce = self.nonce(body)
        self.post(url, 'not-the-nonce', 'left')
        self.assertEqual(self.records(), [])
        self.post(url, nonce, 'left')
        self.post(url, nonce, 'right')  # duplicate submit of the same page
        self.assertEqual(len(self.records()), 1)

    def test_invalid_choice_records_nothing(self):
        url = self.start()
        _, body = self.get(url)
        self.post(url, self.nonce(body), 'ZebraArmQx')
        self.assertEqual(self.records(), [])

    def test_resume_skips_recorded_items(self):
        url = self.start()
        for _ in range(2):
            _, body = self.get(url)
            self.post(url, self.nonce(body), 'left')
        old = self.servers.pop()
        old.shutdown()
        old.server_close()
        url = self.start()
        _, body = self.get(url)
        self.assertIn(self.session[2].presentation.left, body)
        self.post(url, self.nonce(body), 'tie')
        self.assertEqual([r['item_id'] for r in self.records()],
                         [i.item_id for i in self.session[:3]])

    def test_torn_final_line_skipped_and_next_append_on_fresh_line(self):
        first = self.session[0].item_id
        with open(self.choices_path, 'w', encoding='utf-8') as out:
            out.write(json.dumps({'item_id': first, 'winner': 'tie'}) + '\n')
            out.write('{"item_id": "torn')
        url = self.start()
        _, body = self.get(url)
        self.assertIn(self.session[1].presentation.left, body)
        self.post(url, self.nonce(body), 'left')
        with open(self.choices_path, encoding='utf-8') as source:
            lines = source.read().splitlines()
        self.assertEqual(lines[1], '{"item_id": "torn')
        self.assertEqual(json.loads(lines[2])['item_id'], self.session[1].item_id)

    def test_malformed_middle_line_reported_and_skipped(self):
        first, second = self.session[0].item_id, self.session[1].item_id
        with open(self.choices_path, 'w', encoding='utf-8') as out:
            out.write('not json at all\n')
            out.write(json.dumps({'winner': 'tie'}) + '\n')
            out.write(json.dumps({'item_id': first, 'winner': 'tie'}) + '\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            url = self.start()
        self.assertIn('line 1', err.getvalue())
        self.assertIn('line 2', err.getvalue())
        _, body = self.get(url)
        self.assertIn(self.session[1].presentation.left, body)
        self.assertNotIn(second, body)

    def test_second_server_on_same_choices_fails_fast(self):
        self.start()
        with self.assertRaises(blind_ui.ChoicesLocked) as ctx:
            blind_ui.make_server(self.session_path, self.choices_path, port=0)
        self.assertIn(self.choices_path, str(ctx.exception))
        old = self.servers.pop()
        old.shutdown()
        old.server_close()
        self.start()  # lock released on close

    def test_non_loopback_host_refused(self):
        for host in ('0.0.0.0', '192.168.1.5', 'example.org', ''):
            with self.assertRaises(ValueError):
                blind_ui.make_server(self.session_path, self.choices_path, host=host, port=0)


if __name__ == '__main__':
    unittest.main()
