# -*- coding: utf-8 -*-
"""The demo surface is a submission artefact, so its shape is pinned.

Two failures this file exists to prevent, both of which have already happened
once during this build:

1. **The fixture drifting out of the engine's signature format.** An earlier
   version used scalars where the engine wants ``[hue, saturation, value]``
   bands; a later one used four named body parts where the engine wants a 10x3
   grid. The engine accepted both and returned confident-looking distances
   computed from nothing. Nothing failed. The numbers were just wrong.

2. **The page not being in the image.** ``/`` is served from a file inside the
   package. A build that copies ``src/`` but loses ``web/index.html`` starts
   normally, serves MCP correctly, and shows a judge a plain-text apology.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from abc_vision_mcp import demo_fixture  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# The fixture
# --------------------------------------------------------------------------

def test_signatures_are_the_grid_the_engine_expects():
    f = demo_fixture.evidence()
    for name in ("enrolled_sig", *(("rival_sigs",) if f["rival_sigs"] else ())):
        sigs = f[name] if name != "rival_sigs" else f["rival_sigs"]
        for sig in (sigs if isinstance(sigs, list) else [sigs]):
            assert len(sig) == 30, "%s: expected a 10x3 grid, got %d" % (name, len(sig))
            assert set(sig) == set(demo_fixture.REGIONS)
            for key, band in sig.items():
                assert isinstance(band, list) and len(band) == 3, \
                    "%s[%s] is not a [hue, sat, val] band" % (name, key)


def test_the_two_players_are_separable_but_only_partly():
    """Same shorts, different shirts -- which is what makes the demo honest.

    If every region separated them, 'where you two actually differ' would show
    ten identical full bars and say nothing. If none did, the engine would fall
    back to default weights and the demo would be built on a degraded result.
    """
    f = demo_fixture.evidence()
    subject, rival = f["enrolled_sig"], f["rival_sigs"][0]
    differing = [k for k in demo_fixture.REGIONS if subject[k][0] != rival[k][0]]
    assert differing, "the players are identical; the engine would degrade"
    assert len(differing) < len(demo_fixture.REGIONS), \
        "every region differs; the difference explanation would be uninformative"


def test_the_fixture_is_json_serialisable_exactly_as_sent():
    """The browser and the demo script must send byte-identical arguments.

    Tuples survive the Python caller and silently become arrays over the wire,
    which is how the two callers drift apart.
    """
    f = demo_fixture.evidence()
    round_tripped = json.loads(json.dumps(f))
    assert round_tripped == f


def test_the_subject_is_absent_from_one_rally():
    """The demo's whole point is a rally no assignment can cover."""
    f = demo_fixture.evidence()
    assert len(f["ranges"]) == 3
    # the last block of samples carries a single detection, not two
    assert len(f["samples"][-1][1]) == 1
    assert f["coverage_target"] == len(f["ranges"])


# --------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------

def test_the_page_ships_with_the_package():
    page = ROOT / "src" / "abc_vision_mcp" / "web" / "index.html"
    assert page.is_file(), "the demo page is not where the server looks for it"
    html = page.read_text(encoding="utf-8")
    assert len(html) > 4000
    # it has to reach the MCP endpoint and the fixture route, or it renders an
    # empty conversation and no error
    assert "demo/fixture" in html
    assert '"mcp"' in html or "/mcp" in html


def test_the_page_says_the_conversation_is_staged():
    """The organisers do not require it. This project does."""
    html = (ROOT / "src" / "abc_vision_mcp" / "web" / "index.html").read_text(
        encoding="utf-8")
    assert "staged" in html.lower()


# --------------------------------------------------------------------------
# The two cases shown side by side
# --------------------------------------------------------------------------

def test_the_two_cases_differ_only_in_the_third_rally():
    """The comparison is worthless if anything else changed.

    A reader is being asked to accept that the outcome turned on whether the
    subject was on court. That only holds if the two fixtures are otherwise
    byte-identical, so this asserts it rather than trusting the constructor.
    """
    hard = demo_fixture.evidence()
    easy = demo_fixture.evidence_resolved()

    for key in ("fps", "enrolled_sig", "enrolled_height", "rival_sigs",
                "ranges", "coverage_target", "max_attempts"):
        assert hard[key] == easy[key], "%s differs between the two cases" % key

    # same number of sampled frames, and identical up to the third rally
    assert len(hard["samples"]) == len(easy["samples"])
    third = [i for i, s in enumerate(hard["samples"]) if s[0] >= 380]
    first_third = third[0]
    assert hard["samples"][:first_third] == easy["samples"][:first_third]

    # the third rally is where they part: one detection versus two
    assert all(len(s[1]) == 1 for s in hard["samples"][first_third:])
    assert all(len(s[1]) == 2 for s in easy["samples"][first_third:])


def test_both_cases_are_reachable_by_name():
    assert set(demo_fixture.CASES) == {"resolved", "unresolved"}
    assert demo_fixture.CASES["unresolved"]() == demo_fixture.evidence()
    assert demo_fixture.CASES["resolved"]() == demo_fixture.evidence_resolved()


def test_the_page_runs_both_cases():
    """Regression guard for the reason the second case exists.

    The page shipped for a while showing only the declining run, so a reader
    who watched it once saw the system refuse and never saw it do anything
    else. If either case stops being requested, that is back.
    """
    html = (ROOT / "src" / "abc_vision_mcp" / "web" / "index.html").read_text(
        encoding="utf-8")
    assert 'run("resolved")' in html
    assert 'run("unresolved")' in html


def test_the_page_does_not_put_a_level_on_screen():
    """No tool on this surface returns one.

    The success run is the tempting place to invent a number, because a coach
    that says "found you" and stops feels unfinished. It has to stay unfinished
    until the level comes from a call.
    """
    html = (ROOT / "src" / "abc_vision_mcp" / "web" / "index.html").read_text(
        encoding="utf-8")
    flat = re.sub(r"\s+", " ", html)
    assert "computed downstream" in flat, (
        "the success run no longer explains why it shows no level"
    )
    # Word boundaries, not substrings: an earlier version of this test matched
    # "rating" inside "separating" and failed on correct markup.
    for invented in (r"your level is", r"\blevel\s+\d", r"\bgrade\s+\d",
                     r"\brating\s+\d", r"\bLevel:\s*\d"):
        assert not re.search(invented, flat, re.I), (
            "a level appears on the page but no tool returns one: %r" % invented
        )
