"""CO-14 section inference (D-015). All fixtures are LLM-built synthetic text, never corpus data."""
import unittest

from experiments.section_inference import infer_sections


def starts(secs):
    return [(s["start_line"], s["level"], s["method"]) for s in secs]


class InferSectionsTest(unittest.TestCase):
    def test_numbered_headings(self):
        md = ("1. Introduction\n\nThe pump was tested.\n\n2.3 Method details\n\n"
              "We measured flow.\n\nIV. Results\n\nFlow rose.\n\nA) Annex\n\nTables follow.\n")
        secs = infer_sections(md)
        self.assertEqual(starts(secs), [(0, 1, "numbering"), (4, 2, "numbering"),
                                        (8, 1, "numbering"), (12, 1, "numbering")])
        for s in secs:
            self.assertIs(s["inferred"], True)
            self.assertEqual(s["title_line"], s["start_line"])

    def test_bold_and_short_lines(self):
        md = ("**Background of the study**\n\nSome text here.\n\nScope and limits\n\n"
              "More text follows here.\n")
        self.assertEqual(starts(infer_sections(md)), [(0, 1, "formatting"), (4, 1, "formatting")])

    def test_numbered_list_is_not_headings(self):
        md = ("Steps taken.\n\n1. Open the valve\n2. Close the valve\n3. Record\n\n"
              "Done with steps.\n")
        self.assertEqual(infer_sections(md), [])

    def test_code_fence_and_indented_code_never_qualify(self):
        md = ("Intro text.\n\n```\n\n1. Fake heading\n\n**Bold fake**\n\nbody\n```\n\n"
              "    Indented fake\n\nReal prose paragraph.\n")
        self.assertEqual(infer_sections(md), [])

    def test_sentence_line_not_heading(self):
        md = "A short sentence.\n\nAnother paragraph of prose.\n"
        self.assertEqual(infer_sections(md), [])

    def test_empty(self):
        self.assertEqual(infer_sections(""), [])

    def test_deterministic(self):
        md = "1. Intro\n\nText.\n\n**Next part**\n\nMore text.\n"
        self.assertEqual(infer_sections(md), infer_sections(md))
        self.assertEqual(len(infer_sections(md)), 2)


# LLM-built synthetic topic blocks (never corpus text). Each paragraph is one line.
PUMPS = [
    "The centrifugal pump impeller spins inside the volute casing and moves water through the outlet pipe.",
    "Pump seals keep water inside the casing while the impeller shaft rotates at high speed.",
    "When the pump impeller wears, the water flow through the casing drops and the shaft vibrates.",
    "Engineers replace the pump seals and the impeller when water leaks from the casing near the shaft.",
]
BIRDS = [
    "Migrating geese fly south in autumn and rest on lakes where they feed on grass and seeds.",
    "The geese form a long flock and each bird takes turns leading the migration across the sky.",
    "Young birds learn the migration route by following older geese from the nesting lakes.",
    "Feathers keep the migrating birds warm while the flock crosses cold northern skies and lakes.",
]
BREAD = [
    "Bakers mix flour, yeast, salt and warm water to make a soft dough for bread loaves.",
    "The dough rises while the yeast ferments sugar in the flour and the bakers wait patiently.",
    "After kneading the dough, bakers shape loaves and bake the bread in a hot oven.",
    "A good oven gives the bread loaves a crisp crust while the flour crumb stays soft and moist.",
]


def doc(*blocks):
    paras = [p for b in blocks for p in b]
    return "\n\n".join(paras) + "\n", [2 * i for i in range(len(paras))]


