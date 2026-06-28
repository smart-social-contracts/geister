#!/usr/bin/env python3
"""
Tier 2 OAuth 2.1 authorization server for the Geister MCP server.

This makes `geister-mcp` a self-contained OAuth Authorization Server *and*
Resource Server, so an MCP client such as Claude can connect install-free:
the user pastes the server URL, Claude performs Dynamic Client Registration
(RFC 7591) + the PKCE authorization-code flow, the user logs in with Internet
Identity on the registry, and Claude receives a bearer access token. No Node,
no `mcp-remote`, no copy-pasted secret.

Where the principal comes from
------------------------------
The `/authorize` step parks a pending request and redirects the browser to the
registry consent page (`GEISTER_OAUTH_CONSENT_URL`). That page authenticates
the user with Internet Identity (same `derivationOrigin` as the whole platform,
so the principal matches their realms/credits) and POSTs the approved principal
back via `complete_consent()`. This intentionally reuses Geister's existing
"trust the principal asserted by the II-authenticated frontend" model — the
same trust posture as the in-app assistant and the Tier 1 token endpoints.

Storage: PostgreSQL (same DB as `mcp_tokens`). Only hashes of access/refresh
tokens are stored.
"""
import os
import json
import time
import hashlib
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger("geister-mcp.oauth")

# --- Tunables ----------------------------------------------------------------
VALID_SCOPES = ["read", "full"]
DEFAULT_SCOPES = ["read"]

REQUEST_TTL_SECONDS = int(os.getenv("GEISTER_OAUTH_REQUEST_TTL", str(15 * 60)))
CODE_TTL_SECONDS = int(os.getenv("GEISTER_OAUTH_CODE_TTL", str(5 * 60)))
ACCESS_TTL_SECONDS = int(os.getenv("GEISTER_OAUTH_ACCESS_TTL", str(60 * 60)))
REFRESH_TTL_SECONDS = int(os.getenv("GEISTER_OAUTH_REFRESH_TTL", str(30 * 24 * 60 * 60)))

ACCESS_PREFIX = "rgoa_"
REFRESH_PREFIX = "rgor_"


def _connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "geister_db"),
        user=os.getenv("DB_USER", "geister_user"),
        password=os.getenv("DB_PASS", "geister_pass"),
        port=os.getenv("DB_PORT", "5432"),
    )


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _effective_scopes(selected: str) -> list:
    """A 'full' grant implies 'read' so it satisfies read-scoped requirements."""
    return ["read", "full"] if selected == "full" else ["read"]


class GeisterAccessToken(AccessToken):
    """AccessToken carrying the IC principal the token authenticates as.

    FastMCP/the SDK never serialise this back to the client, so the extra
    field is safe to carry through the auth context to the tool handlers.
    """

    user_principal: str = ""


