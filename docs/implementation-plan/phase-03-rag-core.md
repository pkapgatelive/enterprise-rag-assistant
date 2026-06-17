# Phase 3 — RAG Core: Retrieval & LLM Integration

## Goal

Wire the retriever (Phase 2 vector store), context builder, prompt templates, and Amazon Bedrock (Claude) together into a complete, working RAG chain. This phase produces three capabilities: **question answering**, **document summarisation**, and **document comparison**. By the end, the entire AI pipeline can be called from a plain Python function.

---

## Prerequisites

- Phase 0: scaffold and config complete.
- Phase 1: `process_document()` returns `list[Document]`.
- Phase 2: `get_vector_store()` and `index_documents()` working.
- Amazon Bedrock access for model `anthropic.claude-3-5-sonnet-20241022-v2:0`.
- `langchain`, `langchain-aws`, `langchain-community` installed.

---

## What This Phase Produces

```
backend/app/core/rag/
├── __init__.py
├── bedrock_llm.py            # Claude via Bedrock LLM wrapper
├── prompts/
│   ├── __init__.py
│   ├── qa_prompt.py          # Question-answering prompt template
│   ├── summarise_prompt.py   # Summarisation prompt template
│   └── compare_prompt.py     # Document comparison prompt template
├── retriever.py              # Retrieves top-k chunks, formats context
├── context_builder.py        # Builds the context string from retrieved docs
├── citation_extractor.py     # Extracts source citations from retrieved docs
├── qa_chain.py               # Full Q&A RAG chain
├── summarise_chain.py        # Summarisation chain
├── compare_chain.py          # Document comparison chain
└── response_models.py        # Pydantic output models for chain responses
```

---

## Concepts

### LangChain Expression Language (LCEL)

Chains are built using LCEL pipe notation:
```python
chain = prompt | llm | output_parser
```
This makes each step modular and testable in isolation.

### Retrieval-Augmented Generation Flow

```
User Query
    │
    ▼
embed_query()   ─── Titan Embeddings V2
    │
    ▼
vector_store.similarity_search(query, k=5)
    │
    ▼
context_builder.build(retrieved_docs)
    │
    ▼
prompt_template.format(context=..., question=...)
    │
    ▼
bedrock_llm.invoke(prompt)   ─── Claude 3.5 Sonnet via Bedrock
    │
    ▼
citation_extractor.extract(retrieved_docs)
    │
    ▼
RAGResponse(answer, sources, retrieved_docs)
```

### Conversation Memory

Use `ConversationBufferWindowMemory(k=5)` to keep the last 5 exchanges in context. This is stored per session in-memory during Phase 3; it is persisted to PostgreSQL in Phase 6.

---

## Step-by-Step Instructions

### Step 1 — Create `bedrock_llm.py`

Use `langchain_aws.ChatBedrock` to wrap Claude on Bedrock:

```python
from langchain_aws import ChatBedrock
from app.config import settings


def get_llm(temperature: float = 0.0, max_tokens: int = 2048) -> ChatBedrock:
    return ChatBedrock(
        model_id=settings.bedrock_llm_model_id,
        region_name=settings.aws_region,
        model_kwargs={
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": 0.9,
        },
    )
```

### Step 2 — Create `prompts/qa_prompt.py`

The Q&A prompt must instruct Claude to:
1. Answer ONLY using the provided context.
2. Cite sources explicitly.
3. State clearly if the answer is not found in the context.
4. Keep the answer concise and factual.

```python
from langchain_core.prompts import ChatPromptTemplate

QA_SYSTEM = """You are an Enterprise Knowledge Assistant. Your role is to answer
questions accurately based strictly on the provided document context.

Rules:
- Answer ONLY using the information in the context below.
- Always cite the source document name and page/section at the end.
- If the answer cannot be found in the context, respond with:
  "I could not find information about this in the available documents."
- Do not make up information or rely on prior training data.
- Be concise, factual, and professional.

Context:
{context}

Conversation History:
{history}
"""

QA_HUMAN = "Question: {question}"

qa_prompt = ChatPromptTemplate.from_messages([
    ("system", QA_SYSTEM),
    ("human", QA_HUMAN),
])
```

### Step 3 — Create `prompts/summarise_prompt.py`

```python
from langchain_core.prompts import ChatPromptTemplate

SUMMARISE_SYSTEM = """You are a document summarisation expert.
Summarise the following document content according to the requested summary type.

Summary types:
- executive: 3-5 bullet points for senior leadership (no technical jargon)
- technical: detailed summary preserving technical specifics
- key_takeaways: numbered list of the most important points
- brief: 2-3 sentence overview

Document content:
{content}
"""

SUMMARISE_HUMAN = "Provide a {summary_type} summary."

summarise_prompt = ChatPromptTemplate.from_messages([
    ("system", SUMMARISE_SYSTEM),
    ("human", SUMMARISE_HUMAN),
])
```

### Step 4 — Create `prompts/compare_prompt.py`

