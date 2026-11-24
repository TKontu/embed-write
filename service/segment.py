"""CK-02 English sentence segmentation on pinned PySBD 0.3.4.

Production caller: SegmentationCache (CK-03), unwired until CK-01. Pass
SEGMENTER_ID as its key_version; bump it whenever boundary policy changes.
The wrapper uses O(block size) memory and scanning, never a corpus-sized batch.
PySBD's internal regex/span-search runtime is not guaranteed linear; the
100 000-word operating bound is untested.
"""
import re

import pysbd

SEGMENTER_ID = "pysbd-0.3.4-en-clean-false-markdown-v1"

# Single-backtick inline code and numeric Markdown/superscript footnotes.
_PROTECTED = re.compile(r"`[^`]*`|\[\^[0-9]+\]|[⁰¹²³⁴⁵⁶⁷⁸⁹]+")


def segment_sentences(text: str) -> tuple[str, ...]:
    """Return original sentence text, trimming only boundary whitespace.

    Code is opaque to boundary detection; footnotes are transparent and remain
    attached to preceding punctuation. This is not a Markdown block parser.
    A fresh Segmenter per call avoids sharing PySBD's mutable processing state.
    """
    if not text.strip():
        return ()
    # Equal-length masks preserve offsets without collision-prone placeholders.
    masked = _PROTECTED.sub(
        lambda match: ("x" if match[0].startswith("`") else " ") * len(match[0]),
        text,
    )
    spans = pysbd.Segmenter(language="en", clean=False, char_span=True).segment(masked)
    sentences = []
    start = 0
    # Use contiguous original slices, including leading/trailing marker-only text.
    for end in [span.end for span in spans[:-1]] + [len(text)]:
        sentence = text[start:end].strip()
        if sentence:
            sentences.append(sentence)
        start = end
    return tuple(sentences)
