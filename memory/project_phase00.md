---
name: project-phase00-complete
description: Phase 0 (Project Setup) scaffold is complete — all backend dirs, configs, stubs, docker-compose, and setup script created.
metadata:
  type: project
---

Phase 0 scaffold is fully generated and committed to the `dev` branch.

**Why:** Phase 0 establishes the skeleton every subsequent phase builds on — Python packages, pinned deps, config, infra files.

**How to apply:** When working on Phase 1+, trust that all package `__init__.py`, `config.py`, `main.py`, stub routers, and `infra/docker-compose.dev.yml` are already in place. Do not recreate them — extend them.

Key decisions made in Phase 0:
- Vector store: **OpenSearch Serverless only** — `faiss-cpu` is explicitly excluded
- Config pattern: `pydantic-settings` `BaseSettings` with `lru_cache` singleton at `backend/app/config.py`
- Logging: `structlog` — `ConsoleRenderer` in dev, `JSONRenderer` in prod
- Local dev: LocalStack 3.7 simulates S3, SQS, SecretsManager, OpenSearch; Postgres 16 for RDS
- Script: `scripts/setup_dev.sh` automates venv creation, docker-compose start, LocalStack resource provisioning, and `alembic upgrade head`
- Bedrock models: `anthropic.claude-3-5-sonnet-20241022-v2:0` (LLM), `amazon.titan-embed-text-v2:0` (embeddings)
