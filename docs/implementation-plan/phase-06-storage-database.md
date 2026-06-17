# Phase 6 — Storage: Amazon S3 & PostgreSQL

## Goal

Integrate Amazon S3 for durable original document storage and PostgreSQL for structured metadata, document registry, conversation history, and audit logs. Replace the in-memory stubs left in Phase 4 with real persistent storage, and wire the S3 upload into the document ingestion pipeline.

---

## Prerequisites

- Phases 0–5 complete.
- `boto3`, `aiobotocore`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic` installed.
- LocalStack running locally with S3, SQS, Secrets Manager enabled.
- AWS credentials configured with: S3 (`s3:*`), SQS (`sqs:*`), Secrets Manager (`secretsmanager:GetSecretValue`), RDS IAM auth (`rds-db:connect`).
- `S3_BUCKET_NAME`, `SQS_INGESTION_QUEUE_URL`, `DATABASE_URL`, and `RDS_SECRET_ARN` set in `.env`.
- **For cloud:** Amazon RDS PostgreSQL instance (or Aurora Serverless v2) provisioned and accessible from ECS VPC.

---

## What This Phase Produces

```
backend/
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_initial_schema.py
└── app/
    ├── db/
    │   ├── __init__.py
    │   ├── base.py              # SQLAlchemy async engine + Base
    │   ├── models/
    │   │   ├── __init__.py
    │   │   ├── document.py      # Document ORM model
    │   │   └── conversation.py  # Conversation + Message ORM models
    │   └── repositories/
    │       ├── __init__.py
    │       ├── document_repo.py
    │       └── conversation_repo.py
    └── services/
        ├── s3_service.py        # S3 upload, download, delete, presign
        ├── sqs_service.py       # SQS ingestion queue publisher
        └── secrets_service.py   # AWS Secrets Manager retrieval
```

---

## Step-by-Step Instructions

### Step 1 — Create `backend/app/services/secrets_service.py`

In production (`USE_SECRETS_MANAGER=true`), credentials are pulled from AWS Secrets Manager at startup rather than read from environment variables. This ensures no secrets are baked into the container image or task definition.

```python
import json
import boto3
from app.config import settings
from app.utils.logger import logger


def get_database_url() -> str:
    if not settings.use_secrets_manager:
        return settings.database_url

    client = boto3.client("secretsmanager", region_name=settings.aws_region)
    secret = json.loads(
        client.get_secret_value(SecretId=settings.rds_secret_arn)["SecretString"]
    )
    logger.info("secrets_manager_db_url_loaded", secret_id=settings.rds_secret_arn)
    return (
        f"postgresql+asyncpg://{secret['username']}:{secret['password']}"
        f"@{secret['host']}:{secret['port']}/{secret['dbname']}"
        f"?ssl=require"     # RDS requires SSL in transit
    )
```

### Step 2 — Create `backend/app/db/base.py`

Async SQLAlchemy engine. In production the DATABASE_URL comes from Secrets Manager; locally it comes from `.env`:

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.services.secrets_service import get_database_url


class Base(DeclarativeBase):
    pass


def _build_engine():
    db_url = get_database_url()
    return create_async_engine(
        db_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,      # detects stale RDS connections after failover
        pool_recycle=1800,       # recycle connections every 30 min (RDS idle timeout)
    )


engine = _build_engine()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

### Step 3 — Create Amazon RDS Instance (cloud setup)

In the cloud, use Amazon RDS PostgreSQL 16 or Aurora Serverless v2. This is infrastructure created once; it will be automated in Phase 8 via AWS CDK.

Key RDS settings for production:
- Multi-AZ enabled (automatic failover)
- Automated backups (7-day retention)
- Encryption at rest (AWS KMS)
- SSL/TLS in transit (`rds.force_ssl=1`)
- VPC private subnets (no public access)
- Security group: allow inbound 5432 only from ECS task security group

Store the credentials in Secrets Manager (done once):

```bash
aws secretsmanager create-secret \
  --name eka/rds-credentials \
  --description "EKA RDS PostgreSQL credentials" \
  --secret-string '{
    "username": "eka_admin",
    "password": "REPLACE_WITH_STRONG_PASSWORD",
    "host": "eka-db.cluster-xxxx.us-east-1.rds.amazonaws.com",
    "port": 5432,
    "dbname": "eka_db"
  }'
