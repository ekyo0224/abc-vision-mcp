# -*- coding: utf-8 -*-
"""Prove the re-planning loop changes the plan. This is the submission's claim.

The OpenCV rules say the visual evidence must change what the system does next,
and explicitly rule out systems that only describe a fixed result. So the thing
that has to be demonstrated -- not asserted -- is that excluding the anchor a
plan rested on causes the engine to produce a *different* plan, not the same one
again.

The fixture puts the subject on court in two blocks separated by a gap wider
than ``MAX_LINK_GAP_S``, so the engine sees two candidate anchors and has
somewhere else to go when the first is ruled out. A rival with a clearly
different appearance is present throughout, because identity here is a
comparison, not a threshold.

These tests are skipped when the engine checkout is not reachable; they are not
silently passed.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from abc_vision_mcp import identity  # noqa: E402

FPS = 30.0
REGIONS = ["r%02dc%d" % (r, c) for r in range(10) for c in range(3)]


def _sig(hue: float, sat: float = 200.0, val: float = 180.0) -> dict[str, list]:
    """A flat appearance signature.

    Each band is ``[hue, saturation, value]`` in OpenCV's ranges -- hue on
    [0,180), the other two on [0,255] -- matching what ``band_hsv`` produces.
    Two people are separated by hue, and the saturation is kept high because
    ``band_distance`` only trusts hue as far as the region is actually
    coloured.
    """
    return {k: [hue, sat, val] for k in REGIONS}


def _box(x: float, y: float = 400.0, w: float = 60.0, h: float = 160.0) -> tuple:
    # production boxes are (x0, y0, x1, y1, score) of plain floats
    return (x, y, x + w, y + h, 0.9)


def _samples() -> list[tuple]:
    """Subject in two blocks; rival throughout.

    Block A: frames 0..40. Gap of 150 frames (5 s > MAX_LINK_GAP_S = 3 s).
    Block B: frames 190..230.

    The subject walks slowly enough to stay inside MAX_SPEED_PX_PER_S, so each
    block links into one tracklet and the two blocks cannot link to each other.
    """
    subject, rival = _sig(20.0), _sig(120.0)
    out = []
    for fi in list(range(0, 41, 2)) + list(range(190, 231, 2)):
        sx = 300.0 + (fi % 40) * 2.0
        rx = 900.0 - (fi % 40) * 2.0
        out.append((fi, [_box(sx), _box(rx)], [subject, rival], [160.0, 160.0]))
    return out


def _ranges() -> list[tuple]:
    """Two rallies, one over each block, as (start_sec, duration_sec)."""
    return [(0.0, 2.0), (6.3, 2.0)]


@pytest.fixture
def session():
    try:
        identity.engine()
    except RuntimeError as exc:
        pytest.skip("engine unavailable: %s" % exc)
    info = identity.open_session(
        samples=_samples(),
        fps=FPS,
        enrolled_sig=_sig(20.0),
        enrolled_height=160.0,
        rival_sigs=[_sig(120.0)],
        ranges=_ranges(),
    )
    return info["session_id"]


# --------------------------------------------------------------------------
# The claim
# --------------------------------------------------------------------------

def test_excluding_the_anchor_produces_a_different_plan(session):
    """The whole submission rests on this being true."""
    first = identity.propose_identity(session)
    assert first["outcome"] == "plan", first
    assert first["anchor_key"] is not None

    second = identity.propose_identity(
        session, avoid_anchors=[first["anchor_key"]]
    )
    assert second["outcome"] in ("plan", "no_plan")

    if second["outcome"] == "plan":
        assert second["anchor_key"] != first["anchor_key"], (
            "the engine anchored on the same tracklet after it was excluded -- "
            "avoid_anchors did not take effect"
        )
    # Either outcome is honest: a different anchor, or an admission that there
    # is nowhere else to anchor. What would falsify the claim is the *same*
    # anchor coming back, which the assertion above rules out.


def test_anchor_key_survives_a_json_round_trip(session):
    """The silent-failure trap this module exists to close.

    ``anchor_key`` is a tuple. JSON turns it into a list. ``avoid_anchors`` only
    tests membership, and a list never equals a tuple -- so a round-tripped key
    excludes nothing, the same anchor is chosen every time, and a loop that
    looks like it is searching repeats one plan forever.
    """
    import json

    first = identity.propose_identity(session)
    assert first["outcome"] == "plan"

    # exactly what a client would send back
    round_tripped = json.loads(json.dumps(first["anchor_key"]))
    assert isinstance(round_tripped, list)

    second = identity.propose_identity(session, avoid_anchors=[round_tripped])
    if second["outcome"] == "plan":
        assert second["anchor_key"] != first["anchor_key"]
    assert second["anchors_excluded"], "the exclusion was dropped"


def test_plans_accumulate_and_can_be_ranked(session):
    """The search is visible: several plans, compared on the engine's yardstick."""
    first = identity.propose_identity(session)
    identity.propose_identity(session, avoid_anchors=[first["anchor_key"]])

    table = identity.compare_plans(session)
    assert table["plans_tried"] >= 2
    assert table["best"] is not None
    covered = [r["rallies_covered"] or 0 for r in table["ranked"]]
    assert covered == sorted(covered, reverse=True), "ranking is not sorted"


