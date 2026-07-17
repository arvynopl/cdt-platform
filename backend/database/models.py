"""
database/models.py — SQLAlchemy ORM entity definitions.

SQLAlchemy ORM entities + indexes:
    User, StockCatalog, MarketSnapshot, UserAction,
    BiasMetric, CognitiveProfile, FeedbackHistory,
    ConsentLog, UserSurvey, SessionSummary, CdtSnapshot, PostSessionSurvey,
    UATFeedback, SessionError
"""

from datetime import UTC, datetime
from datetime import date as date_type

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


class User(Base):
    """Retail investor user. In v6 the canonical identity is ``username`` with a
    bcrypt ``password_hash``; ``alias`` is retained as a nullable display field
    and for backward compatibility with pre-v6 records (legacy tests seed Users
    without auth credentials).
    """

    __tablename__ = "users"

    id: int = Column(Integer, primary_key=True, autoincrement=True)

    # v6 auth fields — nullable in schema to preserve legacy fixtures, but
    # the auth service treats them as required when registering.
    username: str | None = Column(String(64), unique=True, nullable=True, index=True)
    password_hash: str | None = Column(String(128), nullable=True)
    last_login_at: datetime | None = Column(DateTime(timezone=True), nullable=True)

    # Legacy fields — retained for backward compatibility.
    alias: str | None = Column(String(64), unique=True, nullable=True)
    experience_level: str = Column(
        String(20), nullable=False, default="beginner"
    )  # beginner | intermediate | advanced
    created_at: datetime = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    # Relationships — cascade delete ensures child rows are removed with the user
    actions = relationship("UserAction", back_populates="user", lazy="dynamic", cascade="all, delete-orphan")
    bias_metrics = relationship("BiasMetric", back_populates="user", lazy="dynamic", cascade="all, delete-orphan")
    cognitive_profile = relationship(
        "CognitiveProfile", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    feedback_history = relationship(
        "FeedbackHistory", back_populates="user", lazy="dynamic", cascade="all, delete-orphan"
    )
    survey = relationship(
        "UserSurvey", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    post_session_surveys = relationship(
        "PostSessionSurvey",
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    profile = relationship(
        "UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    onboarding_surveys = relationship(
        "OnboardingSurvey",
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        ident = self.username or self.alias or f"id={self.id}"
        return f"<User id={self.id} {ident!r}>"


class UserProfile(Base):
    """One-time demographic & trait profile collected at v6 registration."""

    __tablename__ = "user_profiles"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False
    )
    full_name: str = Column(String(128), nullable=False)
    age: int = Column(Integer, nullable=False)
    # "laki-laki" | "perempuan" | "lainnya"
    gender: str = Column(String(16), nullable=False)
    # "konservatif" | "moderat" | "agresif"
    risk_profile: str = Column(String(32), nullable=False)
    # "pemula" | "menengah" | "berpengalaman"
    investing_capability: str = Column(String(32), nullable=False)
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    user = relationship("User", back_populates="profile")

    def __repr__(self) -> str:
        return (
            f"<UserProfile user={self.user_id} full_name={self.full_name!r} "
            f"risk={self.risk_profile}>"
        )


class OnboardingSurvey(Base):
    """Initial bias-tendency survey (9 Likert items) collected at registration.

    Kept separate from ``UserSurvey`` so the legacy 4-item structure continues
    to satisfy existing fixtures unchanged. The 9 items cover 3 biases × 3 items
    each (DEI, OCS, LAI) aligned with Odean 1998, Barber & Odean 2000,
    Kahneman & Tversky 1979.
    """

    __tablename__ = "onboarding_surveys"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False
    )

    # DEI items (1–5 Likert)
    dei_q1: int = Column(Integer, nullable=False)
    dei_q2: int = Column(Integer, nullable=False)
    dei_q3: int = Column(Integer, nullable=False)
    # OCS items (1–5 Likert)
    ocs_q1: int = Column(Integer, nullable=False)
    ocs_q2: int = Column(Integer, nullable=False)
    ocs_q3: int = Column(Integer, nullable=False)
    # LAI items (1–5 Likert)
    lai_q1: int = Column(Integer, nullable=False)
    lai_q2: int = Column(Integer, nullable=False)
    lai_q3: int = Column(Integer, nullable=False)

    submitted_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    user = relationship("User", back_populates="onboarding_surveys")

    @property
    def dei_mean(self) -> float:
        return (self.dei_q1 + self.dei_q2 + self.dei_q3) / 3.0

    @property
    def ocs_mean(self) -> float:
        return (self.ocs_q1 + self.ocs_q2 + self.ocs_q3) / 3.0

    @property
    def lai_mean(self) -> float:
        return (self.lai_q1 + self.lai_q2 + self.lai_q3) / 3.0

    def __repr__(self) -> str:
        return (
            f"<OnboardingSurvey user={self.user_id} "
            f"dei={self.dei_mean:.1f} ocs={self.ocs_mean:.1f} lai={self.lai_mean:.1f}>"
        )


class StockCatalog(Base):
    """Metadata for the 6 IDX stocks used in the simulation."""

    __tablename__ = "stock_catalog"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    stock_id: str = Column(String(20), unique=True, nullable=False)  # e.g. "BBCA.JK"
    ticker: str = Column(String(10), nullable=False)                  # e.g. "BBCA"
    name: str = Column(String(128), nullable=False)
    sector: str = Column(String(64), nullable=False)
    volatility_class: str = Column(String(20), nullable=False)  # low|low_medium|medium|high
    bias_role: str = Column(Text, nullable=True)

    # Relationships
    snapshots = relationship("MarketSnapshot", back_populates="stock", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<StockCatalog {self.ticker} ({self.volatility_class})>"


class MarketSnapshot(Base):
    """One trading day of OHLCV + technical indicators for a stock."""

    __tablename__ = "market_snapshots"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    stock_id: str = Column(
        String(20), ForeignKey("stock_catalog.stock_id"), nullable=False
    )
    date: date_type = Column(Date, nullable=False)

    # OHLCV
    open: float = Column(Float, nullable=False)
    high: float = Column(Float, nullable=False)
    low: float = Column(Float, nullable=False)
    close: float = Column(Float, nullable=False)
    volume: int = Column(BigInteger, nullable=False)

    # Technical indicators (may be None for early rows)
    ma_5: float | None = Column(Float, nullable=True)
    ma_20: float | None = Column(Float, nullable=True)
    rsi_14: float | None = Column(Float, nullable=True)
    volatility_20d: float | None = Column(Float, nullable=True)
    trend: str | None = Column(String(20), nullable=True)    # bullish|bearish|neutral
    daily_return: float | None = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("stock_id", "date", name="uq_snapshot_stock_date"),
    )

    # Relationships
    stock = relationship("StockCatalog", back_populates="snapshots")

    def __repr__(self) -> str:
        return f"<MarketSnapshot {self.stock_id} {self.date} close={self.close}>"


class UserAction(Base):
    """One decision (buy/sell/hold) made by a user during a simulation round."""

    __tablename__ = "user_actions"
    __table_args__ = (
        Index("ix_useraction_user_session", "user_id", "session_id"),
    )

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id: str = Column(String(36), nullable=False)    # UUID string
    scenario_round: int = Column(Integer, nullable=False)   # 1–14
    stock_id: str = Column(
        String(20), ForeignKey("stock_catalog.stock_id"), nullable=False
    )
    snapshot_id: int = Column(
        Integer, ForeignKey("market_snapshots.id"), nullable=False
    )
    action_type: str = Column(String(10), nullable=False)   # buy|sell|hold
    quantity: int = Column(Integer, nullable=False, default=0)
    action_value: float = Column(Float, nullable=False, default=0.0)
    response_time_ms: int = Column(Integer, nullable=False, default=0)
    timestamp: datetime = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    # Relationships
    user = relationship("User", back_populates="actions")
    snapshot = relationship("MarketSnapshot")
    stock = relationship("StockCatalog")

    def __repr__(self) -> str:
        return (
            f"<UserAction {self.action_type} {self.stock_id} "
            f"qty={self.quantity} round={self.scenario_round}>"
        )


class BiasMetric(Base):
    """Computed bias scores for a completed simulation session."""

    __tablename__ = "bias_metrics"
    __table_args__ = (
        Index("ix_biasmetric_user_session", "user_id", "session_id"),
    )

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id: str = Column(String(36), nullable=False)

    # Overconfidence
    overconfidence_score: float | None = Column(Float, nullable=True)

    # Disposition Effect
    disposition_pgr: float | None = Column(Float, nullable=True)
    disposition_plr: float | None = Column(Float, nullable=True)
    disposition_dei: float | None = Column(Float, nullable=True)

    # Loss Aversion
    loss_aversion_index: float | None = Column(Float, nullable=True)

    # 95% bootstrap confidence interval bounds
    dei_ci_lower: float | None = Column(Float, nullable=True)
    dei_ci_upper: float | None = Column(Float, nullable=True)
    ocs_ci_lower: float | None = Column(Float, nullable=True)
    ocs_ci_upper: float | None = Column(Float, nullable=True)
    lai_ci_lower: float | None = Column(Float, nullable=True)
    lai_ci_upper: float | None = Column(Float, nullable=True)
    ci_low_confidence: bool | None = Column(Boolean, nullable=True)

    computed_at: datetime = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    # Relationships
    user = relationship("User", back_populates="bias_metrics")

    def __repr__(self) -> str:
        ocs = f"{self.overconfidence_score:.3f}" if self.overconfidence_score is not None else "None"
        dei = f"{self.disposition_dei:.3f}" if self.disposition_dei is not None else "None"
        return f"<BiasMetric session={self.session_id[:8]} OCS={ocs} DEI={dei}>"


class CognitiveProfile(Base):
    """Longitudinal CDT profile updated via EMA after each session."""

    __tablename__ = "cognitive_profiles"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False
    )

    # JSON: {"overconfidence": float, "disposition": float, "loss_aversion": float}
    bias_intensity_vector: dict = Column(JSON, nullable=False, default=lambda: {
        "overconfidence": 0.0,
        "disposition": 0.0,
        "loss_aversion": 0.0,
    })

    risk_preference: float = Column(Float, nullable=False, default=0.0)
    stability_index: float = Column(Float, nullable=False, default=0.0)
    # JSON: {"ocs_dei": float|null, "ocs_lai": float|null, "dei_lai": float|null}
    # Null values indicate insufficient data or zero-variance series.
    interaction_scores: dict | None = Column(JSON, nullable=True, default=None)
    session_count: int = Column(Integer, nullable=False, default=0)
    last_updated_at: datetime = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="cognitive_profile")

    def __repr__(self) -> str:
        return (
            f"<CognitiveProfile user={self.user_id} "
            f"sessions={self.session_count} stability={self.stability_index:.2f}>"
        )


