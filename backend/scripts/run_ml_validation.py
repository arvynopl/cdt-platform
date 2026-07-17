#!/usr/bin/env python3
"""
This script validates the deterministic bias detection formulas using a decision tree
classifier. Feature importance output supports Bab VI Section 6.X of the thesis report.

Keluaran (Output files, all saved to reports/):
    ml_feature_importance.png   — Bar chart horizontal 10 fitur teratas (Plotly/matplotlib)
    ml_decision_tree.png        — Visualisasi pohon keputusan (scikit-learn plot_tree)
    ml_classification_report.csv — Laporan klasifikasi per-kelas (precision/recall/F1)
    ml_summary.json             — Ringkasan statistik keseluruhan

Penggunaan:
    python scripts/run_ml_validation.py

Dependensi tambahan (tidak ada dalam requirements.txt bawaan):
    pip install scikit-learn matplotlib kaleido
    kaleido hanya diperlukan untuk ekspor PNG via Plotly; jika tidak ada, script
    otomatis beralih ke matplotlib untuk semua output gambar.

Catatan Data Sintetis (Synthetic Data Fallback):
    Jika database memiliki kurang dari MIN_REAL_RECORDS (20) rekaman BiasMetric
    berlabel, skrip ini secara otomatis menghasilkan data sintetis menggunakan
    5 persona investor yang merepresentasikan spektrum bias perilaku penuh:

        1. Investor Seimbang       — tidak ada bias signifikan (OCS rendah, DEI~0, LAI<1.2)
        2. Trader Overconfident    — OCS tinggi (≥0.4), frekuensi perdagangan sangat aktif
        3. Investor Efek Disposisi — DEI tinggi (≥0.25), menjual pemenang/menahan pecundang
        4. Investor Aversi Kerugian — LAI tinggi (≥1.5), menahan posisi rugi jauh lebih lama
        5. Investor Multi-Bias     — kombinasi OCS + DEI + LAI semuanya moderat-parah

    Setiap persona menghasilkan 8 sesi dengan noise Gaussian (random_state=42).
    Persona-persona ini mencerminkan pola perilaku yang diamati dalam skenario
    validasi FR02 (tests/test_validation_scenarios.py) dan dikalibrasi terhadap
    threshold keparahan dalam config.py (OCS_MILD=0.20, DEI_MILD=0.05, LAI_MILD=1.20).
    Data sintetis ditandai dalam ml_summary.json (used_synthetic_data: true).
"""

from __future__ import annotations

