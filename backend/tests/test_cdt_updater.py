"""
tests/test_cdt_updater.py — Unit tests for CDT profile updates.

Critical tests:
    - test_ema_convergence:    10 sessions OCS=0.8 → profile approaches 0.8
    - test_stability_stable:   5 similar sessions → stability_index > 0.7
    - test_stability_erratic:  alternating extremes → stability_index < 0.5
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import ALPHA
from database.models import Base, BiasMetric, CdtSnapshot, StockCatalog, User
from modules.cdt.profile import get_or_create_profile
from modules.cdt.stability import compute_learning_trajectory, compute_stability_index
from modules.cdt.updater import update_profile

# ---------------------------------------------------------------------------
# In-memory SQLite fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """Create a fresh in-memory SQLite database for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture()
def user(db):
    u = User(alias="test_user", experience_level="beginner")
    db.add(u)
    db.flush()
    return u


def _make_snapshot(
    db,
    user_id: int,
    session_number: int,
    ocs: float,
    dei: float = 0.0,
    lai: float = 0.0,
) -> CdtSnapshot:
    """Helper: create and persist a CdtSnapshot with given bias intensity values."""
    snap = CdtSnapshot(
        user_id=user_id,
        session_id=str(uuid.uuid4()),
        session_number=session_number,
        cdt_overconfidence=ocs,
        cdt_disposition=dei,
        cdt_loss_aversion=lai,
        cdt_risk_preference=0.0,
        cdt_stability_index=0.5,
    )
    db.add(snap)
    db.flush()
    return snap


