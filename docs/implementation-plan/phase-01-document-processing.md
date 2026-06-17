# Phase 1 — Document Processing Pipeline

## Goal

Build the document processing pipeline that accepts uploaded files (PDF, DOCX, PPTX, XLSX, TXT, Markdown, HTML, CSV), extracts and cleans text, attaches metadata, and produces a list of semantically chunked `Document` objects ready to be embedded in Phase 2.

---

## Prerequisites

- Phase 0 complete: virtual environment, `backend/` scaffold, dependencies installed.
- `python-docx`, `pypdf`, `unstructured`, `openpyxl`, `python-pptx`, `beautifulsoup4` all installed.
- `backend/app/core/document_processor/` directory exists.

---

## What This Phase Produces

```
backend/app/core/document_processor/
├── __init__.py
├── base_loader.py          # Abstract base class for all loaders
├── loaders/
│   ├── __init__.py
│   ├── pdf_loader.py
│   ├── docx_loader.py
│   ├── pptx_loader.py
│   ├── xlsx_loader.py
│   ├── txt_loader.py
│   ├── markdown_loader.py
│   ├── html_loader.py
│   └── csv_loader.py
├── cleaner.py              # Text normalisation
├── chunker.py              # Recursive character splitting + semantic chunking
├── metadata_extractor.py   # Attaches source, page, section, format, timestamps
└── pipeline.py             # Orchestrates: load → clean → chunk → metadata
```

---

## Concepts

### Document Object

