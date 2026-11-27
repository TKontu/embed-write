"""R231/A3 G-01 chain rehearsal: intake -> annotate (first + repeat) -> g01_draft, as a chain.

Each stage consumes exactly the files the previous one wrote, through the command lines intake
prints in ``next_steps``. Everything here is synthetic and LLM-built: the corpus is generated in a
temp dir, the "expert" labels are a scripted deterministic function of the sentence id (no expert
judged anything), the LLM pre-labels come from a loopback stub of the OpenAI-compatible
``/v1/chat/completions`` endpoint (no model runs), and the g01 preregistration is a synthetic
fixture record under a temp root. Never gate evidence (D-011).

Blind mode (R147 / D-009 item 3, as the code defines it): labels written while a pre-label was
shown carry ``prelabel`` and ``g01_inputs.build_config`` excludes them by default. Intake's
printed first-pass annotate line is blind (no ``--prelabels``), as is the repeat line, so the
rehearsal runs the printed first-pass line exactly as printed. Both are asserted below.
"""
import hashlib
import http.server
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from experiments import annotate
from service.annotation_store import AnnotationStore
from service.genre import load_genre
from tests.test_preregistration import fixture_record

ROOT = Path(__file__).resolve().parent.parent
GENRE = ROOT / "examples" / "demo" / "genre.json"
MOVES = ["context", "gap", "method", "finding"]
KEYS = {m: str(i) for i, m in enumerate(MOVES, 1)}


def _h(text):
    return int(hashlib.sha256(text.encode()).hexdigest(), 16)


def expert_label(sid):
    """Scripted synthetic first-pass label: a deterministic function of the sentence id."""
    return MOVES[_h(sid) % 4]


def repeat_label(sid):
    """Scripted synthetic repeat label: the first-pass label, changed for every third id class."""
    return MOVES[(_h(sid) + (_h("r" + sid) % 3 == 0)) % 4]


