import inspect
import json
import tempfile
import unittest
from pathlib import Path

from experiments import corpus, runner
from experiments.gates import sample

CONFIG = {"model_versions": {"embedder": "synthetic-embed@1.0", "llm": "synthetic-llm@2.3"}}


def _strip_timestamp(serialized):
    data = json.loads(serialized)
    data["manifest"].pop("timestamp")
    return json.dumps(data, sort_keys=True)


class RunnerTest(unittest.TestCase):
    def test_same_seed_gives_identical_output(self):
        a = runner.serialize(runner.run_gate(sample.run, seed=42, config=CONFIG))
        b = runner.serialize(runner.run_gate(sample.run, seed=42, config=CONFIG))
        self.assertEqual(_strip_timestamp(a), _strip_timestamp(b))

    def test_different_seed_gives_different_numbers(self):
        a = runner.run_gate(sample.run, seed=1, config=CONFIG)
        b = runner.run_gate(sample.run, seed=2, config=CONFIG)
        self.assertNotEqual(a["result"], b["result"])

    def test_manifest_fields(self):
        m = runner.run_gate(sample.run, seed=7, config=CONFIG)["manifest"]
        self.assertEqual(m["seed"], 7)
        self.assertEqual(m["model_versions"], CONFIG["model_versions"])
        for key in ("python_version", "platform", "machine", "processor", "cpu_count", "timestamp"):
            self.assertIn(key, m)
        self.assertEqual(m["gate"], "sample")

    def test_seed_required_and_int(self):
        with self.assertRaises(TypeError):
            runner.run_gate(sample.run, seed="42", config=CONFIG)


class CorpusTest(unittest.TestCase):
    def test_streams_sorted_lazily(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "sub").mkdir()
            for name, text in [("b.md", "B"), ("a.md", "A"), ("sub/c.md", "C"), ("x.txt", "no")]:
                (root / name).write_text(text, encoding="utf-8")
            gen = corpus.iter_documents(root)
            self.assertTrue(inspect.isgenerator(gen))
            first = next(gen)
            self.assertEqual(first.path.name, "a.md")
            # lazy: a file added after iteration started but before reaching it is not pre-read
            (root / "b.md").write_text("B2", encoding="utf-8")
            rest = list(gen)
            self.assertEqual([doc.text for doc in [first] + rest], ["A", "B2", "C"])

    def test_missing_dir_raises_on_iteration(self):
        with self.assertRaises(FileNotFoundError):
            list(corpus.iter_documents("/nonexistent/corpus/dir"))


if __name__ == "__main__":
    unittest.main()
