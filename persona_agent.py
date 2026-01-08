#!/usr/bin/env python3
"""
Persona Agent - Run a citizen agent with a specific behavioral persona.

Each persona has different motivations, voting strategies, and behaviors.
All personas start by joining the realm, then diverge in their actions.

Usage:
    export OLLAMA_HOST=https://bobtasn529qypg-11434.proxy.runpod.net/
    
    # Run as compliant citizen
    python persona_agent.py --persona compliant --name "Alice"
    
    # Run as exploiter
    python persona_agent.py --persona exploiter --name "Bob"
    
    # Run as watchful citizen
    python persona_agent.py --persona watchful --name "Charlie"
    
    # List available personas
    python persona_agent.py --list
"""

import argparse
import json
import os
import sys
import requests
from typing import Optional

from citizen_personas import get_persona, list_personas, CitizenPersona
from realm_tools import REALM_TOOLS, execute_tool
from agent_memory import AgentMemory


# Default configuration
DEFAULT_OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
DEFAULT_MODEL = os.getenv('PERSONA_AGENT_MODEL', 'gpt-oss:20b')
DEFAULT_NETWORK = 'staging'
DEFAULT_REALM_FOLDER = '.'


def log(message: str):
    """Print with flush for immediate output"""
    print(message, flush=True)


def get_ollama_url() -> str:
    """Get Ollama URL, handling trailing slashes"""
    return DEFAULT_OLLAMA_HOST.rstrip('/')


def call_ollama_with_tools(
    ollama_url: str,
    model: str,
    messages: list,
    tools: list,
    network: str,
    realm_folder: str,
    max_tool_rounds: int = 10,
    tool_history: list = None
) -> str:
    """Call Ollama with tool support, handling tool calls iteratively."""
    current_messages = messages.copy()
    if tool_history is None:
        tool_history = []
    
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
        
        tool_calls = assistant_message.get('tool_calls', [])
        
        if not tool_calls:
            final_response = assistant_message.get('content', '')
            log(f"\nFinal response from LLM:\n{final_response}")
            return final_response
        
        log(f"\nTool calls requested: {len(tool_calls)}")
        
        for tool_call in tool_calls:
            tool_name = tool_call['function']['name']
            tool_args = tool_call['function'].get('arguments', {})
            
            log(f"\n  Executing tool: {tool_name}")
            log(f"  Arguments: {json.dumps(tool_args, indent=2)}")
            
            tool_result = execute_tool(
                tool_name,
                tool_args,
                network=network,
                realm_folder=realm_folder
            )
            
            display_result = tool_result[:500] + "..." if len(tool_result) > 500 else tool_result
            log(f"  Result: {display_result}")
            
            # Track tool call for memory
            tool_history.append({
                "tool": tool_name,
                "args": tool_args,
                "result_preview": display_result[:200]
            })
            
            current_messages.append({
                "role": "tool",
                "content": tool_result
            })
    
    log(f"\nWarning: Reached max tool rounds ({max_tool_rounds})")
    return "Agent completed maximum number of tool rounds."


def build_persona_task(persona: CitizenPersona, agent_name: str) -> str:
    """Build the task prompt based on persona type."""
    
    base_task = f"""Your name is {agent_name}.

PHASE 1 - JOIN THE REALM:
First, you must join the realm as a member and set up your profile.
1. Check the realm status to understand the community
2. Join the realm as a member
3. Set your profile picture to: https://api.dicebear.com/7.x/personas/svg?seed={agent_name}
4. Verify your membership

PHASE 2 - ACT ACCORDING TO YOUR PERSONA:
After joining, behave according to your persona's values and motivations.
"""
    
    persona_tasks = {
        "compliant": """
As a COMPLIANT citizen, your Phase 2 actions:
- Check if there are any pending proposals to vote on
- If proposals exist, review them and vote YES on those from authorities
- Express support for community stability
- Offer to help with community activities
- Report your participation summary
""",
        "exploiter": """
As an EXPLOITER, your Phase 2 actions:
- Analyze the realm for opportunities and weaknesses
- Check proposals for loopholes or personal benefit opportunities
- Look at the treasury/vault status
- Identify any subsidies, grants, or free resources available
- Note potential exploitation vectors (but be subtle about it)
- Report your "observations" in a way that sounds helpful
""",
        "watchful": """
As a WATCHFUL citizen, your Phase 2 actions:
- Analyze the realm structure critically
- Check proposals for hidden agendas or centralization risks
- Examine who holds power and resources
- Identify potential abuse vectors
- Look for transparency gaps
- Document your concerns and observations
- Suggest improvements for accountability
"""
    }
    
    persona_key = persona.name.lower()
    specific_task = persona_tasks.get(persona_key, "")
    
    return base_task + specific_task