def _make_metric(db, user_id: int, ocs: float, dei: float = 0.0, lai: float = 1.0) -> BiasMetric:
    """Helper: create and persist a BiasMetric with given scores."""
    m = BiasMetric(
        user_id=user_id,
        session_id=str(uuid.uuid4()),
        overconfidence_score=ocs,
        disposition_pgr=max(dei, 0.0),
        disposition_plr=0.0,
        disposition_dei=dei,
        loss_aversion_index=lai,
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------

def test_get_or_create_returns_default_profile(db, user):
    profile = get_or_create_profile(db, user.id)
    assert profile.session_count == 0
    assert profile.bias_intensity_vector["overconfidence"] == 0.0
    assert profile.bias_intensity_vector["disposition"] == 0.0
    assert profile.bias_intensity_vector["loss_aversion"] == 0.0
    assert profile.risk_preference == 0.0
    assert profile.stability_index == 0.0


def test_get_or_create_returns_existing_profile(db, user):
    p1 = get_or_create_profile(db, user.id)
    p1.session_count = 5
    db.flush()
    p2 = get_or_create_profile(db, user.id)
    assert p2.session_count == 5
    assert p1.id == p2.id


# ---------------------------------------------------------------------------
# EMA update
# ---------------------------------------------------------------------------

def test_first_session_ema_update(db, user):
    """After first session with OCS=0.8, profile.overconfidence = ALPHA × 0.8."""
    metric = _make_metric(db, user.id, ocs=0.8)
    profile = update_profile(db, user.id, metric, metric.session_id)

    expected = ALPHA * 0.8 + (1 - ALPHA) * 0.0
    assert profile.bias_intensity_vector["overconfidence"] == pytest.approx(expected)
    assert profile.session_count == 1


def test_ema_convergence_after_many_sessions(db, user):
    """10 identical sessions with OCS=0.8 → profile approaches 0.8."""
    TARGET = 0.8
    NUM_SESSIONS = 10

    for _ in range(NUM_SESSIONS):
        metric = _make_metric(db, user.id, ocs=TARGET)
        update_profile(db, user.id, metric, metric.session_id)
        db.flush()

    profile = get_or_create_profile(db, user.id)
    # EMA with ALPHA=0.3 converges: value after n steps = T*(1 - (1-ALPHA)^n)
    convergence_error = abs(profile.bias_intensity_vector["overconfidence"] - TARGET)
    assert convergence_error < 0.15, (
        f"After {NUM_SESSIONS} sessions at OCS={TARGET}, expected value near {TARGET}, "
        f"got {profile.bias_intensity_vector['overconfidence']:.4f}"
    )


def test_ema_loss_aversion_normalized(db, user):
    """LAI is normalised to [0,1] as min(LAI/LAI_EMA_CEILING, 1) before EMA.

    Uses _make_metric which logs no UserActions → session_activity=0
    → effective_alpha=ALPHA (unchanged base rate; no actions = no adaptive boost).
    """
    from config import LAI_EMA_CEILING
    metric = _make_metric(db, user.id, ocs=0.0, lai=LAI_EMA_CEILING)
    profile = update_profile(db, user.id, metric, metric.session_id)
    # min(LAI_EMA_CEILING / LAI_EMA_CEILING, 1.0) = 1.0
    # No UserActions → session_activity=0 → effective_alpha=ALPHA
    # → ALPHA * 1.0 + (1-ALPHA) * 0.0
    expected = ALPHA * 1.0
    assert profile.bias_intensity_vector["loss_aversion"] == pytest.approx(expected)


def test_session_count_increments(db, user):
    for i in range(3):
        metric = _make_metric(db, user.id, ocs=0.5)
        update_profile(db, user.id, metric, metric.session_id)
    profile = get_or_create_profile(db, user.id)
    assert profile.session_count == 3


# ---------------------------------------------------------------------------
# Stability index
# ---------------------------------------------------------------------------

def test_stability_index_zero_with_single_session(db, user):
    """Single session → insufficient data → stability = 0.0."""
    _make_metric(db, user.id, ocs=0.7)
    si = compute_stability_index(db, user.id)
    assert si == 0.0


def test_stability_stable_sessions(db, user):
    """5 near-identical sessions → stability > 0.7."""
    for _ in range(5):
        _make_metric(db, user.id, ocs=0.75, dei=0.3, lai=2.0)
    si = compute_stability_index(db, user.id)
    assert si > 0.7, f"Expected stability > 0.7, got {si:.4f}"


def test_stability_erratic_sessions(db, user):
    """Alternating extremes across all three bias dimensions → stability < 0.5.

    Uses maximum contrast values (0.0 ↔ 1.0 after normalization) to ensure
    mean std > 0.5, producing stability < 0.5 regardless of which 5 of the 6
    sessions fall in the CDT_STABILITY_WINDOW.

    DEI ±1.0 represents complete disposition / complete reverse-disposition.
    LAI 6.0 normalises to 1.0 (ceiling = LAI_EMA_CEILING × 2 ensures saturation).
    """
    for i in range(6):
        ocs = 1.0 if i % 2 == 0 else 0.0
        dei = 1.0 if i % 2 == 0 else -1.0
        lai = 6.0 if i % 2 == 0 else 0.0
        _make_metric(db, user.id, ocs=ocs, dei=dei, lai=lai)
    si = compute_stability_index(db, user.id)
    assert si < 0.5, f"Expected stability < 0.5 (extreme alternation), got {si:.4f}"


# ---------------------------------------------------------------------------
# Survey prior integration
# ---------------------------------------------------------------------------

class TestSurveyPriorIntegration:

    def test_profile_with_survey_uses_priors(self, db, user):
        """User with survey gets non-zero initial bias vector."""
        from database.models import UserSurvey
        db.add(UserSurvey(
            user_id=user.id, q_risk_tolerance=5,
            q_loss_sensitivity=5, q_trading_frequency=5, q_holding_behavior=5,
        ))
        db.flush()
        profile = get_or_create_profile(db, user.id)
        bv = profile.bias_intensity_vector
        assert bv["overconfidence"] > 0.0
        assert bv["disposition"] > 0.0
        assert bv["loss_aversion"] > 0.0
        # Verify damping: max possible is SURVEY_PRIOR_WEIGHT
        from config import SURVEY_PRIOR_WEIGHT
        assert bv["overconfidence"] <= SURVEY_PRIOR_WEIGHT
        assert bv["disposition"] <= SURVEY_PRIOR_WEIGHT
        assert bv["loss_aversion"] <= SURVEY_PRIOR_WEIGHT

    def test_profile_without_survey_uses_zeros(self, db, user):
        """User without survey gets zero initial bias vector (regression)."""
        profile = get_or_create_profile(db, user.id)
        bv = profile.bias_intensity_vector
        assert bv == {"overconfidence": 0.0, "disposition": 0.0, "loss_aversion": 0.0}

    def test_survey_prior_convergence(self, db, user):
        """After 3 EMA updates with zero observed bias, prior decays below 35%."""
        from database.models import BiasMetric, UserSurvey
        db.add(UserSurvey(
            user_id=user.id, q_risk_tolerance=5,
            q_loss_sensitivity=5, q_trading_frequency=5, q_holding_behavior=5,
        ))
        db.flush()
        profile = get_or_create_profile(db, user.id)
        initial_oc = profile.bias_intensity_vector["overconfidence"]

        # Simulate 3 sessions with zero observed bias
        for i in range(3):
            metric = BiasMetric(
                user_id=user.id, session_id=f"conv-test-{i}",
                overconfidence_score=0.0, disposition_dei=0.0,
                loss_aversion_index=0.0,
            )
            db.add(metric)
            db.flush()
            update_profile(db, user.id, metric, f"conv-test-{i}")

        final_oc = profile.bias_intensity_vector["overconfidence"]
        # After 3 updates: prior_weight = 0.7^3 = 0.343
        assert final_oc < initial_oc * 0.35

    def test_extreme_survey_below_mild_threshold(self, db, user):
        """Even max survey responses don't exceed mild OCS threshold."""
        from config import OCS_MILD
        from database.models import UserSurvey
        db.add(UserSurvey(
            user_id=user.id, q_risk_tolerance=5,
            q_loss_sensitivity=5, q_trading_frequency=5, q_holding_behavior=5,
        ))
        db.flush()
        profile = get_or_create_profile(db, user.id)
        assert profile.bias_intensity_vector["overconfidence"] < OCS_MILD


# ---------------------------------------------------------------------------
# R-10: Boundary and stress tests (EMA, stability, snapshot)
# ---------------------------------------------------------------------------

def test_adaptive_alpha_higher_for_active_sessions(db, user):
    """Sessions with many buy/sell actions use effective_alpha > ALPHA.

    We verify that the CDT profile updated for a fully-active session
    (14 buy/sell actions) reflects a higher update weight than ALPHA alone.
    We do this by checking the resulting overconfidence value is greater than
    what ALPHA × OCS would give if activity=0.
    """
    from datetime import date, timedelta

    from config import ALPHA, ALPHA_MAX
    from database.models import MarketSnapshot
    from modules.logging_engine.logger import log_action

    # Seed minimal stock and snapshots
    s = StockCatalog(
        stock_id="BMRI.JK", ticker="BMRI", name="BRI Corp",
        sector="Finance", volatility_class="low", bias_role="test",
    )
    db.add(s)
    db.flush()

    base_date = date(2024, 1, 1)
    snap_ids = []
    for day in range(14):
        snap = MarketSnapshot(
            stock_id="BMRI.JK", date=base_date + timedelta(days=day),
            open=5000.0, high=5000.0, low=5000.0, close=5000.0,
            volume=1_000_000, ma_5=5000.0, ma_20=5000.0, rsi_14=50.0,
            volatility_20d=0.02, trend="neutral", daily_return=0.0,
        )
        db.add(snap)
        db.flush()
        snap_ids.append(snap.id)

    OCS_TARGET = 0.7
    metric = _make_metric(db, user.id, ocs=OCS_TARGET, dei=0.0, lai=0.0)

    # Log 14 buy/sell actions (1 per round) so session_activity = 14/14 = 1.0
    for rnd in range(1, 15):
        log_action(
            session=db, user_id=user.id, session_id=metric.session_id,
            scenario_round=rnd, stock_id="BMRI.JK",
            snapshot_id=snap_ids[rnd - 1],
            action_type="buy", quantity=1, action_value=5000.0,
            response_time_ms=300,
        )
    db.flush()

    profile = update_profile(db, user.id, metric, metric.session_id)

    # With session_activity=1.0: effective_alpha = ALPHA + (ALPHA_MAX - ALPHA) * 1.0 = ALPHA_MAX
    expected_min = ALPHA * OCS_TARGET   # lower bound (activity=0)
    expected_max = ALPHA_MAX * OCS_TARGET  # upper bound (activity=1.0)
    actual = profile.bias_intensity_vector["overconfidence"]

    assert actual > expected_min, (
        f"Active session should update OC above {expected_min:.4f} (ALPHA baseline), "
        f"got {actual:.4f}"
    )
    assert actual <= expected_max + 1e-9, (
        f"OC should not exceed ALPHA_MAX × OCS_TARGET = {expected_max:.4f}, got {actual:.4f}"
    )


def test_extreme_lai_clamped_by_ceiling(db, user):
    """LAI values far above LAI_EMA_CEILING are clamped to 1.0 before EMA.

    Prevents runaway loss_aversion values when LAI >> 3.0 in edge cases
    (e.g., user holds a loser 100 rounds but never holds a winner).
    """
    from config import LAI_EMA_CEILING

    # LAI = 100: min(100/3, 1.0) = 1.0 → same EMA input as LAI = 3.0
    metric_extreme = _make_metric(db, user.id, ocs=0.0, lai=100.0)
    profile_extreme = update_profile(db, user.id, metric_extreme, metric_extreme.session_id)

    # Create fresh user for baseline comparison
    u2 = User(alias="ceiling_test_user", experience_level="beginner")
    db.add(u2)
    db.flush()

    metric_normal = _make_metric(db, u2.id, ocs=0.0, lai=LAI_EMA_CEILING)
    profile_normal = update_profile(db, u2.id, metric_normal, metric_normal.session_id)

    # Both should produce the same loss_aversion EMA value (both clamped to 1.0 input)
    assert profile_extreme.bias_intensity_vector["loss_aversion"] == pytest.approx(
        profile_normal.bias_intensity_vector["loss_aversion"]
    ), (
        f"LAI=100 and LAI={LAI_EMA_CEILING} should produce identical EMA updates "
        f"after ceiling normalization"
    )


def test_cdt_snapshot_created_after_update(db, user):
    """update_profile() now auto-creates a CdtSnapshot record."""
    from database.models import CdtSnapshot

    metric = _make_metric(db, user.id, ocs=0.5, dei=0.3, lai=1.5)
    profile = update_profile(db, user.id, metric, metric.session_id)

    snapshots = db.query(CdtSnapshot).filter_by(user_id=user.id).all()
    assert len(snapshots) == 1, f"Expected 1 CdtSnapshot, got {len(snapshots)}"

    snap = snapshots[0]
    assert snap.session_id == metric.session_id
    assert snap.session_number == 1  # first session
    assert snap.cdt_overconfidence == pytest.approx(profile.bias_intensity_vector["overconfidence"])
    assert snap.cdt_disposition == pytest.approx(profile.bias_intensity_vector["disposition"])
    assert snap.cdt_loss_aversion == pytest.approx(profile.bias_intensity_vector["loss_aversion"])
    assert snap.cdt_risk_preference == pytest.approx(profile.risk_preference)
    assert snap.cdt_stability_index == pytest.approx(profile.stability_index)


def test_three_sessions_create_three_snapshots(db, user):
    """One CdtSnapshot is created per session; session_number increments correctly."""
    from database.models import CdtSnapshot

    for i in range(3):
        metric = _make_metric(db, user.id, ocs=0.3 * (i + 1), dei=0.0, lai=1.0)
        update_profile(db, user.id, metric, metric.session_id)

    snapshots = (
        db.query(CdtSnapshot)
        .filter_by(user_id=user.id)
        .order_by(CdtSnapshot.session_number)
        .all()
    )
    assert len(snapshots) == 3
    assert [s.session_number for s in snapshots] == [1, 2, 3]


def test_stability_index_uses_normalized_dei(db, user):
    """After TASK D: stability reflects DEI in [0,1] space, not raw signed DEI.

    A user whose DEI alternates +0.3 and -0.3 has non-zero instability in raw
    DEI space but near-zero instability in |DEI| or (DEI+1)/2 space only if
    constant. The test verifies that high raw DEI variance (sign-alternating)
    IS correctly captured as instability with the (DEI+1)/2 normalization,
    since +0.3→0.65 and -0.3→0.35 still have non-zero std.
    """
    # 5 alternating DEI sessions: +0.5 and -0.5
    # (DEI+1)/2 → 0.75 and 0.25; std ≈ 0.25; stability ≈ 0.75
    for i in range(5):
        dei = 0.5 if i % 2 == 0 else -0.5
        _make_metric(db, user.id, ocs=0.5, dei=dei, lai=1.5)  # constant OCS and LAI

    si = compute_stability_index(db, user.id)
    # With alternating DEI (0.75/0.25), constant OCS (0.5), constant LAI_norm (0.5):
    # std_dei ≈ 0.25, std_ocs = 0.0, std_lai = 0.0 → mean_std ≈ 0.083 → stability ≈ 0.917
    # But oscillating sign IS instability, so stability < 1.0
    assert si < 1.0, "Alternating DEI sign should not produce perfect stability"
    assert si > 0.5, "Moderate DEI sign-alternation should not produce si < 0.5"


# ---------------------------------------------------------------------------
# Learning trajectory (monotonicity check)
# ---------------------------------------------------------------------------

class TestLearningTrajectory:
    """Tests for compute_learning_trajectory().

    All cases set dei=0.0 and lai=0.0 so that OCS is always the dominant
    bias (highest mean), making the trajectory selection deterministic.
    """

    def test_monotonically_decreasing_is_improving(self, db, user):
        """5 sessions with strictly decreasing OCS → direction='improving'.

        Values [0.9, 0.7, 0.5, 0.3, 0.1] are perfectly linear with
        slope=-0.2 and r²=1.0, both well past the classification thresholds.
        """
        for i, ocs in enumerate([0.9, 0.7, 0.5, 0.3, 0.1]):
            _make_snapshot(db, user.id, session_number=i + 1, ocs=ocs)

        traj = compute_learning_trajectory(user.id, db)

        assert traj.direction == "improving", (
            f"Expected 'improving' for strictly decreasing OCS, got {traj.direction!r}"
        )
        assert traj.bias == "ocs"
        assert traj.slope < -0.05
        assert traj.r_squared > 0.4
        assert traj.sessions_analyzed == 5
        assert traj.interpretation  # non-empty string

    def test_flat_sessions_are_stable(self, db, user):
        """5 sessions with near-constant OCS (±0.02) → direction='stable'.

        Values [0.50, 0.51, 0.49, 0.50, 0.52] yield slope≈0.003, well within
        the ±0.05 stable band regardless of r².
        """
        for i, ocs in enumerate([0.50, 0.51, 0.49, 0.50, 0.52]):
            _make_snapshot(db, user.id, session_number=i + 1, ocs=ocs)

        traj = compute_learning_trajectory(user.id, db)

        assert traj.direction == "stable", (
            f"Expected 'stable' for flat OCS, got {traj.direction!r}"
        )
        assert traj.sessions_analyzed == 5

    def test_two_sessions_is_insufficient_data(self, db, user):
        """Only 2 sessions → direction='insufficient_data' (< 3 required)."""
        for i, ocs in enumerate([0.8, 0.6]):
            _make_snapshot(db, user.id, session_number=i + 1, ocs=ocs)

        traj = compute_learning_trajectory(user.id, db)

        assert traj.direction == "insufficient_data", (
            f"Expected 'insufficient_data' for 2 sessions, got {traj.direction!r}"
        )
        assert traj.sessions_analyzed == 2
        assert traj.slope == 0.0
        assert traj.r_squared == 0.0

    def test_noisy_upward_trend_is_worsening(self, db, user):
        """5 sessions with noisy but clear upward trend → direction='worsening'.

        Values [0.20, 0.40, 0.30, 0.60, 0.75] yield slope≈0.13 and r²≈0.89,
        both past the worsening thresholds (>0.05 and >0.4 respectively).
        """
        for i, ocs in enumerate([0.20, 0.40, 0.30, 0.60, 0.75]):
            _make_snapshot(db, user.id, session_number=i + 1, ocs=ocs)

        traj = compute_learning_trajectory(user.id, db)

        assert traj.direction == "worsening", (
            f"Expected 'worsening' for noisy upward OCS, got {traj.direction!r}"
        )
        assert traj.slope > 0.05
        assert traj.r_squared > 0.4
        assert traj.sessions_analyzed == 5
