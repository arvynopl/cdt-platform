"""app/schemas.py — Pydantic request/response models for the public API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class UsernameCheckIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)


class UsernameCheckOut(BaseModel):
    exists: bool


class OnboardingSurveyIn(BaseModel):
    """9 Likert items (1–5), three per bias — same instrument as the thesis."""

    dei_q1: int = Field(ge=1, le=5)
    dei_q2: int = Field(ge=1, le=5)
    dei_q3: int = Field(ge=1, le=5)
    ocs_q1: int = Field(ge=1, le=5)
    ocs_q2: int = Field(ge=1, le=5)
    ocs_q3: int = Field(ge=1, le=5)
    lai_q1: int = Field(ge=1, le=5)
    lai_q2: int = Field(ge=1, le=5)
    lai_q3: int = Field(ge=1, le=5)


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=128)
    age: int = Field(ge=17, le=100)
    gender: Literal["laki-laki", "perempuan", "lainnya"]
    risk_profile: Literal["konservatif", "moderat", "agresif"]
    investing_capability: Literal["pemula", "menengah", "berpengalaman"]
    onboarding_survey: OnboardingSurveyIn
    consent: bool

    @field_validator("consent")
    @classmethod
    def _must_consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Persetujuan partisipasi wajib dicentang.")
        return v


class LoginIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class MeOut(BaseModel):
    user_id: int
    username: str
    experience_level: str


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


class OrderIn(BaseModel):
    stock_id: str = Field(max_length=20)
    action: Literal["buy", "sell"]
    quantity: int = Field(ge=1)


class RoundSubmitIn(BaseModel):
    orders: list[OrderIn] = Field(default_factory=list, max_length=20)
    response_time_ms: int = Field(ge=0, le=3_600_000)


# ---------------------------------------------------------------------------
# Surveys
# ---------------------------------------------------------------------------


class PostSessionSurveyIn(BaseModel):
    self_overconfidence: int = Field(ge=1, le=5)
    self_disposition: int = Field(ge=1, le=5)
    self_loss_aversion: int = Field(ge=1, le=5)
    feedback_usefulness: int = Field(ge=1, le=5)


class UATFeedbackIn(BaseModel):
    sus_q1: int = Field(ge=1, le=5)
    sus_q2: int = Field(ge=1, le=5)
    sus_q3: int = Field(ge=1, le=5)
    sus_q4: int = Field(ge=1, le=5)
    sus_q5: int = Field(ge=1, le=5)
    sus_q6: int = Field(ge=1, le=5)
    sus_q7: int = Field(ge=1, le=5)
    sus_q8: int = Field(ge=1, le=5)
    sus_q9: int = Field(ge=1, le=5)
    sus_q10: int = Field(ge=1, le=5)
    open_confusing: str | None = Field(default=None, max_length=2000)
    open_useful: str | None = Field(default=None, max_length=2000)
    open_suggestion: str | None = Field(default=None, max_length=2000)
    session_id: str | None = Field(default=None, max_length=36)