class FeedbackHistory(Base):
    """Delivered feedback record for a specific bias in a session."""

    __tablename__ = "feedback_history"
    __table_args__ = (
        Index("ix_feedbackhistory_user_session", "user_id", "session_id"),
    )

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id: str = Column(String(36), nullable=False)
    bias_type: str = Column(String(30), nullable=False)    # overconfidence|disposition_effect|loss_aversion
    severity: str = Column(String(10), nullable=False)     # none|mild|moderate|severe
    explanation_text: str = Column(Text, nullable=True)
    recommendation_text: str = Column(Text, nullable=True)
    delivered_at: datetime = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    # Relationships
    user = relationship("User", back_populates="feedback_history")

    def __repr__(self) -> str:
        return (
            f"<FeedbackHistory {self.bias_type} severity={self.severity} "
            f"session={self.session_id[:8]}>"
        )


class ConsentLog(Base):
    """Records user consent for research participation (UAT audit trail)."""

    __tablename__ = "consent_logs"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, ForeignKey("users.id"), nullable=False)
    consent_given: bool = Column(Boolean, nullable=False, default=False)
    # Optional verbatim consent text snapshot for audit
    consent_text: str | None = Column(Text, nullable=True)
    # SHA-256 of remote IP for audit purposes (not PII linkable without original IP)
    ip_hash: str | None = Column(String(64), nullable=True)
    created_at: datetime = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    def __repr__(self) -> str:
        return f"<ConsentLog user={self.user_id} given={self.consent_given}>"


