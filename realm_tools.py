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
import requests
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
    identity: str = "",
    realm_principal: str = ""
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
        identity=identity,
        realm_principal=realm_principal
    )


def _run_realms_cli(
    subcommand: list,
    network: str = "staging",
    realm_folder: str = ".",
    timeout: int = 30,
    realm_principal: str = "",
    identity: str = ""
) -> str:
    """
    Run a realms CLI command.
    
    Args:
        subcommand: List of subcommand parts (e.g., ["realm", "call", "status"])
        network: Network to use
        realm_folder: Working directory
        timeout: Command timeout in seconds
        realm_principal: Canister ID — when set, a temp dfx.json is created
        identity: dfx identity to use
    
    Returns:
        Command output or error message
    """
    import tempfile

    # When realm_principal is provided, create a minimal temp dfx.json
    # so the realms CLI resolves the canister correctly.
    tmp_dir = None
    effective_folder = realm_folder
    effective_subcommand = list(subcommand)
    if realm_principal:
        tmp_dir = tempfile.mkdtemp(prefix="realms_cli_")
        dfx_json = {
            "canisters": {
                "realm_backend": {
                    "type": "custom",
                    "candid": "realm_backend.did",
                    "build": "",
                    "remote": {"id": {network: realm_principal}}
                }
            }
        }
        with open(os.path.join(tmp_dir, "dfx.json"), "w") as f:
            json.dump(dfx_json, f)
        effective_folder = tmp_dir
        # Replace -f realm_folder with -f tmp_dir in subcommand
        effective_subcommand = [tmp_dir if s == realm_folder else s for s in effective_subcommand]

    # Network flag goes after 'realms' and before subcommand args
    cmd = ["realms", effective_subcommand[0], "-n", network] + effective_subcommand[1:]
    if identity:
        cmd.extend(["--identity", identity])
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=effective_folder,
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
    finally:
        if tmp_dir:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# Registry/Mundus Tools
# =============================================================================

def list_realms(network: str = "staging", realm_folder: str = ".") -> str:
    """List all available realms in the mundus registry."""
    import re
    
    cmd = ["realms", "registry", "realm", "list", "--network", network]
    
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
    cmd = ["realms", "registry", "realm", "search", "--query", query, "--network", network]
    
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


