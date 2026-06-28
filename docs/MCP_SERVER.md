# Geister MCP Server

The MCP server exposes Geister's realm tools (the same `REALM_TOOLS` the in-app
assistant uses) to external [Model Context Protocol](https://modelcontextprotocol.io)
clients — most importantly, a user's **own Claude** (claude.ai web, Claude
Desktop, mobile, or Claude Code).

This is the "bring your own model" half of the assistant: the in-platform
assistant talks to Geister via `/api/ask`; Claude talks to the *same* tools via
this MCP server.

```
  ┌────────────────────────────┐        ┌──────────────────────────────────────┐
  │  User's Claude              │        │  realms-vm (DigitalOcean)            │
  │  (claude.ai / Desktop)      │        │                                      │
  │                             │  MCP   │  geister-mcp  (Streamable HTTP :5001) │
  │  Custom Connector / bridge  │◄──────►│   └─ wraps REALM_TOOLS / execute_tool │
  │  Authorization: Bearer …    │ HTTPS  │  geister-api  (Flask :5000)           │
  └────────────────────────────┘        │  PostgreSQL (pairing tokens)          │
                                         │  Cloudflare tunnel (realms-vm)        │
   geister-mcp.realmsgos.dev ───────────►│                                      │
                                         └──────────────────────────────────────┘
```

## Components

| File | Purpose |
|------|---------|
| `mcp_server.py` | Streamable-HTTP MCP server + OAuth AS/RS wiring. Exposes tools, verifies bearer tokens (OAuth **or** pairing token), scopes calls to the token's principal. |
| `mcp_oauth.py` | OAuth 2.1 authorization server (Postgres): Dynamic Client Registration, PKCE auth-code flow, refresh-token rotation, token revocation, consent completion. |
| `mcp_tokens.py` | Tier 1 pairing-token store (Postgres). Mint / validate / list / revoke. CLI included. |
| `vm/mcp.sh` | Launcher (`start`/`stop`/`status`/`logs`/`restart`), mirrors `vm/dev.sh`. |
| `api.py` → `/api/mcp/tokens` | In-app self-service: mint / list / revoke pairing tokens for the II-authenticated user. |
| registry `routes/connect/authorize/+page.svelte` | OAuth consent screen — logs the user in with Internet Identity and approves access. |

- **Transport:** Streamable HTTP at `/mcp` (stateless). Health at `/healthz`.
- **Bind:** `127.0.0.1:5001` (only the local Cloudflare tunnel reaches it).
- **Public URL:** `https://geister-mcp.realmsgos.dev/mcp` (tunnel `realms-vm`).
- **OAuth endpoints:** `/.well-known/oauth-protected-resource/mcp`,
  `/.well-known/oauth-authorization-server`, `/register`, `/authorize`, `/token`,
  `/revoke`, plus the consent bridge `/oauth/request` + `/oauth/consent`.
- **Network:** defaults to `staging` (where the realms registry lives on the IC);
  override with `GEISTER_MCP_NETWORK`.

Two auth tiers are accepted on `/mcp`, transparently — a request is valid if it
carries **either** an OAuth access token (`rgoa_…`) **or** a pairing token
(`rgmcp_…`).

## Authentication (Tier 2 — OAuth 2.1 + Internet Identity, recommended)

Install-free: the user pastes the server URL into Claude as a custom connector,
Claude registers itself and runs the standard OAuth + PKCE flow, the user logs
in with Internet Identity on the registry and approves a scope. No Node.js, no
`mcp-remote`, no copy-pasted secret.

```
 Claude ──discover──► /.well-known/oauth-protected-resource  (RFC 9728)
        ──register──► /register                              (RFC 7591 DCR)
        ──authorize─► /authorize ──302──► registry /connect/authorize?request_id=…
                                              │  (Internet Identity login + consent)
                                              ▼
                          POST /oauth/consent {principal, scope, approve}
        ◄──redirect── claude.ai/api/mcp/auth_callback?code=…&state=…
        ──exchange──► /token  (code + PKCE verifier) ──► access_token (rgoa_…) + refresh_token
        ──call──────► /mcp    Authorization: Bearer rgoa_…
```

Properties:

- **PKCE (S256) required**; auth codes are single-use and short-lived (5 min).
- **Access tokens** expire (1 h) and are refreshable; **refresh tokens rotate**
  on use (the old one is invalidated). Only SHA-256 hashes are stored.
- **Scope** is chosen by the user on the consent screen (`read` or `full`),
  identical to the pairing-token scopes. A `full` grant also carries `read`.
