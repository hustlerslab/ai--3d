"""P0-AI-002 - the no-silent-mock rule, pinned.

The rule: a deterministic estimate must never be presented as a reading of a
customer's photograph. `ResilientProvider` already draws the distinction that
makes that possible -

  * primary is None  -> the operator CHOSE the deterministic provider. That is
    a selection, not a degradation, and carries no warning.
  * primary FAILED   -> the answer is an estimate standing in for a reading. It
    must say so, naming the provider and the stage.

The behaviour is correct today and was untested. These tests exist so it cannot
regress quietly, which is the only way this particular bug ever arrives.
"""
from __future__ import annotations

import pytest

from app.intelligence import InputBundle, ResilientProvider
from app.intelligence.mock_provider import MockProvider

BRIEF = "A calm two-bedroom flat with a south-facing living room."


class Explodes:
    """A primary that is configured, reachable, and broken - the dangerous
    case. An absent provider is obvious; one that fails mid-stage is not."""

    name = "explodey"
    label = "explodey:v1"

    def __init__(self, exc: Exception | None = None):
        self._exc = exc or RuntimeError("upstream returned 503")

    def _boom(self, *_a, **_k):
        raise self._exc

    analyze_input = _boom
    create_style_spec = _boom
    plan_objects = _boom
    read_scene_elements = _boom
    classify_reference = _boom
    check_element_crop = _boom
    estimate_element_dimensions = _boom
    compose_scene_prompt = _boom


def _bundle() -> InputBundle:
    return InputBundle(project_id="p", description=BRIEF)


def _stages(provider: ResilientProvider):
    """Run all three Protocol stages, returning the result of each."""
    analysis = provider.analyze_input(_bundle())
    style = provider.create_style_spec(analysis, _bundle())
    plan = provider.plan_objects(analysis, style, _bundle())
    return analysis, style, plan


# ── the distinction itself ────────────────────────────────────────────────

def test_selected_mock_is_not_labelled_a_fallback():
    """The operator asked for the deterministic provider. Nothing failed, so
    nothing may claim something failed - a false alarm on every project teaches
    people to ignore the warning that matters."""
    provider = ResilientProvider(None, MockProvider(), allow_fallback=True)
    assert provider.mode == "mock"
    for result in _stages(provider):
        assert "fallback" not in result.provider, result.provider
        assert not any("failed during" in w for w in result.warnings), result.warnings


@pytest.mark.parametrize("stage", ["analyze_input", "create_style_spec", "plan_objects"])
def test_a_failed_primary_names_the_provider_and_the_stage(stage):
    """Every Protocol stage, not just the first one. The warning has to carry
    both facts: WHICH provider broke and WHERE, or an operator reading the feed
    cannot tell a timeout from a bad prompt."""
    provider = ResilientProvider(Explodes(), MockProvider(), allow_fallback=True)
    analysis, style, plan = _stages(provider)
    result = {"analyze_input": analysis, "create_style_spec": style, "plan_objects": plan}[stage]

    assert result.provider == "mock(fallback)", (
        f"{stage} returned provider={result.provider!r}; an estimate that claims to "
        "be the real provider is the exact failure this rule exists to prevent"
    )
    first = result.warnings[0]
    assert "explodey" in first and stage in first, first
    assert "deterministic estimate" in first, first


def test_the_warning_is_first_so_it_cannot_be_scrolled_past():
    """Position is load-bearing: the UI shows warnings in order, and a
    'this is an estimate' notice buried under six advisory lines is not a
    notice."""
    provider = ResilientProvider(Explodes(), MockProvider(), allow_fallback=True)
    analysis = provider.analyze_input(_bundle())
    assert analysis.warnings[0].startswith("explodey failed during analyze_input")


def test_strict_mode_raises_instead_of_substituting():
    """With fallback disallowed the failure must surface, not be absorbed.
    This is the setting a production deployment should run."""
    provider = ResilientProvider(Explodes(), MockProvider(), allow_fallback=False)
    with pytest.raises(RuntimeError, match="503"):
        provider.analyze_input(_bundle())


def test_the_estimate_is_still_a_usable_answer():
    """Honesty must not cost usability - a labelled estimate is better than an
    error page, which is why the fallback exists at all."""
    provider = ResilientProvider(Explodes(), MockProvider(), allow_fallback=True)
    analysis = provider.analyze_input(_bundle())
    assert analysis.rooms, "the fallback produced nothing usable"


# ── optional capabilities: where a fabricated reading would actually land ──
#
# These five have NO mock fallback by design. A mock answer here would be
# invented detail about a photograph nobody looked at.

def test_a_failed_render_read_reports_the_error_not_an_empty_room():
    """'the model timed out' and 'this room is empty' are different facts.
    Collapsing them into {} once hid a real outage."""
    provider = ResilientProvider(Explodes(), MockProvider(), allow_fallback=True)
    out = provider.read_scene_elements(object(), object(), object(), object())
    assert "_error" in out and "503" in out["_error"], out
    assert not out.get("elements"), "a failed read must not return invented furniture"


def test_a_failed_reference_classification_reports_the_error():
    """An unreadable photograph has to stay visible, not vanish."""
    provider = ResilientProvider(Explodes(), MockProvider(), allow_fallback=True)
    out = provider.classify_reference(object(), "a brass floor lamp", object())
    assert "_error" in out and "503" in out["_error"], out


def test_a_failed_crop_check_is_not_a_pass():
    """An empty result routes the crop to a human. Treating a failure as
    approval would wave an unverified element straight through to spend."""
    provider = ResilientProvider(Explodes(), MockProvider(), allow_fallback=True)
    assert provider.check_element_crop(object(), "living_room", object()) == {}


def test_a_failed_prompt_compose_falls_back_to_the_template_not_the_mock():
    """An empty string tells the caller to use the keyword template - a real
    prompt whose provenance the caller records. A mock-written prompt would be
    the silent degradation itself."""
    provider = ResilientProvider(Explodes(), MockProvider(), allow_fallback=True)
    assert provider.compose_scene_prompt(object(), object(), object(), object()) == ""


def test_a_provider_missing_a_capability_says_so_rather_than_returning_nothing():
    """MockProvider has no read_scene_elements. 'cannot read' must be
    distinguishable from 'read and found nothing'."""
    class Bare:
        name = "bare"
        label = "bare:v0"

    provider = ResilientProvider(Bare(), MockProvider(), allow_fallback=True)
    out = provider.read_scene_elements(object(), object(), object(), object())
    assert "_error" in out and "no read_scene_elements" in out["_error"], out
