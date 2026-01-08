#!/usr/bin/env python3
"""
Citizen Agent - An AI agent that joins a realm and sets up its profile.

Uses Ollama LLM with tool calling to interact with a Realm on the Internet Computer.

Usage:
    # Set the Ollama host (remote RunPod instance)
    export OLLAMA_HOST=https://bobtasn529qypg-11434.proxy.runpod.net/
    
    # Run the citizen agent
    python citizen_agent.py
    
    # Or with custom options
    python citizen_agent.py --network staging --model gpt-oss:20b --name "Alice"
"""

import argparse
import json
import os
import sys
import requests
from typing import Optional

from realm_tools import REALM_TOOLS, execute_tool


# Default configuration
DEFAULT_OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
DEFAULT_MODEL = os.getenv('CITIZEN_AGENT_MODEL', 'gpt-oss:20b')
DEFAULT_NETWORK = 'staging'
DEFAULT_REALM_FOLDER = '.'  # Current directory (geister) has dfx.json


def log(message: str):
    """Print with flush for immediate output"""
    print(message, flush=True)


def get_ollama_url() -> str:
    """Get Ollama URL, handling trailing slashes"""
    url = DEFAULT_OLLAMA_HOST.rstrip('/')
    return url


def call_ollama_with_tools(
    ollama_url: str,
    model: str,
    messages: list,
    tools: list,
    network: str,
    realm_folder: str,
    max_tool_rounds: int = 5
) -> str:
    """
    Call Ollama with tool support, handling tool calls iteratively.
    
    Returns the final text response from the LLM.
    """
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
                    "stream": False
                },
                timeout=120
            )
            response.raise_for_status()
            result = response.json()
        except requests.exceptions.RequestException as e:
            log(f"Error calling Ollama: {e}")
            return f"Error: Failed to communicate with Ollama - {e}"
        
        assistant_message = result.get('message', {})
        current_messages.append(assistant_message)
        
        # Check for tool calls
        tool_calls = assistant_message.get('tool_calls', [])
        
        if not tool_calls:
            # No more tool calls - return the final response
            final_response = assistant_message.get('content', '')
            log(f"\nFinal response from LLM:\n{final_response}")
            return final_response
        
        # Execute each tool call
        log(f"\nTool calls requested: {len(tool_calls)}")
        
        for tool_call in tool_calls:
            tool_name = tool_call['function']['name']
            tool_args = tool_call['function'].get('arguments', {})
            
            log(f"\n  Executing tool: {tool_name}")
            log(f"  Arguments: {json.dumps(tool_args, indent=2)}")
            
            # Execute the tool
            tool_result = execute_tool(
                tool_name,
                tool_args,
                network=network,
                realm_folder=realm_folder
            )
            
            # Truncate long results for display
            display_result = tool_result[:500] + "..." if len(tool_result) > 500 else tool_result
            log(f"  Result: {display_result}")
            
            # Add tool result to messages
            current_messages.append({
                "role": "tool",
                "content": tool_result
            })
    
    log(f"\nWarning: Reached max tool rounds ({max_tool_rounds})")
    return "Agent completed maximum number of tool rounds."


def run_citizen_agent(
    name: str,
    network: str = DEFAULT_NETWORK,
    realm_folder: str = DEFAULT_REALM_FOLDER,
    model: str = DEFAULT_MODEL,
    profile_picture_url: Optional[str] = None
):
    """
    Run the citizen agent to join a realm and set up profile.
    
    Args:
        name: Name for the citizen (used for avatar generation)
        network: Network to connect to (local, staging, ic)
        realm_folder: Path to folder with dfx.json
        model: Ollama model to use
        profile_picture_url: Optional custom profile picture URL
    """
    ollama_url = get_ollama_url()
    
    log("="*60)
    log("CITIZEN AGENT")
    log("="*60)
    log(f"Name: {name}")
    log(f"Network: {network}")
    log(f"Realm folder: {realm_folder}")
    log(f"Ollama URL: {ollama_url}")
    log(f"Model: {model}")
    log("="*60)
    
    # Generate avatar URL if not provided
    if not profile_picture_url:
        # Use DiceBear API for generating avatars
        safe_name = name.replace(" ", "")
        profile_picture_url = f"https://api.dicebear.com/7.x/personas/svg?seed={safe_name}"
    
    log(f"Profile picture: {profile_picture_url}")
    
    # System prompt for the citizen agent
    system_prompt = f"""You are a citizen agent named {name} who wants to join a realm on the Internet Computer.

Your task is to:
1. First, check the realm status to understand the community
2. Join the realm as a member
3. Set your profile picture to: {profile_picture_url}
4. Verify your status after joining

You have access to these tools:
- realm_status: Get information about the realm
- join_realm: Join the realm as a member
- set_profile_picture: Set your profile picture URL
- get_my_status: Check your current status in the realm

Please complete these steps in order. After each action, briefly explain what happened.
Be concise but informative about your actions and their results."""

    # Initial user message
    user_message = f"""Hello! I am {name} and I want to join this realm and set up my profile.

Please help me:
1. Check what this realm is about
2. Join as a member
3. Set my profile picture to: {profile_picture_url}
4. Confirm my membership

Let's get started!"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    # Run the agent
    log("\nStarting citizen agent...")
    
    final_response = call_ollama_with_tools(
        ollama_url=ollama_url,
        model=model,
        messages=messages,
        tools=REALM_TOOLS,
        network=network,
        realm_folder=realm_folder
    )
    
    log("\n" + "="*60)
    log("AGENT COMPLETED")
    log("="*60)
    log(f"\nFinal Summary:\n{final_response}")
    
    return final_response


def main():
    parser = argparse.ArgumentParser(
        description="Citizen Agent - Join a realm and set up your profile"
    )
    parser.add_argument(
        "--name", "-n",
        default="Geister",
        help="Name for the citizen (default: Geister)"
    )
    parser.add_argument(
        "--network",
        default=DEFAULT_NETWORK,
        choices=["local", "staging", "ic"],
        help=f"Network to connect to (default: {DEFAULT_NETWORK})"
    )
    parser.add_argument(
        "--realm-folder", "-f",
        default=DEFAULT_REALM_FOLDER,
        help=f"Path to realm folder with dfx.json (default: {DEFAULT_REALM_FOLDER})"
    )
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"Ollama model to use (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--profile-picture", "-p",
        default=None,
        help="Custom profile picture URL (default: auto-generated from DiceBear)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    
    args = parser.parse_args()
    
    # Check if OLLAMA_HOST is set
    if 'OLLAMA_HOST' not in os.environ and DEFAULT_OLLAMA_HOST == 'http://localhost:11434':
        log("Note: OLLAMA_HOST not set. Using localhost:11434")
        log("For remote Ollama, set: export OLLAMA_HOST=https://your-ollama-host/")
    
    try:
        run_citizen_agent(
            name=args.name,
            network=args.network,
            realm_folder=args.realm_folder,
            model=args.model,
            profile_picture_url=args.profile_picture
        )
    except KeyboardInterrupt:
        log("\nAgent interrupted by user")
        sys.exit(1)
    except Exception as e:
        log(f"\nError: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
