# Phase 7 — Testing & RAG Evaluation

## Goal

Achieve confident test coverage across unit, integration, and end-to-end levels. Additionally, implement a RAG quality evaluation suite that measures faithfulness, answer relevance, and context recall — the three dimensions that define whether a RAG system is production-ready. All tests must run in CI without real AWS access.

---

## Prerequisites

- Phases 0–6 complete.
- `pytest`, `pytest-asyncio`, `pytest-cov`, `httpx`, `moto[s3,bedrock]` installed.
- The application runs locally end-to-end (backend + frontend + Postgres).
- At least 5 sample enterprise documents indexed (for evaluation dataset creation).

---

## Test Architecture

```
backend/tests/
├── conftest.py               # Shared fixtures: app client, mocked AWS, test DB
├── unit/
│   ├── test_document_processor.py   (Phase 1)
│   ├── test_embeddings.py           (Phase 2)
│   ├── test_vector_store.py         (Phase 2)
│   ├── test_rag_core.py             (Phase 3)
│   ├── test_context_builder.py      (new)
│   └── test_citation_extractor.py   (new)
├── integration/
│   ├── test_api.py                  (Phase 4)
│   ├── test_db.py                   (Phase 6)
│   └── test_ingestion_pipeline.py   (new — end-to-end ingestion)
└── evaluation/
    ├── eval_dataset.json            # Ground-truth Q&A pairs
    ├── run_evaluation.py            # Evaluation runner
    └── metrics/
        ├── faithfulness.py
        ├── answer_relevance.py
        └── context_recall.py
```

---

## Step-by-Step Instructions

### Step 1 — Create `backend/tests/conftest.py`

This is the most important test file — all shared fixtures live here.

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch, MagicMock
from app.main import app
from app.db.base import Base, get_db
from app.core.vector_store.factory import get_vector_store


# ── In-memory SQLite for tests ───────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture(scope="function")
async def test_db():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ── Mock vector store ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_vector_store():
    from langchain_core.documents import Document
    store = MagicMock()
    sample_docs = [
        Document(
            page_content="The annual leave policy allows 20 days per year.",
            metadata={"file_name": "hr_policy.pdf", "page": 3, "source": "hr_policy.pdf"},
        ),
        Document(
            page_content="Employees must submit leave requests 5 days in advance.",
            metadata={"file_name": "hr_policy.pdf", "page": 4, "source": "hr_policy.pdf"},
        ),
    ]
    store.similarity_search.return_value = sample_docs
    store.similarity_search_with_score.return_value = [(d, 0.9) for d in sample_docs]
    return store


# ── Mock Bedrock (LLM + Embeddings) ──────────────────────────────────────────

@pytest.fixture
def mock_bedrock_llm():
    with patch("app.core.rag.bedrock_llm.ChatBedrock") as mock:
        instance = MagicMock()
        instance.invoke.return_value = MagicMock(content="The leave policy allows 20 days.")
        instance.astream.return_value = aiter(["The ", "leave ", "policy."])
        mock.return_value = instance
        yield instance


@pytest.fixture
def mock_embeddings():
    import random
    with patch("app.core.embeddings.bedrock_embeddings.boto3.client") as mock_client:
        mock_instance = MagicMock()
        mock_instance.invoke_model.return_value = {
            "body": MagicMock(read=lambda: json.dumps(
                {"embedding": [random.random() for _ in range(1024)]}
            ).encode())
        }
        mock_client.return_value = mock_instance
        yield mock_client


# ── HTTP test client ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(test_db, mock_vector_store):
    app.dependency_overrides[get_db] = lambda: test_db
    with patch("app.core.vector_store.factory.get_vector_store", return_value=mock_vector_store):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
    app.dependency_overrides.clear()
```

Install `aiosqlite` for in-memory SQLite async support:

```bash
pip install aiosqlite
```

Add to `requirements-dev.txt`.

### Step 2 — Consolidate and complete unit tests

#### `test_context_builder.py`

```python
from langchain_core.documents import Document
from app.core.rag.context_builder import build_context

def test_context_labels_include_source():
    docs = [Document(page_content="Policy text", metadata={"file_name": "policy.pdf", "page": 1})]
    context = build_context(docs)
    assert "[Source 1: policy.pdf, Page 1]" in context

def test_multiple_docs_separated():
    docs = [
        Document(page_content="A", metadata={"file_name": "a.pdf"}),
        Document(page_content="B", metadata={"file_name": "b.pdf"}),
    ]
    context = build_context(docs)
    assert "---" in context

def test_empty_documents_returns_empty_string():
    assert build_context([]) == ""
```

#### `test_citation_extractor.py`

```python
from langchain_core.documents import Document
from app.core.rag.citation_extractor import extract_citations

def test_deduplication():
    docs = [
        Document(page_content="x", metadata={"file_name": "a.pdf", "page": 1, "source": "a.pdf"}),
        Document(page_content="y", metadata={"file_name": "a.pdf", "page": 1, "source": "a.pdf"}),
    ]
    citations = extract_citations(docs)
    assert len(citations) == 1

