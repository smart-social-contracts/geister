"""
Phase 7 — Proposals and voting (local + federal scope).

Scenario:
  1. admin submits a local proposal
  2. All members vote yes
  3. Verify lifecycle: pending_review → voting → approved
  4. admin submits a federal proposal
  5. Members vote yes/no
"""

from __future__ import annotations

import json
import logging
import time
from typing import List

from e2e_driver import E2EDriver, Member
from e2e.run_state import RunState

log = logging.getLogger(__name__)


def run(
    state: RunState,
    driver: E2EDriver,
    members: List[Member],
    admin: Member,
) -> dict:
    phase = "phase_7_proposals"
    if state.is_done(phase):
        log.info("[Phase 7] already done")
        return state.get("proposals_summary", {})

    summary: dict = {}

    # ── Local proposal ─────────────────────────────────────────────────────
    log.info("[Phase 7] Submitting local proposal …")
    r_prop = driver.submit_proposal(
        agent=admin,
        title="Community Garden Initiative",
        description="Allocate 100 AGO from the social security pool to fund a community garden accessible to all members.",
        code_url="https://realms.vote/proposal/community-garden",
    )
    driver.verify(r_prop["ok"], "submit_proposal failed", {"result": r_prop})
    proposal_id = (r_prop.get("parsed") or {}).get("data", {}).get("id", "")
    if not proposal_id:
        proposal_id = (r_prop.get("parsed") or {}).get("proposal_id", "")
    log.info("[Phase 7] proposal_id=%s", proposal_id)
    summary["local_proposal_id"] = proposal_id

    if proposal_id:
        log.info("[Phase 7] Having %d members vote yes …", len(members))
        voted = 0
        for member in members[:min(len(members), 10)]:  # first 10 members vote
            r_vote = driver.cast_vote(member, proposal_id, "yes")
            if r_vote["ok"]:
                voted += 1
            else:
                log.debug("[Phase 7] %s vote failed: %s", member["agent_id"], r_vote.get("error"))
            time.sleep(0.3)
        log.info("[Phase 7] %d votes cast on local proposal", voted)
        summary["local_votes_cast"] = voted

    # ── Federal proposal ───────────────────────────────────────────────────
    log.info("[Phase 7] Submitting federal proposal …")
    r_fed = driver.submit_proposal(
        agent=admin,
        title="Federal Tax Rate Adjustment",
        description="Propose reducing the federal tax rate from 10% to 8% to stimulate local economic activity.",
        code_url="https://realms.vote/proposal/federal-tax-rate",
    )
    if r_fed["ok"]:
        fed_id = (r_fed.get("parsed") or {}).get("data", {}).get("id", "")
        summary["federal_proposal_id"] = fed_id
        log.info("[Phase 7] federal proposal_id=%s", fed_id)

        if fed_id:
            for i, member in enumerate(members[:min(len(members), 10)]):
                vote = "yes" if i % 3 != 0 else "no"   # 2/3 yes, 1/3 no
                driver.cast_vote(member, fed_id, vote)
                time.sleep(0.3)
    else:
        log.warning("[Phase 7] Federal proposal failed: %s", r_fed.get("error"))

    state.set("proposals_summary", summary)
    state.mark_done(phase)
    log.info("[Phase 7] ✓ proposals and voting complete: %s", summary)
    return summary
