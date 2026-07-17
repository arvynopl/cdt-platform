"""modules/analytics/personal_baseline.py — personal watchpoint thresholds.

Computes per-bias μ + 1σ across a user's recent sessions so the dual-ring
radar can show a **Titik Waspada Pribadi** alongside the literature-based
**Titik Waspada Ilmiah**. When fewer than ``MIN_SESSIONS_FOR_PERSONAL``
sessions exist, the caller is told to fall back to scientific thresholds.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from sqlalchemy.orm import Session

from config import LAI_EMA_CEILING
from database.models import BiasMetric

MIN_SESSIONS_FOR_PERSONAL = 3


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _mu_plus_sigma(xs: list[float]) -> float:
    return max(0.0, min(1.0, _mean(xs) + _stdev(xs)))


def compute_personal_threshold(
    db_session: Session,
    user_id: int,
    bias: str,
    *,
    window: int | None = None,
) -> float | None:
    """Return per-bias μ + 1σ for a user, or None when insufficient history.

    ``bias`` is one of ``"dei" | "ocs" | "lai"``; LAI is normalised by
    ``LAI_EMA_CEILING`` to share the [0, 1] axis with DEI/OCS.
    """
    if bias not in {"dei", "ocs", "lai"}:
        raise ValueError(f"unknown bias key: {bias!r}")

    q = (
        db_session.query(BiasMetric)
        .filter_by(user_id=user_id)
        .order_by(BiasMetric.computed_at.desc())
    )
    if window is not None:
        q = q.limit(window)
    rows = q.all()

    if len(rows) < MIN_SESSIONS_FOR_PERSONAL:
        return None

    if bias == "dei":
        xs = [abs(r.disposition_dei or 0.0) for r in rows]
    elif bias == "ocs":
        xs = [r.overconfidence_score or 0.0 for r in rows]
    else:
        xs = [
            min((r.loss_aversion_index or 0.0) / LAI_EMA_CEILING, 1.0)
            for r in rows
        ]
    return _mu_plus_sigma(xs)


def normalised_scientific_thresholds() -> dict:
    """Severe thresholds from config.py, normalised to the shared [0, 1] axis.

    - DEI severe = 0.50 (already in 0–1)
    - OCS severe = 0.70 (already in 0–1)
    - LAI severe = 2.00 normalised by LAI_EMA_CEILING (e.g. 3.0 → 0.667)

    Relocated from the retired Streamlit ``ui_helpers`` module: the values are
    pure config-derived domain quantities, consumed by both the personal
    fallback below and (in Fase 2) the frontend's radar chart via the API.
    """
    from config import DEI_SEVERE, LAI_SEVERE, OCS_SEVERE

    return {
        "dei": float(DEI_SEVERE),
        "ocs": float(OCS_SEVERE),
        "lai": min(float(LAI_SEVERE) / float(LAI_EMA_CEILING), 1.0),
    }


def compute_personal_thresholds(metrics_data: Iterable[dict]) -> dict:
    """Compute personal watchpoints from already-serialised metric dicts.

    ``metrics_data`` entries must include keys ``dei``, ``ocs``, and ``lai_norm``
    (matching the shapes used in app.py's profile page). Returns:

        {"values": {"dei": float, "ocs": float, "lai": float},
         "is_fallback": bool}

    ``is_fallback`` is True when fewer than ``MIN_SESSIONS_FOR_PERSONAL``
    sessions are present — callers should display a "(data belum cukup)" hint.
    """
    data = list(metrics_data)

    if len(data) < MIN_SESSIONS_FOR_PERSONAL:
        return {
            "values": normalised_scientific_thresholds(),
            "is_fallback": True,
        }

    dei = [float(d.get("dei", 0.0)) for d in data]
    ocs = [float(d.get("ocs", 0.0)) for d in data]
    lai = [float(d.get("lai_norm", 0.0)) for d in data]
    return {
        "values": {
            "dei": _mu_plus_sigma(dei),
            "ocs": _mu_plus_sigma(ocs),
            "lai": _mu_plus_sigma(lai),
        },
        "is_fallback": False,
    }
