# ISSUE-001 — A JSON object in `dimensions` silently wipes a project's room hints

**Status:** open · **Severity:** medium (silent data loss, no error surfaced)
**Found:** 11 Sep 2026, during the verticals QA pass
**Pre-existing:** yes — confirmed against `HEAD` (`67982ee`). Predates the
verticals feature and was deliberately left out of its scope.

Filed here rather than in a tracker because this repo has no issue tracker
configured and `gh` is not installed on the machine it was found on. Move it if
that changes.

## Summary

`POST /api/projects/{id}/inputs` accepts a JSON **object** where it requires a
JSON **list**. An empty object `{}` does not raise — it succeeds as "zero
rooms", writes an input record claiming `rooms: 0`, and overwrites the project's
existing `room_hints` with an empty list. The dimensions the user entered
earlier are gone, and the response is `200`.

## Repro

```bash
# 1. create a project and give it two rooms
curl -s -X POST localhost:8000/api/projects \
  -H 'Content-Type: application/json' \
  -d '{"name":"repro","description":"warm minimal 2BHK"}'
# → note the project_id, e.g. proj_abc123

curl -s -X POST localhost:8000/api/projects/proj_abc123/inputs \
  -F 'dimensions=[{"type":"living_room","width_m":5,"length_m":4},
                  {"type":"bedroom","width_m":4,"length_m":3.5}]'

curl -s localhost:8000/api/projects/proj_abc123      # → room_hints: 2 entries

# 2. send an empty JSON object instead of a list
curl -s -X POST localhost:8000/api/projects/proj_abc123/inputs \
  -F 'dimensions={}'
# → 200 OK, input record with meta {"rooms": 0}

curl -s localhost:8000/api/projects/proj_abc123      # → room_hints: []  ← wiped
```

Expected: `422 INVALID_DIMENSIONS`, and the existing room hints left untouched.

## Root cause

`app/api/projects_routes.py`, in `add_inputs`:

```python
if dimensions is not None and dimensions.strip():
    try:
        hints = [RoomHint.model_validate(h) for h in json.loads(dimensions)]
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        return _error("INVALID_DIMENSIONS", ..., 422)
```

`json.loads("{}")` returns `{}`. Iterating a dict yields its **keys**, and an
empty dict has none — so the comprehension produces `[]` without raising, and
none of the three caught exception types fires. Execution continues: the handler
writes `input/dimensions.json` as `[]`, creates an `InputRecord` with
`meta={"rooms": 0}`, and calls `store.update(project_id, room_hints=[])`.

In `app/projects/store.py`, `update()` treats "omitted" as `None`:

```python
[h.model_dump() for h in (room_hints if room_hints is not None else current.room_hints)]
```

`[]` is not `None`, so it is written through as a deliberate empty value and the
previous hints are replaced.

## What is *not* broken

Every other malformed input is handled correctly and returns `422`: `not json`,
`[1,2,3]`, `"a string"`, `null`, and objects with bad field types. A **non-empty**
object such as `{"a": 1}` also fails correctly — iterating it yields the key
`"a"`, and `RoomHint.model_validate("a")` raises. The defect is specific to a
JSON value that is iterable but empty where a list of rooms was required.

## Suggested fix

Validate the parsed shape before the comprehension:

```python
parsed = json.loads(dimensions)
if not isinstance(parsed, list):
    return _error("INVALID_DIMENSIONS",
                  "dimensions must be a JSON list of rooms", 422)
```

Worth deciding separately, and out of scope for this issue: whether an
explicitly empty list `[]` should clear room hints or be rejected too. Today it
clears them. That is at least arguably intentional, where `{}` plainly is not.

## Test on record

`aether-backend/tests/test_vertical_boundary.py::test_a_json_object_in_dimensions_is_rejected_not_silently_treated_as_no_rooms`

Marked `xfail(strict=True)`, so it records the defect now and **fails the day it
is fixed** — remove the marker as part of the fix.
