"""
modules/cdt/stability.py — Stability index and learning trajectory computation.

The stability index measures how consistent a user's bias pattern is across
recent sessions: high stability = consistent behaviour (not necessarily good).

The learning trajectory detects whether a user's dominant bias intensity is
genuinely decreasing (improving) or increasing (worsening) across sessions.

Functions:
    compute_stability_index       — Returns a float in [0, 1].
    compute_learning_trajectory   — Returns a LearningTrajectory dataclass.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from scipy.stats import linregress
from sqlalchemy.orm import Session

from config import CDT_STABILITY_WINDOW
from database.models import BiasMetric, CdtSnapshot

_LOG = logging.getLogger(__name__)

# Thresholds for classifying trajectory direction
_SLOPE_IMPROVE_THRESHOLD = -0.05   # slope below this → improving (if r² passes)
_SLOPE_WORSEN_THRESHOLD = 0.05    # slope above this → worsening (if r² passes)
_R2_THRESHOLD = 0.4               # minimum fit quality to trust the slope direction

# Human-readable Bahasa Indonesia labels for each bias dimension
_BIAS_LABEL_ID: dict[str, str] = {
    "ocs": "overconfidence",
    "dei": "disposition effect",
    "lai": "loss aversion",
}


@dataclass
class LearningTrajectory:
    """Learning trajectory for the user's most dominant bias dimension.

    Attributes:
        bias:              Which bias dimension was analysed: "ocs" | "dei" | "lai".
        direction:         "improving" | "worsening" | "stable" | "insufficient_data".
        slope:             Linear regression slope over the analysed sessions.
        r_squared:         Coefficient of determination (fit quality).
        sessions_analyzed: Number of CdtSnapshot rows used.
        interpretation:    Human-readable summary in Bahasa Indonesia.
    """

    bias: str
    direction: str
    slope: float
    r_squared: float
    sessions_analyzed: int
    interpretation: str


def _interpret(bias: str, direction: str, n: int) -> str:
    """Build a Bahasa Indonesia interpretation string."""
    label = _BIAS_LABEL_ID.get(bias, bias)
    if direction == "improving":
        return (
            f"Kecenderungan {label} Anda menurun selama {n} sesi terakhir. "
            "Pertahankan pola ini."
        )
    if direction == "worsening":
        return (
            f"Kecenderungan {label} Anda meningkat selama {n} sesi terakhir. "
            "Perhatikan pola ini dan berupaya untuk memperbaikinya."
        )
    if direction == "stable":
        return (
            f"Kecenderungan {label} Anda relatif stabil selama {n} sesi terakhir."
        )
    # insufficient_data
    return "Data tidak cukup untuk menganalisis trajektori pembelajaran."


def compute_learning_trajectory(
    user_id: int,
    session: Session,
) -> LearningTrajectory:
    """Detect whether a user's bias intensity is genuinely decreasing across sessions.

    Algorithm:
        1. Fetch the most recent N CdtSnapshot rows for the user, ordered
           chronologically (N = min(available, CDT_STABILITY_WINDOW = 5)).
        2. If N < 3, return direction="insufficient_data".
        3. For each bias dimension (ocs, dei, lai), compute a linear regression
           of the bias intensity value against session index (0…N-1).
        4. Classify direction per dimension:
           - slope < -0.05 AND r² > 0.4  → "improving"
           - slope >  0.05 AND r² > 0.4  → "worsening"
           - otherwise                   → "stable"
        5. Return the trajectory for the *dominant* bias (highest mean value),
           as that dimension is most actionable for the user.

    Args:
        user_id: ID of the user.
        session: Active SQLAlchemy session.

    Returns:
        LearningTrajectory dataclass.
    """
    # Fetch last CDT_STABILITY_WINDOW snapshots in reverse-chronological order,
    # then reverse to restore oldest-first ordering for the regression x-axis.
    rows = (
        session.query(CdtSnapshot)
        .filter_by(user_id=user_id)
        .order_by(CdtSnapshot.session_number.desc())
        .limit(CDT_STABILITY_WINDOW)
        .all()
    )
    rows = list(reversed(rows))
    n = len(rows)

    _LOG.debug("user_id=%d: %d CdtSnapshot(s) available for trajectory", user_id, n)

    # Determine the dominant bias for labelling (even when data is insufficient)
    def _dominant(snapshots: list[CdtSnapshot]) -> str:
        if not snapshots:
            return "ocs"
        k = len(snapshots)
        means = {
            "ocs": sum(s.cdt_overconfidence for s in snapshots) / k,
            "dei": sum(s.cdt_disposition for s in snapshots) / k,
            "lai": sum(s.cdt_loss_aversion for s in snapshots) / k,
        }
        return max(means, key=means.__getitem__)

    if n < 3:
        dominant = _dominant(rows)
        return LearningTrajectory(
            bias=dominant,
            direction="insufficient_data",
            slope=0.0,
            r_squared=0.0,
            sessions_analyzed=n,
            interpretation=_interpret(dominant, "insufficient_data", n),
        )

    xs = list(range(n))
    bias_series: dict[str, list[float]] = {
        "ocs": [s.cdt_overconfidence for s in rows],
        "dei": [s.cdt_disposition for s in rows],
        "lai": [s.cdt_loss_aversion for s in rows],
    }

    results: dict[str, dict] = {}
    for key, ys in bias_series.items():
        reg = linregress(xs, ys)
        slope = float(reg.slope)
        r_sq = float(reg.rvalue ** 2)

        if slope < _SLOPE_IMPROVE_THRESHOLD and r_sq > _R2_THRESHOLD:
            direction = "improving"
        elif slope > _SLOPE_WORSEN_THRESHOLD and r_sq > _R2_THRESHOLD:
            direction = "worsening"
        else:
            direction = "stable"

        results[key] = {
            "direction": direction,
            "slope": slope,
            "r_squared": r_sq,
            "mean": sum(ys) / n,
        }
        _LOG.debug(
            "user_id=%d bias=%s slope=%.4f r2=%.4f direction=%s",
            user_id, key, slope, r_sq, direction,
        )

    dominant = max(results, key=lambda k: results[k]["mean"])
    best = results[dominant]

    return LearningTrajectory(
        bias=dominant,
        direction=best["direction"],
        slope=best["slope"],
        r_squared=best["r_squared"],
        sessions_analyzed=n,
        interpretation=_interpret(dominant, best["direction"], n),
    )


def compute_stability_index(db_session: Session, user_id: int) -> float:
    """Compute the stability index from the last CDT_STABILITY_WINDOW sessions.

    Algorithm:
        1. Fetch the last N BiasMetric rows for the user (ordered by computed_at).
        2. Normalise each metric to [0, 1]:
           - OCS already in [0, 1) — unchanged.
           - DEI: mapped from [−1, 1] to [0, 1] as (DEI + 1) / 2.
           - LAI: normalised as min(LAI / 3, 1.0).
        3. Compute the standard deviation across sessions for each dimension.
        4. stability = 1 − mean(std_overconfidence, std_dei_norm, std_lai_norm)
           clamped to [0, 1].

    Fewer than 2 sessions → returns 0.0 (insufficient data).

    Args:
        db_session: Active SQLAlchemy session.
        user_id:    ID of the user.

    Returns:
        Float in [0, 1] — higher = more consistent bias pattern.
    """
    metrics = (
        db_session.query(BiasMetric)
        .filter_by(user_id=user_id)
        .order_by(BiasMetric.computed_at.desc())
        .limit(CDT_STABILITY_WINDOW)
        .all()
    )

    if len(metrics) < 2:
        return 0.0

    ocs_vals = [m.overconfidence_score or 0.0 for m in metrics]
    # Map DEI from [−1, 1] to [0, 1] so all three dimensions are scale-comparable.
    # Raw DEI oscillating ±0.8 has std≈0.8; OCS/LAI_norm have max std≈0.5.
    # Without normalization, DEI dominates the mean_std and stability becomes
    # a proxy for DEI variance rather than overall behavioural consistency.
    dei_vals = [((m.disposition_dei or 0.0) + 1.0) / 2.0 for m in metrics]
    lai_vals = [min((m.loss_aversion_index or 0.0) / 3.0, 1.0) for m in metrics]

    def _std(vals: list[float]) -> float:
        n = len(vals)
        if n < 2:
            return 0.0
        mu = sum(vals) / n
        variance = sum((v - mu) ** 2 for v in vals) / (n - 1)
        return math.sqrt(variance)

    mean_std = (_std(ocs_vals) + _std(dei_vals) + _std(lai_vals)) / 3.0
    return max(0.0, min(1.0, 1.0 - mean_std))
