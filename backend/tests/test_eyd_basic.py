"""tests/test_eyd_basic.py — cheap sanity checks for EYD V orthography
on the copy pack strings.

We intentionally keep rules cheap — a full linter would over-constrain
future edits. The checks here are for mechanical failures such as double
spaces, unhyphenated reduplication, or sentences without terminal punctuation.
"""

import re

from modules.feedback.copy_pack import COPY

_SENTENCE_END = (".", "!", "?", ":", "…", ")", "”", "\"")
_REDUPLICATION_PAIRS = {
    ("buku", "buku"),
    ("saham", "saham"),
    ("hari", "hari"),
    ("saat", "saat"),
    ("kata", "kata"),
}


def _all_snippets():
    for concept, registers in COPY.items():
        for reg, text in registers.items():
            yield f"{concept}.{reg}", text


def test_no_double_spaces():
    for name, text in _all_snippets():
        assert "  " not in text, f"{name} contains a double space"


def test_reduplication_uses_hyphen_not_space():
    for name, text in _all_snippets():
        for a, b in _REDUPLICATION_PAIRS:
            bad = re.search(rf"\b{a}\s+{b}\b", text, flags=re.IGNORECASE)
            assert not bad, (
                f"{name}: reduplication {a} {b!r} should use a hyphen "
                f"(\"{a}-{b}\") per EYD V."
            )


def test_sentences_end_with_punctuation():
    for name, text in _all_snippets():
        stripped = text.rstrip()
        assert stripped.endswith(_SENTENCE_END), (
            f"{name} must end with sentence punctuation, got trailing "
            f"{stripped[-1]!r}"
        )


def test_each_snippet_has_a_verb_or_sentence_marker():
    """Cheap heuristic: every snippet must contain at least one Bahasa verb
    prefix (me-, di-, ber-, se-) or the words 'adalah'/'dinyatakan'. This
    prevents empty/label-only copy from passing through."""
    prefixes = re.compile(
        r"\b("
        r"me[a-z]+|di[a-z]+|ber[a-z]+|se[a-z]+|ter[a-z]+|pe[a-z]+|"
        r"adalah|dinyatakan|dihitung|mencerminkan|menunjukkan|menyatakan"
        r")\b",
        flags=re.IGNORECASE,
    )
    for name, text in _all_snippets():
        assert prefixes.search(text), f"{name} appears to lack any verb/sentence marker"
