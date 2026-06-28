#!/usr/bin/env python3
"""
Geister MCP server (Streamable HTTP).

Exposes Geister's realm tools (the same `REALM_TOOLS` the in-app assistant
uses) to MCP clients such as the user's own Claude. Every tool call is scoped
to the IC principal the bearer token authenticates as.

Two authentication tiers are accepted on /mcp, transparently:

  * Tier 2 (OAuth 2.1, recommended): the client discovers the server via
    `/.well-known/oauth-protected-resource`, dynamically registers (RFC 7591),
    runs the PKCE authorization-code flow (`/authorize` -> Internet Identity
    consent on the registry -> `/token`) and presents `rgoa_...` access tokens.
    Install-free: no Node, no `mcp-remote`, no copy-pasted secret.

  * Tier 1 (personal pairing token): the user mints `rgmcp_...` and presents it
    as a bearer token (via `mcp-remote`). Kept for backwards compatibility.

Run:
    GEISTER_MCP_PORT=5001 vm/venv/bin/python3 mcp_server.py

Transport: Streamable HTTP at /mcp (stateless). Health at /healthz.
Sits behind the realms-vm Cloudflare tunnel as geister-mcp.realmsgos.dev.
"""
import os
import sys
import json
import logging
import contextlib
from contextvars import ContextVar
from typing import Optional

import anyio
import uvicorn
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.routing import Mount, Route, request_response
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.authentication import AuthenticationMiddleware

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.routes import (
    create_auth_routes,
    create_protected_resource_routes,
    build_resource_metadata_url,
)
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware

from realm_tools import REALM_TOOLS, execute_tool
import mcp_tokens
import mcp_oauth
from mcp_oauth import GeisterOAuthProvider, GeisterAccessToken, ConsentError, _effective_scopes


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("geister-mcp")

# --- Configuration -----------------------------------------------------------
MCP_PORT = int(os.getenv("GEISTER_MCP_PORT", "5001"))
MCP_HOST = os.getenv("GEISTER_MCP_HOST", "127.0.0.1")
# Realms live in the 'staging' registry on the IC; 'ic' has no registry mapping.
DEFAULT_NETWORK = os.getenv("GEISTER_MCP_NETWORK", "staging")
REALM_FOLDER = os.getenv("REALMS_PROJECT_DIR", "/srv/dev/realms")

# Hard cap on a single tool result. Some tools (realm_status, db_get,
# get_proposals, find_objects) can dump arbitrarily large blobs; an unbounded
# result overwhelms MCP clients (e.g. Claude Desktop spills it to a file and
# chokes trying to chunk-read it). Truncate oversized results to a safe size
# and tell the model how to fetch a narrower slice instead.
MAX_RESULT_CHARS = int(os.getenv("GEISTER_MCP_MAX_RESULT_CHARS", "24000"))

# Public, externally reachable base URL (the OAuth issuer + resource id). Behind
# the Cloudflare tunnel this is https://geister-mcp.realmsgos.dev. For local
# testing set GEISTER_MCP_PUBLIC_URL=http://localhost:5001 (localhost is allowed
# to be plain HTTP by the OAuth issuer-URL validation).
PUBLIC_URL = os.getenv("GEISTER_MCP_PUBLIC_URL", "https://geister-mcp.realmsgos.dev").rstrip("/")
RESOURCE_URL = PUBLIC_URL + "/mcp"
# Browser consent page (registry route) the /authorize step redirects to. The
# page authenticates the user with Internet Identity and posts the approved
# principal back to /oauth/consent.
CONSENT_URL = os.getenv(
    "GEISTER_OAUTH_CONSENT_URL", "https://staging.realmsgos.org/connect/authorize"
)

# Tools that mutate state. A 'read' scoped token may not call these.
WRITE_TOOLS = {
    "registry_redeem_voucher",
    "registry_deploy_realm",
    "join_realm",
    "set_profile_picture",
    "cast_vote",
    "submit_proposal",
    "icw_transfer_tokens",
    "pay_invoice",
}

