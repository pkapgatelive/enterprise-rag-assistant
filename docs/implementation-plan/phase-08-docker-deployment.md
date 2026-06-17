# Phase 8 — Docker & Cloud Deployment

## Goal

Package the application into Docker containers, deploy the backend to Amazon ECS (Fargate), serve the frontend as a static site via Amazon S3 + CloudFront, automate deployments with GitHub Actions CI/CD, and configure CloudWatch for monitoring and alerting.

---

## Prerequisites

- Phases 0–7 complete. All tests pass.
- AWS CLI v2 configured with AdministratorAccess (or equivalent scoped permissions).
- AWS CDK v2 installed: `npm install -g aws-cdk`
- CDK bootstrapped in the target account/region: `cdk bootstrap aws://ACCOUNT_ID/us-east-1`
- Docker Desktop running locally.
- GitHub repository set up with the following secrets configured:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_REGION`
  - `AWS_ACCOUNT_ID`
  - `ECR_REGISTRY` (format: `<account_id>.dkr.ecr.<region>.amazonaws.com`)

---

## What This Phase Produces

```
enterprise-rag-assistant/
├── backend/
│   ├── Dockerfile
│   └── app/workers/
│       └── ingestion_worker.py     # SQS polling worker (ECS separate task)
├── frontend/
│   └── Dockerfile
├── infra/
│   ├── docker-compose.yml          # Full local stack
│   ├── docker-compose.dev.yml      # LocalStack + Postgres
│   ├── nginx.conf                  # Nginx reverse proxy config
│   └── cdk/
│       ├── app.py                  # CDK entry point
│       ├── requirements.txt        # aws-cdk-lib, constructs
│       └── stacks/
│           ├── __init__.py
│           ├── network_stack.py    # VPC, subnets, security groups
│           ├── data_stack.py       # RDS, OpenSearch, S3, SQS, Secrets Manager
│           ├── compute_stack.py    # ECR, ECS cluster, ALB, ECS services (API + worker)
│           ├── auth_stack.py       # Amazon Cognito User Pool + App Client
│           └── frontend_stack.py  # S3 static bucket, CloudFront, Route 53, ACM, WAF
└── .github/
    └── workflows/
        ├── ci.yml                  # Test on every PR
        └── deploy.yml              # Build images + cdk deploy on push to main
```

---

## Step-by-Step Instructions

### Step 1 — Create `backend/Dockerfile`

Multi-stage build to keep the final image small:

```dockerfile
# ── Stage 1: Build ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

COPY --from=builder /install /usr/local
COPY backend/app ./app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health').raise_for_status()"

CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--log-config", "/app/log_config.json"]
```

Create `backend/log_config.json` to configure uvicorn's access logging in JSON format.

### Step 2 — Create `frontend/Dockerfile`

Two-stage: build the Vite bundle then serve it with Nginx:

```dockerfile
# ── Stage 1: Build ─────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ .
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# ── Stage 2: Serve ─────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

COPY --from=builder /app/dist /usr/share/nginx/html
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s \
    CMD wget -qO- http://localhost/health || exit 1
```

### Step 3 — Create `infra/nginx.conf`

Nginx config that:
1. Serves static React files.
2. Proxies `/api/` requests to the backend service.
3. Handles SPA routing (all unknown paths → `index.html`).

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }

    location /health {
        return 200 'ok';
        add_header Content-Type text/plain;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

### Step 4 — Create `infra/docker-compose.yml` (full local stack)

```yaml
version: "3.9"

services:
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    ports:
      - "8000:8000"
    environment:
      - APP_ENV=development
      - DATABASE_URL=postgresql+asyncpg://eka_user:eka_pass@postgres:5432/eka_db
      - OPENSEARCH_ENDPOINT=${OPENSEARCH_ENDPOINT}
      - OPENSEARCH_INDEX_NAME=eka-knowledge-base
      - LOCALSTACK_ENDPOINT=http://localstack:4566
      - SQS_INGESTION_QUEUE_URL=http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/eka-ingestion-queue
      - USE_SECRETS_MANAGER=false
      - AWS_REGION=${AWS_REGION:-us-east-1}
      - BEDROCK_LLM_MODEL_ID=${BEDROCK_LLM_MODEL_ID}
      - BEDROCK_EMBEDDING_MODEL_ID=${BEDROCK_EMBEDDING_MODEL_ID}
      - S3_BUCKET_NAME=eka-documents-dev
    depends_on:
      postgres:
        condition: service_healthy
      localstack:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:8000/api/v1/health').raise_for_status()"]
      interval: 30s
      timeout: 10s
      retries: 3

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
      args:
        VITE_API_BASE_URL: /api/v1
    ports:
      - "80:80"
    depends_on:
      - backend

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: eka_user
      POSTGRES_PASSWORD: eka_pass
      POSTGRES_DB: eka_db
    volumes:
      - eka_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U eka_user -d eka_db"]
      interval: 10s
      timeout: 5s
      retries: 5

  localstack:
    image: localstack/localstack:3.7
    ports:
      - "4566:4566"
    environment:
      - SERVICES=s3,sqs,secretsmanager,opensearch
      - DEFAULT_REGION=us-east-1
    volumes:
      - localstack_data:/var/lib/localstack
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4566/_localstack/health"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  eka_pgdata:
  localstack_data:
