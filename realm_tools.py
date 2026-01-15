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
    realm_principal: str = "",
    identity: str = ""
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
        identity: dfx identity to use for the call (uses current identity if not specified)
    
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
    
    # Use specific identity if provided
    if identity:
        cmd.extend(["--identity", identity])
    
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
    timeout: int = 60,
    identity: str = ""
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
        identity: dfx identity to use for the call
    
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
        timeout=timeout,
        identity=identity
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
    # Network flag goes after 'realms' and before subcommand args
    cmd = ["realms", subcommand[0], "-n", network] + subcommand[1:]
    
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
# Registry/Mundus Tools
# =============================================================================

def list_realms(network: str = "staging", realm_folder: str = ".") -> str:
    """List all available realms in the mundus registry."""
    import re
    
    cmd = ["realms", "registry", "list", "--network", network]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=realm_folder,
            env=_get_env()
        )
        
        output = result.stdout + result.stderr
        
        # Parse the Candid output to extract realm info
        realms = []
        # Match record blocks
        record_pattern = r'record \{([^}]+)\}'
        for match in re.finditer(record_pattern, output, re.DOTALL):
            record_text = match.group(1)
            realm = {}
            
            # Extract fields
            id_match = re.search(r'id = "([^"]+)"', record_text)
            name_match = re.search(r'name = "([^"]+)"', record_text)
            url_match = re.search(r'url = "([^"]+)"', record_text)
            backend_match = re.search(r'backend_url = "([^"]+)"', record_text)
            users_match = re.search(r'users_count = (\d+)', record_text)
            
            if id_match:
                realm['id'] = id_match.group(1)
            if name_match:
                realm['name'] = name_match.group(1)
            if url_match:
                realm['url'] = f"https://{url_match.group(1)}"
            if backend_match:
                realm['backend_url'] = backend_match.group(1)
            if users_match:
                realm['users_count'] = int(users_match.group(1))
            
            if realm.get('name'):
                realms.append(realm)
        
        if realms:
            return json.dumps({"realms": realms, "count": len(realms)})
        elif "Error" in output:
            return json.dumps({"error": output})
        else:
            return json.dumps({"realms": [], "count": 0, "message": "No realms found in registry"})
            
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Command timed out"})
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"error": str(e)})


def search_realm(query: str, network: str = "staging", realm_folder: str = ".") -> str:
    """Search for a realm by name in the mundus registry."""
    cmd = ["realms", "registry", "search", "--query", query, "--network", network]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=realm_folder,
            env=_get_env()
        )
        return result.stdout.strip() or result.stderr.strip() or json.dumps({"message": "No results found"})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Command timed out"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# =============================================================================
# Citizen Tools
# =============================================================================

def join_realm(profile: str = "member", network: str = "staging", realm_folder: str = ".", realm_principal: str = "", identity: str = "") -> str:
    """Join a realm as a citizen with a specific profile."""
    return _run_dfx_call(
        canister="realm_backend",
        method="join_realm",
        args=f'("{profile}")',
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal,
        identity=identity
    )


def set_profile_picture(profile_picture_url: str, network: str = "staging", realm_folder: str = ".", realm_principal: str = "", identity: str = "") -> str:
    """Set your profile picture in the realm."""
    return _run_dfx_call(
        canister="realm_backend",
        method="update_my_profile_picture",
        args=f'("{profile_picture_url}")',
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal,
        identity=identity
    )


def get_my_status(network: str = "staging", realm_folder: str = ".", realm_principal: str = "", identity: str = "") -> str:
    """Get your current user status in the realm."""
    return _run_dfx_call(
        canister="realm_backend",
        method="get_my_user_status",
        args="()",
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal,
        identity=identity
    )


def get_my_principal(network: str = "staging", realm_folder: str = ".", realm_principal: str = "", identity: str = "") -> str:
    """Get your principal ID."""
    return _run_dfx_call(
        canister="realm_backend",
        method="get_my_principal",
        args="()",
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal,
        identity=identity
    )


# =============================================================================
# Realm Status Tools
# =============================================================================

