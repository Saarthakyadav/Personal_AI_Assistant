# server.py
"""
Nova Web Server — FastAPI entry point for the Nova UI.

Reuses the same AgentCore, UserMemory, ToolRegistry, and ReminderService
as main.py, but serves them over HTTP instead of voice.

Phase 1: Bug fixes (turn_count, thread-safe tool tracking, system prompt)
Phase 3: Browser/email/calendar tools + /api/confirm + guardrail modal
Phase 4: RAG PDF upload + /api/documents
Phase 5: Multi-agent /api/workflow + WebSocket streaming
Phase 6: Background scheduler /api/tasks
"""

import sys
import io
import os
import json
import asyncio
import threading
import uuid
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, List, Dict, Any

# Force UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dotenv import load_dotenv
from groq import Groq

from src.memory import UserMemory
from src.agent import AgentCore
from src.tools import ToolRegistry
from src.tools.builtins import ALL_BUILTIN_TOOLS
from src.tools.reminders import ReminderService, create_reminder_tool

load_dotenv()

# ── Initialize all backend services ──────────────────────────────────────────

print("=" * 60)
print("🌐 Nova Web Server")
print("=" * 60)

# Groq client
api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    print("❌ No GROQ_API_KEY found in .env file")
    sys.exit(1)
client = Groq(api_key=api_key)
print("✅ Groq ready")

# User memory
memory = UserMemory(filepath=os.path.join(os.path.dirname(__file__), "user_memory.json"))
print(f"✅ User memory ready ({memory.fact_count} fact(s) loaded)")

# Tool registry
tool_registry = ToolRegistry()
mcp_adapter = None
mcp_error = None
for tool in ALL_BUILTIN_TOOLS:
    tool_registry.register(tool)

# Reminder service — uses a no-op speak callback since the UI handles display
def _web_speak(text: str):
    """No-op TTS for web mode — the UI displays text directly."""
    print(f"🔔 Reminder (web): {text}")
    # Broadcast reminder to all connected WebSocket clients
    _ws_broadcast_sync({"type": "reminder", "message": text})

reminder_service = ReminderService(
    filepath=os.path.join(os.path.dirname(__file__), "reminders.json"),
    speak_callback=_web_speak,
)
reminder_tool = create_reminder_tool(reminder_service)
tool_registry.register(reminder_tool)
# reminder_service.start() — moved to lifespan startup to prevent race conditions

# ── Optional Phase 3: Browser / Email / Calendar / General tools & MCP ────────
try:
    from src.tools.browser import BROWSER_TOOLS
    for t in BROWSER_TOOLS:
        tool_registry.register(t)
    print(f"✅ Browser tools registered: {[t.name for t in BROWSER_TOOLS]}")
except ImportError as e:
    print(f"⚠️  Browser tools not available (pip install playwright): {e}")

try:
    from src.tools.general_tools import GENERAL_TOOLS
    for t in GENERAL_TOOLS:
        tool_registry.register(t)
    print(f"✅ General tools registered: {[t.name for t in GENERAL_TOOLS]}")
except ImportError as e:
    print(f"⚠️  General tools not available: {e}")

try:
    from src.tools.email_tool import EMAIL_TOOLS
    from src.tools.calendar_tool import CALENDAR_TOOLS
    from src.tools.mcp_adapter import MCPPluginAdapter
    
    mcp_adapter = MCPPluginAdapter()
    mcp_adapter.register_tools("email", EMAIL_TOOLS)
    mcp_adapter.register_tools("calendar", CALENDAR_TOOLS)
    
    installed_count = mcp_adapter.install_into_registry(tool_registry)
    print(f"✅ MCP Plugin tools registered via adapter: {installed_count} tools across 2 servers")
except Exception as e:
    mcp_error = str(e)
    print(f"⚠️  MCP / Email / Calendar tools not available: {e}")

# ── Optional Phase 4: RAG tools ───────────────────────────────────────────────
rag_retriever = None
try:
    from src.rag.retriever import RAGRetriever
    from src.tools.rag_tool import create_rag_tool
    rag_retriever = RAGRetriever()
    # FIX #16: create_rag_tool now returns a (search_tool, list_tool) tuple
    rag_search_tool, rag_list_tool = create_rag_tool(rag_retriever)
    tool_registry.register(rag_search_tool)
    tool_registry.register(rag_list_tool)
    print("✅ RAG tools registered")
except ImportError as e:
    print(f"⚠️  RAG not available (pip install chromadb sentence-transformers pymupdf): {e}")
