# Nova AI Assistant — Testing Manual

> **Version:** 2.0  
> **Last Updated:** July 2026  
> **Stack:** Python 3.10 · FastAPI · Groq (Llama 3.3 70B) · Playwright · ChromaDB · APScheduler

---

## Table of Contents

1. [Prerequisites & Setup](#1-prerequisites--setup)
2. [Automated Unit Tests](#2-automated-unit-tests)
3. [Starting the Server](#3-starting-the-server)
4. [Manual Testing — Chat & Conversation](#4-manual-testing--chat--conversation)
5. [Manual Testing — Voice Input](#5-manual-testing--voice-input)
6. [Manual Testing — Memory System](#6-manual-testing--memory-system)
7. [Manual Testing — Email (Gmail)](#7-manual-testing--email-gmail)
8. [Manual Testing — Calendar](#8-manual-testing--calendar)
9. [Manual Testing — Browser Automation & Bookings](#9-manual-testing--browser-automation--bookings)
10. [Manual Testing — Documents & RAG](#10-manual-testing--documents--rag)
11. [Manual Testing — Reminders](#11-manual-testing--reminders)
12. [Manual Testing — Scheduled Tasks](#12-manual-testing--scheduled-tasks)
13. [Manual Testing — Multi-Agent Workflows](#13-manual-testing--multi-agent-workflows)
14. [Manual Testing — Confirmation Modal (Guardrail)](#14-manual-testing--confirmation-modal-guardrail)
15. [Manual Testing — Authentication](#15-manual-testing--authentication)
16. [Manual Testing — WebSocket](#16-manual-testing--websocket)
17. [API Endpoint Reference](#17-api-endpoint-reference)
18. [Environment Variable Checklist](#18-environment-variable-checklist)
19. [CI / CD Pipeline](#19-ci--cd-pipeline)
20. [Known Limitations & Troubleshooting](#20-known-limitations--troubleshooting)

---

## 1. Prerequisites & Setup

### 1.1 Install Dependencies

```bash
# Create and activate virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install all dependencies (production + dev/test)
pip install -r requirements-dev.txt

# Install Playwright browser (required for browser automation)
playwright install chromium
```

### 1.2 Environment Configuration

Copy and configure the `.env` file in the project root:

```ini
# Required
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# Optional — Premium TTS
ELEVENLABS_API_KEY=sk_your_elevenlabs_key_here

# Optional — Email (Gmail App Password)
EMAIL_ADDRESS=you@gmail.com
EMAIL_PASSWORD=your_16_char_app_password

# Optional — Browser
BROWSER_HEADLESS=false

# Optional — Auth
AUTH_ENABLED=false
# SECRET_KEY=your_secure_random_key

# Optional — Database
# MONGODB_URI=mongodb://localhost:27017
```

### 1.3 Google API Setup (for Gmail & Calendar)

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Enable **Gmail API** and **Google Calendar API**.
3. Create an **OAuth 2.0 Client ID** (Desktop application).
4. Download the JSON file and save it as `credentials.json` in the project root.
5. Run `python verify_google.py` — a browser window will open for OAuth consent.
6. After granting permissions, a `token.json` file is created automatically.

---

## 2. Automated Unit Tests

### 2.1 Running All Tests

```bash
# Using the project's virtual environment
.\venv\Scripts\pytest src/ -v
```

### 2.2 Test Files & Coverage

| Test File | Module Under Test | Tests |
|---|---|---|
| `src/test_agent.py` | `AgentCore` | Direct text response, tool calls, confirmation approve/deny, draft description resolution |
| `src/test_auth.py` | `src/auth.py` | Password hashing, JWT creation/verification, auth dependency |
| `src/test_database.py` | `src/database.py` | MongoDB connection, collection access |
| `src/test_memory.py` | `src/memory.py` | Fact storage (Mongo + JSON), fact extraction, local fallback |
| `src/test_rag.py` | `src/rag/retriever.py` | PDF indexing, document search, document listing |

### 2.3 Running a Single Test File

```bash
.\venv\Scripts\pytest src/test_agent.py -v
```

### 2.4 Expected Output (All Pass)

```
src/test_agent.py .....                   [100%]
src/test_auth.py ...                      [100%]
src/test_database.py ..                   [100%]
src/test_memory.py ..                     [100%]
src/test_rag.py ...                       [100%]
=============== 15 passed ================
```

---

## 3. Starting the Server

```bash
python server.py
```

### 3.1 Healthy Startup Checklist

Verify the following lines appear in the terminal output:

| Line | Meaning |
|---|---|
| `✅ Groq ready` | Groq API key is valid |
| `✅ User memory ready (N fact(s) loaded)` | Memory system initialized |
| `✅ Browser tools registered` | Playwright tools loaded |
| `✅ General tools registered` | Built-in tools loaded |
| `✅ Plugin tools registered via adapter` | Email + Calendar tools loaded |
| `✅ ChromaDB collection ready` | RAG vector store initialized |
| `✅ RAG tools registered` | Document search tools loaded |
| `✅ Scheduler + automation tools registered` | APScheduler ready |
| `✅ Agent core ready` | LLM agent loop initialized |
| `✅ Multi-agent orchestrator ready` | Workflow engine loaded |
| `Uvicorn running on http://0.0.0.0:8000` | Server is listening |

### 3.2 Warning Messages (Non-Critical)

| Warning | Cause |
|---|---|
| `⚠️ MONGODB_URI not set` | Using local JSON file for memory (OK for dev) |
| `⚠️ SECRET_KEY not set` | Using insecure dev key (OK when `AUTH_ENABLED=false`) |
| `🔓 Auth mode: DISABLED` | Routes are open (expected in dev) |

---

## 4. Manual Testing — Chat & Conversation

Open your browser to **http://localhost:8000**.

### TC-4.1: Basic Chat

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "Hello, how are you?" and press Send | Nova responds with a friendly greeting. No tools used. |
| 2 | Check the turn counter (top-left) | Turn count increments to 1 |
| 3 | Type "What is 15 × 37?" | Nova calculates and responds with 555. No tools used. |
| 4 | Check Activity drawer (click "Activity" button) | Shows reasoning trace: `assemble context → llm → reasoning → done` |

### TC-4.2: Conversation Context

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "My name is Saarthak" | Nova acknowledges your name |
| 2 | Type "What is my name?" | Nova recalls "Saarthak" from conversation history |

### TC-4.3: Markdown Rendering

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "Write a Python function to reverse a string" | Response renders with syntax-highlighted code block |
| 2 | Type "Give me a bulleted list of 5 fruits" | Response renders as a proper `<ul>` list |

### TC-4.4: Copy Button

| Step | Action | Expected Result |
|---|---|---|
| 1 | Hover over any Nova message | Copy button appears on the left edge |
| 2 | Click the copy button | "Copied to clipboard" toast notification appears |

### TC-4.5: Clear History

| Step | Action | Expected Result |
|---|---|---|
| 1 | Click the "Clear" button in the chat header | All messages disappear, turn counter resets to 0 |

---

## 5. Manual Testing — Voice Input

### TC-5.1: Push-to-Talk

| Step | Action | Expected Result |
|---|---|---|
| 1 | Click the microphone button (hold) | Button glows, recording starts |
| 2 | Speak a question, then release | Audio is transcribed and sent as a chat message |
| 3 | Check response | Nova responds with text; if voice responses enabled, TTS plays |

### TC-5.2: Voice Response Toggle

| Step | Action | Expected Result |
|---|---|---|
| 1 | Open Settings (gear icon in sidebar) | Settings modal opens |
| 2 | Toggle "Voice responses" off | `speechSynthesis` stops, future responses are text-only |
| 3 | Toggle "Voice responses" on | Future responses are spoken aloud |

---

## 6. Manual Testing — Memory System

Navigate to the **Memory** tab in the sidebar.

### TC-6.1: Auto-Remember

| Step | Action | Expected Result |
|---|---|---|
| 1 | In Chat, type "I love pizza and I live in Delhi" | Nova responds naturally |
| 2 | Navigate to Memory tab | New fact(s) appear: e.g., "User loves pizza", "User lives in Delhi" |
| 3 | Return to Chat and type "Where do I live?" | Nova answers "Delhi" using memorized facts |

### TC-6.2: Delete Individual Memory

| Step | Action | Expected Result |
|---|---|---|
| 1 | In Memory tab, click the delete (×) button on a fact | Fact is removed from the list |
| 2 | Verify via API: `GET /api/memory` | Deleted fact no longer in response |

### TC-6.3: Clear All Memory

| Step | Action | Expected Result |
|---|---|---|
| 1 | Click "Clear all memory" at the bottom of Memory tab | All facts removed, count shows 0 |

### TC-6.4: API Verification

```bash
# List all facts
curl http://localhost:8000/api/memory

# Delete a specific fact (index 0)
curl -X DELETE http://localhost:8000/api/memory/0

# Clear all facts
curl -X DELETE http://localhost:8000/api/memory
```

---

## 7. Manual Testing — Email (Gmail)

> **Prerequisite:** Either `credentials.json` + `token.json` (Google OAuth) or `EMAIL_ADDRESS` + `EMAIL_PASSWORD` in `.env`.

### TC-7.1: Draft & Send Email

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "Send an email to test@example.com about meeting tomorrow" | Nova calls `draft_email` → shows a preview of the email |
| 2 | Nova then calls `send_email` | **Confirmation modal** appears: "Nova wants to: send email draft ..." with recipient and subject displayed |
| 3 | Click **Confirm** | Email is sent. Nova confirms: "Email sent successfully." |
| 4 | Click **Cancel** instead | Email is NOT sent. Nova says it was cancelled. |

### TC-7.2: List Emails

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "Show me my recent emails" | Nova calls `list_emails`, returns recent inbox messages with sender, subject, date |

### TC-7.3: Confirmation Description Quality

| Step | Action | Expected Result |
|---|---|---|
| 1 | Trigger a `send_email` with a draft | Modal should show the **actual recipient email** and **subject line**, NOT "?" placeholders |

---

## 8. Manual Testing — Calendar

> **Prerequisite:** `credentials.json` + `token.json` (Google OAuth).

### TC-8.1: Create Calendar Event

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "Create a meeting tomorrow at 3 PM called Team Standup" | Confirmation modal appears: "create a calendar event 'Team Standup' at ..." |
| 2 | Click **Confirm** | Event created in Google Calendar |

### TC-8.2: List Calendar Events

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "What's on my calendar this week?" | Nova calls `list_calendar_events`, shows upcoming events |

### TC-8.3: Delete Calendar Event

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "Delete the Team Standup event" | Confirmation modal appears. After confirming, event is deleted. |

---

## 9. Manual Testing — Browser Automation & Bookings

> **Prerequisite:** Playwright installed (`playwright install chromium`). Set `BROWSER_HEADLESS=false` in `.env` to see the browser window.

### 9.1 Supported Websites

| Category | Site Key | Website | Bot Friendliness |
|---|---|---|---|
| **Trains** | `irctc` | [irctc.co.in](https://www.irctc.co.in) | Requires login; may block bots |
| | `confirmtkt` | [confirmtkt.com](https://www.confirmtkt.com) | ✅ Bot-friendly |
| **Flights** | `makemytrip` | [makemytrip.com](https://www.makemytrip.com) | May block bots |
| | `ixigo` | [ixigo.com](https://www.ixigo.com) | ✅ Bot-friendly |
| | `cleartrip` | [cleartrip.com](https://www.cleartrip.com) | ✅ Bot-friendly |
| **Movies/Events** | `bookmyshow` | [in.bookmyshow.com](https://in.bookmyshow.com) | General |
| **Shopping** | `amazon` | [amazon.in](https://www.amazon.in) | General |
| | `flipkart` | [flipkart.com](https://www.flipkart.com) | ✅ Bot-friendly |
| **Food/Groceries** | `swiggy` | [swiggy.com](https://www.swiggy.com) | General |
| | `zomato` | [zomato.com](https://www.zomato.com) | May block bots |
| | `blinkit` | [blinkit.com](https://blinkit.com) | ✅ Bot-friendly |

### TC-9.1: Web Navigation

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "Open google.com" | Nova calls `browser_navigate`, browser opens Google |
| 2 | Type "Extract the text from this page" | Nova calls `browser_extract_text`, returns page content |

### TC-9.2: Web Search via Browser

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "Search for iPhone 16 reviews on the web" | Nova calls `browser_search_web` or `web_search`, returns results |

### TC-9.3: Booking Flow (e.g., Blinkit)

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "Order magnum ice cream from Blinkit" | Nova calls `browser_search_and_book` with action=search |
| 2 | Nova then calls with action=book | **Confirmation modal** appears: "shop on blinkit" |
| 3 | Click **Confirm** | Browser opens Blinkit with the product page. A message says "Please complete your checkout in the browser window." |

### TC-9.4: Train Search (ConfirmTkt — Bot-Friendly)

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "Search trains from Delhi to Mumbai on confirmtkt" | Nova navigates to ConfirmTkt and attempts to fill the search form |

### TC-9.5: Headed vs Headless Mode

| Step | Action | Expected Result |
|---|---|---|
| 1 | Set `BROWSER_HEADLESS=true` in `.env`, restart server | Browser runs in background (no window visible) |
| 2 | Set `BROWSER_HEADLESS=false` in `.env`, restart server | Browser window opens visibly for manual handoff |

---

## 10. Manual Testing — Documents & RAG

Navigate to the **Documents** tab in the sidebar.

### TC-10.1: Upload PDF

| Step | Action | Expected Result |
|---|---|---|
| 1 | Drag and drop a PDF file onto the dropzone (or click "Browse files") | Upload progress shown, then "Indexed" status with chunk count |
| 2 | Check the documents list below | Uploaded PDF appears with doc ID and filename |

### TC-10.2: Search Uploaded Document

| Step | Action | Expected Result |
|---|---|---|
| 1 | In Chat, type "What does the uploaded PDF say about [topic]?" | Nova calls `search_documents`, returns relevant excerpts from the PDF |

### TC-10.3: Delete Document

| Step | Action | Expected Result |
|---|---|---|
| 1 | In Documents tab, click delete on a listed document | Document is removed from the index |

### TC-10.4: API Verification

```bash
# Upload a PDF
curl -X POST http://localhost:8000/api/upload -F "file=@sample.pdf"

# List indexed documents
curl http://localhost:8000/api/documents

# Delete a document
curl -X DELETE http://localhost:8000/api/documents/{doc_id}
```

---

## 11. Manual Testing — Reminders

### TC-11.1: Set a Reminder

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "Remind me to drink water in 2 minutes" | Confirmation modal appears: "set a reminder at HH:MM to 'drink water'" |
| 2 | Click **Confirm** | Nova confirms reminder is set |
| 3 | Wait 2 minutes | Toast notification appears: "⏰ Reminder: drink water". WebSocket pushes the alert. |

### TC-11.2: View Reminders

| Step | Action | Expected Result |
|---|---|---|
| 1 | Navigate to **Automations** tab | Reminders section lists active/completed reminders |

### TC-11.3: API Verification

```bash
curl http://localhost:8000/api/reminders
```

---

## 12. Manual Testing — Scheduled Tasks

### TC-12.1: Schedule a Recurring Task

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "Every 30 minutes, check the weather in Delhi" | Confirmation modal appears: "schedule a background task '...'" |
| 2 | Click **Confirm** | Task scheduled. Appears in Automations tab. |
| 3 | Wait 30 minutes (or check logs) | Task fires, agent runs weather check in background |

### TC-12.2: List Scheduled Tasks

```bash
curl http://localhost:8000/api/tasks
```

### TC-12.3: Cancel a Task

```bash
curl -X DELETE http://localhost:8000/api/tasks/{task_id}
```

---

## 13. Manual Testing — Multi-Agent Workflows

### TC-13.1: Complex Workflow

| Step | Action | Expected Result |
|---|---|---|
| 1 | Type "Search the web for today's weather in Delhi, then draft an email to boss@company.com with the weather report" | Nova orchestrates multiple tool calls (web_search → draft_email) |
| 2 | Check Activity drawer | Shows multi-step reasoning trace |

### TC-13.2: API Direct Call

```bash
curl -X POST http://localhost:8000/api/workflow \
  -H "Content-Type: application/json" \
  -d '{"goal": "Find the weather in London and summarize it"}'
```

---

## 14. Manual Testing — Confirmation Modal (Guardrail)

### Tools That Require Confirmation

| Tool | Description |
|---|---|
| `send_email` | Sending an email |
| `set_reminder` | Setting a reminder/alarm |
| `create_calendar_event` | Creating a calendar event |
| `delete_calendar_event` | Deleting a calendar event |
| `execute_python` | Running arbitrary Python code |
| `schedule_task` | Scheduling a background task |
| `browser_search_and_book` (action=book) | Booking/purchasing on a website |

### TC-14.1: Confirm Flow

| Step | Action | Expected Result |
|---|---|---|
| 1 | Trigger any guardrailed action (e.g., "Set a reminder for 5 PM") | Modal pops up with amber warning icon, action description, Confirm/Cancel buttons |
| 2 | Click **Confirm** | Action executes, Activity trace shows "action approved by user" |
| 3 | Click **Cancel** | Action cancelled, trace shows "action denied by user" |

### TC-14.2: Timeout

| Step | Action | Expected Result |
|---|---|---|
| 1 | Trigger a guardrailed action | Modal appears |
| 2 | Do NOT click anything for 30 seconds | Action is auto-denied ("Confirmation timed out ... denying") |

### TC-14.3: Overlay Dismiss

| Step | Action | Expected Result |
|---|---|---|
| 1 | When modal appears, click the dark overlay behind it | Treated as a denial — action is cancelled |

---

## 15. Manual Testing — Authentication

> **Prerequisite:** Set `AUTH_ENABLED=true` and `SECRET_KEY=your_key` in `.env`, then restart server.

### TC-15.1: Register

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "TestPass123"}'
```

**Expected:** `{"message": "User registered successfully", "username": "testuser"}`

### TC-15.2: Login

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "TestPass123"}'
```

**Expected:** `{"access_token": "eyJ...", "token_type": "bearer"}`

### TC-15.3: Authenticated Request

```bash
curl http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer eyJ..."
```

**Expected:** `{"username": "testuser"}`

### TC-15.4: Protected Routes (when AUTH_ENABLED=true)

| Step | Action | Expected Result |
|---|---|---|
| 1 | Call `POST /api/chat` without a token | `401 Unauthorized` |
| 2 | Call `POST /api/chat` with a valid Bearer token | Normal chat response |

---

## 16. Manual Testing — WebSocket

### TC-16.1: Connection

| Step | Action | Expected Result |
|---|---|---|
| 1 | Open browser to http://localhost:8000 | WebSocket auto-connects to `ws://localhost:8000/ws` |
| 2 | Check browser DevTools → Network → WS tab | WebSocket connection is `OPEN` |

### TC-16.2: Keepalive

| Step | Action | Expected Result |
|---|---|---|
| 1 | Wait 25+ seconds with the page open | Client sends `ping`, server responds with `pong` |

### TC-16.3: Confirmation via WebSocket

| Step | Action | Expected Result |
|---|---|---|
| 1 | Trigger a guardrailed action | WebSocket receives `{"type": "confirmation_required", "request_id": "...", "tool_name": "...", "description": "..."}` |

### TC-16.4: Reminder Notification via WebSocket

| Step | Action | Expected Result |
|---|---|---|
| 1 | Set a reminder that fires in 1 minute | When it fires, WebSocket receives `{"type": "reminder", "message": "..."}` |

---

## 17. API Endpoint Reference

### Core

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `POST` | `/api/chat` | Send a message to Nova | When `AUTH_ENABLED=true` |
| `POST` | `/api/voice` | Upload audio for transcription + chat | When `AUTH_ENABLED=true` |
| `POST` | `/api/confirm` | Submit confirmation decision (yes/no) | No |
| `GET` | `/api/status` | System module health check | No |

### Memory

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/memory` | List all memorized facts |
| `DELETE` | `/api/memory` | Clear all facts |
| `DELETE` | `/api/memory/{index}` | Delete a specific fact by index |

### Reminders & History

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/reminders` | List all reminders |
| `GET` | `/api/history?session_id=default` | Get conversation history |
| `DELETE` | `/api/history?session_id=default` | Clear conversation history |

### Documents (RAG)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/upload` | Upload and index a PDF |
| `GET` | `/api/documents` | List indexed documents |
| `DELETE` | `/api/documents/{doc_id}` | Remove a document from index |

### Workflows & Tasks

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/workflow` | Run a multi-agent workflow |
| `GET` | `/api/tasks` | List scheduled tasks |
| `POST` | `/api/tasks` | Create a scheduled task |
| `DELETE` | `/api/tasks/{task_id}` | Cancel a scheduled task |

### Plugins

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/plugins/servers` | List plugin servers |
| `GET` | `/api/plugins/servers/{name}/tools` | List tools on a server |
| `POST` | `/api/plugins/servers/{name}/tools/{tool}/execute` | Execute a plugin tool directly |

### Authentication

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Register a new user |
| `POST` | `/api/auth/login` | Login, get JWT token |
| `GET` | `/api/auth/me` | Get current user info |

### Static & UI

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serve the Nova web UI |
| `WS` | `/ws` | WebSocket for live updates |

---

## 18. Environment Variable Checklist

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GROQ_API_KEY` | ✅ Yes | — | Groq API key for LLM + Whisper |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | LLM model selection |
| `ELEVENLABS_API_KEY` | No | — | Premium TTS via ElevenLabs |
| `EMAIL_ADDRESS` | No | — | Gmail App Password fallback (SMTP) |
| `EMAIL_PASSWORD` | No | — | Gmail App Password |
| `BROWSER_HEADLESS` | No | `false` | `true` = headless, `false` = visible window |
| `AUTH_ENABLED` | No | `false` | Enable JWT route protection |
| `SECRET_KEY` | No | Dev fallback | JWT signing key (set in production!) |
| `MONGODB_URI` | No | Local JSON | MongoDB connection URI |

---

## 19. CI / CD Pipeline

### GitHub Actions Workflow

The project includes a CI workflow at `.github/workflows/test.yml`:

```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - run: pip install -r requirements-dev.txt
      - run: pytest src/ -v
```

This runs all unit tests in `src/` on every push and pull request.

### Docker

```bash
# Build the image
docker build -t nova-assistant .

# Run the container
docker run -p 8000:8000 --env-file .env nova-assistant
```

> **Note:** Playwright browser binaries are excluded from the Docker image to keep it lightweight. If browser automation is needed inside Docker, run `playwright install chromium` inside the container.

---

## 20. Known Limitations & Troubleshooting

### Common Issues

| Issue | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'groq'` | Running pytest with system Python instead of venv | Use `.\venv\Scripts\pytest` |
| `⚠️ MONGODB_URI not set` | No MongoDB configured | OK for dev — uses local `user_memory.json` |
| `⚠️ SECRET_KEY not set` | No secret key in `.env` | Set `SECRET_KEY` when using `AUTH_ENABLED=true` |
| IRCTC/MakeMyTrip blocks automation | Anti-bot protections | Use bot-friendly alternatives: `confirmtkt`, `ixigo`, `cleartrip` |
| Confirmation modal shows "?" for email | `send_email` called without draft details | Fixed — now resolves from draft cache or Gmail API |
| Google OAuth browser popup | First-time `credentials.json` auth | Run `python verify_google.py` once to generate `token.json` |
| `FutureWarning: Python 3.10 EOL` | Google API warns about Python 3.10 | Upgrade to Python 3.11+ |
| WebSocket disconnects randomly | Network instability | Auto-reconnects after 3 seconds |
| `test_alternatives.py` fixture error | Test requires a `url` pytest fixture | Not a core test — ignore safely |

### Performance Notes

- **Groq API rate limits:** The `llama-3.3-70b-versatile` model has higher rate limits than smaller models. If you hit rate limits, wait a few seconds and retry.
- **ChromaDB first load:** The sentence-transformers model is downloaded on first use (~90 MB). Subsequent starts are faster.
- **Browser automation:** Each Playwright session opens a fresh Chromium instance. Close unused sessions to free memory.

### Logs & Debugging

- **Server logs:** All tool calls, confirmations, and errors are logged to the terminal running `python server.py`.
- **Tool call format:** `🔧 Tool call: tool_name({arguments})` followed by `✅ Tool result: ...` or `❌ Error: ...`.
- **Confirmation flow:** `🛡️ Awaiting UI confirmation for: ...` → `✅ Confirmation granted` or `🚫 User declined` or `⏱️ Confirmation timed out`.

---

*End of Testing Manual*