# Per-request principal/scope, set by the auth middleware and read in handlers.
_CURRENT: ContextVar[Optional[dict]] = ContextVar("mcp_principal", default=None)

# Arguments the server injects from the authenticated token. They are removed
# from the advertised schema (so MCP clients never supply them, and the SDK's
# input validation does not reject calls that omit them) and filled in the
# call handler from the pairing token's principal.
IDENTITY_INJECTED = {"principal_id"}

_SCHEMA_BY_NAME = {
    t["function"]["name"]: t["function"].get(
        "parameters", {"type": "object", "properties": {}}
    )
    for t in REALM_TOOLS
}


def _public_schema(schema: dict) -> dict:
    """Return a copy of the input schema with server-injected fields removed."""
    props = {
        k: v for k, v in schema.get("properties", {}).items()
        if k not in IDENTITY_INJECTED
    }
    required = [r for r in schema.get("required", []) if r not in IDENTITY_INJECTED]
    out = {"type": schema.get("type", "object"), "properties": props}
    if required:
        out["required"] = required
    return out


def _tools_for_scope(scope: str) -> list:
    tools = []
    for entry in REALM_TOOLS:
        fn = entry["function"]
        name = fn["name"]
        if scope == "read" and name in WRITE_TOOLS:
            continue
        description = fn.get("description", "")
        if name in WRITE_TOOLS:
            description += " [Mutating action; runs on behalf of your principal.]"
        tools.append(
            types.Tool(
                name=name,
                description=description,
                inputSchema=_public_schema(
                    _SCHEMA_BY_NAME.get(name, {"type": "object", "properties": {}})
                ),
            )
        )
    return tools


# --- MCP protocol server ------------------------------------------------------
server: Server = Server("geister-realms")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    ctx = _CURRENT.get()
    scope = ctx["scope"] if ctx else "read"
    return _tools_for_scope(scope)


def _cap_result(name: str, result: str) -> str:
    """Clamp an oversized tool result so it never overwhelms the MCP client.

    Returns the result unchanged when it fits under MAX_RESULT_CHARS. Otherwise
    returns a JSON envelope with a truncated preview (kept as a JSON string so
    the payload stays valid JSON) plus guidance to query a narrower slice.
    """
    if not isinstance(result, str) or len(result) <= MAX_RESULT_CHARS:
        return result
    logger.warning("tool %s result truncated: %d > %d chars", name, len(result), MAX_RESULT_CHARS)
    return json.dumps({
        "truncated": True,
        "tool": name,
        "original_length": len(result),
        "returned_length": MAX_RESULT_CHARS,
        "note": (
            "Result was too large to return in full and has been truncated. "
            "Re-run with a narrower query: pass an entity_id to db_get, a "
            "specific proposal/extension, or filters to find_objects, instead "
            "of fetching the whole realm at once."
        ),
        "preview": result[:MAX_RESULT_CHARS],
    })


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
    ctx = _CURRENT.get()
    if ctx is None:
        return [types.TextContent(type="text", text=json.dumps({"error": "unauthenticated"}))]

    principal = ctx["principal"]
    scope = ctx["scope"]

    if name not in _SCHEMA_BY_NAME:
        return [types.TextContent(type="text", text=json.dumps({"error": f"unknown tool '{name}'"}))]
    if scope == "read" and name in WRITE_TOOLS:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "error": f"tool '{name}' requires a full-access token; this token is read-only"
            }),
        )]

    args = dict(arguments or {})
    # Bind principal-keyed arguments to the authenticated user when omitted.
    props = _SCHEMA_BY_NAME[name].get("properties", {})
    if "principal_id" in props and not args.get("principal_id"):
        args["principal_id"] = principal

    # execute_tool itself pops realm_id -> realm_principal; pass through.
    def _run() -> str:
        return execute_tool(
            name,
            args,
            network=DEFAULT_NETWORK,
            realm_folder=REALM_FOLDER,
            realm_principal="",
            user_principal=principal,
        )

    try:
        result = await anyio.to_thread.run_sync(_run)
    except Exception as e:  # never leak a stack trace to the client
        logger.exception("tool %s failed", name)
        result = json.dumps({"error": str(e)})

    result = _cap_result(name, result)
    return [types.TextContent(type="text", text=result)]