def registry_get_credits(principal_id: str, network: str = "staging", realm_folder: str = ".",
                        billing_url: str = "https://billing.realmsgos.dev") -> str:
    """Get credit balance for a principal from the registry."""
    try:
        resp = requests.get(f"{billing_url}/credits/{principal_id}", timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return json.dumps({
                "balance": data.get("credits", data.get("balance", 0)),
                "total_purchased": data.get("total_purchased", 0),
                "total_spent": data.get("total_spent", 0),
            })
        else:
            return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text[:200]}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def registry_redeem_voucher(
    principal_id: str,
    code: str,
    billing_url: str = "https://billing.realmsgos.dev",
    network: str = "staging",
    realm_folder: str = ".",
) -> str:
    """Redeem a voucher code to add credits to the agent's balance."""
    try:
        resp = requests.post(
            f"{billing_url}/voucher/redeem",
            json={"principal_id": principal_id, "code": code},
            timeout=30
        )
        if resp.status_code == 200:
            data = resp.json()
            return json.dumps({
                "success": True,
                "credits_added": data.get("credits_added", 0),
                "message": f"Voucher {code} redeemed successfully"
            })
        else:
            return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text[:200]}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def registry_deploy_realm(
    principal_id: str,
    realm_name: str,
    description: str = "",
    logo_url: str = "",
    welcome_image_url: str = "",
    welcome_message: str = "",
    management_url: str = "https://management.realmsgos.dev",
    network: str = "staging",
    realm_folder: str = ".",
) -> str:
    """Deploy a new realm via the management service. Returns a deployment_id for status polling."""
    try:
        realm_config = {
            "name": realm_name,
            "descriptions": {"en": description or f"Realm created by agent: {realm_name}"},
            "languages": ["en"],
            "welcome_messages": {"en": welcome_message or f"Welcome to {realm_name}!"},
            "token_enabled": True,
            "token_name": realm_name,
            "token_symbol": realm_name[:4].upper(),
            "extensions": [],
        }
        if logo_url:
            realm_config["logo_url"] = logo_url
        if welcome_image_url:
            realm_config["welcome_image_url"] = welcome_image_url
        resp = requests.post(
            f"{management_url}/api/deploy",
            json={
                "principal_id": principal_id,
                "realm_config": realm_config,
            },
            timeout=120
        )
        if resp.status_code == 200:
            data = resp.json()
            api_success = data.get("success", True)
            result = {
                "success": api_success,
                "deployment_id": data.get("deployment_id"),
            }
            if api_success:
                result["message"] = "Deployment started. Use registry_deploy_status to poll for completion."
            else:
                result["error"] = data.get("error") or data.get("message") or "Deploy failed"
                result["message"] = data.get("message", "Deploy request failed")
            return json.dumps(result)
        else:
            return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text[:200]}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def registry_deploy_status(
    deployment_id: str,
    management_url: str = "https://management.realmsgos.dev",
    wait: bool = True,
    network: str = "staging",
    realm_folder: str = ".",
) -> str:
    """Check deployment status. With wait=True, polls until completed or failed (up to 15 min)."""
    import time
    max_wait = 900  # 15 minutes
    poll_interval = 15
    start_time = time.time()
    
    try:
        while True:
            resp = requests.get(
                f"{management_url}/api/deploy/{deployment_id}",
                timeout=30
            )
            if resp.status_code != 200:
                return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text[:200]}"})
            
            data = resp.json()
            status = data.get("status", "unknown")
        
            result_data = {
                "status": status,
                "deployment_id": deployment_id,
            }
            if data.get("realm_url"):
                result_data["realm_url"] = data["realm_url"]
            if data.get("realm_id"):
                result_data["realm_id"] = data["realm_id"]
            if data.get("error"):
                result_data["error"] = data["error"][:200]
            
            # If not waiting or deployment finished, return immediately
            if not wait or status in ("completed", "failed"):
                return json.dumps(result_data)
            
            # Check timeout
            if time.time() - start_time > max_wait:
                result_data["warning"] = "Polling timed out after 15 minutes"
                return json.dumps(result_data)
            
            time.sleep(poll_interval)
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
    status_raw = _run_dfx_call(
        canister="realm_backend",
        method="status",
        args="()",
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal,
        identity=identity
    )
    # Enrich status with vote tallies (canister status doesn't include them)
    try:
        status_data = json.loads(status_raw) if isinstance(status_raw, str) else status_raw
        proposals_raw = get_proposals(network=network, realm_folder=realm_folder, identity=identity, realm_principal=realm_principal)
        proposals_data = json.loads(proposals_raw) if isinstance(proposals_raw, str) else proposals_raw
        resp = proposals_data.get("response", proposals_data)
        if isinstance(resp, str):
            resp = json.loads(resp)
        props = resp.get("data", {}).get("proposals", []) if isinstance(resp, dict) else []
        total_votes = sum(
            sum(p.get("votes", {}).values()) for p in props if isinstance(p, dict)
        )
        vote_summary = {p["id"]: p.get("votes", {}) for p in props if isinstance(p, dict) and p.get("id")}
        # Inject into status
        inner = status_data.get("data", {}).get("status", status_data) if isinstance(status_data, dict) else status_data
        if isinstance(inner, dict):
            inner["total_votes_cast"] = total_votes
            inner["votes_by_proposal"] = vote_summary
        return json.dumps(status_data)
    except Exception:
        return status_raw


def fetch_codex(codex_id: str, network: str = "staging", realm_principal: str = "", realm_folder: str = ".") -> Optional[Dict[str, Any]]:
    """Fetch a codex by ID from the realm canister. Returns dict with name/code or None."""
    args_json = json.dumps({"codex_id": codex_id}).replace('"', '\\"')
    candid_args = f'(record {{ extension_name = "codex_viewer"; function_name = "get_codex_details"; args = "{args_json}"; }})'
    raw = _run_dfx_call(
        canister="realm_backend",
        method="extension_sync_call",
        args=candid_args,
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal,
        timeout=30
    )
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        # Navigate response: may have success/response wrapper
        resp = parsed
        if isinstance(resp.get("response"), str):
            resp = json.loads(resp["response"])
        codex = resp.get("codex")
        if codex and codex.get("name"):
            return codex
    except Exception:
        pass
    return None


def db_get(entity_type: str, entity_id: Optional[str] = None, network: str = "staging", realm_folder: str = ".", realm_principal: str = "", identity: str = "") -> str:
    """Get entities from the realm database. If entity_id is provided, get a specific entity."""
    # Normalize entity_type to title case (e.g., 'codex' -> 'Codex')
    entity_type = entity_type.title()
    subcommand = ["db", "-f", realm_folder, "get", entity_type]
    if entity_id:
        subcommand.append(entity_id)
    return _run_realms_cli(
        subcommand=subcommand,
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal,
        identity=identity
    )


def db_schema(network: str = "staging", realm_folder: str = ".", realm_principal: str = "", identity: str = "") -> str:
    """Get the database schema showing all entity types, fields, and relationships.
    
    Use this to discover what entity types are available before querying with db_get.
    """
    subcommand = ["db", "-f", realm_folder, "schema"]
    return _run_realms_cli(
        subcommand=subcommand,
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal,
        identity=identity
    )


