#!/usr/bin/env python3
"""
Simple test script for Ollama tool calling with realm tools.
Doesn't require the full API - just tests the tool calling flow directly.
"""
import requests
import json
from realm_tools import REALM_TOOLS, execute_tool

OLLAMA_URL = "http://localhost:11434"
MODEL = "gpt-oss:20b"

def test_tool_calling(question: str, realm_folder: str = "../realms/examples/demo/realm1", network: str = "staging"):
    print(f"\n{'='*60}")
    print(f"Question: {question}")
    print(f"{'='*60}\n")
    
    system_message = """You are Ashoka, a helpful AI assistant for decentralized governance.
You have access to tools to query realm data. Use them when the user asks about users, proposals, votes, transfers, or other realm entities.
Be concise and helpful."""
    
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": question}
    ]
    
    # First call with tools
    print("📤 Sending to Ollama with tools...")
    response = requests.post(f"{OLLAMA_URL}/api/chat", json={
        "model": MODEL,
        "messages": messages,
        "tools": REALM_TOOLS,
        "stream": False
    })
    
    result = response.json()
    assistant_message = result.get('message', {})
    
    print(f"📥 Response role: {assistant_message.get('role')}")
    
    # Check for tool calls
    if assistant_message.get('tool_calls'):
        print(f"🔧 Tool calls requested: {len(assistant_message['tool_calls'])}")
        
        messages.append(assistant_message)
        
        for tool_call in assistant_message['tool_calls']:
            tool_name = tool_call['function']['name']
            tool_args = tool_call['function']['arguments']
            
            print(f"\n   Tool: {tool_name}")
            print(f"   Args: {json.dumps(tool_args)}")
            
            # Execute the tool
            print(f"   Executing...")
            tool_result = execute_tool(tool_name, tool_args, network=network, realm_folder=realm_folder)
            
            # Truncate for display
            display_result = tool_result[:300] + "..." if len(tool_result) > 300 else tool_result
            print(f"   Result: {display_result}")
            
            messages.append({
                "role": "tool", 
                "content": tool_result
            })
        
        # Second call with tool results
        print("\n📤 Sending tool results back to Ollama...")
        final_response = requests.post(f"{OLLAMA_URL}/api/chat", json={
            "model": MODEL,
            "messages": messages,
            "stream": False
        })
        
        final_result = final_response.json()
        answer = final_result.get('message', {}).get('content', 'No response')
    else:
        print("ℹ️  No tool calls - direct response")
        answer = assistant_message.get('content', 'No response')
    
    print(f"\n{'='*60}")
    print(f"🤖 Ashoka: {answer}")
    print(f"{'='*60}\n")
    
    return answer


if __name__ == "__main__":
    # Use the demo realm folder
    REALM_FOLDER = "../realms/.realms/realm_Generated_Demo_Realm_20251217_123241"
    
    # Test 1: Simple question (should NOT use tools)
    test_tool_calling("What is a realm?", realm_folder=REALM_FOLDER, network="local")
    
    # Test 2: Status question (SHOULD use realm_status tool)
    test_tool_calling("How many users are in this realm?", realm_folder=REALM_FOLDER, network="local")
    
    # Test 3: Data question (SHOULD use db_get tool)
    test_tool_calling("Show me the proposals in this realm", realm_folder=REALM_FOLDER, network="local")