class TopicShiftTest(unittest.TestCase):
    def assertNear(self, got, want):
        self.assertEqual(len(got), len(want), (got, want))
        for g, w in zip(got, want):
            self.assertLessEqual(abs(g - w), 2, (got, want))  # +-1 paragraph = +-2 lines

    def test_three_topics_split_at_changes(self):
        md, para = doc(PUMPS, BIRDS, BREAD)
        secs = infer_sections(md)
        self.assertTrue(secs)
        for s in secs:
            self.assertEqual((s["method"], s["level"], s["title_line"], s["inferred"]),
                             ("topic_shift", 1, None, True))
            self.assertIn(s["start_line"], para)
        self.assertNear([s["start_line"] for s in secs], [0, para[4], para[8]])

    def test_two_topics(self):
        md, para = doc(PUMPS, BREAD)
        self.assertNear([s["start_line"] for s in infer_sections(md)], [0, para[4]])

    def test_single_topic_gives_none_or_few(self):
        md, _ = doc(PUMPS, PUMPS[::-1])
        self.assertLessEqual(len(infer_sections(md)), 1)

    def test_short_text_gives_none(self):
        md, _ = doc(PUMPS[:2], BREAD[:2])
        self.assertEqual(infer_sections(md), [])

    def test_structured_documents_not_topic_shift(self):
        md = "1. Pumps\n\n" + "\n\n".join(PUMPS) + "\n\n2. Bread\n\n" + "\n\n".join(BREAD)
        self.assertEqual({s["method"] for s in infer_sections(md)}, {"numbering"})

    def test_deterministic(self):
        md, _ = doc(PUMPS, BIRDS, BREAD)
        self.assertEqual(infer_sections(md), infer_sections(md))

    def test_code_blocks_ignored(self):
        code = "```\n" + "\n\n".join(BIRDS * 2) + "\n```"
        md = "\n\n".join(PUMPS + [code] + PUMPS[::-1] + ["    " + BREAD[0]]) + "\n"
        secs = infer_sections(md)
        self.assertLessEqual(len(secs), 1)
        lines = md.splitlines()
        for s in secs:
            self.assertFalse(lines[s["start_line"]].startswith(("```", "    ")))


TOPIC_WORDS = (("pump", "impeller", "casing", "seal"), ("bird", "geese", "flock", "feather"),
               ("bread", "dough", "flour", "oven", "baker", "yeast"))


class FakeEmbedder:
    """Deterministic fake: one dimension per topic keyword family, plus a constant offset.

    Stands in for a semantic model in tests (fixtures are LLM-built synthetic prose).
    """
    model_id = "fake-semantic"
    model_version = "1"
    dims = 4

    def __init__(self):
        self.batches = []

    def embed(self, texts, level):
        from service.vectors import LevelVector
        self.batches.append(len(texts))
        out = []
        for t in texts:
            low = t.lower()
            vals = [float(sum(low.count(w) for w in ws)) for ws in TOPIC_WORDS] + [0.3]
            out.append(LevelVector(level, tuple(vals)))
        return out


class TopicShiftEmbeddingTest(unittest.TestCase):
    assertNear = TopicShiftTest.assertNear

    def test_three_topics_split_at_changes(self):
        md, para = doc(PUMPS, BIRDS, BREAD)
        emb = FakeEmbedder()
        secs = infer_sections(md, embedder=emb)
        for s in secs:
            self.assertEqual((s["method"], s["level"], s["title_line"], s["inferred"]),
                             ("topic_shift_embedding", 1, None, True))
        self.assertNear([s["start_line"] for s in secs], [0, para[4], para[8]])
        self.assertEqual(emb.batches, [12])  # one document, one batch <= 64

    def test_two_topics(self):
        md, para = doc(PUMPS, BREAD)
        self.assertNear([s["start_line"] for s in infer_sections(md, embedder=FakeEmbedder())],
                        [0, para[4]])

    def test_single_topic_gives_none(self):
        md, _ = doc(PUMPS, PUMPS[::-1])
        self.assertEqual(infer_sections(md, embedder=FakeEmbedder()), [])

    def test_short_text_gives_none(self):
        md, _ = doc(PUMPS[:2], BREAD[:2])
        self.assertEqual(infer_sections(md, embedder=FakeEmbedder()), [])

    def test_batches_of_64(self):
        md, _ = doc(PUMPS * 20, BREAD * 20)
        emb = FakeEmbedder()
        infer_sections(md, embedder=emb)
        self.assertEqual(emb.batches, [64, 64, 32])

    def test_structured_documents_do_not_embed(self):
        md = "1. Pumps\n\n" + "\n\n".join(PUMPS) + "\n\n2. Bread\n\n" + "\n\n".join(BREAD)
        emb = FakeEmbedder()
        self.assertEqual({s["method"] for s in infer_sections(md, embedder=emb)}, {"numbering"})
        self.assertEqual(emb.batches, [])

    def test_deterministic(self):
        md, _ = doc(PUMPS, BIRDS, BREAD)
        self.assertEqual(infer_sections(md, embedder=FakeEmbedder()),
                         infer_sections(md, embedder=FakeEmbedder()))

    def test_no_embedder_is_lexical(self):
        md, _ = doc(PUMPS, BREAD)
        self.assertEqual(infer_sections(md), infer_sections(md, embedder=None))
        self.assertEqual({s["method"] for s in infer_sections(md)}, {"topic_shift"})


if __name__ == "__main__":
    unittest.main()