class UserSurvey(Base):
    """Self-reported risk-preference survey.

    ``survey_type`` discriminates between:
        - "onboarding":  captured once at registration (pre-simulation).
        - "session_level": captured at the end of each simulation session.
    Legacy records default to "session_level".
    """

    __tablename__ = "user_surveys"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )

    # Likert scale 1-5 for each question
    q_risk_tolerance: int = Column(Integer, nullable=False)      # 1=sangat menghindari risiko, 5=sangat menyukai risiko
    q_loss_sensitivity: int = Column(Integer, nullable=False)     # 1=tidak terganggu, 5=sangat terganggu
    q_trading_frequency: int = Column(Integer, nullable=False)    # 1=sangat jarang, 5=sangat sering
    q_holding_behavior: int = Column(Integer, nullable=False)     # 1=langsung jual, 5=selalu menahan

    survey_type: str = Column(
        String(24), nullable=False, default="session_level"
    )  # "onboarding" | "session_level"

    submitted_at: datetime = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    # Relationships
    user = relationship("User", back_populates="survey")

    def __repr__(self) -> str:
        return (
            f"<UserSurvey user={self.user_id} "
            f"risk={self.q_risk_tolerance} loss={self.q_loss_sensitivity}>"
        )


class SessionSummary(Base):
    """Summary record for each simulation session (tracks lifecycle)."""

    __tablename__ = "session_summaries"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id: str = Column(String(36), unique=True, nullable=False)
    started_at: datetime = Column(DateTime(timezone=True), nullable=False)
    completed_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
    rounds_completed: int = Column(Integer, nullable=False, default=0)
    final_portfolio_value: float | None = Column(Float, nullable=True)
    window_start_date: date_type | None = Column(Date, nullable=True)
    window_end_date: date_type | None = Column(Date, nullable=True)
    # in_progress | completed | abandoned
    status: str = Column(String(20), nullable=False, default="in_progress")

    def __repr__(self) -> str:
        return (
            f"<SessionSummary user={self.user_id} session={self.session_id[:8]}"
            f" status={self.status}>"
        )


