"""`python -m jurist.ingest.statutes` — CLI entry."""
from __future__ import annotations

import argparse
import sys

from jurist.ingest.statutes import run_ingest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m jurist.ingest.statutes",
        description="Fetch + parse BWB XML; write data/kg/huurrecht.json.",
    )
    parser.add_argument("--refresh", action="store_true",
                        help="Force re-fetch and re-parse (bypass source_versions check).")
    parser.add_argument("--no-fetch", action="store_true",
                        help="Cache-only; fail if cache is empty for any allowlist BWB.")
    parser.add_argument("--bwb", action="append", dest="bwb_ids", default=None,
                        metavar="BWB_ID",
                        help="Restrict to specific BWB IDs (debug; repeatable).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap articles per BWB (debug).")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print per-step summary.")
    args = parser.parse_args(argv)

    try:
        run_ingest(
            refresh=args.refresh,
            no_fetch=args.no_fetch,
            bwb_ids=args.bwb_ids,
            limit=args.limit,
            verbose=True,
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
