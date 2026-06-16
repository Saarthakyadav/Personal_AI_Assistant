from typing import Optional, Dict, Any, List
from datetime import datetime
import json

from .llm import LLMClient
from .context import ContextBuilder

class AgentCore:
    """The Brain - handles reasoning loop, tool calling, and guardrails"""
    
    def __init__(self, llm_client: LLMClient, config, tools: Optional[List] = None):
        self.llm = llm_client
        self.config = config
        self.tools = tools or {}
        self.context_builder = ContextBuilder(config.system_prompt)
        
        # State tracking
        self.memory: List[Dict] = []  # Chat history
        self.current_step = 0
        self.max_steps = config.max_steps
    
    def process(self, user_input: str) -> str:
        """Main entry point - process user input and return response"""
        
        self.current_step = 0
        context = self.context_builder.build(user_input, self.memory)
        
        # Reason loop
        while self.current_step < self.max_steps:
            self.current_step += 1
            
            # Call LLM to decide next action
            response = self.llm.chat(
                messages=context["messages"],
                tools=self._format_tools()
            )
            
            # Check if we need to call a tool
            if response.get("tool_calls"):
                tool_results = self._execute_tools(response["tool_calls"])
                
                # Add tool results to context and continue
                for result in tool_results:
                    context["messages"].append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": response["tool_calls"]
                    })
                    context["messages"].append({
                        "role": "tool",
                        "tool_call_id": result.get("id", ""),
                        "content": json.dumps(result)
                    })
                
                # Continue loop to let LLM process tool results
                continue
            
            # No tool calls - we have our answer
            final_response = response.get("content", "I'm not sure how to respond.")
            
            # Save to memory
            self.memory.append({"role": "user", "content": user_input})
            self.memory.append({"role": "assistant", "content": final_response})
            
            return final_response
        
        # Max steps exceeded
        return self._graceful_fallback(user_input)
    
    def _format_tools(self) -> List[Dict]:
        """Format tools for LLM API"""
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
        """Execute tool calls with guardrail checks"""
        results = []
        
        for tool_call in tool_calls:
            tool_name = tool_call.get("name")
            arguments = tool_call.get("arguments", {})
            
            if tool_name not in self.tools:
                results.append({
                    "id": tool_call.get("id"),
                    "error": f"Tool '{tool_name}' not found"
                })
                continue
            
            tool_info = self.tools[tool_name]
            
            # Check if irreversible action
            if tool_info.get("irreversible", False):
                # Speak confirmation (this would use TTS in real implementation)
                print(f"⚠️ Confirmation required for: {tool_name}")
                # In Phase 1, we just print; Phase 3 will implement full guardrail
                confirmation = input(f"Confirm {tool_name} {arguments}? (yes/no): ")
                if confirmation.lower() != "yes":
                    results.append({
                        "id": tool_call.get("id"),
                        "result": "Action cancelled by user"
                    })
                    continue
            
            # Execute tool
            try:
                tool_func = tool_info.get("function")
                if tool_func:
                    result = tool_func(**arguments)
                    results.append({
                        "id": tool_call.get("id"),
                        "result": result
                    })
                else:
                    results.append({
                        "id": tool_call.get("id"),
                        "error": f"No function defined for tool '{tool_name}'"
                    })
            except Exception as e:
                results.append({
                    "id": tool_call.get("id"),
                    "error": f"Tool execution failed: {str(e)}"
                })
        
        return results
    
    def _graceful_fallback(self, user_input: str) -> str:
        """Fallback when max steps exceeded"""
        fallback = "I'm having trouble processing that request. Could you simplify it or try again?"
        self.memory.append({"role": "user", "content": user_input})
        self.memory.append({"role": "assistant", "content": fallback})
        return fallback