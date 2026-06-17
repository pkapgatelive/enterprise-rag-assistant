#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Creating Python virtual environment"
python3.11 -m venv .venv
source .venv/bin/activate

echo "==> Installing backend dependencies"
pip install --upgrade pip
pip install -r backend/requirements-dev.txt

echo "==> Copying .env.example to .env"
cp -n .env.example .env || true

echo "==> Starting LocalStack + Postgres via Docker Compose"
docker compose -f infra/docker-compose.dev.yml up -d

echo "==> Waiting for LocalStack to be healthy..."
until curl -sf http://localhost:4566/_localstack/health | grep -q '"s3": "running"'; do
  echo "    ... still waiting"
  sleep 2
done
echo "    LocalStack is ready."

echo "==> Provisioning LocalStack resources"
awslocal s3 mb s3://eka-documents-dev || true
awslocal sqs create-queue --queue-name eka-ingestion-queue || true
awslocal secretsmanager create-secret \
  --name eka/rds-credentials \
  --secret-string '{"username":"eka_user","password":"eka_pass","host":"localhost","port":5432,"dbname":"eka_db"}' \
  2>/dev/null || true

echo "==> Running Alembic migrations"
cd backend && alembic upgrade head && cd "$REPO_ROOT"

echo ""
echo "==> Setup complete."
echo "    Activate venv  : source .venv/bin/activate"
echo "    Start API      : cd backend && uvicorn app.main:app --reload"
echo "    LocalStack     : http://localhost:4566"
echo "    PostgreSQL     : localhost:5432 (eka_db)"
echo "    PGAdmin        : http://localhost:5050  (admin@eka.local / admin)"
