# Phase 2 — Embeddings & Vector Database

## Goal

Generate vector embeddings for every document chunk using Amazon Titan Text Embeddings V2 (via Amazon Bedrock), store them in a vector database (FAISS locally, Amazon OpenSearch Serverless in the cloud), and expose a unified retriever interface that the RAG chain in Phase 3 can call without knowing which backend is active.

---

## Prerequisites

- Phase 0 and Phase 1 complete.
- AWS CLI configured with Bedrock access (`aws bedrock list-foundation-models` succeeds).
- `BEDROCK_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0` set in `.env`.
- `VECTOR_STORE_TYPE` set in `.env` (`faiss` for local dev, `opensearch` for cloud).
- `boto3`, `faiss-cpu`, `opensearch-py`, `langchain-aws`, `langchain-community` installed.

---

## What This Phase Produces

```
backend/app/core/embeddings/
├── __init__.py
├── bedrock_embeddings.py     # Titan V2 embeddings wrapper
└── embedding_config.py       # Embedding dimensions and model config

backend/app/core/vector_store/
├── __init__.py
├── base_store.py             # Abstract vector store interface
├── faiss_store.py            # FAISS implementation (local dev)
├── opensearch_store.py       # OpenSearch Serverless implementation (cloud)
├── factory.py                # Returns the correct store based on VECTOR_STORE_TYPE
└── indexer.py                # Ingestion pipeline: chunks → embed → store
```

---

## Concepts

### Amazon Titan Text Embeddings V2

- Model ID: `amazon.titan-embed-text-v2:0`
- Output: 1024-dimensional float vector per text input
- Max input tokens: 8192 tokens (roughly 6000 words)
- Called via `boto3` client `bedrock-runtime` using the `invoke_model` API

### FAISS (Facebook AI Similarity Search)

- In-process vector library; no server required.
- `IndexFlatIP` (inner product / cosine similarity on normalised vectors).
- Index persisted to disk as `faiss.index` and `docstore.pkl`.
- Used only in `APP_ENV=development`.

### Amazon OpenSearch Serverless (AOSS)

- Managed vector search collection.
- Uses the `knn_vector` field type with cosine similarity.
- Authenticated via AWS SigV4 (boto3 credentials, no username/password).
- Used in `APP_ENV=production`.

### Retriever Interface

Both stores implement a `similarity_search(query: str, k: int) -> list[Document]` method so the RAG chain in Phase 3 is agnostic to the backend.

---

## Step-by-Step Instructions

### Step 1 — Create `bedrock_embeddings.py`

Wrap the `boto3` Bedrock Runtime call into a LangChain-compatible `Embeddings` subclass:

```python
import json
import boto3
from langchain_core.embeddings import Embeddings
from app.config import settings


class BedrockTitanEmbeddings(Embeddings):
    def __init__(self):
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
        )
        self._model_id = settings.bedrock_embedding_model_id

    def _embed(self, text: str) -> list[float]:
        body = json.dumps({"inputText": text})
        response = self._client.invoke_model(
            modelId=self._model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        return result["embedding"]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)
```

**Rate limiting note:** Titan Embeddings has a default quota of 2 req/s in `us-east-1`. Add `tenacity` retry with exponential backoff around `_embed()`.

### Step 2 — Create `embedding_config.py`

```python
TITAN_V2_DIMENSIONS = 1024
```

### Step 3 — Create `base_store.py`

```python
from abc import ABC, abstractmethod
from langchain_core.documents import Document


class BaseVectorStore(ABC):

    @abstractmethod
    def add_documents(self, documents: list[Document]) -> None: ...

    @abstractmethod
    def similarity_search(self, query: str, k: int = 5) -> list[Document]: ...

    @abstractmethod
    def similarity_search_with_score(
        self, query: str, k: int = 5
    ) -> list[tuple[Document, float]]: ...

    @abstractmethod
    def delete_by_source(self, source: str) -> None: ...

    @abstractmethod
    def persist(self) -> None: ...
```

### Step 4 — Create `faiss_store.py`

Use `langchain_community.vectorstores.FAISS`:

```python
import os
import pickle
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from app.config import settings
from app.core.embeddings.bedrock_embeddings import BedrockTitanEmbeddings
from .base_store import BaseVectorStore


class FaissVectorStore(BaseVectorStore):
    def __init__(self):
        self._embeddings = BedrockTitanEmbeddings()
        self._index_path = settings.faiss_index_path
        self._store: FAISS | None = None
        self._load_existing()

    def _load_existing(self):
        if os.path.exists(self._index_path):
            self._store = FAISS.load_local(
                self._index_path,
                self._embeddings,
                allow_dangerous_deserialization=True,
            )

    def add_documents(self, documents: list[Document]) -> None:
        if self._store is None:
            self._store = FAISS.from_documents(documents, self._embeddings)
        else:
            self._store.add_documents(documents)
        self.persist()

    def similarity_search(self, query: str, k: int = 5) -> list[Document]:
        if self._store is None:
            return []
        return self._store.similarity_search(query, k=k)

    def similarity_search_with_score(self, query: str, k: int = 5):
        if self._store is None:
            return []
        return self._store.similarity_search_with_score(query, k=k)

    def delete_by_source(self, source: str) -> None:
        # FAISS does not support selective delete; rebuild index without target docs
        raise NotImplementedError("Use OpenSearch for production delete support")

    def persist(self) -> None:
        if self._store:
            os.makedirs(self._index_path, exist_ok=True)
            self._store.save_local(self._index_path)
```

### Step 5 — Create `opensearch_store.py`

Use `langchain_community.vectorstores.OpenSearchVectorSearch` with AWS SigV4:

```python
from opensearchpy import RequestsHttpConnection, AWSV4SignerAuth
import boto3
from langchain_community.vectorstores import OpenSearchVectorSearch
from langchain_core.documents import Document
from app.config import settings
from app.core.embeddings.bedrock_embeddings import BedrockTitanEmbeddings
from app.core.embeddings.embedding_config import TITAN_V2_DIMENSIONS
from .base_store import BaseVectorStore


class OpenSearchVectorStore(BaseVectorStore):
    def __init__(self):
        self._embeddings = BedrockTitanEmbeddings()
        credentials = boto3.Session().get_credentials()
        auth = AWSV4SignerAuth(credentials, settings.aws_region, "aoss")

        self._store = OpenSearchVectorSearch(
            index_name=settings.opensearch_index_name,
            embedding_function=self._embeddings,
            opensearch_url=settings.opensearch_endpoint,
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            vector_field="embedding",
            text_field="text",
            engine="faiss",
            space_type="cosinesimil",
            ef_construction=512,
            m=16,
        )

    def add_documents(self, documents: list[Document]) -> None:
        self._store.add_documents(documents)

    def similarity_search(self, query: str, k: int = 5) -> list[Document]:
        return self._store.similarity_search(query, k=k)

    def similarity_search_with_score(self, query: str, k: int = 5):
        return self._store.similarity_search_with_score(query, k=k)

    def delete_by_source(self, source: str) -> None:
        self._store.client.delete_by_query(
            index=settings.opensearch_index_name,
            body={"query": {"term": {"metadata.source.keyword": source}}},
        )

    def persist(self) -> None:
        pass  # OpenSearch persists automatically
```

### Step 6 — Create `factory.py`

```python
from app.config import settings
from .base_store import BaseVectorStore
from .faiss_store import FaissVectorStore
from .opensearch_store import OpenSearchVectorStore


def get_vector_store() -> BaseVectorStore:
    if settings.vector_store_type == "opensearch":
        return OpenSearchVectorStore()
    return FaissVectorStore()
```

### Step 7 — Create `indexer.py`

The indexer connects the document processor (Phase 1) output to the vector store:

```python
from langchain_core.documents import Document
from app.core.vector_store.factory import get_vector_store
from app.utils.logger import logger
from tenacity import retry, stop_after_attempt, wait_exponential


BATCH_SIZE = 50


def index_documents(documents: list[Document]) -> dict:
    store = get_vector_store()
    total = len(documents)
    indexed = 0

    for batch_start in range(0, total, BATCH_SIZE):
        batch = documents[batch_start : batch_start + BATCH_SIZE]
        _index_batch_with_retry(store, batch)
        indexed += len(batch)
        logger.info("indexing_progress", indexed=indexed, total=total)

    return {"indexed": indexed, "total": total}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _index_batch_with_retry(store, batch: list[Document]) -> None:
    store.add_documents(batch)
```

### Step 8 — Write unit tests

Create `backend/tests/unit/test_embeddings.py`:

- Mock the `boto3` `invoke_model` response to return a 1024-dim vector.
- Verify `BedrockTitanEmbeddings.embed_query("hello")` returns a list of 1024 floats.
- Verify `embed_documents(["a", "b"])` returns 2 lists.

Create `backend/tests/unit/test_vector_store.py`:

- Test `FaissVectorStore.add_documents` and `similarity_search` with mocked embeddings.
- Use `tmp_path` pytest fixture for the FAISS index path.

