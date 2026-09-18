# -*- coding: utf-8 -*-
"""The demo is a submission artefact, so it is tested like one.

``scripts/demo_agentic_loop.py`` produces the trace a judge opens. If it ever
stops branching -- because a threshold moved, or the fixture drifted, or the
engine changed which anchor it prefers -- the trace would still be produced and
would still look plausible, while no longer demonstrating anything. That is the
failure this file exists to catch.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from abc_vision_mcp import identity  # noqa: E402


@pytest.fixture(scope="module")
def demo_trace(tmp_path_factory):
    try:
        identity.engine()
    except RuntimeError as exc:
        pytest.skip("engine unavailable: %s" % exc)

    out = tmp_path_factory.mktemp("traces")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "demo_agentic_loop.py"),
         "--out", str(out)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, (
        "demo exited %d\nstdout:\n%s\nstderr:\n%s"
        % (proc.returncode, proc.stdout, proc.stderr)
    )
    files = list(out.glob("*.json"))
    assert len(files) == 1, "expected one trace, got %d" % len(files)
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_the_loop_actually_branched(demo_trace):
    """The claim the submission rests on, checked on the artefact itself."""
    summary = demo_trace["summary"]
    assert summary["branching_decisions"] >= 2, (
        "the demo recorded %d branching decision(s); a trace with fewer than "
        "two does not show a search" % summary["branching_decisions"]
    )
    assert summary["tool_calls_failed"] == 0


def test_every_decision_names_its_evidence_and_its_alternatives(demo_trace):
    """A decision missing either half is not evidence of anything."""
    decisions = [r for r in demo_trace["records"] if r["kind"] == "decision"]
    assert decisions
    for d in decisions:
        assert d["evidence"], "%s recorded no evidence" % d["node"]
        assert d["evidence_from"], "%s does not say which tool measured it" % d["node"]
        assert d["rule"], "%s has no rule a judge could re-apply" % d["node"]
        assert d["alternatives"], (
            "%s had no alternatives, so nothing was actually decided" % d["node"]
        )


def test_a_measured_value_changed_the_next_tool_call(demo_trace):
    """The specific thing the rules ask to see.

    Two coverage decisions in a row must name different anchors: the first
    plan's anchor was excluded because of what was measured, so the second plan
    had to anchor elsewhere. Identical anchors would mean the exclusion did
    nothing.
    """
    anchors = [
        d["evidence"].get("anchor_key")
        for d in demo_trace["records"]
        if d.get("kind") == "decision" and d.get("node") == "COVERAGE_GATE"
    ]
    anchors = [a for a in anchors if a]
    assert len(anchors) >= 2, "only %d coverage decision(s) recorded" % len(anchors)
    assert anchors[0] != anchors[1], (
        "the same anchor %r was chosen after being excluded" % (anchors[0],)
    )


def test_running_out_of_options_asks_a_person(demo_trace):
    """The rules count a request for human approval as a qualifying action."""
    assert demo_trace["summary"]["human_approval_requests"] >= 1
    asks = [
        d for d in demo_trace["records"]
        if d.get("kind") == "decision" and d.get("human_approval_requested")
    ]
    assert asks
    # publishing a best-effort guess must be visibly on the table and rejected,
    # otherwise the refusal is not a choice
    assert any("publish_best_effort" in d["alternatives"] for d in asks)


def test_the_trace_carries_nothing_identifying(demo_trace):
    blob = json.dumps(demo_trace, ensure_ascii=False)
    for leak in (".mp4", ".mov", "@", "D:\\", "/Users/"):
        assert leak not in blob, "trace contains %r" % leak
