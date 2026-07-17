"""
synthetic_validation/evaluate.py — Scoring harness (the "detector side").

This module DOES call the production detector (modules.analytics) — that is its
job: run the unmodified pipeline on synthetic sessions and score the recovered
metrics against injected ground truth. The GENERATOR modules (agents, runner,
ground_truth) remain free of any analytics import; only this scorer bridges the
two sides, exactly as a real evaluation harness would.

Phase 2 reports DEI, OCS, and LAI recovery.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd
from sqlalchemy.orm import Session

import config

# NOTE: importing the detector here is intentional and correct — this is the
# scoring side of the harness, not the generator.
from modules.analytics.bias_metrics import (
    classify_severity,
    compute_disposition_effect_result,
    compute_loss_aversion_index_result,
    compute_overconfidence_score,
)
from modules.analytics.features import extract_session_features
from synthetic_validation.ground_truth import SEVERITY_ORDINAL, SyntheticGroundTruth

logger = logging.getLogger(__name__)

# Map a bias name to (detected_value_attr, detected_severity_attr).
BIAS_FIELDS = {
    "disposition": ("dei", "dei_severity"),
    "overconfidence": ("ocs", "ocs_severity"),
    "loss_aversion": ("lai", "lai_severity"),
}


@dataclass
class DetectionRecord:
    """One row joining injected truth with the detector's output for all biases."""
    agent_id: str
    injected_bias: str          # "none" | "disposition" | "overconfidence" | "loss_aversion"
    injected_severity: str
    injected_ordinal: int
    dei: float
    dei_severity: str
    ocs: float
    ocs_severity: str
    lai: float
    lai_severity: str
    n_realized: int


def detect_session(session: Session, user_id: int, session_id: str) -> dict:
    """Run the REAL detector on one synthetic session → all three biases."""
    feats = extract_session_features(session, user_id, session_id)

    dei_res = compute_disposition_effect_result(feats)

    ocs = compute_overconfidence_score(feats)
    ocs_sev = classify_severity(
        ocs, config.OCS_SEVERE, config.OCS_MODERATE, config.OCS_MILD,
    )

    lai_res = compute_loss_aversion_index_result(feats)

    return {
        "dei": dei_res.value, "dei_severity": dei_res.severity,
        "ocs": ocs, "ocs_severity": ocs_sev,
        "lai": lai_res.value, "lai_severity": lai_res.severity,
        "n_realized": len(feats.realized_trades),
    }


@dataclass
class AgentRecord:
    """Per-agent record aggregating the detector's output across the agent's
    multiple sessions. Shares the DEI/OCS/LAI + *_severity field names of
    DetectionRecord so the same scoring functions apply unchanged."""
    agent_id: str
    injected_bias: str
    injected_severity: str
    injected_ordinal: int
    dei: float
    dei_severity: str
    ocs: float
    ocs_severity: str
    lai: float
    lai_severity: str
    mean_n_realized: float
    n_sessions: int


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def build_agent_records(
    session: Session,
    agent_items: list[tuple[SyntheticGroundTruth, int, list[str]]],
) -> list[AgentRecord]:
    """For each (ground_truth, user_id, [session_ids]) run the REAL detector on
    every session, then AVERAGE the per-session metrics into a per-agent
    estimate and re-derive severity from the aggregate. This mirrors the way the
    production CDT consolidates a user's behavior across sessions (EMA), trading
    single-session noise for a stable per-user profile. Mean is used (rather than
    EMA) because it is order-independent and equally smoothing for verification.
    """
    records: list[AgentRecord] = []
    for gt, user_id, session_ids in agent_items:
        per = [detect_session(session, user_id, sid) for sid in session_ids]
        dei = _mean([p["dei"] for p in per])
        ocs = _mean([p["ocs"] for p in per])
        lai = _mean([p["lai"] for p in per])
        mean_n = _mean([float(p["n_realized"]) for p in per])
        min_met = mean_n >= 1  # aggregated agents always trade enough
        records.append(AgentRecord(
            agent_id=gt.agent_id,
            injected_bias=gt.injected_bias,
            injected_severity=gt.injected_severity,
            injected_ordinal=gt.severity_ordinal,
            dei=dei,
            dei_severity=classify_severity(
                abs(dei), config.DEI_SEVERE, config.DEI_MODERATE, config.DEI_MILD,
                min_sample_met=min_met),
            ocs=ocs,
            ocs_severity=classify_severity(
                ocs, config.OCS_SEVERE, config.OCS_MODERATE, config.OCS_MILD),
            lai=lai,
            lai_severity=classify_severity(
                lai, config.LAI_SEVERE, config.LAI_MODERATE, config.LAI_MILD,
                min_sample_met=min_met),
            mean_n_realized=mean_n,
            n_sessions=len(session_ids),
        ))
    return records


def build_records(session: Session, items: list[tuple[SyntheticGroundTruth, int]]):
    records: list[DetectionRecord] = []
    for gt, user_id in items:
        d = detect_session(session, user_id, gt.session_id)
        records.append(DetectionRecord(
            agent_id=gt.agent_id,
            injected_bias=gt.injected_bias,
            injected_severity=gt.injected_severity,
            injected_ordinal=gt.severity_ordinal,
            dei=d["dei"], dei_severity=d["dei_severity"],
            ocs=d["ocs"], ocs_severity=d["ocs_severity"],
            lai=d["lai"], lai_severity=d["lai_severity"],
            n_realized=d["n_realized"],
        ))
    return records


# ---------------------------------------------------------------------------
# Per-bias scoring (accessor-driven so DEI/OCS/LAI share one implementation)
# ---------------------------------------------------------------------------
def _val(record: DetectionRecord, bias: str) -> float:
    return abs(getattr(record, BIAS_FIELDS[bias][0]))


def _sev(record: DetectionRecord, bias: str) -> str:
    return getattr(record, BIAS_FIELDS[bias][1])


def spearman_recovery(records: list[DetectionRecord], bias: str) -> float:
    """Spearman ρ between injected severity ordinal and detected |metric| for
    ``bias``. Computed as Pearson-of-ranks (no scipy)."""
    if len(records) < 3:
        return float("nan")
    df = pd.DataFrame({
        "ordinal": [r.injected_ordinal for r in records],
        "metric": [_val(r, bias) for r in records],
    })
    return float(df["ordinal"].rank().corr(df["metric"].rank()))


def presence_precision_recall(records, bias: str) -> tuple[float, float]:
    tp = fp = fn = 0
    for r in records:
        truth_pos = r.injected_severity != "none"
        pred_pos = _sev(r, bias) != "none"
        if truth_pos and pred_pos:
            tp += 1
        elif not truth_pos and pred_pos:
            fp += 1
        elif truth_pos and not pred_pos:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    return precision, recall


def severity_accuracy(records, bias: str) -> tuple[float, float, int]:
    if not records:
        return float("nan"), float("nan"), 0
    exact = within = catastrophic = 0
    for r in records:
        inj = r.injected_ordinal
        det = SEVERITY_ORDINAL[_sev(r, bias)]
        if det == inj:
            exact += 1
        if abs(det - inj) <= 1:
            within += 1
        if abs(det - inj) >= 3:
            catastrophic += 1
    n = len(records)
    return exact / n, within / n, catastrophic


def confusion_matrix(records, bias: str) -> pd.DataFrame:
    order = ["none", "mild", "moderate", "severe"]
    df = pd.DataFrame(0, index=order, columns=order, dtype=int)
    for r in records:
        df.loc[r.injected_severity, _sev(r, bias)] += 1
    return df
