#!/usr/bin/env python3
"""
Realm Tools - Functions that Ashoka LLM can call to explore realm data
"""
import subprocess
import json
import traceback
from typing import Optional


def db_get(entity_type: str, network: str = "staging", realm_folder: str = "../realms/examples/demo/realm1") -> str:
    """
    Get entities from the realm database.
    
    Args:
        entity_type: Type of entity to query (User, Proposal, Vote, Transfer, Mandate, Task, Organization)
        network: Network to query (local, staging, ic)
        realm_folder: Path to realm folder containing dfx.json
    
    Returns:
        JSON string of entities found
    """
    import os
    cmd = ["realms", "db", "-f", realm_folder, "-n", network, "get", entity_type]
    
    # Set environment to suppress DFX security warnings for read-only operations
    env = os.environ.copy()
    env['DFX_WARNING'] = '-mainnet_plaintext_identity'
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        if result.returncode == 0:
            return result.stdout.strip() or "No entities found"
        else:
            return f"Error: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        traceback.print_exc()
        return f"Error: {str(e)}"


def join_realm(profile: str = "member", network: str = "staging", realm_folder: str = ".") -> str:
    """
    Join a realm as a citizen with a specific profile.
    
    Args:
        profile: Profile type to join with (member, admin)
        network: Network to use (local, staging, ic)
        realm_folder: Path to realm folder containing dfx.json
    
    Returns:
        JSON string with result of joining the realm
    """
    import os
    cmd = [
        "dfx", "canister", "call", "realm_backend", "join_realm",
        f'("{profile}")',
        "--network", network
    ]
    
    env = os.environ.copy()
    env['DFX_WARNING'] = '-mainnet_plaintext_identity'
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=realm_folder, env=env)
        if result.returncode == 0:
            return result.stdout.strip() or "Successfully joined realm"
        else:
            return f"Error: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        traceback.print_exc()
        return f"Error: {str(e)}"


def set_profile_picture(profile_picture_url: str, network: str = "staging", realm_folder: str = ".") -> str:
    """
    Set your profile picture in the realm.
    
    Args:
        profile_picture_url: URL to the profile picture image
        network: Network to use (local, staging, ic)
        realm_folder: Path to realm folder containing dfx.json
    
    Returns:
        JSON string with result of updating profile picture
    """
    import os
    cmd = [
        "dfx", "canister", "call", "realm_backend", "update_my_profile_picture",
        f'("{profile_picture_url}")',
        "--network", network
    ]
    
    env = os.environ.copy()
    env['DFX_WARNING'] = '-mainnet_plaintext_identity'
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=realm_folder, env=env)
        if result.returncode == 0:
            return result.stdout.strip() or "Successfully updated profile picture"
        else:
            return f"Error: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        traceback.print_exc()
        return f"Error: {str(e)}"


def get_my_status(network: str = "staging", realm_folder: str = ".") -> str:
    """
    Get your current user status in the realm.
    
    Args:
        network: Network to use (local, staging, ic)
        realm_folder: Path to realm folder containing dfx.json
    
    Returns:
        JSON string with your user status (principal, profiles, profile picture)
    """
    import os
    cmd = [
        "dfx", "canister", "call", "realm_backend", "get_my_user_status",
        "--network", network
    ]
    
    env = os.environ.copy()
    env['DFX_WARNING'] = '-mainnet_plaintext_identity'
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=realm_folder, env=env)
        if result.returncode == 0:
            return result.stdout.strip() or "No status available"
        else:
            return f"Error: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        traceback.print_exc()
        return f"Error: {str(e)}"


def realm_status(network: str = "local", realm_folder: str = ".") -> str:
    """
    Get the current status of a realm (users count, proposals, votes, etc.).
    
    Args:
        network: Network to query (local, staging, ic)
        realm_folder: Path to realm folder containing dfx.json
    
    Returns:
        JSON string with realm status including counts for users, proposals, votes, etc.
    """
    import os
    cmd = ["realms", "realm", "call", "status", "-n", network]
    
    # Set environment to suppress DFX security warnings for read-only operations
    env = os.environ.copy()
    env['DFX_WARNING'] = '-mainnet_plaintext_identity'
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=realm_folder, env=env)
        if result.returncode == 0:
            return result.stdout.strip() or "No status available"
        else:
            return f"Error: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        traceback.print_exc()
        return f"Error: {str(e)}"


# Tool definitions for Ollama (OpenAI-compatible format)
REALM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "db_get",
            "description": "Get entities from the realm database. Use this to query any entity type including: User, Proposal, Vote, Transfer, Mandate, Task, Organization, Codex, Dispute, Instrument, License, Trade, Contract, Invoice, Balance, Treasury, and more.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "Type of entity to query from the realm database",
                        "enum": ["Balance", "Call", "Codex", "Contract", "Dispute", "Human", "Identity", "Instrument", "Invoice", "Land", "License", "Mandate", "Member", "Notification", "Organization", "PaymentAccount", "Permission", "Proposal", "Realm", "Registry", "Service", "Status", "Task", "TaskExecution", "TaskSchedule", "TaskStep", "Trade", "Transfer", "Treasury", "User", "UserProfile", "Vote"]
                    }
                },
                "required": ["entity_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "realm_status",
            "description": "Get the current status of the realm including counts for all entity types (users, proposals, votes, codexes, disputes, instruments, licenses, trades, etc.) and installed extensions.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "join_realm",
            "description": "Join the realm as a citizen. This registers you as a user in the realm with the specified profile (member or admin).",
            "parameters": {
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "string",
                        "description": "Profile type to join with",
                        "enum": ["member", "admin"],
                        "default": "member"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_profile_picture",
            "description": "Set your profile picture in the realm. Provide a URL to an image.",
            "parameters": {
                "type": "object",
                "properties": {
                    "profile_picture_url": {
                        "type": "string",
                        "description": "URL to the profile picture image (e.g., https://api.dicebear.com/7.x/personas/svg?seed=MyName)"
                    }
                },
                "required": ["profile_picture_url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_status",
            "description": "Get your current user status in the realm, including your principal ID, profiles, and profile picture URL.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]

# Map function names to actual functions
TOOL_FUNCTIONS = {
    "db_get": db_get,
    "realm_status": realm_status,
    "join_realm": join_realm,
    "set_profile_picture": set_profile_picture,
    "get_my_status": get_my_status
}


def execute_tool(tool_name: str, arguments: dict, network: str = "staging", realm_folder: str = "../realms/examples/demo/realm1") -> str:
    """Execute a tool by name with given arguments."""
    if tool_name not in TOOL_FUNCTIONS:
        return f"Error: Unknown tool '{tool_name}'"
    
    # Filter to only valid arguments for the function
    func = TOOL_FUNCTIONS[tool_name]
    import inspect
    valid_params = set(inspect.signature(func).parameters.keys())
    
    # Start with network and realm_folder defaults
    filtered_args = {
        "network": network,
        "realm_folder": realm_folder
    }
    
    # Add any valid arguments from the LLM
    for key, value in arguments.items():
        if key in valid_params:
            filtered_args[key] = value
    
    return func(**filtered_args)
