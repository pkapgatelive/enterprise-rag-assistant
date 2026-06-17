# Phase 0 — Project Setup & Repository Structure

## Goal

Produce a clean, runnable project scaffold with the correct directory tree, Python virtual environment, all dependency files, configuration templates, and environment variable handling. No application logic is written in this phase — only the skeleton that every subsequent phase will populate.

---

## Prerequisites

- Git repository already initialised (`enterprise-rag-assistant/`)
- Python 3.11+ installed
- Node.js 20 LTS installed
- Docker Desktop installed (for LocalStack and later deployment)
- AWS CLI v2 configured with a profile that has Bedrock and OpenSearch access
- An AWS account with Amazon Bedrock model access enabled for:
  - `anthropic.claude-3-5-sonnet-20241022-v2:0`
  - `amazon.titan-embed-text-v2:0`
- AWS CDK v2 installed globally: `npm install -g aws-cdk`
- LocalStack CLI installed: `pip install localstack awscli-local`

---

## Target Directory Structure

```
enterprise-rag-assistant/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── routes/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── documents.py
│   │   │   │   ├── query.py
│   │   │   │   └── health.py
│   │   │   └── dependencies.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── document_processor/
│   │   │   │   └── __init__.py
│   │   │   ├── embeddings/
│   │   │   │   └── __init__.py
│   │   │   ├── vector_store/
│   │   │   │   └── __init__.py
│   │   │   └── rag/
│   │   │       └── __init__.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── document.py
│   │   │   └── query.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── s3_service.py
│   │   │   └── db_service.py
│   │   └── utils/
│   │       ├── __init__.py
│   │       └── logger.py
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── unit/
│   │   │   └── __init__.py
│   │   └── integration/
│   │       └── __init__.py
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── types/
│   │   └── utils/
│   ├── public/
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   └── Dockerfile
├── infra/
│   ├── docker-compose.yml
│   ├── docker-compose.dev.yml  (LocalStack + local backend)
│   └── cdk/                    (AWS CDK app — built in Phase 8)
│       ├── app.py
│       ├── requirements.txt
│       └── stacks/
│           ├── __init__.py
│           ├── network_stack.py
│           ├── data_stack.py
│           ├── compute_stack.py
│           └── frontend_stack.py
├── scripts/
│   ├── setup_dev.sh
│   └── ingest_sample_docs.py
├── docs/
│   └── implementation-plan/    (this directory)
├── .env.example
├── .env                        (git-ignored)
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## Step-by-Step Instructions

### Step 1 — Create the backend directory tree

```bash
cd enterprise-rag-assistant

mkdir -p backend/app/api/routes
mkdir -p backend/app/core/document_processor
mkdir -p backend/app/core/embeddings
mkdir -p backend/app/core/vector_store
mkdir -p backend/app/core/rag
mkdir -p backend/app/models
mkdir -p backend/app/services
mkdir -p backend/app/utils
mkdir -p backend/tests/unit
mkdir -p backend/tests/integration
```

Create empty `__init__.py` files in every Python package directory listed above.

### Step 2 — Create the frontend scaffold

Use Vite to bootstrap a React + TypeScript project:

```bash
cd enterprise-rag-assistant
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

Create the subdirectories inside `frontend/src/`:

```bash
mkdir -p frontend/src/components
mkdir -p frontend/src/pages
mkdir -p frontend/src/hooks
mkdir -p frontend/src/services
mkdir -p frontend/src/types
mkdir -p frontend/src/utils
```

### Step 3 — Create `backend/requirements.txt`

