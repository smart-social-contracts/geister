#!/usr/bin/env python3
"""
Personal pairing tokens for the Geister MCP server (Tier 1 auth).

A pairing token binds a long-lived bearer credential to a single IC principal.
The user's Claude (or any MCP client) presents the token as
`Authorization: Bearer <token>` and the MCP server resolves it to that
principal, scoping every tool call to the user.

Security model (Tier 1):
  - Only a SHA-256 hash of the token is stored; the plaintext is shown once.
  - Tokens carry a scope ('read' or 'full') so a user can hand an external
    LLM a read-only credential.
  - Tokens may carry an expiry and can be revoked.

This intentionally reuses Geister's existing "trust the principal supplied by
the II-authenticated frontend" model. For a fully verified, multi-tenant
public deployment, upgrade to the OAuth/Internet-Identity flow (Tier 2).
"""
import os
import sys
import json
import hashlib
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("geister-mcp.tokens")

TOKEN_PREFIX = "rgmcp_"
VALID_SCOPES = ("read", "full")


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


def ensure_schema() -> None:
    """Create the pairing-token table if it does not already exist."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_pairing_tokens (
                    id             SERIAL PRIMARY KEY,
                    token_hash     TEXT NOT NULL UNIQUE,
                    user_principal TEXT NOT NULL,
                    label          TEXT DEFAULT '',
                    scope          TEXT NOT NULL DEFAULT 'read',
                    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_used_at   TIMESTAMPTZ,
                    expires_at     TIMESTAMPTZ,
                    revoked        BOOLEAN NOT NULL DEFAULT FALSE
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_mcp_tokens_principal "
                "ON mcp_pairing_tokens (user_principal)"
            )
            conn.commit()
    finally:
        conn.close()


def mint_token(
    user_principal: str,
    label: str = "",
    scope: str = "read",
    ttl_days: Optional[int] = None,
) -> dict:
    """Mint a new pairing token. Returns the PLAINTEXT token exactly once."""
    if not user_principal:
        raise ValueError("user_principal is required")
    if scope not in VALID_SCOPES:
        raise ValueError(f"scope must be one of {VALID_SCOPES}")

    ensure_schema()
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token_hash = _hash(raw)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=ttl_days)
        if ttl_days
        else None
    )

    conn = _connect()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO mcp_pairing_tokens
                    (token_hash, user_principal, label, scope, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, user_principal, label, scope, created_at, expires_at
                """,
                (token_hash, user_principal, label, scope, expires_at),
            )
            row = dict(cur.fetchone())
            conn.commit()
    finally:
        conn.close()

    row["token"] = raw  # plaintext, shown once
    return row


def validate_token(token: str) -> Optional[dict]:
    """Resolve a bearer token to its principal/scope, or None if invalid.

    Touches last_used_at on success. Rejects revoked or expired tokens.
    """
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    token_hash = _hash(token)
    try:
        conn = _connect()
    except Exception as e:  # DB unreachable
        logger.error("token validation: DB connection failed: %s", e)
        return None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, user_principal, scope, expires_at, revoked
                FROM mcp_pairing_tokens
                WHERE token_hash = %s
                """,
                (token_hash,),
            )
            row = cur.fetchone()
            if not row:
                return None
            if row["revoked"]:
                return None
            if row["expires_at"] is not None and row["expires_at"] < datetime.now(timezone.utc):
                return None
            cur.execute(
                "UPDATE mcp_pairing_tokens SET last_used_at = NOW() WHERE id = %s",
                (row["id"],),
            )
            conn.commit()
            return {
                "token_id": row["id"],
                "principal": row["user_principal"],
                "scope": row["scope"],
            }
    except Exception as e:
        logger.error("token validation failed: %s", e)
        return None
    finally:
        conn.close()


def list_tokens(user_principal: str) -> list:
    """List a principal's tokens (metadata only, never the plaintext/hash)."""
    ensure_schema()
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, label, scope, created_at, last_used_at, expires_at, revoked
                FROM mcp_pairing_tokens
                WHERE user_principal = %s
                ORDER BY created_at DESC
                """,
                (user_principal,),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def revoke_token(user_principal: str, token_id: int) -> bool:
    """Revoke a token by id, scoped to its owner. Returns True if a row changed."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE mcp_pairing_tokens SET revoked = TRUE
                WHERE id = %s AND user_principal = %s AND revoked = FALSE
                """,
                (token_id, user_principal),
            )
            changed = cur.rowcount > 0
            conn.commit()
            return changed
    finally:
        conn.close()


def _json_default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)


def _cli(argv: list) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Geister MCP pairing tokens")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_mint = sub.add_parser("mint", help="Mint a new pairing token")
    p_mint.add_argument("--principal", required=True, help="IC principal to bind")
    p_mint.add_argument("--label", default="", help="Human label (e.g. 'My Claude')")
    p_mint.add_argument("--scope", default="read", choices=VALID_SCOPES)
    p_mint.add_argument("--ttl-days", type=int, default=None, help="Optional expiry in days")

    p_list = sub.add_parser("list", help="List tokens for a principal")
    p_list.add_argument("--principal", required=True)

    p_revoke = sub.add_parser("revoke", help="Revoke a token")
    p_revoke.add_argument("--principal", required=True)
    p_revoke.add_argument("--id", type=int, required=True)

    sub.add_parser("init", help="Create the table if missing")

    args = parser.parse_args(argv)

    if args.cmd == "init":
        ensure_schema()
        print("ok: schema ensured")
        return 0
    if args.cmd == "mint":
        row = mint_token(args.principal, args.label, args.scope, args.ttl_days)
        print(json.dumps(row, indent=2, default=_json_default))
        print("\n*** Copy the token now — it will not be shown again. ***", file=sys.stderr)
        return 0
    if args.cmd == "list":
        print(json.dumps(list_tokens(args.principal), indent=2, default=_json_default))
        return 0
    if args.cmd == "revoke":
        ok = revoke_token(args.principal, args.id)
        print(json.dumps({"revoked": ok, "id": args.id}))
        return 0
    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(_cli(sys.argv[1:]))
