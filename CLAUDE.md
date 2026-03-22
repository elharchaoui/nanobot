# CLAUDE.md — Project Notes for Claude Code

## Custom Modifications (Preserve After Upstream Merges)

This is a fork of the upstream nanobot repo. When pulling upstream changes, the
following local modifications must be preserved. Always check for conflicts in
these areas after a merge.

---

### 1. Exa Search Provider (`nanobot/agent/tools/web.py`)

An `exa` provider was added to `WebSearch.execute()` and `_search_exa()` was
implemented. The upstream only supports `brave`, `tavily`, `duckduckgo`,
`searxng`, and `jina`.

**What to preserve:**
- `elif provider == "exa": return await self._search_exa(query, n)` branch in `execute()`
- The `_search_exa()` method (calls `https://api.exa.ai/search` with `x-api-key` header)
- API key lookup order: `self.config.exa_api_key` → `self.config.api_key` → `EXA_API_KEY` env var → fallback to DuckDuckGo

**Related schema change (`nanobot/config/schema.py`):**
- `WebSearchConfig` must have `exa_api_key: str = ""` field so `exaApiKey` from
  `~/.nanobot/config.json` is properly loaded.

---

### 2. Mem0 Memory Fix — Trailing Assistant Message (`nanobot/agent/memory.py`)

Anthropic models reject LLM calls where the conversation ends with an assistant
message ("conversation must end with a user message"). The `_consolidate_mem0()`
method must strip trailing assistant messages before passing to `mem0.add()`.

**What to preserve** (in `MemoryStore._consolidate_mem0()`, after building `chat_messages`):
```python
# Anthropic requires conversations to end with a user message
while chat_messages and chat_messages[-1]["role"] == "assistant":
    chat_messages.pop()
```

---

### Active Config

- **Main LLM model**: `minimax/minimax-m2.7` (via OpenRouter) — set in `~/.nanobot/config.json`
- **Search provider**: `exa` with key stored in `tools.web.search.exaApiKey` in config
- **Memory**: mem0 enabled, using `openai/gpt-4o-mini` + `text-embedding-3-small` via OpenRouter
