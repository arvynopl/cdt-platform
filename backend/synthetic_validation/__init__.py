"""
synthetic_validation/ — Layer-1 verification harness for the CDT bias detector.

Generates synthetic trading sessions with KNOWN, injected behavioral-bias
parameters, writes them to the database as ordinary ``UserAction`` rows, then
lets the *existing, unmodified* detector pipeline measure them. The recovered
metrics are compared against the injected ground truth (Spearman recovery,
precision/recall, confusion matrices).

DECOUPLING GUARANTEE (anti "inverse crime", Colton & Kress, 1998):
    This package imports NOTHING from ``modules.analytics`` (no ``bias_metrics``,
    no ``features``). Bias is injected purely as behavioral decision rules over
    the real price path; the detector independently *measures* the consequence.
    Ground truth is the injected rule parameters, never a target metric value.
    A unit test (tests/test_synthetic_validation.py) enforces this import graph.

This is research/verification tooling. It is NOT part of the Streamlit app and
does not alter the production pipeline. See the design spec
(Synthetic_Agent_Generator_Spec.md) and the methodology framing
(Validation_Framing_for_Advisor.md).
"""

from __future__ import annotations

__all__ = ["agents", "runner", "ground_truth", "evaluate"]
