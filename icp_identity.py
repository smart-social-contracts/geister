#!/usr/bin/env python3
"""
icp_identity.py — Shared helpers for dual-store identity management.

During the dfx → icp-cli migration (Phase 1), both tools maintain separate
identity registries that must be kept in sync:

  dfx store : ~/.config/dfx/identity/<name>/identity.pem
  icp store : ~/.local/share/icp-cli/identity/identity_list.json + keys/

Both derive identical principals from compatible PEM files.  After Phase 2
(canister-call migration) dfx will be removed and only icp will remain.

Public API
----------
icp_principal(name)          -> str | None
icp_import_from_dfx(name)   -> bool   (idempotent)
icp_create(name)             -> bool   (creates in icp + registers in dfx)
icp_delete(name)             -> bool   (deletes from icp; dfx side handled by caller)
icp_default(name=None)       -> str    (getter/setter for icp's current identity)
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


# ---------------------------------------------------------------------------
# icp identity operations
# ---------------------------------------------------------------------------

def icp_principal(name: str) -> Optional[str]:
    """Return the principal for `name` from icp's registry, or None if unknown."""
    rc, out, _ = _run(["icp", "identity", "principal", "--identity", name])
    return out if rc == 0 and out else None


def icp_import_from_dfx(name: str) -> bool:
    """
    Import a dfx plaintext identity into icp's registry (idempotent).

    Reads the PEM from dfx's standard location and registers it with icp so
    that `icp identity principal --identity <name>` and related commands work.
    Returns True on success or if already registered; False on failure.
    """
    # Already registered in icp — nothing to do.
    if icp_principal(name) is not None:
        return True

    pem_path = os.path.expanduser(f"~/.config/dfx/identity/{name}/identity.pem")
    if not os.path.exists(pem_path):
        return False

    rc, _, _ = _run([
        "icp", "identity", "import", name,
        "--from-pem", pem_path,
        "--storage", "plaintext",
    ])
    return rc == 0


def icp_create(name: str) -> bool:
    """
    Create a new identity with icp-cli and register it in dfx as well.

    Strategy: create with icp, export the PEM, import into dfx — so both
    tools share the same key and derive the same principal.
    Returns True on success.
    """
    # Create in icp
    rc, _, _ = _run(["icp", "identity", "new", name, "--storage", "plaintext"])
    if rc != 0:
        return False

    # Export PEM from icp and import into dfx so _run_dfx_call can use --identity
    rc_exp, pem, _ = _run(["icp", "identity", "export", name])
    if rc_exp != 0 or not pem:
        return True  # icp creation succeeded; dfx sync failed (non-fatal for Phase 1)

    dfx_dir = os.path.expanduser(f"~/.config/dfx/identity/{name}")
    os.makedirs(dfx_dir, mode=0o755, exist_ok=True)
    pem_path = os.path.join(dfx_dir, "identity.pem")

    try:
        # Write PEM with restricted permissions (dfx expects mode 400)
        with open(pem_path, "w") as f:
            f.write(pem + ("\n" if not pem.endswith("\n") else ""))
        os.chmod(pem_path, 0o400)

        # Write the identity.json metadata dfx needs
        json_path = os.path.join(dfx_dir, "identity.json")
        if not os.path.exists(json_path):
            with open(json_path, "w") as f:
                f.write('{\n  "hsm": null,\n  "encryption": null,\n  "keyring_identity_suffix": null\n}\n')
    except OSError:
        pass  # dfx sync is best-effort during transition

    return True


def icp_delete(name: str) -> bool:
    """Delete an identity from icp's registry. Returns True on success or not-found."""
    rc, _, err = _run(["icp", "identity", "delete", name])
    return rc == 0 or "not found" in err.lower() or "no identity" in err.lower()


def icp_default(name: Optional[str] = None) -> str:
    """
    Get or set icp's current default identity.

    Called with no argument: returns the name of the current default.
    Called with a name: sets that identity as default and returns it.
    Returns empty string on failure.
    """
    if name is None:
        rc, out, _ = _run(["icp", "identity", "default"])
        return out if rc == 0 else ""
    rc, _, _ = _run(["icp", "identity", "default", name])
    return name if rc == 0 else ""