def find_objects(class_name: str, params: list = None, network: str = "staging", realm_folder: str = ".", realm_principal: str = "", identity: str = "") -> str:
    """Search for objects matching given field criteria.
    
    Args:
        class_name: Name of the entity class (e.g., "User", "Transfer", "Mandate")
        params: List of [field_name, field_value] pairs to match
        network: Network to use
        realm_folder: Working directory with dfx.json
        realm_principal: Canister ID for realm
        identity: dfx identity to use
    
    Returns:
        JSON string with matching objects or error
    """
    # Build the Candid vector of records for params
    if params:
        # Convert list of [field, value] pairs to Candid format
        param_records = "; ".join(
            f'record {{ 0 = "{p[0]}"; 1 = "{p[1]}"; }}' for p in params
        )
        args = f'("{class_name}", vec {{ {param_records} }})'
    else:
        args = f'("{class_name}", vec {{}})'
    
    return _run_dfx_call(
        canister="realm_backend",
        method="find_objects",
        args=args,
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal,
        identity=identity
    )


# =============================================================================
# Governance / Voting Tools
# =============================================================================

def get_proposals(status: Optional[str] = None, network: str = "staging", realm_folder: str = ".", identity: str = "", realm_principal: str = "") -> str:
    """Get governance proposals from the realm."""
    args = {"status": status} if status else {}
    return _run_extension_call(
        extension="voting",
        function="get_proposals",
        args=args,
        network=network,
        realm_folder=realm_folder,
        identity=identity,
        realm_principal=realm_principal
    )


def get_proposal(proposal_id: str, network: str = "staging", realm_folder: str = ".", identity: str = "", realm_principal: str = "") -> str:
    """Get details of a specific proposal."""
    return _run_extension_call(
        extension="voting",
        function="get_proposal",
        args={"proposal_id": proposal_id},
        network=network,
        realm_folder=realm_folder,
        identity=identity,
        realm_principal=realm_principal
    )


def cast_vote(proposal_id: str, vote: str, voter_id: str, network: str = "staging", realm_folder: str = ".", identity: str = "", realm_principal: str = "") -> str:
    """Cast a vote on a proposal (yes/no/abstain)."""
    if vote not in ["yes", "no", "abstain"]:
        return json.dumps({"error": f"vote must be 'yes', 'no', or 'abstain', got '{vote}'"})
    
    return _run_extension_call(
        extension="voting",
        function="cast_vote",
        args={"proposal_id": proposal_id, "vote": vote, "voter": voter_id},
        network=network,
        realm_folder=realm_folder,
        identity=identity,
        realm_principal=realm_principal
    )


def get_my_vote(proposal_id: str, voter_id: str, network: str = "staging", realm_folder: str = ".", identity: str = "", realm_principal: str = "") -> str:
    """Check if you have already voted on a proposal."""
    return _run_extension_call(
        extension="voting",
        function="get_user_vote",
        args={"proposal_id": proposal_id, "voter": voter_id},
        network=network,
        realm_folder=realm_folder,
        identity=identity,
        realm_principal=realm_principal
    )


def submit_proposal(title: str, description: str, proposer_id: str, code_url: str = "", network: str = "staging", realm_folder: str = ".", identity: str = "", realm_principal: str = "") -> str:
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
        identity=identity,
        realm_principal=realm_principal
    )


# =============================================================================
# Economic / Vault Tools
# =============================================================================

def get_balance(principal_id: Optional[str] = None, network: str = "staging", realm_folder: str = ".", realm_principal: str = "", identity: str = "") -> str:
    """Get token balance for a principal in the vault."""
    # If no principal provided, get our own first
    if not principal_id:
        principal_result = get_my_principal(network=network, realm_folder=realm_folder, realm_principal=realm_principal, identity=identity)
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
        realm_folder=realm_folder,
        realm_principal=realm_principal,
        identity=identity
    )


def get_transactions(principal_id: Optional[str] = None, network: str = "staging", realm_folder: str = ".", realm_principal: str = "", identity: str = "") -> str:
    """Get transaction history for a principal."""
    if not principal_id:
        principal_result = get_my_principal(network=network, realm_folder=realm_folder, realm_principal=realm_principal, identity=identity)
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
        realm_folder=realm_folder,
        realm_principal=realm_principal,
        identity=identity
    )


