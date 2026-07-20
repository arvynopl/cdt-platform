"""app/services/account.py — UU PDP data-subject rights (audit F8).

Two operations a participant can invoke on their own account:

* ``export_user_data`` — everything the system holds about them, as a plain
  dict ready to serialise to JSON (their right to data portability).
* ``anonymize_user`` — withdrawal. Per the owner's decision the account is
  *anonymised, not hard-deleted*: identifying and login data is removed, but
  the de-identified research rows (bias metrics, CDT trajectory, session
  actions, survey answers) are retained under the now-anonymous user id, on
  the consent basis recorded at registration. The account can never log in
  again (username and password are cleared).

What is removed vs retained on anonymisation:

  removed   AuthSession (all tokens), LoginAttempt (by username), UserProfile
            (name + demographics); User.username / alias / password_hash /
            last_login_at nulled; ConsentLog.ip_hash nulled (the consent
            record itself is kept as the retention basis); UATFeedback free
            text (open_confusing / open_useful) nulled.
  retained  OnboardingSurvey, UserSurvey, CognitiveProfile, BiasMetric,
            CdtSnapshot, PostSessionSurvey, UATFeedback (SUS scores),
            SessionSummary, SessionError, UserAction, FeedbackHistory.

To retain age/gender de-identified instead of deleting the whole profile,
null UserProfile.full_name here rather than deleting the row.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from database.models import (
    AuthSession,
    BiasMetric,
    CdtSnapshot,
    CognitiveProfile,
    ConsentLog,
    LoginAttempt,
    OnboardingSurvey,
    PostSessionSurvey,
    SessionSummary,
    UATFeedback,
    User,
    UserAction,
    UserProfile,
    UserSurvey,
)


def _serialize(obj, *, drop: set[str] | None = None) -> dict:
    """Row → dict over its mapped columns; datetimes to ISO-8601."""
    drop = drop or set()
    out: dict = {}
    for col in obj.__table__.columns:
        name = col.name
        if name in drop:
            continue
        val = getattr(obj, name)
        out[name] = val.isoformat() if isinstance(val, datetime) else val
    return out


def export_user_data(db: Session, user_id: int) -> dict:
    """Return every record tied to ``user_id`` as a JSON-serialisable dict.

    Excludes only the session-token internals (AuthSession) and the
    pseudonymised IP hashes, which are security artifacts rather than the
    participant's own content.
    """
    user = db.get(User, user_id)
    if user is None:
        raise ValueError(f"user {user_id} not found")

    def rows(model):
        return db.query(model).filter(model.user_id == user_id).all()

    profile = db.query(UserProfile).filter_by(user_id=user_id).first()
    onboarding = db.query(OnboardingSurvey).filter_by(user_id=user_id).first()
    cdt = db.query(CognitiveProfile).filter_by(user_id=user_id).first()

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "account": {
            "user_id": user.id,
            "username": user.username,
            "experience_level": user.experience_level,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "profile": _serialize(profile) if profile else None,
        "consent": [_serialize(c, drop={"ip_hash"}) for c in rows(ConsentLog)],
        "onboarding_survey": _serialize(onboarding) if onboarding else None,
        "user_surveys": [_serialize(s) for s in rows(UserSurvey)],
        "cognitive_profile": _serialize(cdt) if cdt else None,
        "bias_metrics": [_serialize(m) for m in rows(BiasMetric)],
        "cdt_snapshots": [_serialize(s) for s in rows(CdtSnapshot)],
        "post_session_surveys": [_serialize(s) for s in rows(PostSessionSurvey)],
        "uat_feedback": [_serialize(f) for f in rows(UATFeedback)],
        "sessions": [_serialize(s) for s in rows(SessionSummary)],
        "actions": [_serialize(a) for a in rows(UserAction)],
    }


def _collection_to_csv(records: list[dict]) -> str:
    """Serialise a list of row-dicts to CSV text.

    Columns are the union of every row's keys in first-seen order, so a row
    missing a field still lines up. None becomes an empty cell.
    """
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in records:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in records:
        writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
    return buf.getvalue()


def export_user_data_csv_zip(db: Session, user_id: int) -> bytes:
    """The same data as ``export_user_data``, as a ZIP of per-table CSVs.

    JSON remains the canonical, full-fidelity portability format; a single CSV
    cannot represent this relational export, so each collection becomes its own
    CSV inside a ZIP. Single-object sections (account, profile, …) are written
    as a one-row CSV. Each CSV carries a UTF-8 BOM so Excel opens the Indonesian
    text with the right encoding. Empty/absent sections are skipped.
    """
    data = export_user_data(db, user_id)
    exported_at = data.pop("exported_at", None)

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
        for key, value in data.items():
            if value is None:
                continue
            records = [value] if isinstance(value, dict) else value
            if not records:
                continue
            zf.writestr(f"{key}.csv", "﻿" + _collection_to_csv(records))

        zf.writestr(
            "BACA-DULU.txt",
            (
                "Ekspor data CDT Platform (format CSV).\n"
                f"Diekspor pada: {exported_at}\n\n"
                "Setiap berkas .csv berisi satu jenis data (profil, sesi, "
                "metrik bias, dan seterusnya). Ini adalah data yang sama "
                "dengan ekspor JSON, hanya dipecah agar mudah dibuka di "
                "aplikasi lembar kerja seperti Excel.\n"
            ),
        )
    return zbuf.getvalue()


def anonymize_user(db: Session, user_id: int) -> None:
    """Withdraw a participant: strip identity + login, keep research rows.

    Idempotent-ish: re-running on an already-anonymised user is a no-op beyond
    re-nulling already-null fields.
    """
    user = db.get(User, user_id)
    if user is None:
        raise ValueError(f"user {user_id} not found")

    old_username = user.username

    # Login / session artifacts — no research value, hold tokens and IP hashes.
    db.query(AuthSession).filter_by(user_id=user_id).delete(synchronize_session=False)
    if old_username:
        db.query(LoginAttempt).filter_by(username=old_username).delete(
            synchronize_session=False
        )

    # Demographic profile (name + age/gender/risk/capability).
    db.query(UserProfile).filter_by(user_id=user_id).delete(synchronize_session=False)

    # Keep the consent record as the retention basis, but drop its IP hash.
    for consent in db.query(ConsentLog).filter_by(user_id=user_id):
        consent.ip_hash = None

    # Free-text feedback could contain typed identifiers; keep the SUS scores.
    for fb in db.query(UATFeedback).filter_by(user_id=user_id):
        fb.open_confusing = None
        fb.open_useful = None

    # The identity itself: unusable for login, unlinkable to a person.
    user.username = None
    user.alias = None
    user.password_hash = None
    user.last_login_at = None

    db.flush()