import csv
import json
import logging
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — allow importing project modules regardless of CWD
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
from config import LAI_EMA_CEILING  # noqa: E402  (after sys.path insert)
from database.connection import get_session, init_db  # noqa: E402
from database.models import BiasMetric  # noqa: E402
from modules.cdt.ml_validator import (  # noqa: E402
    FEATURE_LABELS_ID,
    SEVERITY_ORDER,
    build_feature_matrix,
    derive_worst_severity,
    train_bias_classifier,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPORTS_DIR = _REPO_ROOT / "reports"
MIN_REAL_RECORDS = 20           # DB records required before synthetic fallback kicks in
SYNTHETIC_SESSIONS_PER_PERSONA = 8
CHART_DPI = 150
TOP_N_FEATURES = 10

# Colour palette — matches Streamlit dark theme (#0e1117 background)
DARK_BG = "#0e1117"
DARK_PANEL = "#1a1a2e"
ACCENT_HIGH = "#e74c3c"     # High importance (≥ 0.15)
ACCENT_MED = "#ff7b25"      # Medium importance (0.08–0.15)
ACCENT_LOW = "#4c9be8"      # Low importance (< 0.08)
TEXT_COLOR = "#ffffff"
GRID_COLOR = "#2d2d2d"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity translations (Bahasa Indonesia)
# ---------------------------------------------------------------------------
_SEVERITY_ID: dict[str, str] = {
    "none":         "Tidak Ada Bias",
    "mild":         "Ringan",
    "moderate":     "Sedang",
    "severe":       "Parah",
    "accuracy":     "Akurasi Keseluruhan",
    "macro avg":    "Rata-rata Makro",
    "weighted avg": "Rata-rata Tertimbang",
}

# ---------------------------------------------------------------------------
# Synthetic data — 5 investor personas
# ---------------------------------------------------------------------------
# Each tuple: (name, ocs_center, dei_center, lai_center,
#              trade_freq_center, hold_ratio_center, ret_frac_center, realized_count_center)
_PERSONAS: list[tuple] = [
    # 1 — Balanced investor: no significant bias
    ("Investor Seimbang",        0.10, 0.02, 0.90, 0.35, 0.65,  0.005, 2),
    # 2 — Overconfident trader: high OCS, very active, underperforms
    ("Trader Overconfident",     0.60, 0.06, 1.10, 0.85, 0.15, -0.020, 6),
    # 3 — Disposition effect: high DEI, sells winners / holds losers
    ("Investor Efek Disposisi",  0.18, 0.50, 1.05, 0.45, 0.55, -0.010, 4),
    # 4 — Loss averse: high LAI, holds losing positions far longer than winners
    ("Investor Aversi Kerugian", 0.12, 0.03, 2.10, 0.28, 0.72, -0.015, 3),
    # 5 — Multi-bias: elevated OCS + DEI + LAI simultaneously
    ("Investor Multi-Bias",      0.55, 0.35, 1.80, 0.70, 0.30, -0.025, 5),
]


def generate_synthetic_data() -> tuple[list[list[float]], list[str], list[str]]:
    """Generate synthetic feature vectors for 5 scripted investor personas.

    Each persona is sampled SYNTHETIC_SESSIONS_PER_PERSONA times with
    Gaussian noise (random_state=42) to simulate realistic session variance.
    Severity labels are derived from the same thresholds used in the live
    pipeline (derive_worst_severity from ml_validator.py).

    Returns:
        Tuple ``(X, y, persona_names)``:
            X             — Feature matrix (list of 10-element float lists).
            y             — Severity labels (list[str]).
            persona_names — Per-row persona name (list[str]).
    """
    rng = random.Random(42)

    def _clip01(v: float) -> float:
        return max(0.0, min(1.0, v))

    def _clip_lai(v: float) -> float:
        return max(0.0, min(3.5, v))

    X: list[list[float]] = []
    y: list[str] = []
    names: list[str] = []

    for persona_name, ocs_c, dei_c, lai_c, tf_c, hr_c, ret_c, rc_c in _PERSONAS:
        for _ in range(SYNTHETIC_SESSIONS_PER_PERSONA):
            ocs_v = _clip01(ocs_c + rng.gauss(0, 0.05))
            dei_v = dei_c + rng.gauss(0, 0.05)       # signed; abs used as feature
            lai_v = _clip_lai(lai_c + rng.gauss(0, 0.20))

            # PGR and PLR consistent with DEI = PGR − PLR
            abs_dei_v = abs(dei_v)
            pgr_v = _clip01(0.35 + abs_dei_v / 2.0 + rng.gauss(0, 0.05))
            plr_v = _clip01(pgr_v - abs_dei_v + rng.gauss(0, 0.03))

            tf_v = _clip01(tf_c + rng.gauss(0, 0.08))
            hr_v = _clip01(1.0 - tf_v + rng.gauss(0, 0.05))
            ret_v = ret_c + rng.gauss(0, 0.01)
            rc_raw = rc_c + rng.randint(-1, 1)
            rc_v = min(1.0, max(0.0, rc_raw / 10.0))
            lai_norm = min(lai_v / LAI_EMA_CEILING, 1.0)

            row = [
                ocs_v,
                abs_dei_v,
                lai_norm,
                pgr_v,
                plr_v,
                tf_v,
                hr_v,
                ret_v,
                rc_v,
                ocs_v * lai_norm,   # interaction term
            ]
            X.append(row)
            y.append(derive_worst_severity(ocs_v, dei_v, lai_v))
            names.append(persona_name)

    logger.info(
        "Generated %d synthetic samples from %d personas.",
        len(X), len(_PERSONAS),
    )
    return X, y, names


# ---------------------------------------------------------------------------
# Database loading
# ---------------------------------------------------------------------------

def load_from_database() -> tuple[list[list[float]], list[str], list]:
    """Load all BiasMetric records and build the feature matrix.

    Calls ``build_feature_matrix()`` from ml_validator.py which internally
    calls ``extract_session_features()`` to enrich features with session-level
    behavioural data (trade frequency, hold ratio, etc.).

    Returns:
        ``(X, y, metrics)`` — feature matrix, severity labels, and raw BiasMetric objects.
        Returns ``([], [], [])`` on any DB error or if the table is empty.
    """
    try:
        init_db()
        with get_session() as db:
            metrics = db.query(BiasMetric).all()
            if not metrics:
                logger.info("No BiasMetric records found in the database.")
                return [], [], []
            X, y, _ = build_feature_matrix(db, metrics)
            logger.info("Loaded %d BiasMetric records from database.", len(X))
            return X, y, metrics
    except Exception as exc:
        logger.warning("Database load failed (%s) — will use synthetic data only.", exc)
        return [], [], []


# ---------------------------------------------------------------------------
# Chart: feature importance horizontal bar chart
# ---------------------------------------------------------------------------

def _bar_color(importance: float) -> str:
    """Return accent colour based on feature importance magnitude."""
    if importance >= 0.15:
        return ACCENT_HIGH
    if importance >= 0.08:
        return ACCENT_MED
    return ACCENT_LOW


def _plotly_feature_importance(
    labels_id: list[str],
    values: list[float],
    output_path: Path,
) -> bool:
    """Attempt PNG export via Plotly + kaleido.  Returns True on success."""
    try:
        import plotly.graph_objects as go  # type: ignore
    except ImportError:
        return False

    bar_colors = [_bar_color(v) for v in values]

    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels_id,
            orientation="h",
            marker=dict(color=bar_colors, line=dict(color="#444444", width=0.4)),
            text=[f"{v:.4f}" for v in values],
            textposition="outside",
            textfont=dict(color=TEXT_COLOR, size=11),
        )
    )
    n_show = len(values)
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=DARK_BG,
        plot_bgcolor=DARK_PANEL,
        title=dict(
            text=(
                f"<b>{n_show} Fitur Teratas — Klasifikasi Bias Perilaku Investor</b><br>"
                "<sup>Pohon Keputusan (max_depth=4, criterion=gini) · "
                "Validasi ML Bab VI Thesis</sup>"
            ),
            font=dict(size=15, color=TEXT_COLOR),
            x=0.5,
            xanchor="center",
        ),
        xaxis=dict(
            title=dict(
                text="Tingkat Kepentingan Fitur (Gini Importance)",
                font=dict(size=13, color="#cccccc"),
            ),
            tickfont=dict(color=TEXT_COLOR),
            gridcolor=GRID_COLOR,
            zeroline=False,
            range=[0, max(values) * 1.20],
        ),
        yaxis=dict(
            title="",
            tickfont=dict(size=12, color=TEXT_COLOR),
            gridcolor=GRID_COLOR,
        ),
        margin=dict(l=310, r=130, t=110, b=65),
        height=520,
        width=1150,
    )

    try:
        import kaleido  # noqa: F401
        fig.write_image(str(output_path), width=1150, height=520, scale=2)
        logger.info("Feature importance chart saved (Plotly+kaleido): %s", output_path)
        return True
    except (ImportError, RuntimeError, Exception) as exc:
        logger.warning(
            "Plotly/kaleido PNG export unavailable (%s) — falling back to matplotlib.",
            type(exc).__name__,
        )
        return False


