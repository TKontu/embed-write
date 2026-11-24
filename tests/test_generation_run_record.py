import hashlib
import math
import unittest
from dataclasses import replace

from generation.run_record import (
    GenerationRunRecord,
    SamplingParams,
    compute_run_id,
    from_json,
    replay,
    to_json,
    validate_record,
)


def fake_generate(prompt, exemplar_ids, model, params):
    h = hashlib.sha256(
        f"{prompt}|{','.join(exemplar_ids)}|{model}|{params.seed}|{params.temperature}"
        f"|{params.top_p}|{params.max_tokens}".encode()
    ).hexdigest()
    return f"cand-{h[:12]}"


def make_record():
    prompt = "Rewrite the passage."
    exemplars = ("ex-1", "ex-2")
    model = "local-llm@1.2.3"
    sampling = (
        SamplingParams(seed=1, temperature=0.7, top_p=0.9, max_tokens=256),
        SamplingParams(seed=2, temperature=0.7, top_p=0.9, max_tokens=256),
    )
    cands = tuple(fake_generate(prompt, exemplars, model, s) for s in sampling)
    return GenerationRunRecord.build(prompt, exemplars, model, sampling, cands)


class RoundTripTest(unittest.TestCase):
    def test_json_round_trip_byte_identical(self):
        rec = make_record()
        text = to_json(rec)
        back = from_json(text)
        self.assertEqual(back, rec)
        self.assertEqual(to_json(back), text)

    def test_run_id_stable(self):
        self.assertEqual(make_record().run_id, make_record().run_id)
        self.assertEqual(make_record().run_id, compute_run_id(make_record()))
        self.assertEqual(len(make_record().run_id), 64)


class RunIdSensitivityTest(unittest.TestCase):
    def test_any_input_change_changes_run_id(self):
        rec = make_record()
        s0 = rec.sampling[0]
        variants = [
            replace(rec, prompt="other"),
            replace(rec, exemplar_ids=("ex-1", "ex-3")),
            replace(rec, exemplar_ids=("ex-2", "ex-1")),
            replace(rec, model="local-llm@1.2.4"),
            replace(rec, sampling=(replace(s0, seed=99), rec.sampling[1])),
            replace(rec, sampling=(replace(s0, temperature=0.8), rec.sampling[1])),
            replace(rec, sampling=(replace(s0, top_p=0.5), rec.sampling[1])),
            replace(rec, sampling=(replace(s0, max_tokens=10), rec.sampling[1])),
        ]
        for v in variants:
            self.assertNotEqual(compute_run_id(v), rec.run_id)


class ValidateTest(unittest.TestCase):
    def test_valid_record_passes(self):
        validate_record(make_record())

    def test_rejects_missing_field(self):
        d = __import__("json").loads(to_json(make_record()))
        del d["model"]
        with self.assertRaises(ValueError):
            from_json(__import__("json").dumps(d))

    def test_rejects_empty_prompt(self):
        with self.assertRaises(ValueError):
            validate_record(replace(make_record(), prompt=""))

    def test_rejects_non_string_candidate(self):
        rec = make_record()
        with self.assertRaises(ValueError):
            validate_record(replace(rec, candidates=(rec.candidates[0], 5)))

    def test_rejects_nan_param(self):
        rec = make_record()
        bad = replace(rec.sampling[0], temperature=math.nan)
        with self.assertRaises(ValueError):
            validate_record(replace(rec, sampling=(bad, rec.sampling[1])))

    def test_rejects_count_mismatch(self):
        rec = make_record()
        with self.assertRaises(ValueError):
            validate_record(replace(rec, candidates=rec.candidates[:1]))

    def test_rejects_wrong_run_id(self):
        with self.assertRaises(ValueError):
            validate_record(replace(make_record(), run_id="0" * 64))


class ReplayTest(unittest.TestCase):
    def test_replay_reproduces(self):
        self.assertTrue(replay(make_record(), fake_generate))

    def test_replay_detects_tamper(self):
        rec = make_record()
        tampered = replace(rec, candidates=(rec.candidates[0], "tampered"))
        self.assertFalse(replay(tampered, fake_generate))


if __name__ == "__main__":
    unittest.main()