def get_vault_status(network: str = "staging", realm_folder: str = ".", realm_principal: str = "", identity: str = "") -> str:
    """Get vault status and statistics."""
    return _run_extension_call(
        extension="vault",
        function="get_status",
        args={},
        network=network,
        realm_folder=realm_folder,
        realm_principal=realm_principal,
        identity=identity
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


def pay_invoice(invoice_id: str, amount: str, recipient: str, token: str = "ckbtc", network: str = "staging", realm_folder: str = ".") -> str:
    """Pay a pending invoice by transferring tokens to the vault canister with the invoice's subaccount.
    
    The subaccount is automatically computed from the invoice ID (padded to 32 bytes, hex-encoded).
    Use db_get('Invoice') first to get the invoice_id, amount, and vault canister ID (recipient).
    
    Args:
        invoice_id: The invoice ID (e.g., 'inv_44843786bee9')
        amount: Amount to pay in token units (e.g., '1e-8' for 1 satoshi of ckBTC)
        recipient: The vault canister ID to pay to (from realm_status or invoice payment details)
        token: Token to use for payment (default: ckbtc)
    """
    # Compute subaccount hex: invoice ID encoded as bytes, padded to 32 bytes with null bytes
    subaccount_hex = invoice_id.encode().ljust(32, b'\x00').hex()
    
    cmd = ["icw", "--token", token, "transfer", recipient, amount, "--subaccount", subaccount_hex]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=_get_env())
        if result.returncode == 0:
            return json.dumps({
                "success": True,
                "message": result.stdout.strip(),
                "invoice_id": invoice_id,
                "token": token,
                "amount": amount,
                "recipient": recipient,
                "subaccount": subaccount_hex
            })
        else:
            return json.dumps({"error": result.stderr.strip() or "Payment failed", "invoice_id": invoice_id})
    except Exception as e:
        return json.dumps({"error": str(e), "invoice_id": invoice_id})


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
# Tool Definitions & Dispatch (auto-generated from MCP server)
#
# The MCP server (mcp_server.py) is the single source of truth for tool
# schemas and descriptions. REALM_TOOLS and TOOL_FUNCTIONS are derived
# from it so that Ollama agents and external MCP clients share the
# exact same tool surface.
# =============================================================================

def _load_mcp_tools():
    """Import tool schemas and dispatch map from the MCP server."""
    from mcp_server import get_realm_tools, get_tool_functions
    return get_realm_tools(), get_tool_functions()


# Lazy-loaded module-level singletons.  Accessed via the public helpers
# below so that the (slightly heavy) MCP import only happens once and
# only when something actually needs the tool list.
_realm_tools_cache = None
_tool_functions_cache = None


def _ensure_loaded():
    global _realm_tools_cache, _tool_functions_cache
    if _realm_tools_cache is None:
        _realm_tools_cache, _tool_functions_cache = _load_mcp_tools()


# Public accessors (backward-compatible names) --------------------------------

def get_realm_tools() -> list:
    """Return REALM_TOOLS (OpenAI-compatible tool schemas)."""
    _ensure_loaded()
    return _realm_tools_cache


def get_tool_functions() -> dict:
    """Return TOOL_FUNCTIONS dispatch map {name: callable}."""
    _ensure_loaded()
    return _tool_functions_cache


# For backward compatibility, expose module-level names that lazy-load.
# Code doing ``from realm_tools import REALM_TOOLS`` will get the list
# on first attribute access thanks to the lazy loader below.
class _LazyModule:
    """Tiny helper so that ``REALM_TOOLS`` and ``TOOL_FUNCTIONS`` work
    as module-level attributes while still being lazy-loaded."""

    def __init__(self, module):
        self.__dict__['_module'] = module

    def __getattr__(self, name):
        if name == 'REALM_TOOLS':
            _ensure_loaded()
            return _realm_tools_cache
        if name == 'TOOL_FUNCTIONS':
            _ensure_loaded()
            return _tool_functions_cache
        return getattr(self.__dict__['_module'], name)

    def __setattr__(self, name, value):
        if name in ('REALM_TOOLS', 'TOOL_FUNCTIONS'):
            raise AttributeError(f"{name} is auto-generated from the MCP server and cannot be set directly")
        setattr(self.__dict__['_module'], name, value)

    def __delattr__(self, name):
        delattr(self.__dict__['_module'], name)

import sys as _sys
_sys.modules[__name__] = _LazyModule(_sys.modules[__name__])


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
    _ensure_loaded()
    if tool_name not in _tool_functions_cache:
        return json.dumps({"error": f"Unknown tool '{tool_name}'"})
    
    # If LLM passes realm_id in arguments, use it as realm_principal
    if 'realm_id' in arguments:
        llm_realm_id = arguments.pop('realm_id', '')
        if llm_realm_id:
            realm_principal = llm_realm_id
    
    # Filter to only valid arguments for the function
    func = _tool_functions_cache[tool_name]
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
    
    try:
        return func(**filtered_args)
    except TypeError as e:
        # LLM omitted a required argument – return error so it can self-correct
        return json.dumps({"error": str(e)})