```

### Step 5 — Create GitHub Actions CI workflow

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  test-backend:
    name: Backend Tests
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: eka_user
          POSTGRES_PASSWORD: eka_pass
          POSTGRES_DB: eka_db
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
          cache-dependency-path: backend/requirements-dev.txt

      - name: Install dependencies
        run: pip install -r backend/requirements-dev.txt

      - name: Run linting
        run: ruff check backend/app backend/tests

      - name: Run type checking
        run: mypy backend/app --ignore-missing-imports

      - name: Run tests
        env:
          DATABASE_URL: postgresql+asyncpg://eka_user:eka_pass@localhost:5432/eka_db
          AWS_REGION: us-east-1
          OPENSEARCH_ENDPOINT: http://localhost:4566
          OPENSEARCH_INDEX_NAME: eka-test
          USE_SECRETS_MANAGER: "false"
          SQS_INGESTION_QUEUE_URL: http://localhost:4566/000000000000/eka-ingestion-queue
        run: |
          pytest backend/tests/unit/ backend/tests/integration/ \
            --cov=backend/app \
            --cov-report=xml \
            --cov-fail-under=70 \
            -v

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml

  test-frontend:
    name: Frontend Build Check
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        run: cd frontend && npm ci

      - name: Type check
        run: cd frontend && npx tsc --noEmit

      - name: Build
        run: cd frontend && npm run build
```

### Step 6 — Create GitHub Actions Deploy workflow

`.github/workflows/deploy.yml`:

```yaml
name: Deploy

on:
  push:
    branches: [main]

env:
  AWS_REGION: ${{ secrets.AWS_REGION }}
  ECR_REGISTRY: ${{ secrets.ECR_REGISTRY }}
  ECS_CLUSTER: eka-cluster
  ECS_SERVICE: eka-backend-service
  BACKEND_IMAGE_NAME: eka-backend
  FRONTEND_IMAGE_NAME: eka-frontend

jobs:
  deploy:
    name: Build and Deploy
    runs-on: ubuntu-latest
    needs: []   # runs after CI passes (configure branch protection to enforce)

    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push backend image
        id: build-backend
        run: |
          IMAGE_TAG="${{ env.ECR_REGISTRY }}/${{ env.BACKEND_IMAGE_NAME }}:${{ github.sha }}"
          docker build -f backend/Dockerfile -t "$IMAGE_TAG" .
          docker push "$IMAGE_TAG"
          echo "image=$IMAGE_TAG" >> "$GITHUB_OUTPUT"

      - name: Build and push frontend image
        id: build-frontend
        run: |
          IMAGE_TAG="${{ env.ECR_REGISTRY }}/${{ env.FRONTEND_IMAGE_NAME }}:${{ github.sha }}"
          docker build -f frontend/Dockerfile \
            --build-arg VITE_API_BASE_URL=/api/v1 \
            -t "$IMAGE_TAG" .
          docker push "$IMAGE_TAG"

      - name: Build and deploy with CDK
        run: |
          pip install -r infra/cdk/requirements.txt
          cd infra/cdk
          cdk deploy --all --require-approval never \
            -c backendImageTag=${{ github.sha }} \
            -c workerImageTag=${{ github.sha }}

      - name: Invalidate CloudFront cache
        run: |
          aws cloudfront create-invalidation \
            --distribution-id ${{ secrets.CLOUDFRONT_DISTRIBUTION_ID }} \
            --paths "/*"
```

### Step 7 — AWS CDK Infrastructure (`infra/cdk/`)

