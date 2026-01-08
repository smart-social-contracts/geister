#!/usr/bin/env python3
"""
Voter Agent - An AI agent that reviews and votes on governance proposals.

Uses Ollama LLM with tool calling to:
1. Get list of proposals
2. Review each proposal's details
3. Decide how to vote (yes/no/abstain) based on analysis
4. Cast votes

Usage:
    export OLLAMA_HOST=https://bobtasn529qypg-11434.proxy.runpod.net/
    
    # Run voter agent (will review and vote on proposals)
    python voter_agent.py
    
    # Vote on specific proposal
    python voter_agent.py --proposal prop_001
    
    # Dry run (analyze but don't vote)
    python voter_agent.py --dry-run
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
DEFAULT_MODEL = os.getenv('VOTER_AGENT_MODEL', 'gpt-oss:20b')
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
    max_tool_rounds: int = 10
) -> str:
    """
    Call Ollama with tool support, handling tool calls iteratively.
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
            
            current_messages.append({
                "role": "tool",
                "content": tool_result
            })
    
    log(f"\nWarning: Reached max tool rounds ({max_tool_rounds})")
    return "Agent completed maximum number of tool rounds."


def run_voter_agent(
    voter_id: str,
    proposal_id: Optional[str] = None,
    network: str = DEFAULT_NETWORK,
    realm_folder: str = DEFAULT_REALM_FOLDER,
    model: str = DEFAULT_MODEL,
    dry_run: bool = False,
    voting_strategy: str = "balanced"
):
    """
    Run the voter agent to review and vote on proposals.
    
    Args:
        voter_id: Your user ID in the realm (required for voting)
        proposal_id: Optional specific proposal to vote on
        network: Network to connect to
        realm_folder: Path to folder with dfx.json
        model: Ollama model to use
        dry_run: If True, analyze but don't cast votes
        voting_strategy: Voting approach (balanced, progressive, conservative)
    """
    ollama_url = get_ollama_url()
    
    log("="*60)
    log("VOTER AGENT")
    log("="*60)
    log(f"Voter ID: {voter_id}")
    log(f"Target Proposal: {proposal_id or 'All pending'}")
    log(f"Network: {network}")
    log(f"Model: {model}")
    log(f"Dry Run: {dry_run}")
    log(f"Strategy: {voting_strategy}")
    log("="*60)
    
    # Strategy descriptions
    strategy_prompts = {
        "balanced": "Vote based on a balanced analysis of pros and cons. Support proposals that benefit the community while maintaining stability.",
        "progressive": "Favor proposals that introduce new features, expand capabilities, or promote growth. Be open to change.",
        "conservative": "Be cautious about changes. Only vote yes on proposals that are clearly beneficial with minimal risk."
    }
    
    strategy_desc = strategy_prompts.get(voting_strategy, strategy_prompts["balanced"])
    
    # Build dry run instruction
    dry_run_instruction = ""
    if dry_run:
        dry_run_instruction = """
IMPORTANT: This is a DRY RUN. Analyze the proposals and explain how you would vote, 
but DO NOT actually call cast_vote. Just report your analysis and intended votes."""
    
    # System prompt
    system_prompt = f"""You are a governance participant in a realm on the Internet Computer.

Your voter ID is: {voter_id}

Your task is to:
1. Get the list of proposals (focus on pending_review status)
2. For each proposal, review its details (title, description, votes so far)
3. Analyze whether the proposal is good for the community
4. Cast your vote (yes, no, or abstain)
5. Provide a brief explanation for each vote

Voting Strategy: {strategy_desc}
{dry_run_instruction}

You have access to these tools:
- get_proposals: List all proposals (can filter by status)
- get_proposal: Get details of a specific proposal
- cast_vote: Cast your vote on a proposal (requires proposal_id, vote, voter_id)
- get_my_vote: Check if you already voted on a proposal
- realm_status: Get overall realm status

When voting:
- Use your voter_id: {voter_id}
- Valid votes are: "yes", "no", "abstain"
- Check if you've already voted before casting

Be thorough but efficient. Provide clear reasoning for your votes."""

    # User message
    if proposal_id:
        user_message = f"""Please review and vote on proposal: {proposal_id}

1. Get the proposal details
2. Check if I've already voted
3. Analyze the proposal
4. Cast my vote with reasoning"""
    else:
        user_message = """Please review all pending proposals and vote on them.

1. Get the list of proposals (filter by pending_review status if possible)
2. For each proposal:
   - Check if I've already voted
   - If not voted, analyze it and cast my vote
3. Provide a summary of all votes cast"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    log("\nStarting voter agent...")
    
    final_response = call_ollama_with_tools(
        ollama_url=ollama_url,
        model=model,
        messages=messages,
        tools=REALM_TOOLS,
        network=network,
        realm_folder=realm_folder
    )
    
    log("\n" + "="*60)
    log("VOTING SESSION COMPLETED")
    log("="*60)
    log(f"\nSummary:\n{final_response}")
    
    return final_response


def main():
    parser = argparse.ArgumentParser(
        description="Voter Agent - Review and vote on governance proposals"
    )
    parser.add_argument(
        "--voter-id", "-v",
        required=True,
        help="Your user ID in the realm (required for voting)"
    )
    parser.add_argument(
        "--proposal", "-p",
        default=None,
        help="Specific proposal ID to vote on (default: all pending)"
    )
    parser.add_argument(
        "--network", "-n",
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
        "--dry-run",
        action="store_true",
        help="Analyze proposals but don't actually vote"
    )
    parser.add_argument(
        "--strategy", "-s",
        default="balanced",
        choices=["balanced", "progressive", "conservative"],
        help="Voting strategy (default: balanced)"
    )
    
    args = parser.parse_args()
    
    if 'OLLAMA_HOST' not in os.environ and DEFAULT_OLLAMA_HOST == 'http://localhost:11434':
        log("Note: OLLAMA_HOST not set. Using localhost:11434")
    
    try:
        run_voter_agent(
            voter_id=args.voter_id,
            proposal_id=args.proposal,
            network=args.network,
            realm_folder=args.realm_folder,
            model=args.model,
            dry_run=args.dry_run,
            voting_strategy=args.strategy
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
