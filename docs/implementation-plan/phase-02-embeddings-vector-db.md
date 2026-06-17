# Phase 2 — Embeddings & Vector Database

## Goal

Generate vector embeddings for every document chunk using Amazon Titan Text Embeddings V2 (via Amazon Bedrock) and index them into **Amazon OpenSearch Serverless** — the single vector database used across all environments. Local development targets a LocalStack-simulated OpenSearch instance; cloud environments target a real AOSS collection. Expose a clean retriever interface that Phase 3's RAG chain calls without knowing the environment.

---

## Prerequisites

- Phase 0 and Phase 1 complete.
- AWS CLI configured with Bedrock access (`aws bedrock list-foundation-models` succeeds).
- `BEDROCK_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0` set in `.env`.
- `OPENSEARCH_ENDPOINT` set in `.env` (LocalStack URL for dev, AOSS URL for cloud).
- `boto3`, `opensearch-py`, `requests-aws4auth`, `langchain-aws`, `langchain-community` installed.
- LocalStack running locally with OpenSearch service enabled (`docker compose -f infra/docker-compose.dev.yml up -d`).
- **For cloud:** An Amazon OpenSearch Serverless collection created and its endpoint recorded in `.env`.

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
├── opensearch_store.py       # OpenSearch Serverless (all environments)
├── factory.py                # Returns OpenSearchVectorStore singleton
└── indexer.py                # Ingestion pipeline: chunks → embed → store
```

---

## Concepts

### Amazon Titan Text Embeddings V2

- Model ID: `amazon.titan-embed-text-v2:0`
- Output: 1024-dimensional float vector per text input
- Max input tokens: 8192 tokens (roughly 6000 words)
- Called via `boto3` client `bedrock-runtime` using the `invoke_model` API

### Amazon OpenSearch Serverless (AOSS)

- Fully managed, serverless vector search — no cluster sizing required.
- Uses the `knn_vector` field type with cosine similarity (`space_type="cosinesimil"`).
- Authenticated via **AWS SigV4** (boto3 credentials — no username/password).
- Works identically in both local (LocalStack) and cloud (AOSS) environments; only the endpoint URL differs.
- Hybrid search: combines dense vector similarity with BM25 keyword scoring for higher recall.

### Local Development — LocalStack OpenSearch

LocalStack emulates an OpenSearch endpoint at `http://localhost:4566`. Set:
```
OPENSEARCH_ENDPOINT=http://localhost:4566
```
Authentication for LocalStack uses no-auth (or dummy SigV4 that LocalStack accepts).

### Cloud — Amazon OpenSearch Serverless Collection Setup

Before deploying to AWS, create the AOSS collection:

```bash
# 1. Create a collection
aws opensearchserverless create-collection \
  --name eka-knowledge-base \
  --type VECTORSEARCH \
  --region us-east-1

# 2. Create an encryption policy (required for AOSS)
aws opensearchserverless create-security-policy \
  --name eka-encryption-policy \
  --type encryption \
  --policy '{"Rules":[{"Resource":["collection/eka-knowledge-base"],"ResourceType":"collection"}],"AWSOwnedKey":true}'

# 3. Create a network policy (allow public access)
aws opensearchserverless create-security-policy \
  --name eka-network-policy \
  --type network \
  --policy '[{"Rules":[{"Resource":["collection/eka-knowledge-base"],"ResourceType":"collection"},{"Resource":["collection/eka-knowledge-base"],"ResourceType":"dashboard"}],"AllowFromPublic":true}]'

# 4. Create a data access policy (allow ECS task role)
aws opensearchserverless create-access-policy \
  --name eka-data-access \
  --type data \
  --policy '[{"Rules":[{"Resource":["collection/eka-knowledge-base"],"Permission":["aoss:CreateCollectionItems","aoss:DeleteCollectionItems","aoss:UpdateCollectionItems","aoss:DescribeCollectionItems"],"ResourceType":"collection"},{"Resource":["index/eka-knowledge-base/*"],"Permission":["aoss:CreateIndex","aoss:DeleteIndex","aoss:UpdateIndex","aoss:DescribeIndex","aoss:ReadDocument","aoss:WriteDocument"],"ResourceType":"index"}],"Principal":["arn:aws:iam::ACCOUNT_ID:role/ekaTaskRole"]}]'

# 5. Get the collection endpoint and set it in .env
aws opensearchserverless get-collection --id <collection-id> \
  --query 'collectionDetails.collectionEndpoint' --output text
```

