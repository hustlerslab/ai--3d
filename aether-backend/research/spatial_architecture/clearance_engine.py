"""Compatibility shim. `clearance_engine` was migrated to `app.spatial.clearance_engine` in the
research-to-production pass (docs/production/research_to_production.md).
The canonical implementation is production code; this module re-exports it so
research benchmarks and historical reproductions keep importing from here.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.spatial.clearance_engine as _canonical  # noqa: E402

globals().update({k: v for k, v in vars(_canonical).items() if not k.startswith("__")})
del _canonical
