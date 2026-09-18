# -*- coding: utf-8 -*-
"""The trace goes to competition judges, so redaction is tested, not assumed.

The failure this file exists to prevent: a real customer name, a video path, or
a device id reaching a file that gets attached to a submission.

The fixtures below use 張三 / 李四 / 王五 -- the Chinese equivalent of John Doe.
An earlier version of this file used real customer names taken from the engine's
own archives, on the reasoning that they were the realistic thing to test
against. They were, and that was the wrong call: pushing this file would have
put those names on GitHub, which is the exact outcome the redaction it tests is
meant to prevent.

The main engine repository already learned this the hard way -- 1,931 tracked
data files, customer names in filenames, a live admin key in version control --
so here the property is checked rather than trusted.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from abc_vision_mcp.trace import DecisionTrace, redact  # noqa: E402


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------

def test_sensitive_keys_are_never_echoed():
    dirty = {
        "video_path": r"D:\videos\0726 張三 vs 李四_1080p60.mp4",
        "subject_id": "player-8871",
        "email": "someone@example.com",
        "device_id": "A1B2C3",
        "token": "sk-live-abcdef123456",
        "rally_count": 12,
    }
    clean = redact(dirty)

    blob = json.dumps(clean, ensure_ascii=False)
    for leaked in ("張三", "李四", "player-8871", "someone@example.com",
                   "A1B2C3", "sk-live-abcdef123456"):
        assert leaked not in blob, "leaked %r" % leaked

    # non-sensitive values survive, or the trace would be useless
    assert clean["rally_count"] == 12


def test_same_input_gives_same_handle():
    """Judges must be able to see two calls hit the same video."""
    a = redact({"video_path": "/x/game.mp4"})["video_path"]
    b = redact({"video_path": "/x/game.mp4"})["video_path"]
    c = redact({"video_path": "/x/other.mp4"})["video_path"]
    assert a == b
    assert a != c
    assert a.startswith("sha256:")


def test_nested_sensitive_keys_are_caught():
    clean = redact({"meta": {"inner": {"subject": "王五", "ok": True}}})
    assert "王五" not in json.dumps(clean, ensure_ascii=False)
    assert clean["meta"]["inner"]["ok"] is True


def test_unserialisable_values_are_summarised_not_dropped():
    class Fake:
        shape = (3, 4)

    out = redact({"frame": Fake(), "obj": object()})
    assert out["frame"] == {"_type": "Fake", "shape": [3, 4]}
    assert out["obj"]["_type"] == "object"


def test_long_lists_are_truncated_with_a_visible_marker():
    out = redact(list(range(200)))
    assert len(out) == 51
    assert "more" in str(out[-1])


# --------------------------------------------------------------------------
# Decisions
# --------------------------------------------------------------------------

def _trace_with_one_branch() -> DecisionTrace:
    t = DecisionTrace(subject="player-1")
    t.tool_call("court_locate", {"video_path": "/x/a.mp4"},
                {"found": True, "reproj_error_px": 2.3})
    t.decision(
        node="COURT_GATE",
        evidence_from="court_locate",
        evidence={"found": True, "reproj_error_px": 2.3},
        rule="reproj_error_px <= 6.0 -> continue; otherwise stop",
        chose="continue",
        alternatives=["stop_unsuitable", "request_manual_court"],
        consequence="scan runs over the full clip",
    )
    return t


def test_summary_counts_only_real_branches():
    t = _trace_with_one_branch()
    t.decision(
        node="NO_CHOICE", evidence_from="court_locate", evidence={},
        rule="always", chose="only_path", alternatives=[],
        consequence="nothing else could have happened",
    )
    s = t.summary()
    assert s["decisions"] == 2
    # a decision with no alternatives did not branch and must not be counted
    assert s["branching_decisions"] == 1


def test_human_approval_is_counted_separately():
    t = _trace_with_one_branch()
    t.decision(
        node="IDENTITY_GATE",
        evidence_from="identity_lock",
        evidence={"locked": False, "attempts": 8},
        rule="locked is False after MAX_ANCHOR_ATTEMPTS -> ask the player",
        chose="request_human_pick",
        alternatives=["retry_with_new_anchor", "withhold_level"],
        consequence="job moves to needs_pick and waits for the player",
        human_approval_requested=True,
    )
    assert t.summary()["human_approval_requests"] == 1


def test_recorder_never_raises_on_bad_input():
    """An analysis must not die because logging choked."""
    t = DecisionTrace()

    class Hostile:
        def __repr__(self):
            raise RuntimeError("boom")

    t.tool_call("x", {"a": Hostile()}, Hostile())
    t.decision("N", "x", {"v": Hostile()}, "r", "c", ["d"], "e")
    assert isinstance(t.summary(), dict)


def test_written_file_is_valid_json_and_carries_no_names(tmp_path):
    t = _trace_with_one_branch()
    t.tool_call("identity_lock", {"subject_hint": "李四"}, {"locked": True})
    path = t.write(str(tmp_path))
    assert path is not None

    text = Path(path).read_text(encoding="utf-8")
    assert "李四" not in text
    assert "player-1" not in text
    payload = json.loads(text)
    assert payload["schema"] == "abc_vision_mcp/decision_trace/v1"
    assert payload["summary"]["branching_decisions"] == 1
