"""Exa API-key shim — lets upstream's native Exa provider read ``exaApiKey``.

Upstream ``WebSearchTool`` supports ``provider = "exa"`` natively, but only reads
the key from ``tools.web.search.apiKey`` or the ``EXA_API_KEY`` env var. This
fork's config stores it as ``tools.web.search.exaApiKey`` (a field upstream's
schema doesn't carry), so this subclass injects that key into the search config
and otherwise defers entirely to upstream's implementation.

ToolLoader discovers every module in nanobot/agent/tools/ and sorts tool classes
alphabetically by class name before registering them. This class (XWebSearchTool)
sorts after WebSearchTool (X > W), so it overwrites the built-in web_search
registration and becomes the active tool. Startup logs one "Tool name collision"
warning — expected and harmless.

Key resolution order (first non-empty wins):
  1. tools.web.search.apiKey in config.json   (upstream, used as-is)
  2. EXA_API_KEY environment variable
  3. tools.web.search.exaApiKey in config.json (read from the raw JSON file)
  4. none → upstream falls back to DuckDuckGo
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from nanobot.agent.tools.web import WebSearchTool


def _load_exa_api_key() -> str:
    """Read the Exa key from env or config.json's exaApiKey (absent from upstream schema)."""
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
    """Upstream WebSearchTool plus ``exaApiKey`` resolution for the exa provider."""

    _scopes = {"core", "subagent"}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._inject_exa_key()

    def _refresh_config(self) -> None:
        super()._refresh_config()
        self._inject_exa_key()

    def _inject_exa_key(self) -> None:
        if self.config.provider.strip().lower() != "exa" or self.config.api_key:
            return
        key = _load_exa_api_key()
        if key:
            # Copy so the shared config object (which may be saved back to disk) is untouched.
            self.config = self.config.model_copy(update={"api_key": key})
