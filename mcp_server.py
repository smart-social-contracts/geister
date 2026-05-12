#!/usr/bin/env python3
"""
Realm MCP Server - Exposes realm tools via the Model Context Protocol.

This is the single source of truth for tool definitions. Both MCP clients
(Windsurf, Claude, Cursor, etc.) and the internal Ollama flow consume
tools from this server.

Usage:
    # Run as remote HTTP server (for third-party access)
    python mcp_server.py --transport http --host 0.0.0.0 --port 8090

    # Run as stdio server (for local IDE integrations)
    python mcp_server.py --transport stdio

    # Or programmatically import the server for schema generation
    from mcp_server import mcp, get_ollama_tools
"""
from typing import Annotated, Optional, Literal
from fastmcp import FastMCP

from realm_tools import (
    # Registry/Mundus
    list_realms as _list_realms,
    search_realm as _search_realm,
    registry_get_credits as _registry_get_credits,
    registry_redeem_voucher as _registry_redeem_voucher,
    registry_deploy_realm as _registry_deploy_realm,
    registry_deploy_status as _registry_deploy_status,
    # Citizen
    join_realm as _join_realm,
    set_profile_picture as _set_profile_picture,
    get_my_status as _get_my_status,
    get_my_principal as _get_my_principal,
    # Realm Status
    realm_status as _realm_status,
    db_schema as _db_schema,
    db_get as _db_get,
    find_objects as _find_objects,
    # Governance
    get_proposals as _get_proposals,
    get_proposal as _get_proposal,
    cast_vote as _cast_vote,
    get_my_vote as _get_my_vote,
    submit_proposal as _submit_proposal,
    # Economic / Vault
    get_balance as _get_balance,
    get_transactions as _get_transactions,
    get_vault_status as _get_vault_status,
    # ICW Token Tools
    icw_check_balance as _icw_check_balance,
    icw_transfer_tokens as _icw_transfer_tokens,
    pay_invoice as _pay_invoice,
    icw_get_address as _icw_get_address,
)

mcp = FastMCP(
    "Realms Governance",
    instructions="Tools for interacting with Realms — decentralized governance communities on the Internet Computer.",
)


# =============================================================================
# Registry/Mundus Tools
# =============================================================================

@mcp.tool
def list_realms() -> str:
    """List all available realms in the mundus registry. Returns realm names, IDs, URLs, and user counts. Use this to discover what realms exist before joining one."""
    return _list_realms()


@mcp.tool
def search_realm(
    query: Annotated[str, "Search query (realm name or partial name)"],
) -> str:
    """Search for a specific realm by name in the mundus registry. Returns detailed information about matching realms."""
    return _search_realm(query=query)


@mcp.tool
def registry_get_credits(
    principal_id: Annotated[str, "Principal ID to check credits for"],
) -> str:
    """Check the agent's credit balance in the registry. Credits are needed to deploy realms (5 credits per realm)."""
    return _registry_get_credits(principal_id=principal_id)


@mcp.tool
def registry_redeem_voucher(
    principal_id: Annotated[str, "Principal ID to add credits to"],
    code: Annotated[str, "Voucher code to redeem (e.g., 'BETA50', 'WELCOME10', 'TEST5')"],
) -> str:
    """Redeem a voucher code to add credits to the agent's balance. Use code 'BETA50' for 50 credits."""
    return _registry_redeem_voucher(principal_id=principal_id, code=code)


@mcp.tool
def registry_deploy_realm(
    realm_name: Annotated[str, "Name for the new realm"],
    description: Annotated[str, "A compelling description of the realm's purpose and vision"] = "",
    logo_url: Annotated[str, "Unused in queue deploy (reserved)"] = "",
    welcome_image_url: Annotated[str, "Unused in queue deploy (reserved)"] = "",
    welcome_message: Annotated[str, "Welcome message shown to new citizens joining the realm"] = "",
    network: Annotated[str, "IC network, e.g. staging or demo"] = "staging",
) -> str:
    """Enqueue realm deployment via realm_registry_backend.request_deployment (dfx + credits). Returns job_id; call registry_deploy_status next."""
    return _registry_deploy_realm(
        realm_name=realm_name,
        description=description,
        logo_url=logo_url,
        welcome_image_url=welcome_image_url,
        welcome_message=welcome_message,
        network=network,
    )


