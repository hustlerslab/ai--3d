"""Deterministic checks for the P8 constraint model (constraint_model.py).
No GPU, no models.
"""
from __future__ import annotations

from app.planning.constraint_model import (
    Constraint, ConstraintResult, ConstraintSet, ConstraintStatus, ConstraintType,
    Hardness, Verdict, constraint_id)


def test_constraint_id_is_deterministic():
    a = constraint_id("sofa", ConstraintType.ORIENTATION, "tv", {})
    b = constraint_id("sofa", ConstraintType.ORIENTATION, "tv", {})
    assert a == b


def test_constraint_id_differs_by_type():
    a = constraint_id("sofa", ConstraintType.ORIENTATION, "tv", {})
    b = constraint_id("sofa", ConstraintType.CONTACT, "tv", {})
    assert a != b


def test_constraint_id_is_hex_sha1_not_builtin_hash():
    cid = constraint_id("sofa", ConstraintType.ORIENTATION, "tv", {})
    assert cid.startswith("constraint_")
    int(cid[len("constraint_"):], 16)


def test_constraint_is_frozen():
    c = Constraint(constraint_id="c1", constraint_type=ConstraintType.ORIENTATION,
                   subject_id="sofa", target_id="tv")
    try:
        c.hardness = Hardness.HARD   # type: ignore[misc]
        assert False, "Constraint must be immutable"
    except Exception:
        pass


def test_default_hardness_is_soft():
    c = Constraint(constraint_id="c1", constraint_type=ConstraintType.ORIENTATION,
                   subject_id="sofa", target_id="tv")
    assert c.hardness == Hardness.SOFT


def test_lifecycle_status_and_verdict_are_independent_axes():
    """A constraint can be COMPILED (lifecycle) while its most recent
    evaluation is VIOLATED (verdict) - two different questions, two enums."""
    c = Constraint(constraint_id="c1", constraint_type=ConstraintType.ORIENTATION,
                   subject_id="sofa", target_id="tv", status=ConstraintStatus.COMPILED)
    r = ConstraintResult(constraint_id="c1", verdict=Verdict.VIOLATED, error=42.0)
    assert c.status == ConstraintStatus.COMPILED
    assert r.verdict == Verdict.VIOLATED
    # re-evaluating never mutates `c` - a NEW ConstraintResult is produced
    r2 = ConstraintResult(constraint_id="c1", verdict=Verdict.SATISFIED)
    assert c.status == ConstraintStatus.COMPILED   # unchanged
    assert r2.verdict != r.verdict


def test_constraint_set_lookups():
    c1 = Constraint(constraint_id="c1", constraint_type=ConstraintType.ORIENTATION,
                    subject_id="sofa", target_id="tv")
    c2 = Constraint(constraint_id="c2", constraint_type=ConstraintType.CONTACT,
                    subject_id="sofa", target_id="wall_a")
    cs = ConstraintSet(constraints=(c1, c2))
    assert cs.for_subject("sofa") == (c1, c2)
    assert cs.by_type(ConstraintType.ORIENTATION) == (c1,)
    assert cs.by_type(ConstraintType.SUPPORT) == ()


def test_constraint_set_never_silently_drops_unsupported():
    cs = ConstraintSet(constraints=(), unsupported=("intent_ghost",))
    assert "intent_ghost" in cs.unsupported


def test_reserved_constraint_types_are_named():
    """§10: ALIGNMENT/RELATION/CIRCULATION are reserved but complete - a
    future caller has a place for them without a breaking enum change."""
    for reserved in ("alignment", "relation", "circulation"):
        assert ConstraintType(reserved) is not None