```text
# Core Framework
fastapi==0.115.0
uvicorn[standard]==0.30.6
pydantic==2.9.2
pydantic-settings==2.5.2
python-multipart==0.0.12

# AWS / Bedrock
boto3==1.35.30
botocore==1.35.30

# LangChain
langchain==0.3.7
langchain-community==0.3.7
langchain-aws==0.2.3

# Document Processing
pypdf==5.0.1
python-docx==1.1.2
openpyxl==3.1.5
python-pptx==1.0.2
unstructured[pdf,docx,pptx,xlsx]==0.15.14
beautifulsoup4==4.12.3

# Vector Store (Amazon OpenSearch Serverless)
opensearch-py==2.7.1
requests-aws4auth==1.3.1

# Database
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
alembic==1.13.3

# Async task queue (Amazon SQS)
aiobotocore==2.15.0

# AWS X-Ray tracing
aws-xray-sdk==2.14.0

# Utilities
python-dotenv==1.0.1
httpx==0.27.2
tenacity==9.0.0
structlog==24.4.0
```

### Step 4 — Create `backend/requirements-dev.txt`

```text
-r requirements.txt

pytest==8.3.3
pytest-asyncio==0.24.0
pytest-cov==5.0.0
httpx==0.27.2
aiosqlite==0.20.0
moto[s3,sqs,secretsmanager,opensearch]==5.0.16
localstack==3.7.0
awscli-local==0.22.0
ruff==0.7.0
mypy==1.13.0
pre-commit==4.0.1
```

### Step 5 — Create `pyproject.toml` (project root)

```toml
[tool.ruff]
line-length = 100
select = ["E", "F", "I", "N", "UP"]

[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true
strict = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["backend/tests"]
```

### Step 6 — Create `.gitignore`

Include at minimum:

```
# Python
__pycache__/
*.py[cod]
.venv/
venv/
*.egg-info/
dist/
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/

# Environment
.env
.env.local
.env.*.local

# Node
node_modules/
frontend/dist/
frontend/build/

# Docker
*.log

# MacOS
.DS_Store

# LocalStack persistence volume (managed by Docker)
.localstack/

# CDK output
infra/cdk/cdk.out/

# AWS
.aws/
```

### Step 7 — Create `.env.example`

```dotenv
# ──────────────────────────────────────────────
# AWS Core
# ──────────────────────────────────────────────
AWS_REGION=us-east-1
AWS_PROFILE=default
AWS_ACCOUNT_ID=123456789012

# ──────────────────────────────────────────────
# Amazon Bedrock
# ──────────────────────────────────────────────
BEDROCK_LLM_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
BEDROCK_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0

# ──────────────────────────────────────────────
# Amazon OpenSearch Serverless (single vector store)
# ──────────────────────────────────────────────
OPENSEARCH_ENDPOINT=https://your-collection-id.us-east-1.aoss.amazonaws.com
OPENSEARCH_INDEX_NAME=eka-knowledge-base

# ──────────────────────────────────────────────
# Amazon S3 — Document Storage
# ──────────────────────────────────────────────
S3_BUCKET_NAME=eka-documents-dev
S3_PREFIX=uploads/

# ──────────────────────────────────────────────
# Amazon SQS — Async Ingestion Queue
# ──────────────────────────────────────────────
SQS_INGESTION_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789012/eka-ingestion-queue
SQS_INGESTION_QUEUE_ARN=arn:aws:sqs:us-east-1:123456789012:eka-ingestion-queue

# ──────────────────────────────────────────────
# Amazon RDS — PostgreSQL
# ──────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://eka_user:eka_pass@eka-db.cluster-xxxx.us-east-1.rds.amazonaws.com:5432/eka_db
RDS_SECRET_ARN=arn:aws:secretsmanager:us-east-1:123456789012:secret:eka/rds-credentials

# ──────────────────────────────────────────────
# AWS Secrets Manager
# ──────────────────────────────────────────────
# In production, DATABASE_URL is loaded from Secrets Manager using RDS_SECRET_ARN above.
# Set USE_SECRETS_MANAGER=true in non-local environments.
USE_SECRETS_MANAGER=false

# ──────────────────────────────────────────────
# Amazon Cognito — Authentication
# ──────────────────────────────────────────────
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_APP_CLIENT_ID=your-app-client-id
COGNITO_REGION=us-east-1
COGNITO_JWKS_URL=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXXXXXXX/.well-known/jwks.json

# ──────────────────────────────────────────────
# Amazon CloudFront — Frontend CDN
# ──────────────────────────────────────────────
CLOUDFRONT_DOMAIN=https://dxxxxxxxxxxxx.cloudfront.net
FRONTEND_S3_BUCKET=eka-frontend-static

# ──────────────────────────────────────────────
# AWS X-Ray — Distributed Tracing
# ──────────────────────────────────────────────
XRAY_ENABLED=false                   # set true in production

# ──────────────────────────────────────────────
# Application
# ──────────────────────────────────────────────
APP_ENV=development
APP_PORT=8000
FRONTEND_URL=http://localhost:5173   # replaced by CLOUDFRONT_DOMAIN in production
MAX_UPLOAD_SIZE_MB=50
LOG_LEVEL=INFO

# ──────────────────────────────────────────────
# LocalStack (local AWS simulation — dev only)
# ──────────────────────────────────────────────
LOCALSTACK_ENDPOINT=http://localhost:4566
```