Every loader produces a list of `Document` objects (LangChain's `langchain_core.documents.Document`). Each `Document` has:

- `page_content: str` — extracted text for the chunk
- `metadata: dict` — source file name, page number, section, file type, chunk index, ingestion timestamp

### Chunking Strategy

- Use `RecursiveCharacterTextSplitter` from LangChain as the primary splitter.
- `chunk_size = 1000` characters (approximately 250 tokens — well within Titan Embeddings limit).
- `chunk_overlap = 150` characters to preserve context across chunk boundaries.
- For structured formats (XLSX, CSV) chunk by row-group rather than character count.

---

## Step-by-Step Instructions

### Step 1 — Create `base_loader.py`

Define an abstract class `BaseDocumentLoader` with:

- Abstract method `load(file_path: str) -> list[Document]`
- A `supported_extensions` class attribute (e.g. `[".pdf"]`)

```python
from abc import ABC, abstractmethod
from langchain_core.documents import Document


class BaseDocumentLoader(ABC):
    supported_extensions: list[str] = []

    @abstractmethod
    def load(self, file_path: str) -> list[Document]:
        ...
```

### Step 2 — Create individual loaders

#### `pdf_loader.py`

Use `pypdf.PdfReader` to iterate pages. For each page:
- Extract text with `page.extract_text()`
- Attach metadata: `{"source": file_path, "page": page_number, "file_type": "pdf"}`

Fall back to `unstructured`'s `partition_pdf` if pypdf returns empty text (scanned PDFs).

#### `docx_loader.py`

Use `python-docx` (`Document` class). Iterate `doc.paragraphs` and `doc.tables`.
- Group paragraphs into logical sections using heading styles (`Heading 1`, `Heading 2`).
- Attach metadata: `{"source": file_path, "section": heading_text, "file_type": "docx"}`

#### `pptx_loader.py`

Use `python-pptx`. Iterate slides → shapes → text frames.
- Attach metadata: `{"source": file_path, "slide": slide_number, "file_type": "pptx"}`

#### `xlsx_loader.py`

Use `openpyxl`. Iterate sheets → rows. Convert each sheet into a markdown-style table string.
- Attach metadata: `{"source": file_path, "sheet": sheet_name, "file_type": "xlsx"}`

#### `txt_loader.py`

Read raw UTF-8 text. Split on double newline to create paragraph-level documents.
- Attach metadata: `{"source": file_path, "file_type": "txt"}`

#### `markdown_loader.py`

Read raw text. Split on `##` headings. Each section becomes a document.
- Attach metadata: `{"source": file_path, "file_type": "markdown"}`

#### `html_loader.py`

Use `BeautifulSoup(html, "html.parser")`. Extract `<p>`, `<h1>`–`<h6>`, `<li>` tags.
Remove `<script>` and `<style>` blocks entirely.
- Attach metadata: `{"source": file_path, "file_type": "html"}`

#### `csv_loader.py`

Use `pandas.read_csv`. Convert each row to a key=value sentence:
`"Column1: value1. Column2: value2. ..."`
Group into chunks of 50 rows per document.
- Attach metadata: `{"source": file_path, "file_type": "csv", "rows": "0-49"}`

### Step 3 — Create `cleaner.py`

The cleaner normalises extracted text to improve embedding quality:

```python
import re


def clean_text(text: str) -> str:
    text = re.sub(r'\n{3,}', '\n\n', text)         # Collapse excess newlines
    text = re.sub(r' {2,}', ' ', text)              # Collapse multiple spaces
    text = re.sub(r'\t', ' ', text)                 # Replace tabs
    text = text.strip()
    return text
```

Apply `clean_text` to every `Document.page_content` after loading.

### Step 4 — Create `chunker.py`

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document


CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


def chunk_documents(documents: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(documents)
    for idx, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = idx
    return chunks
```

### Step 5 — Create `metadata_extractor.py`

After chunking, enrich each chunk's metadata:

```python
from datetime import datetime, UTC
import os


def enrich_metadata(chunks: list, original_file_path: str) -> list:
    file_name = os.path.basename(original_file_path)
    ingested_at = datetime.now(UTC).isoformat()
    for chunk in chunks:
        chunk.metadata.setdefault("source", file_name)
        chunk.metadata["file_name"] = file_name
        chunk.metadata["ingested_at"] = ingested_at
        chunk.metadata["char_count"] = len(chunk.page_content)
    return chunks
```

### Step 6 — Create `pipeline.py`

This is the single public entry point for the document processing phase:

```python
import os
from langchain_core.documents import Document
from .loaders import get_loader_for_extension
from .cleaner import clean_text
from .chunker import chunk_documents
from .metadata_extractor import enrich_metadata


SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".html", ".htm", ".csv"
}


def process_document(file_path: str) -> list[Document]:
    ext = os.path.splitext(file_path)[1].lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")

    loader = get_loader_for_extension(ext)
    raw_documents = loader.load(file_path)

    cleaned_documents = []
    for doc in raw_documents:
        doc.page_content = clean_text(doc.page_content)
        if doc.page_content:               # discard empty pages
            cleaned_documents.append(doc)

    chunks = chunk_documents(cleaned_documents)
    chunks = enrich_metadata(chunks, file_path)

    return chunks
```

### Step 7 — Create `loaders/__init__.py` loader registry

```python
from ..base_loader import BaseDocumentLoader
from .pdf_loader import PdfLoader
from .docx_loader import DocxLoader
from .pptx_loader import PptxLoader
from .xlsx_loader import XlsxLoader
from .txt_loader import TxtLoader
from .markdown_loader import MarkdownLoader
from .html_loader import HtmlLoader
from .csv_loader import CsvLoader

_REGISTRY: dict[str, type[BaseDocumentLoader]] = {
    ".pdf":  PdfLoader,
    ".docx": DocxLoader,
    ".pptx": PptxLoader,
    ".xlsx": XlsxLoader,
    ".txt":  TxtLoader,
    ".md":   MarkdownLoader,
    ".html": HtmlLoader,
    ".htm":  HtmlLoader,
    ".csv":  CsvLoader,
}


def get_loader_for_extension(ext: str) -> BaseDocumentLoader:
    cls = _REGISTRY.get(ext)
    if cls is None:
        raise ValueError(f"No loader registered for extension: {ext}")
    return cls()
```

### Step 8 — Write unit tests for the pipeline

Create `backend/tests/unit/test_document_processor.py`:

- Test `process_document` with a minimal in-memory PDF (use `pypdf` to create one).
- Test `clean_text` with strings containing excess whitespace and newlines.
- Test `chunk_documents` verifies chunks are within size limits.
- Test metadata contains `source`, `file_name`, `chunk_index`, `ingested_at`.

---

## Code Generation Prompt

```
You are implementing Phase 1 of the Enterprise Knowledge Assistant (EKA) project.
The backend is a FastAPI application located at `backend/`.
Python virtual environment is active; all dependencies from requirements.txt are installed.

Task: Implement the complete Document Processing Pipeline.

Directory to populate: `backend/app/core/document_processor/`

Files to create:

1. `base_loader.py`
   - Abstract class `BaseDocumentLoader` with abstract method `load(file_path: str) -> list[Document]`
   - `supported_extensions: list[str]` class attribute

2. `loaders/__init__.py`
   - Registry dict mapping file extension strings to loader classes
   - Function `get_loader_for_extension(ext: str) -> BaseDocumentLoader`

3. `loaders/pdf_loader.py`
   - Use `pypdf.PdfReader` to extract text page by page
   - Fallback to `unstructured.partition.pdf.partition_pdf` for scanned PDFs (empty text)
   - Metadata: source, page (int), file_type="pdf"

4. `loaders/docx_loader.py`
   - Use `python-docx`. Extract paragraphs grouped by heading sections.
   - Metadata: source, section (heading text), file_type="docx"

5. `loaders/pptx_loader.py`
   - Use `python-pptx`. Extract all text frames per slide.
   - Metadata: source, slide (int), file_type="pptx"

6. `loaders/xlsx_loader.py`
   - Use `openpyxl`. Convert each sheet to a readable table string.
   - Metadata: source, sheet (name), file_type="xlsx"

7. `loaders/txt_loader.py`
   - Read UTF-8 text. Split on double newline.
   - Metadata: source, file_type="txt"

8. `loaders/markdown_loader.py`
   - Read text. Split on `##` headings.
   - Metadata: source, file_type="markdown"

9. `loaders/html_loader.py`
   - Use BeautifulSoup. Extract p, h1-h6, li. Strip script and style tags.
   - Metadata: source, file_type="html"

10. `loaders/csv_loader.py`
    - Use pandas.read_csv. Convert rows to "Col: val." strings. Group 50 rows per Document.
    - Metadata: source, file_type="csv", rows (range string)

11. `cleaner.py`
    - `clean_text(text: str) -> str`: collapse 3+ newlines to 2, collapse spaces, strip tabs

12. `chunker.py`
    - `chunk_documents(documents: list[Document]) -> list[Document]`
    - Use `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)`
    - After splitting, set `chunk.metadata["chunk_index"] = idx`

13. `metadata_extractor.py`
    - `enrich_metadata(chunks, original_file_path) -> list`
    - Adds: file_name, ingested_at (UTC ISO string), char_count per chunk

14. `pipeline.py`
    - Public function `process_document(file_path: str) -> list[Document]`
    - Validates extension, loads, cleans, chunks, enriches metadata
    - Returns final list of Document chunks

15. `backend/tests/unit/test_document_processor.py`
    - Test clean_text normalisation
    - Test chunk_documents respects chunk_size
    - Test metadata keys present after pipeline
    - Use a small in-memory .txt temp file for pipeline integration test

Rules:
- Each loader must handle FileNotFoundError gracefully.
- Empty page_content after cleaning must be discarded.
- Do not use LangChain's built-in document loaders — write native loaders using the listed libraries directly.
- All type annotations required.
- No print statements; use structlog logger from `app.utils.logger`.
```

---

## Acceptance Criteria

- [ ] `process_document("sample.pdf")` returns a non-empty list of `Document` objects
- [ ] Every chunk has `metadata` keys: `source`, `file_name`, `chunk_index`, `ingested_at`, `char_count`, `file_type`
- [ ] No chunk exceeds 1100 characters (chunk_size + small tolerance)
- [ ] `pytest backend/tests/unit/test_document_processor.py` passes with 100% of tests green
- [ ] All 8 loaders handle a real sample file without raising exceptions
- [ ] Empty documents (blank files) do not cause crashes; they return an empty list
