---
name: upstream-merge
description: >
  Merge upstream HKUDS/nanobot changes into this fork while preserving custom
  features (Exa search plugin, Mem0 memory). Use whenever the user asks to pull
  upstream, sync with upstream, merge new upstream releases, or update the fork.
---

# Upstream Merge — nanobot Fork

This fork (elharchaoui/nanobot) tracks HKUDS/nanobot upstream. Two custom features
must survive every merge:

| Feature | Location | Strategy |
|---|---|---|
| Exa search provider | `nanobot/agent/tools/web_exa.py` | **Plugin file** — zero conflicts, upstream never touches it |
| Mem0 ChromaDB memory | `nanobot/agent/memory.py` + `schema.py` | **Topic branch** — rebase `feat/mem0` onto new upstream |

---

## Step 0 — Check what's new upstream

```bash
git fetch upstream
git log main..upstream/main --oneline | head -30          # commits we're missing
git log main..upstream/main --oneline | grep "^.*feat"    # features only
git tag --sort=-version:refname | head -5                 # latest releases
```

---

## Step 1 — Verify topic branches exist

```bash
git branch -a | grep feat/
```

Expected: `feat/exa-search` and `feat/mem0`. If missing, rebuild them:

### Rebuild feat/exa-search (if lost)

```bash
git checkout -b feat/exa-search upstream/main
# web_exa.py is the plugin — it lives in main already, just copy it over
git checkout main -- nanobot/agent/tools/web_exa.py
git commit -m "feat(search): add Exa search provider plugin (web_exa.py)"
```

### Rebuild feat/mem0 (if lost)

Cherry-pick the Mem0 commits from main, taking only memory-related files:

```bash
git checkout -b feat/mem0 upstream/main

# Commit 1 — initial integration (skip loop.py and commands.py wiring)
git cherry-pick -n 6ef94c48
git restore --staged .
git add nanobot/agent/memory.py nanobot/config/schema.py nanobot/agent/context.py pyproject.toml
git commit -m "feat(memory): integrate Mem0 semantic memory backend"

# Commits 2–6 — single-file fixes (take whole)
git cherry-pick 0d04e537   # handle dict return from mem0.search()
git cherry-pick 9d93f0e5   # log search results
git cherry-pick 3d06ba11   # OpenRouter path
git cherry-pick 7ce486cb   # skip multimodal in mem0.add()
git cherry-pick e1f156f4   # skip multimodal in _append_history_summary

# Commit 7 — trailing assistant fix (skip skills/docs noise)
git cherry-pick -n d91ae12c
git restore --staged .
git add nanobot/agent/memory.py
git commit -m "fix(memory): strip trailing assistant messages before mem0 consolidation"

# Commit 8 — ChromaDB integration (skip telegram.py)
git cherry-pick -n 9b87939f
git restore --staged .
git add nanobot/agent/memory.py nanobot/config/schema.py nanobot/agent/context.py
git commit -m "feat(memory): add Mem0 ChromaDB integration with config schema"
```

---

## Step 2 — Rebase each feature branch

```bash
git rebase upstream/main feat/exa-search
# Conflicts expected in: web_exa.py imports (if web.py was renamed/refactored)
# Resolution: ensure WebSearchTool and _format_results are still importable from web.py

git rebase upstream/main feat/mem0
# Conflicts expected in: memory.py (constructor), schema.py (Mem0Config removed upstream)
# Resolution: keep upstream's base + re-add Mem0 additions on top
```

### Mem0 conflict checklist (schema.py)

Re-add after taking upstream's version:
```python
class Mem0Config(Base):
    enabled: bool = False
    llm_provider: str = "openai"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    embedder_provider: str = "openai"
    embedder_model: str = "text-embedding-3-small"
    embedder_api_key: str = ""
    embedder_base_url: str = ""
    search_limit: int = 10

class MemoryConfig(Base):
    mem0: Mem0Config = Field(default_factory=Mem0Config)
```
And add `memory: MemoryConfig = Field(default_factory=MemoryConfig)` to `AgentDefaults`.

### Mem0 conflict checklist (memory.py)

Re-add after taking upstream's version:
- `mem0_config` param in `MemoryStore.__init__` + `self._mem0_config` / `self._mem0 = None`
- `_get_mem0()` lazy-init method
- `_build_mem0_config()` — builds the dict for `Memory.from_config()`; when `llm_base_url`
  contains "openrouter", set `OPENROUTER_API_KEY` env var and use `openrouter_base_url` key
- `consolidate_via_mem0()` — with trailing-assistant-message strip:
  ```python
  while chat_messages and chat_messages[-1]["role"] == "assistant":
      chat_messages.pop()
  ```
- Skip non-string (multimodal) messages when building `chat_messages`

### Mem0 conflict checklist (context.py)

Re-add: pass `query` string into `MemoryStore.get_memory_context(query)` so semantic
recall works on each incoming message.

---

## Step 3 — Rebuild main

```bash
git checkout -b main-$(git describe --tags upstream/main | head -1) upstream/main

git merge feat/exa-search   # should be clean — web_exa.py is a new file
git merge feat/mem0         # fix any remaining conflicts

# Quick smoke test
python3 -c "from nanobot.agent.tools.web_exa import XWebSearchTool; print('Exa OK:', XWebSearchTool.name)"
python3 -c "from nanobot.agent.memory import MemoryStore; import inspect; print('Mem0 OK:', 'consolidate_via_mem0' in dir(MemoryStore))"

# Point main to the new integration branch
git branch -f main HEAD
git checkout main
```

---

## Step 4 — Verify Exa plugin health

The Exa plugin (`web_exa.py`) should never need changes after a merge **unless**
upstream renames or refactors `web.py`. Check:

```bash
python3 -c "
from nanobot.agent.tools.web_exa import XWebSearchTool, _load_exa_api_key
from nanobot.agent.tools.web import WebSearchTool, _format_results
print('Imports OK')
print('XWebSearchTool sorts after WebSearchTool:', sorted(['WebSearchTool','XWebSearchTool'])[-1] == 'XWebSearchTool')
"
```

If `_format_results` is renamed upstream, update the import in `web_exa.py` and add
a note to CLAUDE.md.

---

## Step 5 — Update CLAUDE.md

After a successful merge, update the commit hashes in CLAUDE.md Section 2
(Mem0 cherry-pick list) if any of the base commits were re-created during rebase
with new hashes.

---

## Notes

- **Telegram duplicate fix**: obsolete since v0.2.0. Upstream rewrote streaming. Do NOT re-apply.
- **Discord filtering** and **SSE streaming**: upstreamed in v0.2.0. No action needed.
- **web_exa.py class name `XWebSearchTool`**: the X prefix is intentional — it must sort after `WebSearchTool` alphabetically so `ToolLoader` registers it last and it wins the `web_search` slot.
- Startup log: `Tool name collision: web_search from WebSearchTool overwrites existing` — this is expected and harmless.
