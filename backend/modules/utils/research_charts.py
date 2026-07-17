"""
modules/utils/research_charts.py — Statistical chart computation helpers.

Pure Python/NumPy functions (no scipy, no Streamlit). Provides reusable
statistical overlays for the researcher dashboard:
  - Triangular kernel KDE
  - OLS regression with 95 % confidence band
  - Pearson r with approximate p-value (math.erf, no scipy)
  - Bootstrap CI for per-group means (NumPy only)
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# KDE — triangular kernel
# ---------------------------------------------------------------------------
def kde_values(
    values: Sequence[float],
    x_grid: np.ndarray,
    bandwidth: float | None = None,
) -> np.ndarray:
    """Triangular kernel density estimate evaluated on x_grid (no scipy).

    Args:
        values: Observed data points.
        x_grid: Grid of evaluation points.
        bandwidth: Kernel half-width.  Uses Silverman's rule when None.

    Returns:
        Density array of the same length as x_grid.  Integrates ≈ 1.
    """
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n == 0:
        return np.zeros(len(x_grid), dtype=float)

    if bandwidth is None:
        std = float(np.std(arr, ddof=1)) if n >= 2 else 1.0
        bandwidth = 1.06 * std * n ** (-0.2) if std > 0 else 1.0

    h = float(bandwidth)
    grid = np.asarray(x_grid, dtype=float)
    density = np.zeros(len(grid), dtype=float)
    for xi in arr:
        u = np.abs(grid - xi) / h
        density += np.where(u <= 1.0, (1.0 - u) / h, 0.0)
    return density / n


# ---------------------------------------------------------------------------
# OLS + confidence band
# ---------------------------------------------------------------------------
def ols_fit(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    """Ordinary least-squares slope and intercept.

    Returns (slope, intercept).  Returns (0.0, mean(ys)) on zero x-variance.
    """
    n = len(xs)
    if n < 2:
        return 0.0, (sum(ys) / n if n else 0.0)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    if sxx == 0:
        return 0.0, my
    slope = sxy / sxx
    return slope, my - slope * mx


def _normal_cdf(z: float) -> float:
    """Standard normal CDF via math.erf."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _normal_quantile(p: float) -> float:
    """Inverse standard normal CDF via binary search on math.erf.

    Accurate to ~5 significant figures; uses no external dependencies.
    """
    if p >= 1.0:
        return 8.0
    if p <= 0.0:
        return -8.0
    if p < 0.5:
        return -_normal_quantile(1.0 - p)
    lo, hi = 0.0, 8.0
    for _ in range(64):
        mid = (lo + hi) / 2.0
        if _normal_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def ols_confidence_band(
    xs: Sequence[float],
    ys: Sequence[float],
    x_grid: np.ndarray,
    alpha: float = 0.05,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """OLS predicted values and (1-alpha) confidence band on x_grid.

    Uses the normal approximation for the t-quantile (conservative for n < 30).

    Returns:
        (y_fit, lower, upper) arrays of the same length as x_grid.
    """
    n = len(xs)
    xs_arr = np.asarray(xs, dtype=float)
    ys_arr = np.asarray(ys, dtype=float)
    slope, intercept = ols_fit(xs, ys)
    y_fit = slope * x_grid + intercept

    if n < 3:
        return y_fit, y_fit.copy(), y_fit.copy()

    y_hat = slope * xs_arr + intercept
    mse = float(np.sum((ys_arr - y_hat) ** 2) / (n - 2))
    mx = float(np.mean(xs_arr))
    sxx = float(np.sum((xs_arr - mx) ** 2))

    se = np.sqrt(mse * (1.0 / n + (x_grid - mx) ** 2 / max(sxx, 1e-12)))
    z = _normal_quantile(1.0 - alpha / 2.0)
    return y_fit, y_fit - z * se, y_fit + z * se


# ---------------------------------------------------------------------------
# Pearson r with p-value
# ---------------------------------------------------------------------------
def pearson_with_p(
    xs: Sequence[float],
    ys: Sequence[float],
) -> tuple[float | None, float | None]:
    """Pearson r and approximate two-tailed p-value (no scipy).

    p-value uses the normal approximation on the t-statistic (t = r√(n-2) /
    √(1-r²)).  Reasonable for n ≥ 10; conservative for smaller samples.

    Returns:
        (r, p_value).  Both None when n < 2 or either series has zero variance.
    """
    n = len(xs)
    if n < 2 or len(xs) != len(ys):
        return None, None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None, None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    r = max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))

    if n <= 2:
        return r, 1.0

    denom = math.sqrt(max(1.0 - r ** 2, 1e-12))
    t_stat = r * math.sqrt(n - 2) / denom
    p_val = max(0.0, min(1.0, 2.0 * (1.0 - _normal_cdf(abs(t_stat)))))
    return r, p_val


def significance_stars(p_val: float | None) -> str:
    """Return APA-style significance asterisks for a p-value."""
    if p_val is None:
        return ""
    if p_val < 0.001:
        return "***"
    if p_val < 0.01:
        return "**"
    if p_val < 0.05:
        return "*"
    return ""


# ---------------------------------------------------------------------------
# Bootstrap CI
# ---------------------------------------------------------------------------
def bootstrap_ci(
    groups: dict[int, list[float]],
    n_resamples: int = 1000,
    ci: float = 0.95,
    rng_seed: int = 42,
) -> dict[int, tuple[float, float, float]]:
    """Bootstrap confidence intervals for per-group means (NumPy only).

    Args:
        groups: Dict mapping group key (e.g. session number) → list of values.
        n_resamples: Number of bootstrap resamples.
        ci: Confidence level (default 0.95 → 95 % CI).
        rng_seed: Seed for reproducibility.

    Returns:
        Dict mapping each key → (mean, lower_ci, upper_ci).
    """
    rng = np.random.default_rng(rng_seed)
    alpha = 1.0 - ci
    result: dict[int, tuple[float, float, float]] = {}
    for key, vals in groups.items():
        arr = np.asarray(vals, dtype=float)
        n = len(arr)
        if n == 0:
            result[key] = (0.0, 0.0, 0.0)
            continue
        mean = float(np.mean(arr))
        if n == 1:
            result[key] = (mean, mean, mean)
            continue
        boot_means = np.array([
            float(np.mean(rng.choice(arr, size=n, replace=True)))
            for _ in range(n_resamples)
        ])
        lo = float(np.percentile(boot_means, 100.0 * alpha / 2))
        hi = float(np.percentile(boot_means, 100.0 * (1 - alpha / 2)))
        result[key] = (mean, lo, hi)
    return result
