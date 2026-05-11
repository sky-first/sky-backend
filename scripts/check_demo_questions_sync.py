#!/usr/bin/env python3
"""Fail CI when the BE smoke gate's question list drifts from FE source.

The structural promise of the demo-questions smoke gate
(``smoke_test_demo_questions.py``) is that the BE tests *exactly* what
the FE shows users. If somebody edits the 20 FE questions without
updating the BE copy, the gate keeps passing while users see refusals.

This helper closes that loop:

  1. Reads the FE source at ``$FRONTEND_ROOT/src/lib/demo-questions.ts``
     (path overrideable for monorepo setups via ``FE_DEMO_QUESTIONS``).
  2. Extracts every ``q: "..."`` literal.
  3. Compares against ``DEMO_QUESTIONS`` in
     ``smoke_test_demo_questions.py``.
  4. Exit 0 → in sync; non-zero → drift, with a diff printed.

Usage in CI (any workflow that mounts both repos):

  ::

      FE_DEMO_QUESTIONS=../sky-poc-frontend/src/lib/demo-questions.ts \
          python scripts/check_demo_questions_sync.py

When the FE repo isn't on disk (most BE-only CI), the helper is a
no-op with a warning — the developer-side ``smoke_test_demo_questions``
gate still runs against staging, which catches the drift functionally
even if the lint-style check skips.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

DEFAULT_FE_PATH = (
    os.environ.get("FE_DEMO_QUESTIONS") or "../sky-poc-frontend/src/lib/demo-questions.ts"
)
BE_SCRIPT = Path(__file__).parent / "smoke_test_demo_questions.py"

# Matches `q: 'text'` or `q: "text"` — handles the case where the
# value contains the OTHER quote (e.g. q: "How many … 'risk' or 'churn'?")
# by using two alternations, each banning only its own quote inside.
_FE_RE = re.compile(r"""q:\s*(?:'([^']+)'|"([^"]+)")""")
# Matches Python dict-literal style `"q": "text"` used in DEMO_QUESTIONS.
_BE_RE = re.compile(r'"q":\s*"([^"]+)"')


def extract_fe_questions(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    # Each match is a 2-tuple — exactly one group is non-empty per
    # match (the quote style that actually opened the value).
    return [a or b for a, b in _FE_RE.findall(src)]


def extract_be_questions(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    return _BE_RE.findall(src)


def main() -> int:
    fe_path = Path(DEFAULT_FE_PATH)
    if not fe_path.is_absolute():
        # Resolve relative to BE repo root (parents[1] = repo root).
        fe_path = (BE_SCRIPT.parent.parent / fe_path).resolve()

    if not fe_path.exists():
        print(
            f"check_demo_questions_sync: FE source not found at {fe_path} — "
            "skipping lint check. The staging smoke gate still enforces the "
            "contract functionally.",
            file=sys.stderr,
        )
        return 0

    fe = extract_fe_questions(fe_path)
    be = extract_be_questions(BE_SCRIPT)

    # Order-insensitive set comparison + size check. Order doesn't
    # change semantics, but a divergent size or content is drift.
    fe_set = set(fe)
    be_set = set(be)

    only_fe = sorted(fe_set - be_set)
    only_be = sorted(be_set - fe_set)

    if not only_fe and not only_be and len(fe) == len(be):
        print(f"OK — {len(fe)} demo questions are in sync between FE and BE.")
        return 0

    print("DRIFT — demo questions out of sync between FE and BE.")
    print(f"  FE: {fe_path}")
    print(f"  BE: {BE_SCRIPT}")
    print(f"  FE count: {len(fe)}    BE count: {len(be)}")
    if only_fe:
        print(f"\n  Only in FE ({len(only_fe)}):")
        for q in only_fe:
            print(f"    - {q}")
    if only_be:
        print(f"\n  Only in BE ({len(only_be)}):")
        for q in only_be:
            print(f"    - {q}")
    print(
        "\nFix: update DEMO_QUESTIONS in smoke_test_demo_questions.py so the "
        "BE gate tests exactly the questions the FE surfaces, then re-run."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