def run_persona_agent(
    persona_name: str,
    agent_name: str,
    network: str = DEFAULT_NETWORK,
    realm_folder: str = DEFAULT_REALM_FOLDER,
    model: str = DEFAULT_MODEL,
    agent_id: str = None,
    principal: str = None,
    realm_principal: str = None
) -> str:
    """
    Run an agent with a specific persona and persistent memory.
    
    Args:
        persona_name: Name of the persona (compliant, exploiter, watchful)
        agent_name: Display name for the agent
        network: Network to connect to
        realm_folder: Path to folder with dfx.json
        model: Ollama model to use
        agent_id: Unique agent identifier for memory (dfx identity name)
        principal: IC principal for this agent
        realm_principal: Realm canister ID for memory scoping
    """
    ollama_url = get_ollama_url()
    
    # Load persona
    persona = get_persona(persona_name)
    if not persona:
        available = ", ".join(list_personas())
        log(f"Error: Unknown persona '{persona_name}'. Available: {available}")
        return ""
    
    # Initialize memory system
    memory = None
    life_story = ""
    if agent_id:
        memory = AgentMemory(agent_id, principal=principal, persona=persona_name)
        memory.ensure_profile(display_name=agent_name)
        life_story = memory.get_life_story_prompt(realm_principal=realm_principal)
        if memory.is_connected():
            log(f"📚 Memory loaded for {agent_id}")
    
    log("=" * 60)
    log(f"{persona.emoji} PERSONA AGENT: {persona.name.upper()}")
    log("=" * 60)
    log(f"Agent Name: {agent_name}")
    log(f"Agent ID: {agent_id or 'none (no memory)'}")
    log(f"Persona: {persona.name} - {persona.description}")
    log(f"Motivation: {persona.motivation}")
    log(f"Network: {network}")
    log(f"Model: {model}")
    log("=" * 60)
    
    # Build system prompt from persona + life story
    system_prompt = persona.system_prompt
    if life_story:
        system_prompt = f"{system_prompt}\n\n{life_story}"
    
    # Build task prompt
    task_prompt = build_persona_task(persona, agent_name)
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task_prompt}
    ]
    
    log(f"\nStarting {persona.name} agent...")
    
    # Track tool calls for memory
    tool_history = []
    
    final_response = call_ollama_with_tools(
        ollama_url=ollama_url,
        model=model,
        messages=messages,
        tools=REALM_TOOLS,
        network=network,
        realm_folder=realm_folder,
        tool_history=tool_history
    )
    
    # Save session to memory
    if memory and agent_id:
        # Summarize the session
        action_types = list(set(t.get('tool') for t in tool_history if t.get('tool')))
        action_summary = f"Session with {len(tool_history)} actions: {', '.join(action_types)}"
        
        memory.remember(
            action_type="session",
            action_summary=action_summary,
            realm_principal=realm_principal,
            action_details={"tools": tool_history, "response": final_response[:500]},
            emotional_state=_infer_emotional_state(persona_name, final_response),
            observations=_extract_observations(final_response)
        )
        memory.close()
        log(f"📚 Session saved to memory")
    
    log("\n" + "=" * 60)
    log(f"{persona.emoji} AGENT COMPLETED: {persona.name.upper()}")
    log("=" * 60)
    log(f"\nSummary:\n{final_response}")
    
    return final_response


def _infer_emotional_state(persona_name: str, response: str) -> str:
    """Infer emotional state based on persona and response."""
    response_lower = response.lower()
    
    if persona_name == "compliant":
        if "success" in response_lower or "completed" in response_lower:
            return "satisfied"
        elif "error" in response_lower or "failed" in response_lower:
            return "concerned"
        return "content"
    
    elif persona_name == "exploiter":
        if "opportunity" in response_lower or "found" in response_lower:
            return "opportunistic"
        elif "blocked" in response_lower or "restricted" in response_lower:
            return "frustrated"
        return "calculating"
    
    elif persona_name == "watchful":
        if "suspicious" in response_lower or "concern" in response_lower:
            return "vigilant"
        elif "transparent" in response_lower or "fair" in response_lower:
            return "cautiously optimistic"
        return "analytical"
    
    return "neutral"


def _extract_observations(response: str) -> str:
    """Extract key observations from the response."""
    # Simple extraction - take the last paragraph or sentence as observation
    lines = response.strip().split('\n')
    for line in reversed(lines):
        if line.strip() and len(line.strip()) > 20:
            return line.strip()[:200]
    return ""


def main():
    parser = argparse.ArgumentParser(
        description="Persona Agent - Run a citizen agent with a specific behavioral persona"
    )
    parser.add_argument(
        "--persona", "-p",
        default="compliant",
        help="Persona to use (compliant, exploiter, watchful)"
    )
    parser.add_argument(
        "--name", "-n",
        default=None,
        help="Agent name (default: auto-generated from persona)"
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
        "--list", "-l",
        action="store_true",
        help="List available personas and exit"
    )
    parser.add_argument(
        "--agent-id",
        default=None,
        help="Agent ID for persistent memory (e.g., swarm_agent_001)"
    )
    parser.add_argument(
        "--realm-principal",
        default=None,
        help="Realm canister ID for memory scoping"
    )
    
    args = parser.parse_args()
    
    # List personas
    if args.list:
        from citizen_personas import get_personas
        personas = get_personas()
        print("\nAvailable Citizen Personas:")
        print("=" * 50)
        for name, p in sorted(personas.items()):
            print(f"\n{p.emoji} {p.name}")
            print(f"   {p.description}")
            print(f"   Motivation: {p.motivation}")
        return
    
    # Generate agent name if not provided
    agent_name = args.name
    if not agent_name:
        import random
        suffixes = ["Alpha", "Beta", "Gamma", "Delta", "Omega"]
        persona = get_persona(args.persona)
        if persona:
            agent_name = f"{persona.name}{random.choice(suffixes)}"
        else:
            agent_name = f"Agent{random.randint(100, 999)}"
    
    if 'OLLAMA_HOST' not in os.environ and DEFAULT_OLLAMA_HOST == 'http://localhost:11434':
        log("Note: OLLAMA_HOST not set. Using localhost:11434")
    
    try:
        run_persona_agent(
            persona_name=args.persona,
            agent_name=agent_name,
            network=args.network,
            realm_folder=args.realm_folder,
            model=args.model,
            agent_id=args.agent_id,
            realm_principal=args.realm_principal
        )
    except KeyboardInterrupt:
        log("\nAgent interrupted by user")
        sys.exit(1)
    except Exception as e:
        log(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
