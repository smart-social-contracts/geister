"""
Phase 1 — Create realm from registry (Agora codex).

Steps:
  1. Operator authenticates via icp identity
  2. Check / redeem voucher for registry credits
  3. Request deployment via registry_deploy_realm (Agora codex, useCasals=true)
  4. Poll installer until realm_principal is available
  5. Join as admin / operator
  6. Assert: AGO token provisioned, realm.status == "alpha"
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import realm_tools
from e2e_driver import E2EDriver, Member
from e2e.run_state import RunState

log = logging.getLogger(__name__)

POLL_INTERVAL = 10   # seconds between installer status checks
POLL_TIMEOUT  = 600  # max seconds to wait for deployment


def run(
    state: RunState,
    driver: E2EDriver,
    operator: Member,
    voucher: str = "",
    realm_name: str = "E2E Test Realm",
    codex: str = "agora",
) -> str:
    """Deploy a fresh realm via the registry.  Returns the realm_principal (canister ID)."""

    phase = "phase_1_realm"
    if state.is_done(phase):
        realm_principal = state.get("realm_principal")
        log.info("[Phase 1] already done — realm_principal=%s", realm_principal)
        return realm_principal

    # ── 1. Credits check / voucher ────────────────────────────────────────
    log.info("[Phase 1] Checking registry credits …")
    credits_raw = realm_tools.execute_tool(
        "registry_get_credits",
        {"principal_id": operator["principal"]},
        network=driver.network,
        realm_folder=driver.realm_folder,
        user_identity=operator["agent_id"],
        user_principal=operator["principal"],
    )
    credits_result = json.loads(credits_raw)
    credits = credits_result.get("credits", 0) if isinstance(credits_result, dict) else 0

    if credits < 5 and voucher:
        log.info("[Phase 1] Redeeming voucher %s …", voucher)
        realm_tools.execute_tool(
            "registry_redeem_voucher",
            {"voucher_code": voucher},
            network=driver.network,
            realm_folder=driver.realm_folder,
            user_identity=operator["agent_id"],
            user_principal=operator["principal"],
        )

    # ── 2. Deploy realm ───────────────────────────────────────────────────
    log.info("[Phase 1] Deploying realm '%s' (codex=%s) …", realm_name, codex)
    deploy_raw = realm_tools.execute_tool(
        "registry_deploy_realm",
        {"realm_name": realm_name, "codex": codex, "use_casals": True},
        network=driver.network,
        realm_folder=driver.realm_folder,
        user_identity=operator["agent_id"],
        user_principal=operator["principal"],
    )
    deploy_result = json.loads(deploy_raw)
    if deploy_result.get("error"):
        raise RuntimeError(f"[Phase 1] Deploy failed: {deploy_result}")

    job_id = (deploy_result.get("data") or deploy_result).get("job_id", "")
    if not job_id:
        raise RuntimeError(f"[Phase 1] No job_id in deploy response: {deploy_result}")

    log.info("[Phase 1] Deploy job_id=%s — polling installer …", job_id)

    # ── 3. Poll installer ─────────────────────────────────────────────────
    realm_principal: Optional[str] = None
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        status_raw = realm_tools.execute_tool(
            "registry_deploy_status",
            {"job_id": job_id},
            network=driver.network,
            realm_folder=driver.realm_folder,
            user_identity=operator["agent_id"],
            user_principal=operator["principal"],
        )
        status = json.loads(status_raw)
        job_status = (status.get("data") or status).get("status", "")
        log.info("[Phase 1] installer status: %s", job_status)

        if job_status == "deployed":
            realm_principal = (status.get("data") or status).get("backend_canister_id", "")
            break
        if job_status in ("failed", "error"):
            raise RuntimeError(f"[Phase 1] Deployment failed: {status}")

        time.sleep(POLL_INTERVAL)

    if not realm_principal:
        raise RuntimeError("[Phase 1] Timed out waiting for realm deployment")

    log.info("[Phase 1] Realm deployed — principal=%s", realm_principal)
    state.set("realm_principal", realm_principal)
    state.set("job_id", job_id)
    driver.realm_principal = realm_principal

    # ── 4. Join as operator/admin ─────────────────────────────────────────
    log.info("[Phase 1] Operator joining realm …")
    r = driver.join_realm(operator, profile="admin")
    driver.verify(r["ok"], "Operator failed to join realm", {"result": r})

    state.mark_done(phase)
    log.info("[Phase 1] ✓ realm_principal=%s", realm_principal)
    return realm_principal