def realm_status(network: str = "staging", realm_folder: str = ".", realm_principal: str = "", identity: str = "") -> str:
    """Get the current status of the realm (users, proposals, votes, extensions)."""
    return _run_dfx_call(
        canister="realm_backend",
        method="status",
        args="()",
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal,
        identity=identity
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


def db_schema(network: str = "staging", realm_folder: str = ".") -> str:
    """Get the database schema showing all entity types, fields, and relationships.
    
    Use this to discover what entity types are available before querying with db_get.
    """
    subcommand = ["db", "-f", realm_folder, "schema"]
    return _run_realms_cli(
        subcommand=subcommand,
        network=network,
        realm_folder=realm_folder
    )


# =============================================================================
# Governance / Voting Tools
# =============================================================================

def get_proposals(status: Optional[str] = None, network: str = "staging", realm_folder: str = ".", identity: str = "") -> str:
    """Get governance proposals from the realm."""
    args = {"status": status} if status else {}
    return _run_extension_call(
        extension="voting",
        function="get_proposals",
        args=args,
        network=network,
        realm_folder=realm_folder,
        identity=identity
    )


def get_proposal(proposal_id: str, network: str = "staging", realm_folder: str = ".", identity: str = "") -> str:
    """Get details of a specific proposal."""
    return _run_extension_call(
        extension="voting",
        function="get_proposal",
        args={"proposal_id": proposal_id},
        network=network,
        realm_folder=realm_folder,
        identity=identity
    )


def cast_vote(proposal_id: str, vote: str, voter_id: str, network: str = "staging", realm_folder: str = ".", identity: str = "") -> str:
    """Cast a vote on a proposal (yes/no/abstain)."""
    if vote not in ["yes", "no", "abstain"]:
        return json.dumps({"error": f"vote must be 'yes', 'no', or 'abstain', got '{vote}'"})
    
    return _run_extension_call(
        extension="voting",
        function="cast_vote",
        args={"proposal_id": proposal_id, "vote": vote, "voter": voter_id},
        network=network,
        realm_folder=realm_folder,
        identity=identity
    )


def get_my_vote(proposal_id: str, voter_id: str, network: str = "staging", realm_folder: str = ".", identity: str = "") -> str:
    """Check if you have already voted on a proposal."""
    return _run_extension_call(
        extension="voting",
        function="get_user_vote",
        args={"proposal_id": proposal_id, "voter": voter_id},
        network=network,
        realm_folder=realm_folder,
        identity=identity
    )


def submit_proposal(title: str, description: str, proposer_id: str, code_url: str = "", network: str = "staging", realm_folder: str = ".", identity: str = "") -> str:
    """Submit a new proposal for voting."""
    # code_url is required by the voting extension - provide default if empty
    if not code_url:
        code_url = "https://realms.vote/proposal/discussion"
    
    args = {
        "title": title,
        "description": description,
        "proposer": proposer_id,
        "code_url": code_url
    }
    
    return _run_extension_call(
        extension="voting",
        function="submit_proposal",
        args=args,
        network=network,
        realm_folder=realm_folder,
        identity=identity
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
    # Registry/Mundus Tools
    {
        "type": "function",
        "function": {
            "name": "list_realms",
            "description": "List all available realms in the mundus registry. Returns realm names, IDs, URLs, and user counts. Use this to discover what realms exist before joining one.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_realm",
            "description": "Search for a specific realm by name in the mundus registry. Returns detailed information about matching realms.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (realm name or partial name)"
                    }
                },
                "required": ["query"]
            }
        }
    },
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
            "name": "db_schema",
            "description": "Get the database schema showing all available entity types, their fields, and relationships. Use this first to discover what entity types exist before querying with db_get.",
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
            "name": "db_get",
            "description": "Get entities from the realm database. Without entity_id, lists all entities of that type. With entity_id, gets a specific entity. Use db_schema first to discover available entity types.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "Type of entity to query (e.g., User, Notification, Transfer). Use db_schema to discover available types."
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
            "description": "Cast a vote on a proposal. Your voter_id is automatically filled from your identity.",
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
                    }
                },
                "required": ["proposal_id", "vote"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_vote",
            "description": "Check if you have already voted on a proposal. Your voter_id is automatically filled from your identity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {
                        "type": "string",
                        "description": "The proposal ID to check"
                    }
                },
                "required": ["proposal_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "submit_proposal",
            "description": "Submit a new proposal for voting. Your proposer_id is automatically filled from your identity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title of the proposal (short, descriptive)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of the proposal"
                    },
                    "code_url": {
                        "type": "string",
                        "description": "URL to proposal code/implementation or discussion link (defaults to generic link if not provided)"
                    }
                },
                "required": ["title", "description"]
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
    # Registry/Mundus
    "list_realms": list_realms,
    "search_realm": search_realm,
    # Citizen
    "join_realm": join_realm,
    "set_profile_picture": set_profile_picture,
    "get_my_status": get_my_status,
    "get_my_principal": get_my_principal,
    # Realm status
    "realm_status": realm_status,
    "db_schema": db_schema,
    "db_get": db_get,
    # Governance
    "get_proposals": get_proposals,
    "get_proposal": get_proposal,
    "cast_vote": cast_vote,
    "get_my_vote": get_my_vote,
    "submit_proposal": submit_proposal,
    # Economic
    "get_balance": get_balance,
    "get_transactions": get_transactions,
    "get_vault_status": get_vault_status,
    # ICW Token Tools
    "icw_check_balance": icw_check_balance,
    "icw_transfer_tokens": icw_transfer_tokens,
    "icw_get_address": icw_get_address,
}


def execute_tool(tool_name: str, arguments: dict, network: str = "staging", realm_folder: str = ".", realm_principal: str = "", user_principal: str = "", user_identity: str = "") -> str:
    """Execute a tool by name with given arguments.
    
    Args:
        tool_name: Name of the tool to execute
        arguments: Arguments from the LLM
        network: Network to use
        realm_folder: Working directory
        realm_principal: Canister ID for realm
        user_principal: User's IC principal (for auto-filling voter_id, proposer_id)
        user_identity: dfx identity name to use for calls (e.g., 'swarm_agent_005')
    """
    if tool_name not in TOOL_FUNCTIONS:
        return json.dumps({"error": f"Unknown tool '{tool_name}'"})
    
    # Filter to only valid arguments for the function
    func = TOOL_FUNCTIONS[tool_name]
    import inspect
    valid_params = set(inspect.signature(func).parameters.keys())
    
    # Start with network, realm_folder, realm_principal, and identity defaults
    filtered_args = {
        "network": network,
        "realm_folder": realm_folder,
        "realm_principal": realm_principal,
        "identity": user_identity
    }
    
    # Auto-fill voter_id from user_principal for voting tools (agent's identity)
    if "voter_id" in valid_params and "voter_id" not in arguments and user_principal:
        filtered_args["voter_id"] = user_principal
    
    # Auto-fill proposer_id from user_principal for submit_proposal tool
    if "proposer_id" in valid_params and "proposer_id" not in arguments and user_principal:
        filtered_args["proposer_id"] = user_principal
    
    # Add any valid arguments from the LLM
    for key, value in arguments.items():
        if key in valid_params:
            filtered_args[key] = value
    
    # Only pass parameters the function accepts
    if "realm_principal" not in valid_params:
        del filtered_args["realm_principal"]
    if "identity" not in valid_params:
        del filtered_args["identity"]
    
    return func(**filtered_args)
