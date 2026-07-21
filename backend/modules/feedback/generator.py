"""
modules/feedback/generator.py — Rule-based feedback generation.

Combines bias metrics + templates into FeedbackHistory records.

Functions:
    generate_feedback       — Create and persist FeedbackHistory for a session.
    compute_counterfactual  — Estimate gains if user had held a winning position longer.
    get_session_feedback    — Retrieve delivered feedback for a session.
    get_longitudinal_summary — Summarise bias trends across all sessions.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from config import (
    CDT_MODIFIER_STABILITY_THRESHOLD,
    DEI_MILD,
    DEI_MODERATE,
    DEI_SEVERE,
    LAI_EMA_CEILING,
    LAI_MILD,
    LAI_MODERATE,
    LAI_SEVERE,
    MIN_TRADES_FOR_FULL_SEVERITY,
    OCS_MILD,
    OCS_MODERATE,
    OCS_SEVERE,
    ROUNDS_PER_SESSION,
)

logger = logging.getLogger(__name__)
from database.models import (
    BiasMetric,
    CognitiveProfile,
    FeedbackHistory,
    MarketSnapshot,
    UserAction,
)
from modules.analytics.bias_metrics import classify_severity
from modules.feedback.templates import TEMPLATES


def compute_counterfactual(
    db_session: Session,
    realized_trades: list[dict],
    open_positions: list[dict],
    session_snapshots: dict | None = None,
    extra_rounds: int = 3,
    session_id: str | None = None,
) -> str:
    """Estimate what the user would have earned by holding the best winner longer.

    Finds the realized trade with the highest sell value, then looks up what the
    price would have been *extra_rounds* later (if available).

    Args:
        db_session:        Active SQLAlchemy session.
        realized_trades:   From SessionFeatures.realized_trades.
        open_positions:    From SessionFeatures.open_positions.
        session_snapshots: Deprecated, unused. Pass None.
        extra_rounds:      How many additional rounds to project forward.
        session_id:        Optional session UUID. When provided, actual MarketSnapshot
                           data is used for projection instead of linear extrapolation
                           (preferred).

    Returns:
        A Bahasa Indonesia counterfactual string, or empty string if not applicable.
    """
    # Find winner with highest absolute gain
    winners = [
        t for t in realized_trades if t["sell_price"] > t["buy_price"]
    ]
    if not winners:
        return ""

    best = max(winners, key=lambda t: (t["sell_price"] - t["buy_price"]) * t["quantity"])
    actual_gain = (best["sell_price"] - best["buy_price"]) * best["quantity"]

    # Try to find what price was extra_rounds after sell_round
    # Clamp extra_rounds so we don't project beyond the simulation window
    actual_extra = min(extra_rounds, ROUNDS_PER_SESSION - best["sell_round"])
    if actual_extra <= 0:
        return ""
    target_round = best["sell_round"] + actual_extra

    # Prefer actual market data over linear extrapolation.
    # If session_id is provided, look up the real MarketSnapshot price for
    # the target round by querying the UserAction record for that round.
    projected_price: float | None = None
    if session_id is not None:
        target_action = (
            db_session.query(UserAction)
            .filter_by(
                session_id=session_id,
                stock_id=best["stock_id"],
                scenario_round=target_round,
            )
            .first()
        )
        if target_action:
            snap = db_session.get(MarketSnapshot, target_action.snapshot_id)
            if snap and snap.close is not None:
                projected_price = snap.close

    if projected_price is None:
        # Fallback: linear extrapolation with a price floor to prevent negatives.
        trend_per_round = (best["sell_price"] - best["buy_price"]) / max(
            best["sell_round"] - best["buy_round"], 1
        )
        projected_price = max(best["sell_price"] + trend_per_round * actual_extra, 0.01)

    projected_gain = (projected_price - best["buy_price"]) * best["quantity"]

    if projected_gain <= actual_gain:
        return ""

    additional = projected_gain - actual_gain
    return (
        f"Contoh: Anda menjual {best['stock_id']} di putaran {best['sell_round']} "
        f"dengan keuntungan Rp {actual_gain:,.0f}. "
        f"Jika Anda menahan {actual_extra} putaran lebih lama, "
        f"estimasi keuntungan bisa mencapai Rp {projected_gain:,.0f} "
        f"(tambahan ≈ Rp {additional:,.0f})."
    )


_SEVERITY_RANK: dict[str, int] = {"none": 0, "mild": 1, "moderate": 2, "severe": 3}


def generate_tldr_summary(bias_results: dict) -> str:
    """Generate a 1–2 sentence plain-language TL;DR summary in Bahasa Indonesia.

    Args:
        bias_results: Dict with keys "dei", "ocs", "lai", each a (score, severity) tuple.
                      E.g. {"dei": (0.65, "severe"), "ocs": (0.15, "none"), "lai": (1.1, "none")}

    Returns:
        A Bahasa Indonesia summary string (may contain Markdown bold via **...**).
    """
    # All none → encouragement
    if all(sv == "none" for _, sv in bias_results.values()):
        return (
            "Dalam sesi ini, Anda tidak menunjukkan pola bias perilaku yang signifikan. "
            "Terus pertahankan pendekatan yang disiplin."
        )

    # Find dominant bias: highest severity rank, then highest score as tiebreaker
    best_key = max(
        ["dei", "ocs", "lai"],
        key=lambda k: (_SEVERITY_RANK.get(bias_results[k][1], 0), bias_results[k][0]),
    )
    _, severity = bias_results[best_key]

    _SUMMARIES: dict[str, dict[str, str]] = {
        "dei": {
            "mild": (
                "Pola **efek disposisi ringan** terdeteksi: Anda cenderung menjual saham "
                "yang untung sedikit lebih cepat dari optimal. "
                "Perhatikan timing penjualan di sesi berikutnya."
            ),
            "moderate": (
                "Dalam sesi ini, kecenderungan **efek disposisi Anda berada di tingkat sedang** "
                "— Anda cenderung menjual saham yang untung terlalu cepat dan menahan yang rugi "
                "terlalu lama. Coba terapkan aturan stop-loss yang konsisten di sesi berikutnya."
            ),
            "severe": (
                "Dalam sesi ini, kecenderungan **efek disposisi Anda berada di tingkat berat** "
                "— Anda menjual saham yang untung terlalu cepat dan menahan yang rugi terlalu "
                "lama secara signifikan. Terapkan aturan stop-loss yang ketat dan target profit "
                "yang jelas sebelum memulai transaksi."
            ),
        },
        "ocs": {
            "mild": (
                "Pola **overconfidence ringan** terdeteksi: frekuensi transaksi Anda lebih "
                "tinggi dari rata-rata tanpa peningkatan performa proporsional."
            ),
            "moderate": (
                "Pola **overconfidence sedang** terdeteksi: frekuensi transaksi Anda lebih "
                "tinggi dari rata-rata tanpa peningkatan performa proporsional. "
                "Pertimbangkan untuk mengurangi jumlah transaksi dan fokus pada kualitas keputusan."
            ),
            "severe": (
                "Pola **overconfidence berat** terdeteksi: Anda bertransaksi terlalu sering "
                "dengan hasil di bawah rata-rata pasar. Kurangi intensitas transaksi dan "
                "evaluasi setiap keputusan secara lebih kritis."
            ),
        },
        "lai": {
            "mild": (
                "Pola **loss aversion ringan** terdeteksi: Anda cenderung menahan posisi "
                "merugi sedikit lebih lama dari yang optimal."
            ),
            "moderate": (
                "Dalam sesi ini, **loss aversion Anda berada di tingkat sedang** — Anda "
                "menahan posisi yang merugi secara tidak proporsional dibanding posisi untung. "
                "Coba tetapkan batas kerugian maksimum sebelum membuka posisi."
            ),
            "severe": (
                "Dalam sesi ini, **loss aversion Anda berada di tingkat berat** — Anda menahan "
                "posisi merugi jauh lebih lama dari posisi untung. Terapkan disiplin cut-loss "
                "yang konsisten untuk melindungi modal Anda."
            ),
        },
    }

    return _SUMMARIES[best_key][severity]

_INTERACTION_THRESHOLD = 0.65  # Strong coupling threshold (Cohen 1988)
_MIN_SESSIONS_FOR_INTERACTION = 3   # FIXED: align with interaction.py minimum (was 5, caused UAT suppression)

_BIAS_METRIC_KEY: dict[str, str] = {
    "overconfidence": "overconfidence_score",
    "disposition_effect": "disposition_dei",
    "loss_aversion": "loss_aversion_index",
}


def _classify_bias_trajectory(
    db_session: Session,
    user_id: int,
    current_session_id: str,
    bias_type: str,
) -> str:
    """Classify the 3-session trend for a specific bias type.

    Fetches the last 3 BiasMetric records (excluding the current session),
    normalises the relevant metric to [0, 1], and returns a trajectory label.

    Normalisation (mirrors stability index logic):
      - overconfidence_score: already in [0, 1) — unchanged.
      - disposition_dei: abs(DEI) — captures magnitude regardless of sign.
      - loss_aversion_index: min(LAI / LAI_EMA_CEILING, 1.0).

    Returns:
        "improving"   — strictly decreasing over the 3 sessions (oldest→newest)
        "worsening"   — strictly increasing over the 3 sessions
        "volatile"    — non-monotonic (oscillating) pattern
        "stable"      — all three values within 0.05 of each other
        "insufficient"— fewer than 3 prior sessions available
    """
    col_name = _BIAS_METRIC_KEY.get(bias_type)
    if col_name is None:
        return "insufficient"

    prior_metrics = (
        db_session.query(BiasMetric)
        .filter(
            BiasMetric.user_id == user_id,
            BiasMetric.session_id != current_session_id,
        )
        .order_by(BiasMetric.computed_at.asc())
        .all()
    )

    if len(prior_metrics) < 3:
        return "insufficient"

    # Take last 3 prior sessions (oldest → newest for trend direction)
    last_three = prior_metrics[-3:]

    def _normalize(metric: BiasMetric) -> float:
        if bias_type == "overconfidence":
            return metric.overconfidence_score or 0.0
        elif bias_type == "disposition_effect":
            return abs(metric.disposition_dei or 0.0)
        else:  # loss_aversion
            return min((metric.loss_aversion_index or 0.0) / LAI_EMA_CEILING, 1.0)

    vals = [_normalize(m) for m in last_three]
    a, b, c = vals[0], vals[1], vals[2]

    # Stability band: all values within 0.05 of each other → stable
    if max(vals) - min(vals) < 0.05:
        return "stable"

    if c < b < a:
        return "improving"
    if c > b > a:
        return "worsening"
    return "volatile"


def _get_cdt_modifier(
    db_session: Session,
    user_id: int,
    session_id: str,
    bias_type: str,
    current_severity: str,
    profile: CognitiveProfile,
) -> str:
    """Generate a CDT-aware contextual sentence appended to feedback explanation.

    Uses 3-session trajectory analysis when ≥ 3 prior sessions exist.
    Falls back to single-lag comparison for exactly 2 prior sessions.
    Returns empty string when fewer than 3 total sessions are completed
    or when no notable trend or stability pattern is detected.

    Args:
        db_session:       Active SQLAlchemy session.
        user_id:          ID of the user.
        session_id:       Current session UUID (excluded from prior-metric queries).
        bias_type:        One of "overconfidence", "disposition_effect", "loss_aversion".
        current_severity: Severity label for this session.
        profile:          Current CognitiveProfile.

    Returns:
        A Bahasa Indonesia modifier string, or "".
    """
    if profile.session_count < 3:
        return ""

    modifiers: list[str] = []

    # --- 3-session trajectory analysis ---
    trajectory = _classify_bias_trajectory(
        db_session, user_id, session_id, bias_type
    )

    if trajectory == "improving" and current_severity != "none":
        modifiers.append(
            "Tren positif terdeteksi: intensitas bias ini menurun secara konsisten "
            "dalam 3 sesi terakhir — umpan balik yang Anda terima menunjukkan dampak."
        )
    elif trajectory == "improving" and current_severity == "none":
        modifiers.append(
            "Tren positif terdeteksi: bias ini tidak lagi signifikan setelah menurun "
            "secara konsisten dalam 3 sesi terakhir. Pertahankan pola ini!"
        )
    elif trajectory == "worsening":
        modifiers.append(
            "Perhatian: intensitas bias ini meningkat secara konsisten dalam 3 sesi "
            "terakhir. Tinjau kembali strategi keputusan investasi Anda secara mendasar."
        )
    elif trajectory == "volatile":
        modifiers.append(
            "Pola tidak konsisten: bias ini berfluktuasi antar sesi, mengindikasikan "
            "bahwa keputusan Anda mungkin dipengaruhi oleh kondisi pasar sesi tertentu "
            "daripada pola perilaku yang menetap."
        )
    elif trajectory == "insufficient":
        # Fewer than 3 prior sessions — fall back to single-lag comparison
        prev_feedback = (
            db_session.query(FeedbackHistory)
            .filter_by(user_id=user_id, bias_type=bias_type)
            .filter(FeedbackHistory.session_id != session_id)
            .order_by(FeedbackHistory.delivered_at.desc())
            .first()
        )
        if prev_feedback:
            curr_rank = _SEVERITY_RANK.get(current_severity, 0)
            prev_rank = _SEVERITY_RANK.get(prev_feedback.severity, 0)
            if curr_rank < prev_rank and current_severity != "none":
                modifiers.append(
                    "Perkembangan positif: kecenderungan bias ini menurun dibanding "
                    "sesi sebelumnya."
                )
            elif curr_rank > prev_rank:
                modifiers.append(
                    "Perhatian: intensitas bias ini meningkat dari sesi sebelumnya."
                )
    # trajectory == "stable": no modifier needed (no trend to report)

    # --- Persistent-pattern warning (independent of trajectory) ---
    if (
        profile.stability_index > CDT_MODIFIER_STABILITY_THRESHOLD
        and current_severity in ("moderate", "severe")
    ):
        modifiers.append(
            "Pola ini terdeteksi konsisten di beberapa sesi terakhir — "
            "pertimbangkan untuk mengubah strategi trading Anda secara lebih mendasar."
        )

    return " ".join(modifiers)


def _get_interaction_modifier(profile: CognitiveProfile) -> list[str]:
    """Return Bahasa Indonesia insight strings for strong cross-bias couplings.

    Reads interaction_scores from the CognitiveProfile (already computed and
    stored by update_profile() via compute_interaction_scores()).

    Returns an empty list when:
      - session_count < _MIN_SESSIONS_FOR_INTERACTION (insufficient data)
      - interaction_scores is None or empty
      - No pairwise r exceeds ±_INTERACTION_THRESHOLD

    Returns:
        List of insight strings (Bahasa Indonesia). Typically 0–2 items.
    """
    if profile.session_count < _MIN_SESSIONS_FOR_INTERACTION:
        return []

    scores = profile.interaction_scores
    if not scores:
        return []

    insights: list[str] = []

    ocs_dei = scores.get("ocs_dei")
    ocs_lai = scores.get("ocs_lai")
    dei_lai = scores.get("dei_lai")

    # OCS ↔ DEI: Overtrading often co-occurs with premature winner liquidation
    if ocs_dei is not None and abs(ocs_dei) >= _INTERACTION_THRESHOLD:
        if ocs_dei > 0:
            insights.append(
                "Sistem mendeteksi pola gabungan antara overconfidence dan efek "
                "disposisi: frekuensi trading yang tinggi cenderung muncul bersamaan "
                "dengan kecenderungan menjual keuntungan terlalu cepat. "
                "Pertimbangkan untuk mengurangi intensitas transaksi dan memberikan "
                "lebih banyak waktu bagi posisi menguntungkan untuk berkembang."
            )
        else:
            insights.append(
                "Pola kompensasi terdeteksi: ketika frekuensi trading meningkat, "
                "Anda justru cenderung menahan posisi menguntungkan lebih lama — "
                "ini mengindikasikan kehati-hatian yang lebih besar saat aktif trading."
            )

    # OCS ↔ LAI: High trading activity co-occurs with reluctance to cut losses
    if ocs_lai is not None and abs(ocs_lai) >= _INTERACTION_THRESHOLD:
        if ocs_lai > 0:
            insights.append(
                "Pola menarik terdeteksi: semakin sering Anda bertransaksi, semakin "
                "lama Anda menahan posisi yang merugi. Ini mengindikasikan bahwa "
                "aktivitas trading yang tinggi mungkin dipengaruhi oleh keengganan "
                "untuk merealisasi kerugian — kombinasi yang dapat menggerus modal "
                "secara signifikan."
            )
        else:
            insights.append(
                "Pola kompensasi terdeteksi: sesi dengan aktivitas trading tinggi "
                "justru disertai pengelolaan kerugian yang lebih disiplin. "
                "Ini adalah tanda kesadaran diri yang berkembang."
            )

    # DEI ↔ LAI: Both biases reinforce each other — selling winners too fast
    # AND holding losers too long amplifies portfolio damage
    if dei_lai is not None and abs(dei_lai) >= _INTERACTION_THRESHOLD:
        if dei_lai > 0:
            insights.append(
                "Dua pola bias yang saling memperkuat terdeteksi secara konsisten: "
                "Anda cenderung menjual keuntungan terlalu cepat sekaligus menahan "
                "kerugian terlalu lama. Kombinasi ini secara bersamaan memperbesar "
                "kerugian dan memperkecil keuntungan — dampaknya terhadap portofolio "
                "lebih besar dari kedua bias secara terpisah."
            )
        else:
            insights.append(
                "Pola kompensasi terdeteksi antara efek disposisi dan loss aversion: "
                "keduanya tidak selalu muncul bersamaan dalam perilaku trading Anda, "
                "menandakan pengendalian diri yang mulai berkembang pada salah satu dimensi."
            )

    return insights


def generate_feedback(
    db_session: Session,
    user_id: int,
    session_id: str,
    bias_metric: BiasMetric,
    profile: CognitiveProfile,
    realized_trades: list[dict] | None = None,
    open_positions: list[dict] | None = None,
) -> list[FeedbackHistory]:
    """Generate and persist FeedbackHistory records for a completed session.

    One FeedbackHistory row is created per bias type (always 3 rows, even for
    severity="none", so the renderer can display a green "no bias" card).

    Args:
        db_session:      Active SQLAlchemy session.
        user_id:         ID of the user.
        session_id:      UUID string of the session.
        bias_metric:     Computed BiasMetric for this session.
        profile:         Current CognitiveProfile.
        realized_trades: Optional list from SessionFeatures (for counterfactual).
        open_positions:  Optional list from SessionFeatures (for counterfactual).

    Returns:
        List of 3 persisted FeedbackHistory instances.
    """
    realized_trades = realized_trades or []
    open_positions = open_positions or []

    # Actual buy+sell action count from DB (Bug 2 fix)
    trade_count = (
        db_session.query(UserAction)
        .filter_by(user_id=user_id, session_id=session_id)
        .filter(UserAction.action_type.in_(["buy", "sell"]))
        .count()
    )

    has_trades = (
        bool(realized_trades)
        or bool(open_positions)
        or trade_count > 0
        or (bias_metric.overconfidence_score or 0) > 1e-9
        or (bias_metric.loss_aversion_index or 0) > 1e-9
    )

    win_count = sum(1 for t in realized_trades if t["sell_price"] > t["buy_price"])
    loss_count = sum(1 for t in realized_trades if t["sell_price"] < t["buy_price"])

    # Pre-compute severities so counterfactuals are only generated when needed
    dei_val_abs = abs(bias_metric.disposition_dei or 0.0)
    dei_severity_pre = classify_severity(dei_val_abs, DEI_SEVERE, DEI_MODERATE, DEI_MILD)
    ocs_val_pre = bias_metric.overconfidence_score or 0.0
    lai_val_pre = bias_metric.loss_aversion_index or 0.0

    # Counterfactual text — only computed for severe cases to avoid wasted work
    counterfactual_disp = (
        compute_counterfactual(
            db_session, realized_trades, open_positions,
            session_id=session_id,
        )
        if dei_severity_pre == "severe"
        else ""
    )
    counterfactual_oc = (
        "Dengan mengurangi frekuensi trading, Anda bisa menghemat lebih banyak modal "
        "untuk peluang yang benar-benar menjanjikan."
        if ocs_val_pre >= OCS_SEVERE else ""
    )
    counterfactual_la = (
        "Posisi merugi yang Anda pertahankan mengunci modal yang bisa digunakan "
        "untuk peluang investasi lainnya."
        if lai_val_pre >= LAI_SEVERE else ""
    )

    # Slot values
    dei_val = bias_metric.disposition_dei or 0.0
    pgr_val = bias_metric.disposition_pgr or 0.0
    plr_val = bias_metric.disposition_plr or 0.0
    ocs_val = bias_metric.overconfidence_score or 0.0
    lai_val = bias_metric.loss_aversion_index or 0.0

    bias_configs = [
        {
            "bias_type": "disposition_effect",
            "value": abs(dei_val),
            "severe_t": DEI_SEVERE,
            "moderate_t": DEI_MODERATE,
            "mild_t": DEI_MILD,
            "min_sample_met": len(realized_trades) >= MIN_TRADES_FOR_FULL_SEVERITY,
            "slots": {
                "dei": dei_val,
                "pgr": pgr_val,
                "plr": plr_val,
                "win_count": win_count,
                "loss_count": loss_count,
                "counterfactual_text": counterfactual_disp,
            },
        },
        {
            "bias_type": "overconfidence",
            "value": ocs_val,
            "severe_t": OCS_SEVERE,
            "moderate_t": OCS_MODERATE,
            "mild_t": OCS_MILD,
            "slots": {
                "ocs": ocs_val,
                "trade_count": trade_count,
                "counterfactual_text": counterfactual_oc,
            },
        },
        {
            "bias_type": "loss_aversion",
            "value": lai_val,
            "severe_t": LAI_SEVERE,
            "moderate_t": LAI_MODERATE,
            "mild_t": LAI_MILD,
            "min_sample_met": len(realized_trades) >= MIN_TRADES_FOR_FULL_SEVERITY,
            "slots": {
                "lai": lai_val,
                "counterfactual_text": counterfactual_la,
            },
        },
    ]

    # ── Confidence override: suppress misleading severity when data is insufficient ──
    # Import is deferred to avoid circular imports at module load time.
    from modules.analytics.bias_metrics import (
        compute_disposition_effect_result,
        compute_loss_aversion_index_result,
    )
    from modules.analytics.features import SessionFeatures as _SF

    _sf_for_gate = _SF(user_id=user_id, session_id=session_id)
    _sf_for_gate.realized_trades = realized_trades
    _sf_for_gate.open_positions = open_positions

    dei_result = compute_disposition_effect_result(_sf_for_gate)
    lai_result = compute_loss_aversion_index_result(_sf_for_gate)

    records: list[FeedbackHistory] = []
    for cfg in bias_configs:
        severity = classify_severity(
            cfg["value"],
            cfg["severe_t"],
            cfg["moderate_t"],
            cfg.get("mild_t"),
            min_sample_met=cfg.get("min_sample_met", True),
        )

        # When DEI or LAI data is insufficient, downgrade severity to "none"
        # so the feedback template does not mischaracterize the user's behavior.
        # Only override when BiasMetric itself also shows no evidence of trades
        # (guards against the case where realized_trades is not passed but
        # the BiasMetric was computed from real data in the DB).
        _bias_pgr = bias_metric.disposition_pgr or 0.0
        _bias_plr = bias_metric.disposition_plr or 0.0
        _bias_dei = abs(bias_metric.disposition_dei or 0.0)
        _bias_has_trade_evidence = _bias_pgr > 1e-9 or _bias_plr > 1e-9 or _bias_dei > 1e-9
        _bias_lai = bias_metric.loss_aversion_index or 0.0

        if (cfg["bias_type"] == "disposition_effect"
                and dei_result.confidence == "insufficient"
                and not _bias_has_trade_evidence):
            severity = "none"
            logger.debug("generate_feedback: DEI confidence=insufficient → severity forced to none")
        if (cfg["bias_type"] == "loss_aversion"
                and lai_result.confidence == "insufficient"
                and not _bias_has_trade_evidence
                and _bias_lai < 1e-9):
            severity = "none"
            logger.debug("generate_feedback: LAI confidence=insufficient → severity forced to none")

        logger.debug("bias=%s value=%.3f severity=%s", cfg["bias_type"], cfg["value"], severity)

        if not has_trades:
            severity = "none"
            explanation = (
                f"Data transaksi tidak cukup untuk menganalisis "
                f"{cfg['bias_type'].replace('_', ' ')} pada sesi ini. "
                f"Cobalah untuk melakukan beberapa transaksi beli dan jual "
                f"pada sesi berikutnya agar sistem dapat mengevaluasi pola keputusan Anda."
            )
            recommendation = (
                "Lakukan setidaknya beberapa transaksi beli dan jual pada sesi berikutnya "
                "untuk memungkinkan analisis bias yang bermakna."
            )
        elif severity == "none":
            explanation = (
                f"Tidak terdeteksi bias {cfg['bias_type'].replace('_', ' ')} yang "
                f"signifikan pada sesi ini. Pertahankan pola pengambilan keputusan "
                f"yang baik ini!"
            )
            recommendation = "Terus pantau keputusan investasi Anda dan jaga konsistensi."
        else:
            tmpl = TEMPLATES[cfg["bias_type"]][severity]
            # Use defaultdict so missing slots become empty strings (Bug 7 fix)
            safe_slots = defaultdict(str, cfg["slots"])
            explanation = tmpl["explanation"].format_map(safe_slots)
            recommendation = tmpl["recommendation"].format_map(safe_slots)

        # Append CDT-aware longitudinal modifier when applicable
        if has_trades and severity != "none":
            cdt_mod = _get_cdt_modifier(
                db_session, user_id, session_id, cfg["bias_type"], severity, profile
            )
            if cdt_mod:
                explanation = explanation + " " + cdt_mod

        record = FeedbackHistory(
            user_id=user_id,
            session_id=session_id,
            bias_type=cfg["bias_type"],
            severity=severity,
            explanation_text=explanation,
            recommendation_text=recommendation,
            delivered_at=datetime.now(UTC),
        )
        db_session.add(record)
        records.append(record)

    db_session.flush()
    return records


def get_session_feedback(
    db_session: Session, user_id: int, session_id: str
) -> list[FeedbackHistory]:
    """Retrieve all FeedbackHistory records for a specific session.

    Args:
        db_session: Active SQLAlchemy session.
        user_id:    ID of the user.
        session_id: UUID string of the session.

    Returns:
        List of FeedbackHistory instances.
    """
    return (
        db_session.query(FeedbackHistory)
        .filter_by(user_id=user_id, session_id=session_id)
        .order_by(FeedbackHistory.delivered_at)
        .all()
    )


def get_longitudinal_summary(db_session: Session, user_id: int) -> dict:
    """Summarise bias severity trends across all sessions for a user.

    Args:
        db_session: Active SQLAlchemy session.
        user_id:    ID of the user.

    Returns:
        Dict with keys: sessions (list of session_id), trend (dict of bias_type →
        list of severity labels per session), latest (dict of bias_type → severity).
    """
    all_feedback = (
        db_session.query(FeedbackHistory)
        .filter_by(user_id=user_id)
        .order_by(FeedbackHistory.delivered_at)
        .all()
    )

    sessions_ordered: list[str] = []
    seen: set[str] = set()
    for f in all_feedback:
        if f.session_id not in seen:
            sessions_ordered.append(f.session_id)
            seen.add(f.session_id)

    trend: dict[str, list[str]] = {
        "disposition_effect": [],
        "overconfidence": [],
        "loss_aversion": [],
    }
    for sid in sessions_ordered:
        session_fb = [f for f in all_feedback if f.session_id == sid]
        for bias_type in trend:
            match = next((f for f in session_fb if f.bias_type == bias_type), None)
            trend[bias_type].append(match.severity if match else "none")

    latest = {
        bias_type: trend[bias_type][-1] if trend[bias_type] else "none"
        for bias_type in trend
    }

    return {"sessions": sessions_ordered, "trend": trend, "latest": latest}
