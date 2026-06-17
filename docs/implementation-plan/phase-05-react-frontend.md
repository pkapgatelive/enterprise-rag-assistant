# Phase 5 — React / TypeScript Frontend

## Goal

Build a production-quality, responsive web UI using React 18, TypeScript, and Tailwind CSS. The interface provides a chat panel for Q&A, a document upload area, citation display, conversation history, and document management. It communicates exclusively with the FastAPI backend from Phase 4.

---

## Prerequisites

- Phase 4 backend running at `http://localhost:8000`.
- `frontend/` Vite project scaffolded in Phase 0 (`npm create vite@latest frontend -- --template react-ts`).
- Tailwind CSS configured.
- Node.js 20 LTS.

---

## Additional Frontend Dependencies

```bash
cd frontend

# HTTP client
npm install axios

# UI components / icons
npm install lucide-react

# Markdown rendering (for AI responses)
npm install react-markdown remark-gfm

# Syntax highlighting (code blocks in responses)
npm install react-syntax-highlighter @types/react-syntax-highlighter

# Form handling
npm install react-hook-form

# Notifications
npm install react-hot-toast

# UUID (session IDs)
npm install uuid @types/uuid
```

---

## What This Phase Produces

```
frontend/src/
├── types/
│   ├── document.ts          # Document and upload types
│   └── chat.ts              # Chat message, citation, session types
├── services/
│   ├── api.ts               # Axios instance with base URL
│   ├── documentService.ts   # Upload, list, delete document API calls
│   └── queryService.ts      # ask, askStream, summarise, compare API calls
├── hooks/
│   ├── useChat.ts           # Chat state, send message, session management
│   ├── useDocuments.ts      # Document list state and operations
│   └── useStream.ts         # SSE streaming hook
├── components/
│   ├── layout/
│   │   ├── AppLayout.tsx    # Sidebar + main content shell
│   │   ├── Sidebar.tsx      # Navigation and document list
│   │   └── Header.tsx       # Top bar with title and theme toggle
│   ├── chat/
│   │   ├── ChatPanel.tsx    # Main chat area
│   │   ├── MessageBubble.tsx # Individual chat message
│   │   ├── ChatInput.tsx    # Text input + send button
│   │   └── CitationCard.tsx # Source citation display
│   ├── documents/
│   │   ├── UploadDropzone.tsx   # Drag-and-drop upload area
│   │   ├── DocumentList.tsx     # Uploaded documents table
│   │   └── DocumentCard.tsx     # Single document row
│   └── shared/
│       ├── LoadingSpinner.tsx
│       ├── ErrorMessage.tsx
│       └── Badge.tsx
├── pages/
│   ├── ChatPage.tsx         # Main chat page
│   └── DocumentsPage.tsx    # Document management page
├── utils/
│   └── formatters.ts        # Date, file size formatters
├── App.tsx
└── main.tsx
```

---

## Step-by-Step Instructions

### Step 1 — Configure Tailwind CSS

In `tailwind.config.ts`, extend the theme for brand colours and configure the content paths:

```typescript
import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eff6ff',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
        },
      },
    },
  },
  plugins: [],
}

export default config
```

In `src/index.css`, add Tailwind directives:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

### Step 2 — Define TypeScript types

`src/types/chat.ts`:

```typescript
export interface Citation {
  file_name: string
  page: number | string | null
  section: string | null
  source: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  retrievedChunks?: number
  timestamp: Date
  isStreaming?: boolean
}

export interface ChatSession {
  sessionId: string
  messages: ChatMessage[]
  createdAt: Date
}
```

`src/types/document.ts`:

```typescript
export type DocumentStatus = 'processing' | 'indexed' | 'failed'

export interface DocumentMetadata {
  document_id: string
  file_name: string
  file_type: string
  file_size_bytes: number
  chunk_count: number
  status: DocumentStatus
  uploaded_at: string
}
```

### Step 3 — Create `src/services/api.ts`

```typescript
import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1',
  timeout: 30000,
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error.response?.data?.detail || error.message || 'An error occurred'
    return Promise.reject(new Error(message))
  }
)

export default api
```

Add `VITE_API_BASE_URL=http://localhost:8000/api/v1` to `frontend/.env.local`.

### Step 4 — Create `src/services/documentService.ts`

```typescript
import api from './api'
import type { DocumentMetadata } from '../types/document'

export const documentService = {
  async upload(files: File[]): Promise<{ documents: DocumentMetadata[] }> {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    const { data } = await api.post('/documents/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },

  async list(): Promise<{ documents: DocumentMetadata[]; total: number }> {
    const { data } = await api.get('/documents/')
    return data
  },

  async remove(documentId: string): Promise<void> {
    await api.delete(`/documents/${documentId}`)
  },
}
```