```python
from langchain_core.prompts import ChatPromptTemplate

COMPARE_SYSTEM = """You are a document comparison expert.
Compare Document A and Document B and provide a structured analysis.

Document A ({doc_a_name}):
{doc_a_content}

Document B ({doc_b_name}):
{doc_b_content}
"""

COMPARE_HUMAN = """Provide the comparison as:
1. **Common Topics** — what both documents cover
2. **Unique to {doc_a_name}** — topics only in Document A
3. **Unique to {doc_b_name}** — topics only in Document B
4. **Key Differences** — where they differ in content or position
5. **Summary** — one paragraph conclusion
"""

compare_prompt = ChatPromptTemplate.from_messages([
    ("system", COMPARE_SYSTEM),
    ("human", COMPARE_HUMAN),
])
```

### Step 5 — Create `retriever.py`

```python
from langchain_core.documents import Document
from app.core.vector_store.factory import get_vector_store


def retrieve(query: str, k: int = 5) -> list[Document]:
    store = get_vector_store()
    return store.similarity_search(query, k=k)


def retrieve_with_scores(query: str, k: int = 5) -> list[tuple[Document, float]]:
    store = get_vector_store()
    return store.similarity_search_with_score(query, k=k)
```

### Step 6 — Create `context_builder.py`

```python
from langchain_core.documents import Document


def build_context(documents: list[Document]) -> str:
    sections = []
    for i, doc in enumerate(documents, 1):
        source = doc.metadata.get("file_name", "Unknown")
        page = doc.metadata.get("page", "")
        section = doc.metadata.get("section", "")
        location = f"[Source {i}: {source}"
        if page:
            location += f", Page {page}"
        if section:
            location += f", Section: {section}"
        location += "]"
        sections.append(f"{location}\n{doc.page_content}")
    return "\n\n---\n\n".join(sections)
```

### Step 7 — Create `citation_extractor.py`

```python
from langchain_core.documents import Document


def extract_citations(documents: list[Document]) -> list[dict]:
    seen = set()
    citations = []
    for doc in documents:
        meta = doc.metadata
        key = (meta.get("file_name", ""), meta.get("page", ""), meta.get("section", ""))
        if key not in seen:
            seen.add(key)
            citations.append({
                "file_name": meta.get("file_name", "Unknown"),
                "page": meta.get("page"),
                "section": meta.get("section"),
                "source": meta.get("source", ""),
            })
    return citations
```

### Step 8 — Create `response_models.py`

```python
from pydantic import BaseModel


class Citation(BaseModel):
    file_name: str
    page: int | str | None = None
    section: str | None = None
    source: str


class RAGResponse(BaseModel):
    answer: str
    citations: list[Citation]
    retrieved_chunks: int
    query: str


class SummariseResponse(BaseModel):
    summary: str
    document_name: str
    summary_type: str


class CompareResponse(BaseModel):
    comparison: str
    document_a: str
    document_b: str
```

### Step 9 — Create `qa_chain.py`

```python
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from .bedrock_llm import get_llm
from .prompts.qa_prompt import qa_prompt
from .retriever import retrieve
from .context_builder import build_context
from .citation_extractor import extract_citations
from .response_models import RAGResponse, Citation


def answer_question(
    question: str,
    k: int = 5,
    conversation_history: str = "",
) -> RAGResponse:
    retrieved_docs = retrieve(question, k=k)
    context = build_context(retrieved_docs)

    chain = qa_prompt | get_llm() | StrOutputParser()

    answer = chain.invoke({
        "context": context,
        "question": question,
        "history": conversation_history,
    })

    raw_citations = extract_citations(retrieved_docs)
    citations = [Citation(**c) for c in raw_citations]

    return RAGResponse(
        answer=answer,
        citations=citations,
        retrieved_chunks=len(retrieved_docs),
        query=question,
    )
```

### Step 10 — Create `summarise_chain.py`

```python
from langchain_core.output_parsers import StrOutputParser
from .bedrock_llm import get_llm
from .prompts.summarise_prompt import summarise_prompt
from .response_models import SummariseResponse

VALID_SUMMARY_TYPES = {"executive", "technical", "key_takeaways", "brief"}


def summarise_document(
    content: str,
    document_name: str,
    summary_type: str = "executive",
) -> SummariseResponse:
    if summary_type not in VALID_SUMMARY_TYPES:
        raise ValueError(f"summary_type must be one of {VALID_SUMMARY_TYPES}")

    chain = summarise_prompt | get_llm() | StrOutputParser()
    summary = chain.invoke({"content": content, "summary_type": summary_type})

    return SummariseResponse(
        summary=summary,
        document_name=document_name,
        summary_type=summary_type,
    )
```

### Step 11 — Create `compare_chain.py`