class CdtSnapshot(Base):
    """Point-in-time snapshot of the CognitiveProfile after each completed session.

    Unlike CognitiveProfile (which holds only the *current* state), CdtSnapshot
    preserves the full CDT state vector at the end of each session. This enables:
      - Longitudinal CDT evolution charts in the thesis report (Bab VI)
      - Reconstruction of past CDT states without replaying EMA history
      - Validation that the CDT adapts meaningfully across sessions
    """

    __tablename__ = "cdt_snapshots"
    __table_args__ = (
        Index("ix_cdtsnapshot_user_session", "user_id", "session_id"),
    )

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id: str = Column(String(36), nullable=False)   # UUID of the session that produced this snapshot
    session_number: int = Column(Integer, nullable=False)  # CognitiveProfile.session_count at snapshot time

    # Bias intensity vector components
    cdt_overconfidence: float = Column(Float, nullable=False, default=0.0)
    cdt_disposition: float = Column(Float, nullable=False, default=0.0)
    cdt_loss_aversion: float = Column(Float, nullable=False, default=0.0)

    # Other CDT state
    cdt_risk_preference: float = Column(Float, nullable=False, default=0.0)
    cdt_stability_index: float = Column(Float, nullable=False, default=0.0)

    snapshotted_at: datetime = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    def __repr__(self) -> str:
        return (
            f"<CdtSnapshot user={self.user_id} session={self.session_id[:8]} "
            f"#={self.session_number} OC={self.cdt_overconfidence:.3f}>"
        )


