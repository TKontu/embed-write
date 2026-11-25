"""Local blind-comparison front end (X-04) over a saved BJ-02 session.

Production caller of blind_session.load_session and record_session_choice.
Serves one pair at a time on 127.0.0.1 only (I9: offline, local); the browser
sees only blind_pair.render_html output plus an opaque per-page nonce and a
metadata-free keyboard script. The current item is tracked on the server; a
POST is accepted only with the current nonce, so stale or duplicate submits
record nothing. Items already in CHOICES.jsonl are skipped on restart; a torn
final line is skipped (the next append starts on a fresh line) and any other
malformed line is reported on stderr and skipped. An exclusive flock on the
CHOICES.jsonl.lock sidecar makes a second server on the same file fail fast.

Usage: python3 -m experiments.blind_ui SESSION.json CHOICES.jsonl [--port N]
"""

import argparse
import fcntl
import json
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from experiments import blind_pair
from experiments.blind_session import load_session, record_session_choice

LOOPBACK = '127.0.0.1'
_MAX_BODY = 64 * 1024

_KEYS = '''<p>Keys: 1 = Left, 2 = Right, 3 = Tie (outside the reason box).</p>
<script>
document.addEventListener('keydown', function (e) {
  if (e.target.tagName === 'TEXTAREA') return;
  var v = {'1': 'left', '2': 'right', '3': 'tie'}[e.key];
  if (!v) return;
  document.querySelector('input[name=choice][value=' + v + ']').checked = true;
  document.querySelector('form').submit();
});
</script>
'''

_DONE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Done</title></head>
<body><h1>All comparisons recorded</h1><p>You may close this window.</p></body></html>'''


class ChoicesLocked(RuntimeError):
    """Another process holds the CHOICES file."""


def _lock_choices(path):
    lock_path = path + '.lock'
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise ChoicesLocked(f'{path} is in use by another blind_ui server '
                            f'(lock {lock_path}); stop it first') from None
    return fd


def _recorded_ids(path):
    """Return recorded item ids; skip a torn final line, report other bad lines.

    A file not ending in a newline gets one appended so the next record starts
    on a fresh line. Call only while holding the CHOICES lock.
    """
    done = set()
    try:
        with open(path, 'rb') as source:
            data = source.read()
    except FileNotFoundError:
        return done
    lines = data.split(b'\n')
    torn = not data.endswith(b'\n') and data != b''
    for number, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            item_id = json.loads(raw.decode('utf-8'))['item_id']
            if not isinstance(item_id, str):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            if torn and number == len(lines):
                print(f'{path}: line {number}: torn final line skipped', file=sys.stderr)
            else:
                print(f'{path}: line {number}: malformed record skipped', file=sys.stderr)
            continue
        done.add(item_id)
    if torn:
        with open(path, 'ab') as out:
            out.write(b'\n')
    return done


class _State:
    def __init__(self, session_path, choices_path):
        self.session = load_session(session_path)
        self.choices_path = choices_path
        self.lock_fd = _lock_choices(choices_path)
        try:
            done = _recorded_ids(choices_path)
        except BaseException:
            self.close()
            raise
        self.pending = [item for item in self.session if item.item_id not in done]
        self.nonce = None
        self.lock = threading.Lock()

    def page(self):
        with self.lock:
            if not self.pending:
                return _DONE
            if self.nonce is None:
                self.nonce = secrets.token_urlsafe(16)
            html = blind_pair.render_html(self.pending[0].presentation)
            hidden = f'<input type="hidden" name="nonce" value="{self.nonce}">\n'
            html = html.replace('<form method="post">\n', '<form method="post">\n' + hidden, 1)
            return html.replace('</body>', _KEYS + '</body>', 1)

    def submit(self, nonce, choice, reason):
        """Record a choice for the current item; return True if recorded."""
        with self.lock:
            if (not self.pending or self.nonce is None or nonce is None
                    or not secrets.compare_digest(nonce, self.nonce)
                    or choice not in ('left', 'right', 'tie')):
                return False
            item = self.pending[0]
            record_session_choice(self.choices_path, self.session, item.item_id, choice,
                                  reason or None)
            self.pending.pop(0)
            self.nonce = None
            return True

    def close(self):
        if self.lock_fd is not None:
            os.close(self.lock_fd)  # releases the flock
            self.lock_fd = None


def _handler(state):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'blind-ui'
        sys_version = ''

        def log_message(self, *args):
            pass

        def _send(self, status, body=b'', location=None):
            self.send_response(status)
            if location:
                self.send_header('Location', location)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != '/':
                return self._send(404)
            self._send(200, state.page().encode('utf-8'))

        def do_POST(self):
            if self.path != '/':
                return self._send(404)
            length = int(self.headers.get('Content-Length') or 0)
            if length > _MAX_BODY:
                return self._send(413)
            form = parse_qs(self.rfile.read(length).decode('utf-8', 'replace'))
            first = lambda name: (form.get(name) or [None])[0]
            state.submit(first('nonce'), first('choice'), first('reason'))
            self._send(303, location='/')

    return Handler


def make_server(session_path, choices_path, host=LOOPBACK, port=0):
    """Build (not start) the server; any host other than 127.0.0.1 is refused."""
    if host != LOOPBACK:
        raise ValueError(f'blind_ui binds to {LOOPBACK} only')
    state = _State(session_path, choices_path)
    try:
        server = _Server((LOOPBACK, port), _handler(state))
    except BaseException:
        state.close()
        raise
    server.state = state
    return server


class _Server(ThreadingHTTPServer):
    state = None

    def server_close(self):
        super().server_close()
        if self.state is not None:
            self.state.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('session')
    parser.add_argument('choices')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        server = make_server(args.session, args.choices, port=args.port)
    except ChoicesLocked as error:
        sys.exit(f'blind_ui: {error}')
    print(f'Open http://{LOOPBACK}:{server.server_address[1]}/ (Ctrl-C to stop)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
