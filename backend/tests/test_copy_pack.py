"""tests/test_copy_pack.py — structural contract for the v6 copy pack."""

import pytest

from modules.feedback.copy_pack import COPY, get

REQUIRED_REGISTERS = {"humane", "practical", "technical"}

REQUIRED_CONCEPTS = {
    "disposition_effect",
    "overconfidence",
    "loss_aversion",
    "stability_index",
    "risk_preference",
    "cdt_ema",
}


def test_every_concept_has_three_registers():
    for concept, registers in COPY.items():
        assert REQUIRED_REGISTERS.issubset(registers), (
            f"{concept!r} missing registers: "
            f"{REQUIRED_REGISTERS - set(registers)}"
        )


def test_all_required_concepts_present():
    missing = REQUIRED_CONCEPTS - set(COPY)
    assert not missing, f"COPY missing required concepts: {missing}"


def test_no_empty_strings():
    for concept, registers in COPY.items():
        for reg, text in registers.items():
            assert text.strip(), f"{concept}.{reg} is empty"
            assert len(text) > 20, f"{concept}.{reg} is suspiciously short"


def test_get_accessor_validates_inputs():
    assert get("disposition_effect", "humane").startswith("Anda")
    with pytest.raises(KeyError):
        get("nope", "humane")
    with pytest.raises(KeyError):
        get("overconfidence", "formal")


def test_loanword_parenthetical_on_first_occurrence():
    """Main term in Bahasa, English in parens — first occurrence at least."""
    expect_pairs = [
        ("disposition_effect", "technical", "Disposition Effect"),
        ("overconfidence", "technical", "Overconfidence"),
        ("loss_aversion", "technical", "Loss Aversion"),
        ("stability_index", "humane", "Stability Index"),
    ]
    for concept, register, english in expect_pairs:
        txt = COPY[concept][register]
        assert f"({english})" in txt, (
            f"{concept}.{register} must include '({english})' on first mention "
            f"per loanword policy."
        )
