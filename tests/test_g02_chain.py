"""R232/A1 G-02 chain rehearsal: g02_notes -> g02_generate -> g02_session -> blind_ui -> g02_draft.

Each stage runs as a subprocess on exactly the files the previous one wrote, through the command
line it printed (``next:`` / ``serve:`` / ``after judging:``). Everything here is synthetic and
LLM-built: the corpus is invented template text in a temp dir, the genre is the LLM-built
``tests/fixtures/genre_synthetic_sections.json``, every model reply comes from a loopback stub of
the OpenAI-compatible ``/v1/chat/completions`` endpoint (no model runs), the "judge" choices are a
scripted deterministic function of the pair_id recorded through blind_ui's own HTTP path (nobody
judged anything), and the g02 preregistration is a synthetic fixture record under a temp root.
Never gate evidence (D-011).

The exemplar pool comes from ``experiments.g02_pool`` (R233/A1), run through the ``pool:`` line
g02_notes prints; its output is the ``--pool`` of the printed g02_generate line, and the test checks
it holds training-split reports only.
"""
import hashlib
import http.client
import http.server
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

from experiments import blind_ui
from tests.test_preregistration import fixture_record

ROOT = Path(__file__).resolve().parent.parent
GENRE = ROOT / "tests" / "fixtures" / "genre_synthetic_sections.json"


def _h(text):
    return int(hashlib.sha256(text.encode()).hexdigest(), 16)


def reply_for(prompt):
    if prompt.startswith("Score how well"):
        return str(_h(prompt) % 10)
    if prompt.startswith("Extract the content"):
        return f"- synthetic fact {_h(prompt) % 997}\n- another synthetic fact"
    return f"Synthetic generated section text {_h(prompt) % 99991}."


def winner_arm(pair_id, arms):
    """Scripted synthetic choice: a deterministic function of pair_id (repeats agree)."""
    return sorted(arms)[_h(pair_id) % 2]