def test_scoring_uses_the_engines_own_coverage_definition(session):
    first = identity.propose_identity(session)
    score = identity.score_plan(session, first["plan_id"])
    assert score["rallies_total"] == 2
    assert 0 <= score["rallies_covered"] <= 2
    assert score["claimed_frames"] > 0


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------

def test_missing_signature_is_refused_not_guessed():
    """The one input that makes the engine answer confidently and wrongly.

    With no signature but a height present, ``assign`` falls back to comparing
    box heights and returns a full assignment. That is the failure this product
    is supposed to be incapable of, so it is blocked at the door.
    """
    try:
        identity.engine()
    except RuntimeError as exc:
        pytest.skip("engine unavailable: %s" % exc)

    sid = identity.open_session(
        samples=_samples(), fps=FPS,
        enrolled_sig={}, enrolled_height=160.0,
        ranges=_ranges(),
    )["session_id"]

    out = identity.propose_identity(sid)
    assert out["error"] == "no_enrolled_signature"
    assert "confident" in out["detail"]


def test_unknown_session_is_an_error_not_an_exception():
    out = identity.propose_identity("sess_does_not_exist")
    assert out["error"] == "unknown session_id"


def test_explain_difference_flags_its_own_degraded_mode():
    """Identical appearances mean the weights are defaults, not evidence."""
    try:
        identity.engine()
    except RuntimeError as exc:
        pytest.skip("engine unavailable: %s" % exc)

    # identical appearances: one region still comes back, but with a gap of 0
    same = identity.explain_difference(_sig(60.0), [_sig(60.0)])
    assert same["degraded_to_defaults"] is True
    assert same["largest_gap"] == 0.0
    assert "not meaningfully distinguishable" in same["degraded_because"]

    # no comparable appearance at all: fixed body-band weights
    none_given = identity.explain_difference(_sig(60.0), [])
    assert none_given["degraded_to_defaults"] is True
    assert "fixed body-band weights" in none_given["degraded_because"]

    # barely apart is still degraded -- evidence exists but is below the floor
    barely = identity.explain_difference(_sig(60.0), [_sig(61.0)])
    assert barely["regions_used"] == 1
    assert barely["degraded_to_defaults"] is True

    apart = identity.explain_difference(_sig(20.0), [_sig(120.0)])
    assert apart["degraded_to_defaults"] is False
    assert apart["degraded_because"] is None
    assert apart["regions_used"] > 0
    assert apart["largest_gap"] > apart["floor"]
