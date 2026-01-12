#!/usr/bin/env python3
"""
Realm Tools - Functions that Ashoka LLM can call to interact with realm data

Provides tools for:
- Citizen actions (join, profile, status)
- Governance (proposals, voting)
- Economic (balance, transactions)
"""
import subprocess
import json
import os
import traceback
from typing import Optional, Dict, Any


# =============================================================================
# Common Helper Functions
# =============================================================================

def _get_env() -> dict:
    """Get environment with DFX warnings suppressed."""
    env = os.environ.copy()
    env['DFX_WARNING'] = '-mainnet_plaintext_identity'
    return env


def _run_dfx_call(
    canister: str,
    method: str,
    args: str = "()",
    network: str = "staging",
    realm_folder: str = ".",
    timeout: int = 60,
    realm_principal: str = ""
) -> str:
    """
    Run a dfx canister call with JSON output.
    
    Args:
        canister: Canister name (e.g., "realm_backend") - used if realm_principal not provided
        method: Method to call
        args: Candid arguments string
        network: Network to use
        realm_folder: Working directory with dfx.json
        timeout: Command timeout in seconds
        realm_principal: Canister ID to use directly (overrides canister name)
    
    Returns:
        JSON string result or error message
    """
    # Use realm_principal (canister ID) if provided, otherwise use canister name
    target_canister = realm_principal if realm_principal else canister
    
    cmd = [
        "dfx", "canister", "call", target_canister, method, args,
        "--network", network,
        "--output", "json"
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=realm_folder,
            env=_get_env()
        )
        if result.returncode == 0:
            return result.stdout.strip() or "{}"
        else:
            return json.dumps({"error": result.stderr.strip()})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Command timed out"})
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"error": str(e)})


def _run_extension_call(
    extension: str,
    function: str,
    args: Dict[str, Any] = None,
    network: str = "staging",
    realm_folder: str = ".",
    timeout: int = 60
) -> str:
    """
    Run an extension sync call with JSON output.
    
    Args:
        extension: Extension name (e.g., "voting", "vault")
        function: Function to call
        args: Dictionary of arguments (will be JSON encoded)
        network: Network to use
        realm_folder: Working directory with dfx.json
        timeout: Command timeout in seconds
    
    Returns:
        JSON string result or error message
    """
    args_dict = args or {}
    args_json = json.dumps(args_dict).replace('"', '\\"')
    
    candid_args = f'(record {{ extension_name = "{extension}"; function_name = "{function}"; args = "{args_json}"; }})'
    
    return _run_dfx_call(
        canister="realm_backend",
        method="extension_sync_call",
        args=candid_args,
        network=network,
        realm_folder=realm_folder,
        timeout=timeout
    )


def _run_realms_cli(
    subcommand: list,
    network: str = "staging",
    realm_folder: str = ".",
    timeout: int = 30
) -> str:
    """
    Run a realms CLI command.
    
    Args:
        subcommand: List of subcommand parts (e.g., ["realm", "call", "status"])
        network: Network to use
        realm_folder: Working directory
        timeout: Command timeout in seconds
    
    Returns:
        Command output or error message
    """
    cmd = ["realms"] + subcommand + ["-n", network]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=realm_folder,
            env=_get_env()
        )
        if result.returncode == 0:
            return result.stdout.strip() or "{}"
        else:
            return json.dumps({"error": result.stderr.strip()})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Command timed out"})
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"error": str(e)})


# =============================================================================
# Citizen Tools
# =============================================================================

def join_realm(profile: str = "member", network: str = "staging", realm_folder: str = ".", realm_principal: str = "") -> str:
    """Join a realm as a citizen with a specific profile."""
    return _run_dfx_call(
        canister="realm_backend",
        method="join_realm",
        args=f'("{profile}")',
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal
    )


def set_profile_picture(profile_picture_url: str, network: str = "staging", realm_folder: str = ".", realm_principal: str = "") -> str:
    """Set your profile picture in the realm."""
    return _run_dfx_call(
        canister="realm_backend",
        method="update_my_profile_picture",
        args=f'("{profile_picture_url}")',
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal
    )


def get_my_status(network: str = "staging", realm_folder: str = ".", realm_principal: str = "") -> str:
    """Get your current user status in the realm."""
    return _run_dfx_call(
        canister="realm_backend",
        method="get_my_user_status",
        args="()",
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal
    )


