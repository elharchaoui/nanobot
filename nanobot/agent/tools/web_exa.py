"""Exa neural search — plugs into WebSearchTool with zero upstream-file changes.

ToolLoader discovers every module in nanobot/agent/tools/ and sorts tool classes
alphabetically by class name before registering them. This class (XWebSearchTool)
sorts after WebSearchTool (X > W), so it overwrites the built-in web_search
registration and becomes the active tool. Startup logs one "Tool name collision"
warning — expected and harmless.

Config: set tools.web.search.provider = "exa" in ~/.nanobot/config.json and
supply the API key via EITHER:
  • tools.web.search.exaApiKey in config.json  (upstream schema doesn't carry this
    field, so it's read directly from the raw JSON file at startup)
  • EXA_API_KEY environment variable
  • tools.web.search.apiKey in config.json     (shared api_key field)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.web import WebSearchTool, _format_results


def _load_exa_api_key() -> str:
    """Read exaApiKey from config.json — field absent from upstream WebSearchConfig."""
    key = os.environ.get("EXA_API_KEY", "")
    if key:
        return key
    try:
        raw = json.loads((Path.home() / ".nanobot" / "config.json").read_text())
        return (
            raw.get("tools", {}).get("web", {}).get("search", {}).get("exaApiKey", "")
            or raw.get("exaApiKey", "")
            or ""
        )
    except Exception:
        return ""


class XWebSearchTool(WebSearchTool):
    """WebSearchTool extended with Exa neural search.

    Inherits all upstream providers (brave, tavily, duckduckgo, …) and adds
    exa.  Overrides execute() to intercept provider == "exa" before the
    upstream dispatch, then delegates everything else to super().
    """

    _scopes = {"core", "subagent"}

    def __init__(self, *, exa_api_key: str = "", **kwargs: Any) -> None:
        self._exa_api_key = exa_api_key
        super().__init__(**kwargs)

    @classmethod
    def create(cls, ctx: Any) -> "XWebSearchTool":
        config_loader = None
        if ctx.provider_snapshot_loader is not None:
            def config_loader():
                from nanobot.config.loader import load_config, resolve_config_env_vars
                return resolve_config_env_vars(load_config()).tools.web.search
        return cls(
            config=ctx.config.web.search,
            proxy=ctx.config.web.proxy,
            user_agent=ctx.config.web.user_agent,
            config_loader=config_loader,
            exa_api_key=_load_exa_api_key(),
        )

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        self._refresh_config()
        provider = self.config.provider.strip().lower() or "brave"
        if provider == "exa":
            n = min(max(count or self.config.max_results, 1), 10)
            return await self._search_exa(query, n)
        return await super().execute(query=query, count=count, **kwargs)

    async def _search_exa(self, query: str, n: int) -> str:
        api_key = (
            self._exa_api_key
            or self.config.api_key
            or os.environ.get("EXA_API_KEY", "")
        )
        if not api_key:
            logger.warning("EXA_API_KEY not set, falling back to DuckDuckGo")
            return await self._search_duckduckgo(query, n)
        try:
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.post(
                    "https://api.exa.ai/search",
                    headers={"x-api-key": api_key, "Content-Type": "application/json"},
                    json={
                        "query": query,
                        "numResults": n,
                        "type": "neural",
                        "contents": {"text": {"maxCharacters": 1000}},
                    },
                    timeout=15.0,
                )
                r.raise_for_status()
            items = [
                {
                    "title": x.get("title", ""),
                    "url": x.get("url", ""),
                    "content": x.get("text") or x.get("snippet") or "",
                }
                for x in r.json().get("results", [])
            ]
            return _format_results(query, items, n)
        except Exception as e:
            logger.warning("Exa search failed: {}", e)
            return f"Error: Exa search failed ({e})"
