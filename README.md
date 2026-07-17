# CDT Platform

Production rebuild of the **Cognitive Digital Twin (CDT) behavioral-bias detection system** for
Indonesian retail investors — detecting Disposition Effect, Overconfidence, and Loss Aversion
through a 14-round historical-replay trading simulation on 12 IDX stocks.

This repo supersedes the research prototype
[`TA-18222007`](https://github.com/arvynopl/TA-18222007) (frozen at tag `thesis-defense`).
The research-validated **domain layer is ported unchanged** and guarded by a golden-master
parity test suite; only the presentation layer is rebuilt (FastAPI + Next.js, replacing
Streamlit).

## Layout

```
backend/            FastAPI API + ported domain layer (Python 3.11)
  config.py         All thresholds & tunable parameters (single source of truth)
  database/         SQLAlchemy 2.0 models, engine/session factory, seeding
  modules/          Domain logic: analytics, cdt, simulation, feedback, auth, utils
  app/              FastAPI application (routes land in Fase 1)
  alembic/          Versioned schema migrations
  tests/            Domain tests + golden-master parity suite
frontend/           Next.js app (Fase 2); static placeholder until then
```

## Development

```bash
# Backend
cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows; use bin/activate on POSIX
pip install -r requirements-dev.txt
pytest tests/                                     # domain + parity suite
uvicorn app.main:app --reload --port 8000

# Full stack (placeholder frontend)
docker compose up
```

Unset `CDT_DATABASE_URL` → local SQLite. Production uses Neon Postgres
(`ap-southeast-1`, co-located with the app per audit finding F1).

## Schema migrations

```bash
cd backend
alembic upgrade head                 # apply
alembic revision --autogenerate -m "…"  # create (review before committing!)
```

## Research parity — do not break

`tests/test_golden_master.py` asserts that DEI / OCS / LAI, bootstrap CIs, and the
EMA-updated CDT profile reproduce the thesis-defense pipeline's outputs **exactly**
on frozen fixture sessions. These formulas were validated in the thesis
(synthetic-agent agreement up to ρ = 0.97); any diff here is a regression, not a
refactor. Parameter values in `config.py` — including
`MIN_TRADES_FOR_FULL_SEVERITY = 1` — are research decisions; change them only with
new calibration data.

## Key parameters (`backend/config.py`)

| Parameter | Value | Meaning |
|---|---|---|
| `INITIAL_CAPITAL` | Rp 10,000,000 | Starting simulated portfolio |
| `ROUNDS_PER_SESSION` | 14 | Trading rounds per session |
| `ALPHA` / `ALPHA_MAX` | 0.3 / 0.45 | Activity-weighted EMA for bias intensity |
| `BETA` | 0.2 | EMA weight for risk preference |
| `MIN_TRADES_FOR_FULL_SEVERITY` | 1 | Severity uncapped from 1 realized trade; epistemic uncertainty is carried by confidence levels instead |
| `USE_DOLLAR_WEIGHTED_DEI` | True | Frazzini (2006) dollar-weighted DEI |

## Provenance

- Research: Arvyno Pranata Limahardja, Institut Teknologi Bandung (STEI/STI), 2026.
- Prototype evaluation: 374-test CI suite, 16-participant UAT (SUS 64.0), synthetic-agent
  validation ρ up to 0.97 — see thesis Bab VI.
