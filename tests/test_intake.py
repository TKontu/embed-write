"""CO-12 intake: chain, determinism, flags, isolation and the privacy rule (synthetic demo data)."""
import contextlib
import io
import os
import json
import re
import shutil
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from experiments import intake
from service.segment import segment_sentences

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "examples" / "demo"
GENRE = str(DEMO / "genre.json")
SECRET = "Quarantined zebra paragraphs whisper confidential turbine numbers tonight"


class FakeModel:
    model_id = "fake"

    def __init__(self):
        self.calls = 0

    def __call__(self, prompt, temperature=None):
        self.calls += 1
        return "context" if self.calls % 2 else "not a label"


class IntakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.src = self.tmp / "src"
        self.src.mkdir()
        for p in sorted(DEMO.glob("*.md")):
            shutil.copy(p, self.src / p.name)
        self.out = self.tmp / "out"

    def run_intake(self, *extra, model=None):
        argv = ["run", str(self.src), str(self.out), "--genre", GENRE, "--force", *extra]
        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            code = intake.main(argv, model=model)
        text = (self.out / intake.REPORT_NAME).read_text(encoding="utf-8")
        return code, json.loads(text), text, so.getvalue() + se.getvalue()

    def assert_private(self, *texts):
        words = []
        for p in sorted(self.src.iterdir()):
            if p.suffix in (".md", ".txt"):
                for s in segment_sentences(p.read_text(encoding="utf-8")):
                    w = re.findall(r"\w+", s)
                    words.extend(" ".join(w[i:i + 4]) for i in range(len(w) - 3))
        words.append(" ".join(SECRET.split()[:4]))
        self.assertTrue(words)
        for blob in texts:
            flat = " ".join(re.findall(r"\w+", blob))
            for gram in words:
                self.assertNotIn(gram, flat)

    def test_full_run_on_demo(self):
        code, rep, text, printed = self.run_intake()
        self.assertEqual(code, 0)
        st = {k: v["status"] for k, v in rep["steps"].items()}
        self.assertEqual(st, {"ingest": "ok", "conversion_quality": "ok", "corpus_stats": "ok",
                              "metadata": "skipped", "annotation_sample": "ok",
                              "prelabel": "skipped", "discovery": "skipped"})
        self.assertEqual(rep["steps"]["metadata"]["reason"], intake.NO_METADATA)
        self.assertEqual(rep["steps"]["prelabel"]["reason"], intake.NO_MODEL)
        self.assertEqual(rep["steps"]["ingest"]["counts"]["documents"]["ok"], 3)
        self.assertGreater(rep["steps"]["corpus_stats"]["counts"]["sentences"], 0)
        self.assertGreater(rep["steps"]["annotation_sample"]["counts"]["n_drawn"], 0)
        self.assert_private(text, printed)

    def test_fake_model_prelabels(self):
        code, rep, text, printed = self.run_intake(model=FakeModel())
        self.assertEqual(code, 0)
        pre = rep["steps"]["prelabel"]
        self.assertEqual(pre["status"], "ok")
        n = rep["steps"]["annotation_sample"]["counts"]["n_drawn"]
        self.assertEqual(pre["counts"]["records"], n)
        self.assertEqual(sum(pre["counts"]["by_status"].values()), n)
        self.assertIn("--prelabels", rep["next_steps"][0])
        self.assert_private(text, printed)

    def test_rerun_is_byte_identical(self):
        _, _, first, _ = self.run_intake(model=FakeModel())
        _, _, second, _ = self.run_intake(model=FakeModel())
        self.assertEqual(first, second)

    def test_no_headings_flag_still_exits_zero(self):
        body = " ".join(f"{SECRET} item{i}." for i in range(40))
        (self.src / "flat.txt").write_text(body + "\n", encoding="utf-8")
        code, rep, text, printed = self.run_intake()
        self.assertEqual(code, 0)
        self.assertEqual(rep["steps"]["conversion_quality"]["counts"]["flags"]["no_headings"], 1)
        self.assert_private(text, printed)

    def test_corrupt_docx_counted_failed_privately(self):
        (self.src / "broken.docx").write_text(SECRET, encoding="utf-8")
        code, rep, text, printed = self.run_intake()
        self.assertEqual(code, 0)
        docs = rep["steps"]["ingest"]["counts"]["documents"]
        self.assertEqual((docs["ok"], docs["failed"]), (3, 1))
        self.assertEqual(rep["steps"]["annotation_sample"]["status"], "ok")
        self.assertEqual(rep["steps"]["conversion_quality"]["counts"]["flags"]
                         ["conversion_failed"], 1)
        self.assertNotIn("BadZipFile", text)
        self.assertNotIn("zip", text.lower())
        self.assert_private(text, printed)

    def test_failed_step_blocks_dependents(self):
        for p in self.src.iterdir():
            p.unlink()
        (self.src / "broken.docx").write_text(SECRET, encoding="utf-8")
        code, rep, text, printed = self.run_intake(model=FakeModel())
        self.assertEqual(code, 1)
        steps = rep["steps"]
        self.assertEqual(steps["ingest"]["status"], "failed")
        for name in ("conversion_quality", "corpus_stats", "annotation_sample", "prelabel"):
            self.assertEqual(steps[name]["status"], "skipped")
        self.assertEqual(steps["prelabel"]["reason"], "blocked by annotation_sample")
        self.assertEqual(steps["corpus_stats"]["reason"], "blocked by ingest")
        self.assertEqual(rep["next_steps"], [])
        self.assert_private(text, printed)

    def test_invalid_metadata_fails_by_count_only(self):
        meta = self.tmp / "meta.jsonl"
        meta.write_text(json.dumps({"doc_id": SECRET}) + "\n", encoding="utf-8")
        code, rep, text, printed = self.run_intake("--metadata", str(meta))
        self.assertEqual(code, 1)
        self.assertEqual(rep["steps"]["metadata"]["status"], "failed")
        self.assertGreaterEqual(rep["steps"]["metadata"]["counts"]["errors"], 1)
        self.assertEqual(rep["steps"]["annotation_sample"]["status"], "ok")
        self.assert_private(text, printed)

    def test_next_steps_name_existing_files(self):
        _, rep, _, _ = self.run_intake()
        cmds = rep["next_steps"]
        self.assertEqual(len(cmds), 4)
        ann = cmds[0].split()
        for flag in ("--manifest", "--corpus", "--genre"):
            self.assertTrue(Path(ann[ann.index(flag) + 1]).exists(), flag)
        for cmd in cmds[1:]:
            self.assertTrue(cmd.startswith("cd editor && npm run demo -- --report "))
            path = Path(cmd.split()[-1])
            self.assertTrue((path if path.is_absolute() else REPO / "editor" / path).is_file())

    def test_privacy_check_detects_a_leak(self):
        with self.assertRaises(AssertionError):
            self.assert_private("x " + SECRET)
        demo = next(p for p in self.src.iterdir() if p.suffix == ".md")
        with self.assertRaises(AssertionError):
            self.assert_private(demo.read_text(encoding="utf-8"))

    def test_discovery_skipped_by_default(self):
        _, rep, _, _ = self.run_intake()
        disc = rep["steps"]["discovery"]
        self.assertEqual((disc["status"], disc["reason"]), ("skipped", intake.NO_DISCOVER))
        self.assertFalse((self.out / intake.DISCOVERY_NAME).exists())

    def test_discover_writes_private_report_counts_only(self):
        with mock.patch.dict(os.environ, {intake.MODEL_DIR_ENV: ""}):
            code, rep, text, printed = self.run_intake("--discover")
        self.assertEqual(code, 0)
        disc = rep["steps"]["discovery"]
        self.assertEqual(disc["status"], "ok")
        path = Path(disc["output"])
        self.assertTrue(path.is_file())
        self.assertEqual(path, self.out / intake.DISCOVERY_NAME)
        counts = disc["counts"]
        self.assertGreater(counts["sentences_sampled"], 0)
        self.assertTrue(counts["clusters_per_section_type"])
        self.assertTrue(counts["development_only_embedder"])
        full = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(counts["clusters_per_section_type"],
                         {t: len(c) for t, c in full["clusters"].items()})
        self.assert_private(text, printed)

    def test_discover_rerun_is_byte_identical(self):
        with mock.patch.dict(os.environ, {intake.MODEL_DIR_ENV: ""}):
            _, _, first, _ = self.run_intake("--discover")
            disc_first = (self.out / intake.DISCOVERY_NAME).read_bytes()
            _, _, second, _ = self.run_intake("--discover")
        self.assertEqual(first, second)
        self.assertEqual(disc_first, (self.out / intake.DISCOVERY_NAME).read_bytes())

    def test_discover_bad_model_dir_fails_by_type_name(self):
        with mock.patch.dict(os.environ, {intake.MODEL_DIR_ENV: str(self.tmp / "nomodel")}):
            code, rep, text, printed = self.run_intake("--discover")
        self.assertEqual(code, 1)
        self.assertEqual(rep["steps"]["discovery"]["status"], "failed")
        self.assertEqual(rep["steps"]["discovery"]["reason"], "DiscoveryError")
        self.assert_private(text, printed)

    def test_force_rerun_removes_stale_owned_outputs_only(self):
        with mock.patch.dict(os.environ, {intake.MODEL_DIR_ENV: ""}):
            self.run_intake("--discover")
        self.assertTrue((self.out / intake.DISCOVERY_NAME).exists())
        (self.out / "prelabels.jsonl").write_text("stale\n", encoding="utf-8")
        (self.out / "annotations.jsonl").write_text("keep\n", encoding="utf-8")
        (self.out / "notes.txt").write_text("keep\n", encoding="utf-8")
        code, rep, _, _ = self.run_intake()
        self.assertEqual(code, 0)
        self.assertFalse((self.out / intake.DISCOVERY_NAME).exists())
        self.assertFalse((self.out / "prelabels.jsonl").exists())
        self.assertEqual((self.out / "annotations.jsonl").read_text(), "keep\n")
        self.assertEqual((self.out / "notes.txt").read_text(), "keep\n")

    def test_discover_flags_reach_move_discovery(self):
        with mock.patch.dict(os.environ, {intake.MODEL_DIR_ENV: ""}):
            _, rep, _, _ = self.run_intake("--discover", "--discover-k", "1",
                                           "--discover-sample", "3")
        counts = rep["steps"]["discovery"]["counts"]
        self.assertEqual((counts["k"], counts["max_per_type"]), (1, 3))
        self.assertTrue(all(n <= 1 for n in counts["clusters_per_section_type"].values()))
        full = json.loads((self.out / intake.DISCOVERY_NAME).read_text(encoding="utf-8"))
        for sec in full["sections"].values():
            self.assertLessEqual(sec["sampled"], 3)
        self.assertLessEqual(counts["sentences_sampled"],
                             3 * len(counts["clusters_per_section_type"]))

    def test_discover_defaults_unchanged(self):
        with mock.patch.dict(os.environ, {intake.MODEL_DIR_ENV: ""}):
            _, rep, first, _ = self.run_intake("--discover")
            disc = (self.out / intake.DISCOVERY_NAME).read_bytes()
            _, _, explicit, _ = self.run_intake(
                "--discover", "--discover-k", str(intake.move_discovery.DEFAULT_K),
                "--discover-sample", str(intake.move_discovery.DEFAULT_MAX_PER_TYPE))
        self.assertNotIn("k", rep["steps"]["discovery"]["counts"])
        self.assertEqual(disc, (self.out / intake.DISCOVERY_NAME).read_bytes())
        self.assertNotEqual(first, explicit)  # explicit flags are recorded

    def test_discover_flag_usage_errors(self):
        se = io.StringIO()
        with contextlib.redirect_stderr(se):
            for flag in ("--discover-k", "--discover-sample"):
                self.assertEqual(intake.main(["run", str(self.src), str(self.out), "--genre",
                                              GENRE, "--force", flag, "0"]), 2)

    def test_no_stale_row_id(self):
        for p in (REPO / "experiments" / "intake.py", Path(__file__)):
            self.assertNotIn("CO-" + "11", p.read_text(encoding="utf-8"), p)

    def test_usage_errors(self):
        self.out.mkdir()
        (self.out / "x").write_text("x")
        se = io.StringIO()
        with contextlib.redirect_stderr(se):
            self.assertEqual(intake.main(["run", str(self.src), str(self.out), "--genre",
                                          GENRE]), 2)
            self.assertEqual(intake.main(["run", str(self.tmp / "nope"), str(self.out),
                                          "--genre", GENRE, "--force"]), 2)


if __name__ == "__main__":
    unittest.main()
