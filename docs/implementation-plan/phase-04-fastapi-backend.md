# Phase 4 — FastAPI Backend

## Goal

Expose the document processing pipeline (Phase 1), indexer (Phase 2), and RAG chains (Phase 3) as a RESTful API using FastAPI. This phase produces all API endpoints, request/response Pydantic models, dependency injection wiring, streaming support, and background task handling for long-running ingestion jobs.

---

## Prerequisites

- Phases 0–3 complete and tested.
- `fastapi`, `uvicorn`, `python-multipart`, `pydantic v2` installed.
- `backend/app/main.py` skeleton in place.

---

## What This Phase Produces

```
backend/app/
├── api/
│   ├── dependencies.py          # Shared FastAPI dependencies (vector store, LLM)
│   └── routes/
│       ├── health.py            # GET /api/v1/health
│       ├── documents.py         # POST /upload, GET /list, DELETE /{id}
│       └── query.py             # POST /ask, POST /summarise, POST /compare, POST /ask/stream
├── models/
│   ├── document.py              # Request/response models for document routes
│   └── query.py                 # Request/response models for query routes
```

---

## API Contract

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | Returns service status and version |

### Documents

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/documents/upload` | Upload one or more files; triggers async ingestion |
| GET | `/api/v1/documents/` | List all indexed documents |
| GET | `/api/v1/documents/{document_id}` | Get metadata for a single document |
| DELETE | `/api/v1/documents/{document_id}` | Remove document from index and storage |

### Query

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/query/ask` | Ask a question; returns RAGResponse JSON |
| POST | `/api/v1/query/ask/stream` | Ask a question; returns Server-Sent Events stream |
| POST | `/api/v1/query/summarise` | Summarise a document by ID |
| POST | `/api/v1/query/compare` | Compare two documents by ID |

---

## Step-by-Step Instructions

### Step 1 — Create `backend/app/models/document.py`

```python
from pydantic import BaseModel
from datetime import datetime
from enum import Enum


class DocumentStatus(str, Enum):
    processing = "processing"
    indexed = "indexed"
    failed = "failed"


class DocumentMetadata(BaseModel):
    document_id: str
    file_name: str
    file_type: str
    file_size_bytes: int
    chunk_count: int
    status: DocumentStatus
    uploaded_at: datetime


class UploadResponse(BaseModel):
    message: str
    documents: list[DocumentMetadata]


class DocumentListResponse(BaseModel):
    documents: list[DocumentMetadata]
    total: int
```

### Step 2 — Create `backend/app/models/query.py`

```python
from pydantic import BaseModel, Field
from typing import Literal
from app.core.rag.response_models import Citation


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    k: int = Field(default=5, ge=1, le=20)
    session_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    retrieved_chunks: int
    query: str
    session_id: str | None


class SummariseRequest(BaseModel):
    document_id: str
    summary_type: Literal["executive", "technical", "key_takeaways", "brief"] = "executive"


class SummariseResponse(BaseModel):
    summary: str
    document_name: str
    summary_type: str


class CompareRequest(BaseModel):
    document_id_a: str
    document_id_b: str


class CompareResponse(BaseModel):
    comparison: str
    document_a: str
    document_b: str
```

### Step 3 — Create `backend/app/api/dependencies.py`

Provide shared singletons via FastAPI's dependency injection:

```python
from functools import lru_cache
from app.core.vector_store.factory import get_vector_store
from app.core.vector_store.base_store import BaseVectorStore


@lru_cache(maxsize=1)
def get_vector_store_dep() -> BaseVectorStore:
    return get_vector_store()
```

### Step 4 — Create `backend/app/api/routes/documents.py`

Key implementation notes:

- **Upload endpoint**: Accept `UploadFile` list via `multipart/form-data`. Validate MIME types. Save file to a temp path. Call `process_document()` → `index_documents()` as a `BackgroundTask` so the HTTP response returns immediately.
- **List endpoint**: Query the PostgreSQL `documents` table (added in Phase 6; for now return from an in-memory dict or a simple JSON file).
- **Delete endpoint**: Remove from vector store (`delete_by_source`) and S3 (Phase 6).

