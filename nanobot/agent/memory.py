"""Memory system for persistent agent memory."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.config.schema import Mem0Config
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


_MEM0_USER = "owner"

_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


class MemoryStore:
    """Two-layer memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log).

    When mem0_config.enabled is True, conversation facts are automatically extracted
    and stored in a local ChromaDB via Mem0, and retrieved semantically per query.
    MEMORY.md is kept for manually-pinned facts written directly by the agent.
    HISTORY.md is always maintained as a grep-searchable timestamped log.
    """

    def __init__(self, workspace: Path, mem0_config: "Mem0Config | None" = None):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self._mem0_config = mem0_config
        self._mem0 = None  # lazy-initialized

    # ── Mem0 helpers ────────────────────────────────────────────────────────────

    def _get_mem0(self):
        """Lazy-initialize and return the Mem0 client, or None if disabled/unavailable."""
        if self._mem0 is not None:
            return self._mem0
        if not self._mem0_config or not self._mem0_config.enabled:
            return None
        try:
            from mem0 import Memory  # type: ignore[import]
            cfg = self._build_mem0_config()
            # Trigger Mem0's native OpenRouter path so calls appear in the dashboard
            c = self._mem0_config
            if c.llm_api_key and c.llm_base_url and "openrouter" in c.llm_base_url.lower():
                os.environ.setdefault("OPENROUTER_API_KEY", c.llm_api_key)
            self._mem0 = Memory.from_config(cfg)
            logger.info("Mem0 initialized (chroma at {})", self.memory_dir / "chroma")
            return self._mem0
        except ImportError:
            logger.warning("mem0ai is not installed — run: pip install 'nanobot-ai[mem0]'")
            return None
        except Exception:
            logger.exception("Mem0 initialization failed")
            return None

    def _build_mem0_config(self) -> dict:
        c = self._mem0_config
        cfg: dict = {
            "vector_store": {
                "provider": "chroma",
                "config": {
                    "collection_name": "nanobot_memories",
                    "path": str(self.memory_dir / "chroma"),
                },
            }
        }
        if c.llm_provider:
            llm_cfg: dict = {}
            if c.llm_model:
                llm_cfg["model"] = c.llm_model
            if c.llm_api_key:
                llm_cfg["api_key"] = c.llm_api_key
            if c.llm_base_url:
                key = "openrouter_base_url" if "openrouter" in c.llm_base_url.lower() else "openai_base_url"
                llm_cfg[key] = c.llm_base_url
            cfg["llm"] = {"provider": c.llm_provider, "config": llm_cfg}
        if c.embedder_provider:
            emb_cfg: dict = {}
            if c.embedder_model:
                emb_cfg["model"] = c.embedder_model
            if c.embedder_api_key:
                emb_cfg["api_key"] = c.embedder_api_key
            if c.embedder_base_url:
                emb_cfg["openai_base_url"] = c.embedder_base_url
            cfg["embedder"] = {"provider": c.embedder_provider, "config": emb_cfg}
        return cfg

    # ── Core API ─────────────────────────────────────────────────────────────────

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def get_memory_context(self, query: str = "") -> str:
        """Return memory context to inject into the system prompt.

        With Mem0: semantically searches for facts relevant to `query`, plus
        any manually-pinned content from MEMORY.md.
        Without Mem0: returns full MEMORY.md content (existing behaviour).
        """
        mem0 = self._get_mem0()
        parts = []

        # Manually-pinned facts are always included
        long_term = self.read_long_term()
        if long_term:
            label = "## Pinned Memory" if mem0 else "## Long-term Memory"
            parts.append(f"{label}\n{long_term}")

        # Semantic recall via Mem0
        if mem0 and query:
            try:
                raw = mem0.search(query, user_id=_MEM0_USER, limit=self._mem0_config.search_limit)
                # Mem0 returns {"results": [...]} in newer versions, plain list in older
                results = raw.get("results", raw) if isinstance(raw, dict) else raw
                facts = [r["memory"] for r in results if r.get("memory")]
                logger.info("Mem0 search: query={!r} → {} facts", query[:60], len(facts))
                if facts:
                    parts.append("## Recalled Memories\n" + "\n".join(f"- {f}" for f in facts))
            except Exception:
                logger.exception("Mem0 search failed, falling back to pinned memory only")

        return "\n\n".join(parts)

    async def consolidate(
        self,
        session: "Session",
        provider: "LLMProvider",
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
    ) -> bool:
        """Consolidate old messages into memory storage.

        With Mem0: extracts structured facts into ChromaDB + appends HISTORY.md.
        Without Mem0: existing LLM-based MEMORY.md + HISTORY.md approach.
        Returns True on success (including no-op), False on failure.
        """
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
        else:
            keep_count = memory_window // 2
            if len(session.messages) <= keep_count:
                return True
            if len(session.messages) - session.last_consolidated <= 0:
                return True
            old_messages = session.messages[session.last_consolidated:-keep_count]
            if not old_messages:
                return True
            logger.info("Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count)

        mem0 = self._get_mem0()
        if mem0:
            return await self._consolidate_mem0(session, mem0, old_messages, archive_all, keep_count)
        return await self._consolidate_llm(session, provider, model, old_messages, archive_all, keep_count)

    # ── Consolidation backends ──────────────────────────────────────────────────

    async def _consolidate_mem0(
        self, session: "Session", mem0, old_messages: list, archive_all: bool, keep_count: int
    ) -> bool:
        """Mem0 path: extract facts into ChromaDB and append a log entry to HISTORY.md."""
        chat_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in old_messages
            if isinstance(m.get("content"), str) and m["content"] and m.get("role") in ("user", "assistant")
        ]
        if chat_messages:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: mem0.add(chat_messages, user_id=_MEM0_USER),
                )
                logger.info("Mem0: extracted facts from {} messages", len(chat_messages))
            except Exception:
                logger.exception("Mem0 add failed")
                return False

        # Always keep the grep-searchable history log
        self._append_history_summary(old_messages)

        session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
        logger.info("Mem0 consolidation done: last_consolidated={}", session.last_consolidated)
        return True

    async def _consolidate_llm(
        self,
        session: "Session",
        provider: "LLMProvider",
        model: str,
        old_messages: list,
        archive_all: bool,
        keep_count: int,
    ) -> bool:
        """LLM path (original): summarize into MEMORY.md + HISTORY.md via tool call."""
        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")

        current_memory = self.read_long_term()
        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

        try:
            response = await provider.chat(
                messages=[
                    {"role": "system", "content": "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation."},
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = response.tool_calls[0].arguments
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict):
                logger.warning("Memory consolidation: unexpected arguments type {}", type(args).__name__)
                return False

            if entry := args.get("history_entry"):
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                self.append_history(entry)
            if update := args.get("memory_update"):
                if not isinstance(update, str):
                    update = json.dumps(update, ensure_ascii=False)
                if update != current_memory:
                    self.write_long_term(update)

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            logger.info(
                "Memory consolidation done: {} messages, last_consolidated={}",
                len(session.messages), session.last_consolidated,
            )
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False

    def _append_history_summary(self, messages: list) -> None:
        """Append a brief timestamped entry to HISTORY.md from a list of messages."""
        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        snippets = [
            m["content"][:80]
            for m in messages
            if m.get("role") == "user" and m.get("content")
        ]
        topics = "; ".join(snippets[:3])
        entry = f"[{ts}] Processed {len(messages)} messages. User topics: {topics}"
        self.append_history(entry)
