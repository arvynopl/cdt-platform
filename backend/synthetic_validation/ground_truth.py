"""
synthetic_validation/ground_truth.py — Injected-truth record for one synthetic
session. This is the label set the detector is scored against. It contains the
behavioral rule PARAMETERS only — never a target metric value — so comparing it
to detector output is a genuine recovery test, not a tautology.
"""

from __future__ import annotations

from dataclasses import dataclass

# Ordinal encoding for Spearman recovery / confusion matrices.
SEVERITY_ORDINAL: dict[str, int] = {
    "none": 0,
    "mild": 1,
    "moderate": 2,
    "severe": 3,
}


@dataclass(frozen=True)
class SyntheticGroundTruth:
    """Known truth for one synthetic agent session."""
    agent_id: str
    session_id: str
    base_strategy: str          # e.g. "buy_and_hold" or "disposition_basket"
    injected_bias: str          # "none" | "disposition" | "overconfidence" | "loss_aversion" | "mixed"
    injected_severity: str      # "none" | "mild" | "moderate" | "severe"
    rule_parameters: dict       # the actual knobs used, e.g. {"k": 4.0, "gain_threshold": 0.015}
    market_window: tuple        # (start_date_iso, end_date_iso)
    rng_seed: int

    @property
    def severity_ordinal(self) -> int:
        return SEVERITY_ORDINAL[self.injected_severity]
