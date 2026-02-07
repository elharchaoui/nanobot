# nanobot Technical Documentation

## Executive Summary

**nanobot** is an ultra-lightweight personal AI assistant framework written in Python. Inspired by Clawdbot but designed to be 99% smaller (~4,000 lines vs 430,000+ lines), nanobot delivers core agent functionality with a minimal footprint, making it ideal for research, customization, and personal use.

**Key Metrics:**
- **Code Size:** ~4,000 lines of Python
- **Python Version:** ≥3.11
- **License:** MIT
- **Package Name:** `nanobot-ai` (PyPI)

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Core Components](#core-components)
3. [Agent System](#agent-system)
4. [Tool Framework](#tool-framework)
5. [Message Bus](#message-bus)
6. [Channel System](#channel-system)
7. [Configuration System](#configuration-system)
8. [Memory & Session Management](#memory--session-management)
9. [Scheduling & Heartbeat](#scheduling--heartbeat)
10. [Skills System](#skills-system)
11. [Subagent Architecture](#subagent-architecture)
12. [Deployment & Operations](#deployment--operations)

---

## System Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        nanobot System                           │
├─────────────────────────────────────────────────────────────────┤
│  Channels        │  Core Agent         │  Services             │
│  ─────────────   │  ────────────        │  ────────             │
│  • Telegram      │  • AgentLoop         │  • CronService        │
│  • WhatsApp      │  • ContextBuilder    │  • HeartbeatService   │
│  (extensible)    │  • MemoryStore       │                       │
│                  │  • SessionManager    │                       │
├──────────────────┴─────────────────────┴───────────────────────┤
│                      Message Bus (async Queue)                   │
├─────────────────────────────────────────────────────────────────┤
│  Tools: read_file │ write_file │ exec │ web_search │ web_fetch  │
│         edit_file │ list_dir   │ spawn │ message               │
├─────────────────────────────────────────────────────────────────┤
│  LLM Provider (LiteLLM): OpenRouter │ Anthropic │ OpenAI        │
└─────────────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Minimalism:** Every feature is essential; no bloat
2. **Modularity:** Components are loosely coupled via the message bus
3. **Extensibility:** Tools, channels, and skills are plugin-based
4. **Transparency:** All operations are visible and debuggable
5. **Research-Friendly:** Clean, readable code for easy modification

---

## Core Components

### 1. Agent Core (`nanobot/agent/`)

The agent core is the brain of nanobot, responsible for processing messages and orchestrating tool execution.

#### AgentLoop (`loop.py`)

The central processing engine that:
- Receives messages from the message bus
- Builds context with history, memory, and skills
- Orchestrates LLM calls and tool execution
- Manages the iteration loop (max 20 iterations by default)

```python
class AgentLoop:
    def __init__(self, bus, provider, workspace, model, max_iterations=20)
    async def run()  # Main event loop
    async def _process_message(msg)  # Single message processing
```

**Key Flow:**
1. Consume message from inbound queue
2. Load/create session for context
3. Build messages with system prompt + history
4. Call LLM with available tools
5. Execute tool calls (if any)
6. Repeat until no more tool calls or max iterations
7. Send response to outbound queue

#### ContextBuilder (`context.py`)

Assembles the system prompt and message context:

- **Identity:** Core assistant identity with timestamp and workspace info
- **Bootstrap Files:** `AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `IDENTITY.md`
- **Memory:** Long-term (`MEMORY.md`) and daily notes (`YYYY-MM-DD.md`)
- **Skills:** Progressive loading (always-loaded + available skills)

```python
class ContextBuilder:
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    
    def build_system_prompt(skill_names=None) -> str
    def build_messages(history, current_message, skill_names=None) -> list[dict]
```

#### MemoryStore (`memory.py`)

Persistent memory system with two tiers:

- **Daily Notes:** `memory/YYYY-MM-DD.md` - Short-term, session-based memory
- **Long-term Memory:** `memory/MEMORY.md` - Important facts that persist

```python
class MemoryStore:
    def get_today_file() -> Path
    def read_today() -> str
    def append_today(content)
    def read_long_term() -> str
    def write_long_term(content)
    def get_recent_memories(days=7) -> str
```

#### SkillsLoader (`skills.py`)

Dynamic skill loading with progressive disclosure:

- **Workspace Skills:** User-defined in `~/.nanobot/workspace/skills/`
- **Built-in Skills:** Package-provided in `nanobot/skills/`
- **Metadata:** YAML frontmatter with requirements, descriptions, icons
- **Progressive Loading:** Always-loaded skills in context, others referenced

```python
class SkillsLoader:
    def list_skills(filter_unavailable=True) -> list[dict]
    def load_skill(name) -> str | None
    def build_skills_summary() -> str  # XML format for agent
    def get_always_skills() -> list[str]
```

#### SubagentManager (`subagent.py`)

Background task execution system:

- Spawns isolated agent instances for complex tasks
- Limited tool set (no message tool, no spawn tool)
- Async execution with result announcement
- Result routing back to originating channel

```python
class SubagentManager:
    async def spawn(task, label=None, origin_channel, origin_chat_id) -> str
    async def _run_subagent(task_id, task, label, origin)
    async def _announce_result(task_id, label, task, result, origin, status)
```

---

## Tool Framework

### Base Tool Class (`tools/base.py`)

All tools inherit from the abstract `Tool` class:

```python
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str                    # Tool identifier
    
    @property  
    @abstractmethod
    def description(self) -> str             # What it does
    
    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]   # JSON Schema
    
    @abstractmethod
    async def execute(self, **kwargs) -> str # Execution logic
    
    def to_schema(self) -> dict[str, Any]    # OpenAI format
```

### Tool Registry (`tools/registry.py`)

Central tool management:

```python
class ToolRegistry:
    def register(tool: Tool)
    def unregister(name: str)
    def get(name: str) -> Tool | None
    def get_definitions() -> list[dict]  # For LLM
    async def execute(name, params) -> str
```

### Built-in Tools

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `read_file` | Read file contents | `path` |
| `write_file` | Write/create files | `path`, `content` |
| `edit_file` | Find/replace editing | `path`, `old_text`, `new_text` |
| `list_dir` | Directory listing | `path` |
| `exec` | Shell command execution | `command`, `working_dir` |
| `web_search` | Brave Search API | `query`, `count` |
| `web_fetch` | URL content extraction | `url`, `extractMode` |
| `message` | Send messages to channels | `content`, `channel`, `chat_id` |
| `spawn` | Create background subagent | `task`, `label` |

---

## Message Bus

### Architecture (`bus/`)

The message bus provides decoupled communication between channels and the agent:

```
┌──────────┐     ┌──────────────┐     ┌───────────┐
│ Telegram │────→│              │     │           │
├──────────┤     │   Inbound    │────→│  Agent    │
│ WhatsApp │────→│   Queue      │     │  Loop     │
├──────────┤     │              │     │           │
│   CLI    │────→│              │     │           │
└──────────┘     └──────────────┘     └─────┬─────┘
                                            │
┌──────────┐     ┌──────────────┐     ┌─────┴─────┐
│ Telegram │←────│              │←────│           │
├──────────┤     │   Outbound   │     │  Response │
│ WhatsApp │←────│   Queue      │     │  Handler  │
└──────────┘     └──────────────┘     └───────────┘
```

### Event Types (`bus/events.py`)

```python
@dataclass
class InboundMessage:
    channel: str        # telegram, whatsapp, cli, system
    sender_id: str      # User identifier
    chat_id: str        # Chat/channel identifier
    content: str        # Message text
    timestamp: datetime
    media: list[str]    # Media file paths
    metadata: dict      # Channel-specific data

@dataclass  
class OutboundMessage:
    channel: str
    chat_id: str
    content: str
    reply_to: str | None
    media: list[str]
    metadata: dict
```

### MessageBus (`bus/queue.py`)

```python
class MessageBus:
    async def publish_inbound(msg: InboundMessage)
    async def consume_inbound() -> InboundMessage
    async def publish_outbound(msg: OutboundMessage)
    async def consume_outbound() -> OutboundMessage
    def subscribe_outbound(channel, callback)
    async def dispatch_outbound()
```

---

## Channel System

### BaseChannel (`channels/base.py`)

Abstract interface for all chat channels:

```python
class BaseChannel(ABC):
    name: str
    
    @abstractmethod
    async def start()  # Begin listening
    
    @abstractmethod
    async def stop()   # Cleanup
    
    @abstractmethod
    async def send(msg: OutboundMessage)  # Send message
    
    def is_allowed(sender_id) -> bool  # ACL check
    async def _handle_message(sender_id, chat_id, content, media, metadata)
```

### Telegram Channel (`channels/telegram.py`)

- **Library:** `python-telegram-bot`
- **Mode:** Long polling (no webhook/public IP needed)
- **Features:** Text, photos, voice, audio, documents
- **Formatting:** Markdown → Telegram HTML conversion
- **Media:** Downloaded to `~/.nanobot/media/`

```python
class TelegramChannel(BaseChannel):
    name = "telegram"
    
    async def start()  # Start polling
    async def stop()   # Stop polling
    async def send(msg)  # Send with HTML parsing
```

### WhatsApp Channel (`channels/whatsapp.py`)

- **Bridge:** Node.js + `@whiskeysockets/baileys`
- **Protocol:** WhatsApp Web multi-device
- **Communication:** WebSocket (`ws://localhost:3001`)
- **Auth:** QR code scan for initial pairing

```python
class WhatsAppChannel(BaseChannel):
    name = "whatsapp"
    
    async def start()  # Connect to bridge WebSocket
    async def stop()   # Disconnect
    async def send(msg)  # Send via WebSocket
```

### WhatsApp Bridge (`bridge/`)

TypeScript Node.js application:

```
bridge/
├── src/
│   ├── index.ts      # Entry point
│   ├── server.ts     # WebSocket server
│   └── whatsapp.ts   # Baileys client
├── package.json
└── tsconfig.json
```

**Dependencies:**
- `@whiskeysockets/baileys`: WhatsApp Web protocol
- `ws`: WebSocket server
- `qrcode-terminal`: QR display

---

## Configuration System

### Schema (`config/schema.py`)

Pydantic-based configuration with nested models:

```python
class Config(BaseSettings):
    agents: AgentsConfig
    channels: ChannelsConfig
    providers: ProvidersConfig
    gateway: GatewayConfig
    tools: ToolsConfig
    
    def get_api_key() -> str | None
    def get_api_base() -> str | None
```

### Configuration Structure

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192,
      "temperature": 0.7,
      "maxToolIterations": 20
    }
  },
  "providers": {
    "openrouter": { "apiKey": "sk-or-...", "apiBase": "..." },
    "anthropic": { "apiKey": "..." },
    "openai": { "apiKey": "..." }
  },
  "channels": {
    "telegram": { "enabled": true, "token": "...", "allowFrom": [] },
    "whatsapp": { "enabled": false, "bridgeUrl": "ws://localhost:3001" }
  },
  "tools": {
    "web": { "search": { "apiKey": "BSA-...", "maxResults": 5 } }
  }
}
```

### Loader (`config/loader.py`)

- **Path:** `~/.nanobot/config.json`
- **Format:** CamelCase in JSON, snake_case in Python
- **Environment:** `NANOBOT_*` prefix support

---

## Memory & Session Management

### Session Manager (`session/manager.py`)

JSONL-based conversation persistence:

```python
class SessionManager:
    def get_or_create(key: str) -> Session
    def save(session: Session)
    def delete(key: str) -> bool
    def list_sessions() -> list[dict]
```

**Storage Format:** `~/.nanobot/sessions/{channel_chat_id}.jsonl`

```jsonl
{"_type": "metadata", "created_at": "...", "updated_at": "..."}
{"role": "user", "content": "...", "timestamp": "..."}
{"role": "assistant", "content": "...", "timestamp": "..."}
```

### Session (`session/manager.py`)

```python
@dataclass
class Session:
    key: str                    # channel:chat_id
    messages: list[dict]
    created_at: datetime
    updated_at: datetime
    metadata: dict
    
    def add_message(role, content, **kwargs)
    def get_history(max_messages=50) -> list[dict]
    def clear()
```

---

## Scheduling & Heartbeat

### Cron Service (`cron/`)

Job scheduling system with three schedule types:

| Type | Description | Example |
|------|-------------|---------|
| `at` | One-time at specific time | `--at "2025-02-01T10:00:00"` |
| `every` | Recurring interval | `--every 3600` (seconds) |
| `cron` | Cron expression | `--cron "0 9 * * *"` |

```python
class CronService:
    def add_job(name, schedule, message, deliver=False, to=None) -> CronJob
    def remove_job(job_id) -> bool
    def enable_job(job_id, enabled=True) -> CronJob | None
    def list_jobs(include_disabled=False) -> list[CronJob]
    async def run_job(job_id, force=False) -> bool
```

**Storage:** `~/.nanobot/cron/jobs.json`

### Heartbeat Service (`heartbeat/service.py`)

Periodic agent wake-up for proactive tasks:

- **Interval:** 30 minutes (configurable)
- **Trigger:** Reads `HEARTBEAT.md` from workspace
- **Purpose:** Check for scheduled tasks, reminders, monitoring
- **Skip:** If `HEARTBEAT.md` is empty or contains only headers

```python
class HeartbeatService:
    async def start()
    def stop()
    async def trigger_now() -> str | None
```

---

## Skills System

### Skill Format

Each skill is a directory with a `SKILL.md` file:

```markdown
---
name: skill-name
description: What this skill does
homepage: https://docs.example.com
metadata: {"nanobot":{"emoji":"🎯","requires":{"bins":["tool"],"env":["API_KEY"]},"always":true}}
---

# Skill Name

Instructions for the agent on how to use this skill...
```

### Metadata Schema

```json
{
  "nanobot": {
    "emoji": "🐙",
    "requires": {
      "bins": ["gh", "curl"],
      "env": ["GITHUB_TOKEN"]
    },
    "always": true,
    "install": [
      {"id": "brew", "kind": "brew", "formula": "gh", "bins": ["gh"]}
    ]
  }
}
```

### Built-in Skills

| Skill | Description | Requirements |
|-------|-------------|--------------|
| `github` | GitHub CLI operations | `gh` CLI |
| `weather` | Weather forecasts | `curl` |
| `summarize` | URL/file summarization | - |
| `tmux` | Terminal multiplexing | `tmux`, shell scripts |
| `skill-creator` | Create new skills | - |

---

## Subagent Architecture

### Purpose

Subagents enable background task execution without blocking the main agent:

- Long-running tasks (data processing, research)
- Parallel task execution
- Isolated contexts for focused work

### Architecture

```
Main Agent                    Subagent Manager              Subagent Instance
───────────                   ────────────────              ────────────────
    │                                │                             │
    │── spawn(task="research") ─────→│                             │
    │                                │── create_task() ───────────→│
    │                                │                             │── limited_tools()
    │                                │                             │── focused_prompt()
    │←─ "Task started..." ───────────│                             │
    │                                │                             │── async_execute()
    │                                │                             │    ...
    │                                │←─ result ───────────────────│
    │←─ [announce via system msg] ───│                             │
```

### Differences from Main Agent

| Feature | Main Agent | Subagent |
|---------|------------|----------|
| Tools | Full set | Limited (no message, no spawn) |
| Context | Full history | Task-focused prompt only |
| Iterations | 20 max | 15 max |
| Communication | Direct user interaction | Results announced via system message |

---

## LLM Provider System

### Base Provider (`providers/base.py`)

```python
@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCallRequest]
    finish_reason: str
    usage: dict[str, int]
    
    @property
    def has_tool_calls() -> bool

class LLMProvider(ABC):
    @abstractmethod
    async def chat(messages, tools, model, max_tokens, temperature) -> LLMResponse
    @abstractmethod
    def get_default_model() -> str
```

### LiteLLM Provider (`providers/litellm_provider.py`)

Multi-provider support via LiteLLM:

**Supported Providers:**
- OpenRouter (default)
- Anthropic (Claude)
- OpenAI (GPT)

**Features:**
- Automatic model name prefixing for OpenRouter
- Environment variable configuration
- Error handling with graceful degradation
- Usage tracking

---

## Deployment & Operations

### CLI Commands (`cli/commands.py`)

| Command | Description |
|---------|-------------|
| `nanobot onboard` | Initialize config and workspace |
| `nanobot agent -m "..."` | Single message mode |
| `nanobot agent` | Interactive chat mode |
| `nanobot gateway` | Start full gateway server |
| `nanobot status` | Show configuration status |
| `nanobot channels login` | WhatsApp QR login |
| `nanobot channels status` | Channel status |
| `nanobot cron add/remove/list` | Schedule management |

### File Structure

```
~/.nanobot/
├── config.json           # Main configuration
├── sessions/             # Conversation history
│   └── {session_key}.jsonl
├── cron/
│   └── jobs.json        # Scheduled jobs
├── media/               # Downloaded media files
├── bridge/              # WhatsApp bridge (copied)
└── workspace/           # User workspace
    ├── AGENTS.md        # Agent instructions
    ├── SOUL.md          # Personality definition
    ├── USER.md          # User preferences
    ├── HEARTBEAT.md     # Proactive task list
    ├── TOOLS.md         # Tool instructions
    ├── memory/
    │   ├── MEMORY.md    # Long-term memory
    │   └── 2025-02-01.md # Daily notes
    └── skills/
        └── custom-skill/
            └── SKILL.md
```

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `NANOBOT_*` | Configuration override (Pydantic Settings) |
| `OPENROUTER_API_KEY` | OpenRouter authentication |
| `ANTHROPIC_API_KEY` | Anthropic authentication |
| `OPENAI_API_KEY` | OpenAI authentication |
| `BRAVE_API_KEY` | Brave Search API key |
| `BRIDGE_PORT` | WhatsApp bridge port (default: 3001) |
| `AUTH_DIR` | WhatsApp auth storage |

---

## Security Considerations

### Access Control

- Channel-level allow lists (`allow_from`)
- No authentication on CLI (assumes trusted user)
- WhatsApp/Token-based auth for Telegram

### Command Execution

- Shell commands run with user permissions
- Working directory restricted to workspace
- Timeout protection (60 seconds default)

### API Keys

- Stored in local config file
- Environment variable support
- No key encryption (user responsibility)

---

## Extension Points

### Adding a New Tool

```python
from nanobot.agent.tools.base import Tool

class MyTool(Tool):
    @property
    def name(self) -> str:
        return "my_tool"
    
    @property
    def description(self) -> str:
        return "What this tool does"
    
    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "param": {"type": "string", "description": "..."}
            },
            "required": ["param"]
        }
    
    async def execute(self, param: str, **kwargs) -> str:
        return f"Result: {param}"
```

### Adding a New Channel

```python
from nanobot.channels.base import BaseChannel

class DiscordChannel(BaseChannel):
    name = "discord"
    
    async def start(self):
        # Connect and listen
        pass
    
    async def stop(self):
        # Cleanup
        pass
    
    async def send(self, msg: OutboundMessage):
        # Send message
        pass
```

### Adding a New Skill

Create `~/.nanobot/workspace/skills/my-skill/SKILL.md`:

```markdown
---
name: my-skill
description: What this skill does
metadata: {"nanobot":{"emoji":"🎯","requires":{"bins":["my-tool"]}}}
---

# My Skill

Instructions for the agent...
```

---

## Performance Characteristics

| Metric | Value |
|--------|-------|
| Startup Time | ~1-2 seconds |
| Memory Footprint | ~50-100 MB |
| Message Throughput | Limited by LLM API latency |
| Max Concurrent Subagents | Unlimited (async) |
| Session History | Last 50 messages by default |
| Tool Output Limit | 10,000 characters |
| Web Fetch Limit | 50,000 characters |

---

## Development Guide

### Setup

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e ".[dev]"
```

### Testing

```bash
pytest
```

### Linting

```bash
ruff check .
ruff format .
```

---

## Roadmap

- [ ] Multi-modal support (images, voice, video)
- [ ] Long-term memory with vector search
- [ ] Better reasoning (multi-step planning, reflection)
- [ ] More integrations (Discord, Slack, email, calendar)
- [ ] Self-improvement from feedback

---

## References

- **Repository:** https://github.com/HKUDS/nanobot
- **PyPI:** https://pypi.org/project/nanobot-ai/
- **Inspired by:** https://github.com/openclaw/openclaw
- **License:** MIT

---

*Document generated for nanobot v0.1.3*
