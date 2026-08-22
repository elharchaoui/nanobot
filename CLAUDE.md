# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

nanobot is a lightweight, open-source AI agent framework written in Python with a React/TypeScript WebUI. It centers around a small agent loop that receives messages from chat channels, invokes an LLM provider, executes tools, and manages session memory.

## Development Commands

```bash
# Python: run single test / lint
pytest tests/test_openai_api.py::test_function -v
ruff check nanobot/

# WebUI: dev server (proxies API/WS to gateway :8765), build, test
# Build outputs to ../nanobot/web/dist (bundled into the Python wheel)
cd webui && bun run dev      # or NANOBOT_API_URL=... bun run dev
cd webui && bun run build
cd webui && bun run test

# Gateway
nanobot gateway
```

## High-Level Architecture

### Core Data Flow

Messages flow through an async `MessageBus` (`nanobot/bus/queue.py`) that decouples chat channels from the agent core:

1. **Channels** (`nanobot/channels/`) receive messages from external platforms and publish `InboundMessage` events to the bus.
2. **`AgentLoop`** (`nanobot/agent/loop.py`) consumes inbound messages, builds context, and coordinates the turn.
3. **`AgentRunner`** (`nanobot/agent/runner.py`) handles the actual LLM conversation loop: send messages to the provider, receive tool calls, execute tools, and stream responses.
4. Responses are published as `OutboundMessage` events back to the appropriate channel.

### Key Subsystems

- **Agent Loop** (`nanobot/agent/loop.py`, `runner.py`): The core processing engine. `AgentLoop` manages session keys, hooks, and context building. `AgentRunner` executes the multi-turn LLM conversation with tool execution.
- **LLM Providers** (`nanobot/providers/`): Provider implementations (Anthropic, OpenAI-compatible, OpenAI Responses API, Azure, Bedrock, GitHub Copilot, OpenAI Codex, etc.) built on a common base (`base.py`). Includes image generation (`image_generation.py`) and audio transcription (`transcription.py`). `factory.py` and `registry.py` handle instantiation and model discovery.
- **Channels** (`nanobot/channels/`): Platform integrations (Telegram, Discord, Slack, Feishu, Matrix, WhatsApp, QQ, WeChat, WeCom, DingTalk, Email, MoChat, MS Teams, WebSocket). `manager.py` discovers and coordinates them. Channels are auto-discovered via `pkgutil` scan + entry-point plugins.
- **Tools** (`nanobot/agent/tools/`): Agent capabilities exposed to the LLM: filesystem (read/write/edit/list), shell execution (with sandbox backends), web search/fetch, MCP servers, cron, notebook editing, subagent spawning, long-running tasks / sustained goals (`long_task.py`), image generation, and self-modification. Tools are auto-discovered via `pkgutil` scan + entry-point plugins.
- **Memory** (`nanobot/agent/memory.py`): Session history persistence with Dream two-phase memory consolidation. Uses atomic writes with fsync for durability.
- **Session Management** (`nanobot/session/`): Per-session history, context compaction, TTL-based auto-compaction (`manager.py`), and sustained goal state tracking (`goal_state.py`).
- **Config** (`nanobot/config/schema.py`, `loader.py`): Pydantic-based configuration loaded from `~/.nanobot/config.json`. Supports camelCase aliases for JSON compatibility.
- **Bridge** (`bridge/`): TypeScript services (e.g. WhatsApp bridge) bundled into the wheel via `pyproject.toml` `force-include`.
- **WebUI** (`webui/`): Vite-based React SPA that talks to the gateway over a WebSocket multiplex protocol. The dev server proxies `/api`, `/webui`, `/auth`, and WebSocket traffic to the gateway.
- **API Server** (`nanobot/api/server.py`): OpenAI-compatible HTTP API (`/v1/chat/completions`, `/v1/models`) for programmatic access.
- **Command Router** (`nanobot/command/`): Slash command routing and built-in command handlers.
- **Heartbeat** (`nanobot/heartbeat/`): Periodic agent wake-up service for scheduled task checking.
- **Pairing** (`nanobot/pairing/`): DM sender approval store with persistent pairing codes per channel.
- **Skills** (`nanobot/skills/`): Built-in skill definitions (long-goal, cron, github, image-generation, etc.) loaded into agent context.
- **Security** (`nanobot/security/`): PTH file guard and other security measures activated at CLI entry.

### Entry Points

- **CLI**: `nanobot/cli/commands.py`
- **Python SDK**: `nanobot/nanobot.py`

## Project-Specific Notes

- Architecture constraints: [`.agent/design.md`](.agent/design.md)
- Security boundaries: [`.agent/security.md`](.agent/security.md)
- Common gotchas: [`.agent/gotchas.md`](.agent/gotchas.md)

## Branching Strategy

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the full two-branch model (`main` vs `nightly`) and PR guidelines.

## Code Style

- Python 3.11+, asyncio throughout.
- Line length: 100.
- Linting: `ruff` with rules E, F, I, N, W (E501 ignored).
- pytest with `asyncio_mode = "auto"`.

## Common File Locations

- Config schema: `nanobot/config/schema.py`
- Provider base / new provider template: `nanobot/providers/base.py`
- Channel base / new channel template: `nanobot/channels/base.py`
- Tool registry: `nanobot/agent/tools/registry.py`
- WebUI dev proxy config: `webui/vite.config.ts`
- Tests mirror the `nanobot/` package structure.

---

# Fork Notes — Custom Modifications (Preserve After Upstream Merges)

This is a fork of upstream nanobot (`elharchaoui/nanobot`, tracking `HKUDS/nanobot`).
Currently synced to upstream `v0.2.0`. Two local features must survive every
upstream merge; the sections below describe what they are and how to re-apply
them if a merge drops them.

