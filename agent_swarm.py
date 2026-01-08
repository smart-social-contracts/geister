#!/usr/bin/env python3
"""
Agent Swarm - Run multiple citizen agents with unique identities.

Uses dfx identity management to create unique principals for each agent.

Usage:
    # Set Ollama host
    export OLLAMA_HOST=https://bobtasn529qypg-11434.proxy.runpod.net/
    
    # Generate 10 agent identities
    python agent_swarm.py generate 10
    
    # Run all agents (join realm + set profile)
    python agent_swarm.py run
    
    # Run specific agents
    python agent_swarm.py run --start 1 --end 5
    
    # List existing agent identities
    python agent_swarm.py list
    
    # Clean up all agent identities
    python agent_swarm.py cleanup --confirm
"""

import argparse
import json
import os
import subprocess
import sys
import time
from typing import List, Optional

from citizen_agent import run_citizen_agent


# =============================================================================
# Configuration
# =============================================================================

AGENT_PREFIX = "swarm_agent"
DEFAULT_NETWORK = "staging"
DEFAULT_MODEL = os.getenv('CITIZEN_AGENT_MODEL', 'gpt-oss:20b')


def log(message: str):
    """Print with flush for immediate output"""
    print(message, flush=True)


# =============================================================================
# Identity Management
# =============================================================================

def get_agent_identity_name(index: int) -> str:
    """Get the identity name for an agent by index."""
    return f"{AGENT_PREFIX}_{index:03d}"


