"""tests/test_golden_master.py — research-parity guard (audit invariant).

Replays the deterministic scenarios in ``fixtures/parity_scenarios.py``
against THIS repo's domain layer and asserts the outputs are identical to
``fixtures/golden_master.json``, which was recorded by running the very same
scenario file against the frozen thesis-defense checkout of TA-18222007
(tag ``thesis-defense``, commit fe34c36).

A failure here is a REGRESSION of research-validated behavior, not a test to
update casually. Regenerate the golden master only when a domain-formula
change is intentional, approved, and documented:

    cd tests/fixtures
    PYTHONPATH=<repo-to-record> python parity_scenarios.py golden_master.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures.parity_scenarios import run_all

_GOLDEN = Path(__file__).parent / "fixtures" / "golden_master.json"

# Floats travel through JSON (repr round-trip, exact); the tolerance only
# absorbs cross-platform libm noise, not algorithmic drift.
_ABS_TOL = 1e-12


def _assert_matches(actual, expected, path: str) -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: type mismatch"
        assert set(actual.keys()) == set(expected.keys()), (
            f"{path}: key set drifted (missing={set(expected) - set(actual)}, "
            f"extra={set(actual) - set(expected)})"
        )
        for k in expected:
            _assert_matches(actual[k], expected[k], f"{path}.{k}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), (
            f"{path}: length {len(actual)} != {len(expected)}"
        )
        for i, (a, e) in enumerate(zip(actual, expected)):
            _assert_matches(a, e, f"{path}[{i}]")
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected, abs=_ABS_TOL), (
            f"{path}: {actual!r} != {expected!r}"
        )
    else:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"


def test_domain_layer_reproduces_thesis_defense_outputs():
    expected = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    actual = run_all()
    _assert_matches(actual, expected, path="$")
