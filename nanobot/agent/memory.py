"""Memory system for persistent agent memory."""

from __future__ import annotations

import asyncio
import json
import os
import weakref
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from nanobot.utils.helpers import ensure_dir, estimate_message_tokens, estimate_prompt_tokens_chain

if TYPE_CHECKING:
    from nanobot.config.schema import Mem0Config
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session, SessionManager


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
                        "description": "A paragraph summarizing key events/decisions/topics. "
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


def _ensure_text(value: Any) -> str:
    """Normalize tool-call payload values to text for file storage."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _normalize_save_memory_args(args: Any) -> dict[str, Any] | None:
    """Normalize provider tool-call arguments to the expected dict shape."""
    if isinstance(args, str):
        args = json.loads(args)
    if isinstance(args, list):
        return args[0] if args and isinstance(args[0], dict) else None
    return args if isinstance(args, dict) else None

_TOOL_CHOICE_ERROR_MARKERS = (
    "tool_choice",
    "toolchoice",
    "does not support",
    'should be ["none", "auto"]',
)


def _is_tool_choice_unsupported(content: str | None) -> bool:
    """Detect provider errors caused by forced tool_choice being unsupported."""
    text = (content or "").lower()
    return any(m in text for m in _TOOL_CHOICE_ERROR_MARKERS)


class MemoryStore:
    """Two-layer memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log).

    When mem0_config.enabled is True, conversation facts are automatically extracted
    and stored in a local ChromaDB via Mem0, and retrieved semantically per query.
    MEMORY.md is kept for manually-pinned facts written directly by the agent.
    HISTORY.md is always maintained as a grep-searchable timestamped log.
    """

    _MAX_FAILURES_BEFORE_RAW_ARCHIVE = 3

    def __init__(self, workspace: Path, mem0_config: "Mem0Config | None" = None):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self._mem0_config = mem0_config
        self._mem0 = None  # lazy-initialized
        self._consecutive_failures = 0

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

    @staticmethod
    def _format_messages(messages: list[dict]) -> str:
        lines = []
        for message in messages:
            if not message.get("content"):
                continue
            tools = f" [tools: {', '.join(message['tools_used'])}]" if message.get("tools_used") else ""
            lines.append(
                f"[{message.get('timestamp', '?')[:16]}] {message['role'].upper()}{tools}: {message['content']}"
            )
        return "\n".join(lines)

    async def consolidate(
        self,
        messages: list[dict],
        provider: "LLMProvider",
        model: str,
    ) -> bool:
        """Consolidate the provided message chunk into MEMORY.md + HISTORY.md.

        With Mem0: extracts structured facts into ChromaDB + appends HISTORY.md.
        Without Mem0: LLM-based MEMORY.md + HISTORY.md approach.
        Returns True on success (including no-op), False on failure.
        """
        if not messages:
            return True

        mem0 = self._get_mem0()
        if mem0:
            return await self._consolidate_mem0(mem0, messages)
        return await self._consolidate_llm(messages, provider, model)

    # ── Consolidation backends ──────────────────────────────────────────────────

    async def _consolidate_mem0(self, mem0, messages: list) -> bool:
        """Mem0 path: extract facts into ChromaDB and append a log entry to HISTORY.md."""
        chat_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
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
        self._append_history_summary(messages)
        logger.info("Mem0 consolidation done for {} messages", len(messages))
        return True

    async def _consolidate_llm(
        self,
        messages: list,
        provider: "LLMProvider",
        model: str,
    ) -> bool:
        """LLM path: summarize into MEMORY.md + HISTORY.md via tool call."""
        current_memory = self.read_long_term()
        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{self._format_messages(messages)}"""

        chat_messages = [
            {"role": "system", "content": "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation."},
            {"role": "user", "content": prompt},
        ]

        try:
            forced = {"type": "function", "function": {"name": "save_memory"}}
            response = await provider.chat_with_retry(
                messages=chat_messages,
                tools=_SAVE_MEMORY_TOOL,
                model=model,
                tool_choice=forced,
            )

            if response.finish_reason == "error" and _is_tool_choice_unsupported(
                response.content
            ):
                logger.warning("Forced tool_choice unsupported, retrying with auto")
                response = await provider.chat_with_retry(
                    messages=chat_messages,
                    tools=_SAVE_MEMORY_TOOL,
                    model=model,
                    tool_choice="auto",
                )

            if not response.has_tool_calls:
                logger.warning(
                    "Memory consolidation: LLM did not call save_memory "
                    "(finish_reason={}, content_len={}, content_preview={})",
                    response.finish_reason,
                    len(response.content or ""),
                    (response.content or "")[:200],
                )
                return self._fail_or_raw_archive(messages)

            args = _normalize_save_memory_args(response.tool_calls[0].arguments)
            if args is None:
                logger.warning("Memory consolidation: unexpected save_memory arguments")
                return self._fail_or_raw_archive(messages)

            if "history_entry" not in args or "memory_update" not in args:
                logger.warning("Memory consolidation: save_memory payload missing required fields")
                return self._fail_or_raw_archive(messages)

            entry = args["history_entry"]
            update = args["memory_update"]

            if entry is None or update is None:
                logger.warning("Memory consolidation: save_memory payload contains null required fields")
                return self._fail_or_raw_archive(messages)

            entry = _ensure_text(entry).strip()
            if not entry:
                logger.warning("Memory consolidation: history_entry is empty after normalization")
                return self._fail_or_raw_archive(messages)

            self.append_history(entry)
            update = _ensure_text(update)
            if update != current_memory:
                self.write_long_term(update)

            self._consecutive_failures = 0
            logger.info("Memory consolidation done for {} messages", len(messages))
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return self._fail_or_raw_archive(messages)

    def _fail_or_raw_archive(self, messages: list[dict]) -> bool:
        """Increment failure count; after threshold, raw-archive messages and return True."""
        self._consecutive_failures += 1
        if self._consecutive_failures < self._MAX_FAILURES_BEFORE_RAW_ARCHIVE:
            return False
        self._raw_archive(messages)
        self._consecutive_failures = 0
        return True

    def _raw_archive(self, messages: list[dict]) -> None:
        """Fallback: dump raw messages to HISTORY.md without LLM summarization."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.append_history(
            f"[{ts}] [RAW] {len(messages)} messages\n"
            f"{self._format_messages(messages)}"
        )
        logger.warning(
            "Memory consolidation degraded: raw-archived {} messages", len(messages)
        )

    def _append_history_summary(self, messages: list) -> None:
        """Append a brief timestamped entry to HISTORY.md from a list of messages."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        snippets = [
            m["content"][:80]
            for m in messages
            if m.get("role") == "user" and isinstance(m.get("content"), str) and m["content"]
        ]
        topics = "; ".join(snippets[:3])
        entry = f"[{ts}] Processed {len(messages)} messages. User topics: {topics}"
        self.append_history(entry)