# --- OAuth provider + token verification -------------------------------------
oauth_provider = GeisterOAuthProvider(consent_url=CONSENT_URL)


class UnifiedTokenVerifier(TokenVerifier):
    """Accept OAuth (Tier 2) access tokens, falling back to Tier 1 pairing tokens.

    Both resolve to a `GeisterAccessToken` carrying the user's IC principal, so
    the rest of the server is identical regardless of how the user connected.
    """

    def __init__(self, provider: GeisterOAuthProvider):
        self.provider = provider

    async def verify_token(self, token: str) -> Optional[GeisterAccessToken]:
        oauth_tok = await self.provider.load_access_token(token)
        if oauth_tok is not None:
            return oauth_tok
        # Tier 1 fallback: personal pairing token (rgmcp_...).
        info = await anyio.to_thread.run_sync(mcp_tokens.validate_token, token)
        if info:
            return GeisterAccessToken(
                token=token,
                client_id="tier1-pairing-token",
                scopes=_effective_scopes(info["scope"]),
                expires_at=None,
                user_principal=info["principal"],
            )
        return None


token_verifier = UnifiedTokenVerifier(oauth_provider)


# --- Streamable HTTP transport -----------------------------------------------
session_manager = StreamableHTTPSessionManager(
    app=server,
    json_response=True,
    stateless=True,  # each request is self-contained; ideal behind a proxy
)


async def _handle_mcp(scope, receive, send):
    await session_manager.handle_request(scope, receive, send)


