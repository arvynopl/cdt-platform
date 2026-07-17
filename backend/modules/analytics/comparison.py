"""
modules/analytics/comparison.py — Stated-preference vs. revealed-behavior comparison.

Compares what an investor SAYS they do (UserSurvey Likert responses) against
what the system DETECTS from their trading behavior (BiasMetric severity).

Public API:
    build_stated_vs_revealed(user_id, session) → StatedVsRevealedReport
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from config import (
    DEI_MILD,
    DEI_MODERATE,
    DEI_SEVERE,
    LAI_MILD,
    LAI_MODERATE,
    LAI_SEVERE,
    OCS_MILD,
    OCS_MODERATE,
    OCS_SEVERE,
)
from database.models import BiasMetric, UserSurvey
from modules.analytics.bias_metrics import classify_severity

# ---------------------------------------------------------------------------
# Level constants
# ---------------------------------------------------------------------------

_LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}


def _likert_to_level(score: float) -> str:
    """Map a Likert 1–5 average to low / medium / high."""
    if score <= 2.5:
        return "low"
    if score <= 3.5:
        return "medium"
    return "high"


def _severity_to_level(severity: str) -> str:
    """Map bias severity label to low / medium / high."""
    if severity in ("none", "mild"):
        return "low"
    if severity == "moderate":
        return "medium"
    return "high"  # severe


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BiasComparison:
    """Comparison result for a single bias dimension."""

    bias_name: str          # Human-readable name ("Disposition Effect", etc.)
    stated_level: str       # "low" / "medium" / "high"
    revealed_level: str     # "low" / "medium" / "high"
    discrepancy: str        # see below
    interpretation_id: str  # Bahasa Indonesia narrative (1–2 sentences)


@dataclass
class StatedVsRevealedReport:
    """Full comparison report for a user."""

    has_survey: bool
    comparisons: list[BiasComparison] = field(default_factory=list)
    overall_alignment: str = "no_survey"   # "aligned" / "discrepant" / "no_survey"


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _compute_discrepancy(stated_level: str, revealed_level: str) -> str:
    """Determine discrepancy label from stated vs. revealed levels.

    Returns:
        "aligned"                — levels match
        "underestimates_bias"    — stated < revealed (user thinks they're less biased)
        "overestimates_discipline" — stated > revealed (user states more bias than detected;
                                     actual behavior shows more discipline than claimed)
        "unable_to_compare"      — missing data
    """
    if stated_level not in _LEVEL_RANK or revealed_level not in _LEVEL_RANK:
        return "unable_to_compare"
    s = _LEVEL_RANK[stated_level]
    r = _LEVEL_RANK[revealed_level]
    if s == r:
        return "aligned"
    if s < r:
        return "underestimates_bias"
    return "overestimates_discipline"


_INTERPRETATION: dict[str, dict[str, str]] = {
    "disposition_effect": {
        "aligned": (
            "Persepsi Anda tentang kecenderungan efek disposisi sesuai dengan "
            "perilaku yang terdeteksi sistem."
        ),
        "underestimates_bias": (
            "Anda menyatakan jarang menjual saham untung terlalu cepat, namun "
            "data sesi menunjukkan pola efek disposisi yang lebih kuat dari yang "
            "Anda sadari. Perhatikan timing keputusan jual Anda."
        ),
        "overestimates_discipline": (
            "Anda menyatakan sering terburu-buru menjual, namun perilaku trading "
            "Anda menunjukkan lebih banyak kesabaran dari yang Anda kira. "
            "Pertahankan pendekatan ini."
        ),
        "unable_to_compare": (
            "Data tidak cukup untuk membandingkan pernyataan dan perilaku "
            "pada dimensi efek disposisi."
        ),
    },
    "overconfidence": {
        "aligned": (
            "Frekuensi trading yang Anda laporkan sesuai dengan pola yang terdeteksi."
        ),
        "underestimates_bias": (
            "Anda memperkirakan frekuensi trading Anda lebih rendah dari yang "
            "sebenarnya. Aktivitas trading yang tinggi tanpa peningkatan kinerja "
            "proporsional mengindikasikan overconfidence yang perlu diwaspadai."
        ),
        "overestimates_discipline": (
            "Anda memperkirakan frekuensi trading Anda lebih tinggi, namun "
            "perilaku aktual Anda lebih selektif. Ini adalah tanda pengendalian diri "
            "yang baik."
        ),
        "unable_to_compare": (
            "Data tidak cukup untuk membandingkan pernyataan dan perilaku "
            "pada dimensi overconfidence."
        ),
    },
    "loss_aversion": {
        "aligned": (
            "Sensitivitas kerugian yang Anda laporkan sesuai dengan perilaku "
            "yang terdeteksi sistem."
        ),
        "underestimates_bias": (
            "Anda menyatakan tidak terlalu terganggu oleh kerugian, namun "
            "data menunjukkan Anda menahan posisi merugi lebih lama dari posisi untung. "
            "Pertimbangkan untuk menetapkan batas kerugian yang eksplisit."
        ),
        "overestimates_discipline": (
            "Anda memperkirakan diri Anda sangat sensitif terhadap kerugian, "
            "namun perilaku aktual menunjukkan Anda mampu melepas posisi rugi "
            "dengan lebih disiplin dari yang diperkirakan."
        ),
        "unable_to_compare": (
            "Data tidak cukup untuk membandingkan pernyataan dan perilaku "
            "pada dimensi loss aversion."
        ),
    },
}


def build_stated_vs_revealed(
    user_id: int,
    db_session: Session,
) -> StatedVsRevealedReport:
    """Compare stated preferences (UserSurvey) against revealed behavior (BiasMetric).

    Survey → stated_level mapping (Likert 1–5):
        DEI  ← q_holding_behavior   (1=sell immediately → low DEI, 5=always hold → high DEI)
        OCS  ← avg(q_risk_tolerance, q_trading_frequency)
        LAI  ← q_loss_sensitivity   (1=not bothered → low LAI, 5=very bothered → high LAI)

    BiasMetric → revealed_level:
        none/mild → low | moderate → medium | severe → high

    Args:
        user_id:    User identifier.
        db_session: Active SQLAlchemy session.

    Returns:
        StatedVsRevealedReport dataclass.
    """
    # v6: use the most recent UserSurvey row regardless of survey_type so the
    # comparison naturally follows the user's evolving self-perception — see
    # "Niat vs Aksi" section in the feedback renderer.
    survey = (
        db_session.query(UserSurvey)
        .filter_by(user_id=user_id)
        .order_by(UserSurvey.submitted_at.desc())
        .first()
    )

    if survey is None:
        return StatedVsRevealedReport(has_survey=False, overall_alignment="no_survey")

    # Latest BiasMetric for this user
    latest_metric = (
        db_session.query(BiasMetric)
        .filter_by(user_id=user_id)
        .order_by(BiasMetric.computed_at.desc())
        .first()
    )

    # Stated levels from survey
    dei_stated = _likert_to_level(float(survey.q_holding_behavior))
    ocs_stated = _likert_to_level(
        (float(survey.q_risk_tolerance) + float(survey.q_trading_frequency)) / 2.0
    )
    lai_stated = _likert_to_level(float(survey.q_loss_sensitivity))

    # Revealed levels from latest BiasMetric
    if latest_metric is None:
        dei_revealed = "low"
        ocs_revealed = "low"
        lai_revealed = "low"
    else:
        dei_val = abs(latest_metric.disposition_dei or 0.0)
        ocs_val = latest_metric.overconfidence_score or 0.0
        lai_val = latest_metric.loss_aversion_index or 0.0

        dei_sev = classify_severity(dei_val, DEI_SEVERE, DEI_MODERATE, DEI_MILD)
        ocs_sev = classify_severity(ocs_val, OCS_SEVERE, OCS_MODERATE, OCS_MILD)
        lai_sev = classify_severity(lai_val, LAI_SEVERE, LAI_MODERATE, LAI_MILD)

        dei_revealed = _severity_to_level(dei_sev)
        ocs_revealed = _severity_to_level(ocs_sev)
        lai_revealed = _severity_to_level(lai_sev)

    comparisons: list[BiasComparison] = []
    for bias_key, bias_name, stated, revealed in [
        ("disposition_effect", "Disposition Effect", dei_stated, dei_revealed),
        ("overconfidence", "Overconfidence", ocs_stated, ocs_revealed),
        ("loss_aversion", "Loss Aversion", lai_stated, lai_revealed),
    ]:
        disc = _compute_discrepancy(stated, revealed)
        interp = _INTERPRETATION[bias_key].get(disc, "")
        comparisons.append(BiasComparison(
            bias_name=bias_name,
            stated_level=stated,
            revealed_level=revealed,
            discrepancy=disc,
            interpretation_id=interp,
        ))

    # Overall alignment: discrepant if ANY bias has underestimates_bias
    discrepancy_types = {c.discrepancy for c in comparisons}
    if "underestimates_bias" in discrepancy_types:
        overall = "discrepant"
    elif discrepancy_types <= {"aligned", "overestimates_discipline"}:
        overall = "aligned"
    else:
        overall = "aligned"

    return StatedVsRevealedReport(
        has_survey=True,
        comparisons=comparisons,
        overall_alignment=overall,
    )
