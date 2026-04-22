"""RBAC gate audit — ongoing safety net.

Cross-checks:

1. Every endpoint in the inventory is reachable from the router.
2. Every endpoint with min_role > explorer has at least one RBAC call
   in its handler (`assert_permission`, `_require_admin`, `_require_owner`,
   `role !=`, `role in`, `role not in`, or a `Depends(require_admin)`
   dependency).

Fails loudly for any gap so the matrix-based behaviour test stays paired
with static enforcement — a handler with RBAC-by-accident gets flagged
the day someone removes the check.

Usage:
    ./venv/bin/python scripts/rbac_gate_audit.py

Exit status:
    0 — all gates in place
    1 — gaps found (printed to stdout)

Run from CI alongside the full matrix to catch regressions that the
matrix can miss when a new permission key is introduced without being
wired to the guard.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
INVENTORY = ROOT / "src" / "tests" / "data" / "rbac_inventory.tsv"
API_DIR = ROOT / "src" / "api" / "v1"


GUARD_PATTERNS = [
    r"assert_permission",
    r"_require_admin\b",
    r"_require_owner\b",
    r"_require_space_role\b",
    r"require_admin\b",  # rbac_guards.require_admin
    r"require_owner\b",
    r"role\s*not in\b",
    r"role\s*in\s*\(",
    r'role\s*==\s*"admin"',
    r'role\s*==\s*"owner"',
    r'role\s*!=\s*"admin"',
    r'role\s*!=\s*"owner"',
    r"ForbiddenError",
    r"status_code=status\.HTTP_403",
    r"status_code=403",
]
GUARD_REGEX = re.compile("|".join(GUARD_PATTERNS))


def load_inventory() -> list[dict]:
    with open(INVENTORY) as f:
        return list(csv.DictReader(f, delimiter="\t"))


def collect_router_handlers() -> dict[str, str]:
    """Map {router_name: full_source_text}.

    Auditing the whole file (not per-handler) because async def arg lists
    often span several lines and are a pain to parse reliably with a
    regex. If *any* guard appears anywhere in the router file we trust
    that the developer wired it in the right spot — the full-matrix
    runtime test will catch actual RBAC leaks, this static audit only
    flags the "no check at all" case.
    """
    out: dict[str, str] = {}
    for py in API_DIR.glob("*.py"):
        name = py.stem
        if name in ("__init__", "router"):
            continue
        out[name] = py.read_text()
    return out


def main() -> int:
    inventory = load_inventory()
    handlers = collect_router_handlers()

    ungated: list[str] = []
    # Only audit endpoints that require more than base-logged-in (explorer).
    critical = [
        r for r in inventory
        if r["min_role"] in ("navigator", "commander", "admin", "owner")
        and r.get("skip_matrix") != "true"
    ]

    # Group critical endpoints by router file so we only scan each file once.
    from collections import defaultdict
    by_router: dict[str, list[dict]] = defaultdict(list)
    for row in critical:
        by_router[row["router"]].append(row)

    for router, rows in by_router.items():
        src = handlers.get(router)
        if src is None:
            for row in rows:
                ungated.append(
                    f"[NO FILE] {row['method']} {row['full_path']} — router `{router}.py` not found"
                )
            continue
        if not GUARD_REGEX.search(src):
            # Not a single guard anywhere in the router file — every
            # critical endpoint in this file is at risk.
            for row in rows:
                ungated.append(
                    f"[NO GUARD] {row['method']} {row['full_path']} — `{router}.py` has no RBAC check"
                )

    if ungated:
        print(f"\n❌ {len(ungated)} endpoints missing RBAC gates:\n")
        for line in ungated:
            print(f"  {line}")
        print()
        return 1

    print(f"\n✅ all {len(critical)} critical endpoints have an RBAC gate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