### Step 5 — Create `src/services/queryService.ts`

```typescript
import api from './api'
import type { ChatMessage } from '../types/chat'

export const queryService = {
  async ask(question: string, k = 5, sessionId?: string) {
    const { data } = await api.post('/query/ask', { question, k, session_id: sessionId })
    return data
  },

  async summarise(documentId: string, summaryType = 'executive') {
    const { data } = await api.post('/query/summarise', {
      document_id: documentId,
      summary_type: summaryType,
    })
    return data
  },

  async compare(documentIdA: string, documentIdB: string) {
    const { data } = await api.post('/query/compare', {
      document_id_a: documentIdA,
      document_id_b: documentIdB,
    })
    return data
  },

  createStreamingAsk(question: string, k = 5): EventSource {
    // POST-based SSE requires fetch + ReadableStream since EventSource only supports GET
    return new EventSource(
      `${import.meta.env.VITE_API_BASE_URL}/query/ask/stream?question=${encodeURIComponent(question)}&k=${k}`
    )
  },
}
```

### Step 6 — Create `src/hooks/useChat.ts`

```typescript
import { useState, useCallback } from 'react'
import { v4 as uuidv4 } from 'uuid'
import type { ChatMessage, ChatSession } from '../types/chat'
import { queryService } from '../services/queryService'

export function useChat() {
  const [session, setSession] = useState<ChatSession>({
    sessionId: uuidv4(),
    messages: [],
    createdAt: new Date(),
  })
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const sendMessage = useCallback(async (question: string) => {
    const userMessage: ChatMessage = {
      id: uuidv4(),
      role: 'user',
      content: question,
      timestamp: new Date(),
    }

    setSession((prev) => ({
      ...prev,
      messages: [...prev.messages, userMessage],
    }))
    setIsLoading(true)
    setError(null)

    try {
      const response = await queryService.ask(question, 5, session.sessionId)
      const assistantMessage: ChatMessage = {
        id: uuidv4(),
        role: 'assistant',
        content: response.answer,
        citations: response.citations,
        retrievedChunks: response.retrieved_chunks,
        timestamp: new Date(),
      }
      setSession((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }))
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to get answer')
    } finally {
      setIsLoading(false)
    }
  }, [session.sessionId])

  const clearSession = useCallback(() => {
    setSession({ sessionId: uuidv4(), messages: [], createdAt: new Date() })
    setError(null)
  }, [])

  return { session, isLoading, error, sendMessage, clearSession }
}
```

### Step 7 — Create key UI components

#### `ChatInput.tsx`

A textarea that submits on Enter (Shift+Enter for newline), with a send button and character counter.

#### `MessageBubble.tsx`

- User messages: right-aligned blue bubble.
- Assistant messages: left-aligned white/grey bubble with markdown rendering (`react-markdown` + `remark-gfm`).
- Show citation cards below assistant messages.
- Show a pulsing animation when `isStreaming=true`.

#### `CitationCard.tsx`

Compact card showing file name, page, section with a document icon from `lucide-react`.

#### `UploadDropzone.tsx`

- Uses the HTML5 drag-and-drop API and `<input type="file" multiple>`.
- Accepts: `.pdf,.docx,.pptx,.xlsx,.txt,.md,.html,.csv`.
- Shows progress per file.
- Calls `documentService.upload()` on drop/select.

#### `DocumentList.tsx`

Table with columns: File Name, Type, Size, Status (badge), Uploaded, Actions (delete button).

### Step 8 — Create pages

#### `ChatPage.tsx`

Main layout: left sidebar (document list, new chat button), right main area (chat messages, input).

#### `DocumentsPage.tsx`

Full-page document management: upload dropzone at top, document list below.

### Step 9 — Configure routing

Use hash-based routing without installing `react-router-dom`:

```typescript
// App.tsx — simple hash-based page selector
import { useState } from 'react'
import ChatPage from './pages/ChatPage'
import DocumentsPage from './pages/DocumentsPage'

export default function App() {
  const [page, setPage] = useState<'chat' | 'documents'>('chat')
  return page === 'chat'
    ? <ChatPage onNavigate={setPage} />
    : <DocumentsPage onNavigate={setPage} />
}
```

Or install `react-router-dom v6` if richer routing is needed.

### Step 10 — Configure environment

Create `frontend/.env.local`:

```
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

Create `frontend/.env.production`:

```
VITE_API_BASE_URL=/api/v1
```

---

## Code Generation Prompt

```
You are implementing Phase 5 of the Enterprise Knowledge Assistant (EKA) project.
The FastAPI backend is running at http://localhost:8000 with these endpoints:
  POST /api/v1/documents/upload (multipart)
  GET  /api/v1/documents/
  DELETE /api/v1/documents/{id}
  POST /api/v1/query/ask  → {answer, citations, retrieved_chunks, query, session_id}
  POST /api/v1/query/ask/stream → SSE stream of {token: "..."} ending with [DONE]
  POST /api/v1/query/summarise → {summary, document_name, summary_type}
  POST /api/v1/query/compare  → {comparison, document_a, document_b}