class PostSessionSurvey(Base):
    """Post-session self-assessment survey: user's self-rated bias awareness.

    Captured after the feedback page is viewed so responses reflect post-feedback
    metacognition. Compared against system-detected severity for thesis analysis.
    """

    __tablename__ = "post_session_surveys"
    __table_args__ = (
        UniqueConstraint("user_id", "session_id", name="uq_post_survey_user_session"),
    )

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id: str = Column(String(36), nullable=False)

    # Self-assessed bias awareness: 1 = tidak menyadari sama sekali, 5 = sangat menyadari
    self_overconfidence: int = Column(Integer, nullable=False)
    self_disposition: int = Column(Integer, nullable=False)
    self_loss_aversion: int = Column(Integer, nullable=False)

    # Overall feedback usefulness: 1 = tidak berguna, 5 = sangat berguna
    feedback_usefulness: int = Column(Integer, nullable=False)

    submitted_at: datetime = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    user = relationship("User", back_populates="post_session_surveys")

    def __repr__(self) -> str:
        return (
            f"<PostSessionSurvey user={self.user_id} session={self.session_id[:8]} "
            f"OC={self.self_overconfidence} DEI={self.self_disposition} LA={self.self_loss_aversion}>"
        )


class UATFeedback(Base):
    """SUS (System Usability Scale) responses + open-ended feedback from UAT testers.

    Captures the 10 standard SUS items (1–5 Likert) plus two free-text fields
    (apa yang membingungkan, apa yang berguna). The SUS score is computable on
    read via :meth:`sus_score` (0–100, higher = better usability).
    """

    __tablename__ = "uat_feedback"
    __table_args__ = (
        Index("ix_uatfeedback_user", "user_id"),
    )

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id: str | None = Column(String(36), nullable=True)

    sus_q1: int = Column(Integer, nullable=False)
    sus_q2: int = Column(Integer, nullable=False)
    sus_q3: int = Column(Integer, nullable=False)
    sus_q4: int = Column(Integer, nullable=False)
    sus_q5: int = Column(Integer, nullable=False)
    sus_q6: int = Column(Integer, nullable=False)
    sus_q7: int = Column(Integer, nullable=False)
    sus_q8: int = Column(Integer, nullable=False)
    sus_q9: int = Column(Integer, nullable=False)
    sus_q10: int = Column(Integer, nullable=False)

    open_confusing: str | None = Column(Text, nullable=True)
    open_useful: str | None = Column(Text, nullable=True)

    submitted_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    @property
    def sus_score(self) -> float:
        """Standard SUS score: ((odd-1) + (5-even)) * 2.5, range 0–100."""
        odd = (
            (self.sus_q1 - 1)
            + (self.sus_q3 - 1)
            + (self.sus_q5 - 1)
            + (self.sus_q7 - 1)
            + (self.sus_q9 - 1)
        )
        even = (
            (5 - self.sus_q2)
            + (5 - self.sus_q4)
            + (5 - self.sus_q6)
            + (5 - self.sus_q8)
            + (5 - self.sus_q10)
        )
        return (odd + even) * 2.5

    def __repr__(self) -> str:
        return f"<UATFeedback user={self.user_id} sus={self.sus_score:.1f}>"


class SessionError(Base):
    """Lightweight DB-backed error counter (no third-party APM).

    One row per error event, queryable for /admin error-rate dashboard.
    """

    __tablename__ = "session_errors"
    __table_args__ = (
        Index("ix_sessionerror_session", "session_id"),
    )

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int | None = Column(Integer, ForeignKey("users.id"), nullable=True)
    session_id: str | None = Column(String(36), nullable=True)
    error_type: str = Column(String(64), nullable=False)
    message: str | None = Column(Text, nullable=True)
    occurred_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        sid = (self.session_id or "")[:8]
        return f"<SessionError session={sid} type={self.error_type}>"
