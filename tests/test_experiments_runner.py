import inspect
import json
import tempfile
import unittest
from pathlib import Path

from experiments import corpus, runner
from experiments.gates import sample
from experiments.preregistration import PreregistrationError
from tests.test_preregistration import fixture_record

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


class PreregistrationRunnerTest(unittest.TestCase):
    def test_invalid_records_never_call_gate(self):
        cases = [None, "{", json.dumps({**fixture_record(), "confirmed_by": ""}),
                 json.dumps({**fixture_record(), "confirmed_at": ""}),
                 json.dumps({**fixture_record(), "gate": "G-other"})]
        for content in cases:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as root:
                calls = []

                def gate(rng, config):
                    calls.append(True)

                gate.gate_id = "G-test"
                if content is not None:
                    (Path(root) / "G-test.json").write_text(content, encoding="utf-8")
                with self.assertRaises(PreregistrationError):
                    runner.run_gate(gate, seed=1, config=CONFIG, preregistration_root=root)
                self.assertEqual(calls, [])

    def test_confirmed_record_runs_and_is_serialized_reproducibly(self):
        with tempfile.TemporaryDirectory() as root:
            record = fixture_record()
            path = Path(root) / "G-test.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            calls = []

            def gate(rng, config):
                calls.append(True)
                return rng.random()

            gate.gate_id = "G-test"
            a = runner.run_gate(gate, seed=42, config=CONFIG, preregistration_root=root)
            b = runner.run_gate(gate, seed=42, config=CONFIG, preregistration_root=root)
            self.assertEqual(calls, [True, True])
            self.assertEqual(a["manifest"]["preregistration"], record)
            b["manifest"]["timestamp"] = a["manifest"]["timestamp"]
            self.assertEqual(runner.serialize(a), runner.serialize(b))
            self.assertEqual(json.loads(path.read_text()), record)

    def test_only_sample_is_exempt(self):
        self.assertEqual(runner.exempt, ("sample",))
        with tempfile.TemporaryDirectory() as root:
            result = runner.run_gate(sample.run, seed=1, config=CONFIG,
                                     preregistration_root=root)
            self.assertNotIn("preregistration", result["manifest"])

    def test_module_name_fallback_requires_confirmation(self):
        def gate(rng, config):
            self.fail("unconfirmed gate executed")

        gate.__module__ = "experiments.gates.G-test"
        with tempfile.TemporaryDirectory() as root, self.assertRaises(PreregistrationError):
            runner.run_gate(gate, seed=1, config=CONFIG, preregistration_root=root)


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