```

Then set `RDS_SECRET_ARN` and `USE_SECRETS_MANAGER=true` in the ECS task environment.

### Step 2 — Create ORM models

#### `backend/app/db/models/document.py`

```python
from sqlalchemy import String, Integer, DateTime, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
import enum


class DocumentStatus(enum.Enum):
    processing = "processing"
    indexed = "indexed"
    failed = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus), default=DocumentStatus.processing
    )
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=True)
    uploaded_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    indexed_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str] = mapped_column(String(2048), nullable=True)
```

#### `backend/app/db/models/conversation.py`

```python
from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[str] = mapped_column(Text, nullable=True)  # JSON array
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
```

### Step 3 — Create repositories

#### `backend/app/db/repositories/document_repo.py`

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.db.models.document import Document, DocumentStatus
from datetime import datetime, UTC


class DocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Document:
        doc = Document(**kwargs)
        self.db.add(doc)
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def get_by_id(self, doc_id: str) -> Document | None:
        result = await self.db.execute(select(Document).where(Document.id == doc_id))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Document]:
        result = await self.db.execute(select(Document).order_by(Document.uploaded_at.desc()))
        return list(result.scalars().all())

    async def update_status(
        self,
        doc_id: str,
        status: DocumentStatus,
        chunk_count: int | None = None,
        error_message: str | None = None,
    ) -> None:
        values: dict = {"status": status}
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        if error_message is not None:
            values["error_message"] = error_message
        if status == DocumentStatus.indexed:
            values["indexed_at"] = datetime.now(UTC)
        await self.db.execute(update(Document).where(Document.id == doc_id).values(**values))
        await self.db.commit()

    async def delete(self, doc_id: str) -> bool:
        doc = await self.get_by_id(doc_id)
        if not doc:
            return False
        await self.db.delete(doc)
        await self.db.commit()
        return True
```

#### `backend/app/db/repositories/conversation_repo.py`

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.db.models.conversation import Conversation, Message
import uuid


class ConversationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create(self, session_id: str) -> Conversation:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == session_id)
            .options(selectinload(Conversation.messages))
        )
        conversation = result.scalar_one_or_none()
        if not conversation:
            conversation = Conversation(id=session_id)
            self.db.add(conversation)
            await self.db.commit()
        return conversation

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        citations_json: str | None = None,
    ) -> Message:
        msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=session_id,
            role=role,
            content=content,
            citations_json=citations_json,
        )
        self.db.add(msg)
        await self.db.commit()
        return msg

    async def get_history_text(self, session_id: str, limit: int = 10) -> str:
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(reversed(result.scalars().all()))
        return "\n".join(f"{m.role.upper()}: {m.content}" for m in messages)
```

### Step 4 — Create `backend/app/services/s3_service.py`

```python
import boto3
from botocore.exceptions import ClientError
from app.config import settings
from app.utils.logger import logger


class S3Service:
    def __init__(self):
        self._client = boto3.client("s3", region_name=settings.aws_region)
        self._bucket = settings.s3_bucket_name
        self._prefix = settings.s3_prefix

    def _key(self, document_id: str, file_name: str) -> str:
        return f"{self._prefix}{document_id}/{file_name}"

    def upload_file(self, file_bytes: bytes, document_id: str, file_name: str) -> str:
        key = self._key(document_id, file_name)
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=file_bytes,
        )
        logger.info("s3_upload_success", key=key)
        return key

    def download_file(self, s3_key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=s3_key)
        return response["Body"].read()

    def delete_file(self, s3_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=s3_key)
        logger.info("s3_delete_success", key=s3_key)

    def generate_presigned_url(self, s3_key: str, expiry_seconds: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": s3_key},
            ExpiresIn=expiry_seconds,
        )
```

### Step 5 — Create `backend/app/services/sqs_service.py`

Replace FastAPI `BackgroundTasks` with Amazon SQS for reliable async document ingestion. SQS decouples the HTTP upload from the ingestion worker, enabling retry, dead-letter queuing, and horizontal scaling.

```python
import json
import boto3
from app.config import settings
from app.utils.logger import logger


class SQSIngestionService:
    def __init__(self):
        kwargs = {"region_name": settings.aws_region}
        if settings.localstack_endpoint:
            kwargs["endpoint_url"] = settings.localstack_endpoint
        self._client = boto3.client("sqs", **kwargs)
        self._queue_url = settings.sqs_ingestion_queue_url

    def enqueue(self, document_id: str, s3_key: str, file_name: str) -> str:
        message = {
            "document_id": document_id,
            "s3_key": s3_key,
            "file_name": file_name,
        }
        response = self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(message),
            MessageAttributes={
                "document_id": {"StringValue": document_id, "DataType": "String"},
            },
        )
        logger.info("sqs_message_sent", document_id=document_id, message_id=response["MessageId"])
        return response["MessageId"]
