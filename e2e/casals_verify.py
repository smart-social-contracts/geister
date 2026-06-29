"""
casals_verify.py — E2E canister retention verification.

Casals issue #8.

After a test run, every realm/quarter/token canister created by the E2E test
must appear in `casals tree` with status `in_use`.  This module provides:

  verify_e2e_handoff(realm_slug, casals_principal, network) -> list[dict]
  preflight_treasury_check(casals_principal, network, min_cycles_e12) -> dict
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

# Casals backend canister on staging (from canister_ids.json)
CASALS_STAGING_PRINCIPAL = "jj2e5-5aaaa-aaaac-qadgq-cai"


def _icp_call(canister: str, method: str, args: str = "()", network: str = "ic") -> dict:
    """Make a bare icp canister call and return parsed JSON."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    import icp_candid
    cmd = ["icp", "canister", "call", canister, method, args, "-n", network, "--query", "--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {"error": result.stderr.strip()}
    try:
        envelope = json.loads(result.stdout.strip())
        return icp_candid.parse(envelope.get("response_candid", "")) or {}
    except Exception as e:
        return {"error": str(e)}


def verify_e2e_handoff(
    realm_slug: str,
    canister_ids: List[str],
    casals_principal: str = CASALS_STAGING_PRINCIPAL,
    network: str = "staging",
) -> List[Dict]:
    """Assert all *canister_ids* appear in Casals pool as ``in_use``.

    Parameters
    ----------
    realm_slug:
        The slug/stand name used when creating the realm in Casals.
    canister_ids:
        All canister IDs created during the run (backend, frontend, quarters).
    casals_principal:
        Casals backend canister ID.
    network:
        Network name (mapped to icp ``-n ic``).

    Returns
    -------
    list of dicts: ``[{"canister_id", "name", "status", "ok": bool}]``
    Raises ``AssertionError`` if any canister is missing or not ``in_use``.
    """
    icp_net = "ic" if network in ("staging", "ic", "demo") else network
    report: List[Dict] = []

    # Fetch Casals tree for the realm stand
    tree_result = _icp_call(
        casals_principal, "get_tree", "()", icp_net
    )
    pool_canisters: Dict[str, dict] = {}
    if isinstance(tree_result, dict):
        for stand in tree_result.get("stands", []):
            if realm_slug.lower() in stand.get("name", "").lower():
                for c in stand.get("canisters", []):
                    pool_canisters[c.get("canister_id", "")] = c

    missing = []
    for cid in canister_ids:
        entry = pool_canisters.get(cid)
        if entry is None:
            report.append({"canister_id": cid, "name": "?", "status": "MISSING", "ok": False})
            missing.append(cid)
        else:
            status = entry.get("status", "")
            ok = status == "in_use"
            report.append({
                "canister_id": cid,
                "name": entry.get("name", ""),
                "status": status,
                "ok": ok,
            })
            if not ok:
                missing.append(cid)

    if missing:
        raise AssertionError(
            f"verify_e2e_handoff: {len(missing)} canister(s) missing or not in_use in Casals:\n"
            + "\n".join(f"  {cid}" for cid in missing)
        )

    log.info("verify_e2e_handoff: all %d canisters present as in_use ✓", len(canister_ids))
    return report


def preflight_treasury_check(
    casals_principal: str = CASALS_STAGING_PRINCIPAL,
    network: str = "staging",
    min_cycles_e12: int = 3,
) -> dict:
    """Check that the Casals treasury has at least *min_cycles_e12* trillion cycles.

    Returns ``{"ok": bool, "cycles_e12": float, "message": str}``.
    Raises ``RuntimeError`` if treasury is below threshold (fail-fast).
    """
    icp_net = "ic" if network in ("staging", "ic", "demo") else network
    result = _icp_call(casals_principal, "get_treasury_status", "()", icp_net)
    cycles_e12 = 0.0
    if isinstance(result, dict):
        cycles_e12 = result.get("cycles", result.get("spendable_cycles", 0)) / 1e12

    ok = cycles_e12 >= min_cycles_e12
    msg = f"Treasury: {cycles_e12:.1f}T cycles ({'✓ OK' if ok else '✗ INSUFFICIENT'})"
    log.info("[Casals] %s", msg)

    if not ok:
        raise RuntimeError(
            f"Casals treasury too low: {cycles_e12:.1f}T < {min_cycles_e12}T required. "
            "Top up before running E2E."
        )
    return {"ok": ok, "cycles_e12": cycles_e12, "message": msg}
