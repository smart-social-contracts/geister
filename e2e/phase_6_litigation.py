"""
Phase 6 — Litigation: intra-quarter and cross-quarter suits.

Scenario:
  member[0] sues member[1] (same quarter)         → intra-quarter user suit
  member[2] sues member[3] (different quarter)    → cross-quarter user suit (if >1 quarter)
  member[4] sues the Treasury department           → department suit

Full verdict/penalty/appeal lifecycle on the intra-quarter case.
Cross-quarter suit: file + verdict; penalty execution is a TODO stub.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from e2e_driver import E2EDriver, Member
from e2e.run_state import RunState

log = logging.getLogger(__name__)


def run(
    state: RunState,
    driver: E2EDriver,
    members: List[Member],
    admin: Member,
) -> dict:
    """Run Phase 6.  Returns a summary dict with case/verdict/appeal IDs."""

    phase = "phase_6_litigation"
    if state.is_done(phase):
        log.info("[Phase 6] already done")
        return state.get("litigation_summary", {})

    driver.verify(len(members) >= 5, "Need at least 5 members for litigation phase", {"count": len(members)})

    summary: dict = {}

    # ── A. Intra-quarter user suit ────────────────────────────────────────
    log.info("[Phase 6-A] %s suing %s (intra-quarter) …", members[0]["agent_id"], members[1]["agent_id"])
    r_sue = driver.sue_user(
        agent=members[0],
        defendant_principal=members[1]["principal"],
        title="Breach of community guidelines",
        description="The defendant repeatedly violated community rules causing damage to the plaintiff.",
    )
    driver.verify(r_sue["ok"], "Intra-quarter sue_user failed", {"result": r_sue})
    case_id_intra = r_sue.get("case_id", "")
    log.info("[Phase 6-A] case_id=%s", case_id_intra)
    summary["intra_case_id"] = case_id_intra

    # Assign judge (admin acts as judge for E2E)
    r_judge = driver.assign_judge(admin, case_id_intra, admin["principal"])
    if not r_judge["ok"]:
        log.warning("[Phase 6-A] assign_judge failed: %s (continuing)", r_judge.get("error"))

    # Issue verdict
    r_verdict = driver.issue_verdict(
        judge=admin,
        case_id=case_id_intra,
        decision="guilty",
        penalties=[{
            "type": "fine",
            "amount": 10.0,
            "currency": "AGO",
            "description": "Fine for community guidelines breach",
            "target_user_id": members[1]["principal"],
        }],
        reasoning="Clear evidence of repeated violations.",
    )
    driver.verify(r_verdict["ok"], "issue_verdict failed", {"result": r_verdict})
    verdict_id = (r_verdict.get("parsed") or {}).get("data", {}).get("verdict", {}).get("id", "")
    penalty_id = ""
    penalties = (r_verdict.get("parsed") or {}).get("data", {}).get("verdict", {}).get("penalties", [])
    if penalties:
        penalty_id = penalties[0].get("id", "")
    log.info("[Phase 6-A] verdict_id=%s penalty_id=%s", verdict_id, penalty_id)
    summary["verdict_id"] = verdict_id
    summary["penalty_id"] = penalty_id

    # Execute penalty
    if penalty_id:
        r_exec = driver.execute_penalty(admin, penalty_id)
        if not r_exec["ok"]:
            log.warning("[Phase 6-A] execute_penalty failed: %s", r_exec.get("error"))
        else:
            log.info("[Phase 6-A] penalty executed")

    # File appeal
    r_appeal = driver.file_appeal(
        agent=members[1],
        case_id=case_id_intra,
        grounds="The verdict lacked proper evidence and the judge was biased.",
    )
    driver.verify(r_appeal["ok"], "file_appeal failed", {"result": r_appeal})
    appeal_id = (r_appeal.get("parsed") or {}).get("data", {}).get("appeal", {}).get("id", "")
    log.info("[Phase 6-A] appeal_id=%s", appeal_id)
    summary["appeal_id"] = appeal_id

    # Decide appeal
    if appeal_id:
        r_decide = driver.decide_appeal(
            judge=admin,
            appeal_id=appeal_id,
            decision="upheld",
            reasoning="Evidence was sufficient. Original verdict stands.",
        )
        if not r_decide["ok"]:
            log.warning("[Phase 6-A] decide_appeal failed: %s", r_decide.get("error"))
        else:
            log.info("[Phase 6-A] appeal decided: upheld")

    # ── B. Cross-quarter user suit ────────────────────────────────────────
    quarters = state.get("quarters", [])
    if len(quarters) >= 2:
        cross_quarter_id = quarters[1].get("canister_id", "")
        if cross_quarter_id:
            log.info("[Phase 6-B] %s suing %s cross-quarter …", members[2]["agent_id"], members[3]["agent_id"])
            r_cross = driver.sue_user(
                agent=members[2],
                defendant_principal=members[3]["principal"],
                title="Cross-quarter financial dispute",
                description="The defendant owes funds from a cross-quarter transaction.",
                defendant_quarter_id=cross_quarter_id,
            )
            if r_cross["ok"]:
                summary["cross_case_id"] = r_cross.get("case_id", "")
                log.info("[Phase 6-B] cross-quarter case filed: %s", summary["cross_case_id"])
            else:
                log.warning("[Phase 6-B] cross-quarter suit failed: %s", r_cross.get("error"))
    else:
        log.info("[Phase 6-B] Only 1 quarter — skipping cross-quarter suit")

    # ── C. Department suit ────────────────────────────────────────────────
    log.info("[Phase 6-C] %s suing Treasury department …", members[4]["agent_id"])
    r_dept = driver.sue_department(
        agent=members[4],
        defendant_department="Treasury",
        title="Improper funds allocation",
        description="The Treasury department failed to properly allocate social security funds.",
    )
    if r_dept["ok"]:
        summary["dept_case_id"] = r_dept.get("case_id", "")
        log.info("[Phase 6-C] dept case filed: %s", summary["dept_case_id"])
    else:
        log.warning("[Phase 6-C] dept suit failed: %s", r_dept.get("error"))

    state.set("litigation_summary", summary)
    state.mark_done(phase)
    log.info("[Phase 6] ✓ litigation scenario complete: %s", summary)
    return summary
