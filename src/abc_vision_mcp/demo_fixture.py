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


def evidence() -> dict[str, Any]:
    """JSON-serialisable, because the browser is one of the two callers.

    Tuples would survive the Python caller and become arrays over the wire, so
    everything here is already a list — the two callers then send byte-identical
    arguments to the same tools.
    """
    subject, rival = _sig(20.0), _sig(120.0)
    samples: list[list[Any]] = []

    # rally 1 (frames 0-40) and rally 2 (frames 190-230): both players on court.
    # The blocks are separated by more than the engine's link window, so each is
    # a distinct candidate anchor and ruling one out is a real choice.
    for fi in list(range(0, 41, 2)) + list(range(190, 231, 2)):
        sx = 300.0 + (fi % 40) * 2.0
        rx = 900.0 - (fi % 40) * 2.0
        samples.append([fi, [_box(sx), _box(rx)], [subject, rival], [160.0, 160.0]])

    # rally 3 (frames 380-420): the subject is off court, only the rival plays.
    for fi in range(380, 421, 2):
        rx = 900.0 - (fi % 40) * 2.0
        samples.append([fi, [_box(rx)], [rival], [160.0]])

    return {
        "samples": samples,
        "fps": FPS,
        "enrolled_sig": subject,
        "enrolled_height": 160.0,
        "rival_sigs": [rival],
        "ranges": [[0.0, 2.0], [6.3, 2.0], [12.6, 2.0]],
        "coverage_target": COVERAGE_TARGET,
        "max_attempts": MAX_ATTEMPTS,
        "note": (
            "Synthetic input, production tools. Three rallies; the subject "
            "sits out the third. No assignment can cover a rally the subject "
            "was not in."
        ),
    }