The CDK app replaces all manual CloudFormation JSON. It is the single source of truth for all cloud resources. Install CDK dependencies:

```bash
cd infra/cdk
pip install aws-cdk-lib constructs
```

#### `infra/cdk/stacks/network_stack.py`

```python
from aws_cdk import Stack, aws_ec2 as ec2
from constructs import Construct

class NetworkStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)
        self.vpc = ec2.Vpc(self, "EkaVpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="Public",  subnet_type=ec2.SubnetType.PUBLIC,  cidr_mask=24),
                ec2.SubnetConfiguration(name="Private", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=24),
                ec2.SubnetConfiguration(name="Isolated",subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=28),
            ],
        )
        self.alb_sg   = ec2.SecurityGroup(self, "AlbSg",   vpc=self.vpc, description="ALB")
        self.ecs_sg   = ec2.SecurityGroup(self, "EcsSg",   vpc=self.vpc, description="ECS tasks")
        self.rds_sg   = ec2.SecurityGroup(self, "RdsSg",   vpc=self.vpc, description="RDS")
        self.alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443))
        self.ecs_sg.add_ingress_rule(self.alb_sg, ec2.Port.tcp(8000))
        self.rds_sg.add_ingress_rule(self.ecs_sg, ec2.Port.tcp(5432))
```

#### `infra/cdk/stacks/data_stack.py`

Provisions: RDS Aurora Serverless v2, S3 buckets, SQS queue + DLQ, Secrets Manager secrets.

Key CDK constructs:
- `rds.DatabaseCluster` with `ServerlessV2ClusterInstanceProps`
- `s3.Bucket` with `BlockPublicAccess.BLOCK_ALL`, KMS encryption, versioning enabled
- `sqs.Queue` with `DeadLetterQueue` (maxReceiveCount=3)
- `secretsmanager.Secret` for RDS credentials (auto-rotation enabled)

#### `infra/cdk/stacks/auth_stack.py`

```python
from aws_cdk import Stack, aws_cognito as cognito
from constructs import Construct

class AuthStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)
        self.user_pool = cognito.UserPool(self, "EkaUserPool",
            user_pool_name="eka-users",
            self_sign_up_enabled=False,      # admin creates users (enterprise)
            sign_in_aliases=cognito.SignInAliases(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
        )
        self.app_client = self.user_pool.add_client("EkaWebClient",
            auth_flows=cognito.AuthFlow(user_srp=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
                callback_urls=["https://YOUR_CLOUDFRONT_DOMAIN/callback"],
                logout_urls=["https://YOUR_CLOUDFRONT_DOMAIN/logout"],
            ),
            prevent_user_existence_errors=True,
        )
```

#### `infra/cdk/stacks/frontend_stack.py`

Provisions: S3 static hosting bucket, CloudFront distribution with OAC, ACM certificate, Route 53 alias record, and AWS WAF WebACL.

Key constructs:
- `s3.Bucket` for frontend static files (private, OAC access only)
- `acm.Certificate` with DNS validation in Route 53 (`CertificateValidation.from_dns`)
- `cloudfront.Distribution` with `S3BucketOrigin.with_origin_access_control`, ALB origin for `/api/*`
- `wafv2.CfnWebACL` with managed rules: `AWSManagedRulesCommonRuleSet`, `AWSManagedRulesSQLiRuleSet`, `AWSManagedRulesKnownBadInputsRuleSet`; rate limit rule: 2000 req/5min per IP
- `route53.ARecord` pointing the apex domain to the CloudFront distribution

#### `infra/cdk/stacks/compute_stack.py`

Provisions: ECR repositories (with lifecycle policies), ECS Fargate cluster, ECS services (API + ingestion worker), Application Load Balancer, IAM task role.

IAM task role permissions:
```python
# Bedrock
task_role.add_to_policy(iam.PolicyStatement(
    actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
    resources=[
        f"arn:aws:bedrock:{region}::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0",
        f"arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0",
    ]
))
# S3
task_role.add_to_policy(iam.PolicyStatement(
    actions=["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket"],
    resources=[bucket.bucket_arn, f"{bucket.bucket_arn}/*"]
))
# SQS
task_role.add_to_policy(iam.PolicyStatement(
    actions=["sqs:SendMessage","sqs:ReceiveMessage","sqs:DeleteMessage","sqs:GetQueueAttributes"],
    resources=[queue.queue_arn]
))
# OpenSearch Serverless
task_role.add_to_policy(iam.PolicyStatement(
    actions=["aoss:APIAccessAll"],
    resources=[f"arn:aws:aoss:{region}:{account}:collection/*"]
))
# Secrets Manager
task_role.add_to_policy(iam.PolicyStatement(
    actions=["secretsmanager:GetSecretValue"],
    resources=[rds_secret.secret_arn, opensearch_secret.secret_arn]
))
# X-Ray
task_role.add_to_policy(iam.PolicyStatement(
    actions=["xray:PutTraceSegments","xray:PutTelemetryRecords"],
    resources=["*"]
))
```

