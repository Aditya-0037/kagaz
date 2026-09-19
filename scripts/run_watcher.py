"""Run the expiry watcher for a chosen date, so a demo can show the digest
arriving without waiting for real time to pass.

Usage: .venv/Scripts/python.exe scripts/run_watcher.py --as-of 2026-09-12
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root, for `watcher.*`/`agents.*` imports

from watcher.expiry_job import run_watcher  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Kagaz expiry watcher as of a chosen date.")
    parser.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()

    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    body, alerts, outbox_path = run_watcher(as_of)

    print(body)
    print()
    print(f"{len(alerts)} alert(s).")
    if outbox_path:
        print(f"Digest written to {outbox_path}")


if __name__ == "__main__":
    main()