### Step 8 — Create `backend/app/config.py`

This file reads all env vars via Pydantic Settings and provides a single `settings` object used across the application.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # AWS Core
    aws_region: str = "us-east-1"
    aws_profile: str | None = None
    aws_account_id: str = ""

    # Amazon Bedrock
    bedrock_llm_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"

    # Amazon OpenSearch Serverless (single vector store)
    opensearch_endpoint: str = ""
    opensearch_index_name: str = "eka-knowledge-base"

    # Amazon S3
    s3_bucket_name: str = "eka-documents-dev"
    s3_prefix: str = "uploads/"

    # Amazon SQS
    sqs_ingestion_queue_url: str = ""
    sqs_ingestion_queue_arn: str = ""

    # Amazon RDS / Database
    database_url: str = "postgresql+asyncpg://eka_user:eka_pass@localhost:5432/eka_db"
    rds_secret_arn: str = ""
    use_secrets_manager: bool = False

    # Amazon Cognito
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""
    cognito_region: str = "us-east-1"
    cognito_jwks_url: str = ""

    # Amazon CloudFront / Frontend
    cloudfront_domain: str = ""
    frontend_s3_bucket: str = ""

    # AWS X-Ray
    xray_enabled: bool = False

    # Application
    app_env: str = "development"
    app_port: int = 8000
    frontend_url: str = "http://localhost:5173"
    max_upload_size_mb: int = 50
    log_level: str = "INFO"

    # LocalStack (dev only)
    localstack_endpoint: str = ""

    @property
    def is_local(self) -> bool:
        return self.app_env == "development"

    @property
    def effective_frontend_url(self) -> str:
        return self.cloudfront_domain if self.cloudfront_domain else self.frontend_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
```

### Step 9 — Create `backend/app/main.py` (skeleton)

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.routes import documents, query, health

app = FastAPI(
    title="Enterprise Knowledge Assistant API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])
app.include_router(query.router, prefix="/api/v1/query", tags=["query"])
```

### Step 10 — Create `infra/docker-compose.dev.yml`

Provides a **LocalStack** container (AWS simulation) and a local PostgreSQL instance for development.
LocalStack simulates S3, SQS, Secrets Manager, and OpenSearch so no real AWS charges are incurred during local development.

```yaml
version: "3.9"

services:

  # ── Local AWS simulation via LocalStack ──────────────────────────────────
  localstack:
    image: localstack/localstack:3.7
    container_name: eka_localstack
    ports:
      - "4566:4566"         # all AWS service endpoints on one port
    environment:
      - SERVICES=s3,sqs,secretsmanager,opensearch
      - DEFAULT_REGION=us-east-1
      - DEBUG=0
      - PERSISTENCE=1
    volumes:
      - localstack_data:/var/lib/localstack
      - /var/run/docker.sock:/var/run/docker.sock
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4566/_localstack/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── Local PostgreSQL (mirrors Amazon RDS schema) ─────────────────────────
  postgres:
    image: postgres:16-alpine
    container_name: eka_postgres
    environment:
      POSTGRES_USER: eka_user
      POSTGRES_PASSWORD: eka_pass
      POSTGRES_DB: eka_db
    ports:
      - "5432:5432"
    volumes:
      - eka_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U eka_user -d eka_db"]
      interval: 10s
      timeout: 5s
      retries: 5

  pgadmin:
    image: dpage/pgadmin4:latest
    container_name: eka_pgadmin
    environment:
      PGADMIN_DEFAULT_EMAIL: admin@eka.local
      PGADMIN_DEFAULT_PASSWORD: admin
    ports:
      - "5050:80"
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  eka_pgdata:
  localstack_data:
```

