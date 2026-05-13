#!/usr/bin/env python3
"""
Shared Ollama client with tool-calling loop.

Used by voter_agent, citizen_agent, persona_agent, and telos_executor.
"""

import json
import requests

from realm_tools import REALM_TOOLS, execute_tool


def log(message: str):
    """Print with flush for immediate output."""
    print(message, flush=True)


def call_ollama_with_tools(
    ollama_url: str,
    model: str,
    messages: list,
    tools: list = None,
    network: str = "staging",
    realm_folder: str = ".",
    realm_principal: str = None,
    user_principal: str = None,
    max_tool_rounds: int = 10,
) -> str:
    """Call Ollama with tool support, handling tool calls iteratively.

    Returns the final text response from the LLM.
    """
    if tools is None:
        tools = REALM_TOOLS

    current_messages = messages.copy()

    for round_num in range(max_tool_rounds):
        log(f"\n{'='*60}")
        log(f"Round {round_num + 1}: Sending to Ollama...")

        try:
            response = requests.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": model,
                    "messages": current_messages,
                    "tools": tools,
                    "stream": False,
                },
                timeout=120,
            )
            response.raise_for_status()
            result = response.json()
        except requests.exceptions.RequestException as e:
            log(f"Error calling Ollama: {e}")
            return f"Error: Failed to communicate with Ollama - {e}"

        assistant_message = result.get("message", {})
        current_messages.append(assistant_message)

        tool_calls = assistant_message.get("tool_calls", [])

        if not tool_calls:
            final_response = assistant_message.get("content", "")
            log(f"\nFinal response from LLM:\n{final_response}")
            return final_response

        log(f"\nTool calls requested: {len(tool_calls)}")

        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            tool_args = tool_call["function"].get("arguments", {})

            log(f"\n  Executing tool: {tool_name}")
            log(f"  Arguments: {json.dumps(tool_args, indent=2)}")

            tool_result = execute_tool(
                tool_name,
                tool_args,
                network=network,
                realm_folder=realm_folder,
                realm_principal=realm_principal,
                user_principal=user_principal,
            )

            display_result = tool_result[:500] + "..." if len(tool_result) > 500 else tool_result
            log(f"  Result: {display_result}")

            current_messages.append({"role": "tool", "content": tool_result})

    log(f"\nWarning: Reached max tool rounds ({max_tool_rounds})")
    return "Agent completed maximum number of tool rounds."
