"""P1-FRONTEND-002: everything the review screen says, in plain words.

The review screen is where a person judges the design, so its words are
assembled here - from the render verifier's evidence, the review queue, the
trade-offs and the repair audit trail - and nowhere else. Every string this
returns is a sentence for a person: no check name, category, status code or
internal id. `tests/test_review_surface.py` scans the whole payload for them.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from .projects import get_project_store
from .projects.layout import file_url, project_dir

#: Each deterministic scene check, as a person would ask it.
SCENE_CHECK_TEXT = {
    "expected_objects_exist": "Every piece was built",
    "object_count": "Nothing is missing or extra",
    "severe_intersections": "No piece passes through a wall or another piece",
    "room_architecture_preserved": "Walls, floors and ceilings are in place",
    "doors_windows_respected": "Doors can open fully",
    "circulation": "There is a clear way through the room",
    "render_matches_committed_scene": "The picture shows the current design",
}

#: Per-piece checks, summarised across pieces.
PIECE_CHECK_TEXT = {
    "scale": "Every piece is the size that was planned",
    "floating_objects": "Nothing is floating above the floor",
    "orientation": "Pieces face the way the picture showed",
    "approximate_location": "Pieces stand where the picture showed them",
}

#: What each review action means to the person deciding.
NEXT_STEP_TEXT = {
    "accept_as_is": "You can accept it as it is.",
    "retry_repair": "We can try correcting it again.",
    "replan": "We can re-plan the room.",
    "cancel": "You can stop here.",
}


def _read(path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _sentence(text: str) -> str:
    text = (text or "").strip().replace("(s)", "s")
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def _checks(ev: dict) -> list[dict[str, str]]:
    out = []
    for key, label in SCENE_CHECK_TEXT.items():
        verdict = (ev.get("scene_checks") or {}).get(key)
        if verdict is None:
            continue
        out.append({"label": label, "outcome": {"pass": "passed", "fail": "failed"}.get(verdict, "not_checked")})
    per = ev.get("per_object") or []
    for key, label in PIECE_CHECK_TEXT.items():
        verdicts = [(o.get("checks") or {}).get(key) for o in per]
        judged = [v for v in verdicts if v in ("pass", "fail")]
        if not judged:
            outcome = "not_checked"
        else:
            outcome = "failed" if "fail" in judged else "passed"
        out.append({"label": label, "outcome": outcome})
    out.append({"label": "Materials and colours match the design", "outcome": "not_checked"})
    return out


def review_view(project_id: str, *, role: str) -> dict[str, Any]:
    from .supervisor.messages import user_message
    from .supervisor.orchestrator import AuditTrail
    from .supervisor.review import ReviewQueue

    project = get_project_store().get(project_id)
    root = project_dir(project_id)

    render_rel = next((rel for rel in ("previews/build_preview.png", "renders/verify/corner_0.png")
                       if (root / rel).is_file()), None)
    render = {"url": file_url(project_id, render_rel)} if render_rel else None

    ev = _read(root / "planning" / "render_verification.json")
    checks = _checks(ev) if ev else []

    issues: list[dict[str, str]] = []
    for item in ReviewQueue().items(project_id, role=role, status="open"):
        issues.append({"text": _sentence(item.get("issue", "")),
                       "next": NEXT_STEP_TEXT.get(item.get("recommendation", ""), "")})
    try:
        from .api.projects_routes import tradeoff_statements

        for t in tradeoff_statements(project_id):
            issues.append({"text": t["statement"], "next": " ".join(o["label"] + "." for o in t["options"][:2])})
    except Exception:                                      # noqa: BLE001 - advisory, like the trade-off route
        pass

    rounds = AuditTrail(project_id).rounds()
    repair = None
    if rounds:
        latest = rounds[-1]
        if latest.get("outcome") == "in_progress" and latest.get("decision") == "RE_SOLVE":
            repair = {"attempt": int(latest["round"]), "of": 2,
                      "text": user_message("RE_SOLVE", repair_round=int(latest["round"]))}
        else:
            done = sum(1 for r in rounds if r.get("decision") == "RE_SOLVE")
            if done:
                repair = {"attempt": done, "of": 2,
                          "text": f"The layout was corrected automatically ({done} of 2 attempts used)."}

    failed = [c for c in checks if c["outcome"] == "failed"]
    if not project.scene_ids:
        status, text = "not_ready", "There is no design to review yet. Plan the space first."
    elif not ev:
        status, text = "not_verified", "This design hasn't been checked against its render yet."
    elif failed or issues:
        n = len(failed) + len(issues)
        status, text = "needs_attention", f"{n} thing{'s' if n != 1 else ''} to look at before you approve."
    else:
        status, text = "verified", "The built room was checked against the design and matches it."

    return {"status": status, "status_text": text, "render": render, "checks": checks,
            "issues": issues, "repair": repair, "can_decide": bool(project.scene_ids)}


__all__ = ["review_view", "SCENE_CHECK_TEXT", "PIECE_CHECK_TEXT"]
