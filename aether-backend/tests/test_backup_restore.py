"""P0-INFRA-002 - Allure cannot lose every customer's purchased 3D assets to
one disk failure.

The acceptance criterion is not "a backup script exists". It is:

    A restore reproduces a working project INCLUDING its meshes.

So these tests take a real snapshot, restore it into a clean directory, and
then OPEN the restored database and read the project back out of it.

The sharpest test here is the WAL one. Before this script existed, the obvious
backup was `cp data/allure.db`. On this machine the write-ahead log was 1.9 MB
against a 1.0 MB database - most recent commits lived in the `-wal`, not the
`.db`. A copied file would open cleanly, pass a smoke test, and be missing
every recent transaction. That is the failure this module exists to prevent,
and it is asserted directly.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.backup import read_manifest, run_backup, run_restore, verify  # noqa: E402

PAID_MESH = b"GLB-paid-mesh-bytes"
PANORAMA = b"a rendered panorama"
BRIEF = "A warm modern 2BHK, keeping the oak flooring."


def _data_dir(root: Path) -> Path:
    """A data directory shaped like a real one: a database, a paid mesh, a
    material, and one project with a render and a brief."""
    from app.db.sqlite import Database

    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)

    db = Database(data / "allure.db")
    db.execute(
        "INSERT INTO projects(project_id, name, description, stage, scene_ids,"
        " room_hints, vertical, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        ("proj_restore_me", "Sharma Residence", BRIEF, "CREATED", "[]", "[]",
         "residential", "2026-09-21T00:00:00Z", "2026-09-21T00:00:00Z"),
    )
    db.close()

    (data / "assets" / "normalized").mkdir(parents=True, exist_ok=True)
    (data / "assets" / "normalized" / "sofa.glb").write_bytes(PAID_MESH)
    (data / "materials" / "wood_oak").mkdir(parents=True, exist_ok=True)
    (data / "materials" / "wood_oak" / "color.jpg").write_bytes(b"tex")
    web = data / "projects" / "proj_restore_me" / "outputs" / "web"
    web.mkdir(parents=True, exist_ok=True)
    (web / "pano.jpg").write_bytes(PANORAMA)
    (data / "projects" / "proj_restore_me" / "input").mkdir(parents=True, exist_ok=True)
    (data / "projects" / "proj_restore_me" / "input" / "description.txt").write_text(
        BRIEF, encoding="utf-8")
    return data


# ── the snapshot ─────────────────────────────────────────────────────────

def test_a_snapshot_records_what_it_contains(tmp_path):
    data = _data_dir(tmp_path)
    manifest = run_backup(data, tmp_path / "snap")

    assert manifest["created_at"].endswith("Z"), "timestamps must be UTC"
    assert manifest["schema_version"] >= 7
    assert manifest["database"]["tables"]["projects"] == 1
    assert len(manifest["database"]["sha256"]) == 64
    assert manifest["trees"]["assets"]["files"] == 1
    assert manifest["trees"]["projects"]["files"] == 2


def test_a_snapshot_verifies_against_its_own_manifest(tmp_path):
    data = _data_dir(tmp_path)
    run_backup(data, tmp_path / "snap")
    assert verify(tmp_path / "snap") == []


def test_a_tampered_snapshot_fails_verification(tmp_path):
    """A backup nobody verifies is a backup nobody has."""
    data = _data_dir(tmp_path)
    run_backup(data, tmp_path / "snap")
    (tmp_path / "snap" / "assets" / "normalized" / "sofa.glb").unlink()

    problems = verify(tmp_path / "snap")
    assert problems and any("assets" in p for p in problems), problems


def test_a_corrupt_database_in_a_snapshot_is_caught(tmp_path):
    data = _data_dir(tmp_path)
    run_backup(data, tmp_path / "snap")
    (tmp_path / "snap" / "allure.db").write_bytes(b"not a database")

    problems = verify(tmp_path / "snap")
    assert problems, "a corrupted database passed verification"


# ── the WAL trap: the reason this is a script and not `cp` ───────────────

def test_a_snapshot_captures_commits_that_a_file_copy_would_miss(tmp_path):
    """THE test.

    A live WAL database holds committed rows outside the .db file. A naive copy
    produces a database that opens, passes a smoke test, and has lost data.
    """
    import shutil

    from app.db.sqlite import Database

    data = _data_dir(tmp_path)
    live = Database(data / "allure.db")        # left OPEN, as in production
    for i in range(50):
        live.execute(
            "INSERT INTO projects(project_id, name, description, stage, scene_ids,"
            " room_hints, vertical, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (f"proj_wal_{i}", f"p{i}", "", "CREATED", "[]", "[]", "residential",
             "2026-09-21T00:00:00Z", "2026-09-21T00:00:00Z"),
        )

    # The honest snapshot, taken while the database is live.
    run_backup(data, tmp_path / "snap")

    # The naive alternative, for comparison: copy the .db and nothing else.
    naive = tmp_path / "naive.db"
    shutil.copy2(data / "allure.db", naive)
    live.close()

    def count(path: Path) -> int:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        finally:
            conn.close()

    assert count(tmp_path / "snap" / "allure.db") == 51, \
        "the snapshot lost committed rows"
    # Not asserting the naive copy is wrong - on some builds a checkpoint may
    # have landed. Asserting the snapshot is RIGHT is the claim that matters,
    # and it holds either way.
    assert count(naive) <= 51


# ── the restore ──────────────────────────────────────────────────────────

def test_a_restore_reproduces_the_project_including_its_meshes(tmp_path):
    """The acceptance criterion, end to end."""
    data = _data_dir(tmp_path)
    run_backup(data, tmp_path / "snap")
    restored = tmp_path / "restored"
    run_restore(tmp_path / "snap", restored)

    # The paid mesh, byte for byte. This is the money.
    mesh = restored / "assets" / "normalized" / "sofa.glb"
    assert mesh.exists() and mesh.read_bytes() == PAID_MESH

    # The customer's render and brief.
    assert (restored / "projects" / "proj_restore_me" / "outputs" / "web"
            / "pano.jpg").read_bytes() == PANORAMA
    assert (restored / "projects" / "proj_restore_me" / "input"
            / "description.txt").read_text(encoding="utf-8") == BRIEF

    # And the database OPENS and the project is readable out of it - not just
    # "a file of the right size is present".
    conn = sqlite3.connect(f"file:{restored / 'allure.db'}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT name, description FROM projects WHERE project_id = ?",
            ("proj_restore_me",)).fetchone()
    finally:
        conn.close()
    assert row == ("Sharma Residence", BRIEF)


def test_the_restored_database_is_usable_by_the_application(tmp_path):
    """Opened through the app's own Database class, which runs the migration
    ladder - a restore that needs a schema upgrade must not explode."""
    from app.db.sqlite import SCHEMA_VERSION, Database

    data = _data_dir(tmp_path)
    run_backup(data, tmp_path / "snap")
    run_restore(tmp_path / "snap", tmp_path / "restored")

    db = Database(tmp_path / "restored" / "allure.db")
    try:
        assert int(db.scalar(
            "SELECT value FROM meta WHERE key='schema_version'")) == SCHEMA_VERSION
        assert db.one("SELECT name FROM projects WHERE project_id = ?",
                      ("proj_restore_me",))["name"] == "Sharma Residence"
    finally:
        db.close()


def test_a_restored_database_has_no_stale_wal_beside_it(tmp_path):
    """A `-wal` from another database next to a restored `.db` is a corruption
    waiting to be opened."""
    data = _data_dir(tmp_path)
    run_backup(data, tmp_path / "snap")
    restored = tmp_path / "restored"
    restored.mkdir()
    (restored / "allure.db-wal").write_bytes(b"stale wal from somewhere else")

    run_restore(tmp_path / "snap", restored, force=True)
    assert not (restored / "allure.db-wal").exists()


def test_restoring_into_a_non_empty_directory_is_refused(tmp_path):
    """A restore runs under pressure. "It silently merged into the live data
    directory" is worse than "it stopped and asked"."""
    data = _data_dir(tmp_path)
    run_backup(data, tmp_path / "snap")
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "something.txt").write_text("in use", encoding="utf-8")

    with pytest.raises(SystemExit, match="not empty"):
        run_restore(tmp_path / "snap", target)

    run_restore(tmp_path / "snap", target, force=True)     # deliberate override
    assert (target / "allure.db").exists()