After starting, initialise the LocalStack resources with:

```bash
# Create S3 bucket
awslocal s3 mb s3://eka-documents-dev

# Create SQS ingestion queue
awslocal sqs create-queue --queue-name eka-ingestion-queue

# Store a local DB secret in Secrets Manager
awslocal secretsmanager create-secret \
  --name eka/rds-credentials \
  --secret-string '{"username":"eka_user","password":"eka_pass","host":"localhost","port":5432,"dbname":"eka_db"}'
```

Add these commands to `scripts/setup_dev.sh`.

### Step 11 — Create `scripts/setup_dev.sh`

```bash
#!/usr/bin/env bash
set -e

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
  sleep 2
done

echo "==> Provisioning LocalStack resources"
awslocal s3 mb s3://eka-documents-dev
awslocal sqs create-queue --queue-name eka-ingestion-queue
awslocal secretsmanager create-secret \
  --name eka/rds-credentials \
  --secret-string '{"username":"eka_user","password":"eka_pass","host":"localhost","port":5432,"dbname":"eka_db"}' 2>/dev/null || true

echo "==> Running Alembic migrations"
cd backend && alembic upgrade head && cd ..

echo "==> Setup complete. Activate venv with: source .venv/bin/activate"
echo "    LocalStack endpoint: http://localhost:4566"
echo "    PostgreSQL: localhost:5432 (eka_db)"
echo "    PGAdmin: http://localhost:5050"
```

Make it executable: `chmod +x scripts/setup_dev.sh`

### Step 12 — Create `backend/app/utils/logger.py`

```python
import structlog
import logging
from app.config import settings


def configure_logging() -> None:
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if settings.app_env == "development"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
    )


logger = structlog.get_logger()
```

### Step 13 — Create stub route files

Create `backend/app/api/routes/health.py`:

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "Enterprise Knowledge Assistant"}
```

Create empty stub routers in `documents.py` and `query.py`:

```python
from fastapi import APIRouter

router = APIRouter()
```

---

## Code Generation Prompt

Paste the following prompt into Claude Code (or any AI coding assistant) to generate this phase:

```
You are building the project scaffold for a production-ready RAG application called
"Enterprise Knowledge Assistant" (EKA). The repository root is `enterprise-rag-assistant/`.

Task: Generate ALL files needed for Phase 0 — Project Setup.

Requirements:
1. Create the full backend directory tree under `backend/` exactly as specified:
   - `backend/app/` with sub-packages: api/routes, core/document_processor,
     core/embeddings, core/vector_store, core/rag, models, services, utils
   - Each Python package must have an `__init__.py`
   - `backend/tests/unit/` and `backend/tests/integration/` with `__init__.py`

2. Write `backend/requirements.txt` with pinned versions for:
   fastapi, uvicorn[standard], pydantic v2, pydantic-settings, python-multipart,
   boto3, aiobotocore, langchain, langchain-community, langchain-aws, pypdf,
   python-docx, openpyxl, python-pptx, unstructured, beautifulsoup4,
   opensearch-py, requests-aws4auth, sqlalchemy[asyncio], asyncpg, alembic,
   python-dotenv, httpx, tenacity, structlog, aws-xray-sdk
   NOTE: do NOT include faiss-cpu — OpenSearch Serverless is the only vector store.

3. Write `backend/requirements-dev.txt` extending requirements.txt with:
   pytest, pytest-asyncio, pytest-cov, httpx, aiosqlite,
   moto[s3,sqs,secretsmanager,opensearch], localstack, awscli-local,
   ruff, mypy, pre-commit

