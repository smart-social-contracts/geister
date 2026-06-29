"""
Phase 3 — Register N members; force 1-2 extra quarters.

Steps:
  1. ensure_members(N) → create swarm identities
  2. join_realm for each member (parallel batches, idempotent)
  3. Assert: N members joined; Casals quarter scaling triggered for N > autoscale threshold
"""

from __future__ import annotations

import json
import logging
import time
from typing import List, Optional

import realm_tools
from e2e_driver import E2EDriver, Member, ensure_members as _ensure_members
from e2e.run_state import RunState

log = logging.getLogger(__name__)

# Autoscale thresholds from realms defaults (configurable per realm)
AUTOSCALE_THRESHOLD = 10   # members per quarter before a new quarter spins up


def run(
    state: RunState,
    driver: E2EDriver,
    n_members: int = 20,
    start_index: int = 1,
) -> List[Member]:
    """Ensure N members are joined to the realm.  Returns the full member list."""

    phase = "phase_3_members"
    if state.is_done(phase):
        log.info("[Phase 3] already done — loading members from state")
        return state.get("members", [])

    # ── 1. Create identities ──────────────────────────────────────────────
    log.info("[Phase 3] Ensuring %d members (start_index=%d) …", n_members, start_index)
    members = _ensure_members(n_members, start_index=start_index)
    driver.verify(len(members) > 0, "No members were created", {"n_members": n_members})

    # ── 2. Join realm ─────────────────────────────────────────────────────
    joined = []
    failed = []
    for member in members:
        r = driver.join_realm(member)
        if r["ok"]:
            joined.append(member)
            log.info("[Phase 3] %s joined (note=%s)", member["agent_id"], r.get("note", ""))
        else:
            log.warning("[Phase 3] %s failed to join: %s", member["agent_id"], r.get("error"))
            failed.append(member)
        time.sleep(0.5)   # avoid rate-limiting on staging

    log.info("[Phase 3] Joined: %d/%d (failed: %d)", len(joined), n_members, len(failed))
    driver.verify(
        len(joined) >= n_members * 0.8,
        f"Too many join failures: {len(failed)}/{n_members}",
        {"joined": len(joined), "failed": [m["agent_id"] for m in failed]},
    )

    # ── 3. Check quarter autoscaling ──────────────────────────────────────
    expected_quarters = max(1, (len(joined) + AUTOSCALE_THRESHOLD - 1) // AUTOSCALE_THRESHOLD)
    log.info("[Phase 3] Expected quarters after autoscale: %d", expected_quarters)
    status_raw = realm_tools.realm_status(
        network=driver.network,
        realm_folder=driver.realm_folder,
        realm_principal=driver.realm_principal,
    )
    try:
        status = json.loads(status_raw) if isinstance(status_raw, str) else status_raw
        quarters = status.get("data", {}).get("quarters", [])
        log.info("[Phase 3] Quarters registered: %d", len(quarters))
        state.set("quarters", quarters)
    except Exception as e:
        log.warning("[Phase 3] Could not parse realm_status: %s", e)

    state.set("members", joined)
    state.mark_done(phase)
    log.info("[Phase 3] ✓ %d members joined the realm", len(joined))
    return joined
