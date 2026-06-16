import os
from dotenv import load_dotenv
from dataclasses import dataclass

load_dotenv()

@dataclass
class AudioConfig:
    sample_rate: int = 16000
    frame_duration_ms: int = 30
    silence_timeout: float = 1.5
    wake_words: list = None
    
    def __post_init__(self):
        if self.wake_words is None:
            # FREE wake words - no API key needed!
            self.wake_words = ["computer", "alexa", "hey jarvis"]


@dataclass
class STTConfig:
    model: str = "base"  # tiny, base, small, medium, large
    device: str = "cpu"
    compute_type: str = "int8"


@dataclass
class TTSConfig:
    engine: str = "piper"  # Free, local TTS
    piper_model: str = "en_US-lessac-medium"
    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_voice: str = "Rachel"


@dataclass
class GroqConfig:
    api_key: str = os.getenv("GROQ_API_KEY", "")
    model: str = "llama3-70b-8192"
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float = 1.0
    
    def __post_init__(self):
        if not self.api_key:
            print("⚠️ GROQ_API_KEY not found. Get one from https://console.groq.com")
            print("   For free local alternative, install Ollama: https://ollama.ai")


@dataclass
class AgentConfig:
    max_steps: int = 5
    system_prompt: str = """You are Agentic, a helpful voice assistant.

Guidelines:
- Be concise and conversational (voice interface)
- Answer directly without markdown or lists
- Keep responses under 3 sentences when possible
- Remember what users tell you using your memory tools
- If you don't know something, say so honestly

You have memory tools:
- Use remember_fact to store information users share
- Use recall_memory to retrieve past information

Current time: {time}
"""