def test_different_pages_not_deduplicated():
    docs = [
        Document(page_content="x", metadata={"file_name": "a.pdf", "page": 1, "source": "a.pdf"}),
        Document(page_content="y", metadata={"file_name": "a.pdf", "page": 2, "source": "a.pdf"}),
    ]
    assert len(extract_citations(docs)) == 2
```

### Step 3 — Create integration test for ingestion pipeline

`backend/tests/integration/test_ingestion_pipeline.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
import tempfile, os

@pytest.mark.asyncio
async def test_full_ingestion_pipeline(mock_vector_store):
    # Write a small temp text file
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
        f.write("This is a test document about leave policy.\n\nEmployees get 20 days.")
        tmp_path = f.name

    with patch("app.core.vector_store.factory.get_vector_store", return_value=mock_vector_store):
        from app.core.document_processor.pipeline import process_document
        from app.core.vector_store.indexer import index_documents

        chunks = process_document(tmp_path)
        assert len(chunks) > 0
        assert all("chunk_index" in c.metadata for c in chunks)

        result = index_documents(chunks)
        assert result["indexed"] == result["total"]
        mock_vector_store.add_documents.assert_called()

    os.unlink(tmp_path)
```

### Step 4 — Add coverage configuration

In `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["backend/tests"]
addopts = "--cov=backend/app --cov-report=term-missing --cov-fail-under=70"
```

### Step 5 — Create the RAG evaluation dataset

Create `backend/tests/evaluation/eval_dataset.json` with at least 10 Q&A pairs:

```json
[
  {
    "question": "How many annual leave days do employees receive?",
    "ground_truth": "Employees receive 20 days of annual leave per year.",
    "relevant_documents": ["hr_policy.pdf"]
  },
  {
    "question": "What is the process for submitting a leave request?",
    "ground_truth": "Employees must submit leave requests 5 days in advance through the HR portal.",
    "relevant_documents": ["hr_policy.pdf"]
  },
  {
    "question": "What are the mandatory items for employee onboarding?",
    "ground_truth": "ID verification, signed employment contract, IT equipment setup, and compliance training.",
    "relevant_documents": ["onboarding_guide.pdf"]
  }
]
```

Populate with domain-specific Q&A pairs from the sample documents you index.

### Step 6 — Implement RAG evaluation metrics

#### `backend/tests/evaluation/metrics/faithfulness.py`

Faithfulness measures whether the answer is grounded in the retrieved context (no hallucination):

```python
def evaluate_faithfulness(answer: str, context: str, llm) -> float:
    """
    Uses LLM-as-judge: asks Claude to score on 0-1 whether every claim
    in the answer is supported by the context.
    """
    prompt = f"""Score the faithfulness of this answer to the provided context.
Faithfulness = every claim in the answer is explicitly supported by the context.
Score: 0.0 (completely unfaithful) to 1.0 (fully faithful).
Return only a float, nothing else.

Context:
{context}

Answer:
{answer}
"""
    score_text = llm.invoke(prompt).content.strip()
    try:
        return float(score_text)
    except ValueError:
        return 0.0
```

#### `backend/tests/evaluation/metrics/answer_relevance.py`

Answer relevance measures whether the answer actually addresses the question:

```python
def evaluate_answer_relevance(question: str, answer: str, llm) -> float:
    prompt = f"""Score how relevant this answer is to the question on a 0.0-1.0 scale.
1.0 = completely and directly answers the question.
Return only a float.

Question: {question}
Answer: {answer}
"""
    score_text = llm.invoke(prompt).content.strip()
    try:
        return float(score_text)
    except ValueError:
        return 0.0
```

#### `backend/tests/evaluation/metrics/context_recall.py`

Context recall measures whether the retrieved chunks contain the information needed to answer:

```python
def evaluate_context_recall(ground_truth: str, context: str, llm) -> float:
    prompt = f"""Score whether the provided context contains enough information to
derive the ground truth answer. Score 0.0-1.0.
Return only a float.

Ground Truth: {ground_truth}
Context: {context}
"""
    score_text = llm.invoke(prompt).content.strip()
    try:
        return float(score_text)
    except ValueError:
        return 0.0
```

### Step 7 — Create `run_evaluation.py`

```python
#!/usr/bin/env python3
"""
RAG Evaluation Runner
Usage: python -m tests.evaluation.run_evaluation
Requires: documents indexed, Bedrock access, .env configured
"""
import json
import statistics
from pathlib import Path
from app.core.rag.qa_chain import answer_question
from app.core.rag.context_builder import build_context
from app.core.rag.retriever import retrieve
from app.core.rag.bedrock_llm import get_llm
from .metrics.faithfulness import evaluate_faithfulness
from .metrics.answer_relevance import evaluate_answer_relevance
from .metrics.context_recall import evaluate_context_recall

DATASET_PATH = Path(__file__).parent / "eval_dataset.json"
PASSING_THRESHOLD = 0.70


