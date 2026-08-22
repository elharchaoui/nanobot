# Knowledge Base (KB) — Design Document

**Status:** Draft  
**Date:** 2026-04-02  
**Project:** nanobot

---

## Overview

A personal knowledge base layer for nanobot. The user explicitly curates knowledge — URLs, documents, notes, code snippets — and the agent queries it on their behalf. This is distinct from mem0, which is agent memory (automatic, conversation-driven). The KB is user-driven: nothing is stored without an explicit instruction.

---

## Goals

- Give the user a queryable knowledge base that survives session restarts
- Support adding knowledge from URLs, raw text, and code snippets
- Surface relevant knowledge automatically or on demand during conversations
- Keep the system local-first and inspectable

---

## Non-Goals

- Agent-driven automatic ingestion (that is mem0's job)
- Multi-user isolation (single-user system)
- Real-time web crawling or RSS feeds
- Cloud sync (local-first; sync is out of scope)
- Semantic deduplication (handled by the user)

---

## Architecture

```
User instruction: "remember this URL / note / snippet"
    │
    ▼
┌─────────────────────┐
│  Ingest Layer        │  Smart detect → fetch/summarize URLs, store text as-is
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Structure-aware     │  Split into parent chunks (injection) and
│  Chunker             │  child chunks (retrieval), respecting document structure
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Embedder            │  Embed child chunks via text-embedding-3-small
│                      │  Error → raise immediately, store nothing
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  ChromaDB            │  Two collections:
│  Vector Store        │  · child_chunks (embedding + parent_id)
│                      │  · parent_chunks (text + metadata, no embedding)
└────────┬────────────┘
         │ (at query time)
         ▼
┌─────────────────────┐
│  Retriever           │  Embed query → score child chunks → resolve parent chunks
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Context Injector    │  Prepend retrieved parent chunks to system prompt
└─────────────────────┘
```

---

## Ingest Layer — Smart Detect

Detection logic:

```
input
 ├── matches URL pattern?     → fetch page content → summarize → store summary + source URL
 ├── looks like a code block? → store as-is, mark type: "code"
 └── otherwise                → store as-is, mark type: "text"
```

| Scenario | Behavior | Reason |
|---|---|---|
| User provides a URL | Fetch + summarize | Raw HTML is noisy; a summary is more useful for retrieval |
| User provides a paragraph | Store as-is | Already human-readable; no transformation needed |
| User provides a code snippet | Store as-is, type=code | Code must not be paraphrased; exact text matters |

### URL fetching

- Use `WebFetch` to retrieve the page
- Summarize with a short LLM call: "Summarize this page for future reference in 3–5 sentences."
- Stored text: the summary. Metadata: `source_url`, `fetched_at`.

---

## Chunking — Structure-aware with Parent-Child Retrieval

Fixed-size chunking cuts across sentence and paragraph boundaries, producing incoherent fragments that hurt retrieval precision. Instead, the system uses a two-level parent-child approach:

```
Document
  │
  ├── Parent chunks (~1024 tokens, boundary-aligned)
  │     Stored in parent_chunks collection (no embedding)
  │     Used for INJECTION — what the agent reads
  │
  └── Child chunks (~128 tokens, sentence/paragraph level)
        Stored in child_chunks collection (with embedding)
        Used for RETRIEVAL — what gets scored against the query
```

When a child chunk scores above the threshold, its parent chunk is what gets injected into the prompt. This gives:
- **Precise retrieval**: small chunks match queries more tightly
- **Rich context injection**: agent reads the full surrounding section, not a 128-token fragment

### Splitting rules (applied in order of priority)

1. **Markdown headers** (`##`, `###`) — hard boundary, never split across a section
2. **Blank lines** (paragraph breaks) — preferred split point
3. **Sentence boundaries** (`.`, `?`, `!` followed by space + capital letter)
4. **Token limit fallback** — split mid-sentence only if a paragraph exceeds the child size limit

### Per content type

| Type | Strategy |
|---|---|
| `url` | Usually short (summary). Often a single parent chunk. Split by sentence if longer. |
| `text` | Paragraph-aware splitting. Respect blank lines first, then sentences. |
| `code` | Never split mid-block. Split only at top-level function or class boundaries. |

### Size parameters

| Parameter | Value |
|---|---|
| Parent chunk size | ~1024 tokens |
| Child chunk size | ~128 tokens |

Short inputs (< 128 tokens) are stored as a single child = single parent, no splitting.

---

## Embedding

- **Model:** `text-embedding-3-small` (OpenAI-compatible, via OpenRouter)
- **Dimensions:** 1536
- **Only child chunks are embedded** — parent chunks are stored as plain text
- **Error policy:** If the embedding API call fails, raise an exception immediately. Nothing is stored. No fallback, no partial state, no retry queue. The user retries when the API is available.

---

## Vector Store — ChromaDB

- **Library:** ChromaDB (embedded, no server process)
- **Persistence path:** `~/.nanobot/kb/chroma/`
- **Two collections:**

### `child_chunks` collection

Stores embeddings for retrieval.

```jsonc
{
  "id": "uuid-v4",
  "embedding": [0.1, ...],
  "metadata": {
    "parent_id": "uuid-v4",
    "source": "https://..." | "user",
    "type": "url" | "text" | "code",
    "chunk_index": 0,
    "added_at": "2026-04-02T12:00:00Z"
  },
  "document": "<child chunk text>"
}
```

### `parent_chunks` collection

Stores full text for injection. No embedding.

```jsonc
{
  "id": "uuid-v4",
  "metadata": {
    "source": "https://..." | "user",
    "type": "url" | "text" | "code",
    "tags": [],
    "added_at": "2026-04-02T12:00:00Z",
    "fetched_at": "2026-04-02T12:00:00Z"   // URL only
  },
  "document": "<parent chunk text>"
}
```

---

## Retrieval

### Algorithm

1. Embed the query string via `text-embedding-3-small`
2. Query `child_chunks` collection: cosine similarity, fetch top-K×3 candidates
3. Filter by similarity threshold (≥ 0.75)
4. Deduplicate by `parent_id` — keep the highest-scoring child per parent
5. Resolve parent chunks from `parent_chunks` collection
6. Return top-K parent chunks, sorted by score descending

### Parameters

| Parameter | Default |
|---|---|
| Top-K (parents returned) | 5 |
| Similarity threshold | 0.75 |
| Candidate multiplier | ×3 (fetch 15 children, resolve to 5 parents) |

---

## Context Injection

Retrieved parent chunks are injected into the system prompt before the user message:

```
[KNOWLEDGE BASE]
Source: https://example.com (fetched 2026-04-02)
---
<parent chunk text>

Source: user note (added 2026-04-02)
---
<parent chunk text>
[END KNOWLEDGE BASE]
```

- Max injected tokens: 2000 (chunks truncated if total exceeds limit, highest-scoring first)
- Injection is skipped if no chunks meet the threshold

---

## Tool Interface

Three tools exposed to the agent:

### `kb_add`

Add a URL, text note, or code snippet to the knowledge base.

```
kb_add(input: string, tags?: string[]) → { id, parent_chunks_stored, child_chunks_stored, type }
```

- Runs smart detect on `input`
- Raises on embedding failure — nothing stored

### `kb_search`

Manually query the knowledge base (explicit recall or debugging).

```
kb_search(query: string, k?: number) → ParentChunk[]
```

### `kb_delete`

Remove a document (all its parent and child chunks) by source ID.

```
kb_delete(id: string) → { deleted_parents: number, deleted_children: number }
```

---

## Automatic vs. Manual Retrieval

- **Automatic (default):** Every user message triggers a retrieval pass. Relevant parent chunks (above threshold) are injected silently.
- **Manual override:** User can say "check the knowledge base for X" to trigger an explicit `kb_search` call.
- **Opt-out:** User can say "ignore the knowledge base" to suppress injection for that turn.

---

## File Layout

```
~/.nanobot/
└── kb/
    ├── chroma/           # ChromaDB persistence directory
    └── config.json       # chunk sizes, top-K, threshold overrides
```

---

## Configuration (`config.json`)

```jsonc
{
  "parent_chunk_size": 1024,
  "child_chunk_size": 128,
  "top_k": 5,
  "similarity_threshold": 0.75,
  "max_injected_tokens": 2000,
  "summarize_urls": true,
  "embedding_model": "text-embedding-3-small"
}
```

---

## Open Questions

| # | Question | Status |
|---|---|---|
| 1 | Should re-fetching a URL update or append its chunks? | Leaning toward update (replace old chunks for that source) |
| 2 | How to handle PDF / local file path inputs? | Deferred to v2 |
| 3 | Should retrieval fire on every turn or only on certain signals? | Defaulting to every turn; revisit if latency is an issue |

---

## Implementation Phases

### Phase 1 — Core storage
- [ ] Set up ChromaDB with `child_chunks` and `parent_chunks` collections
- [ ] Implement structure-aware chunker (parent-child split)
- [ ] Wire up embedding API (`text-embedding-3-small`), raise on error
- [ ] Implement cosine similarity retrieval with parent resolution
- [ ] Expose `kb_add`, `kb_search`, `kb_delete` tools

### Phase 2 — Ingest polish
- [ ] Smart detect (URL vs. text vs. code)
- [ ] URL fetch + summarize pipeline
- [ ] Tag support and metadata filtering in `kb_search`

### Phase 3 — Auto-retrieval
- [ ] Hook retrieval into every conversation turn
- [ ] Context injection into system prompt
- [ ] Token budget enforcement (highest-scoring first)

### Phase 4 — Maintenance
- [ ] `kb_delete` cascades to both collections
- [ ] Config hot-reload
- [ ] ChromaDB collection stats / list sources command