### Step 8 — Create SQS Ingestion Worker (`backend/app/workers/ingestion_worker.py`)

A standalone Python process that polls the SQS queue and processes documents:

```python
"""
EKA Ingestion Worker — deployed as a separate ECS Fargate task.
Polls the SQS ingestion queue, processes each document, and updates RDS.
Run: python -m app.workers.ingestion_worker
"""
import json
import boto3
import asyncio
from app.config import settings
from app.services.s3_service import S3Service
from app.core.document_processor.pipeline import process_document
from app.core.vector_store.indexer import index_documents
from app.db.base import AsyncSessionLocal
from app.db.repositories.document_repo import DocumentRepository
from app.db.models.document import DocumentStatus
from app.utils.logger import logger
import tempfile, os


sqs = boto3.client("sqs", region_name=settings.aws_region)
s3_service = S3Service()


async def process_message(body: dict) -> None:
    document_id = body["document_id"]
    s3_key = body["s3_key"]
    file_name = body["file_name"]
    ext = os.path.splitext(file_name)[1].lower()

    async with AsyncSessionLocal() as db:
        repo = DocumentRepository(db)
        try:
            file_bytes = s3_service.download_file(s3_key)
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            chunks = process_document(tmp_path)
            for chunk in chunks:
                chunk.metadata["document_id"] = document_id

            result = index_documents(chunks)
            await repo.update_status(document_id, DocumentStatus.indexed, chunk_count=result["indexed"])
            logger.info("ingestion_complete", document_id=document_id, chunks=result["indexed"])
        except Exception as exc:
            await repo.update_status(document_id, DocumentStatus.failed, error_message=str(exc))
            logger.error("ingestion_failed", document_id=document_id, error=str(exc))
        finally:
            if "tmp_path" in dir() and os.path.exists(tmp_path):
                os.remove(tmp_path)


def poll_forever() -> None:
    logger.info("worker_started", queue=settings.sqs_ingestion_queue_url)
    while True:
        response = sqs.receive_message(
            QueueUrl=settings.sqs_ingestion_queue_url,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=20,   # long polling
            VisibilityTimeout=300,
        )
        for msg in response.get("Messages", []):
            body = json.loads(msg["Body"])
            asyncio.run(process_message(body))
            sqs.delete_message(
                QueueUrl=settings.sqs_ingestion_queue_url,
                ReceiptHandle=msg["ReceiptHandle"],
            )


if __name__ == "__main__":
    poll_forever()
```

### Step 9 — Configure AWS X-Ray Tracing

Add X-Ray middleware to FastAPI so every request is traced end-to-end across the API → Bedrock → OpenSearch → RDS calls:

```python
# In backend/app/main.py startup
from aws_xray_sdk.core import xray_recorder, patch_all
from aws_xray_sdk.ext.fastapi.middleware import XRayMiddleware
from app.config import settings

if settings.xray_enabled:
    xray_recorder.configure(service="eka-backend")
    patch_all()   # auto-patches boto3, requests, sqlalchemy
    app.add_middleware(XRayMiddleware, recorder=xray_recorder)
```

### Step 10 — Configure CloudWatch Monitoring

All alarms and the dashboard are defined in `infra/cdk/stacks/compute_stack.py` as CDK constructs. No manual CLI steps needed after `cdk deploy`.

| Alarm | Metric | Threshold |
|-------|--------|-----------|
| High CPU | `ECS/CPUUtilization` | > 80% for 5 min |
| High Memory | `ECS/MemoryUtilization` | > 85% for 5 min |
| 5xx Errors | `ApplicationELB/HTTPCode_Target_5XX_Count` | > 10 in 5 min |
| High P99 Latency | `ApplicationELB/TargetResponseTime` | > 5 seconds |
| SQS DLQ Messages | `SQS/NumberOfMessagesSent` on DLQ | >= 1 |
| RDS CPU | `RDS/CPUUtilization` | > 80% for 10 min |