def run() -> dict:
    dataset = json.loads(DATASET_PATH.read_text())
    llm = get_llm(temperature=0.0)

    results = []
    for item in dataset:
        question = item["question"]
        ground_truth = item["ground_truth"]

        retrieved_docs = retrieve(question, k=5)
        context = build_context(retrieved_docs)
        rag_response = answer_question(question)

        faithfulness = evaluate_faithfulness(rag_response.answer, context, llm)
        relevance = evaluate_answer_relevance(question, rag_response.answer, llm)
        recall = evaluate_context_recall(ground_truth, context, llm)

        results.append({
            "question": question,
            "faithfulness": faithfulness,
            "answer_relevance": relevance,
            "context_recall": recall,
        })
        print(f"Q: {question[:60]}...")
        print(f"  Faithfulness={faithfulness:.2f}  Relevance={relevance:.2f}  Recall={recall:.2f}")

    avg_faithfulness = statistics.mean(r["faithfulness"] for r in results)
    avg_relevance = statistics.mean(r["answer_relevance"] for r in results)
    avg_recall = statistics.mean(r["context_recall"] for r in results)

    print(f"\n=== EVALUATION SUMMARY ===")
    print(f"Avg Faithfulness:  {avg_faithfulness:.3f}  {'PASS' if avg_faithfulness >= PASSING_THRESHOLD else 'FAIL'}")
    print(f"Avg Relevance:     {avg_relevance:.3f}  {'PASS' if avg_relevance >= PASSING_THRESHOLD else 'FAIL'}")
    print(f"Avg Context Recall:{avg_recall:.3f}  {'PASS' if avg_recall >= PASSING_THRESHOLD else 'FAIL'}")

    return {
        "faithfulness": avg_faithfulness,
        "answer_relevance": avg_relevance,
        "context_recall": avg_recall,
        "passed": all(v >= PASSING_THRESHOLD for v in [avg_faithfulness, avg_relevance, avg_recall]),
    }


if __name__ == "__main__":
    result = run()
    exit(0 if result["passed"] else 1)
```

---

## Code Generation Prompt

```
You are implementing Phase 7 of the Enterprise Knowledge Assistant (EKA) project.
Phases 0-6 are complete. The full application (FastAPI + vector store + PostgreSQL + S3) is working.

Task: Create a complete test suite and RAG evaluation framework.

Files to create:

1. `backend/tests/conftest.py`
   - Async in-memory SQLite fixture (using aiosqlite) for all DB tests
   - Mock vector store fixture returning 2 sample Documents
   - Mock Bedrock LLM fixture using unittest.mock.patch on ChatBedrock
   - Mock embeddings fixture using unittest.mock.patch on boto3.client
   - AsyncClient fixture (httpx + ASGITransport) with overridden dependencies

2. `backend/tests/unit/test_context_builder.py`
   - test_source_labels_correct
   - test_multiple_docs_separated_by_divider
   - test_empty_docs_returns_empty_string
   - test_page_and_section_in_label

3. `backend/tests/unit/test_citation_extractor.py`
   - test_deduplication_same_page
   - test_different_pages_not_deduplicated
   - test_missing_metadata_handled_gracefully

4. `backend/tests/integration/test_ingestion_pipeline.py`
   - End-to-end test: write temp .txt file → process_document → index_documents
   - Verify chunks have correct metadata
   - Verify add_documents called on mock store

5. `backend/tests/evaluation/eval_dataset.json`
   - At least 10 Q&A pairs with ground_truth and relevant_documents fields

6. `backend/tests/evaluation/metrics/faithfulness.py`
   - `evaluate_faithfulness(answer, context, llm) -> float` using LLM-as-judge
   
7. `backend/tests/evaluation/metrics/answer_relevance.py`
   - `evaluate_answer_relevance(question, answer, llm) -> float`

8. `backend/tests/evaluation/metrics/context_recall.py`
   - `evaluate_context_recall(ground_truth, context, llm) -> float`

9. `backend/tests/evaluation/run_evaluation.py`
   - Load eval_dataset.json
   - For each item: retrieve, build context, answer_question, score all 3 metrics
   - Print per-question results and summary table
   - Exit code 1 if any metric average < 0.70
   - Can be run as: `python -m tests.evaluation.run_evaluation`

10. Update `pyproject.toml`
    - pytest addopts: --cov=backend/app --cov-report=term-missing --cov-fail-under=70

Rules:
- No real AWS calls in unit or integration tests — use mocks/moto
- Evaluation tests (evaluation/) are NOT run by default pytest; document how to run them separately
- conftest.py fixtures must clean up after themselves (drop tables, clear mocks)
- All test functions must be properly named test_*
- Each test file must have at least 3 test functions
```

---

## Acceptance Criteria

- [ ] `pytest backend/tests/unit/ -v` — all unit tests pass (no real AWS calls)
- [ ] `pytest backend/tests/integration/ -v` — all integration tests pass
- [ ] `pytest --cov=backend/app --cov-report=term-missing` — coverage ≥ 70%
- [ ] `python -m tests.evaluation.run_evaluation` (with real Bedrock) — all 3 metric averages ≥ 0.70
- [ ] `pytest backend/tests/` — total runtime under 60 seconds
- [ ] No test modifies the production database or real S3 bucket
