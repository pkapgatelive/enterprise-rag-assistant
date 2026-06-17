# Phase 0 — Project Setup & Repository Structure

## Goal

Produce a clean, runnable project scaffold with the correct directory tree, Python virtual environment, all dependency files, configuration templates, and environment variable handling. No application logic is written in this phase — only the skeleton that every subsequent phase will populate.

---

## Prerequisites

- Git repository already initialised (`enterprise-rag-assistant/`)
- Python 3.11+ installed
- Node.js 20 LTS installed
- Docker Desktop installed (for local Postgres and later deployment)
- AWS CLI v2 configured with a profile that has Bedrock access
- An AWS account with Amazon Bedrock model access enabled for:
  - `anthropic.claude-3-5-sonnet-20241022-v2:0`
  - `amazon.titan-embed-text-v2:0`

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
│   ├── docker-compose.dev.yml
│   └── cloudformation/         (placeholder for Phase 8)
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

# Vector Store
faiss-cpu==1.8.0
opensearch-py==2.7.1

# Database
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
alembic==1.13.3

# Storage
boto3==1.35.30  # covers S3

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
fakeredis==2.26.1
moto[s3,bedrock]==5.0.16
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

# Vector store local index
backend/data/faiss_index/

# AWS
.aws/
```

### Step 7 — Create `.env.example`

```dotenv
# ──────────────────────────────────────────────
# AWS Configuration
# ──────────────────────────────────────────────
AWS_REGION=us-east-1
AWS_PROFILE=default

# ──────────────────────────────────────────────
# Amazon Bedrock
# ──────────────────────────────────────────────
BEDROCK_LLM_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
BEDROCK_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0

# ──────────────────────────────────────────────
# Vector Store
# ──────────────────────────────────────────────
VECTOR_STORE_TYPE=faiss              # faiss | opensearch
FAISS_INDEX_PATH=backend/data/faiss_index
OPENSEARCH_ENDPOINT=https://your-collection.us-east-1.aoss.amazonaws.com
OPENSEARCH_INDEX_NAME=eka-knowledge-base

# ──────────────────────────────────────────────
# Amazon S3
# ──────────────────────────────────────────────
S3_BUCKET_NAME=eka-documents-dev
S3_PREFIX=uploads/

# ──────────────────────────────────────────────
# PostgreSQL
# ──────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://eka_user:eka_pass@localhost:5432/eka_db

# ──────────────────────────────────────────────
# Application
# ──────────────────────────────────────────────
APP_ENV=development
APP_PORT=8000
FRONTEND_URL=http://localhost:5173
MAX_UPLOAD_SIZE_MB=50
LOG_LEVEL=INFO
```

### Step 8 — Create `backend/app/config.py`

This file reads all env vars via Pydantic Settings and provides a single `settings` object used across the application.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # AWS
    aws_region: str = "us-east-1"
    aws_profile: str | None = None

    # Bedrock
    bedrock_llm_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"

    # Vector store
    vector_store_type: str = "faiss"
    faiss_index_path: str = "backend/data/faiss_index"
    opensearch_endpoint: str = ""
    opensearch_index_name: str = "eka-knowledge-base"

    # S3
    s3_bucket_name: str = "eka-documents-dev"
    s3_prefix: str = "uploads/"

    # Database
    database_url: str = "postgresql+asyncpg://eka_user:eka_pass@localhost:5432/eka_db"

    # Application
    app_env: str = "development"
    app_port: int = 8000
    frontend_url: str = "http://localhost:5173"
    max_upload_size_mb: int = 50
    log_level: str = "INFO"


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

Provides a local Postgres instance for development without any cloud dependency:

```yaml
version: "3.9"

services:
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

  pgadmin:
    image: dpage/pgadmin4:latest
    container_name: eka_pgadmin
    environment:
      PGADMIN_DEFAULT_EMAIL: admin@eka.local
      PGADMIN_DEFAULT_PASSWORD: admin
    ports:
      - "5050:80"
    depends_on:
      - postgres

volumes:
  eka_pgdata:
```

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

echo "==> Starting local Postgres via Docker Compose"
docker compose -f infra/docker-compose.dev.yml up -d

echo "==> Setup complete. Activate venv with: source .venv/bin/activate"
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
   boto3, langchain, langchain-community, langchain-aws, pypdf, python-docx,
   openpyxl, python-pptx, unstructured, beautifulsoup4, faiss-cpu, opensearch-py,
   sqlalchemy[asyncio], asyncpg, alembic, python-dotenv, httpx, tenacity, structlog

3. Write `backend/requirements-dev.txt` extending requirements.txt with:
   pytest, pytest-asyncio, pytest-cov, httpx, moto[s3], ruff, mypy, pre-commit

4. Write `pyproject.toml` at the repo root configuring ruff (line-length=100),
   mypy (python_version=3.11), and pytest (asyncio_mode=auto).

5. Write `.gitignore` excluding: __pycache__, .venv, .env, node_modules,
   frontend/dist, backend/data/faiss_index, .DS_Store, *.log

6. Write `.env.example` with all variables documented:
   AWS_REGION, AWS_PROFILE, BEDROCK_LLM_MODEL_ID, BEDROCK_EMBEDDING_MODEL_ID,
   VECTOR_STORE_TYPE (faiss|opensearch), FAISS_INDEX_PATH, OPENSEARCH_ENDPOINT,
   OPENSEARCH_INDEX_NAME, S3_BUCKET_NAME, S3_PREFIX, DATABASE_URL, APP_ENV,
   APP_PORT, FRONTEND_URL, MAX_UPLOAD_SIZE_MB, LOG_LEVEL

7. Write `backend/app/config.py` using Pydantic BaseSettings with lru_cache,
   reading from .env file.

8. Write `backend/app/main.py` as a FastAPI skeleton with CORS middleware and
   three router includes: health, documents, query.

9. Write `backend/app/utils/logger.py` using structlog with JSON in prod,
   ConsoleRenderer in dev.

10. Write stub routers: health.py returns {"status":"ok"}, documents.py and
    query.py are empty APIRouter stubs.

11. Write `infra/docker-compose.dev.yml` with postgres:16-alpine and pgadmin4
    services.

12. Write `scripts/setup_dev.sh` that creates a venv, installs requirements-dev.txt,
    copies .env.example to .env, and starts docker compose.

Generate all files with correct content. Do not skip any file.
```

---

## Acceptance Criteria

Before moving to Phase 1, verify:

- [ ] `source .venv/bin/activate && pip install -r backend/requirements-dev.txt` completes without errors
- [ ] `cd backend && uvicorn app.main:app --reload` starts without import errors
- [ ] `GET http://localhost:8000/api/v1/health` returns `{"status":"ok"}`
- [ ] `docker compose -f infra/docker-compose.dev.yml up -d` starts Postgres successfully
- [ ] `psql -h localhost -U eka_user -d eka_db` connects without error
- [ ] `cd frontend && npm run dev` starts the Vite dev server on port 5173
- [ ] `.env` is present and git-ignored