class PrincipalContextMiddleware:
    """Bridge the authenticated token -> the `_CURRENT` contextvar the handlers
    read. Runs inside RequireAuthMiddleware, so `scope['user']` is guaranteed
    to be an authenticated user with a `GeisterAccessToken`."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        user = scope.get("user")
        tok = getattr(user, "access_token", None) if user else None
        if tok is None:
            await self.app(scope, receive, send)
            return
        effective = "full" if "full" in (tok.scopes or []) else "read"
        reset = _CURRENT.set(
            {"principal": getattr(tok, "user_principal", ""), "scope": effective}
        )
        try:
            await self.app(scope, receive, send)
        finally:
            _CURRENT.reset(reset)


# --- OAuth consent endpoints (called by the registry consent page) -----------
def _oauth_cors(handler, methods):
    """CORS wrapper for the browser-called consent endpoints.

    The SDK's own cors_middleware only allows the MCP protocol-version header,
    which would block the consent page's JSON POST preflight; allow any header
    here (these endpoints carry no credentials, only an unguessable request_id).
    """
    return CORSMiddleware(
        request_response(handler),
        allow_origins=["*"],
        allow_methods=methods,
        allow_headers=["*"],
    )


async def oauth_request_info(request: Request):
    """Return display details for a pending /authorize request (no secrets)."""
    request_id = request.query_params.get("request_id", "")
    try:
        return JSONResponse(oauth_provider.load_pending_request(request_id))
    except ConsentError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # pragma: no cover
        logger.exception("oauth_request_info failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def oauth_consent(request: Request):
    """Finish the authorization: bind the approved principal, return redirect."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    request_id = (data.get("request_id") or "").strip()
    user_principal = (data.get("user_principal") or "").strip()
    selected_scope = data.get("scope") or "read"
    approve = bool(data.get("approve", False))
    try:
        redirect_to = await anyio.to_thread.run_sync(
            oauth_provider.complete_consent,
            request_id,
            user_principal,
            selected_scope,
            approve,
        )
        return JSONResponse({"redirect_to": redirect_to})
    except ConsentError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:  # pragma: no cover
        logger.exception("oauth_consent failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def healthz(_request):
    return JSONResponse({
        "status": "ok",
        "service": "geister-mcp",
        "network": DEFAULT_NETWORK,
        "tool_count": len(REALM_TOOLS),
        "read_tool_count": len(REALM_TOOLS) - len(WRITE_TOOLS),
        "auth": "oauth2.1+pairing-token",
        "issuer": PUBLIC_URL,
    })


async def root(_request):
    return PlainTextResponse(
        "Geister MCP server. Connect an MCP client to /mcp — it will discover "
        "OAuth via /.well-known/oauth-protected-resource and log you in with "
        "Internet Identity. (Pairing-token bearer auth is also accepted.)"
    )


@contextlib.asynccontextmanager
async def lifespan(_app):
    for name, fn in (("pairing-token", mcp_tokens.ensure_schema),
                     ("oauth", mcp_oauth.ensure_schema)):
        try:
            fn()
        except Exception as e:
            logger.warning("could not ensure %s schema at startup: %s", name, e)
    async with session_manager.run():
        _log(f"[geister-mcp] listening on {MCP_HOST}:{MCP_PORT} "
             f"(network={DEFAULT_NETWORK}, issuer={PUBLIC_URL})")
        yield


# --- Route assembly ----------------------------------------------------------
auth_settings = AuthSettings(
    issuer_url=AnyHttpUrl(PUBLIC_URL),
    resource_server_url=AnyHttpUrl(RESOURCE_URL),
    required_scopes=["read"],
    client_registration_options=ClientRegistrationOptions(
        enabled=True,
        valid_scopes=["read", "full"],
        default_scopes=["read"],
    ),
    revocation_options=RevocationOptions(enabled=True),
)

# OAuth AS endpoints: /.well-known/oauth-authorization-server, /authorize,
# /token, /register, /revoke (each already CORS-wrapped by the SDK).
_routes = create_auth_routes(
    provider=oauth_provider,
    issuer_url=auth_settings.issuer_url,
    client_registration_options=auth_settings.client_registration_options,
    revocation_options=auth_settings.revocation_options,
)
# RS metadata: /.well-known/oauth-protected-resource/mcp
_routes += create_protected_resource_routes(
    resource_url=auth_settings.resource_server_url,
    authorization_servers=[auth_settings.issuer_url],
    scopes_supported=["read", "full"],
)

# Protected MCP endpoint: authenticate -> require scope -> set principal ctx.
_resource_metadata_url = build_resource_metadata_url(auth_settings.resource_server_url)
_mcp_app = AuthenticationMiddleware(
    AuthContextMiddleware(
        RequireAuthMiddleware(
            PrincipalContextMiddleware(_handle_mcp),
            required_scopes=["read"],
            resource_metadata_url=_resource_metadata_url,
        )
    ),
    backend=BearerAuthBackend(token_verifier),
)
_mcp_app = CORSMiddleware(
    _mcp_app,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id", "WWW-Authenticate"],
)

_routes += [
    Route("/", root, methods=["GET"]),
    Route("/healthz", healthz, methods=["GET"]),
    Route(
        "/oauth/request",
        endpoint=_oauth_cors(oauth_request_info, ["GET", "OPTIONS"]),
        methods=["GET", "OPTIONS"],
    ),
    Route(
        "/oauth/consent",
        endpoint=_oauth_cors(oauth_consent, ["POST", "OPTIONS"]),
        methods=["POST", "OPTIONS"],
    ),
    Mount("/mcp", app=_mcp_app),
]

_starlette_app = Starlette(debug=False, routes=_routes, lifespan=lifespan)


class _McpSlashAdapter:
    """Serve the advertised resource id `.../mcp` directly.

    Starlette mounts match `^/mcp/(?P<path>.*)$`, so a request to exactly
    `/mcp` would otherwise 307-redirect to `/mcp/` and force every client
    through an extra hop. Rewriting the path here lets `/mcp` and `/mcp/`
    both hit the StreamableHTTP transport with no redirect.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/mcp":
            scope = dict(scope)
            scope["path"] = "/mcp/"
            if scope.get("raw_path") in (b"/mcp", None):
                scope["raw_path"] = b"/mcp/"
        await self.app(scope, receive, send)


app = _McpSlashAdapter(_starlette_app)


if __name__ == "__main__":
    uvicorn.run(app, host=MCP_HOST, port=MCP_PORT, log_level="info")
