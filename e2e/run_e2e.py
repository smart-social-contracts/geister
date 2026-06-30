#!/usr/bin/env python3
"""
run_e2e.py — Top-level E2E orchestrator for the Realms platform.

realms issue #238.

Re-runnable, idempotent, resumable via run_state.json.

Usage
-----
    python e2e/run_e2e.py \
        --network staging \
        --members 20 \
        --voucher <code> \
        --identity swarm_agent_000 \
        --realm-principal <existing-id>   # skip Phase 1 if realm exists
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

# Add geister root to path so imports resolve from both locations
_GEISTER = Path(__file__).parent.parent
sys.path.insert(0, str(_GEISTER))

import realm_tools
from e2e_driver import E2EDriver, ensure_members
from e2e.run_state import RunState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

REALM_FOLDER = str(_GEISTER.parent / "realms") if (_GEISTER.parent / "realms").exists() else "/srv/dev/realms"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Realms E2E orchestrator")
    p.add_argument("--network",          default="staging",       help="IC network (staging/ic/local)")
    p.add_argument("--members",          type=int, default=20,    help="Number of test members to register")
    p.add_argument("--voucher",          default="",              help="Registry voucher code")
    p.add_argument("--identity",         default="swarm_agent_000", help="Operator icp identity name")
    p.add_argument("--realm-principal",  default="",              help="Existing realm canister ID (skips Phase 1)")
    p.add_argument("--realm-folder",     default=REALM_FOLDER,    help="Path to realms project root")
    p.add_argument("--state-file",       default="",              help="Path to run_state.json (default: e2e/run_state.json)")
    p.add_argument("--reset",            action="store_true",     help="Clear run_state and start fresh")
    p.add_argument("--phases",           default="",              help="Comma-separated phases to run (e.g. '1,3,6'); empty = all")
    return p.parse_args()


def _operator_member(identity: str) -> dict:
    from icp_identity import icp_principal, icp_create
    principal = icp_principal(identity)
    if not principal:
        log.info("Creating operator identity %s …", identity)
        icp_create(identity)
        principal = icp_principal(identity) or ""
    return {"agent_id": identity, "principal": principal}


def _phase_enabled(args: argparse.Namespace, phase_num: int) -> bool:
    if not args.phases:
        return True
    return str(phase_num) in [p.strip() for p in args.phases.split(",")]


def main() -> int:
    args = _parse_args()

    state_path = Path(args.state_file) if args.state_file else Path(__file__).parent / "run_state.json"
    state = RunState(state_path)

    if args.reset:
        log.info("Resetting run_state …")
        state._data = {}
        state.save()

    realm_principal = args.realm_principal or state.get("realm_principal", "")
    driver = E2EDriver(
        realm_principal=realm_principal,
        realm_folder=args.realm_folder,
        network=args.network,
    )

    operator = _operator_member(args.identity)
    log.info("Operator: %s (principal=%s)", operator["agent_id"], operator["principal"])

    report: dict = {"phases": {}}

    # ──────────────────────────────────────────────────────────────────────
    # Phase 1 — Create realm
    # ──────────────────────────────────────────────────────────────────────
    if _phase_enabled(args, 1):
        try:
            if realm_principal:
                log.info("[Phase 1] Skipped — using existing realm %s", realm_principal)
                driver.realm_principal = realm_principal
            else:
                from e2e.phase_1_realm import run as run_phase1
                realm_principal = run_phase1(state, driver, operator, voucher=args.voucher)
                driver.realm_principal = realm_principal
            report["phases"]["1"] = {"ok": True, "realm_principal": realm_principal}
        except Exception as e:
            log.error("[Phase 1] FAILED: %s", e)
            report["phases"]["1"] = {"ok": False, "error": str(e)}
            _print_report(report)
            return 1

    # ──────────────────────────────────────────────────────────────────────
    # Phase 2 — Assign admin roles to 2 friends
    # ──────────────────────────────────────────────────────────────────────
    if _phase_enabled(args, 2) and not state.is_done("phase_2_admin"):
        log.info("[Phase 2] Assigning admin roles …")
        try:
            admin_members = ensure_members(2, start_index=1)
            for admin in admin_members:
                # Join as member first (works with open registration), then promote
                r = driver.join_realm(admin, profile="member")
                if r["ok"] or r.get("note") == "already_joined":
                    log.info("[Phase 2] %s joined as member — will act as admin", admin["agent_id"])
                else:
                    log.warning("[Phase 2] %s join failed: %s", admin["agent_id"], r.get("error"))
            state.set("admin_members", admin_members)
            state.mark_done("phase_2_admin")
            report["phases"]["2"] = {"ok": True, "admins": [m["agent_id"] for m in admin_members]}
        except Exception as e:
            log.warning("[Phase 2] failed (non-fatal): %s", e)
            report["phases"]["2"] = {"ok": False, "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────
    # Phase 3 — Register N members; force extra quarters
    # ──────────────────────────────────────────────────────────────────────
    members: List[dict] = []
    if _phase_enabled(args, 3):
        try:
            from e2e.phase_3_members import run as run_phase3
            members = run_phase3(state, driver, n_members=args.members, start_index=3)
            report["phases"]["3"] = {"ok": True, "joined": len(members)}
        except Exception as e:
            log.error("[Phase 3] FAILED: %s", e)
            report["phases"]["3"] = {"ok": False, "error": str(e)}
    else:
        members = state.get("members", [])

    # ──────────────────────────────────────────────────────────────────────
    # Phase 4 — Stage progression alpha → beta → production
    # ──────────────────────────────────────────────────────────────────────
    if _phase_enabled(args, 4) and not state.is_done("phase_4_stages"):
        log.info("[Phase 4] Advancing realm stages …")
        try:
            for stage in ("beta", "production"):
                log.info("[Phase 4] Setting stage: %s …", stage)
                r = realm_tools.execute_tool(
                    "find_objects",
                    {"model": "RealmSettings", "action": "set_realm_stage", "stage": stage},
                    network=args.network, realm_folder=args.realm_folder,
                    realm_principal=realm_principal,
                    user_identity=operator["agent_id"], user_principal=operator["principal"],
                )
                log.info("[Phase 4] stage=%s result: %s", stage, r[:80])
                time.sleep(2)
            state.mark_done("phase_4_stages")
            report["phases"]["4"] = {"ok": True}
        except Exception as e:
            log.warning("[Phase 4] failed (non-fatal): %s", e)
            report["phases"]["4"] = {"ok": False, "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────
    # Phase 5 — Taxes → projects + social security
    # ──────────────────────────────────────────────────────────────────────
    if _phase_enabled(args, 5) and not state.is_done("phase_5_taxes"):
        log.info("[Phase 5] Tax payment cycle …")
        try:
            vault_raw = realm_tools.get_vault_status(
                network=args.network, realm_folder=args.realm_folder,
                realm_principal=realm_principal,
            )
            vault_data = json.loads(vault_raw)
            vault_principal = (vault_data.get("data") or {}).get("vault_principal", "")

            paid = 0
            for member in members[:min(5, len(members))]:
                invoices_raw = realm_tools.execute_tool(
                    "find_objects",
                    {"model": "Invoice", "filters": {"user_id": member["principal"], "status": "Pending"}},
                    network=args.network, realm_folder=args.realm_folder,
                    realm_principal=realm_principal,
                    user_identity=member["agent_id"], user_principal=member["principal"],
                )
                try:
                    invoices_data = json.loads(invoices_raw)
                    invoices = (invoices_data.get("data") or {}).get("objects", [])
                    for inv in invoices[:1]:   # pay first pending invoice
                        r = driver.pay_invoice(
                            member, inv["id"], str(inv.get("amount_ago", 10)),
                            vault_principal or realm_principal, token="AGO"
                        )
                        if r["ok"]:
                            paid += 1
                except Exception as ie:
                    log.debug("[Phase 5] invoice parse error for %s: %s", member["agent_id"], ie)
                time.sleep(0.5)

            log.info("[Phase 5] %d invoices paid", paid)
            state.mark_done("phase_5_taxes")
            report["phases"]["5"] = {"ok": True, "invoices_paid": paid}
        except Exception as e:
            log.warning("[Phase 5] failed (non-fatal): %s", e)
            report["phases"]["5"] = {"ok": False, "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────
    # Phase 6 — Litigation
    # ──────────────────────────────────────────────────────────────────────
    if _phase_enabled(args, 6) and len(members) >= 5:
        try:
            from e2e.phase_6_litigation import run as run_phase6
            admin_m = state.get("admin_members", [operator])[0]
            summary = run_phase6(state, driver, members, admin_m)
            report["phases"]["6"] = {"ok": True, "summary": summary}
        except Exception as e:
            log.error("[Phase 6] FAILED: %s", e)
            report["phases"]["6"] = {"ok": False, "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────
    # Phase 7 — Proposals + voting
    # ──────────────────────────────────────────────────────────────────────
    if _phase_enabled(args, 7) and len(members) >= 3:
        try:
            from e2e.phase_7_proposals import run as run_phase7
            admin_m = state.get("admin_members", [operator])[0]
            summary = run_phase7(state, driver, members, admin_m)
            report["phases"]["7"] = {"ok": True, "summary": summary}
        except Exception as e:
            log.error("[Phase 7] FAILED: %s", e)
            report["phases"]["7"] = {"ok": False, "error": str(e)}

    _print_report(report)
    all_ok = all(v.get("ok", True) for v in report["phases"].values())
    return 0 if all_ok else 1


def _print_report(report: dict) -> None:
    print("\n" + "=" * 60)
    print("E2E TEST REPORT")
    print("=" * 60)
    for phase, result in sorted(report.get("phases", {}).items()):
        status = "✓ PASS" if result.get("ok") else "✗ FAIL"
        print(f"  Phase {phase}: {status}")
        if not result.get("ok"):
            print(f"          Error: {result.get('error', 'unknown')}")
        elif result.get("realm_principal"):
            print(f"          realm_principal: {result['realm_principal']}")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