CloudWatch dashboard `EKA-Production`: request rate, 5xx rate, P99 latency, ECS CPU/memory, SQS queue depth, RDS connections.

CloudWatch Logs Insights query saved for RAG latency analysis:
```
fields @timestamp, @message
| filter @message like "chain_invoked"
| stats avg(duration_ms) as avg_latency, p99(duration_ms) as p99_latency by bin(5m)
```

---

## Code Generation Prompt

```
You are implementing Phase 8 of the Enterprise Knowledge Assistant (EKA) project.
Phases 0-7 are complete. All tests pass locally. This project uses the COMPLETE
AWS ecosystem — no manual CloudFormation JSON. All infra is AWS CDK (Python).

Task: Create all Docker, CI/CD, CDK infrastructure, and AWS service configuration files.

Files to create:

1. `backend/Dockerfile`
   - Multi-stage: python:3.11-slim builder → python:3.11-slim runtime
   - Builder: pip install --prefix=/install -r requirements.txt (no faiss-cpu)
   - Runtime: non-root user "appuser", EXPOSE 8000, HEALTHCHECK via httpx
   - CMD: uvicorn app.main:app --workers 2 --host 0.0.0.0

2. `frontend/Dockerfile`
   - Multi-stage: node:20-alpine builder → nginx:1.27-alpine runtime
   - Builder: npm ci, npm run build with VITE_API_BASE_URL=/api/v1 build arg
   - Runtime: copy dist + nginx.conf; no /api/ proxy needed (CloudFront handles it)

3. `infra/nginx.conf`
   - Serve static files with SPA fallback (/index.html)
   - /health → 200 ok
   - No API proxy (CloudFront routes /api/* to ALB directly)

4. `infra/docker-compose.yml` (full local stack — does NOT use real AWS)
   - Services: backend, frontend (nginx), postgres, localstack
   - backend: env vars pointing to localstack endpoint for S3/SQS/Secrets
   - Named volumes: eka_pgdata, localstack_data

5. `backend/app/workers/ingestion_worker.py`
   - Polls SQS queue with long polling (WaitTimeSeconds=20)
   - For each message: download from S3, process_document, index_documents, update RDS
   - Deletes message on success; leaves it for DLQ retry on failure
   - Runs as separate ECS Fargate task (CMD: python -m app.workers.ingestion_worker)

6. Update `backend/app/main.py`
   - Add X-Ray middleware when settings.xray_enabled=True
   - xray_recorder.configure(service="eka-backend"), patch_all(), XRayMiddleware

7. `infra/cdk/requirements.txt`
   - aws-cdk-lib>=2.160.0, constructs>=10.0.0

8. `infra/cdk/app.py`
   - CDK App instantiating 5 stacks in order: Network → Data → Auth → Compute → Frontend
   - Pass VPC/security groups between stacks via stack properties

9. `infra/cdk/stacks/network_stack.py`
   - VPC with 2 AZs, 1 NAT gateway
   - Public, Private (with egress), Isolated subnets
   - Security groups: ALB (443 inbound), ECS (8000 from ALB), RDS (5432 from ECS)

10. `infra/cdk/stacks/data_stack.py`
    - Aurora Serverless v2 (PostgreSQL 16) in isolated subnets; credentials in Secrets Manager with rotation
    - S3 bucket for documents: block public access, KMS encryption, versioning, lifecycle rules
    - S3 bucket for frontend static files: block public access, OAC only
    - SQS ingestion queue with DLQ (maxReceiveCount=3, visibility 300s)
    - Secrets Manager secrets for RDS, OpenSearch endpoint

11. `infra/cdk/stacks/auth_stack.py`
    - Cognito UserPool: email sign-in, no self-signup, MFA optional (TOTP), 12-char password
    - App client with authorization_code_grant flow
    - Output: user_pool_id, app_client_id, jwks_url

12. `infra/cdk/stacks/compute_stack.py`
    - ECR repos: eka-backend, eka-worker with lifecycle policy (keep last 10 images)
    - ECS Fargate cluster with Container Insights enabled
    - API service: FargateService 1 vCPU/2GB, desired=2, health check /api/v1/health
    - Worker service: FargateService 0.5 vCPU/1GB, desired=1, CMD override for worker
    - ALB: HTTPS listener (ACM cert), forward to API target group
    - IAM task role: bedrock InvokeModel+Stream, s3 CRUD, sqs Send+Receive+Delete, aoss APIAccessAll,
      secretsmanager GetSecretValue, xray PutTraceSegments
    - CloudWatch alarms: CPU, memory, 5xx, latency, SQS DLQ, RDS CPU
    - CloudWatch dashboard: EKA-Production

13. `infra/cdk/stacks/frontend_stack.py`
    - ACM certificate (DNS validation via Route 53) for custom domain
    - CloudFront distribution:
      * Default origin: S3 with OAC
      * /api/* origin: ALB (HTTPS, cache disabled)
      * Viewer protocol: redirect HTTP→HTTPS
    - WAF WebACL attached to CloudFront:
      * AWSManagedRulesCommonRuleSet
      * AWSManagedRulesSQLiRuleSet
      * Rate limit: 2000 req/5min per IP
    - Route 53 ARecord: apex domain → CloudFront distribution

14. `.github/workflows/ci.yml`
    - Jobs: test-backend (ruff → mypy → pytest with coverage ≥70%), test-frontend (tsc + build)
    - Backend uses postgres service container; no real AWS calls (moto mocks)
    - Upload coverage to codecov

15. `.github/workflows/deploy.yml`
    - Configure AWS creds, ECR login
    - Build and push backend + worker images (same Dockerfile, different CMD)
    - Build frontend, upload to S3 frontend bucket, CloudFront invalidation
    - Run `cdk deploy --all` with image tags as context vars
    - Require CI to pass (branch protection rule)

Rules:
- All infra in AWS CDK Python — no raw CloudFormation JSON templates
- Docker images must be non-root (user "appuser")
- No faiss-cpu in any Dockerfile or requirements
- Secrets injected at runtime via ECS secrets (from Secrets Manager) — never baked into image
- CI must not make real AWS calls — use moto for all boto3 tests
- CloudFront serves both frontend (S3) and API (/api/* → ALB) from same domain
- X-Ray traces backend requests when XRAY_ENABLED=true
```