def get_my_principal(network: str = "staging", realm_folder: str = ".", realm_principal: str = "") -> str:
    """Get your principal ID."""
    return _run_dfx_call(
        canister="realm_backend",
        method="get_my_principal",
        args="()",
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal
    )


# =============================================================================
# Realm Status Tools
# =============================================================================

def realm_status(network: str = "staging", realm_folder: str = ".", realm_principal: str = "") -> str:
    """Get the current status of the realm (users, proposals, votes, extensions)."""
    return _run_dfx_call(
        canister="realm_backend",
        method="status",
        args="()",
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal
    )


def db_get(entity_type: str, entity_id: Optional[str] = None, network: str = "staging", realm_folder: str = ".") -> str:
    """Get entities from the realm database. If entity_id is provided, get a specific entity."""
    # Normalize entity_type to title case (e.g., 'codex' -> 'Codex')
    entity_type = entity_type.title()
    subcommand = ["db", "-f", realm_folder, "get", entity_type]
    if entity_id:
        subcommand.append(entity_id)
    return _run_realms_cli(
        subcommand=subcommand,
        network=network,
        realm_folder=realm_folder
    )


# =============================================================================
# Governance / Voting Tools
# =============================================================================

def get_proposals(status: Optional[str] = None, network: str = "staging", realm_folder: str = ".") -> str:
    """Get governance proposals from the realm."""
    args = {"status": status} if status else {}
    return _run_extension_call(
        extension="voting",
        function="get_proposals",
        args=args,
        network=network,
        realm_folder=realm_folder
    )


def get_proposal(proposal_id: str, network: str = "staging", realm_folder: str = ".") -> str:
    """Get details of a specific proposal."""
    return _run_extension_call(
        extension="voting",
        function="get_proposal",
        args={"proposal_id": proposal_id},
        network=network,
        realm_folder=realm_folder
    )


def cast_vote(proposal_id: str, vote: str, voter_id: str, network: str = "staging", realm_folder: str = ".") -> str:
    """Cast a vote on a proposal (yes/no/abstain)."""
    if vote not in ["yes", "no", "abstain"]:
        return json.dumps({"error": f"vote must be 'yes', 'no', or 'abstain', got '{vote}'"})
    
    return _run_extension_call(
        extension="voting",
        function="cast_vote",
        args={"proposal_id": proposal_id, "vote": vote, "voter": voter_id},
        network=network,
        realm_folder=realm_folder
    )


def get_my_vote(proposal_id: str, voter_id: str, network: str = "staging", realm_folder: str = ".") -> str:
    """Check if you have already voted on a proposal."""
    return _run_extension_call(
        extension="voting",
        function="get_user_vote",
        args={"proposal_id": proposal_id, "voter": voter_id},
        network=network,
        realm_folder=realm_folder
    )


# =============================================================================
# Economic / Vault Tools
# =============================================================================

def get_balance(principal_id: Optional[str] = None, network: str = "staging", realm_folder: str = ".") -> str:
    """Get token balance for a principal in the vault."""
    # If no principal provided, get our own first
    if not principal_id:
        principal_result = get_my_principal(network=network, realm_folder=realm_folder)
        try:
            # Parse the JSON result to extract principal
            data = json.loads(principal_result)
            if isinstance(data, str):
                principal_id = data
            elif isinstance(data, dict) and "error" in data:
                return principal_result
        except json.JSONDecodeError:
            # Handle raw string output
            principal_id = principal_result.strip().strip('"')
    
    return _run_extension_call(
        extension="vault",
        function="get_balance",
        args={"principal_id": principal_id},
        network=network,
        realm_folder=realm_folder
    )


def get_transactions(principal_id: Optional[str] = None, network: str = "staging", realm_folder: str = ".") -> str:
    """Get transaction history for a principal."""
    if not principal_id:
        principal_result = get_my_principal(network=network, realm_folder=realm_folder)
        try:
            data = json.loads(principal_result)
            if isinstance(data, str):
                principal_id = data
            elif isinstance(data, dict) and "error" in data:
                return principal_result
        except json.JSONDecodeError:
            principal_id = principal_result.strip().strip('"')
    
    return _run_extension_call(
        extension="vault",
        function="get_transactions",
        args={"principal_id": principal_id},
        network=network,
        realm_folder=realm_folder
    )