def _matplotlib_feature_importance(
    labels_id: list[str],
    values: list[float],
    output_path: Path,
) -> None:
    """Matplotlib fallback for feature importance bar chart."""
    try:
        import matplotlib  # type: ignore
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
    except ImportError:
        logger.warning("matplotlib not available — cannot export feature importance PNG.")
        return

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(11, 6), facecolor=DARK_BG)
    ax.set_facecolor(DARK_PANEL)

    bar_colors = [_bar_color(v) for v in values]
    bars = ax.barh(labels_id, values, color=bar_colors, edgecolor="#555555", linewidth=0.5)
    for bar, val in zip(bars, values, strict=False):
        ax.text(
            bar.get_width() + max(values) * 0.015,
            bar.get_y() + bar.get_height() / 2,
            f"{val:.4f}",
            va="center", ha="left", fontsize=9, color=TEXT_COLOR,
        )

    ax.set_xlabel(
        "Tingkat Kepentingan Fitur (Gini Importance)",
        color="#cccccc", fontsize=11,
    )
    ax.set_title(
        f"{len(values)} Fitur Teratas — Klasifikasi Bias Perilaku Investor\n"
        "Pohon Keputusan (max_depth=4) · Validasi ML Bab VI",
        color=TEXT_COLOR, fontsize=12, pad=14,
    )
    ax.tick_params(colors=TEXT_COLOR, labelsize=10)
    for spine in ax.spines.values():
        spine.set_color("#444444")
    ax.grid(axis="x", color=GRID_COLOR, linestyle="--", alpha=0.6, linewidth=0.7)
    ax.set_xlim(0, max(values) * 1.25)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=CHART_DPI, bbox_inches="tight", facecolor=DARK_BG)
    plt.close(fig)
    logger.info("Feature importance chart saved (matplotlib): %s", output_path)