def test_restoring_a_failing_snapshot_is_refused(tmp_path):
    """Better to stop than to hand somebody a half-restored data directory."""
    data = _data_dir(tmp_path)
    run_backup(data, tmp_path / "snap")
    (tmp_path / "snap" / "allure.db").write_bytes(b"corrupt")

    with pytest.raises(SystemExit, match="verification"):
        run_restore(tmp_path / "snap", tmp_path / "restored")
    assert not (tmp_path / "restored" / "allure.db").exists()


def test_a_snapshot_round_trips_twice_without_drift(tmp_path):
    """Back up a restore, and the manifests must agree - otherwise each cycle
    quietly loses something."""
    data = _data_dir(tmp_path)
    first = run_backup(data, tmp_path / "snap1")
    run_restore(tmp_path / "snap1", tmp_path / "restored")
    second = run_backup(tmp_path / "restored", tmp_path / "snap2")

    assert first["database"]["tables"] == second["database"]["tables"]
    for tree, stats in first["trees"].items():
        assert second["trees"][tree]["files"] == stats["files"], tree


def test_the_manifest_is_json_a_human_can_read(tmp_path):
    data = _data_dir(tmp_path)
    run_backup(data, tmp_path / "snap")
    raw = (tmp_path / "snap" / "manifest.json").read_text(encoding="utf-8")
    assert json.loads(raw) == read_manifest(tmp_path / "snap")
    assert "\n" in raw, "the manifest should be readable, not one long line"
