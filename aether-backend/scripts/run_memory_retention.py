"""P1-MEMORY-002: apply agent-memory retention and print what was deleted.

The backend also runs this once at boot; schedule this script (cron / Task
Scheduler, daily) for a deployment that stays up for weeks.

    python scripts/run_memory_retention.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.supervisor.memory import apply_retention  # noqa: E402


def main() -> int:
    log = apply_retention()
    print(json.dumps([{k: e[k] for k in ("table_name", "reason", "cutoff", "deleted", "projects")} for e in log],
                     indent=2))
    print(f"{sum(e['deleted'] for e in log)} row(s) deleted across {len(log)} store(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