```python
import uuid
import tempfile
import os
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from app.models.document import UploadResponse, DocumentMetadata, DocumentStatus
from app.core.document_processor.pipeline import process_document
from app.core.vector_store.indexer import index_documents
from app.config import settings
from app.utils.logger import logger
from datetime import datetime, UTC

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".html", ".csv"}
MAX_FILE_SIZE = settings.max_upload_size_mb * 1024 * 1024


async def _ingest_file(file_path: str, document_id: str, file_name: str) -> None:
    try:
        chunks = process_document(file_path)
        for chunk in chunks:
            chunk.metadata["document_id"] = document_id
        result = index_documents(chunks)
        logger.info("document_indexed", document_id=document_id, chunks=result["indexed"])
    except Exception as e:
        logger.error("document_ingestion_failed", document_id=document_id, error=str(e))
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@router.post("/upload", response_model=UploadResponse)
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
) -> UploadResponse:
    results = []
    for file in files:
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, f"Unsupported file type: {ext}")

        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(413, f"File {file.filename} exceeds {settings.max_upload_size_mb}MB limit")

        document_id = str(uuid.uuid4())
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        tmp.write(content)
        tmp.close()

        background_tasks.add_task(_ingest_file, tmp.name, document_id, file.filename)

        results.append(DocumentMetadata(
            document_id=document_id,
            file_name=file.filename or "unknown",
            file_type=ext.lstrip("."),
            file_size_bytes=len(content),
            chunk_count=0,            # updated after background task completes
            status=DocumentStatus.processing,
            uploaded_at=datetime.now(UTC),
        ))

    return UploadResponse(message="Upload received. Processing in background.", documents=results)
```

### Step 5 — Create `backend/app/api/routes/query.py`

#### Standard Q&A endpoint

```python
from fastapi import APIRouter
from app.models.query import AskRequest, AskResponse
from app.core.rag.qa_chain import answer_question

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    rag_response = answer_question(
        question=request.question,
        k=request.k,
    )
    return AskResponse(
        answer=rag_response.answer,
        citations=rag_response.citations,
        retrieved_chunks=rag_response.retrieved_chunks,
        query=rag_response.query,
        session_id=request.session_id,
    )
```

#### Streaming Q&A endpoint (Server-Sent Events)

```python
from fastapi.responses import StreamingResponse
from langchain_core.output_parsers import StrOutputParser
from app.core.rag.bedrock_llm import get_llm
from app.core.rag.prompts.qa_prompt import qa_prompt
from app.core.rag.retriever import retrieve
from app.core.rag.context_builder import build_context
import json


@router.post("/ask/stream")
async def ask_stream(request: AskRequest):
    async def event_stream():
        retrieved_docs = retrieve(request.question, k=request.k)
        context = build_context(retrieved_docs)

        chain = qa_prompt | get_llm() | StrOutputParser()

        async for chunk in chain.astream({
            "context": context,
            "question": request.question,
            "history": "",
        }):
            yield f"data: {json.dumps({'token': chunk})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

#### Summarise endpoint

```python
from app.models.query import SummariseRequest, SummariseResponse as SummariseResponseModel
from app.core.rag.summarise_chain import summarise_document


@router.post("/summarise", response_model=SummariseResponseModel)
async def summarise(request: SummariseRequest) -> SummariseResponseModel:
    # In Phase 6, fetch full document content from S3 by document_id.
    # For now, retrieve from vector store and concatenate chunks.
    from app.core.vector_store.factory import get_vector_store
    store = get_vector_store()
    docs = store.similarity_search(f"document:{request.document_id}", k=20)
    content = "\n\n".join(d.page_content for d in docs)
    result = summarise_document(content, request.document_id, request.summary_type)
    return SummariseResponseModel(
        summary=result.summary,
        document_name=result.document_name,
        summary_type=result.summary_type,
    )
```

#### Compare endpoint

```python
from app.models.query import CompareRequest, CompareResponse as CompareResponseModel
from app.core.rag.compare_chain import compare_documents


@router.post("/compare", response_model=CompareResponseModel)
async def compare(request: CompareRequest) -> CompareResponseModel:
    store = get_vector_store()
    docs_a = store.similarity_search(f"document:{request.document_id_a}", k=20)
    docs_b = store.similarity_search(f"document:{request.document_id_b}", k=20)
    content_a = "\n\n".join(d.page_content for d in docs_a)
    content_b = "\n\n".join(d.page_content for d in docs_b)
    result = compare_documents(content_a, request.document_id_a, content_b, request.document_id_b)
    return CompareResponseModel(
        comparison=result.comparison,
        document_a=result.document_a,
        document_b=result.document_b,
    )
