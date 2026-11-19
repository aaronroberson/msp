#!/usr/bin/env python3
"""Generate src/tui_manifest/COVERAGE.md: per CLI action, curated pages or fallback-only.

    .venv/bin/python scripts/coverage_report.py [--check]

Fallback pages never count as implementing a command (plan D14). ``--check``
exits 1 when the committed report is stale.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.tui_manifest import coverage, load_commands, load_pages, render_coverage  # noqa: E402

REPORT = REPO / "src" / "tui_manifest" / "COVERAGE.md"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Fail if the committed report is stale")
    args = parser.parse_args(argv)
    rendered = render_coverage(coverage(load_commands(), load_pages()))
    if args.check:
        if not REPORT.exists() or REPORT.read_text() != rendered:
            print(f"{REPORT.relative_to(REPO)} is stale; run scripts/coverage_report.py", file=sys.stderr)
            return 1
        return 0
    REPORT.write_text(rendered)
    print(f"wrote {REPORT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