- The principal is asserted by the II-authenticated registry consent page —
  the *same* trust model as the in-app assistant and the Tier 1 token endpoints
  (the platform trusts the principal supplied by the II-authenticated frontend).

Config (set by `vm/mcp.sh`, override via env):

| Env | Default | Meaning |
|-----|---------|---------|
| `GEISTER_MCP_PUBLIC_URL` | `https://geister-mcp.realmsgos.dev` | OAuth issuer + resource id (the public tunnel host). |
| `GEISTER_OAUTH_CONSENT_URL` | `https://staging.realmsgos.org/connect/authorize` | Registry consent page `/authorize` redirects to. |

End-to-end regression test (spins up a throwaway server, drives the whole flow):

```bash
DB_HOST=localhost vm/venv/bin/python3 tests/test_oauth_flow.py
```

## Authentication (Tier 1 — personal pairing tokens, advanced)

Each request sends `Authorization: Bearer rgmcp_…`. A token is bound to one IC
principal and a scope:

- `read` (default) — read-only tools only (`list_realms`, `realm_status`,
  balances, proposals, …). Mutating tools are hidden.
- `full` — also exposes mutating tools (`cast_vote`, `submit_proposal`,
  `registry_deploy_realm`, `icw_transfer_tokens`, …), which run on behalf of the
  bound principal.

Only a SHA-256 hash of the token is stored; the plaintext is shown once. Tokens
can carry an expiry (`ttl_days`) and be revoked. Because hosted Claude surfaces
can't set a custom bearer header, Tier 1 needs the Node-based `mcp-remote`
bridge — prefer Tier 2 unless you specifically need a long-lived token.

> **Identity note.** Tools are scoped by `user_principal`, the *same* stable
> principal the platform sees (thanks to the Internet Identity
> `derivationOrigin` setup). On-chain *writes* that must be signed as the user
> (e.g. voting) are constrained by Geister's calling identity — full delegated
> signing from Claude is future work (it needs an II session delegation, not
> just an OAuth identity binding).

### Mint a token

In-app (self-service, from the II-authenticated frontend):

```bash
curl -X POST https://geister-api.realmsgos.dev/api/mcp/tokens \
  -H 'Content-Type: application/json' \
  -d '{"user_principal":"<principal>","label":"My Claude","scope":"read"}'
# → { "success": true, "token": "rgmcp_…", "metadata": {…} }
```

Or via CLI on the VM:

```bash
vm/venv/bin/python3 mcp_tokens.py mint --principal <principal> --label "My Claude" --scope read
vm/venv/bin/python3 mcp_tokens.py list   --principal <principal>
vm/venv/bin/python3 mcp_tokens.py revoke --principal <principal> --id <id>
```

## Connecting Claude

### Custom connector / OAuth (recommended — claude.ai web, Desktop, mobile)

1. In Claude: **Settings → Connectors → Add custom connector**.
2. Paste the server URL: `https://geister-mcp.realmsgos.dev/mcp`.
3. Claude discovers OAuth, registers itself, and opens a browser.
4. Sign in with **Internet Identity** on the registry consent page and pick
   `read` or `full`.
5. Done — ask *"List my realms"* or *"How many credits do I have?"*.

No Node.js, no bridge, no token to copy. Revoke any time from the registry
dashboard → **Connect Claude**, or with `/revoke`.

### Claude Desktop via the `mcp-remote` bridge (Tier 1 fallback)

If you'd rather use a long-lived pairing token, the bridge injects the bearer
header. Edit `claude_desktop_config.json` (Windows launches `npx` via `cmd /c`
because it's a `.cmd` shim):

```json
{
  "mcpServers": {
    "realms": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote",
        "https://geister-mcp.realmsgos.dev/mcp",
        "--header", "Authorization: Bearer rgmcp_YOUR_TOKEN"
      ]
    }
  }
}
```

Restart Claude Desktop, then ask: *"List my realms"*.

## Operations

```bash
./vm/mcp.sh start|stop|restart|status|logs
curl -s https://geister-mcp.realmsgos.dev/healthz
```

Cloudflare exposure lives in `/etc/cloudflared/config.yml` (ingress
`geister-mcp.realmsgos.dev → http://localhost:5001`) with a CNAME created via
`cloudflared tunnel route dns realms-vm geister-mcp.realmsgos.dev`.

> The repo's `cloudflared/config.yml` is the **realms-runpod** tunnel (Ollama).
> The live VM tunnel config is `/etc/cloudflared/config.yml` (`realms-vm`).
