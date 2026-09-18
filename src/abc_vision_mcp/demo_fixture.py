# -*- coding: utf-8 -*-
"""The evidence the demo runs on, in one place.

Two things use this: `scripts/demo_agentic_loop.py`, which produces the trace
attached to the submission, and the simulated Alexa+ front end served at `/`.
They must show the same run, or the video and the trace would disagree about
what the engine did — so the fixture lives here rather than in either of them.

It is synthetic, and it is synthetic on purpose. The tools it feeds are the
production ones; what is fabricated is only the *input*, because real input is
a customer's face. A judge should be able to run this without anyone's video
existing anywhere.

The situation it describes is the ordinary one, not a contrived one: three
rallies, and the subject rotates off court for the third while the camera keeps
rolling. No assignment can cover a rally the subject was not in. The loop will
therefore try every anchor available, fail to reach its target, and have to
decide what to do about that — which is the decision worth showing.
"""

from __future__ import annotations

from typing import Any

FPS = 30.0

# Matches core/identity/signature.py: a 10x3 grid down the body, each cell
# carrying [hue, saturation, value]. Two earlier versions of this fixture got
# this wrong in ways the engine accepted -- scalars instead of bands, and then
# four named body parts instead of the grid -- and in both cases it returned
# confident-looking distances computed from nothing. The shape is copied from
# the engine rather than remembered.
REGIONS = ["r%02dc%d" % (r, c) for r in range(10) for c in range(3)]

COVERAGE_TARGET = 3
MAX_ATTEMPTS = 8  # mirrors core/analysis.py MAX_ANCHOR_ATTEMPTS


# Both players wear the club's shorts and their own shirt. That is the ordinary
# case on a club court, and it is also what makes explain_identity_difference
# say anything useful: an earlier version of this fixture coloured each player
# uniformly head to toe, so every region separated them by exactly the same
# amount and "which body regions tell you apart" had no answer worth showing.
SHARED_SHORTS_HUE = 60.0
UPPER_ROWS = 5  # rows 0-4 are shirt, 5-9 are shorts


def _sig(shirt_hue: float, shorts_hue: float = SHARED_SHORTS_HUE) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for r in range(10):
        hue = shirt_hue if r < UPPER_ROWS else shorts_hue
        for c in range(3):
            out["r%02dc%d" % (r, c)] = [hue, 200.0, 180.0]
    return out


def _box(x: float) -> list[float]:
    return [x, 400.0, x + 60.0, 560.0, 0.9]


def _rally(samples: list[list[Any]], frames: range, subject: dict, rival: dict,
           subject_on_court: bool) -> None:
    """Append one rally's sampled frames.

    The only difference between the two cases below is what this is called
    with. Keeping it in one place is the point: if the two fixtures differed
    anywhere else, a reader could fairly ask whether the outcome turned on
    something other than the subject being present.
    """
    for fi in frames:
        rx = 900.0 - (fi % 40) * 2.0
        if subject_on_court:
            sx = 300.0 + (fi % 40) * 2.0
            samples.append([fi, [_box(sx), _box(rx)], [subject, rival],
                            [160.0, 160.0]])
        else:
            samples.append([fi, [_box(rx)], [rival], [160.0]])


# Rally 1 and rally 2 are separated by more than the engine's link window, so
# each is a distinct candidate anchor and ruling one out is a real choice.
RALLIES = (range(0, 41, 2), range(190, 231, 2), range(380, 421, 2))
RANGES = [[0.0, 2.0], [6.3, 2.0], [12.6, 2.0]]


def _fixture(third_rally_has_subject: bool, note: str) -> dict[str, Any]:
    """JSON-serialisable, because the browser is one of the two callers.

    Tuples would survive the Python caller and become arrays over the wire, so
    everything here is already a list — the two callers then send byte-identical
    arguments to the same tools.
    """
    subject, rival = _sig(20.0), _sig(120.0)
    samples: list[list[Any]] = []
    for i, frames in enumerate(RALLIES):
        _rally(samples, frames, subject, rival,
               subject_on_court=(i < 2 or third_rally_has_subject))
    return {
        "samples": samples,
        "fps": FPS,
        "enrolled_sig": subject,
        "enrolled_height": 160.0,
        "rival_sigs": [rival],
        "ranges": RANGES,
        "coverage_target": COVERAGE_TARGET,
        "max_attempts": MAX_ATTEMPTS,
        "note": note,
    }


def evidence() -> dict[str, Any]:
    """The ordinary hard case: the subject sits out the third rally.

    This is the run the submission is built around, because it is the one where
    a measured result changes the next tool call — propose, score, exclude,
    propose again, and finally ask a person.
    """
    return _fixture(
        third_rally_has_subject=False,
        note=("Synthetic input, production tools. Three rallies; the subject "
              "sits out the third. No assignment can cover a rally the subject "
              "was not in."),
    )


def evidence_resolved() -> dict[str, Any]:
    """The ordinary easy case: the subject plays all three rallies.

    Added because the demo previously had only the case above, so a reader who
    watched it once saw the system decline and never saw it do anything else.
    That is a fair thing to hold against a coaching product, and it was not
    what the numbers said: over the production export, jobs that produced a
    report published a level more often than they withheld one.

    It is deliberately *not* a replacement. This run locks on the first attempt
    and excludes nothing, so on its own it would demonstrate no loop at all —
    the branching evidence lives entirely in ``evidence()``. The two belong
    side by side or not at all.
    """
    return _fixture(
        third_rally_has_subject=True,
        note=("Synthetic input, production tools. Same two players, same "
              "signatures, same geometry as the harder case -- the only "
              "difference is that the subject stays on court for all three "
              "rallies."),
    )


CASES = {"unresolved": evidence, "resolved": evidence_resolved}