```

### Step 6 — Update `backend/app/main.py`

Register all routers with the correct prefixes:

```python
app.include_router(health.router,    prefix="/api/v1",           tags=["health"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])
app.include_router(query.router,     prefix="/api/v1/query",     tags=["query"])
```

Add global exception handler:

```python
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", path=str(request.url), error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
```

### Step 7 — Write integration tests

`backend/tests/integration/test_api.py`:

- Use `httpx.AsyncClient` with the FastAPI `app` as transport.
- Test `GET /api/v1/health` returns 200.
- Test `POST /api/v1/documents/upload` with a small text file returns 200 and status "processing".
- Test `POST /api/v1/documents/upload` with an unsupported file type returns 400.
- Test `POST /api/v1/query/ask` with mocked RAG chain returns a valid `AskResponse`.
- Mock all AWS calls with `moto`.

---

## Code Generation Prompt

```
You are implementing Phase 4 of the Enterprise Knowledge Assistant (EKA) project.
Phases 0-3 are complete. The RAG core functions (answer_question, summarise_document,
compare_documents) are implemented at `backend/app/core/rag/`.

Task: Implement all FastAPI route handlers, request/response models, and integration tests.

Files to create / update:

1. `backend/app/models/document.py`
   - Pydantic v2 models: DocumentStatus (Enum), DocumentMetadata, UploadResponse, DocumentListResponse

2. `backend/app/models/query.py`
   - Pydantic v2 models: AskRequest, AskResponse, SummariseRequest, SummariseResponse, CompareRequest, CompareResponse
   - AskRequest: question (min 3, max 2000 chars), k (1-20, default 5), optional session_id

3. `backend/app/api/dependencies.py`
   - `get_vector_store_dep()` using lru_cache — returns BaseVectorStore singleton

4. `backend/app/api/routes/documents.py`
   - `POST /upload`: Accept list[UploadFile], validate extension and size, save to tempfile,
     add BackgroundTask calling `_ingest_file(path, document_id, filename)`,
     return UploadResponse immediately with status=processing
   - `_ingest_file`: calls process_document → index_documents, enriches chunks with document_id,
     cleans up temp file in finally block, logs with structlog
   - `GET /`: return DocumentListResponse (stub returning empty list for now)
   - `DELETE /{document_id}`: call store.delete_by_source, return 204

5. `backend/app/api/routes/query.py`
   - `POST /ask`: calls answer_question(), returns AskResponse
   - `POST /ask/stream`: returns StreamingResponse with text/event-stream media type,
     each token yielded as `data: {"token": "..."}\\n\\n`, ends with `data: [DONE]\\n\\n`
     Use chain.astream() for async streaming
   - `POST /summarise`: retrieves chunks by document_id similarity, calls summarise_document
   - `POST /compare`: retrieves chunks for both document IDs, calls compare_documents

6. `backend/app/main.py`
   - Register all 3 routers
   - Global exception handler returning 500 JSON
   - Call configure_logging() from utils.logger on startup

7. `backend/tests/integration/test_api.py`
   - Use `pytest-asyncio` and `httpx.AsyncClient(app=app, base_url="http://test")`
   - Mock `process_document` and `index_documents` to avoid real AWS calls
   - Test health endpoint returns {"status": "ok"}
   - Test upload with a .txt UploadFile bytes returns 200
   - Test upload with .exe returns 400
   - Test ask endpoint with mocked answer_question returns valid AskResponse JSON

Rules:
- Background tasks must not block the HTTP response
- File validation: check extension AND content-type header
- Max file size enforced before processing begins
- Streaming must use `async for` with `astream()` — not synchronous iteration
- All error responses use RFC 7807 format: {"detail": "message"}
- structlog for all request logging
```

---

## Acceptance Criteria

- [ ] `uvicorn backend.app.main:app --reload` starts without errors
- [ ] `GET http://localhost:8000/api/docs` shows all endpoints in Swagger UI
- [ ] Upload a `.pdf` via Swagger returns `{"status": "processing"}` immediately
- [ ] `POST /api/v1/query/ask` with a valid question returns an `AskResponse` with answer
- [ ] `POST /api/v1/query/ask/stream` returns `text/event-stream` content type with token events
- [ ] Upload a `.exe` returns HTTP 400
- [ ] Upload a file over the size limit returns HTTP 413
- [ ] `pytest backend/tests/integration/test_api.py` all tests pass