class Stub(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        content = reply_for(body["messages"][-1]["content"])
        out = json.dumps({"choices": [{"index": 0, "message": {"role": "assistant",
                                                               "content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


def synthetic_corpus(root, n_docs=16):
    """Clearly synthetic reports (LLM-built template text, invented facts)."""
    root.mkdir()
    for d in range(n_docs):
        parts = [f"# Synthetic G-02 chain report {d} - not real data", ""]
        for sec in ("Findings", "Conclusions"):
            parts += [f"## {sec}", ""]
            parts.append(" ".join(f"Synthetic {sec.lower()} sentence {k} of report {d} names "
                                  f"invented item {d * 10 + k}." for k in range(6)))
            parts.append("")
        (root / f"synthetic-g02-{d:02d}.md").write_text("\n".join(parts), encoding="utf-8")


def printed(stdout, prefix):
    lines = [ln[len(prefix):].strip() for ln in stdout.splitlines() if ln.startswith(prefix)]
    assert len(lines) == 1, (prefix, stdout)
    return shlex.split(lines[0])


def opts(argv):
    return dict(zip(argv[3::2], argv[4::2]))


class G02ChainRehearsalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.env = {**os.environ, "PYTHONPATH": str(ROOT)}
        self.env.pop("EMBED_WRITE_MODEL_DIR", None)
        for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                  "all_proxy", "ALL_PROXY"):
            self.env.pop(k, None)
        self.env["NO_PROXY"] = self.env["no_proxy"] = "127.0.0.1,localhost"

    def cli(self, argv, ok=True):
        self.assertEqual(argv[:2], ["python", "-m"], argv)
        r = subprocess.run([sys.executable, *argv[1:]], capture_output=True, text=True,
                           cwd=self.tmp, env=self.env, timeout=60)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def judge(self, serve_line):
        """Scripted choices through blind_ui's own HTTP recording path."""
        self.assertEqual(serve_line[:3], ["python", "-m", "experiments.blind_ui"])
        session_path, choices_path = serve_line[3:5]
        server = blind_ui.make_server(session_path, choices_path)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        try:
            n = 0
            while True:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                conn.request("GET", "/")
                page = conn.getresponse().read().decode()
                if "All comparisons recorded" in page:
                    break
                nonce = re.search(r'name="nonce" value="([^"]+)"', page).group(1)
                item = server.state.pending[0]
                p = item.presentation
                arm = winner_arm(p.pair_id, (p._left_arm, p._right_arm))
                choice = "left" if arm == p._left_arm else "right"
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                conn.request("POST", "/", urlencode({"nonce": nonce, "choice": choice}),
                             {"Content-Type": "application/x-www-form-urlencoded"})
                self.assertEqual(conn.getresponse().status, 303)
                n += 1
        finally:
            server.shutdown()
            server.server_close()
        return n

    def test_chain(self):
        t0 = time.monotonic()
        corpus, work = self.tmp / "corpus", self.tmp / "work"
        synthetic_corpus(corpus)
        work.mkdir()
        notes, originals = work / "notes.jsonl", work / "originals.jsonl"

        # Stage 1: g02_notes (the operator's first command; its inputs are the corpus + genre).
        r = self.cli(["python", "-m", "experiments.g02_notes", "--corpus", str(corpus),
                      "--genre", str(GENRE), "--split-seed", "0", "--test-fraction", "0.5",
                      "--n", "6", "--min-words", "20", "--out", str(notes),
                      "--sections-out", str(originals), "--model-url", self.url,
                      "--model-name", "stub-model"])
        n_sections = json.loads(r.stdout.strip().splitlines()[-1])["selected"]
        self.assertEqual(n_sections, 6)
        gen_line = printed(r.stdout, "next:")
        self.assertEqual(gen_line[:3], ["python", "-m", "experiments.g02_generate"])
        o = opts(gen_line)
        self.assertEqual(o["--notes"], str(notes))
        self.assertEqual(o["--originals"], str(originals))
        self.assertEqual(o["--expected-sections"], str(n_sections))
        self.assertEqual(o["--model-url"], self.url)
        # Stage 1b: g02_pool exactly as printed; its output is the generate line's --pool.
        pool_line = printed(r.stdout, "pool:")
        self.assertEqual(pool_line[:3], ["python", "-m", "experiments.g02_pool"])
        self.assertEqual(opts(pool_line)["--out"], o["--pool"])
        self.cli(pool_line)
        pool_reports = {json.loads(l)["report_id"]
                        for l in Path(o["--pool"]).read_text(encoding="utf-8").splitlines()}
        note_reports = {json.loads(l)["report_id"]
                        for l in notes.read_text(encoding="utf-8").splitlines()}
        self.assertTrue(pool_reports)
        self.assertFalse(pool_reports & note_reports)

        # Stage 2: g02_generate exactly as printed.
        r = self.cli(gen_line)
        summary = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(summary["complete"], summary)
        session_line = printed(r.stdout, "next:")
        self.assertEqual(session_line[:3], ["python", "-m", "experiments.g02_session"])
        so = opts(session_line)
        self.assertEqual(so["--generations"], o["--out"])
        self.assertEqual(so["--originals"], str(originals))

        # Stage 3: g02_session exactly as printed.
        r = self.cli(session_line)
        serve_line = printed(r.stdout, "serve:")
        draft_line = printed(r.stdout, "after judging:")
        self.assertEqual(serve_line[3:5], [so["--out"], so["--choices"]])

        # Stage 4: blind_ui, scripted synthetic choices over HTTP.
        items = len(json.loads(Path(so["--out"]).read_text(encoding="utf-8")))
        self.assertEqual(self.judge(serve_line), items)

        # Stage 5: g02_draft as printed, on a temp synthetic preregistration root.
        self.assertEqual(draft_line[:3], ["python", "-m", "experiments.g02_draft"])
        do = opts(draft_line)
        self.assertEqual((do["--session"], do["--choices"]), (so["--out"], so["--choices"]))
        self.assertEqual(do["--text-model"], "stub-model")
        prereg = self.tmp / "prereg"
        prereg.mkdir()
        (prereg / "g02.json").write_text(json.dumps({**fixture_record(), "gate": "g02", "threshold": "0.70"}),
                                         encoding="utf-8")
        stem = Path(do["--out"])
        self.assertTrue(stem.is_relative_to(self.tmp), stem)
        self.cli(draft_line + ["--n-resamples", "50", "--preregistration-root", str(prereg)])
        res = json.loads(Path(str(stem) + ".json").read_text(encoding="utf-8"))["result"]
        for name in ("A_vs_C", "A_vs_B", "C_vs_original"):
            self.assertEqual(res["comparisons"][name]["n"], n_sections, name)
        ac = res["comparisons"]["A_vs_C"]
        self.assertGreater(ac["win_rate"], 0)
        self.assertLess(ac["win_rate"], 1)
        self.assertEqual(len(ac["interval"]), 2)
        self.assertTrue(all(isinstance(x, (int, float)) for x in ac["interval"]))
        self.assertTrue(res["completeness"]["complete"])
        self.assertGreater(res["consistency"]["n"], 0)  # repeats were judged
        self.assertEqual(res["consistency"]["rate"], 1)  # scripted: repeats agree
        md = Path(str(stem) + ".md").read_text(encoding="utf-8")
        self.assertIn("DRAFT", md)
        self.assertIn("Verdict: owed to the expert", md)
        self.assertLess(time.monotonic() - t0, 60)
        print(f"\nrehearsal: sections={n_sections} items={items} "
              f"A_vs_C={ac['win_rate']} {ac['interval']}", file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
