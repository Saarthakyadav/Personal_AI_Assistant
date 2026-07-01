import os
from dotenv import load_dotenv
load_dotenv()

from groq import Groq
from src.agent import AgentCore
from src.memory import UserMemory
from src.tools import ToolRegistry

# Import all tools
from src.tools.general_tools import GENERAL_TOOLS
from src.tools.builtins import ALL_BUILTIN_TOOLS
from src.tools.browser import BROWSER_TOOLS

# Import Google tools via Plugin Adapter
from src.tools.plugin_adapter import PluginAdapter
from src.tools.email_tool import EMAIL_TOOLS
from src.tools.calendar_tool import CALENDAR_TOOLS

def run_cli():
    print("🧠 Booting up Nova's Brain (Stage 4 Tester)...")
    
    # 1. Initialize Memory
    memory = UserMemory()
    
    # 2. Setup Tool Registry
    registry = ToolRegistry()
    for tool in GENERAL_TOOLS:
        registry.register(tool)
    for tool in ALL_BUILTIN_TOOLS:
        registry.register(tool)
    for tool in BROWSER_TOOLS:
        registry.register(tool)
    
    # Setup Plugin Adapter for Google Tools
    plugin = PluginAdapter()
    plugin.register_tools("email", EMAIL_TOOLS)
    plugin.register_tools("calendar", CALENDAR_TOOLS)
    plugin.install_into_registry(registry)
    
    # 3. Setup Groq LLM
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        print("❌ Error: GROQ_API_KEY is missing from your .env file!")
        return
        
    client = Groq(api_key=groq_api_key)
    
    # 4. Initialize AgentCore
    agent = AgentCore(
        groq_client=client,
        memory=memory,
        tool_registry=registry
    )
    
    history = []
    
    print("\n✅ System Ready. You are now chatting with Nova!")
    print("Type 'exit' or 'quit' to stop.\n")
    print("-" * 50)
    
    while True:
        user_input = input("You: ")
        if user_input.lower() in ['exit', 'quit']:
            break
            
        def cli_confirm_callback(tool_name, description):
            """Ask the user for permission in the terminal."""
            print(f"\n⚠️ SECURITY CHECK: Nova wants to {description}.")
            ans = input("Do you allow this? (y/n): ")
            return ans.lower().startswith('y')
            
        def cli_step_callback(event, detail):
            """Print exactly what the brain is doing."""
            if event == "tool":
                print(f"   [Thinking... Using Tool: {detail}]")
                
        # Run the agent
        response = agent.run(
            user_message=user_input,
            conversation_history=history,
            confirm_callback=cli_confirm_callback,
            step_callback=cli_step_callback
        )
        
        print(f"\nNova: {response}\n")
        
        # Append to history so Nova remembers the context
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": response})

if __name__ == "__main__":
    run_cli()
