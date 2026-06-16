from typing import Optional, List, Dict, Any
import json
from groq import Groq

class GroqLLMClient:
    """Ultra-fast LLM client using Groq's LPU inference"""
    
    def __init__(self, api_key: str, model: str = "llama3-70b-8192",
                 temperature: float = 0.7, max_tokens: int = 1024,
                 top_p: float = 1.0):
        
        self.client = Groq(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        
        # Available models on Groq
        self.available_models = {
            "llama3-70b-8192": "Meta Llama 3 70B (fastest, most capable)",
            "llama3-8b-8192": "Meta Llama 3 8B (faster, smaller)",
            "mixtral-8x7b-32768": "Mixtral 8x7B (great for complex tasks)",
            "gemma2-9b-it": "Google Gemma 2 9B",
            "llama-3.1-70b-versatile": "Llama 3.1 70B (latest)"
        }
        
        print(f"✅ Groq client initialized")
        print(f"   Model: {self.model}")
        print(f"   Speed: Up to 500 tokens/sec on LPU")
    
    def chat(self, messages: List[Dict[str, str]], 
             tools: Optional[List[Dict]] = None,
             tool_choice: str = "auto") -> Dict[str, Any]:
        """
        Send chat messages to Groq.
        Returns response with optional tool_calls.
        """
        
        try:
            # Prepare request parameters
            params = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "top_p": self.top_p,
                "stream": False
            }
            
            # Add tools if provided (Groq supports native tool calling)
            if tools:
                params["tools"] = tools
                params["tool_choice"] = tool_choice
            
            # Make API call
            response = self.client.chat.completions.create(**params)
            choice = response.choices[0]
            
            # Parse response
            result = {
                "content": choice.message.content or "",
                "tool_calls": [],
                "finish_reason": choice.finish_reason,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }
            
            # Extract tool calls if present
            if hasattr(choice.message, 'tool_calls') and choice.message.tool_calls:
                for tool_call in choice.message.tool_calls:
                    result["tool_calls"].append({
                        "id": tool_call.id,
                        "name": tool_call.function.name,
                        "arguments": json.loads(tool_call.function.arguments)
                    })
            
            return result
            
        except Exception as e:
            print(f"❌ Groq API error: {e}")
            return {
                "content": f"I'm having trouble connecting to my language model. Please try again.",
                "tool_calls": [],
                "error": str(e)
            }
    
    def stream_chat(self, messages: List[Dict[str, str]]):
        """Stream responses token by token (for real-time voice feedback)"""
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True
            )
            
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            print(f"❌ Groq streaming error: {e}")
            yield "I encountered an error. Please try again."


class GroqWithTools(GroqLLMClient):
    """Extended Groq client with pre-configured common tools"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Common tool definitions
        self.common_tools = {
            "get_current_time": {
                "type": "function",
                "function": {
                    "name": "get_current_time",
                    "description": "Get the current date and time",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            "get_weather": {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "City name or location"
                            }
                        },
                        "required": ["location"]
                    }
                }
            }
        }
    
    def chat_with_common_tools(self, messages, enable_tools=None):
        """Chat with pre-configured tools"""
        if enable_tools is None:
            enable_tools = ["get_current_time"]
        
        tools = [self.common_tools[tool] for tool in enable_tools if tool in self.common_tools]
        return self.chat(messages, tools=tools)