@mcp.tool
def registry_deploy_status(
    job_id: Annotated[str, "job_id returned by registry_deploy_realm"],
    wait: Annotated[bool, "If true, wait for deployment to complete (polls periodically). Default: true."] = True,
    network: Annotated[str, "IC network"] = "staging",
) -> str:
    """Poll realm_installer for job status. With wait=true, polls until completed or failed (up to 15 minutes)."""
    return _registry_deploy_status(job_id=job_id, wait=wait, network=network)


# =============================================================================
# Citizen Tools
# =============================================================================

@mcp.tool
def join_realm(
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
    profile: Annotated[str, "Profile type to join with ('member' or 'admin')"] = "member",
) -> str:
    """Join the realm as a citizen. This registers you as a user with the specified profile (member or admin)."""
    return _join_realm(profile=profile, realm_principal=realm_id)


@mcp.tool
def set_profile_picture(
    profile_picture_url: Annotated[str, "URL to the profile picture image (e.g., https://api.dicebear.com/7.x/personas/svg?seed=MyName)"],
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Set your profile picture in the realm. Provide a URL to an image."""
    return _set_profile_picture(profile_picture_url=profile_picture_url, realm_principal=realm_id)


@mcp.tool
def get_my_status(
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Get your current user status in the realm, including your principal ID, profiles, and profile picture URL."""
    return _get_my_status(realm_principal=realm_id)


@mcp.tool
def get_my_principal(
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Get your principal ID (your unique identifier on the Internet Computer)."""
    return _get_my_principal(realm_principal=realm_id)


# =============================================================================
# Realm Status Tools
# =============================================================================

@mcp.tool
def realm_status(
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Get the current status of the realm including counts for all entity types (users, proposals, votes, codexes, disputes, etc.) and installed extensions."""
    return _realm_status(realm_principal=realm_id)


@mcp.tool
def db_schema(
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Get the database schema showing all available entity types, their fields, and relationships. Use this first to discover what entity types exist before querying with db_get."""
    return _db_schema(realm_principal=realm_id)


@mcp.tool
def db_get(
    entity_type: Annotated[str, "Type of entity to query (e.g., User, Notification, Transfer). Use db_schema to discover available types."],
    entity_id: Annotated[Optional[str], "Optional ID of a specific entity to retrieve. If omitted, lists all entities of the type."] = None,
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Get entities from the realm database. Without entity_id, lists all entities of that type. With entity_id, gets a specific entity. Use db_schema first to discover available entity types."""
    return _db_get(entity_type=entity_type, entity_id=entity_id, realm_principal=realm_id)


@mcp.tool
def find_objects(
    class_name: Annotated[str, "Name of the entity class (e.g., 'User', 'Transfer', 'Mandate', 'Proposal')"],
    params: Annotated[Optional[list], "List of [field_name, field_value] pairs to match. Example: [['id', 'system'], ['status', 'active']]"] = None,
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Search for objects matching given field criteria. More flexible than db_get - allows filtering by any field values. Use db_schema first to discover available entity types and their fields."""
    return _find_objects(class_name=class_name, params=params, realm_principal=realm_id)


# =============================================================================
# Governance / Voting Tools
# =============================================================================

@mcp.tool
def get_proposals(
    status: Annotated[Optional[str], "Filter proposals by status: 'pending_review', 'accepted', 'rejected', or 'executed'"] = None,
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Get governance proposals from the realm. Optionally filter by status."""
    return _get_proposals(status=status, realm_principal=realm_id)


@mcp.tool
def get_proposal(
    proposal_id: Annotated[str, "The proposal ID (e.g., 'prop_001')"],
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Get details of a specific proposal by ID."""
    return _get_proposal(proposal_id=proposal_id, realm_principal=realm_id)


@mcp.tool
def cast_vote(
    proposal_id: Annotated[str, "The proposal ID to vote on"],
    vote: Annotated[str, "Your vote: 'yes', 'no', or 'abstain'"],
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Cast a vote on a proposal. Your voter_id is automatically filled from your identity."""
    return _cast_vote(proposal_id=proposal_id, vote=vote, voter_id="", realm_principal=realm_id)


@mcp.tool
def get_my_vote(
    proposal_id: Annotated[str, "The proposal ID to check"],
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Check if you have already voted on a proposal. Your voter_id is automatically filled from your identity."""
    return _get_my_vote(proposal_id=proposal_id, voter_id="", realm_principal=realm_id)


@mcp.tool
def submit_proposal(
    title: Annotated[str, "Title of the proposal (short, descriptive)"],
    description: Annotated[str, "Detailed description of the proposal"],
    code_url: Annotated[str, "URL to proposal code/implementation or discussion link (defaults to generic link if not provided)"] = "",
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Submit a new proposal for voting. Your proposer_id is automatically filled from your identity."""
    return _submit_proposal(title=title, description=description, proposer_id="", code_url=code_url, realm_principal=realm_id)


# =============================================================================
# Economic / Vault Tools
# =============================================================================

@mcp.tool
def get_balance(
    principal_id: Annotated[Optional[str], "Principal ID to check (optional, defaults to your own)"] = None,
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Get token balance for a principal in the vault. Defaults to your own balance if no principal specified."""
    return _get_balance(principal_id=principal_id, realm_principal=realm_id)


@mcp.tool
def get_transactions(
    principal_id: Annotated[Optional[str], "Principal ID to check (optional, defaults to your own)"] = None,
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Get transaction history for a principal. Defaults to your own if no principal specified."""
    return _get_transactions(principal_id=principal_id, realm_principal=realm_id)


@mcp.tool
def get_vault_status(
    realm_id: Annotated[str, "Canister ID of the realm to interact with (from list_realms results). Always pass this when targeting a specific realm."] = "",
) -> str:
    """Get vault status and statistics including balances and canister configuration."""
    return _get_vault_status(realm_principal=realm_id)


# =============================================================================
# ICW Token Tools
# =============================================================================

@mcp.tool
def icw_check_balance(
    token: Annotated[str, "Token to check balance for: 'ckbtc', 'cketh', 'icp', 'ckusdc', 'ckusdt', or 'realms'"] = "ckbtc",
    principal: Annotated[Optional[str], "Principal ID to check balance for (optional, defaults to your own)"] = None,
) -> str:
    """Check token balance for yourself or another principal. Supports ckBTC, ckETH, ICP, ckUSDC, ckUSDT, and REALMS tokens."""
    return _icw_check_balance(token=token, principal=principal)


@mcp.tool
def icw_transfer_tokens(
    recipient: Annotated[str, "Principal ID of the recipient"],
    amount: Annotated[str, "Amount to transfer (e.g., '0.001' for 0.001 ckBTC)"],
    token: Annotated[str, "Token to transfer: 'ckbtc', 'cketh', 'icp', 'ckusdc', 'ckusdt', or 'realms'"] = "ckbtc",
    memo: Annotated[Optional[str], "Optional memo/tag for the transaction (max 32 bytes)"] = None,
    subaccount: Annotated[Optional[str], "Recipient subaccount hex (for invoice payments to vault)"] = None,
) -> str:
    """Transfer tokens to another principal. Supports ckBTC, ckETH, ICP, ckUSDC, ckUSDT, and REALMS tokens."""
    return _icw_transfer_tokens(recipient=recipient, amount=amount, token=token, memo=memo, subaccount=subaccount)


@mcp.tool
def pay_invoice(
    invoice_id: Annotated[str, "The invoice ID from db_get('Invoice') results (e.g., 'inv_44843786bee9')"],
    amount: Annotated[str, "Amount to pay in token units (e.g., '1e-8' for 1 satoshi of ckBTC). Get this from the invoice amount field."],
    recipient: Annotated[str, "The vault canister ID to pay to. Get this from realm_status vault extension info or the realm's backend_url canister."],
    token: Annotated[str, "Token for payment: 'ckbtc', 'cketh', 'icp', 'ckusdc', 'ckusdt', or 'realms'"] = "ckbtc",
) -> str:
    """Pay a pending invoice. First use db_get('Invoice') to list invoices and get invoice_id, amount, and the vault canister ID (recipient). The subaccount is computed automatically from the invoice ID."""
    return _pay_invoice(invoice_id=invoice_id, amount=amount, recipient=recipient, token=token)


@mcp.tool
def icw_get_address() -> str:
    """Get your wallet address (principal ID) for receiving tokens."""
    return _icw_get_address()


# =============================================================================
# Ollama Integration Helpers
# =============================================================================

def _list_mcp_tools():
    """Synchronously fetch tool definitions from the FastMCP server."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(lambda: asyncio.run(mcp.list_tools())).result()
    return asyncio.run(mcp.list_tools())


def get_ollama_tools() -> list:
    """Convert MCP tool definitions to OpenAI-compatible format for Ollama.

    This is the bridge between the MCP single source of truth and
    Ollama's /api/chat tool calling interface.
    """
    tools = []
    for tool in _list_mcp_tools():
        schema = dict(tool.parameters) if tool.parameters else {"type": "object", "properties": {}, "required": []}

        # Clean up schema: remove pydantic metadata keys that Ollama doesn't need
        schema.pop("title", None)
        schema.pop("$defs", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)

        # Ensure required is present
        if "required" not in schema:
            schema["required"] = []

        tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": schema,
            }
        })
    return tools


# Convenience aliases for backward compatibility
_REALM_TOOLS = None  # Lazy-loaded, see get_realm_tools()
_TOOL_FUNCTIONS = None  # Lazy-loaded, see get_tool_functions()


def get_realm_tools() -> list:
    """Get REALM_TOOLS (OpenAI-compatible format). Lazy singleton."""
    global _REALM_TOOLS
    if _REALM_TOOLS is None:
        _REALM_TOOLS = get_ollama_tools()
    return _REALM_TOOLS


# Map MCP tool names → raw realm_tools functions (which accept infrastructure
# params like network, realm_folder, realm_principal, identity).  execute_tool()
# needs these raw functions, not the MCP wrappers.
_RAW_TOOL_FUNCTIONS = {
    # Registry/Mundus
    "list_realms": _list_realms,
    "search_realm": _search_realm,
    "registry_get_credits": _registry_get_credits,
    "registry_redeem_voucher": _registry_redeem_voucher,
    "registry_deploy_realm": _registry_deploy_realm,
    "registry_deploy_status": _registry_deploy_status,
    # Citizen
    "join_realm": _join_realm,
    "set_profile_picture": _set_profile_picture,
    "get_my_status": _get_my_status,
    "get_my_principal": _get_my_principal,
    # Realm status
    "realm_status": _realm_status,
    "db_schema": _db_schema,
    "db_get": _db_get,
    "find_objects": _find_objects,
    # Governance
    "get_proposals": _get_proposals,
    "get_proposal": _get_proposal,
    "cast_vote": _cast_vote,
    "get_my_vote": _get_my_vote,
    "submit_proposal": _submit_proposal,
    # Economic
    "get_balance": _get_balance,
    "get_transactions": _get_transactions,
    "get_vault_status": _get_vault_status,
    # ICW Token Tools
    "icw_check_balance": _icw_check_balance,
    "icw_transfer_tokens": _icw_transfer_tokens,
    "pay_invoice": _pay_invoice,
    "icw_get_address": _icw_get_address,
}


def get_tool_functions() -> dict:
    """Get TOOL_FUNCTIONS dispatch map {name: raw_callable}.

    Returns the *raw* realm_tools functions (not MCP wrappers) so that
    execute_tool() can inject infrastructure params (network, realm_folder,
    realm_principal, identity) that are hidden from the LLM-facing schema.
    """
    return dict(_RAW_TOOL_FUNCTIONS)


if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Realms Governance MCP Server")
    parser.add_argument(
        "--transport", choices=["http", "stdio"], 
        default=os.getenv("MCP_TRANSPORT", "http"),
        help="Transport protocol (default: http)"
    )
    parser.add_argument(
        "--host", default=os.getenv("MCP_HOST", "0.0.0.0"),
        help="Host to bind to for HTTP transport (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("MCP_PORT", "8090")),
        help="Port to bind to for HTTP transport (default: 8090)"
    )
    args = parser.parse_args()

    if args.transport == "http":
        print(f"Starting Realms MCP Server on http://{args.host}:{args.port}")
        print(f"  Streamable HTTP endpoint: http://{args.host}:{args.port}/mcp")
        print(f"  {len(_RAW_TOOL_FUNCTIONS)} tools available")
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")