```

> **Worker note**: A separate ECS task (or Lambda trigger on SQS) polls the queue, calls
> `process_document()` → `index_documents()`, and updates the DB status. The worker code
> lives in `backend/app/workers/ingestion_worker.py` (scaffolded in Phase 8).

### Step 6 — Set up Alembic

Initialise Alembic and configure the async env:

```bash
cd backend
alembic init alembic
```

Edit `alembic/env.py` to use the async engine and import all ORM models:

```python
from app.db.base import Base
from app.db.models import document, conversation  # noqa: F401 — register models

target_metadata = Base.metadata
```

Create the initial migration:

```bash
alembic revision --autogenerate -m "initial_schema"
alembic upgrade head
```

### Step 7 — Update the upload route (Phase 4 enhancement)

Enhance `POST /documents/upload` in `documents.py` to use the full AWS pipeline:

1. Upload file bytes to **Amazon S3** (`S3Service.upload_file`).
2. Save document record to **Amazon RDS** via `DocumentRepository` with `status=processing`.
3. Publish a message to **Amazon SQS** (`SQSIngestionService.enqueue`) with `document_id`, `s3_key`, `file_name`.
4. Return `202 Accepted` immediately — no blocking background task in the HTTP process.

The ECS ingestion worker (Phase 8) receives the SQS message and handles steps 5–7:

5. Download file from S3.
6. Call `process_document()` → `index_documents()`.
7. Update RDS status to `indexed` (or `failed`) with `chunk_count`.

Update `GET /documents/` to query `DocumentRepository.list_all()` from RDS.

### Step 8 — Update the query route (Phase 4 enhancement)

Enhance `POST /ask` to:
1. Save user message to `ConversationRepository` (RDS).
2. Fetch conversation history from RDS via `get_history_text()`.
3. Pass history to `answer_question()`.
4. Save assistant response + citations (serialised as JSON) to `ConversationRepository`.

### Step 9 — Write database tests

`backend/tests/integration/test_db.py`:

- Use in-memory SQLite (`aiosqlite`) — mirrors RDS schema.
- Test `DocumentRepository.create` and `get_by_id`.
- Test `update_status` transitions (processing → indexed, processing → failed).
- Test `ConversationRepository.add_message` and `get_history_text`.

`backend/tests/unit/test_sqs_service.py`:

- Mock `boto3.client("sqs")` using `moto[sqs]`.
- Create an SQS queue in the mock, set `SQS_INGESTION_QUEUE_URL`.
- Test `enqueue()` sends a message with the correct JSON body and message attributes.

`backend/tests/unit/test_secrets_service.py`:

- Mock `boto3.client("secretsmanager")` using `moto[secretsmanager]`.
- Create a secret with the expected ARN.
- Test `get_database_url()` returns a correctly assembled `postgresql+asyncpg://...?ssl=require` string.
- Test `get_database_url()` returns `settings.database_url` when `USE_SECRETS_MANAGER=false`.

---

## Code Generation Prompt

```
You are implementing Phase 6 of the Enterprise Knowledge Assistant (EKA) project.
Phases 0-5 are complete. The FastAPI routes are working with in-memory stubs.
Replace them with real AWS storage: Amazon S3, Amazon SQS, Amazon RDS (PostgreSQL),
and AWS Secrets Manager.

Files to create:

A) `backend/app/services/secrets_service.py`
   - `get_database_url() -> str`
   - When USE_SECRETS_MANAGER=false: return settings.database_url directly
   - When USE_SECRETS_MANAGER=true: call boto3 secretsmanager.get_secret_value(SecretId=settings.rds_secret_arn),
     parse JSON, build `postgresql+asyncpg://user:pass@host:port/db?ssl=require`
   - Log successful secret retrieval with structlog (do NOT log the secret value)

B) `backend/app/db/base.py`
   - Call `get_database_url()` to get the URL (supports Secrets Manager)
   - `create_async_engine` with pool_pre_ping=True, pool_recycle=1800, pool_size=10
   - `AsyncSessionLocal = async_sessionmaker(...)`
   - `get_db()` async generator yielding AsyncSession
   - `Base = DeclarativeBase()`