Tech: React 18, TypeScript, Tailwind CSS, Vite.
Additional packages already installed: axios, lucide-react, react-markdown, remark-gfm,
react-hook-form, react-hot-toast, uuid.

Task: Implement the complete frontend.

Files to create:

1. `src/types/chat.ts` — Citation, ChatMessage (role, content, citations, isStreaming), ChatSession
2. `src/types/document.ts` — DocumentStatus, DocumentMetadata
3. `src/services/api.ts` — axios instance with VITE_API_BASE_URL, error interceptor
4. `src/services/documentService.ts` — upload (FormData), list, remove
5. `src/services/queryService.ts` — ask, summarise, compare

6. `src/hooks/useChat.ts`
   - State: session (messages array), isLoading, error
   - sendMessage(question): appends user message, calls queryService.ask, appends assistant message
   - clearSession(): resets to new session with new UUID

7. `src/hooks/useDocuments.ts`
   - State: documents, isLoading, error
   - fetchDocuments(): calls documentService.list()
   - uploadFiles(files): calls documentService.upload(), refreshes list after
   - removeDocument(id): calls documentService.remove(), refreshes list after

8. `src/components/layout/AppLayout.tsx`
   - Two-column layout: fixed 280px sidebar + flex-grow main area
   - Sidebar has navigation links: "Chat" and "Documents"
   - Header shows "Enterprise Knowledge Assistant" with a bot icon

9. `src/components/chat/ChatInput.tsx`
   - Textarea, auto-resize up to 5 lines
   - Enter sends (Shift+Enter for newline)
   - Send button disabled when isLoading or question is empty
   - Character counter showing X/2000

10. `src/components/chat/MessageBubble.tsx`
    - User: right-aligned, blue background, white text
    - Assistant: left-aligned, white background, grey border, markdown rendered
    - Timestamp shown in small text below each bubble
    - If isStreaming: show pulsing ellipsis "..."

11. `src/components/chat/CitationCard.tsx`
    - Shows: file icon + file_name + "Page X" or "Section Y" badge
    - Compact horizontal card, shown in a row below assistant message

12. `src/components/chat/ChatPanel.tsx`
    - Scrollable message list using useChat hook
    - Auto-scrolls to bottom on new message
    - Shows "No documents indexed yet" empty state when messages=[],
    - Shows LoadingSpinner when isLoading

13. `src/components/documents/UploadDropzone.tsx`
    - HTML5 drag-and-drop + click-to-browse
    - Accepted types: .pdf .docx .pptx .xlsx .txt .md .html .csv
    - Max 50MB per file, client-side validation before upload
    - Progress indicator per file (using Axios upload progress)
    - On success: toast notification + refresh document list

14. `src/components/documents/DocumentList.tsx`
    - Table: Name | Type | Size | Status | Uploaded | Actions
    - Status shown as colored Badge (processing=yellow, indexed=green, failed=red)
    - Delete button with confirmation prompt before calling removeDocument

15. `src/pages/ChatPage.tsx`
    - Left panel: document count badge, "New Chat" button, recent messages preview
    - Right panel: ChatPanel (messages) + ChatInput
    - Shows error toast if chat fails

16. `src/pages/DocumentsPage.tsx`
    - UploadDropzone at top
    - DocumentList below
    - "Refresh" button

17. `src/App.tsx`
    - Simple state-based navigation between ChatPage and DocumentsPage
    - Wrap with react-hot-toast <Toaster />

18. `tailwind.config.ts` — configure content paths and brand color extension

Rules:
- All components must be functional with React hooks, no class components
- All props must have TypeScript interfaces
- Use Tailwind utility classes exclusively — no custom CSS except in index.css for Tailwind directives
- Axios errors must show as toast notifications
- No hardcoded API URLs — use import.meta.env.VITE_API_BASE_URL
- Responsive: mobile-friendly (stack sidebar above content on small screens)
```

---

## Acceptance Criteria

- [ ] `npm run dev` starts without TypeScript errors
- [ ] `npm run build` produces a dist/ bundle without errors
- [ ] Upload a PDF via the dropzone; it appears in the document list with status "processing"
- [ ] Type a question in the chat input and press Enter; an answer appears with citation cards
- [ ] Chat messages persist within the session on page scroll
- [ ] The document list shows "indexed" / "processing" status badges with correct colours
- [ ] Responsive layout: sidebar stacks correctly on a 375px viewport
- [ ] No `console.error` output in the browser during normal use
