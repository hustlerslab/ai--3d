"""Back up and restore `data/` — P0-INFRA-002.

    python scripts/backup.py backup  --to  ../backups/2026-09-21
    python scripts/backup.py verify  --from ../backups/2026-09-21
    python scripts/backup.py restore --from ../backups/2026-09-21 --to ./data-restored

`data/` holds everything Allure cannot regenerate: the SQLite database, every
customer's uploaded photographs and renders, and **every Meshy mesh that was
paid for**. Losing it is not losing a cache; it is losing money and other
people's homes.

**The database is copied with SQLite's online backup API, never `cp`.**

That is the whole reason this is a script rather than a line in a runbook. The
database runs in WAL mode, and on this machine the write-ahead log was 1.9 MB
against a 1.0 MB database — so the majority of recent commits lived in the
`-wal` file, not in `allure.db`. A `cp allure.db` backup would produce a file
that opens cleanly, passes a smoke test, and is **missing every recent
transaction**. Copying the `-wal` alongside it is not a fix either: the pair is
consistent only if nothing writes between the two copies, and something always
writes.

`sqlite3.Connection.backup()` takes a consistent snapshot of a live database,
checkpointing as it goes. It is in the standard library and needs no lock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

#: Everything under data/ that must survive. `archive/` is included: it holds
#: deleted projects' artifacts, which is exactly what somebody asks to recover.
TREES = ("assets", "materials", "projects", "archive")

DB_NAME = "allure.db"
MANIFEST = "manifest.json"

#: Tables whose row counts are recorded, so a restore can be checked against
#: the source rather than merely "looking fine".
COUNTED = ("projects", "inputs", "analyses", "scene_specs", "jobs", "events",
           "outputs", "users", "sessions", "project_members", "spend_records",
           "capability_tokens")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_stats(root: Path) -> dict:
    files = total = 0
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            try:
                total += (Path(dirpath) / name).stat().st_size
                files += 1
            except OSError:
                pass                      # a file vanishing mid-walk is not fatal
    return {"files": files, "bytes": total}


def _table_counts(db_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        present = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in COUNTED if t in present}
    finally:
        conn.close()


def _copy_database(source: Path, target: Path) -> None:
    """A consistent snapshot of a LIVE database.

    Not shutil.copy2. See the module docstring: under WAL, the file on disk can
    be missing most of what has been committed.
    """
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)                   # stdlib online backup
        dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        # Fail here rather than hand over a corrupt snapshot that restores
        # silently and breaks weeks later.
        result = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"the snapshot failed its integrity check: {result}")
    finally:
        src.close()
        dst.close()


def run_backup(data_dir: Path, into: Path) -> dict:
    data_dir, into = Path(data_dir), Path(into)
    if not data_dir.is_dir():
        raise SystemExit(f"no such data directory: {data_dir}")
    into.mkdir(parents=True, exist_ok=True)

    db_source = data_dir / DB_NAME
    if db_source.exists():
        _copy_database(db_source, into / DB_NAME)

    for tree in TREES:
        source = data_dir / tree
        if source.is_dir():
            shutil.copytree(source, into / tree, dirs_exist_ok=True)

    manifest = {
        "created_at": _now_iso(),
        "source": str(data_dir.resolve()),
        "tool": "scripts/backup.py",
        "database": None,
        "trees": {t: _tree_stats(into / t) for t in TREES if (into / t).is_dir()},
    }
    if (into / DB_NAME).exists():
        manifest["database"] = {
            "path": DB_NAME,
            "sha256": _sha256(into / DB_NAME),
            "bytes": (into / DB_NAME).stat().st_size,
            "tables": _table_counts(into / DB_NAME),
        }
        conn = sqlite3.connect(f"file:{into / DB_NAME}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'").fetchone()
            manifest["schema_version"] = int(row[0]) if row else None
        except sqlite3.Error:
            manifest["schema_version"] = None
        finally:
            conn.close()

    (into / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def read_manifest(snapshot: Path) -> dict:
    return json.loads((Path(snapshot) / MANIFEST).read_text(encoding="utf-8"))


def verify(snapshot: Path) -> list[str]:
    """Check a snapshot against its own manifest. Returns a list of problems.

    A backup nobody verifies is a backup nobody has. This is cheap enough to
    run on every snapshot rather than on the day it is needed.
    """
    snapshot = Path(snapshot)
    problems: list[str] = []
    try:
        manifest = read_manifest(snapshot)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifest unreadable: {exc}"]

    db = manifest.get("database")
    if db:
        path = snapshot / db["path"]
        if not path.exists():
            problems.append(f"{db['path']} is missing")
        else:
            if _sha256(path) != db["sha256"]:
                problems.append(f"{db['path']} checksum does not match the manifest")
            # A verifier that CRASHES on a corrupt database is useless exactly
            # when corruption exists. Unreadable is a finding, not an exception.
            try:
                counts = _table_counts(path)
            except sqlite3.DatabaseError as exc:
                problems.append(f"{db['path']} is not a readable database: {exc}")
            else:
                for table, expected in (db.get("tables") or {}).items():
                    if counts.get(table) != expected:
                        problems.append(
                            f"{table}: {counts.get(table)} rows, manifest says {expected}")
            try:
                conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                try:
                    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
                finally:
                    conn.close()
                if result != "ok":
                    problems.append(f"{db['path']} failed its integrity check: {result}")
            except sqlite3.DatabaseError as exc:
                problems.append(f"{db['path']} could not be integrity-checked: {exc}")

    for tree, stats in (manifest.get("trees") or {}).items():
        actual = _tree_stats(snapshot / tree)
        if actual["files"] != stats["files"]:
            problems.append(
                f"{tree}/: {actual['files']} files, manifest says {stats['files']}")
    return problems


def run_restore(snapshot: Path, into: Path, force: bool = False) -> dict:
    """Restore into a directory. Refuses to overwrite a non-empty one.

    The refusal is the point: a restore runs under pressure, usually onto a
    machine somebody is guessing about, and "it silently merged into the live
    data directory" is a worse outcome than "it stopped and asked".
    """
    snapshot, into = Path(snapshot), Path(into)
    problems = verify(snapshot)
    if problems:
        raise SystemExit("refusing to restore a snapshot that fails verification:\n  "
                         + "\n  ".join(problems))

    if into.exists() and any(into.iterdir()) and not force:
        raise SystemExit(
            f"{into} is not empty. Restore into a clean directory, or pass --force "
            "if you have decided to overwrite it."
        )
    into.mkdir(parents=True, exist_ok=True)

    manifest = read_manifest(snapshot)
    if manifest.get("database"):
        shutil.copy2(snapshot / DB_NAME, into / DB_NAME)
        # A restored database must start with no stale sidecars: a -wal from
        # somewhere else, next to a restored .db, is a corruption waiting to be
        # opened.
        for sidecar in (f"{DB_NAME}-wal", f"{DB_NAME}-shm"):
            (into / sidecar).unlink(missing_ok=True)

    for tree in TREES:
        source = snapshot / tree
        if source.is_dir():
            shutil.copytree(source, into / tree, dirs_exist_ok=True)
    return manifest


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Back up and restore Allure's data directory.")
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("backup", help="take a snapshot")
    b.add_argument("--data", default=os.environ.get("AETHER_DATA_DIR", "./data"))
    b.add_argument("--to", required=True)

    v = sub.add_parser("verify", help="check a snapshot against its manifest")
    v.add_argument("--from", dest="src", required=True)

    r = sub.add_parser("restore", help="restore a snapshot into a directory")
    r.add_argument("--from", dest="src", required=True)
    r.add_argument("--to", required=True)
    r.add_argument("--force", action="store_true",
                   help="overwrite a non-empty target (think first)")

    args = parser.parse_args(argv)

    if args.command == "backup":
        manifest = run_backup(Path(args.data), Path(args.to))
        db = manifest.get("database") or {}
        print(f"snapshot written to {args.to}")
        print(f"  schema_version: {manifest.get('schema_version')}")
        print(f"  database: {db.get('bytes', 0):,} bytes  "
              f"sha256={db.get('sha256', '-')[:16]}...")
        for table, count in (db.get("tables") or {}).items():
            print(f"    {table}: {count}")
        for tree, stats in (manifest.get("trees") or {}).items():
            print(f"  {tree}/: {stats['files']:,} files, {stats['bytes']:,} bytes")
        return 0

    if args.command == "verify":
        problems = verify(Path(args.src))
        if problems:
            print("VERIFICATION FAILED:")
            for p in problems:
                print(f"  {p}")
            return 1
        print(f"{args.src} verifies against its manifest")
        return 0

    manifest = run_restore(Path(args.src), Path(args.to), force=args.force)
    print(f"restored {args.src} -> {args.to}")
    print(f"  taken {manifest.get('created_at')}, "
          f"schema_version {manifest.get('schema_version')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