def ensure_schema() -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_oauth_clients (
                    client_id        TEXT PRIMARY KEY,
                    client_secret    TEXT,
                    metadata         JSONB NOT NULL,
                    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_oauth_requests (
                    request_id            TEXT PRIMARY KEY,
                    client_id             TEXT NOT NULL,
                    redirect_uri          TEXT NOT NULL,
                    redirect_uri_explicit BOOLEAN NOT NULL DEFAULT TRUE,
                    code_challenge        TEXT NOT NULL,
                    scopes                TEXT NOT NULL DEFAULT '',
                    state                 TEXT,
                    resource              TEXT,
                    client_name           TEXT,
                    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at            TIMESTAMPTZ NOT NULL,
                    consumed              BOOLEAN NOT NULL DEFAULT FALSE
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_oauth_authcodes (
                    code                  TEXT PRIMARY KEY,
                    client_id             TEXT NOT NULL,
                    user_principal        TEXT NOT NULL,
                    redirect_uri          TEXT NOT NULL,
                    redirect_uri_explicit BOOLEAN NOT NULL DEFAULT TRUE,
                    code_challenge        TEXT NOT NULL,
                    scopes                TEXT NOT NULL DEFAULT '',
                    resource              TEXT,
                    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at            TIMESTAMPTZ NOT NULL,
                    used                  BOOLEAN NOT NULL DEFAULT FALSE
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_oauth_tokens (
                    id                 SERIAL PRIMARY KEY,
                    access_hash        TEXT UNIQUE,
                    refresh_hash       TEXT UNIQUE,
                    client_id          TEXT NOT NULL,
                    user_principal     TEXT NOT NULL,
                    scopes             TEXT NOT NULL DEFAULT '',
                    resource           TEXT,
                    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    access_expires_at  TIMESTAMPTZ,
                    refresh_expires_at TIMESTAMPTZ,
                    revoked            BOOLEAN NOT NULL DEFAULT FALSE
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_oauth_tokens_principal "
                "ON mcp_oauth_tokens (user_principal)"
            )
            conn.commit()
    finally:
        conn.close()


class ConsentError(Exception):
    """Raised by complete_consent / load_pending_request for bad/expired ids."""


class GeisterOAuthProvider:
    """OAuthAuthorizationServerProvider backed by PostgreSQL.

    Implements the SDK provider protocol. The PKCE check, redirect_uri match,
    client authentication and code expiry are enforced by the SDK handlers;
    this class persists state and binds issued tokens to an IC principal.
    """

    def __init__(self, consent_url: str):
        self.consent_url = consent_url.rstrip("/") if consent_url else ""

    # -- Dynamic client registration -----------------------------------------
    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        conn = _connect()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT metadata FROM mcp_oauth_clients WHERE client_id = %s",
                    (client_id,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        try:
            return OAuthClientInformationFull.model_validate(row["metadata"])
        except Exception as e:  # pragma: no cover - corrupt row
            logger.error("could not parse client %s: %s", client_id, e)
            return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        metadata = client_info.model_dump(mode="json")
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mcp_oauth_clients (client_id, client_secret, metadata)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (client_id) DO UPDATE
                        SET client_secret = EXCLUDED.client_secret,
                            metadata = EXCLUDED.metadata
                    """,
                    (client_info.client_id, client_info.client_secret, json.dumps(metadata)),
                )
                conn.commit()
        finally:
            conn.close()

    # -- Authorization (start) ------------------------------------------------
    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Park the request and redirect the browser to the consent page."""
        if not self.consent_url:
            raise AuthorizeError(
                error="server_error",
                error_description="consent endpoint not configured",
            )
        request_id = secrets.token_urlsafe(32)
        scopes = " ".join(params.scopes or DEFAULT_SCOPES)
        expires_at = _now() + timedelta(seconds=REQUEST_TTL_SECONDS)
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mcp_oauth_requests
                        (request_id, client_id, redirect_uri, redirect_uri_explicit,
                         code_challenge, scopes, state, resource, client_name, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        request_id,
                        client.client_id,
                        str(params.redirect_uri),
                        params.redirect_uri_provided_explicitly,
                        params.code_challenge,
                        scopes,
                        params.state,
                        params.resource,
                        client.client_name or "",
                        expires_at,
                    ),
                )
                conn.commit()
        finally:
            conn.close()
        return f"{self.consent_url}?request_id={request_id}"

    # -- Consent (completed by the registry page) -----------------------------
    def load_pending_request(self, request_id: str) -> dict:
        """Return display info for a live pending request (raises if invalid)."""
        conn = _connect()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM mcp_oauth_requests WHERE request_id = %s",
                    (request_id,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            raise ConsentError("unknown or expired authorization request")
        if row["consumed"]:
            raise ConsentError("authorization request already used")
        if row["expires_at"] < _now():
            raise ConsentError("authorization request expired")
        return {
            "request_id": row["request_id"],
            "client_name": row["client_name"] or "An MCP client",
            "requested_scopes": (row["scopes"] or "").split(),
            "valid_scopes": VALID_SCOPES,
        }

    def complete_consent(
        self, request_id: str, user_principal: str, selected_scope: str, approve: bool
    ) -> str:
        """Consume a pending request and return the URL to send the browser to.

        On approval, mints a one-time authorization code bound to the principal
        and returns the client's redirect_uri with `code`+`state`. On denial,
        returns the redirect_uri with an `access_denied` error.
        """
        if approve:
            if not user_principal:
                raise ConsentError("user_principal is required to approve")
            if selected_scope not in VALID_SCOPES:
                raise ConsentError(f"scope must be one of {VALID_SCOPES}")

        conn = _connect()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Atomically consume the request.
                cur.execute(
                    """
                    UPDATE mcp_oauth_requests SET consumed = TRUE
                    WHERE request_id = %s AND consumed = FALSE AND expires_at > NOW()
                    RETURNING client_id, redirect_uri, redirect_uri_explicit,
                              code_challenge, scopes, state, resource
                    """,
                    (request_id,),
                )
                req = cur.fetchone()
                if not req:
                    raise ConsentError("unknown, expired or already-used request")

                redirect_uri = req["redirect_uri"]
                state = req["state"]

                if not approve:
                    conn.commit()
                    return _build_redirect(
                        redirect_uri, error="access_denied",
                        error_description="user denied the request", state=state,
                    )

                granted = " ".join(_effective_scopes(selected_scope))
                code = secrets.token_urlsafe(32)
                expires_at = _now() + timedelta(seconds=CODE_TTL_SECONDS)
                cur.execute(
                    """
                    INSERT INTO mcp_oauth_authcodes
                        (code, client_id, user_principal, redirect_uri,
                         redirect_uri_explicit, code_challenge, scopes, resource, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        code,
                        req["client_id"],
                        user_principal,
                        redirect_uri,
                        req["redirect_uri_explicit"],
                        req["code_challenge"],
                        granted,
                        req["resource"],
                        expires_at,
                    ),
                )
                conn.commit()
                return _build_redirect(redirect_uri, code=code, state=state)
        finally:
            conn.close()

    # -- Authorization code -> tokens -----------------------------------------
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[AuthorizationCode]:
        conn = _connect()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM mcp_oauth_authcodes WHERE code = %s",
                    (authorization_code,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row or row["used"]:
            return None
        # Stash the principal on the model so exchange_authorization_code can
        # read it without a second query (subclass field is ignored by the SDK).
        code = _AuthCodeWithPrincipal(
            code=row["code"],
            scopes=(row["scopes"] or "").split(),
            expires_at=row["expires_at"].timestamp(),
            client_id=row["client_id"],
            code_challenge=row["code_challenge"],
            redirect_uri=row["redirect_uri"],
            redirect_uri_provided_explicitly=row["redirect_uri_explicit"],
            resource=row["resource"],
            user_principal=row["user_principal"],
        )
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        user_principal = getattr(authorization_code, "user_principal", "")
        conn = _connect()
        try:
            with conn.cursor() as cur:
                # Single-use: mark consumed, refuse if already used.
                cur.execute(
                    "UPDATE mcp_oauth_authcodes SET used = TRUE "
                    "WHERE code = %s AND used = FALSE RETURNING code",
                    (authorization_code.code,),
                )
                if cur.fetchone() is None:
                    conn.commit()
                    from mcp.server.auth.provider import TokenError
                    raise TokenError("invalid_grant", "authorization code already used")
                conn.commit()
        finally:
            conn.close()
        return self._issue_tokens(
            client_id=authorization_code.client_id,
            user_principal=user_principal,
            scopes=authorization_code.scopes,
            resource=authorization_code.resource,
        )

    # -- Refresh --------------------------------------------------------------
    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[RefreshToken]:
        conn = _connect()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT client_id, scopes, refresh_expires_at, revoked "
                    "FROM mcp_oauth_tokens WHERE refresh_hash = %s",
                    (_hash(refresh_token),),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row or row["revoked"]:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=row["client_id"],
            scopes=(row["scopes"] or "").split(),
            expires_at=int(row["refresh_expires_at"].timestamp()) if row["refresh_expires_at"] else None,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list,
    ) -> OAuthToken:
        # Rotate: revoke the old row, issue a fresh access+refresh pair.
        conn = _connect()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT user_principal, scopes, resource FROM mcp_oauth_tokens "
                    "WHERE refresh_hash = %s AND revoked = FALSE",
                    (_hash(refresh_token.token),),
                )
                row = cur.fetchone()
                if not row:
                    from mcp.server.auth.provider import TokenError
                    raise TokenError("invalid_grant", "refresh token not found")
                cur.execute(
                    "UPDATE mcp_oauth_tokens SET revoked = TRUE WHERE refresh_hash = %s",
                    (_hash(refresh_token.token),),
                )
                conn.commit()
                user_principal = row["user_principal"]
                resource = row["resource"]
        finally:
            conn.close()
        granted = scopes or (refresh_token.scopes or DEFAULT_SCOPES)
        return self._issue_tokens(
            client_id=refresh_token.client_id,
            user_principal=user_principal,
            scopes=list(granted),
            resource=resource,
        )

    # -- Access token verification / revocation -------------------------------
    async def load_access_token(self, token: str) -> Optional[GeisterAccessToken]:
        if not token or not token.startswith(ACCESS_PREFIX):
            return None
        conn = _connect()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT client_id, user_principal, scopes, resource, "
                    "access_expires_at, revoked FROM mcp_oauth_tokens "
                    "WHERE access_hash = %s",
                    (_hash(token),),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row or row["revoked"]:
            return None
        expires_at = int(row["access_expires_at"].timestamp()) if row["access_expires_at"] else None
        if expires_at and expires_at < int(time.time()):
            return None
        return GeisterAccessToken(
            token=token,
            client_id=row["client_id"],
            scopes=(row["scopes"] or "").split(),
            expires_at=expires_at,
            resource=row["resource"],
            user_principal=row["user_principal"],
        )

    async def revoke_token(self, token) -> None:
        h = _hash(token.token)
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE mcp_oauth_tokens SET revoked = TRUE "
                    "WHERE access_hash = %s OR refresh_hash = %s",
                    (h, h),
                )
                conn.commit()
        finally:
            conn.close()

    # -- helpers --------------------------------------------------------------
    def _issue_tokens(
        self, client_id: str, user_principal: str, scopes: list, resource: Optional[str]
    ) -> OAuthToken:
        access = ACCESS_PREFIX + secrets.token_urlsafe(32)
        refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
        scope_str = " ".join(scopes)
        access_exp = _now() + timedelta(seconds=ACCESS_TTL_SECONDS)
        refresh_exp = _now() + timedelta(seconds=REFRESH_TTL_SECONDS)
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mcp_oauth_tokens
                        (access_hash, refresh_hash, client_id, user_principal,
                         scopes, resource, access_expires_at, refresh_expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        _hash(access),
                        _hash(refresh),
                        client_id,
                        user_principal,
                        scope_str,
                        resource,
                        access_exp,
                        refresh_exp,
                    ),
                )
                conn.commit()
        finally:
            conn.close()
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TTL_SECONDS,
            scope=scope_str,
            refresh_token=refresh,
        )


class _AuthCodeWithPrincipal(AuthorizationCode):
    user_principal: str = ""


def _build_redirect(redirect_uri: str, **params) -> str:
    from mcp.server.auth.provider import construct_redirect_uri
    return construct_redirect_uri(redirect_uri, **{k: v for k, v in params.items() if v is not None})
