"""
config.py — Central configuration for the CDT Bias Detection System.

All tunable parameters, thresholds, and paths are defined here.

Environment variables:
    CDT_DATABASE_URL          — Override default sqlite path.
    CDT_BCRYPT_ROUNDS         — Override default bcrypt cost factor (12).
    CDT_ADMIN_TOKEN           — Token for ``?admin=...`` admin dashboard.
    CDT_RESEARCHER_PASSWORD   — Password for the hidden researcher view at
                                ``?view=researcher``. Unset → view disabled.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("CDT_DATABASE_URL", f"sqlite:///{BASE_DIR / 'cdt_bias.db'}")

# ---------------------------------------------------------------------------
# Simulation parameters
# ---------------------------------------------------------------------------
INITIAL_CAPITAL: float = 10_000_000.0   # Rp 10,000,000
ROUNDS_PER_SESSION: int = 14
PRE_WINDOW_DAYS: int = 30               # Days of history shown before the trading window

# ---------------------------------------------------------------------------
# CDT update weights (EMA)
# ---------------------------------------------------------------------------
ALPHA: float = 0.3   # Recency weight for bias intensity vector
BETA: float = 0.2    # Recency weight for risk preference
SURVEY_PRIOR_WEIGHT: float = 0.15  # Damping factor for survey-informed CDT priors
CDT_STABILITY_WINDOW: int = 5  # Number of past sessions used for stability index

# Adaptive alpha bounds for EMA (activity-weighted update rate)
# Low-activity sessions use ALPHA; fully-active sessions use ALPHA_MAX.
ALPHA_MAX: float = 0.45  # Upper bound for high-activity sessions (buy+sell fills all rounds)

# CDT state snapshot & feedback
LAI_EMA_CEILING: float = 3.0   # LAI is normalised as min(LAI/LAI_EMA_CEILING, 1) before EMA
CDT_MODIFIER_STABILITY_THRESHOLD: float = 0.75  # Stability above this triggers pattern-persistence modifier

# ---------------------------------------------------------------------------
# Bias severity thresholds
# ---------------------------------------------------------------------------
# Disposition Effect Index (DEI)
DEI_SEVERE: float = 0.5
DEI_MODERATE: float = 0.15
DEI_MILD: float = 0.05

# Overconfidence Score (OCS)
OCS_SEVERE: float = 0.7
OCS_MODERATE: float = 0.4
OCS_MILD: float = 0.2

# Loss Aversion Index (LAI)
LAI_SEVERE: float = 2.0
LAI_MODERATE: float = 1.5
LAI_MILD: float = 1.2

# Minimum realized trades required for DEI/LAI severity to be computed at all.
# With MIN=1, full severity applies as long as ≥1 round-trip is realized.
# Epistemic uncertainty is still communicated via confidence_gate() levels
# ("low"/"medium"/"high") — the severity cap is intentionally removed because
# in a 14-round session many rational buy-and-hold investors will not realize
# 3+ trades, and capping their severity underestimates actual bias tendency.
# Paper gains/losses already factor into DEI, so the metric is valid with 1 trade.
MIN_TRADES_FOR_FULL_SEVERITY: int = 1

# ---------------------------------------------------------------------------
# DEI formula variant selection
# ---------------------------------------------------------------------------
# If True (production default), use dollar-weighted DEI (Frazzini, 2006):
#   weights each position by trade value (quantity × |price_diff|).
# If False, use count-based DEI (Odean, 1998): equal weight per position.
# Both variants produce DEI ∈ [−1, 1]; switch does not affect severity thresholds.
USE_DOLLAR_WEIGHTED_DEI: bool = True

# ---------------------------------------------------------------------------
# Authentication (v6)
# ---------------------------------------------------------------------------
BCRYPT_ROUNDS: int = int(os.environ.get("CDT_BCRYPT_ROUNDS", "12"))
AUTH_RATE_LIMIT_MAX: int = 5
AUTH_RATE_LIMIT_WINDOW_SEC: int = 600  # 10 minutes
AUTH_PASSWORD_MIN_LEN: int = 8

# ---------------------------------------------------------------------------
# Researcher view — password gate via env var. None = view disabled.
# Enables the hidden ``?view=researcher`` URL for cohort-level UAT inspection.
# ---------------------------------------------------------------------------
RESEARCHER_PASSWORD = os.environ.get("CDT_RESEARCHER_PASSWORD") or None

# Usernames explicitly excluded from UAT cohort statistics even if they hold
# consent / profile / auth credentials. These are developer/test accounts that
# would otherwise distort cohort means (e.g. the long-running "test1" seed used
# during development). Override via env (comma-separated) if needed.
COHORT_EXCLUDED_USERNAMES: set[str] = {
    u.strip()
    for u in (os.environ.get("CDT_COHORT_EXCLUDED_USERNAMES") or "test1").split(",")
    if u.strip()
}

# ---------------------------------------------------------------------------
# Stock catalog
# ---------------------------------------------------------------------------
STOCK_CATALOG_FILE = DATA_DIR / "stock_catalog.json"
MARKET_SNAPSHOTS_FILE = DATA_DIR / "all_market_snapshots.csv"

# Volatility classes considered "high risk"
HIGH_VOLATILITY_CLASSES = {"high"}

# Design note: only "high" volatility stocks contribute to observed_risk
# in update_profile(). Stocks with volatility_class "medium" or below
# count as zero-risk regardless of trading frequency. This is a deliberate
# simplification: risk_preference tracks exposure to the most volatile
# instruments. Future work may extend this to a multi-tier weighting
# (e.g., medium=0.5, high=1.0) for a more granular risk-appetite signal.


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def validate_config() -> None:
    """Assert that all configuration parameters are internally consistent.

    Raises:
        ValueError: if any parameter violates its constraint.

    Call this once at application startup (e.g. in app.py) to catch
    misconfigured thresholds before they silently corrupt bias scores.
    """
    if INITIAL_CAPITAL <= 0:
        raise ValueError(f"INITIAL_CAPITAL must be > 0, got {INITIAL_CAPITAL}")
    if ROUNDS_PER_SESSION <= 0:
        raise ValueError(f"ROUNDS_PER_SESSION must be > 0, got {ROUNDS_PER_SESSION}")
    if not (0 < ALPHA < 1):
        raise ValueError(f"ALPHA must be in (0, 1), got {ALPHA}")
    if not (0 < BETA < 1):
        raise ValueError(f"BETA must be in (0, 1), got {BETA}")
    if not (0.0 < SURVEY_PRIOR_WEIGHT <= 0.5):
        raise ValueError("SURVEY_PRIOR_WEIGHT must be in (0, 0.5]")

    # Severity thresholds must be strictly ordered: mild < moderate < severe
    for label, mild, moderate, severe in [
        ("DEI", DEI_MILD, DEI_MODERATE, DEI_SEVERE),
        ("OCS", OCS_MILD, OCS_MODERATE, OCS_SEVERE),
        ("LAI", LAI_MILD, LAI_MODERATE, LAI_SEVERE),
    ]:
        if not (mild < moderate < severe):
            raise ValueError(
                f"{label} thresholds must satisfy mild < moderate < severe, "
                f"got mild={mild} moderate={moderate} severe={severe}"
            )
    if not (ALPHA < ALPHA_MAX < 1):
        raise ValueError(f"ALPHA_MAX must be in (ALPHA, 1), got ALPHA={ALPHA} ALPHA_MAX={ALPHA_MAX}")
    if LAI_EMA_CEILING <= 0:
        raise ValueError(f"LAI_EMA_CEILING must be > 0, got {LAI_EMA_CEILING}")
    if MIN_TRADES_FOR_FULL_SEVERITY < 1:
        raise ValueError(f"MIN_TRADES_FOR_FULL_SEVERITY must be >= 1, got {MIN_TRADES_FOR_FULL_SEVERITY}")
    if not isinstance(USE_DOLLAR_WEIGHTED_DEI, bool):
        raise ValueError("USE_DOLLAR_WEIGHTED_DEI must be a bool")

    # Auth parameters
    if not (4 <= BCRYPT_ROUNDS <= 16):
        raise ValueError(
            f"BCRYPT_ROUNDS must be in [4, 16], got {BCRYPT_ROUNDS}"
        )
    if AUTH_RATE_LIMIT_MAX < 1:
        raise ValueError("AUTH_RATE_LIMIT_MAX must be >= 1")
    if AUTH_RATE_LIMIT_WINDOW_SEC < 1:
        raise ValueError("AUTH_RATE_LIMIT_WINDOW_SEC must be >= 1 second")
    if AUTH_PASSWORD_MIN_LEN < 6:
        raise ValueError("AUTH_PASSWORD_MIN_LEN must be >= 6")