def plot_feature_importance(
    feature_names: list[str],
    importances: list[float],
    output_path: Path,
    top_n: int = TOP_N_FEATURES,
) -> None:
    """Export a horizontal bar chart of decision-tree feature importances.

    Tries Plotly + kaleido first; falls back to matplotlib if kaleido is absent.

    Args:
        feature_names: Feature key names (from DECISION_TREE_FEATURE_NAMES).
        importances:   Gini importance values from the fitted classifier.
        output_path:   Destination .png file path.
        top_n:         Maximum number of features to display (default 10).
    """
    # Sort ascending (lowest importance first) so highest appears at top of chart
    pairs = sorted(zip(feature_names, importances, strict=False), key=lambda p: p[1])
    n_show = min(top_n, len(pairs))
    pairs = pairs[-n_show:]

    labels_id = [FEATURE_LABELS_ID.get(fn, fn) for fn, _ in pairs]
    values = [imp for _, imp in pairs]

    if not _plotly_feature_importance(labels_id, values, output_path):
        _matplotlib_feature_importance(labels_id, values, output_path)


# ---------------------------------------------------------------------------
# Chart: decision tree visualization
# ---------------------------------------------------------------------------

def plot_decision_tree(
    clf,
    feature_names: list[str],
    class_names: list[str],
    output_path: Path,
) -> None:
    """Export the fitted decision tree as a PNG using sklearn plot_tree.

    Requires matplotlib (and optionally scikit-learn, which is already needed
    to train the classifier).

    Args:
        clf:           Fitted DecisionTreeClassifier.
        feature_names: Ordered list of feature name keys.
        class_names:   Ordered class labels present in training data.
        output_path:   Destination .png file path.
    """
    try:
        import matplotlib  # type: ignore
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
        from sklearn.tree import plot_tree  # type: ignore
    except ImportError as exc:
        logger.warning("Cannot export decision tree PNG (%s).", exc)
        return

    feature_labels = [FEATURE_LABELS_ID.get(fn, fn) for fn in feature_names]
    class_labels_id = [_SEVERITY_ID.get(c, c) for c in class_names]

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(24, 12), facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG)

    plot_tree(
        clf,
        ax=ax,
        feature_names=feature_labels,
        class_names=class_labels_id,
        filled=True,
        rounded=True,
        impurity=True,
        proportion=False,
        fontsize=7,
    )
    ax.set_title(
        "Pohon Keputusan — Klasifikasi Tingkat Keparahan Bias Perilaku Investor\n"
        "Validasi ML Sistem CDT · Bab VI Thesis",
        color=TEXT_COLOR, fontsize=13, pad=18,
    )

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=CHART_DPI, bbox_inches="tight", facecolor=DARK_BG)
    plt.close(fig)
    logger.info("Decision tree chart saved: %s", output_path)


# ---------------------------------------------------------------------------
# Export: classification report CSV
# ---------------------------------------------------------------------------

