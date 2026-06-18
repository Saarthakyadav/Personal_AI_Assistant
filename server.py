# server.py
"""
Nova Web Server — FastAPI entry point for the Nova UI.

Reuses the same AgentCore, UserMemory, ToolRegistry, and ReminderService
as main.py, but serves them over HTTP instead of voice.
"""

import sys
import io
import os

# Force UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import threading
import json

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
for tool in ALL_BUILTIN_TOOLS:
    tool_registry.register(tool)

# Reminder service — uses a no-op speak callback since the UI handles display
def _web_speak(text: str):
    """No-op TTS for web mode — the UI displays text directly."""
    print(f"🔔 Reminder (web): {text}")

reminder_service = ReminderService(
    filepath=os.path.join(os.path.dirname(__file__), "reminders.json"),
    speak_callback=_web_speak,
)
reminder_tool = create_reminder_tool(reminder_service)
tool_registry.register(reminder_tool)
reminder_service.start()
print(f"✅ Tools ready: {tool_registry.tool_names}")

# Agent core
agent = AgentCore(
    groq_client=client,
    memory=memory,
    tool_registry=tool_registry,
    max_steps=5,
)
print("✅ Agent core ready")

# Conversation state
MAX_HISTORY_TURNS = 10
conversation_history: list = []
turn_count = 0
_chat_lock = threading.Lock()


# ── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(title="Nova Assistant", version="1.0")


# ── Request / Response models ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    tools_used: List[str]
    turn: int

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


# ── Chat endpoint ────────────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Send a message to Nova and get a response."""
    global turn_count

    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    with _chat_lock:
        turn_count += 1

        # Track which tools the agent uses during this request
        tools_used = []
        original_execute = tool_registry.execute

        def tracking_execute(tool_name: str, arguments: dict) -> str:
            tools_used.append(tool_name)
            return original_execute(tool_name, arguments)

        # Temporarily patch execute to track tool usage
        tool_registry.execute = tracking_execute

        try:
            # Auto-approve guardrailed tools from web UI
            def web_confirm(tool_name: str, description: str) -> bool:
                print(f"   🛡️ Auto-approved (web): {tool_name} — {description}")
                return True

            response_text = agent.run(
                user_message=message,
                conversation_history=conversation_history,
                confirm_callback=web_confirm,
            )
        except Exception as e:
            print(f"❌ Agent error: {e}")
            raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")
        finally:
            # Restore original execute
            tool_registry.execute = original_execute

        # Update conversation history
        conversation_history.append({"role": "user", "content": message})
        conversation_history.append({"role": "assistant", "content": response_text})

        # Trim history to window
        if len(conversation_history) > MAX_HISTORY_TURNS * 2:
            del conversation_history[:2]

        turn_count += 1

        # Extract user facts in background
        threading.Thread(
            target=memory.extract_and_store,
            args=(message, response_text, client),
            daemon=True,
        ).start()

    return ChatResponse(
        response=response_text,
        tools_used=tools_used,
        turn=turn_count,
    )


# ── Voice endpoint ───────────────────────────────────────────────────────────

@app.post("/api/voice", response_model=VoiceResponse)
async def voice_chat(file: UploadFile = File(...)):
    """Upload an audio file, transcribe it, and process through the agent."""
    global turn_count

    import tempfile
    
    suffix = os.path.splitext(file.filename)[1] if file.filename else ".webm"
    if not suffix:
        suffix = ".webm"
        
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = temp_file.name
    try:
        contents = await file.read()
        temp_file.write(contents)
        temp_file.close()

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

        if not transcript_text:
            raise HTTPException(status_code=400, detail="Could not transcribe audio or audio was empty")

    except Exception as e:
        print(f"❌ Transcription/Upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription error: {str(e)}")
    finally:
        try:
            os.unlink(temp_path)
        except Exception:
            pass

    with _chat_lock:
        turn_count += 1

        tools_used = []
        original_execute = tool_registry.execute

        def tracking_execute(tool_name: str, arguments: dict) -> str:
            tools_used.append(tool_name)
            return original_execute(tool_name, arguments)

        tool_registry.execute = tracking_execute

        try:
            def web_confirm(tool_name: str, description: str) -> bool:
                print(f"   🛡️ Auto-approved (web): {tool_name} — {description}")
                return True

            response_text = agent.run(
                user_message=transcript_text,
                conversation_history=conversation_history,
                confirm_callback=web_confirm,
            )
        except Exception as e:
            print(f"❌ Agent error: {e}")
            raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")
        finally:
            tool_registry.execute = original_execute

        conversation_history.append({"role": "user", "content": transcript_text})
        conversation_history.append({"role": "assistant", "content": response_text})

        if len(conversation_history) > MAX_HISTORY_TURNS * 2:
            del conversation_history[:2]

        turn_count += 1

        threading.Thread(
            target=memory.extract_and_store,
            args=(transcript_text, response_text, client),
            daemon=True,
        ).start()

    return VoiceResponse(
        transcript=transcript_text,
        response=response_text,
        tools_used=tools_used,
        turn=turn_count,
    )


# ── Memory endpoints ─────────────────────────────────────────────────────────

@app.get("/api/memory", response_model=MemoryResponse)
def get_memory():
    """Get all stored user facts."""
    with memory._lock:
        facts = [
            MemoryFact(fact=f, index=i)
            for i, f in enumerate(memory._facts)
        ]
    return MemoryResponse(facts=facts, count=len(facts))


@app.delete("/api/memory")
def clear_memory():
    """Clear all memory facts."""
    with memory._lock:
        count = len(memory._facts)
        memory._facts.clear()
        memory._save_unlocked()
    return {"deleted": count, "status": "ok"}


@app.delete("/api/memory/{index}")
def delete_memory(index: int):
    """Delete a single memory fact by index."""
    with memory._lock:
        if index < 0 or index >= len(memory._facts):
            raise HTTPException(status_code=404, detail="Memory index out of range")
        removed = memory._facts.pop(index)
        memory._save_unlocked()
    return {"deleted": removed, "status": "ok"}


# ── Reminders endpoint ───────────────────────────────────────────────────────

@app.get("/api/reminders", response_model=RemindersResponse)
def get_reminders():
    """Get all reminders."""
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
def get_history():
    """Get conversation history."""
    messages = [
        HistoryMessage(role=m["role"], content=m["content"])
        for m in conversation_history
    ]
    return HistoryResponse(messages=messages, turn=turn_count)


@app.delete("/api/history")
def clear_history():
    """Clear conversation history."""
    global turn_count
    with _chat_lock:
        conversation_history.clear()
        turn_count = 0
    return {"status": "ok"}


# ── Serve the UI ──────────────────────────────────────────────────────────────

ui_dir = os.path.join(os.path.dirname(__file__), "ui")

# Serve static files (CSS, JS)
app.mount("/static", StaticFiles(directory=ui_dir), name="static")


@app.get("/")
def serve_ui():
    """Serve the Nova UI."""
    return FileResponse(os.path.join(ui_dir, "index.html"))


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("\n🌐 Starting Nova Web Server on http://localhost:8000")
    print("   Open your browser to http://localhost:8000")
    print("─" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