---

## Deployment Checklist (CDK handles most — run once before first deploy)

- [ ] `cdk bootstrap aws://ACCOUNT_ID/us-east-1` — one-time CDK bootstrap
- [ ] Enable Bedrock model access in console: Claude 3.5 Sonnet + Titan Embeddings V2
- [ ] Create OpenSearch Serverless collection (Phase 2 steps) and record endpoint in Secrets Manager
- [ ] Register domain in Route 53 (or transfer) before `cdk deploy frontend_stack`
- [ ] Set GitHub repository secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AWS_ACCOUNT_ID`, `ECR_REGISTRY`, `CLOUDFRONT_DISTRIBUTION_ID`
- [ ] `cdk deploy --all` — provisions VPC, RDS, S3, SQS, Cognito, ECS, ALB, CloudFront, WAF, Route 53
- [ ] Run `alembic upgrade head` against RDS once (via ECS exec or bastion)
- [ ] Verify `GET https://your-domain.com/api/v1/health` returns `{"status": "ok"}`

---

## Acceptance Criteria

- [ ] No `faiss-cpu` in either Dockerfile or in any `pip list` inside the container
- [ ] `docker compose -f infra/docker-compose.yml up` starts all services (backend, frontend, LocalStack, Postgres); app accessible at `http://localhost`
- [ ] Backend Docker image builds cleanly; container runs as non-root user
- [ ] Frontend Docker image builds cleanly; `npm run build` produces a `dist/` folder
- [ ] Push to a PR branch triggers CI; all tests pass without real AWS calls
- [ ] Push to `main` triggers deploy workflow; images pushed to ECR, `cdk deploy --all` completes
- [ ] `cdk synth` produces valid CloudFormation with no errors for all 5 stacks
- [ ] `GET https://your-domain.com/api/v1/health` returns `{"status": "ok"}` from CloudFront → ALB → ECS
- [ ] Frontend served via CloudFront; `/api/*` requests proxied to ALB by CloudFront behaviour rules
- [ ] AWS WAF blocks a simple SQLi probe (`' OR 1=1 --`) with a 403 response
- [ ] CloudWatch dashboard `EKA-Production` shows active metrics after first request
- [ ] Amazon Cognito User Pool created; a test user can authenticate and receive a JWT
- [ ] SQS ingestion worker picks up a test message and updates RDS `status=indexed`
- [ ] X-Ray service map shows traces connecting `eka-backend` → Bedrock → OpenSearch