def export_classification_report_csv(report_dict: dict, output_path: Path) -> None:
    """Write sklearn classification_report dict to a UTF-8 CSV file.

    Columns: kelas, precision, recall, f1_score, support, accuracy

    Args:
        report_dict: Dict returned by ``classification_report(..., output_dict=True)``.
        output_path: Destination .csv file path.
    """
    fieldnames = ["kelas", "precision", "recall", "f1_score", "support", "accuracy"]
    rows: list[dict] = []

    for cls, vals in report_dict.items():
        if cls == "accuracy":
            rows.append({
                "kelas":     _SEVERITY_ID.get(cls, cls),
                "precision": "",
                "recall":    "",
                "f1_score":  "",
                "support":   "",
                "accuracy":  f"{vals:.4f}",
            })
        elif isinstance(vals, dict):
            rows.append({
                "kelas":     _SEVERITY_ID.get(cls, cls),
                "precision": f"{vals.get('precision', 0.0):.4f}",
                "recall":    f"{vals.get('recall', 0.0):.4f}",
                "f1_score":  f"{vals.get('f1-score', 0.0):.4f}",
                "support":   int(vals.get("support", 0)),
                "accuracy":  "",
            })

    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Classification report CSV saved: %s", output_path)


# ---------------------------------------------------------------------------
# Export: summary JSON
# ---------------------------------------------------------------------------

