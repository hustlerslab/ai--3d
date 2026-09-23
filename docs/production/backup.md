# Backing up `data/` — the procedure

**P0-INFRA-002.** Restore-tested on 2026-09-21 against the real 1.5 GB data directory.

---

## What is at stake

`data/` holds everything Allure cannot regenerate:

| | Measured 2026-09-21 |
|---|---|
| `allure.db` | 1,110,016 bytes — 3 projects, 184 jobs, 2,459 events, 247 outputs |
| `assets/` | 310 files, **590 MB — every Meshy mesh that was paid for** |
| `materials/` | 65 files, 98 MB |
| `projects/` | 556 files, 828 MB — uploaded photographs, renders, planning artifacts |
| `archive/` | 120 files, 14 MB — deleted projects' artifacts |

Losing this is not losing a cache. It is losing money already spent and other people's homes.

**Before this task there was no backup of any kind.** The state was recorded as `[UNKNOWN]`; it was, in fact, none.

## Do not use `cp`

The database runs in **WAL mode**. When this was written the write-ahead log was **1.9 MB against a 1.0 MB database** — most recent commits lived in `allure.db-wal`, not in `allure.db`.

A `cp data/allure.db backup/` produces a file that:

- opens without error,
- passes a casual smoke test,
- and is **missing every recent transaction**.

Copying `-wal` and `-shm` alongside it is not a fix either: the three files are consistent only if nothing writes between the copies, and something always writes.

`scripts/backup.py` uses `sqlite3.Connection.backup()` — SQLite's online backup API — which takes a consistent snapshot of a live database with no downtime and no lock.

## The commands

```bash
cd aether-backend

# take a snapshot (data/ is opened read-only; the service keeps running)
python scripts/backup.py backup --data ./data --to /backups/allure/2026-09-21

# check a snapshot against its own manifest
python scripts/backup.py verify --from /backups/allure/2026-09-21

# restore into a CLEAN directory
python scripts/backup.py restore --from /backups/allure/2026-09-21 --to ./data-restored
```

Measured on the real directory: **backup 8.2 s, restore 8.7 s** for 1.5 GB.

## Frequency and retention

| | Policy | Why |
|---|---|---|
| **Frequency** | **Daily**, plus **before every deployment and every migration** | A migration is the most likely way to lose data deliberately, and it is the one moment you know about in advance |
| **Retention** | **7 daily**, **4 weekly**, **6 monthly** | Corruption noticed on Friday may have started on Tuesday; seven dailies cover the week you would actually look back over |
| **Location** | At least one copy **on a different physical device** | A snapshot on the same disk protects against `rm -rf`, not against the disk |
| **Verification** | `verify` on **every** snapshot; a full **restore test quarterly** | A backup nobody has restored is a hypothesis |

A restore test means this exact procedure into a scratch directory, then opening a project — not reading the manifest and nodding.

## What a snapshot contains

```
2026-09-21/
  allure.db          consistent snapshot, integrity-checked at write time
  assets/            the paid meshes
  materials/
  projects/
  archive/
  manifest.json
```

`manifest.json`:

```json
{
  "created_at": "2026-09-21T16:59:35Z",
  "schema_version": 6,
  "source": "/app/data",
  "database": {
    "path": "allure.db",
    "sha256": "ddb654b58ff1fd76...",
    "bytes": 1110016,
    "tables": {"projects": 3, "jobs": 184, "events": 2459, "outputs": 247}
  },
  "trees": {"assets": {"files": 310, "bytes": 590283345}}
}
```

Row counts and file counts are recorded so a restore can be **checked against the source**, rather than merely looking plausible.

## Safety behaviours, and why each exists

| Behaviour | Reason |
|---|---|
| `restore` **refuses a non-empty target** unless `--force` | A restore runs under pressure, onto a machine somebody is guessing about. "It silently merged into the live data directory" is worse than "it stopped and asked". |
| `restore` **verifies first** and refuses a failing snapshot | Better to stop than to hand over a half-restored directory. |
| `restore` **removes any `-wal`/`-shm`** in the target | A write-ahead log from a *different* database, sitting next to a restored `.db`, is corruption waiting to be opened. |
| `backup` runs `PRAGMA integrity_check` **at write time** | Fail now, loudly, rather than discover it on the day it is needed. |
| `verify` **reports** an unreadable database instead of raising | Found by a test: the first version crashed on a corrupt file — useless exactly when corruption exists. |

## The restore test, performed

Real snapshot of the live directory, restored into a clean directory, and the application booted against it:

```
GET /api/projects                    -> 3 projects
GET /api/projects/proj_a25a006c88    -> 200   name: test 1   stage: PREVIEW_RENDERING   inputs: 4
GET .../outputs                      -> 2 outputs
GET /files/.../panos/preview/n01.jpg -> 200, 160,216 bytes

read back from the restored database: 82 jobs, 114 outputs, 1,123 events
PAID MESHES restored: 69 .glb files, 396,443,592 bytes
```

The meshes are the point. A backup that restores the database but not `assets/` would look successful and cost the price of regenerating every purchased model.

## Not yet done

- **Off-site copy is a policy, not an automation.** The script writes wherever it is pointed; nothing yet ships a snapshot off the machine. That belongs with the deployment target, which is not chosen.
- **No scheduler is installed.** On a single host, `cron` or Task Scheduler calling the `backup` command is enough; in the container, an **external** scheduler should invoke it — a backup that dies with its container is not a backup.
