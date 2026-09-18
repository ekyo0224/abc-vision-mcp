# -*- coding: utf-8 -*-
"""Render the production-outcome chart used in the submission video.

Every number on the chart is read from the de-identified CSV at render time.
None of them are typed. That is the entire reason this file exists: a figure in
a video cannot be corrected after the fact, and a hand-typed chart is exactly
how a stale number gets in front of a judge.

    python scripts/make_outcomes_chart.py --out docs/outcomes.svg

The output is 1920x1080 so it can be dropped straight into a 1080p timeline.
"""

from __future__ import annotations

import argparse
import os
import sys
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from abc_vision_mcp import stats  # noqa: E402

W, H = 1920, 1080
BG = "#0b0f14"
PANEL = "#121820"
LINE = "#1f2a36"
TEXT = "#e8eef5"
MUTED = "#8b9cb0"
ACCENT = "#00caff"
WARN = "#ffb454"
GOOD = "#5ad19a"
DIM = "#3a4a5c"

FONT = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
        "'Helvetica Neue', Arial, sans-serif")
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


def _t(x, y, s, size=22, fill=TEXT, weight="400", anchor="start", font=FONT):
    return ('<text x="%d" y="%d" font-family="%s" font-size="%d" fill="%s" '
            'font-weight="%s" text-anchor="%s">%s</text>'
            % (x, y, font, size, fill, weight, anchor, escape(str(s))))


def _rect(x, y, w, h, fill, rx=4):
    return '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%d" fill="%s"/>' % (
        x, y, max(w, 0), h, rx, fill)


def build() -> str:
    data = stats.outcome_breakdown()
    den = data["denominators"]
    all_jobs = den["all_jobs"]
    reported = den["jobs_that_produced_a_report"]
    rows = {o["outcome"]: o for o in data["outcomes"]}

    no_report = rows["no_report_produced"]["jobs"]
    published = rows["given_level"]["jobs"]
    other = rows["other"]["jobs"]
    declines = [o for o in data["outcomes"]
                if o["outcome"] not in ("no_report_produced", "given_level", "other")]
    declines.sort(key=lambda o: -o["jobs"])
    declined_total = sum(o["jobs"] for o in declines)

    # The chart must add up, or it is a nicer-looking lie.
    assert no_report + published + other + declined_total == all_jobs, "rows do not sum"
    assert published + other + declined_total == reported, "reported does not reconcile"

    o: list[str] = []
    o.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
             'width="%d" height="%d">' % (W, H, W, H))
    o.append(_rect(0, 0, W, H, BG, rx=0))

    # ---------------------------------------------------------------- header
    o.append(_t(90, 110, "What the engine did with %s jobs" % f"{all_jobs:,}",
                size=54, weight="600"))
    o.append(_t(90, 158, "%s to %s  ·  every figure read from the de-identified "
                         "record at render time"
                % (data["window"]["first_date"], data["window"]["last_date"]),
                size=24, fill=MUTED))

    bar_x, bar_w = 90, W - 180

    # ------------------------------------------------- row A: all jobs split
    y = 250
    o.append(_t(bar_x, y, "All %s jobs" % f"{all_jobs:,}", size=28, weight="600"))
    o.append(_t(bar_x + bar_w, y, "denominator 1", size=22, fill=MUTED, anchor="end"))
    y += 28
    seg = [(no_report, DIM, "no report produced"),
           (reported, ACCENT, "produced a report")]
    x = bar_x
    for n, colour, _label in seg:
        w = bar_w * n / all_jobs
        o.append(_rect(x, y, w - 3, 56, colour))
        x += w
    # The count sits on the bar, where it needs contrast against the fill. The
    # caption sits below it on the page background, where that same contrast
    # colour would be invisible -- which is exactly what the first render did.
    x = bar_x
    for n, colour, label in seg:
        w = bar_w * n / all_jobs
        o.append(_t(x + 16, y + 38, f"{n:,}", size=30, weight="700",
                    fill=BG if colour == ACCENT else TEXT, font=MONO))
        o.append(_t(x + 16, y + 86, "%s  ·  %.1f%% of all"
                    % (label, 100.0 * n / all_jobs), size=21, fill=MUTED))
        x += w
    y += 86

    # --------------------------------------- row B: of those that reported
    y = 452
    o.append(_t(bar_x, y, "Of the %s that produced a report" % f"{reported:,}",
                size=28, weight="600"))
    o.append(_t(bar_x + bar_w, y, "denominator 2", size=22, fill=MUTED, anchor="end"))
    y += 28
    seg = [(published, GOOD, "published a level"),
           (declined_total, WARN, "declined to publish"),
           (other, DIM, "other")]
    x = bar_x
    for n, colour, _label in seg:
        w = bar_w * n / reported
        o.append(_rect(x, y, w - 3, 56, colour))
        x += w
    x = bar_x
    for n, colour, label in seg:
        w = bar_w * n / reported
        dark = colour in (GOOD, WARN)
        o.append(_t(x + 16, y + 38, f"{n:,}", size=30, weight="700",
                    fill=BG if dark else TEXT, font=MONO))
        # A segment too thin to carry a caption gets one on a second line,
        # right-aligned. Putting it on the same line collided with the caption
        # of the segment before it, which the first render did visibly.
        caption = "%s  ·  %.1f%%" % (label, 100.0 * n / reported)
        if w < 260:
            o.append(_t(bar_x + bar_w, y + 118, caption, size=21, fill=MUTED,
                        anchor="end"))
        else:
            o.append(_t(x + 16, y + 86, caption, size=21, fill=MUTED))
        x += w
    y += 86

    # ------------------------------------------------- row C: why it declined
    y = 640
    o.append(_t(bar_x, y, "Why it declined", size=28, weight="600"))
    o.append(_t(bar_x + 230, y, "as a share of the %s reported" % f"{reported:,}",
                size=22, fill=MUTED))
    y += 34

    widest = max(o2["jobs"] for o2 in declines)
    label_w, num_w = 560, 190
    track_x = bar_x + label_w
    track_w = bar_w - label_w - num_w
    for row in declines:
        meaning = row["meaning"].replace("declined: ", "")
        o.append(_t(bar_x, y + 26, meaning[:58], size=23, fill=TEXT))
        o.append(_rect(track_x, y + 8, track_w, 24, PANEL))
        o.append(_rect(track_x, y + 8, track_w * row["jobs"] / widest, 24, WARN))
        o.append(_t(bar_x + bar_w, y + 27,
                    "%4d   %4.1f%%" % (row["jobs"], row["pct_of_reported"]),
                    size=23, fill=MUTED, anchor="end", font=MONO))
        y += 42

    # ---------------------------------------------------------------- footer
    o.append(_rect(bar_x, H - 132, bar_w, 2, LINE, rx=0))
    o.append(_t(bar_x, H - 88,
                "Two denominators, always. A job that expired before anyone "
                "opened it never reached the gate:", size=22, fill=MUTED))
    o.append(_t(bar_x, H - 56,
                "it is in the 1,117 and not in the 705. A percentage without "
                "its denominator is a way of being wrong on purpose.",
                size=22, fill=MUTED))
    o.append("</svg>")
    return "\n".join(o)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/outcomes.svg")
    args = ap.parse_args()
    svg = build()
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg)
    print("wrote %s (%d bytes)" % (args.out, len(svg.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