def export_summary_json(
    result: dict,
    used_synthetic: bool,
    n_db_records: int,
    output_path: Path,
) -> None:
    """Write overall training statistics to a JSON file.

    Args:
        result:         Dict returned by ``train_bias_classifier()``.
        used_synthetic: True if synthetic data was included in training.
        n_db_records:   Number of records actually loaded from the database.
        output_path:    Destination .json file path.
    """
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": (
            "DecisionTreeClassifier("
            "max_depth=4, criterion='gini', class_weight='balanced', "
            "min_samples_leaf=2, random_state=42)"
        ),
        "overall_accuracy": round(result["accuracy"], 4),
        "n_training_samples": result["n_samples"],
        "n_db_records": n_db_records,
        "used_synthetic_data": used_synthetic,
        "synthetic_personas": (
            [p[0] for p in _PERSONAS] if used_synthetic else []
        ),
        "class_counts": result["class_counts"],
        "feature_names": result["feature_names"],
        "notes": (
            "Akurasi dihitung pada data latih (in-sample). "
            "Untuk evaluasi generalisasi, lihat laporan klasifikasi per-kelas (CSV). "
            + (
                f"Data sintetis ditambahkan karena hanya ada {n_db_records} rekaman "
                f"di database (minimum diperlukan: {MIN_REAL_RECORDS})."
                if used_synthetic
                else "Dilatih sepenuhnya pada data BiasMetric dari database."
            )
        ),
    }

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    logger.info("Summary JSON saved: %s", output_path)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the full ML validation pipeline and export all output files."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("ML Validation Pipeline — CDT Bias Detection System")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Load real data from database
    # ------------------------------------------------------------------
    db_X, db_y, real_metrics = load_from_database()
    n_db_records = len(db_X)

    # ------------------------------------------------------------------
    # Step 2: Supplement with synthetic data when DB has < MIN_REAL_RECORDS
    # ------------------------------------------------------------------
    used_synthetic = False
    if n_db_records < MIN_REAL_RECORDS:
        logger.info(
            "DB has %d labelled records (min=%d). "
            "Adding synthetic data from %d personas × %d sessions.",
            n_db_records, MIN_REAL_RECORDS, len(_PERSONAS), SYNTHETIC_SESSIONS_PER_PERSONA,
        )
        syn_X, syn_y, _ = generate_synthetic_data()
        X = db_X + syn_X
        y = db_y + syn_y
        used_synthetic = True
    else:
        X = db_X
        y = db_y

    logger.info(
        "Total training samples: %d  (DB=%d, synthetic=%d)",
        len(X), n_db_records, len(X) - n_db_records,
    )

    # ------------------------------------------------------------------
    # Step 3: Train decision tree classifier
    # ------------------------------------------------------------------
    result = train_bias_classifier(X, y)
    if result is None:
        logger.error(
            "Training failed — ensure scikit-learn is installed "
            "(`pip install scikit-learn`) and there are >= 4 samples."
        )
        sys.exit(1)

    clf = result["classifier"]
    feature_names = result["feature_names"]
    importances: list[float] = clf.feature_importances_.tolist()
    class_names = sorted(set(y), key=lambda s: SEVERITY_ORDER.get(s, 99))

    logger.info(
        "Accuracy (in-sample): %.1f%% | Classes: %s",
        result["accuracy"] * 100,
        class_names,
    )

    # ------------------------------------------------------------------
    # Step 4: Export all outputs (idempotent — safe to re-run)
    # ------------------------------------------------------------------
    fi_path  = REPORTS_DIR / "ml_feature_importance.png"
    dt_path  = REPORTS_DIR / "ml_decision_tree.png"
    cr_path  = REPORTS_DIR / "ml_classification_report.csv"
    sum_path = REPORTS_DIR / "ml_summary.json"

    plot_feature_importance(feature_names, importances, fi_path, top_n=TOP_N_FEATURES)
    plot_decision_tree(clf, feature_names, class_names, dt_path)
    export_classification_report_csv(result["report"], cr_path)
    export_summary_json(result, used_synthetic, n_db_records, sum_path)

    logger.info("")
    logger.info("=== Semua output berhasil disimpan ke %s/ ===", REPORTS_DIR.name)
    logger.info("  %s", fi_path.relative_to(_REPO_ROOT))
    logger.info("  %s", dt_path.relative_to(_REPO_ROOT))
    logger.info("  %s", cr_path.relative_to(_REPO_ROOT))
    logger.info("  %s", sum_path.relative_to(_REPO_ROOT))

    # ── Post-UAT: per-bias classifiers ───────────────────────────────────────
    POST_UAT_MODE = n_db_records >= MIN_REAL_RECORDS

    if POST_UAT_MODE:
        print(f"\n[POST-UAT] {n_db_records} real records found — running per-bias classifiers.")
        from database.db import get_session as _get_session
        from modules.cdt.ml_validator import derive_per_bias_labels, train_per_bias_classifiers

        with _get_session() as _db:
            y_ocs, y_dei, y_lai = derive_per_bias_labels(_db, real_metrics)
        per_bias_results = train_per_bias_classifiers(db_X, y_ocs, y_dei, y_lai)

        if per_bias_results:
            for bias_key, res in per_bias_results.items():
                print(f"  [{bias_key.upper()}] accuracy={res['accuracy']:.3f}  "
                      f"n={res['n_samples']}  classes={list(res['class_counts'].keys())}")
                import json
                out = {
                    "bias":            bias_key,
                    "accuracy":        res["accuracy"],
                    "n_samples":       res["n_samples"],
                    "class_counts":    res["class_counts"],
                    "report":          res["report"],
                    "feature_names":   res["feature_names"],
                }
                report_path = REPORTS_DIR / f"per_bias_{bias_key}_summary.json"
                report_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
                print(f"  → Saved to {report_path}")
    else:
        print(f"\n[POST-UAT GATED] Only {n_db_records} real records "
              f"(minimum: {MIN_REAL_RECORDS}). Skipping per-bias classifiers.")
        print("   Re-run this script after UAT data collection is complete.")

    # ── Post-UAT: stratified k-fold cross-validation ─────────────────────────
    if POST_UAT_MODE:
        from sklearn.tree import DecisionTreeClassifier

        from modules.cdt.ml_validator import run_kfold_validation

        clf_template = DecisionTreeClassifier(
            max_depth=4,
            criterion="gini",
            class_weight="balanced",
            min_samples_leaf=2,
            random_state=42,
        )

        print("\n[POST-UAT] Running stratified 5-fold CV on combined severity labels.")
        kfold_result = run_kfold_validation(clf_template, X, y, k=5)

        if kfold_result:
            print(f"  K-fold CV: mean_accuracy={kfold_result['mean_accuracy']:.3f} "
                  f"± {kfold_result['std_accuracy']:.3f}")
            print(f"  Fold accuracies: {[f'{a:.3f}' for a in kfold_result['fold_accuracies']]}")

            import json
            kfold_path = REPORTS_DIR / "kfold_summary.json"
            kfold_path.write_text(json.dumps(kfold_result, indent=2))
            print(f"  → Saved to {kfold_path}")


if __name__ == "__main__":
    main()
