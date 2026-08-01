# 🎙️ Nova — Agentic Voice AI Assistant

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-LLM-F55036?style=for-the-badge&logo=groq&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![ChromaDB](https://img.shields.io/badge/ChromaDB-RAG-FF6B35?style=for-the-badge)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

**A fully agentic, voice-first AI assistant powered by Groq's ultra-fast inference, featuring multi-tier memory, RAG, browser automation, and a multi-agent orchestration system.**

[Features](#-features) • [Architecture](#-architecture) • [Quick Start](#-quick-start) • [Tools](#-built-in-tools) • [Configuration](#-configuration) • [Docker](#-docker-deployment)

</div>

---

## ✨ Features

| Category | Capabilities |
|---|---|
| 🎙️ **Voice I/O** | Wake word detection (`alexa`, `hey jarvis`), VAD-based recording, Groq Whisper STT, ElevenLabs / pyttsx3 TTS |
| 🧠 **Multi-Tier Memory** | Short-term conversation history · Long-term MongoDB user profile · Episodic ChromaDB memory |
| 🔍 **RAG Pipeline** | PDF ingestion, BM25 + semantic hybrid retrieval, ChromaDB vector store |
| 🤖 **Agentic Loop** | Iterative tool-calling with a safety brake, guardrail-protected reasoning |
| 🌐 **Multi-Agent Orchestration** | Research, Browser, Email, Calendar, and General specialist sub-agents |
| 🔒 **Security** | JWT auth, prompt-injection guardrails, automatic secret scrubbing from outputs |
| 🖥️ **Web UI** | Full-featured browser UI served via FastAPI + WebSocket streaming |
| 🐳 **Docker** | Multi-stage, lightweight production image |

---

## 🏗️ Architecture

```
agentic_voice_ai/
├── main.py                  # CLI voice assistant (wake word → STT → agent → TTS)
├── server.py                # FastAPI web server (REST + WebSocket)
├── src/
│   ├── agent.py             # AgentCore — the agentic reasoning loop
│   ├── orchestrator.py      # Multi-agent workflow orchestrator
│   ├── memory.py            # Long-term user profile (MongoDB)
│   ├── memory_episodic.py   # Episodic memory (ChromaDB + sentence-transformers)
│   ├── guardrails.py        # Prompt-injection screening & secret scrubbing
│   ├── auth.py              # JWT authentication
│   ├── scheduler.py         # Background task scheduler (APScheduler)
│   ├── audio/
│   │   ├── mic.py           # Enhanced microphone with VAD
│   │   ├── wakeword.py      # Text-based wake word detector
│   │   └── tts.py           # TTSEngine (ElevenLabs + pyttsx3 fallback)
│   ├── tools/
│   │   ├── __init__.py      # ToolRegistry
│   │   ├── general_tools.py # execute_python, http_fetch, read_file, web_search
│   │   ├── browser.py       # Playwright browser automation
│   │   ├── email_tool.py    # Gmail SMTP send/read
│   │   ├── calendar_tool.py # Google Calendar integration
│   │   ├── reminders.py     # Reminder service
│   │   ├── automation.py    # Background task scheduling tools
│   │   └── rag_tool.py      # Document search tool
│   └── rag/                 # RAG retriever & PDF ingestion
└── ui/
    ├── index.html           # Web UI
    ├── app.js               # Frontend logic (WebSocket client)
    └── styles.css           # Styling
```

### Agent Reasoning Loop

```
User Input
    │
    ▼
sanitize_input()  ←── Guardrails: prompt-injection check
    │
    ▼
Assemble Context  ←── System prompt + user profile + episodic memory + history
    │
    ▼
LLM Call (Groq)  ←── llama-3.3-70b-versatile (configurable)
    │
    ├── Text Response ──► scrub_output() ──► User
    │
    └── Tool Call ──► Guardrail check ──► Confirmation (HIGH_RISK_TOOLS)
            │                                      │
            └──────── Execute Tool ◄───────────────┘
                            │
                       Feed result back
                            │
                       (loop, max 10 steps)
```

### Multi-Agent Orchestration

```
Goal (complex query)
        │
        ▼
  Orchestrator (LLM planner)
        │
        ├── ResearchAgent  → web_search, search_documents
        ├── BrowserAgent   → browser_navigate, browser_search_and_book
        ├── EmailAgent     → draft_email, send_email
        ├── CalendarAgent  → create_calendar_event, list_calendar_events
        ├── GeneralAgent   → execute_python, http_fetch, read_file
        └── NovaAgent      → all tools (fallback)
                │
                ▼
        Aggregated Response
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- A [Groq API key](https://console.groq.com) (free)
- MongoDB (optional — for persistent user memory)
- Windows: PyAudio wheel is bundled (`PyAudio-0.2.14-cp310-cp310-win_amd64.whl`)

### 1. Clone & Install

```bash
git clone https://github.com/Saarthakyadav/Personal_AI_Assistant.git
cd Personal_AI_Assistant

# Create and activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Windows only: install bundled PyAudio wheel
pip install PyAudio-0.2.14-cp310-cp310-win_amd64.whl

# Install Playwright browser (for browser automation)
playwright install chromium
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your keys:

```env
# Required
GROQ_API_KEY=your_groq_api_key_here

# Optional — LLM model (default: llama-3.3-70b-versatile)
GROQ_MODEL=llama-3.3-70b-versatile

# Optional — TTS (falls back to pyttsx3 if not set)
ELEVENLABS_API_KEY=your_elevenlabs_key_here

# Optional — Persistent user memory
MONGODB_URI=mongodb+srv://...

# Optional — Email integration (Gmail App Password)
EMAIL_ADDRESS=you@gmail.com
EMAIL_PASSWORD=your_app_password

# Required for web server auth
SECRET_KEY=your_secret_key_here
```

### 3. Run

**Voice mode (CLI):**
```bash
python main.py
# Say "hey jarvis" or "alexa" to wake Nova up
```

**Web UI mode:**
```bash
uvicorn server:app --reload --port 8000
# Open http://localhost:8000
```

---

## 🛠️ Built-in Tools

Nova ships with a rich tool library, all registered in `ToolRegistry`:

| Tool | Module | Description |
|---|---|---|
| `web_search` | `general_tools.py` | DuckDuckGo web search (no API key needed) |
| `execute_python` | `general_tools.py` | Sandboxed Python REPL |
| `http_fetch` | `general_tools.py` | Fetch any URL |
| `read_file` | `general_tools.py` | Read local files |
| `browser_navigate` | `browser.py` | Playwright browser navigation |
| `browser_extract_text` | `browser.py` | Extract page text |
| `browser_search_and_book` | `browser.py` | Autonomous booking automation |
| `send_email` | `email_tool.py` | Send email via Gmail SMTP |
| `draft_email` | `email_tool.py` | Compose and save a draft |
| `list_emails` | `email_tool.py` | List inbox emails |
| `create_calendar_event` | `calendar_tool.py` | Add Google Calendar event |
| `list_calendar_events` | `calendar_tool.py` | List upcoming events |
| `delete_calendar_event` | `calendar_tool.py` | Remove calendar event |
| `set_reminder` | `reminders.py` | Set a time-based reminder |
| `schedule_task` | `automation.py` | Schedule background task |
| `cancel_task` | `automation.py` | Cancel a scheduled task |
| `search_documents` | `rag_tool.py` | RAG search over indexed PDFs |
| `get_current_datetime` | `general_tools.py` | Current date/time |

### ⚠️ High-Risk Tool Confirmation

The following tools require explicit voice/UI confirmation before execution (configured in `src/guardrails.py`):

`set_reminder` · `execute_python` · `read_file` · `send_email` · `create_calendar_event` · `delete_calendar_event` · `schedule_task` · `cancel_task`

---

## 🧠 Memory System

Nova uses a **three-tier memory architecture**:

| Tier | Storage | Scope | Purpose |
|---|---|---|---|
| **Short-term** | In-process list | Current session | Rolling conversation window (last 10 turns) |
| **Long-term** | MongoDB | Cross-session | User profile: facts & behavioral preferences |
| **Episodic** | ChromaDB | Cross-session | Semantic search over past conversation turns |

The long-term memory extracts facts and preferences using a dedicated LLM call after each exchange. Episodic memory uses `all-MiniLM-L6-v2` embeddings for semantic retrieval and intentionally skips recent turns already present in the rolling window.

---

## 🔒 Security & Guardrails

Defined in `src/guardrails.py`:

- **Input sanitization** — regex/heuristic scan for prompt-injection patterns (system-prompt overrides, identity overrides, fake delimiters). Flag-and-log only — no silent rewrites.
- **Output scrubbing** — replaces API key shapes (`sk-*`, `AIza*`, `ghp_*`), Bearer tokens, and actual env-var values with `[redacted]` before any response leaves the agent.
- **JWT authentication** — all web server endpoints protected via `src/auth.py`.

---

## ⚙️ Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | **Required.** Groq API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | LLM model for inference |
| `ELEVENLABS_API_KEY` | — | ElevenLabs TTS key (optional) |
| `MONGODB_URI` | — | MongoDB connection string (optional) |
| `EMAIL_ADDRESS` | — | Gmail address for email tool |
| `EMAIL_PASSWORD` | — | Gmail App Password |
| `SECRET_KEY` | — | JWT signing key (required for web server) |

---

## 🐳 Docker Deployment

```bash
# Build
docker build -t nova-assistant .

# Run
docker run -p 8000:8000 \
  -e GROQ_API_KEY=your_key \
  -e SECRET_KEY=your_secret \
  nova-assistant

# Open http://localhost:8000
```

The Dockerfile uses a **multi-stage build** (Python 3.10 slim) to keep the final image lightweight. Playwright browser binaries are excluded by default — mount them or run `playwright install chromium` inside the container if browser automation is needed.

---

## 🧪 Testing

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest src/ -v

# Run specific test modules
pytest src/test_agent.py -v
pytest src/test_memory.py -v
pytest src/test_tool_registry.py -v
pytest src/test_auth.py -v
```

Tests cover: agent reasoning loop, memory persistence, tool registry, auth flows, RAG retrieval.

---

## 📦 Tech Stack

| Layer | Technology |
|---|---|
| **LLM Inference** | [Groq](https://groq.com) (`llama-3.3-70b-versatile`) |
| **STT** | Groq Whisper API |
| **TTS** | ElevenLabs + pyttsx3 fallback |
| **Wake Word** | openwakeword (local, free) |
| **VAD** | webrtcvad-wheels |
| **Audio I/O** | sounddevice + PyAudio |
| **Web Server** | FastAPI + Uvicorn |
| **Real-time** | WebSockets |
| **Vector DB** | ChromaDB |
| **Embeddings** | sentence-transformers (`all-MiniLM-L6-v2`) |
| **Database** | MongoDB (pymongo) |
| **Browser** | Playwright (Chromium) |
| **Scheduler** | APScheduler |
| **Auth** | PyJWT + bcrypt |
| **Web Search** | ddgs (DuckDuckGo, no key required) |

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/amazing-feature`
3. Commit your changes: `git commit -m 'feat: add amazing feature'`
4. Push to the branch: `git push origin feat/amazing-feature`
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">
Built with ❤️ using Groq's blazing-fast inference
</div>