def get_vault_status(network: str = "staging", realm_folder: str = ".") -> str:
    """Get vault status and statistics."""
    return _run_extension_call(
        extension="vault",
        function="get_status",
        args={},
        network=network,
        realm_folder=realm_folder
    )


# =============================================================================
# ICW Token Tools (Internet Computer Wallet)
# =============================================================================

def icw_check_balance(token: str = "ckbtc", principal: Optional[str] = None, network: str = "staging", realm_folder: str = ".") -> str:
    """Check token balance using icw CLI."""
    cmd = ["icw", "--token", token, "balance"]
    if principal:
        cmd.extend(["--principal", principal])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=_get_env())
        if result.returncode == 0:
            return json.dumps({"balance": result.stdout.strip(), "token": token})
        else:
            return json.dumps({"error": result.stderr.strip() or "Failed to get balance"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def icw_transfer_tokens(recipient: str, amount: str, token: str = "ckbtc", memo: Optional[str] = None, subaccount: Optional[str] = None, network: str = "staging", realm_folder: str = ".") -> str:
    """Transfer tokens to a recipient using icw CLI."""
    cmd = ["icw", "--token", token, "transfer", recipient, amount]
    if memo:
        cmd.extend(["--memo", memo])
    if subaccount:
        cmd.extend(["--subaccount", subaccount])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=_get_env())
        if result.returncode == 0:
            return json.dumps({"success": True, "message": result.stdout.strip(), "token": token, "amount": amount, "recipient": recipient})
        else:
            return json.dumps({"error": result.stderr.strip() or "Transfer failed"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def icw_get_address(network: str = "staging", realm_folder: str = ".") -> str:
    """Get wallet address (principal) for receiving tokens."""
    try:
        result = subprocess.run(["icw", "id"], capture_output=True, text=True, timeout=10, env=_get_env())
        if result.returncode == 0:
            return json.dumps({"address": result.stdout.strip()})
        else:
            return json.dumps({"error": result.stderr.strip() or "Failed to get address"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# =============================================================================
# Tool Definitions for Ollama (OpenAI-compatible format)
# =============================================================================

REALM_TOOLS = [
    # Citizen Tools
    {
        "type": "function",
        "function": {
            "name": "join_realm",
            "description": "Join the realm as a citizen. This registers you as a user with the specified profile (member or admin).",
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
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_principal",
            "description": "Get your principal ID (your unique identifier on the Internet Computer).",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    # Realm Status Tools
    {
        "type": "function",
        "function": {
            "name": "realm_status",
            "description": "Get the current status of the realm including counts for all entity types (users, proposals, votes, codexes, disputes, etc.) and installed extensions.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "db_get",
            "description": "Get entities from the realm database. Without entity_id, lists all entities of that type. With entity_id, gets a specific entity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "Type of entity to query from the realm database",
                        "enum": ["Balance", "Codex", "Dispute", "Identity", "Invoice", "Land", "License", "Mandate", "Organization", "Proposal", "Realm", "Task", "Transfer", "Treasury", "User", "UserProfile", "Vote"]
                    },
                    "entity_id": {
                        "type": "string",
                        "description": "Optional ID of a specific entity to retrieve. If omitted, lists all entities of the type."
                    }
                },
                "required": ["entity_type"]
            }
        }
    },
    # Governance / Voting Tools
    {
        "type": "function",
        "function": {
            "name": "get_proposals",
            "description": "Get governance proposals from the realm. Optionally filter by status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter proposals by status",
                        "enum": ["pending_review", "accepted", "rejected", "executed"]
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_proposal",
            "description": "Get details of a specific proposal by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {
                        "type": "string",
                        "description": "The proposal ID (e.g., 'prop_001')"
                    }
                },
                "required": ["proposal_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cast_vote",
            "description": "Cast a vote on a proposal. You must provide your voter_id (your user ID in the realm).",
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {
                        "type": "string",
                        "description": "The proposal ID to vote on"
                    },
                    "vote": {
                        "type": "string",
                        "description": "Your vote",
                        "enum": ["yes", "no", "abstain"]
                    },
                    "voter_id": {
                        "type": "string",
                        "description": "Your user ID in the realm"
                    }
                },
                "required": ["proposal_id", "vote", "voter_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_vote",
            "description": "Check if you have already voted on a proposal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {
                        "type": "string",
                        "description": "The proposal ID to check"
                    },
                    "voter_id": {
                        "type": "string",
                        "description": "Your user ID in the realm"
                    }
                },
                "required": ["proposal_id", "voter_id"]
            }
        }
    },
    # Economic / Vault Tools
    {
        "type": "function",
        "function": {
            "name": "get_balance",
            "description": "Get token balance for a principal in the vault. Defaults to your own balance if no principal specified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "principal_id": {
                        "type": "string",
                        "description": "Principal ID to check (optional, defaults to your own)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_transactions",
            "description": "Get transaction history for a principal. Defaults to your own if no principal specified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "principal_id": {
                        "type": "string",
                        "description": "Principal ID to check (optional, defaults to your own)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_vault_status",
            "description": "Get vault status and statistics including balances and canister configuration.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    # ICW Token Tools
    {
        "type": "function",
        "function": {
            "name": "icw_check_balance",
            "description": "Check token balance for yourself or another principal. Supports ckBTC, ckETH, ICP, ckUSDC, ckUSDT, and REALMS tokens.",
            "parameters": {
                "type": "object",
                "properties": {
                    "token": {
                        "type": "string",
                        "description": "Token to check balance for",
                        "enum": ["ckbtc", "cketh", "icp", "ckusdc", "ckusdt", "realms"],
                        "default": "ckbtc"
                    },
                    "principal": {
                        "type": "string",
                        "description": "Principal ID to check balance for (optional, defaults to your own)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "icw_transfer_tokens",
            "description": "Transfer tokens to another principal. Supports ckBTC, ckETH, ICP, ckUSDC, ckUSDT, and REALMS tokens.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Principal ID of the recipient"
                    },
                    "amount": {
                        "type": "string",
                        "description": "Amount to transfer (e.g., '0.001' for 0.001 ckBTC)"
                    },
                    "token": {
                        "type": "string",
                        "description": "Token to transfer",
                        "enum": ["ckbtc", "cketh", "icp", "ckusdc", "ckusdt", "realms"],
                        "default": "ckbtc"
                    },
                    "memo": {
                        "type": "string",
                        "description": "Optional memo/tag for the transaction (max 32 bytes)"
                    },
                    "subaccount": {
                        "type": "string",
                        "description": "Recipient subaccount hex (for invoice payments to vault)"
                    }
                },
                "required": ["recipient", "amount"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "icw_get_address",
            "description": "Get your wallet address (principal ID) for receiving tokens.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    }
]

# Map function names to actual functions
TOOL_FUNCTIONS = {
    # Citizen
    "join_realm": join_realm,
    "set_profile_picture": set_profile_picture,
    "get_my_status": get_my_status,
    "get_my_principal": get_my_principal,
    # Realm status
    "realm_status": realm_status,
    "db_get": db_get,
    # Governance
    "get_proposals": get_proposals,
    "get_proposal": get_proposal,
    "cast_vote": cast_vote,
    "get_my_vote": get_my_vote,
    # Economic
    "get_balance": get_balance,
    "get_transactions": get_transactions,
    "get_vault_status": get_vault_status,
    # ICW Token Tools
    "icw_check_balance": icw_check_balance,
    "icw_transfer_tokens": icw_transfer_tokens,
    "icw_get_address": icw_get_address,
}


def execute_tool(tool_name: str, arguments: dict, network: str = "staging", realm_folder: str = ".", realm_principal: str = "") -> str:
    """Execute a tool by name with given arguments."""
    if tool_name not in TOOL_FUNCTIONS:
        return json.dumps({"error": f"Unknown tool '{tool_name}'"})
    
    # Filter to only valid arguments for the function
    func = TOOL_FUNCTIONS[tool_name]
    import inspect
    valid_params = set(inspect.signature(func).parameters.keys())
    
    # Start with network, realm_folder, and realm_principal defaults
    filtered_args = {
        "network": network,
        "realm_folder": realm_folder,
        "realm_principal": realm_principal
    }
    
    # Add any valid arguments from the LLM
    for key, value in arguments.items():
        if key in valid_params:
            filtered_args[key] = value
    
    # Only pass realm_principal if the function accepts it
    if "realm_principal" not in valid_params:
        del filtered_args["realm_principal"]
    
    return func(**filtered_args)