except Exception as e:
    print(f"⚠️  RAG init failed: {e}")

# ── Optional Phase 6: Task Scheduler ─────────────────────────────────────────
task_scheduler = None
try:
    from src.scheduler import TaskScheduler
    from src.tools.automation import create_automation_tools
    task_scheduler = TaskScheduler()
    # task_scheduler.start() — moved to lifespan startup to prevent races
    automation_tools = create_automation_tools(task_scheduler)
    for t in automation_tools:
        tool_registry.register(t)
    print("✅ Scheduler + automation tools registered")
except ImportError as e:
    print(f"⚠️  Scheduler not available (pip install apscheduler): {e}")
except Exception as e:
    print(f"⚠️  Scheduler init failed: {e}")

print(f"✅ All tools ready: {tool_registry.tool_names}")

# Agent core
agent = AgentCore(
    groq_client=client,
    memory=memory,
    tool_registry=tool_registry,
    max_steps=10,
)
print("✅ Agent core ready")

# ── Optional Phase 5: Orchestrator ────────────────────────────────────────────
orchestrator = None
try:
    from src.orchestrator import Orchestrator
    orchestrator = Orchestrator(groq_client=client, tool_registry=tool_registry, memory=memory)
    print("✅ Multi-agent orchestrator ready")
except ImportError as e:
    print(f"⚠️  Orchestrator not available: {e}")

# ── Conversation state ────────────────────────────────────────────────────────
# FIX #4: Per-session conversation history to prevent cross-user data leaks.
# Each session gets its own history list and turn counter.
MAX_HISTORY_TURNS = 10
_sessions: Dict[str, dict] = {}   # session_id → {"history": [], "turn_count": 0}
_sessions_lock = threading.Lock()
_chat_lock = threading.Lock()


def _get_session(session_id: str = "default") -> dict:
    """Get or create a per-session conversation state."""
    with _sessions_lock:
        if session_id not in _sessions:
            _sessions[session_id] = {"history": [], "turn_count": 0}
        return _sessions[session_id]

# ── Pending confirmations (guardrail modal) ───────────────────────────────────
# Maps request_id → threading.Event + result dict
_pending_confirmations: Dict[str, dict] = {}
_confirm_lock = threading.Lock()

# ── WebSocket clients ─────────────────────────────────────────────────────────
_ws_clients: List[WebSocket] = []
_ws_lock = threading.Lock()


# FIX #9: Capture the running event loop at startup so background threads
# can safely schedule coroutines without calling asyncio.get_event_loop()
# (which is deprecated/broken in non-async threads on Python 3.10+).
_event_loop: Optional[asyncio.AbstractEventLoop] = None


def _ws_broadcast_sync(data: dict):
    """Thread-safe broadcast to all connected WebSocket clients."""
    if _event_loop is None:
        return
    with _ws_lock:
        clients = list(_ws_clients)
    for ws in clients:
        try:
            asyncio.run_coroutine_threadsafe(ws.send_json(data), _event_loop)
        except Exception:
            pass


# ── Thread-safe tool tracking context manager ─────────────────────────────────
_track_lock = threading.Lock()  # FIX #5: serialise patch/restore of execute


@contextmanager
def track_tools(registry: ToolRegistry):
    """
    Context manager that wraps the registry's execute() to collect tool names
    used during the request.  Thread-safe — uses a local list and a lock to
    prevent concurrent patch/restore races.
    """
    import types
    tools_used: List[str] = []

    with _track_lock:
        # FIX #5: Save the *current* execute (class method or prior patch)
        # so we restore to exactly what was there before, even under concurrency.
        saved_execute = getattr(registry, 'execute', registry.__class__.execute)
        class_execute = registry.__class__.execute

        def patched_execute(self, tool_name: str, arguments: dict) -> str:
            tools_used.append(tool_name)
            return class_execute(self, tool_name, arguments)

        registry.execute = types.MethodType(patched_execute, registry)

    try:
        yield tools_used
    finally:
        with _track_lock:
            try:
                # Restore to the state before our patch
                if saved_execute is class_execute:
                    # Was the class method — just remove instance override
                    try:
                        del registry.execute
                    except AttributeError:
                        pass
                else:
                    # Was another patch — restore it
                    registry.execute = saved_execute
            except Exception:
                pass


# ── FastAPI app ─────────────────────────────────────────────────────────────────────

