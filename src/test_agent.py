# src/test_agent.py
import unittest
import json
from unittest.mock import MagicMock

from src.agent import AgentCore
from src.tools import Tool, ToolRegistry

# Create some mock tools
def fake_weather(location: str):
    return f"Weather in {location} is sunny."

WEATHER_TOOL = Tool(
    name="get_weather",
    description="Get weather",
    parameters={"type": "object", "properties": {"location": {"type": "string"}}},
    handler=fake_weather,
    requires_confirmation=False
)

def fake_send_email(to: str, subject: str, body: str):
    return f"Email sent to {to}"

SEND_EMAIL_TOOL = Tool(
    name="send_email",
    description="Send an email",
    parameters={"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}},
    handler=fake_send_email,
    requires_confirmation=True
)

class MockGroqResponse:
    def __init__(self, content, tool_calls=None):
        self.choices = [MagicMock()]
        self.choices[0].message = MagicMock()
        self.choices[0].message.content = content
        self.choices[0].message.tool_calls = tool_calls

class MockToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = json.dumps(arguments)

class TestAgentCore(unittest.TestCase):
    def setUp(self):
        self.mock_memory = MagicMock()
        self.mock_memory.get_facts_prompt.return_value = "User is named Sam."
        
        self.registry = ToolRegistry()
        self.registry.register(WEATHER_TOOL)
        self.registry.register(SEND_EMAIL_TOOL)
        
        self.mock_groq = MagicMock()
        
        self.agent = AgentCore(
            groq_client=self.mock_groq,
            memory=self.mock_memory,
            tool_registry=self.registry,
            max_steps=3
        )

    def test_direct_text_response(self):
        """Test when the LLM just answers directly with text."""
        self.mock_groq.chat.completions.create.return_value = MockGroqResponse(
            content="Hello Sam! I am doing well."
        )
        
        result = self.agent.run("How are you?", [])
        self.assertEqual(result, "Hello Sam! I am doing well.")
        
    def test_tool_call_weather(self):
        """Test when the LLM calls a tool without needing confirmation."""
        # Step 1: LLM wants to call weather
        tool_call = MockToolCall("call_123", "get_weather", {"location": "London"})
        step1_response = MockGroqResponse(content=None, tool_calls=[tool_call])
        
        # Step 2: LLM summarizes the weather
        step2_response = MockGroqResponse(content="It is currently sunny in London.")
        
        self.mock_groq.chat.completions.create.side_effect = [step1_response, step2_response]
        
        result = self.agent.run("What's the weather in London?", [])
        self.assertEqual(result, "It is currently sunny in London.")
        
    def test_tool_call_requires_confirmation_approved(self):
        """Test an email tool call that requires user confirmation (approved)."""
        tool_call = MockToolCall("call_email", "send_email", {"to": "bob@test.com", "subject": "Hi", "body": "Hello"})
        step1_response = MockGroqResponse(content=None, tool_calls=[tool_call])
        step2_response = MockGroqResponse(content="I have sent the email to Bob.")
        
        self.mock_groq.chat.completions.create.side_effect = [step1_response, step2_response]
        
        # Mock the user saying YES
        def mock_confirm(tool_name, desc):
            return True
            
        result = self.agent.run("Send email to Bob", [], confirm_callback=mock_confirm)
        self.assertEqual(result, "I have sent the email to Bob.")
        
    def test_tool_call_requires_confirmation_denied(self):
        """Test an email tool call where the user denies confirmation."""
        tool_call = MockToolCall("call_email", "send_email", {"to": "bob@test.com", "subject": "Hi", "body": "Hello"})
        step1_response = MockGroqResponse(content=None, tool_calls=[tool_call])
        step2_response = MockGroqResponse(content="Okay, I cancelled sending the email.")
        
        self.mock_groq.chat.completions.create.side_effect = [step1_response, step2_response]
        
        # Mock the user saying NO
        def mock_confirm(tool_name, desc):
            return False
            
        result = self.agent.run("Send email to Bob", [], confirm_callback=mock_confirm)
        self.assertEqual(result, "Okay, I cancelled sending the email.")

if __name__ == "__main__":
    unittest.main()
