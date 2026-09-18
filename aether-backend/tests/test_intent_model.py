"""Deterministic checks for the P8 intent model (intent_model.py). No GPU,
no models. See docs/spatial_architecture/intent_model.md for the design.
"""
from __future__ import annotations

from app.planning.intent_model import (
    DEFAULT_PRIORITY, Intent, IntentPriority, IntentSource, intent_id)


def test_intent_id_is_deterministic():
    a = intent_id("sofa", "FACES", "tv", {})
    b = intent_id("sofa", "FACES", "tv", {})
    assert a == b


def test_intent_id_differs_by_parameters():
    a = intent_id("sofa", "NEAR", "tv", {"distance_m": 1.0})
    b = intent_id("sofa", "NEAR", "tv", {"distance_m": 2.0})
    assert a != b


def test_intent_id_parameter_key_order_is_irrelevant():
    a = intent_id("sofa", "NEAR", "tv", {"a": 1, "b": 2})
    b = intent_id("sofa", "NEAR", "tv", {"b": 2, "a": 1})
    assert a == b


def test_intent_id_is_not_pythons_builtin_hash():
    iid = intent_id("sofa", "FACES", "tv", {})
    assert iid.startswith("intent_")
    int(iid[len("intent_"):], 16)   # must be valid hex (sha1-derived)


def test_create_assigns_default_priority_from_source():
    i = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x")
    assert i.priority == IntentPriority.USER_EXPLICIT


def test_create_honours_explicit_priority_even_when_it_is_zero():
    """Regression guard for the `priority or DEFAULT_PRIORITY[source]` bug
    caught during development: IntentPriority.USER_EXPLICIT == 0, which is
    falsy in Python, so `or` would silently discard an explicit zero."""
    i = Intent.create("sofa", "FACES", "tv", source=IntentSource.MODEL_INFERRED,
                      provenance="x", priority=IntentPriority.USER_EXPLICIT)
    assert i.priority == IntentPriority.USER_EXPLICIT


def test_every_source_has_a_default_priority():
    for source in IntentSource:
        assert source in DEFAULT_PRIORITY


def test_intent_is_frozen():
    i = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x")
    try:
        i.confidence = "LOW"   # type: ignore[misc]
        assert False, "Intent must be immutable"
    except Exception:
        pass


def test_intent_has_no_mutable_status_field():
    """Documented design choice (module docstring): unlike the brief's own
    sketch, `Intent` carries no `status` - lifecycle lives on the derived
    `Constraint` instead."""
    i = Intent.create("sofa", "FACES", "tv", source=IntentSource.USER_ASSERTED, provenance="x")
    assert not hasattr(i, "status")


def test_parameters_default_to_empty_dict_not_shared():
    a = Intent.create("x", "NEAR", "y", provenance="p")
    b = Intent.create("x", "NEAR", "y", provenance="p")
    assert a.parameters == {} and b.parameters == {}
    assert a.parameters is not b.parameters
