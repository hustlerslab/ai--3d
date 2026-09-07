"""SQLite persistence layer (DPR §21).

Holds projects, inputs, analyses, scene_specs, jobs, events and outputs.
Scenes and the asset/material registries stay as JSON files: they are
already versioned artifacts with their own stores.
"""
from .sqlite import Database, get_db, reset_db

__all__ = ["Database", "get_db", "reset_db"]
