#!/usr/bin/env python3
"""
e2e_driver.py — Deterministic, LLM-free driver for the Realms E2E test.

geister issue #19.

All actions are direct signed canister calls via realm_tools.execute_tool.
No LLM in the loop.  Designed to be run repeatedly (idempotent).

Usage
-----
    from e2e_driver import E2EDriver, ensure_members

    driver = E2EDriver(
        realm_principal="h5vpp-qyaaa-aaaac-qai3a-cai",
        realm_folder="/srv/dev/realms",
        network="staging",
    )
    members = ensure_members(20)
    r = driver.join_realm(members[0])
    assert r["ok"], r["error"]
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

import realm_tools
from icp_identity import icp_create, icp_principal, _run as _icp_run

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Member = Dict[str, str]  # {"agent_id": "swarm_agent_001", "principal": "..."}
Result = Dict[str, Any]  # {"ok": bool, "raw": str, "parsed": dict|None, "error": str|None}

# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------

_AGENT_PREFIX = "swarm_agent_"


def ensure_members(
    n: int,
    persona: str = "compliant",
    start_index: int = 1,
) -> List[Member]:
    """Idempotently ensure N swarm members exist in the icp/dfx identity store.

    Returns a list of dicts::

        [{"agent_id": "swarm_agent_001", "principal": "<principal>"}, ...]

    Never deletes existing members.  New identities are created via icp-cli and
    mirrored to dfx (as per Phase 1 of the icp-cli migration).
    """
    return _ensure_members_impl(n, persona, start_index)


# ---------------------------------------------------------------------------
# Core executor
# ---------------------------------------------------------------------------

class E2EDriver:
    """Signed action executor for E2E tests.

    Parameters
    ----------
    realm_principal:
        Canister ID of the realm backend to target.
    realm_folder:
        Path to the realms project root (used for Candid / .did resolution).
    network:
        Network name — "staging" (default), "ic", "local".
    """

    def __init__(
        self,
        realm_principal: str,
        realm_folder: str = "/srv/dev/realms",
        network: str = "staging",
    ) -> None:
        self.realm_principal = realm_principal
        self.realm_folder = realm_folder
        self.network = network

    # ── Generic signed call ────────────────────────────────────────────────

    def execute(
        self,
        agent: Member,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        realm_principal: Optional[str] = None,
    ) -> Result:
        """Thin signed wrapper around realm_tools.execute_tool.

        Automatically injects ``user_identity``, ``user_principal``, ``network``,
        ``realm_folder``, and ``realm_principal`` — the caller only needs to
        supply domain-specific arguments.

        Returns::

            {"ok": bool, "raw": str, "parsed": dict|None, "error": str|None}
        """
        target = realm_principal or self.realm_principal
        raw = realm_tools.execute_tool(
            tool_name=tool_name,
            arguments=dict(args or {}),
            network=self.network,
            realm_folder=self.realm_folder,
            realm_principal=target,
            user_principal=agent["principal"],
            user_identity=agent["agent_id"],
        )
        return _wrap_result(raw)

    # ── Citizen actions ────────────────────────────────────────────────────

    def join_realm(
        self,
        agent: Member,
        profile: str = "member",
        preferred_quarter: str = "",
        realm_principal: Optional[str] = None,
    ) -> Result:
        """Join the realm as *agent*. Idempotent: "already joined" → ok=True."""
        args: Dict[str, Any] = {"profile": profile}
        if preferred_quarter:
            args["preferred_quarter"] = preferred_quarter
        r = self.execute(agent, "join_realm", args, realm_principal=realm_principal)
        # "already" in error text means already a member — treat as success
        err_str = str(r.get("error") or "").lower()
        if not r["ok"] and err_str and "already" in err_str:
            r["ok"] = True
            r["note"] = "already_joined"
        return r

    def get_status(self, agent: Member, realm_principal: Optional[str] = None) -> Result:
        """Get the member's current status in the realm."""
        return self.execute(agent, "get_my_status", realm_principal=realm_principal)

    # ── Governance ─────────────────────────────────────────────────────────

    def submit_proposal(
        self,
        agent: Member,
        title: str,
        description: str,
        code_url: str = "",
        realm_principal: Optional[str] = None,
    ) -> Result:
        """Submit a proposal for voting."""
        return self.execute(agent, "submit_proposal", {
            "title": title,
            "description": description,
            "code_url": code_url or "https://realms.vote/proposal/discussion",
        }, realm_principal=realm_principal)

    def cast_vote(
        self,
        agent: Member,
        proposal_id: str,
        vote: str,
        realm_principal: Optional[str] = None,
    ) -> Result:
        """Cast a vote on a proposal. vote: 'yes' | 'no' | 'abstain'."""
        r = self.execute(agent, "cast_vote", {
            "proposal_id": proposal_id,
            "vote": vote,
        }, realm_principal=realm_principal)
        if not r["ok"] and r.get("error") and "already" in r["error"].lower():
            r["ok"] = True
            r["note"] = "already_voted"
        return r

    # ── Economic ───────────────────────────────────────────────────────────

    def pay_invoice(
        self,
        agent: Member,
        invoice_id: str,
        amount: str,
        recipient: str,
        token: str = "AGO",
        realm_principal: Optional[str] = None,
    ) -> Result:
        """Pay an invoice by transferring tokens to the vault subaccount."""
        return self.execute(agent, "pay_invoice", {
            "invoice_id": invoice_id,
            "amount": amount,
            "recipient": recipient,
            "token": token,
        }, realm_principal=realm_principal)

    def transfer_tokens(
        self,
        agent: Member,
        recipient_principal: str,
        amount: str,
        token: str = "AGO",
        realm_principal: Optional[str] = None,
    ) -> Result:
        """Transfer tokens from agent to recipient."""
        return self.execute(agent, "icw_transfer_tokens", {
            "recipient": recipient_principal,
            "amount": amount,
            "token": token,
        }, realm_principal=realm_principal)

    def get_balance(
        self,
        agent: Member,
        principal_id: str = "",
        realm_principal: Optional[str] = None,
    ) -> Result:
        """Get token balance for agent (or a specific principal)."""
        args: Dict[str, Any] = {}
        if principal_id:
            args["principal_id"] = principal_id
        return self.execute(agent, "get_balance", args, realm_principal=realm_principal)

    # ── Litigation ─────────────────────────────────────────────────────────

    def sue_user(
        self,
        agent: Member,
        defendant_principal: str,
        title: str,
        description: str,
        defendant_quarter_id: str = "",
        realm_principal: Optional[str] = None,
    ) -> Result:
        """File and populate a user-vs-user litigation case.

        Calls create_litigation then set_litigation_content in one step.
        Returns the result of set_litigation_content (with case_id accessible
        from the create step's ``raw`` if needed).
        """
        create_args: Dict[str, Any] = {"defendant_principal": defendant_principal}
        if defendant_quarter_id:
            create_args["defendant_quarter_id"] = defendant_quarter_id
        r_create = self.execute(agent, "sue_user", create_args, realm_principal=realm_principal)
        if not r_create["ok"]:
            return r_create
        case_id = _extract_case_id(r_create)
        if not case_id:
            return _error_result("create_litigation returned no case_id", r_create["raw"])
        r_content = self.execute(agent, "set_litigation_content", {
            "case_id": case_id,
            "title": title,
            "description": description,
        }, realm_principal=realm_principal)
        r_content["case_id"] = case_id
        return r_content

    def sue_department(
        self,
        agent: Member,
        defendant_department: str,
        title: str,
        description: str,
        defendant_quarter_id: str = "",
        realm_principal: Optional[str] = None,
    ) -> Result:
        """File and populate a member-vs-department litigation case."""
        create_args: Dict[str, Any] = {"defendant_department": defendant_department}
        if defendant_quarter_id:
            create_args["defendant_quarter_id"] = defendant_quarter_id
        r_create = self.execute(agent, "sue_department", create_args, realm_principal=realm_principal)
        if not r_create["ok"]:
            return r_create
        case_id = _extract_case_id(r_create)
        if not case_id:
            return _error_result("create_litigation returned no case_id", r_create["raw"])
        r_content = self.execute(agent, "set_litigation_content", {
            "case_id": case_id,
            "title": title,
            "description": description,
        }, realm_principal=realm_principal)
        r_content["case_id"] = case_id
        return r_content

    def assign_judge(
        self,
        admin: Member,
        case_id: str,
        judge_principal: str,
        realm_principal: Optional[str] = None,
    ) -> Result:
        """Assign a judge to a case (admin action)."""
        return self.execute(admin, "assign_judge", {
            "case_id": case_id,
            "judge_principal": judge_principal,
        }, realm_principal=realm_principal)

    def issue_verdict(
        self,
        judge: Member,
        case_id: str,
        decision: str,
        penalties: Optional[list] = None,
        reasoning: str = "",
        realm_principal: Optional[str] = None,
    ) -> Result:
        """Issue a verdict (judge action)."""
        args: Dict[str, Any] = {"case_id": case_id, "decision": decision}
        if reasoning:
            args["reasoning"] = reasoning
        if penalties:
            args["penalties"] = penalties
        return self.execute(judge, "issue_verdict", args, realm_principal=realm_principal)

    def execute_penalty(
        self,
        admin: Member,
        penalty_id: str,
        realm_principal: Optional[str] = None,
    ) -> Result:
        """Execute a penalty after verdict (admin action)."""
        return self.execute(admin, "execute_penalty", {
            "penalty_id": penalty_id,
        }, realm_principal=realm_principal)

    def file_appeal(
        self,
        agent: Member,
        case_id: str,
        grounds: str,
        realm_principal: Optional[str] = None,
    ) -> Result:
        """File an appeal on the most recent verdict."""
        return self.execute(agent, "file_appeal", {
            "case_id": case_id,
            "grounds": grounds,
        }, realm_principal=realm_principal)

    def decide_appeal(
        self,
        judge: Member,
        appeal_id: str,
        decision: str,
        reasoning: str = "",
        realm_principal: Optional[str] = None,
    ) -> Result:
        """Decide an appeal (appellate judge action)."""
        args: Dict[str, Any] = {"appeal_id": appeal_id, "decision": decision}
        if reasoning:
            args["reasoning"] = reasoning
        return self.execute(judge, "decide_appeal", args, realm_principal=realm_principal)

    # ── Assertions ─────────────────────────────────────────────────────────

    @staticmethod
    def verify(condition: bool, message: str, context: Optional[Dict] = None) -> None:
        """Assert *condition* with a structured diagnostic on failure."""
        if not condition:
            diag = {"assertion": message}
            if context:
                diag.update(context)
            raise AssertionError(json.dumps(diag, indent=2, default=str))

    @staticmethod
    def assert_equal(a: Any, b: Any, message: str, context: Optional[Dict] = None) -> None:
        """Assert a == b with a structured diagnostic on failure."""
        if a != b:
            diag = {"assertion": message, "expected": b, "actual": a}
            if context:
                diag.update(context)
            raise AssertionError(json.dumps(diag, indent=2, default=str))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_case_id(result: "Result") -> str:
    """Extract case_id/id from a nested extension_sync_call response.

    The ExtensionCallResponse wrapper is: {"response": "<json>", "success": bool}.
    The inner json may be: {"success": true, "data": {"id": "..."}} or {"data": {...}}.
    """
    parsed = result.get("parsed") or {}
    # Try direct data.id first (clean path)
    direct = parsed.get("data", {})
    if isinstance(direct, dict) and direct.get("id"):
        return str(direct["id"])
    # Unwrap nested response string
    inner_str = parsed.get("response", "")
    if isinstance(inner_str, str) and inner_str:
        try:
            inner = json.loads(inner_str)
            data = inner.get("data", {})
            if isinstance(data, dict) and data.get("id"):
                return str(data["id"])
        except (json.JSONDecodeError, TypeError):
            pass
    return ""