### Retriever Interface

`OpenSearchVectorStore` implements `similarity_search(query, k) -> list[Document]` which Phase 3 calls. Tests use a `unittest.mock.MagicMock` in place of the real store — no FAISS, no disk state.

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

### Step 4 — Create `opensearch_store.py`

Use `langchain_community.vectorstores.OpenSearchVectorSearch` with AWS SigV4. The connection is automatically adapted for LocalStack (no SSL, no cert verification) vs real AOSS (SSL + cert verification):

```python
from opensearchpy import RequestsHttpConnection, AWSV4SignerAuth
import boto3
from langchain_community.vectorstores import OpenSearchVectorSearch
from langchain_core.documents import Document
from app.config import settings
from app.core.embeddings.bedrock_embeddings import BedrockTitanEmbeddings
from .base_store import BaseVectorStore


class OpenSearchVectorStore(BaseVectorStore):
    def __init__(self):
        self._embeddings = BedrockTitanEmbeddings()

        is_localstack = settings.is_local and settings.localstack_endpoint
        endpoint = (
            f"{settings.localstack_endpoint}/opensearch/us-east-1/{settings.opensearch_index_name}"
            if is_localstack
            else settings.opensearch_endpoint
        )
        # SigV4 service name differs: "aoss" for real AOSS, "es" for LocalStack
        service_name = "es" if is_localstack else "aoss"
        credentials = boto3.Session().get_credentials()
        auth = AWSV4SignerAuth(credentials, settings.aws_region, service_name)

        self._store = OpenSearchVectorSearch(
            index_name=settings.opensearch_index_name,
            embedding_function=self._embeddings,
            opensearch_url=endpoint,
            http_auth=auth,
            use_ssl=not is_localstack,
            verify_certs=not is_localstack,
            ssl_assert_hostname=not is_localstack,
            ssl_show_warn=False,
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

    def create_index_if_not_exists(self) -> None:
        client = self._store.client
        if not client.indices.exists(index=settings.opensearch_index_name):
            client.indices.create(
                index=settings.opensearch_index_name,
                body={
                    "settings": {"index": {"knn": True}},
                    "mappings": {
                        "properties": {
                            "embedding": {
                                "type": "knn_vector",
                                "dimension": 1024,
                                "method": {
                                    "name": "hnsw",
                                    "space_type": "cosinesimil",
                                    "engine": "faiss",
                                    "parameters": {"ef_construction": 512, "m": 16},
                                },
                            },
                            "text": {"type": "text"},
                            "metadata": {"type": "object"},
                        }
                    },
                },
            )
```

### Step 5 — Create `factory.py`

```python
from functools import lru_cache
from .base_store import BaseVectorStore
from .opensearch_store import OpenSearchVectorStore


@lru_cache(maxsize=1)
def get_vector_store() -> BaseVectorStore:
    store = OpenSearchVectorStore()
    store.create_index_if_not_exists()
    return store
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

### Step 7 — Write unit tests

Create `backend/tests/unit/test_embeddings.py`:

- Mock `boto3.client` to return a fake `invoke_model` response with a 1024-float list.
- Verify `BedrockTitanEmbeddings.embed_query("hello")` returns a list of 1024 floats.
- Verify `embed_documents(["a", "b"])` returns 2 lists each of length 1024.

Create `backend/tests/unit/test_vector_store.py`:

- Mock `OpenSearchVectorSearch` entirely — do not connect to any real or LocalStack endpoint.
- Test `add_documents` delegates to the underlying `_store.add_documents`.
- Test `similarity_search` returns the mocked result.
- Test `delete_by_source` calls `delete_by_query` with correct body.
- Test `create_index_if_not_exists` calls `indices.create` only when `indices.exists` returns False.

---

## Code Generation Prompt

```
You are implementing Phase 2 of the Enterprise Knowledge Assistant (EKA) project.
Phases 0 (scaffold) and 1 (document processing) are complete.
The backend is at `backend/`. Config is in `backend/app/config.py`.
IMPORTANT: There is NO FAISS in this project. Amazon OpenSearch Serverless is the
single vector store for all environments. Do not create faiss_store.py.

Task: Implement the Embeddings and Vector Database layer.

Files to create:

A) `backend/app/core/embeddings/bedrock_embeddings.py`
   - Class `BedrockTitanEmbeddings(Embeddings)` implementing LangChain Embeddings interface
   - Uses `boto3.client("bedrock-runtime", region_name=settings.aws_region)`
   - `invoke_model` request body: `{"inputText": text}`
   - Response parsing: `result["embedding"]`
   - Wrap `_embed()` with tenacity retry: 3 attempts, exponential backoff 2-10s
   - Both `embed_documents(texts)` and `embed_query(text)` required

B) `backend/app/core/embeddings/embedding_config.py`
   - `TITAN_V2_DIMENSIONS = 1024`

C) `backend/app/core/vector_store/base_store.py`
   - Abstract class `BaseVectorStore` with abstract methods:
     add_documents, similarity_search, similarity_search_with_score,
     delete_by_source, persist, create_index_if_not_exists

D) `backend/app/core/vector_store/opensearch_store.py`
   - Class `OpenSearchVectorStore(BaseVectorStore)`
   - Uses `langchain_community.vectorstores.OpenSearchVectorSearch`
   - On init, detect LocalStack vs real AOSS:
     * LocalStack: endpoint = settings.localstack_endpoint + "/opensearch/us-east-1/" + index_name,
       service_name="es", use_ssl=False, verify_certs=False
     * AOSS: endpoint = settings.opensearch_endpoint, service_name="aoss",
       use_ssl=True, verify_certs=True
   - Auth: `AWSV4SignerAuth(boto3.Session().get_credentials(), settings.aws_region, service_name)`
   - Index mapping: knn_vector field "embedding" (dim=1024, engine=faiss, cosinesimil, hnsw)
   - `create_index_if_not_exists()`: creates the index with full knn_vector mapping if absent
   - `delete_by_source`: delete_by_query on metadata.source.keyword
   - `persist` is a no-op (OpenSearch is durable by default)

E) `backend/app/core/vector_store/factory.py`
   - `get_vector_store() -> BaseVectorStore` decorated with `@lru_cache(maxsize=1)`
   - Always returns `OpenSearchVectorStore` (no other option)
   - Calls `store.create_index_if_not_exists()` on first call

F) `backend/app/core/vector_store/indexer.py`
   - `index_documents(documents: list[Document]) -> dict`
   - Batches in groups of 50
   - Logs progress with structlog
   - Uses `_index_batch_with_retry` with tenacity (3 attempts, exponential backoff 2-10s)
   - Returns `{"indexed": N, "total": N}`

G) `backend/tests/unit/test_embeddings.py`
   - Use `unittest.mock.patch` to mock `boto3.client`
   - Mock `invoke_model` to return a response body with a 1024-float list
   - Test embed_query returns list[float] of length 1024
   - Test embed_documents with 2 texts returns 2 lists
   - Test tenacity retry fires on ClientError (mock throws then succeeds)

H) `backend/tests/unit/test_vector_store.py`
   - Mock `OpenSearchVectorSearch` entirely with MagicMock — no real HTTP calls
   - Mock `indices.exists` returning False → test create_index_if_not_exists calls create
   - Mock `indices.exists` returning True → test create_index_if_not_exists skips create
   - Test add_documents delegates to _store.add_documents
   - Test similarity_search returns mocked result
   - Test delete_by_source calls delete_by_query with correct body structure

Rules:
- Do NOT create faiss_store.py or import faiss anywhere
- All AWS calls must use boto3 session credentials (not hardcoded keys)
- Do not use LangChain's built-in BedrockEmbeddings — implement directly with boto3
- LocalStack detection: settings.is_local AND settings.localstack_endpoint is non-empty
- All type annotations required
- Use structlog logger for all logging; no print statements
```

---

## Acceptance Criteria

- [ ] `faiss_store.py` does NOT exist anywhere in the codebase
- [ ] `BedrockTitanEmbeddings().embed_query("test")` returns a list of 1024 floats (requires Bedrock access)
- [ ] With LocalStack running: `awslocal opensearch list-domain-names` shows the index
- [ ] `similarity_search("leave policy", k=3)` returns 3 documents with correct metadata (against LocalStack)
- [ ] `factory.get_vector_store()` always returns an `OpenSearchVectorStore` instance
- [ ] `factory.get_vector_store()` returns the same instance on repeated calls (lru_cache)
- [ ] `pytest backend/tests/unit/test_embeddings.py backend/tests/unit/test_vector_store.py` all pass with zero real network calls
- [ ] `index_documents(chunks)` logs progress and returns `{"indexed": N, "total": N}`
- [ ] OpenSearch index is auto-created with correct `knn_vector` mapping on first `get_vector_store()` call
