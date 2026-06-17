# Enterprise Knowledge Assistant (EKA) — Implementation Plan Index

## Project Summary

Enterprise Knowledge Assistant is a production-ready RAG application that allows users to query enterprise documents using natural language. It uses Amazon Bedrock (Claude + Titan Embeddings), LangChain, Amazon OpenSearch Serverless for vector search, FastAPI backend, and a React/TypeScript frontend.

---

## Implementation Phases

| Phase | File | Title | Description |
|-------|------|--------|-------------|
| 0 | [phase-00-project-setup.md](phase-00-project-setup.md) | Project Setup & Repository Structure | Create the full folder scaffold, Python environment, dependency files, and configuration baseline |
| 1 | [phase-01-document-processing.md](phase-01-document-processing.md) | Document Processing Pipeline | Build loaders, text extraction, cleaning, chunking, and metadata tagging for all supported formats |
| 2 | [phase-02-embeddings-vector-db.md](phase-02-embeddings-vector-db.md) | Embeddings & Vector Database | Generate embeddings via Amazon Titan Text Embeddings V2 and index them into Amazon OpenSearch Serverless (single vector store across all environments) |
| 3 | [phase-03-rag-core.md](phase-03-rag-core.md) | RAG Core — Retrieval & LLM Integration | Wire the retriever, context builder, prompt templates, and Amazon Bedrock (Claude) together into a complete RAG chain |
| 4 | [phase-04-fastapi-backend.md](phase-04-fastapi-backend.md) | FastAPI Backend | Expose document ingestion, query answering, summarization, and comparison as REST API endpoints |
| 5 | [phase-05-react-frontend.md](phase-05-react-frontend.md) | React / TypeScript Frontend | Build the chat UI, document upload, citation display, and conversation history components |
| 6 | [phase-06-storage-database.md](phase-06-storage-database.md) | Storage — S3 & PostgreSQL | Integrate Amazon S3 for document storage and PostgreSQL for metadata, conversation history, and audit logs |
| 7 | [phase-07-testing-evaluation.md](phase-07-testing-evaluation.md) | Testing & RAG Evaluation | Unit tests, integration tests, and RAG quality evaluation (faithfulness, relevance, context recall) |
| 8 | [phase-08-docker-deployment.md](phase-08-docker-deployment.md) | Docker & Cloud Deployment | Containerise with Docker, deploy to Amazon ECS, set up GitHub Actions CI/CD, and configure CloudWatch monitoring |

---

## Sequential Dependency Map

```
Phase 0 (Setup)
    └── Phase 1 (Document Processing)
            └── Phase 2 (Embeddings + Vector DB)
                    └── Phase 3 (RAG Core)
                            └── Phase 4 (FastAPI Backend)
                            └── Phase 5 (React Frontend)  ← depends on Phase 4 API
                            └── Phase 6 (S3 + PostgreSQL) ← feeds Phase 4
                                    └── Phase 7 (Testing) ← requires Phases 1–6
                                            └── Phase 8 (Deployment)
```

---

## Technology Quick Reference

| Layer | Technology |
|-------|-----------|
| LLM | Anthropic Claude 3.5 Sonnet via Amazon Bedrock |
| Embeddings | Amazon Titan Text Embeddings V2 via Amazon Bedrock |
| Vector DB | Amazon OpenSearch Serverless (all environments) |
| RAG orchestration | LangChain + LangChain-Community + LangChain-AWS |
| Backend | FastAPI + Uvicorn + Pydantic v2 |
| Frontend | React 18 + TypeScript + Tailwind CSS |
| Frontend CDN | Amazon CloudFront + Amazon S3 (static hosting) |
| Document storage | Amazon S3 |
| Metadata / history | Amazon RDS PostgreSQL (via SQLAlchemy + asyncpg) |
| Async ingestion queue | Amazon SQS |
| Secret management | AWS Secrets Manager |
| Non-secret config | AWS Systems Manager Parameter Store |
| Authentication | Amazon Cognito (User Pool + App Client) |
| Containerisation | Docker + Docker Compose |
| Container registry | Amazon ECR |
| Container orchestration | Amazon ECS (Fargate) |
| Load balancing | Application Load Balancer (ALB) |
| DNS | Amazon Route 53 |
| TLS certificates | AWS Certificate Manager (ACM) |
| Web Application Firewall | AWS WAF |
| CI/CD | GitHub Actions |
| Infrastructure as Code | AWS CDK (Python) |
| Monitoring & logging | Amazon CloudWatch (Logs, Metrics, Alarms, Dashboard) |
| Distributed tracing | AWS X-Ray |
| Local AWS simulation | LocalStack (for unit/integration tests) |

---

## How to Use This Plan

1. Work through phases **sequentially** — each phase produces artifacts consumed by the next.
2. Each phase file contains:
   - **Goal** — what will exist when the phase is complete.
   - **Prerequisites** — what must be done first.
   - **Folder & file structure** — exact paths to create.
   - **Step-by-step instructions** — numbered, granular steps.
   - **Code generation prompt** — a self-contained prompt ready to paste into Claude Code or another AI coding assistant.
   - **Acceptance criteria** — how to verify the phase is complete before moving on.
3. The code generation prompts are designed to be used **one phase at a time**. Do not combine phases.