class Stub(http.server.BaseHTTPRequestHandler):
    """Loopback OpenAI-compatible stub: replies a move chosen from a hash of the prompt."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        content = MOVES[_h(body["messages"][-1]["content"]) % 4]
        out = json.dumps({"choices": [{"index": 0, "message": {"role": "assistant",
                                                               "content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


def synthetic_corpus(root, n_docs=12):
    """Clearly synthetic reports (LLM-built template text, invented facts)."""
    root.mkdir()
    for d in range(n_docs):
        parts = [f"# Synthetic chain report {d} - not real data", ""]
        for sec in ("Context", "Method", "Finding"):
            parts += [f"## {sec}", ""]
            parts.append(" ".join(f"Synthetic {sec.lower()} sentence {k} of report {d} "
                                  f"names invented item {d * 10 + k}." for k in range(4)))
            parts.append("")
        (root / f"synthetic-chain-{d:02d}.md").write_text("\n".join(parts), encoding="utf-8")


class G01ChainRehearsalTest(unittest.TestCase):
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
        # Hermetic: a cwd that is not the repo, imports via PYTHONPATH, no model dir, and an
        # empty temp section-corrections dir (never the real edit-log/).
        self.env = {**os.environ, "PYTHONPATH": str(ROOT),
                    "SECTION_CORRECTIONS_DIR": str(self.tmp / "section-corrections")}
        self.env.pop("EMBED_WRITE_MODEL_DIR", None)
        for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                  "all_proxy", "ALL_PROXY"):
            self.env.pop(k, None)
        self.env["NO_PROXY"] = self.env["no_proxy"] = "127.0.0.1,localhost"

    def cli(self, argv, stdin=""):
        assert argv[:2] == ["python", "-m"], argv
        return subprocess.run([sys.executable, *argv[1:]], input=stdin, capture_output=True,
                              text=True, cwd=self.tmp, env=self.env, timeout=60)

    def annotate_cli(self, argv, label_of):
        """Drive the annotate CLI over stdin with the scripted label for each shown sentence."""
        opt = dict(zip(argv[3::2], argv[4::2]))
        manifest = json.loads(Path(opt["--manifest"]).read_text(encoding="utf-8"))
        genre = load_genre(opt["--genre"])
        pass_name = opt.get("--pass", "first")
        items = list(annotate.resolve_items(
            manifest, annotate.load_documents(Path(opt["--corpus"]), manifest), genre,
            only=annotate.pass_ids(manifest, pass_name)))
        keys = "".join(KEYS[label_of(it["sentence_id"])] + "\n" for it in items)
        r = self.cli(argv, stdin=keys)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"{len(items)} labels written this session", r.stdout)
        return manifest, genre, items

    def test_chain(self):
        t0 = time.monotonic()
        src, out = self.tmp / "src", self.tmp / "out"
        synthetic_corpus(src)
        r = self.cli(["python", "-m", "experiments.intake", "run", str(src), str(out),
                      "--genre", str(GENRE), "--model-url", self.url,
                      "--model-name", "stub-model"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rep = json.loads((out / "intake_report.json").read_text(encoding="utf-8"))
        self.assertEqual(rep["steps"]["prelabel"]["status"], "ok")
        steps = [shlex.split(c) for c in rep["next_steps"]]
        first_line, repeat_line, draft_line = steps[:3]
        self.assertEqual(first_line[:3], ["python", "-m", "experiments.annotate"])
        self.assertEqual(draft_line[:3], ["python", "-m", "experiments.g01_draft"])

        # (c) intake's printed first line is blind, run exactly as printed.
        self.assertNotIn("--prelabels", first_line)
        self.assertNotIn("--prelabels", repeat_line)
        manifest, genre, first_items = self.annotate_cli(first_line, expert_label)
        _, _, repeat_items = self.annotate_cli(repeat_line, repeat_label)
        n_first, n_repeat = len(manifest["entries"]), len(manifest["repeat"])
        self.assertEqual(len(first_items), n_first)
        self.assertEqual(len(repeat_items), n_repeat)
        self.assertGreater(n_repeat, 1)
        store = AnnotationStore(dict(zip(first_line[3::2], first_line[4::2]))["--store"])
        self.assertFalse(any("prelabel" in rec for rec in store.read(genre)))

        # (b) g01_draft from intake's own line, on a temp synthetic preregistration root.
        prereg = self.tmp / "prereg"
        prereg.mkdir()
        (prereg / "g01.json").write_text(json.dumps({**fixture_record(), "gate": "g01"}),
                                         encoding="utf-8")
        stem = Path(dict(zip(draft_line[3::2], draft_line[4::2]))["--out"])
        self.assertTrue(stem.is_relative_to(self.tmp), stem)
        r = self.cli(draft_line + ["--n-resamples", "50", "--preregistration-root", str(prereg)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = json.loads(Path(str(stem) + ".json").read_text(encoding="utf-8"))
        res = run["result"]
        pairing = res["pairing"]
        self.assertEqual(pairing["expert_llm"],
                         {"paired": n_first, "only_expert": 0, "only_llm": 0})
        self.assertEqual(pairing["expert_self"],
                         {"paired": n_repeat, "only_expert": n_first - n_repeat,
                          "only_repeat": 0})
        m = {x["metric"]: x for x in res["metrics"]}
        self.assertEqual(m["kappa_expert_llm"]["n"], n_first)
        self.assertEqual(m["kappa_expert_self"]["n"], n_repeat)
        for name in ("kappa_expert_llm", "kappa_expert_self"):
            self.assertIsInstance(m[name]["value"], float, name)
            self.assertLess(m[name]["value"], 1, name)  # scripted: neither 0 nor perfect
            self.assertNotEqual(m[name]["value"], 0, name)
        md = Path(str(stem) + ".md").read_text(encoding="utf-8")
        self.assertIn("DRAFT", md)
        self.assertIn("Verdict: owed to the expert", md)
        self.assertLess(time.monotonic() - t0, 60)
        print(f"\nrehearsal: first={n_first} repeat={n_repeat} "
              f"kappa_el={m['kappa_expert_llm']['value']} "
              f"kappa_self={m['kappa_expert_self']['value']}", file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
