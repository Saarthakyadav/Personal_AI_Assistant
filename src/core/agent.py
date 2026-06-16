from typing import Optional, List, Dict, Any
import json
from datetime import datetime
from .groq_llm import GroqLLMClient
from .memory import ConversationMemory, ShortTermMemory

class AgentCore:
    """Enhanced agent with free memory and tool calling"""
    
    def __init__(self, llm_client: GroqLLMClient, config, tools: Optional[Dict] = None):
        self.llm = llm_client
        self.config = config
        self.tools = tools or {}
        
        # Free memory systems (no API keys)
        self.long_term_memory = ConversationMemory()
        self.short_term_memory = ShortTermMemory()
        
        self.current_step = 0
        self.max_steps = config.max_steps
    
    def process(self, user_input: str) -> str:
        """Process user input with memory and tools"""
        
        self.current_step = 0
        
        # Search relevant memories
        relevant_memories = self.long_term_memory.search(user_input, n_results=3)
        recent_context = self.short_term_memory.get_all()
        
        # Build messages with memory
        messages = self._build_messages(user_input, recent_context, relevant_memories)
        
        # Reasoning loop
        while self.current_step < self.max_steps:
            self.current_step += 1
            
            # Get LLM response
            response = self.llm.chat(
                messages=messages,
                tools=self._format_tools()
            )
            
            # Handle tool calls
            if response.get("tool_calls"):
                tool_results = self._execute_tools(response["tool_calls"])
                
                # Add tool results to conversation
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": response["tool_calls"]
                })
                messages.append({
                    "role": "tool",
                    "content": json.dumps(tool_results)
                })
                continue
            
            # Final response
            final_response = response.get("content", "I'm not sure how to respond.")
            
            # Save to memory
            self.short_term_memory.add("user", user_input)
            self.short_term_memory.add("assistant", final_response)
            self.long_term_memory.add_user_message(user_input)
            self.long_term_memory.add_assistant_message(final_response)
            
            return final_response
        
        return self._fallback(user_input)
    
    def _build_messages(self, user_input: str, recent: List[Dict], memories: List[Dict]) -> List[Dict]:
        """Build context messages with memory"""
        
        messages = [
            {"role": "system", "content": self.config.system_prompt}
        ]
        
        # Add relevant long-term memories
        if memories:
            memory_text = "Relevant past information:\n"
            for mem in memories[:3]:
                if 'content' in mem:
                    memory_text += f"- {mem['content'][:150]}\n"
            messages.append({"role": "system", "content": memory_text})
        
        # Add recent conversation
        messages.extend(recent[-10:])
        
        # Add current query
        messages.append({"role": "user", "content": user_input})
        
        return messages
    
    def _format_tools(self) -> Optional[List[Dict]]:
        """Format tools for Groq API"""
        if not self.tools:
            return None
        
        tool_definitions = []
        for name, tool in self.tools.items():
            tool_definitions.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {
                        "type": "object",
                        "properties": {},
                        "required": []
                    })
                }
            })
        return tool_definitions
    
    def _execute_tools(self, tool_calls: List[Dict]) -> List[Dict]:
        """Execute tool calls"""
        results = []
        
        for tool_call in tool_calls:
            tool_name = tool_call.get("function", {}).get("name")
            arguments = tool_call.get("function", {}).get("arguments", {})
            
            if tool_name not in self.tools:
                results.append({"error": f"Tool '{tool_name}' not found"})
                continue
            
            try:
                tool_func = self.tools[tool_name].get("function")
                if tool_func:
                    result = tool_func(**arguments)
                    results.append({"result": result})
                else:
                    results.append({"error": "No function defined"})
            except Exception as e:
                results.append({"error": str(e)})
        
        return results
    
    def _fallback(self, user_input: str) -> str:
        """Fallback when max steps exceeded"""
        return "I'm having trouble with that. Could you rephrase or try something simpler?"