---

## Code Generation Prompt

```
You are implementing Phase 2 of the Enterprise Knowledge Assistant (EKA) project.
Context: Phase 0 (scaffold) and Phase 1 (document processing) are already complete.
The backend is at `backend/`. The app config is in `backend/app/config.py`.

Task: Implement the Embeddings and Vector Database layer.

Files to create:

A) `backend/app/core/embeddings/bedrock_embeddings.py`
   - Class `BedrockTitanEmbeddings(Embeddings)` implementing LangChain Embeddings interface
   - Uses `boto3.client("bedrock-runtime")` and model `amazon.titan-embed-text-v2:0`
   - `invoke_model` request body: `{"inputText": text}`
   - Response parsing: `result["embedding"]`
   - Wrap `_embed()` with tenacity retry: 3 attempts, exponential backoff 2-10s
   - Both `embed_documents(texts)` and `embed_query(text)` required

B) `backend/app/core/embeddings/embedding_config.py`
   - `TITAN_V2_DIMENSIONS = 1024`

C) `backend/app/core/vector_store/base_store.py`
   - Abstract class `BaseVectorStore` with abstract methods:
     add_documents, similarity_search, similarity_search_with_score,
     delete_by_source, persist

D) `backend/app/core/vector_store/faiss_store.py`
   - Class `FaissVectorStore(BaseVectorStore)`
   - Uses `langchain_community.vectorstores.FAISS`
   - Loads existing index from `settings.faiss_index_path` on init if it exists
   - `add_documents`: creates new store if none exists, otherwise adds to existing
   - Calls `persist()` after each `add_documents`
   - `similarity_search` returns empty list if store not initialised

E) `backend/app/core/vector_store/opensearch_store.py`
   - Class `OpenSearchVectorStore(BaseVectorStore)`
   - Uses `langchain_community.vectorstores.OpenSearchVectorSearch`
   - Auth: `AWSV4SignerAuth` from `opensearchpy` using boto3 session credentials
   - Service name "aoss" (OpenSearch Serverless)
   - Index config: engine="faiss", space_type="cosinesimil", ef_construction=512, m=16
   - `delete_by_source`: uses `delete_by_query` with term match on `metadata.source.keyword`
   - `persist` is a no-op

F) `backend/app/core/vector_store/factory.py`
   - `get_vector_store() -> BaseVectorStore`
   - Returns `OpenSearchVectorStore` if `settings.vector_store_type == "opensearch"`
   - Otherwise returns `FaissVectorStore`

G) `backend/app/core/vector_store/indexer.py`
   - `index_documents(documents: list[Document]) -> dict`
   - Batches in groups of 50
   - Logs progress with structlog
   - Uses `_index_batch_with_retry` decorated with tenacity (3 attempts, exp backoff)
   - Returns `{"indexed": N, "total": N}`

H) `backend/tests/unit/test_embeddings.py`
   - Use `unittest.mock.patch` to mock `boto3.client`
   - Mock `invoke_model` to return a response with a 1024-float embedding
   - Test embed_query returns list[float] of length 1024
   - Test embed_documents with 2 texts returns list of 2 embeddings

I) `backend/tests/unit/test_vector_store.py`
   - Use pytest `tmp_path` fixture; set FAISS_INDEX_PATH to tmp_path
   - Mock `BedrockTitanEmbeddings` to return random 1024-dim vectors
   - Test add_documents then similarity_search returns non-empty results
   - Test similarity_search on empty store returns empty list

Rules:
- All AWS calls must use credentials from boto3 session (not hardcoded keys)
- Do not use LangChain's BedrockEmbeddings wrapper — implement directly with boto3
- All type annotations required
- Use structlog logger from `app.utils.logger` for all logging
- No print statements
```

---

## Acceptance Criteria

- [ ] `BedrockTitanEmbeddings().embed_query("test")` returns a list of 1024 floats (requires Bedrock access)
- [ ] `FaissVectorStore.add_documents(chunks)` persists index to disk
- [ ] After restart, `FaissVectorStore` reloads the persisted index
- [ ] `similarity_search("leave policy", k=3)` returns 3 documents with correct metadata
- [ ] `factory.get_vector_store()` returns `FaissVectorStore` when `VECTOR_STORE_TYPE=faiss`
- [ ] `pytest backend/tests/unit/test_embeddings.py backend/tests/unit/test_vector_store.py` all pass
- [ ] `index_documents(chunks)` logs progress and returns `{"indexed": N, "total": N}`
