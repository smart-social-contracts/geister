#!/usr/bin/env python3
"""
End-to-end test of the Geister MCP OAuth 2.1 flow (no browser required).

Spins up a throwaway `mcp_server.py` on a local port and drives the full
authorization-code + PKCE flow the way Claude would, except the Internet
Identity consent step (which needs a real human) is simulated by POSTing an
approved principal straight to /oauth/consent — exactly what the registry
consent page does after II login.

Run:
    cd /srv/dev/geister
    DB_HOST=localhost vm/venv/bin/python3 tests/test_oauth_flow.py
"""
import os
import sys
import time
import base64
import hashlib
import secrets
import subprocess
from urllib.parse import urlparse, parse_qs

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PORT = int(os.getenv("TEST_MCP_PORT", "5009"))
BASE = f"http://localhost:{PORT}"
CLAUDE_CB = "https://claude.ai/api/mcp/auth_callback"
TEST_PRINCIPAL = "aaaaa-bbbbb-ccccc-ddddd-test"

PASS = "\033[0;32mPASS\033[0m"
FAIL = "\033[0;31mFAIL\033[0m"
_failures = []


def check(name, cond, detail=""):
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)
    return cond


def pkce():
    verifier = secrets.token_urlsafe(64)[:64]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


def main():
    env = dict(os.environ)
    env.setdefault("DB_HOST", "localhost")
    env.update({
        "GEISTER_MCP_PORT": str(PORT),
        "GEISTER_MCP_HOST": "127.0.0.1",
        "GEISTER_MCP_PUBLIC_URL": BASE,
        "GEISTER_OAUTH_CONSENT_URL": "https://example.test/connect/authorize",
    })
    proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.Popen(
        [os.path.join(proj, "vm/venv/bin/python3"), os.path.join(proj, "mcp_server.py")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=proj,
    )
    try:
        # Wait for healthz.
        for _ in range(50):
            try:
                if httpx.get(f"{BASE}/healthz", timeout=1).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            print("server did not start; output:")
            print(proc.stdout.read().decode(errors="replace") if proc.stdout else "")
            return 1

        c = httpx.Client(timeout=10, follow_redirects=False)

        print("\n1. Discovery (RFC 9728 + RFC 8414)")
        prm = c.get(f"{BASE}/.well-known/oauth-protected-resource/mcp").json()
        check("protected-resource advertises this AS",
              BASE in [str(a).rstrip("/") for a in prm.get("authorization_servers", [])],
              str(prm))
        asm = c.get(f"{BASE}/.well-known/oauth-authorization-server").json()
        for ep in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
            check(f"AS metadata has {ep}", ep in asm and asm[ep], str(asm.get(ep)))
        check("PKCE S256 advertised", "S256" in (asm.get("code_challenge_methods_supported") or []))

        print("\n2. Dynamic client registration (RFC 7591)")
        reg = c.post(f"{BASE}/register", json={
            "redirect_uris": [CLAUDE_CB],
            "client_name": "Claude (test)",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
            "scope": "read full",
        })
        check("register returns 201", reg.status_code == 201, f"{reg.status_code}: {reg.text}")
        client = reg.json()
        client_id = client.get("client_id")
        client_secret = client.get("client_secret")
        check("client_id issued", bool(client_id))

        print("\n3. Authorize -> consent redirect")
        verifier, challenge = pkce()
        state = secrets.token_urlsafe(16)
        authz = c.get(f"{BASE}/authorize", params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CLAUDE_CB,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "scope": "read full",
        })
        check("authorize returns 302", authz.status_code == 302, f"{authz.status_code}: {authz.text[:200]}")
        loc = authz.headers.get("location", "")
        req_q = parse_qs(urlparse(loc).query)
        request_id = req_q.get("request_id", [None])[0]
        check("redirect carries request_id to consent page", bool(request_id), loc)

        print("\n4. Consent page fetches request info")
        info = c.get(f"{BASE}/oauth/request", params={"request_id": request_id}).json()
        check("request info shows client_name", info.get("client_name") == "Claude (test)", str(info))
        check("request info lists valid scopes", set(info.get("valid_scopes", [])) == {"read", "full"})

        print("\n5. User approves with Internet Identity (simulated principal) — scope=read")
        consent = c.post(f"{BASE}/oauth/consent", json={
            "request_id": request_id,
            "user_principal": TEST_PRINCIPAL,
            "scope": "read",
            "approve": True,
        }).json()
        redirect_to = consent.get("redirect_to", "")
        cb_q = parse_qs(urlparse(redirect_to).query)
        code = cb_q.get("code", [None])[0]
        check("consent returns redirect to Claude callback", redirect_to.startswith(CLAUDE_CB), redirect_to)
        check("state echoed back unchanged", cb_q.get("state", [None])[0] == state)
        check("authorization code issued", bool(code))

        check("request id is single-use",
              c.post(f"{BASE}/oauth/consent", json={"request_id": request_id,
                     "user_principal": TEST_PRINCIPAL, "scope": "read", "approve": True}).status_code == 400)

        print("\n6. Token exchange (authorization_code + PKCE)")
        tok = c.post(f"{BASE}/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": CLAUDE_CB,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": verifier,
        })
        check("token endpoint returns 200", tok.status_code == 200, f"{tok.status_code}: {tok.text}")
        tj = tok.json()
        access = tj.get("access_token")
        refresh = tj.get("refresh_token")
        check("access_token issued (rgoa_)", bool(access) and access.startswith("rgoa_"))
        check("refresh_token issued", bool(refresh))

        check("PKCE is enforced (wrong verifier rejected)",
              c.post(f"{BASE}/token", data={
                  "grant_type": "authorization_code", "code": code, "redirect_uri": CLAUDE_CB,
                  "client_id": client_id, "client_secret": client_secret,
                  "code_verifier": "wrong"}).status_code == 400)

        print("\n7. Authenticated MCP calls")
        h = {"Authorization": f"Bearer {access}",
             "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream"}
        check("missing token -> 401",
              c.post(f"{BASE}/mcp", headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"},
                     json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401)

        init = c.post(f"{BASE}/mcp", headers=h, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18",
                       "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
        })
        check("initialize succeeds with access token", init.status_code == 200, f"{init.status_code}: {init.text[:200]}")

        listed = c.post(f"{BASE}/mcp", headers=h, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = [t["name"] for t in listed.json().get("result", {}).get("tools", [])]
        check("tools/list returns tools", len(names) > 0, str(listed.text[:200]))
        check("read scope EXCLUDES write tools (e.g. cast_vote)", "cast_vote" not in names, str(names))

        print("\n8. Scope gating for full-access tokens")
        # New flow granting full scope.
        v2, ch2 = pkce()
        a2 = c.get(f"{BASE}/authorize", params={
            "response_type": "code", "client_id": client_id, "redirect_uri": CLAUDE_CB,
            "code_challenge": ch2, "code_challenge_method": "S256", "state": "s2", "scope": "read full"})
        rid2 = parse_qs(urlparse(a2.headers["location"]).query)["request_id"][0]
        cons2 = c.post(f"{BASE}/oauth/consent", json={
            "request_id": rid2, "user_principal": TEST_PRINCIPAL, "scope": "full", "approve": True}).json()
        code2 = parse_qs(urlparse(cons2["redirect_to"]).query)["code"][0]
        tok2 = c.post(f"{BASE}/token", data={
            "grant_type": "authorization_code", "code": code2, "redirect_uri": CLAUDE_CB,
            "client_id": client_id, "client_secret": client_secret, "code_verifier": v2}).json()
        full_access = tok2["access_token"]
        h2 = dict(h); h2["Authorization"] = f"Bearer {full_access}"
        c.post(f"{BASE}/mcp", headers=h2, json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "t", "version": "0"}}})
        l2 = c.post(f"{BASE}/mcp", headers=h2, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names2 = [t["name"] for t in l2.json().get("result", {}).get("tools", [])]
        check("full scope INCLUDES write tools (e.g. cast_vote)", "cast_vote" in names2, str(names2))

        print("\n9. Refresh token rotation")
        rt = c.post(f"{BASE}/token", data={
            "grant_type": "refresh_token", "refresh_token": refresh,
            "client_id": client_id, "client_secret": client_secret})
        check("refresh returns 200", rt.status_code == 200, f"{rt.status_code}: {rt.text}")
        new_access = rt.json().get("access_token")
        check("refresh yields a new access token", bool(new_access) and new_access != access)
        check("old refresh token is single-use (rotated)",
              c.post(f"{BASE}/token", data={"grant_type": "refresh_token", "refresh_token": refresh,
                     "client_id": client_id, "client_secret": client_secret}).status_code == 400)

        print("\n10. Tier 1 pairing token still works on /mcp")
        import mcp_tokens
        row = mcp_tokens.mint_token(TEST_PRINCIPAL, label="test", scope="read")
        h3 = dict(h); h3["Authorization"] = f"Bearer {row['token']}"
        i3 = c.post(f"{BASE}/mcp", headers=h3, json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "t", "version": "0"}}})
        check("pairing-token initialize succeeds", i3.status_code == 200, f"{i3.status_code}: {i3.text[:160]}")

        print()
        if _failures:
            print(f"\033[0;31m{len(_failures)} check(s) FAILED:\033[0m " + ", ".join(_failures))
            return 1
        print("\033[0;32mALL CHECKS PASSED\033[0m")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
