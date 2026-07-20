"""tests/test_account.py — UU PDP export + anonymisation (audit F8)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.account import anonymize_user, export_user_data
from database.models import (
    BiasMetric,
    ConsentLog,
    OnboardingSurvey,
    UATFeedback,
    User,
    UserProfile,
)
from tests.conftest import csrf_headers
from tests.test_api_auth import _register_payload


def _seed_full_user(db) -> User:
    u = User(
        username="dewi.lestari",
        password_hash="bcrypt-hash",
        alias="dewi.lestari",
        experience_level="menengah",
    )
    db.add(u)
    db.flush()
    db.add(UserProfile(
        user_id=u.id, full_name="Dewi Lestari", age=28, gender="perempuan",
        risk_profile="moderat", investing_capability="pemula",
    ))
    db.add(ConsentLog(
        user_id=u.id, consent_given=True, consent_text="Setuju.", ip_hash="deadbeef",
    ))
    db.add(OnboardingSurvey(
        user_id=u.id, dei_q1=3, dei_q2=3, dei_q3=3, ocs_q1=3, ocs_q2=3, ocs_q3=3,
        lai_q1=3, lai_q2=3, lai_q3=3,
    ))
    db.add(BiasMetric(
        user_id=u.id, session_id="sess-1", overconfidence_score=0.3,
        disposition_pgr=0.6, disposition_plr=0.4, disposition_dei=0.2,
        loss_aversion_index=0.5, computed_at=datetime.now(UTC),
    ))
    db.add(UATFeedback(
        user_id=u.id, session_id="sess-1",
        sus_q1=4, sus_q2=2, sus_q3=4, sus_q4=2, sus_q5=4,
        sus_q6=2, sus_q7=4, sus_q8=2, sus_q9=4, sus_q10=2,
        open_confusing="Nama saya Dewi, agak bingung di awal.",
        open_useful="Umpan baliknya bagus.",
    ))
    db.flush()
    return u


class TestExport:
    def test_export_includes_all_the_users_data(self, db):
        u = _seed_full_user(db)
        data = export_user_data(db, u.id)

        assert data["account"]["username"] == "dewi.lestari"
        assert data["profile"]["full_name"] == "Dewi Lestari"
        assert data["onboarding_survey"]["dei_q1"] == 3
        assert len(data["bias_metrics"]) == 1
        assert len(data["uat_feedback"]) == 1
        # Consent is exported without the pseudonymised IP hash.
        assert data["consent"] and "ip_hash" not in data["consent"][0]

    def test_csv_zip_export_has_a_csv_per_populated_section(self, db):
        import io
        import zipfile

        from app.services.account import export_user_data_csv_zip

        u = _seed_full_user(db)
        payload = export_user_data_csv_zip(db, u.id)

        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = set(zf.namelist())
            # A CSV per populated collection, plus the readme manifest.
            assert {
                "account.csv",
                "profile.csv",
                "onboarding_survey.csv",
                "bias_metrics.csv",
                "uat_feedback.csv",
                "BACA-DULU.txt",
            } <= names

            account = zf.read("account.csv").decode("utf-8-sig")
            assert "username" in account.splitlines()[0]  # header row
            assert "dewi.lestari" in account
            # UTF-8 BOM present so Excel reads the encoding correctly.
            assert zf.read("account.csv").startswith(b"\xef\xbb\xbf")


class TestAnonymize:
    def test_strips_identity_and_login_but_keeps_research(self, db):
        uid = _seed_full_user(db).id

        anonymize_user(db, uid)
        db.expire_all()

        u = db.get(User, uid)
        assert u.username is None
        assert u.alias is None
        assert u.password_hash is None
        assert u.last_login_at is None

        # PII profile removed entirely.
        assert db.query(UserProfile).filter_by(user_id=uid).first() is None

        # De-identified research rows retained under the anonymous user id.
        assert db.query(BiasMetric).filter_by(user_id=uid).count() == 1
        assert db.query(OnboardingSurvey).filter_by(user_id=uid).first() is not None

        # Consent record kept as the retention basis, but IP hash cleared.
        consent = db.query(ConsentLog).filter_by(user_id=uid).first()
        assert consent is not None
        assert consent.ip_hash is None

        # Free-text scrubbed, SUS scores preserved.
        fb = db.query(UATFeedback).filter_by(user_id=uid).first()
        assert fb.open_confusing is None
        assert fb.open_useful is None
        assert fb.sus_q1 == 4


class TestAccountApi:
    def test_export_then_delete_ends_session_and_blocks_relogin(self, api_client):
        resp = api_client.post(
            "/api/auth/register", json=_register_payload("citra.dewi")
        )
        assert resp.status_code == 201

        exp = api_client.get("/api/me/export")
        assert exp.status_code == 200
        assert exp.json()["account"]["username"] == "citra.dewi"
        assert exp.json()["profile"]["full_name"] == "Budi Santoso"

        # Deletion is a mutation → CSRF required.
        assert api_client.post("/api/me/delete").status_code == 403

        ok = api_client.post("/api/me/delete", headers=csrf_headers(api_client))
        assert ok.status_code == 200

        # Session ended, and the cleared username can no longer log in.
        assert api_client.get("/api/auth/me").status_code == 401
        relogin = api_client.post(
            "/api/auth/login",
            json={"username": "citra.dewi", "password": "rahasia-123"},
        )
        assert relogin.status_code == 401