### Merge strategy

Each custom feature lives on its own topic branch (`feat/exa-search`, `feat/mem0`),
kept as local branches (not pushed to origin). To merge upstream:

1. `git fetch upstream`
2. `git rebase upstream/main feat/exa-search` — fix conflicts (`web_exa.py` only;
   it's a standalone file, so conflicts only happen if upstream renames/refactors
   `nanobot/agent/tools/web.py`)
3. `git rebase upstream/main feat/mem0` — fix conflicts (scope: `memory.py`,
   `schema.py`, `context.py`, `loop.py`)
4. Rebuild `main` from those rebased branches: branch off `upstream/main`, then
   `git merge feat/exa-search && git merge feat/mem0`
5. Run the smoke tests in the "Verification" section below before treating the
   merge as done.

Use the `/upstream-merge` skill (`.claude/skills/upstream-merge/SKILL.md`) to
drive this process — it has the full step-by-step recipe and a conflict
checklist per file.

---

### 1. Exa Search Provider (`nanobot/agent/tools/web_exa.py`)

**Implemented as a zero-conflict plugin** — lives entirely in `web_exa.py`, a file
upstream never touches. No changes to `web.py` or `schema.py` are needed.

`XWebSearchTool` subclasses upstream's `WebSearchTool` and intercepts
`provider == "exa"` in `execute()`. The class name sorts after `WebSearchTool`
alphabetically so `ToolLoader` registers it last and it wins the `web_search` slot.
Startup logs one "Tool name collision" warning — expected and harmless.

**API key resolution order:**
1. `EXA_API_KEY` environment variable
2. `tools.web.search.exaApiKey` in `~/.nanobot/config.json` (read from raw JSON —
   `WebSearchConfig` intentionally does not carry this field, to keep this
   feature a zero-diff plugin against upstream's schema.py)
3. Falls back to DuckDuckGo if no key found

**After any upstream merge:** `web_exa.py` requires no changes. Just verify
`WebSearchTool.execute()` and `_format_results` are still importable from `web.py`.

---

### 2. Mem0 Semantic Memory (`nanobot/agent/memory.py`, `nanobot/config/schema.py`,
`nanobot/agent/context.py`, `nanobot/agent/loop.py`)

Upstream has no mem0 integration (removed in an earlier upstream refactor). Must
be re-applied after each merge that touches these files.

**What to preserve in `memory.py`:**
- `MemoryStore.__init__` accepts `mem0_config` param and stores `self._mem0_config` / `self._mem0`
- `_get_mem0()`, `_build_mem0_config()`, `consolidate_via_mem0()` methods on `MemoryStore`
- `Consolidator.archive()` calls `self.store.consolidate_via_mem0(messages)` first;
  if it returns `True`, short-circuit and return `"[mem0]"` instead of the LLM-summary path
- In `consolidate_via_mem0()`, strip trailing assistant messages before `mem0.add()`:
  ```python
  while chat_messages and chat_messages[-1]["role"] == "assistant":
      chat_messages.pop()
  ```
- Skip multimodal (non-string `content`) messages when building `chat_messages`

**What to preserve in `schema.py`:**
- `Mem0Config` class (llm/embedder provider, model, api_key, base_url, search_limit fields)
- `MemoryConfig` class with `mem0: Mem0Config` field
- `memory: MemoryConfig` field on `AgentDefaults`

**Wiring:**
- `nanobot/agent/context.py`: `ContextBuilder.__init__` takes `mem0_config=None` and
  passes it through to `MemoryStore(workspace, mem0_config=mem0_config)`
- `nanobot/agent/loop.py`: `AgentLoop.__init__` takes `mem0_config=None` and passes it
  to `ContextBuilder(...)`; `AgentLoop.from_config()` passes `mem0_config=defaults.memory.mem0`

Note: `search_limit` on `Mem0Config` and query-based semantic recall
(`mem0.search()` wired into `get_memory_context()`) are **not implemented** —
mem0 is currently write-only (fact extraction on consolidation), not read back
into context. Don't assume that wiring exists without checking.

There is no `mem0` extra in `pyproject.toml` — `mem0ai` is an ad-hoc
`pip install` the user runs manually; `_get_mem0()` logs a warning with the
install command if it's missing.

---

### 3. Telegram Duplicate Message Fix — OBSOLETE, do not re-apply

Upstream rewrote the Telegram streaming system some time ago. The
`send_message_draft()` draft-simulation fix no longer applies to the current
codebase.

---

### Verification

After rebuilding `main`, run:

```bash
python3 -c "
from nanobot.agent.tools.web_exa import XWebSearchTool
from nanobot.agent.tools.web import WebSearchTool, _format_results
print('Exa OK:', sorted(['WebSearchTool','XWebSearchTool'])[-1] == 'XWebSearchTool')
"
python3 -c "
from nanobot.agent.memory import MemoryStore
from nanobot.agent.loop import AgentLoop
import inspect
print('Mem0 methods OK:', all(h in dir(MemoryStore) for h in ('_get_mem0','_build_mem0_config','consolidate_via_mem0')))
print('AgentLoop wiring OK:', 'mem0_config' in inspect.signature(AgentLoop.__init__).parameters)
"
```

### Active Config

- **Main LLM model**: `deepseek/deepseek-v4-flash-0731` (via OpenRouter) — set in `~/.nanobot/config.json`
- **Search provider**: `exa` with key stored in `EXA_API_KEY` env var or
  `tools.web.search.exaApiKey` in config
- **Memory**: mem0 enabled, using `openai/gpt-4o-mini` + `text-embedding-3-small` via OpenRouter