def list_agent_identities() -> List[str]:
    """List all existing agent identities."""
    try:
        result = subprocess.run(
            ["dfx", "identity", "list"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            identities = result.stdout.strip().split('\n')
            return [i.strip().rstrip('*').strip() for i in identities if i.strip().startswith(AGENT_PREFIX)]
        return []
    except Exception as e:
        log(f"Error listing identities: {e}")
        return []


def create_identity(name: str) -> bool:
    """Create a new dfx identity."""
    try:
        result = subprocess.run(
            ["dfx", "identity", "new", name, "--storage-mode", "plaintext"],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except Exception as e:
        log(f"Error creating identity {name}: {e}")
        return False


def delete_identity(name: str) -> bool:
    """Delete a dfx identity."""
    try:
        result = subprocess.run(
            ["dfx", "identity", "remove", name],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except Exception as e:
        log(f"Error deleting identity {name}: {e}")
        return False


def use_identity(name: str) -> bool:
    """Switch to a dfx identity."""
    try:
        result = subprocess.run(
            ["dfx", "identity", "use", name],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except Exception as e:
        log(f"Error switching to identity {name}: {e}")
        return False


def get_current_identity() -> str:
    """Get the current dfx identity name."""
    try:
        result = subprocess.run(
            ["dfx", "identity", "whoami"],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def get_principal_for_identity(name: str) -> Optional[str]:
    """Get the principal ID for an identity."""
    try:
        result = subprocess.run(
            ["dfx", "identity", "get-principal", "--identity", name],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


# =============================================================================
# Commands
# =============================================================================

def cmd_generate(count: int, start_index: int = 1):
    """Generate N agent identities."""
    log(f"Generating {count} agent identities starting from index {start_index}...")
    
    created = 0
    failed = 0
    existing = list_agent_identities()
    
    for i in range(start_index, start_index + count):
        name = get_agent_identity_name(i)
        
        if name in existing:
            log(f"  [{i:03d}] {name} already exists, skipping")
            continue
        
        if create_identity(name):
            principal = get_principal_for_identity(name)
            log(f"  [{i:03d}] Created {name} -> {principal[:20]}...")
            created += 1
        else:
            log(f"  [{i:03d}] Failed to create {name}")
            failed += 1
    
    log(f"\nDone! Created: {created}, Failed: {failed}, Skipped: {count - created - failed}")


def cmd_list():
    """List all agent identities with their principals."""
    identities = list_agent_identities()
    
    if not identities:
        log("No agent identities found.")
        log("Run: python agent_swarm.py generate <count>")
        return
    
    log(f"Found {len(identities)} agent identities:\n")
    log(f"{'Index':<8} {'Identity':<25} {'Principal'}")
    log("-" * 80)
    
    for name in sorted(identities):
        principal = get_principal_for_identity(name) or "unknown"
        try:
            index = int(name.split('_')[-1])
        except:
            index = 0
        log(f"{index:<8} {name:<25} {principal}")


def cmd_run(
    start: int = 1,
    end: Optional[int] = None,
    network: str = DEFAULT_NETWORK,
    model: str = DEFAULT_MODEL,
    delay: float = 1.0
):
    """Run citizen agents for the specified identity range."""
    identities = list_agent_identities()
    
    if not identities:
        log("No agent identities found. Run: python agent_swarm.py generate <count>")
        return
    
    # Determine end index
    if end is None:
        # Find max index from existing identities
        max_idx = 0
        for name in identities:
            try:
                idx = int(name.split('_')[-1])
                max_idx = max(max_idx, idx)
            except:
                pass
        end = max_idx
    
    # Filter to requested range
    target_identities = []
    for i in range(start, end + 1):
        name = get_agent_identity_name(i)
        if name in identities:
            target_identities.append((i, name))
    
    if not target_identities:
        log(f"No identities found in range {start}-{end}")
        return
    
    log(f"Running {len(target_identities)} agents (indices {start}-{end})")
    log(f"Network: {network}, Model: {model}")
    log("=" * 60)
    
    # Save current identity to restore later
    original_identity = get_current_identity()
    
    results = []
    
    try:
        for index, identity_name in target_identities:
            agent_name = f"Agent{index:03d}"
            
            try:
                # Switch to this identity
                if not use_identity(identity_name):
                    results.append({"index": index, "success": False, "error": "Failed to switch identity"})
                    continue
                
                # Small delay to avoid rate limiting
                if delay > 0:
                    time.sleep(delay)
                
                # Run the citizen agent
                log(f"\n[Agent {index:03d}] Starting as {identity_name}...")
                
                result = run_citizen_agent(
                    name=agent_name,
                    network=network,
                    model=model,
                    realm_folder="."
                )
                
                results.append({"index": index, "success": True})
                log(f"[Agent {index:03d}] ✓ Completed")
                
            except Exception as e:
                results.append({"index": index, "success": False, "error": str(e)})
                log(f"[Agent {index:03d}] ✗ Failed: {e}")
    
    finally:
        # Restore original identity
        use_identity(original_identity)
        log(f"\nRestored identity to: {original_identity}")
    
    # Summary
    successful = sum(1 for r in results if r["success"])
    failed = len(results) - successful
    
    log("\n" + "=" * 60)
    log("SWARM SUMMARY")
    log("=" * 60)
    log(f"Total agents: {len(results)}")
    log(f"Successful: {successful}")
    log(f"Failed: {failed}")


def cmd_cleanup(confirm: bool = False):
    """Delete all agent identities."""
    identities = list_agent_identities()
    
    if not identities:
        log("No agent identities to clean up.")
        return
    
    log(f"Found {len(identities)} agent identities to delete:")
    for name in identities:
        log(f"  - {name}")
    
    if not confirm:
        log("\nAdd --confirm to actually delete these identities.")
        return
    
    log("\nDeleting...")
    deleted = 0
    for name in identities:
        if delete_identity(name):
            log(f"  Deleted {name}")
            deleted += 1
        else:
            log(f"  Failed to delete {name}")
    
    log(f"\nDeleted {deleted}/{len(identities)} identities")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Agent Swarm - Run multiple citizen agents with unique identities"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # generate command
    gen_parser = subparsers.add_parser("generate", help="Generate agent identities")
    gen_parser.add_argument("count", type=int, help="Number of identities to generate")
    gen_parser.add_argument("--start", type=int, default=1, help="Starting index (default: 1)")
    
    # list command
    subparsers.add_parser("list", help="List all agent identities")
    
    # run command
    run_parser = subparsers.add_parser("run", help="Run citizen agents")
    run_parser.add_argument("--start", type=int, default=1, help="Start index (default: 1)")
    run_parser.add_argument("--end", type=int, default=None, help="End index (default: all)")
    run_parser.add_argument("--network", "-n", default=DEFAULT_NETWORK, help="Network to use")
    run_parser.add_argument("--model", "-m", default=DEFAULT_MODEL, help="Ollama model to use")
    run_parser.add_argument("--delay", "-d", type=float, default=1.0, help="Delay between agents (seconds)")
    
    # cleanup command
    cleanup_parser = subparsers.add_parser("cleanup", help="Delete all agent identities")
    cleanup_parser.add_argument("--confirm", action="store_true", help="Actually delete identities")
    
    args = parser.parse_args()
    
    if args.command == "generate":
        cmd_generate(args.count, args.start)
    elif args.command == "list":
        cmd_list()
    elif args.command == "run":
        cmd_run(args.start, args.end, args.network, args.model, args.delay)
    elif args.command == "cleanup":
        cmd_cleanup(args.confirm)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