```python
from langchain_core.output_parsers import StrOutputParser
from .bedrock_llm import get_llm
from .prompts.compare_prompt import compare_prompt
from .response_models import CompareResponse


def compare_documents(
    doc_a_content: str,
    doc_a_name: str,
    doc_b_content: str,
    doc_b_name: str,
) -> CompareResponse:
    chain = compare_prompt | get_llm() | StrOutputParser()
    comparison = chain.invoke({
        "doc_a_content": doc_a_content,
        "doc_a_name": doc_a_name,
        "doc_b_content": doc_b_content,
        "doc_b_name": doc_b_name,
    })
    return CompareResponse(
        comparison=comparison,
        document_a=doc_a_name,
        document_b=doc_b_name,
    )
```

### Step 12 — Write unit tests

`backend/tests/unit/test_rag_core.py`:

- Mock `get_vector_store()` to return a store with fixture documents.
- Mock `get_llm()` to return a mock ChatBedrock that returns a fixed string.
- Test `answer_question` returns a `RAGResponse` with non-empty answer and citations.
- Test `build_context` formats source labels correctly.
- Test `extract_citations` deduplicates same source/page pairs.
- Test `summarise_document` raises `ValueError` for invalid summary_type.

---

## Code Generation Prompt

```
You are implementing Phase 3 of the Enterprise Knowledge Assistant (EKA) project.
Phases 0-2 are complete. The vector store and document pipeline are working.

Task: Implement the RAG Core layer at `backend/app/core/rag/`.

Files to create:

1. `bedrock_llm.py`
   - Function `get_llm(temperature=0.0, max_tokens=2048) -> ChatBedrock`
   - Uses `langchain_aws.ChatBedrock` with `settings.bedrock_llm_model_id`
   - model_kwargs: temperature, max_tokens, top_p=0.9

2. `prompts/qa_prompt.py`
   - `QA_SYSTEM` string with rules: answer only from context, cite sources,
     say "not found" if absent, no hallucination
   - `QA_HUMAN` = "Question: {question}"
   - `qa_prompt = ChatPromptTemplate.from_messages(...)` with system + human
   - Variables: {context}, {history}, {question}

3. `prompts/summarise_prompt.py`
   - System prompt explains 4 summary types: executive, technical, key_takeaways, brief
   - Human prompt: "Provide a {summary_type} summary."
   - Variables: {content}, {summary_type}

4. `prompts/compare_prompt.py`
   - System prompt embeds doc A and B content with their names
   - Human prompt requests 5-section structured comparison
   - Variables: {doc_a_name}, {doc_a_content}, {doc_b_name}, {doc_b_content}

5. `retriever.py`
   - `retrieve(query, k=5) -> list[Document]`
   - `retrieve_with_scores(query, k=5) -> list[tuple[Document, float]]`
   - Both use `get_vector_store()` from factory

6. `context_builder.py`
   - `build_context(documents) -> str`
   - Format each doc: "[Source N: file_name, Page X, Section: Y]\n{content}"
   - Join with "\n\n---\n\n"

7. `citation_extractor.py`
   - `extract_citations(documents) -> list[dict]`
   - Keys per citation: file_name, page, section, source
   - Deduplicate by (file_name, page, section) tuple

8. `response_models.py`
   - Pydantic v2 models: Citation, RAGResponse, SummariseResponse, CompareResponse

9. `qa_chain.py`
   - `answer_question(question, k=5, conversation_history="") -> RAGResponse`
   - Flow: retrieve → build_context → qa_prompt | get_llm() | StrOutputParser() → extract_citations

10. `summarise_chain.py`
    - `summarise_document(content, document_name, summary_type="executive") -> SummariseResponse`
    - Validate summary_type in {"executive","technical","key_takeaways","brief"}

11. `compare_chain.py`
    - `compare_documents(doc_a_content, doc_a_name, doc_b_content, doc_b_name) -> CompareResponse`

12. `backend/tests/unit/test_rag_core.py`
    - Mock get_vector_store to return a store with 3 fixture Document objects
    - Mock get_llm to return a callable returning "Mock answer"
    - Test answer_question returns RAGResponse with answer="Mock answer" and len(citations)>=1
    - Test build_context includes "[Source 1:" in output
    - Test extract_citations deduplication works
    - Test summarise_document raises ValueError for summary_type="invalid"

Rules:
- Use LCEL (| operator) for all chains
- All responses use Pydantic v2 response models
- No streaming in this phase (streaming added in Phase 4)
- All type annotations required
- Use structlog logger for chain invocation logging
```

---

## Acceptance Criteria

- [ ] `answer_question("What is the leave policy?")` returns a `RAGResponse` with a non-empty answer (requires indexed docs)
- [ ] `RAGResponse.citations` is a non-empty list with `file_name` populated
- [ ] `summarise_document(content, "doc.pdf", "executive")` returns a `SummariseResponse`
- [ ] `compare_documents(...)` returns a `CompareResponse` with structured sections
- [ ] `pytest backend/tests/unit/test_rag_core.py` passes all tests without hitting AWS
- [ ] Prompts are grounded — Claude's answer for a question about content NOT in any document returns the "not found" message