def _wrap_result(raw: str) -> Result:
    """Parse a raw JSON string from realm_tools into a Result dict."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = None

    # An error-only dict (no "success" key) from _run_dfx_call / dfx fallback
    if isinstance(parsed, dict) and "error" in parsed and "success" not in parsed:
        return {"ok": False, "raw": raw, "parsed": parsed, "error": parsed["error"]}

    if isinstance(parsed, dict) and "error" in parsed and not parsed.get("success", True):
        return {"ok": False, "raw": raw, "parsed": parsed, "error": parsed["error"]}

    if isinstance(parsed, dict) and parsed.get("success") is False:
        return {"ok": False, "raw": raw, "parsed": parsed, "error": parsed.get("error") or parsed.get("data")}

    return {"ok": True, "raw": raw, "parsed": parsed, "error": None}


def _error_result(message: str, raw: str = "") -> Result:
    return {"ok": False, "raw": raw, "parsed": None, "error": message}


def _list_icp_identities() -> set[str]:
    """Return the set of identity names known to icp-cli."""
    rc, stdout, _ = _icp_run(["icp", "identity", "list", "--quiet"])
    if rc != 0:
        return set()
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def _ensure_members_impl(n: int, persona: str = "compliant", start_index: int = 1) -> List[Member]:
    members: List[Member] = []
    existing = _list_icp_identities()
    for i in range(start_index, start_index + n):
        agent_id = f"{_AGENT_PREFIX}{i:03d}"
        if agent_id not in existing:
            log.info("Creating identity %s …", agent_id)
            ok = icp_create(agent_id)
            if not ok:
                log.warning("Failed to create identity %s — skipping", agent_id)
                continue
        principal = icp_principal(agent_id)
        if not principal:
            log.warning("Could not resolve principal for %s — skipping", agent_id)
            continue
        members.append({"agent_id": agent_id, "principal": principal})
    return members


# ensure_members at module top delegates here; this line makes it idempotent
ensure_members = _ensure_members_impl  # noqa: F811


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Quick smoke test
    members = ensure_members(3, start_index=1)
    print(f"Members: {members}")