class MemoryConsolidator:
    """Owns consolidation policy, locking, and session offset updates."""

    _MAX_CONSOLIDATION_ROUNDS = 5

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        sessions: SessionManager,
        context_window_tokens: int,
        build_messages: Callable[..., list[dict[str, Any]]],
        get_tool_definitions: Callable[[], list[dict[str, Any]]],
        mem0_config: "Mem0Config | None" = None,
    ):
        self.store = MemoryStore(workspace, mem0_config=mem0_config)
        self.provider = provider
        self.model = model
        self.sessions = sessions
        self.context_window_tokens = context_window_tokens
        self._build_messages = build_messages
        self._get_tool_definitions = get_tool_definitions
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    def get_lock(self, session_key: str) -> asyncio.Lock:
        """Return the shared consolidation lock for one session."""
        return self._locks.setdefault(session_key, asyncio.Lock())

    async def consolidate_messages(self, messages: list[dict[str, object]]) -> bool:
        """Archive a selected message chunk into persistent memory."""
        return await self.store.consolidate(messages, self.provider, self.model)

    def pick_consolidation_boundary(
        self,
        session: Session,
        tokens_to_remove: int,
    ) -> tuple[int, int] | None:
        """Pick a user-turn boundary that removes enough old prompt tokens."""
        start = session.last_consolidated
        if start >= len(session.messages) or tokens_to_remove <= 0:
            return None

        removed_tokens = 0
        last_boundary: tuple[int, int] | None = None
        for idx in range(start, len(session.messages)):
            message = session.messages[idx]
            if idx > start and message.get("role") == "user":
                last_boundary = (idx, removed_tokens)
                if removed_tokens >= tokens_to_remove:
                    return last_boundary
            removed_tokens += estimate_message_tokens(message)

        return last_boundary

    def estimate_session_prompt_tokens(self, session: Session) -> tuple[int, str]:
        """Estimate current prompt size for the normal session history view."""
        history = session.get_history(max_messages=0)
        channel, chat_id = (session.key.split(":", 1) if ":" in session.key else (None, None))
        probe_messages = self._build_messages(
            history=history,
            current_message="[token-probe]",
            channel=channel,
            chat_id=chat_id,
        )
        return estimate_prompt_tokens_chain(
            self.provider,
            self.model,
            probe_messages,
            self._get_tool_definitions(),
        )

    async def archive_messages(self, messages: list[dict[str, object]]) -> bool:
        """Archive messages with guaranteed persistence (retries until raw-dump fallback)."""
        if not messages:
            return True
        for _ in range(self.store._MAX_FAILURES_BEFORE_RAW_ARCHIVE):
            if await self.consolidate_messages(messages):
                return True
        return True

    async def maybe_consolidate_by_tokens(self, session: Session) -> None:
        """Loop: archive old messages until prompt fits within half the context window."""
        if not session.messages or self.context_window_tokens <= 0:
            return

        lock = self.get_lock(session.key)
        async with lock:
            target = self.context_window_tokens // 2
            estimated, source = self.estimate_session_prompt_tokens(session)
            if estimated <= 0:
                return
            if estimated < self.context_window_tokens:
                logger.debug(
                    "Token consolidation idle {}: {}/{} via {}",
                    session.key,
                    estimated,
                    self.context_window_tokens,
                    source,
                )
                return

            for round_num in range(self._MAX_CONSOLIDATION_ROUNDS):
                if estimated <= target:
                    return

                boundary = self.pick_consolidation_boundary(session, max(1, estimated - target))
                if boundary is None:
                    logger.debug(
                        "Token consolidation: no safe boundary for {} (round {})",
                        session.key,
                        round_num,
                    )
                    return

                end_idx = boundary[0]
                chunk = session.messages[session.last_consolidated:end_idx]
                if not chunk:
                    return

                logger.info(
                    "Token consolidation round {} for {}: {}/{} via {}, chunk={} msgs",
                    round_num,
                    session.key,
                    estimated,
                    self.context_window_tokens,
                    source,
                    len(chunk),
                )
                if not await self.consolidate_messages(chunk):
                    return
                session.last_consolidated = end_idx
                self.sessions.save(session)

                estimated, source = self.estimate_session_prompt_tokens(session)
                if estimated <= 0:
                    return