C) `backend/app/db/models/document.py`
   - ORM class `Document(Base)`:
     id (str PK), file_name, file_type, file_size_bytes, chunk_count (default 0),
     status (Enum: processing/indexed/failed), s3_key, uploaded_at (server_default now()),
     indexed_at (nullable), error_message (nullable, str 2048)

D) `backend/app/db/models/conversation.py`
   - ORM class `Conversation(Base)`: id, created_at (server_default), messages (relationship)
   - ORM class `Message(Base)`: id, conversation_id (FK cascade delete), role, content (Text),
     citations_json (Text nullable), created_at (server_default)

E) `backend/app/db/repositories/document_repo.py`
   - `DocumentRepository(db: AsyncSession)`:
     create(**kwargs) → Document, get_by_id(id) → Document | None,
     list_all() → list[Document], update_status(id, status, chunk_count=None, error_message=None),
     delete(id) → bool

F) `backend/app/db/repositories/conversation_repo.py`
   - `ConversationRepository(db: AsyncSession)`:
     get_or_create(session_id), add_message(session_id, role, content, citations_json),
     get_history_text(session_id, limit=10) → str

G) `backend/app/services/s3_service.py`
   - `S3Service` with endpoint_url=settings.localstack_endpoint if set (LocalStack support)
   - Methods: upload_file(bytes, document_id, file_name) → s3_key,
     download_file(s3_key) → bytes, delete_file(s3_key), generate_presigned_url(s3_key, expiry=3600)

H) `backend/app/services/sqs_service.py`
   - `SQSIngestionService` with endpoint_url=settings.localstack_endpoint if set
   - `enqueue(document_id, s3_key, file_name) -> str` (returns message_id)
   - Message body: JSON with document_id, s3_key, file_name
   - Log message_id with structlog

I) `alembic/env.py` (update)
   - Import all ORM models to register metadata
   - Use asyncio event loop with `run_sync` for async engine

J) Update `backend/app/api/routes/documents.py`
   - Upload flow: S3 upload → create RDS record (processing) → SQS enqueue → return 202
   - No blocking background task in the API process
   - `GET /`: DocumentRepository.list_all() from RDS
   - `DELETE /{id}`: S3 delete + RDS delete

K) Update `backend/app/api/routes/query.py`
   - `POST /ask`: ConversationRepository.add_message (user), get_history_text,
     answer_question(history), ConversationRepository.add_message (assistant + citations JSON)

L) `backend/tests/integration/test_db.py`
   - In-memory SQLite (aiosqlite) — not real RDS
   - Test DocumentRepository: create, get_by_id, list_all, update_status, delete
   - Test ConversationRepository: add 3 messages, verify get_history_text order and format

M) `backend/tests/unit/test_sqs_service.py`
   - Use moto SQS mock; create queue; test enqueue sends correct JSON body

N) `backend/tests/unit/test_secrets_service.py`
   - Use moto secretsmanager mock; store secret; test get_database_url builds correct URL
   - Test USE_SECRETS_MANAGER=false bypasses Secrets Manager

Rules:
- Always async DB access; never synchronous SQLAlchemy
- S3 upload must succeed BEFORE SQS enqueue; if S3 fails, do not enqueue, return 500
- DB status must always be set to indexed or failed — no indefinite processing state
- All boto3 clients check settings.localstack_endpoint for non-empty string to support LocalStack
- Never log credential values or secret contents
- Use FastAPI Depends for DB session injection
```

---

## Acceptance Criteria

- [ ] `alembic upgrade head` creates all tables in local Postgres without errors
- [ ] Uploading a PDF via API: RDS record has `status=processing`, file exists in S3 (or LocalStack S3), SQS queue has 1 message
- [ ] `GET /api/v1/documents/` returns real list from RDS
- [ ] Conversation messages persist in RDS; `get_history_text` returns them in chronological order
- [ ] `DELETE /api/v1/documents/{id}` removes from both RDS and S3
- [ ] With `USE_SECRETS_MANAGER=true` and moto mock: `get_database_url()` returns correct connection string with `?ssl=require`
- [ ] `pytest backend/tests/integration/test_db.py backend/tests/unit/test_sqs_service.py backend/tests/unit/test_secrets_service.py` all pass
- [ ] No hardcoded AWS credentials or secret values anywhere in application code