4. Write `pyproject.toml` at the repo root configuring ruff (line-length=100),
   mypy (python_version=3.11), and pytest (asyncio_mode=auto).

5. Write `.gitignore` excluding: __pycache__, .venv, .env, node_modules,
   frontend/dist, .localstack/, infra/cdk/cdk.out/, .DS_Store, *.log

6. Write `.env.example` with all variables documented:
   AWS_REGION, AWS_PROFILE, AWS_ACCOUNT_ID,
   BEDROCK_LLM_MODEL_ID, BEDROCK_EMBEDDING_MODEL_ID,
   OPENSEARCH_ENDPOINT, OPENSEARCH_INDEX_NAME,
   S3_BUCKET_NAME, S3_PREFIX,
   SQS_INGESTION_QUEUE_URL, SQS_INGESTION_QUEUE_ARN,
   DATABASE_URL, RDS_SECRET_ARN, USE_SECRETS_MANAGER,
   COGNITO_USER_POOL_ID, COGNITO_APP_CLIENT_ID, COGNITO_REGION, COGNITO_JWKS_URL,
   CLOUDFRONT_DOMAIN, FRONTEND_S3_BUCKET,
   XRAY_ENABLED,
   APP_ENV, APP_PORT, FRONTEND_URL, MAX_UPLOAD_SIZE_MB, LOG_LEVEL,
   LOCALSTACK_ENDPOINT

7. Write `backend/app/config.py` using Pydantic BaseSettings with lru_cache,
   reading from .env file. Include all AWS service settings (Bedrock, OpenSearch,
   S3, SQS, RDS, Secrets Manager, Cognito, CloudFront, X-Ray, LocalStack).
   Add `is_local` property (returns True when APP_ENV=development) and
   `effective_frontend_url` property (returns CLOUDFRONT_DOMAIN if set, else FRONTEND_URL).

8. Write `backend/app/main.py` as a FastAPI skeleton with CORS middleware and
   three router includes: health, documents, query.

9. Write `backend/app/utils/logger.py` using structlog with JSON in prod,
   ConsoleRenderer in dev.

10. Write stub routers: health.py returns {"status":"ok"}, documents.py and
    query.py are empty APIRouter stubs.

11. Write `infra/docker-compose.dev.yml` with:
    - localstack/localstack:3.7 (SERVICES=s3,sqs,secretsmanager,opensearch, port 4566)
    - postgres:16-alpine with healthcheck
    - pgadmin4 depending on postgres health

12. Write `scripts/setup_dev.sh` that:
    - Creates a venv and installs requirements-dev.txt
    - Copies .env.example to .env
    - Starts docker compose (LocalStack + Postgres)
    - Waits for LocalStack health endpoint
    - Uses awslocal to create: S3 bucket, SQS queue, Secrets Manager secret
    - Runs alembic upgrade head

Generate all files with correct content. Do not skip any file.
```

---

## Acceptance Criteria

Before moving to Phase 1, verify:

- [ ] `source .venv/bin/activate && pip install -r backend/requirements-dev.txt` completes without errors
- [ ] `faiss-cpu` is NOT in requirements.txt — confirm with `grep -c faiss backend/requirements.txt` returning 0
- [ ] `cd backend && uvicorn app.main:app --reload` starts without import errors
- [ ] `GET http://localhost:8000/api/v1/health` returns `{"status":"ok"}`
- [ ] `docker compose -f infra/docker-compose.dev.yml up -d` starts LocalStack and Postgres
- [ ] `curl -s http://localhost:4566/_localstack/health` shows `s3`, `sqs`, `secretsmanager` as running
- [ ] `awslocal s3 ls` shows the `eka-documents-dev` bucket
- [ ] `awslocal sqs list-queues` shows `eka-ingestion-queue`
- [ ] `psql -h localhost -U eka_user -d eka_db` connects without error
- [ ] `cd frontend && npm run dev` starts the Vite dev server on port 5173
- [ ] `.env` is present and git-ignored
- [ ] `infra/cdk/` directory scaffolded with `app.py` and `stacks/` directory