# FIX #9: Use lifespan instead of deprecated @app.on_event("startup")
@asynccontextmanager
async def lifespan(app):
    """Capture the event loop at startup for thread-safe WebSocket broadcasting."""
    global _event_loop
    _event_loop = asyncio.get_running_loop()
    
    # Bug #10: Start services inside lifespan to prevent startup race conditions
    reminder_service.start()
    if task_scheduler:
        task_scheduler._agent = agent
        task_scheduler.start()
        print("✅ Task scheduler and reminder service started in lifespan context")
    yield

app = FastAPI(title="Nova Assistant", version="2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"  # FIX #4: per-session history

class ChatResponse(BaseModel):
    response: str
    tools_used: List[str]
    turn: int
    requires_confirmation: Optional[dict] = None

class VoiceResponse(BaseModel):
    transcript: str
    response: str
    tools_used: List[str]
    turn: int

class MemoryFact(BaseModel):
    fact: str
    index: int

class MemoryResponse(BaseModel):
    facts: List[MemoryFact]
    count: int

class ReminderItem(BaseModel):
    time: str
    message: str
    created_at: str
    done: bool

class RemindersResponse(BaseModel):
    reminders: List[ReminderItem]
    pending: int

class HistoryMessage(BaseModel):
    role: str
    content: str

class HistoryResponse(BaseModel):
    messages: List[HistoryMessage]
    turn: int

class ConfirmRequest(BaseModel):
    request_id: str
    confirmed: bool

class WorkflowRequest(BaseModel):
    goal: str
    agents: Optional[List[str]] = None

class TaskCreateRequest(BaseModel):
    name: str
    goal: str
    trigger: str        # "interval", "cron", "date"
    trigger_args: dict  # e.g. {"minutes": 30} or {"hour": 9, "minute": 0}


# ── Chat endpoint ─────────────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Send a message to Nova and get a response."""
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # FIX #4: per-session conversation history
    session = _get_session(req.session_id or "default")
    session_history = session["history"]

    # FIX #8: Hold _chat_lock only for the minimal state mutation (turn counter
    # + snapshot), then release it before agent.run() so confirmation waits
    # don't block all other HTTP requests for up to 30 seconds.
    with _chat_lock:
        session["turn_count"] += 1
        current_turn = session["turn_count"]
        history_snapshot = list(session_history)

    # BUG FIX #2: thread-safe tool tracking via context manager
    with track_tools(tool_registry) as tools_used:
        # Phase 3: real confirmation callback — creates a pending confirmation
        # and waits up to 30s for the frontend to respond via /api/confirm
        confirmation_result = {}

        def web_confirm(tool_name: str, description: str) -> bool:
            req_id = str(uuid.uuid4())
            evt = threading.Event()
            with _confirm_lock:
                _pending_confirmations[req_id] = {"event": evt, "confirmed": False}

            # Push confirmation request to UI via WebSocket
            _ws_broadcast_sync({
                "type": "confirmation_required",
                "request_id": req_id,
                "tool_name": tool_name,
                "description": description,
            })
            confirmation_result["request_id"] = req_id
            confirmation_result["tool_name"] = tool_name
            confirmation_result["description"] = description

            print(f"   🛡️ Awaiting UI confirmation for: {tool_name} — {description}")
            granted = evt.wait(timeout=30)  # 30s timeout

            with _confirm_lock:
                result = _pending_confirmations.pop(req_id, {}).get("confirmed", False)

            if not granted:
                print(f"   ⏱️  Confirmation timed out for {tool_name} — denying")
                return False
            print(f"   {'✅' if result else '🚫'} Confirmation {'granted' if result else 'denied'} for {tool_name}")
            return result

        try:
            response_text = agent.run(
                user_message=message,
                conversation_history=history_snapshot,
                confirm_callback=web_confirm,
                mode="chat",
            )
        except Exception as e:
            print(f"❌ Agent error: {e}")
            raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

    # Update conversation history (re-acquire lock for the mutation)
    with _chat_lock:
        session_history.append({"role": "user", "content": message})
        session_history.append({"role": "assistant", "content": response_text})

        # Trim history to window
        if len(session_history) > MAX_HISTORY_TURNS * 2:
            del session_history[:2]

    # Extract user facts in background
    threading.Thread(
        target=memory.extract_and_store,
        args=(message, response_text, client),
        daemon=True,
    ).start()

    return ChatResponse(
        response=response_text,
        tools_used=tools_used,
        turn=current_turn,
        requires_confirmation=confirmation_result if confirmation_result else None,
    )


# ── Voice endpoint ────────────────────────────────────────────────────────────

@app.post("/api/voice", response_model=VoiceResponse)
async def voice_chat(file: UploadFile = File(...)):
    """Upload an audio file, transcribe it, and process through the agent."""
    import tempfile

    suffix = os.path.splitext(file.filename)[1] if file.filename else ".webm"
    if not suffix:
        suffix = ".webm"

    # FIX #6: Ensure the temp file is always closed before unlink, even on
    # exception.  On Windows, os.unlink() raises PermissionError if the
    # file handle is still open.
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = temp_file.name
    try:
        try:
            contents = await file.read()
            temp_file.write(contents)
        finally:
            temp_file.close()  # always close, even on error

        print(f"   📝 Transcribing uploaded voice: {file.filename} ({len(contents)} bytes) ...")
        with open(temp_path, 'rb') as f:
            transcript = client.audio.transcriptions.create(
                file=(temp_path, f.read()),
                model="whisper-large-v3",
                language="en",
                response_format="text",
            )

        transcript_text = transcript.strip()
        print(f"   📝 Transcribed text: '{transcript_text}'")

        hallucinations = {"you", "you you you", "thank you", "thank you.", "thanks for watching", "thank you for watching"}
        if not transcript_text or transcript_text.lower().strip() in hallucinations:
            print("   ⚠️ Empty transcription or detected silent hallucination pattern.")
            raise HTTPException(status_code=400, detail="Could not detect speech, please try again")

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Transcription/Upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription error: {str(e)}")
    finally:
        try:
            os.unlink(temp_path)
        except Exception:
            pass

    # FIX #4: per-session history (voice uses 'default' session)
    session = _get_session("default")
    session_history = session["history"]

    # FIX #8: minimal lock scope — snapshot under lock, run agent outside lock
    with _chat_lock:
        session["turn_count"] += 1
        current_turn = session["turn_count"]
        history_snapshot = list(session_history)

    with track_tools(tool_registry) as tools_used:
        def web_confirm_voice(tool_name: str, description: str) -> bool:
            print(f"   🛡️ Auto-approved (voice): {tool_name} — {description}")
            return True

        try:
            response_text = agent.run(
                user_message=transcript_text,
                conversation_history=history_snapshot,
                confirm_callback=web_confirm_voice,
                mode="voice",
            )
        except Exception as e:
            print(f"❌ Agent error: {e}")
            raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

    with _chat_lock:
        session_history.append({"role": "user", "content": transcript_text})
        session_history.append({"role": "assistant", "content": response_text})

        if len(session_history) > MAX_HISTORY_TURNS * 2:
            del session_history[:2]

    threading.Thread(
        target=memory.extract_and_store,
        args=(transcript_text, response_text, client),
        daemon=True,
    ).start()

    return VoiceResponse(
        transcript=transcript_text,
        response=response_text,
        tools_used=tools_used,
        turn=current_turn,
    )


# ── Confirmation endpoint (guardrail modal) ───────────────────────────────────

@app.post("/api/confirm")
def confirm_tool(req: ConfirmRequest):
    """Frontend sends user's yes/no decision for a guardrailed tool call."""
    with _confirm_lock:
        pending = _pending_confirmations.get(req.request_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Confirmation request not found or expired")
    pending["confirmed"] = req.confirmed
    pending["event"].set()
    return {"status": "ok", "confirmed": req.confirmed}


# ── Memory endpoints ──────────────────────────────────────────────────────────

@app.get("/api/memory", response_model=MemoryResponse)
def get_memory():
    with memory._lock:
        facts = [MemoryFact(fact=f, index=i) for i, f in enumerate(memory._facts)]
    return MemoryResponse(facts=facts, count=len(facts))


@app.delete("/api/memory")
def clear_memory():
    with memory._lock:
        count = len(memory._facts)
        memory._facts.clear()
        memory._save_unlocked()
    return {"deleted": count, "status": "ok"}


@app.delete("/api/memory/{index}")
def delete_memory(index: int):
    with memory._lock:
        if index < 0 or index >= len(memory._facts):
            raise HTTPException(status_code=404, detail="Memory index out of range")
        removed = memory._facts.pop(index)
        memory._save_unlocked()
    return {"deleted": removed, "status": "ok"}


# ── Reminders endpoint ────────────────────────────────────────────────────────

@app.get("/api/reminders", response_model=RemindersResponse)
def get_reminders():
    with reminder_service._lock:
        items = [
            ReminderItem(
                time=r.get("time", ""),
                message=r.get("message", ""),
                created_at=r.get("created_at", ""),
                done=r.get("done", False),
            )
            for r in reminder_service._reminders
        ]
        pending = sum(1 for r in reminder_service._reminders if not r.get("done"))
    return RemindersResponse(reminders=items, pending=pending)


# ── History endpoint ──────────────────────────────────────────────────────────

@app.get("/api/history", response_model=HistoryResponse)
def get_history(session_id: str = "default"):
    # FIX #4: per-session history
    session = _get_session(session_id)
    messages = [
        HistoryMessage(role=m["role"], content=m["content"])
        for m in session["history"]
    ]
    return HistoryResponse(messages=messages, turn=session["turn_count"])


@app.delete("/api/history")
def clear_history(session_id: str = "default"):
    # FIX #4: per-session history
    session = _get_session(session_id)
    with _chat_lock:
        session["history"].clear()
        session["turn_count"] = 0
    return {"status": "ok"}


# ── Documents / RAG endpoints ─────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload a PDF and index it for RAG search."""
    if rag_retriever is None:
        raise HTTPException(status_code=503, detail="RAG not available — install chromadb, sentence-transformers, pymupdf")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    import tempfile
    contents = await file.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(contents)
    tmp.close()

    try:
        doc_id, chunk_count = rag_retriever.index_pdf(tmp.name, filename=file.filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF indexing failed: {str(e)}")
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    return {"doc_id": doc_id, "filename": file.filename, "chunks": chunk_count, "status": "indexed"}


@app.get("/api/documents")
def list_documents():
    """List all indexed documents."""
    if rag_retriever is None:
        return {"documents": [], "available": False}
    try:
        docs = rag_retriever.list_documents()
        return {"documents": docs, "available": True}
    except Exception as e:
        return {"documents": [], "available": True, "error": str(e)}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    """Remove a document from the index."""
    if rag_retriever is None:
        raise HTTPException(status_code=503, detail="RAG not available")
    try:
        rag_retriever.delete_document(doc_id)
        return {"status": "ok", "deleted": doc_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Multi-agent Workflow endpoint ─────────────────────────────────────────────

@app.post("/api/workflow")
def run_workflow(req: WorkflowRequest):
    """Run a multi-agent workflow for a complex goal."""
    confirmation_result = {}

    def web_confirm(tool_name: str, description: str) -> bool:
        req_id = str(uuid.uuid4())
        evt = threading.Event()
        with _confirm_lock:
            _pending_confirmations[req_id] = {"event": evt, "confirmed": False}

        # Push confirmation request to UI via WebSocket
        _ws_broadcast_sync({
            "type": "confirmation_required",
            "request_id": req_id,
            "tool_name": tool_name,
            "description": description,
        })
        confirmation_result["request_id"] = req_id
        confirmation_result["tool_name"] = tool_name
        confirmation_result["description"] = description

        print(f"   🛡️ Awaiting UI confirmation (workflow) for: {tool_name} — {description}")
        granted = evt.wait(timeout=30)  # 30s timeout

        with _confirm_lock:
            result = _pending_confirmations.pop(req_id, {}).get("confirmed", False)

        if not granted:
            print(f"   ⏱️  Confirmation timed out for {tool_name} — denying")
            return False
        print(f"   {'✅' if result else '🚫'} Confirmation {'granted' if result else 'denied'} for {tool_name}")
        return result

    if orchestrator is None:
        # Fall back to single agent
        session = _get_session("default")
        with _chat_lock:
            session["turn_count"] += 1
            current_turn = session["turn_count"]
            history_snapshot = list(session["history"])
        with track_tools(tool_registry) as tools_used:
            try:
                response_text = agent.run(
                    user_message=req.goal,
                    conversation_history=history_snapshot,
                    confirm_callback=web_confirm,
                    mode="chat",
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        return {
            "result": response_text,
            "tools_used": tools_used,
            "turn": current_turn,
            "agents_used": ["nova"],
            "requires_confirmation": confirmation_result if confirmation_result else None
        }

    try:
        result = orchestrator.run_workflow(req.goal, agents=req.agents, confirm_callback=web_confirm)
        if confirmation_result:
            result["requires_confirmation"] = confirmation_result
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── WebSocket for live updates ────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    with _ws_lock:
        _ws_clients.append(websocket)
    try:
        while True:
            # Keep alive — listen for any incoming messages
            data = await websocket.receive_text()
            # Handle ping
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        with _ws_lock:
            if websocket in _ws_clients:
                _ws_clients.remove(websocket)


# ── Scheduled Tasks endpoints ─────────────────────────────────────────────────

@app.get("/api/tasks")
def list_tasks():
    if task_scheduler is None:
        return {"tasks": [], "available": False}
    return {"tasks": task_scheduler.list_tasks(), "available": True}


@app.post("/api/tasks")
def create_task(req: TaskCreateRequest):
    if task_scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available — install apscheduler")
    try:
        session = _get_session("default")
        task_id = task_scheduler.schedule_task(
            name=req.name,
            goal=req.goal,
            trigger=req.trigger,
            trigger_args=req.trigger_args,
            agent=agent,
            conversation_history=session["history"],
        )
        return {"task_id": task_id, "status": "scheduled"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/tasks/{task_id}")
def cancel_task(task_id: str):
    if task_scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    ok = task_scheduler.cancel_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "cancelled", "task_id": task_id}


# ── MCP Plugin endpoints ──────────────────────────────────────────────────────

@app.get("/api/mcp/servers")
def list_mcp_servers():
    """List all registered MCP-style plugin servers."""
    if mcp_adapter is None:
        return {
            "servers": [],
            "available": False,
            "error": mcp_error or "MCP adapter not initialized"
        }
    return {"servers": mcp_adapter.list_servers(), "available": True}


@app.get("/api/mcp/servers/{server_name}/tools")
def list_mcp_server_tools(server_name: str):
    """List tools registered for a specific MCP server."""
    if mcp_adapter is None:
        raise HTTPException(
            status_code=503,
            detail=f"MCP adapter not initialized. Reason: {mcp_error or 'Not loaded'}"
        )
    server = mcp_adapter.get_server(server_name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")
    
    tools = []
    for tool_name in server.list_tools():
        tool = server.get_tool(tool_name)
        if tool:
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "requires_confirmation": tool.requires_confirmation
            })
    return {"server": server_name, "tools": tools}


@app.post("/api/mcp/servers/{server_name}/tools/{tool_name}/execute")
def execute_mcp_tool(server_name: str, tool_name: str, arguments: dict):
    """Execute an MCP tool directly."""
    if mcp_adapter is None:
        raise HTTPException(
            status_code=503,
            detail=f"MCP adapter not initialized. Reason: {mcp_error or 'Not loaded'}"
        )
    server = mcp_adapter.get_server(server_name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")
    
    tool = server.get_tool(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"MCP tool '{tool_name}' not found on server '{server_name}'")
        
    try:
        result = mcp_adapter.execute(server_name, tool_name, arguments)
        return json.loads(result)
    except json.JSONDecodeError:
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/status")
def get_system_status():
    """Get the status of all assistant modules."""
    # 1. RAG status
    rag_ok = False
    if rag_retriever is not None:
        rag_ok = True
        
    # 2. Scheduler status
    scheduler_ok = False
    if task_scheduler is not None:
        scheduler_ok = True
        
    # 3. Browser status
    browser_ok = False
    try:
        from playwright.sync_api import sync_playwright
        browser_ok = True
    except ImportError:
        pass
        
    # 4. MCP / Email / Calendar status
    mcp_ok = mcp_adapter is not None
    email_ok = False
    calendar_ok = False
    if mcp_ok:
        email_ok = mcp_adapter.get_server("email") is not None
        calendar_ok = mcp_adapter.get_server("calendar") is not None
        
    return {
        "browser": {"available": browser_ok, "status": "ready" if browser_ok else "unavailable"},
        "email": {"available": email_ok, "status": "ready" if email_ok else "unavailable"},
        "calendar": {"available": calendar_ok, "status": "ready" if calendar_ok else "unavailable"},
        "rag": {"available": rag_ok, "status": "ready" if rag_ok else "unavailable"},
        "scheduler": {"available": scheduler_ok, "status": "ready" if scheduler_ok else "unavailable"},
        "mcp": {
            "available": mcp_ok,
            "error": mcp_error
        }
    }


# ── Serve the UI ──────────────────────────────────────────────────────────────

ui_dir = os.path.join(os.path.dirname(__file__), "ui")
app.mount("/static", StaticFiles(directory=ui_dir), name="static")


@app.get("/")
def serve_ui():
    return FileResponse(os.path.join(ui_dir, "index.html"))




# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("\n🌐 Starting Nova Web Server on http://localhost:8000")
    print("   Open your browser to http://localhost:8000")
    print("─" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
