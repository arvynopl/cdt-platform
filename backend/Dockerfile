FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/backend

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Migrations run as a separate release step (alembic upgrade head), not at boot.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
