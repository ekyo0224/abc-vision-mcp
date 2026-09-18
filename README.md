# ABC Vision MCP

An MCP server that exposes a production badminton video-analysis engine as
agent tools — and records, at every branch point, how a measured visual result
changed what the system did next.

Built on **OpenCV 5.0.0**. Speaks **MCP over Streamable HTTP**.

---

## Why this exists

ABC (AI Badminton Coach) is a shipping product: an App Store listing, seven
locales, five jurisdictions' privacy compliance, 527 commits, and 1,117
production jobs over the twelve days to 2026-09-17. Its defining behaviour is
that it refuses to answer when it is not sure — across 1,117 real jobs it
declined to assign a skill level in **30.2%** of the analyses that produced a
report, and recorded a human-readable reason each time.

That refusal is not a UI message bolted on at the end. It is the outcome of a
chain of gates, each fed by a measurement from the vision pipeline: was a court
found, did the camera drift, was the player held long enough, were the serves
segmented cleanly. When a gate fails, the system does something different —
retries with a different anchor, asks the player to identify themselves, or
publishes an analysis with the level withheld.

This server makes that chain callable by an agent, and writes down the
reasoning as it goes.

## What is in here

| Path | What it is |
|---|---|
| `src/abc_vision_mcp/trace.py` | Decision trace: tool calls, branch points, and the alternatives not taken |
| `src/abc_vision_mcp/server.py` | The MCP server and its tools |
| `tests/` | Tests, including the redaction properties the trace must hold |
| `data/deidentified/` | Production outcome statistics with every identifier removed |
| `infra/` | AWS deployment |
| `docs/` | Technical report, architecture, evaluation |

## Decisions, not logs

A log of "scan ran, then lock ran" proves nothing — a fixed script produces the
same log. So the trace separates two kinds of record:

- **ToolCall** — what ran, with inputs and outputs. Supporting detail.
- **Decision** — a branch point where a *measured value* selected the next
  action, recorded together with the branches that were **not** taken and the
  rule that maps evidence to branch.

`summary()` reports `branching_decisions` separately from `decisions`, because
a decision with no alternatives did not branch on anything and should not be
presented as if it had.

Example of one real branch, taken from the engine's identity lock
(`core/analysis.py`, `MAX_ANCHOR_ATTEMPTS = 8`): when geometric validation of a
candidate anchor fails, the rejected anchor key is added to an `avoid` set and
the *same tool is called again with different parameters*. The visual result
changed the next tool call. That loop already exists in production; this server
exposes and records it rather than inventing one for a submission.

## Privacy

This repository is built to be handed to competition judges, so it is
structured to make leaking hard rather than to rely on care:

- `.gitignore` is an **allowlist** — everything is ignored, and tracked paths
  are named explicitly. The engine repository used a blocklist, missed five
  directories, and ended up tracking 1,931 data files including customer names
  in filenames. That repository can never be pushed anywhere. This one starts
  from the opposite default.
- The trace redacts by key name, so a field added later called `subject_name`
  is redacted the day it appears. Paths and identifiers become truncated
  SHA-256 handles: stable enough to show two calls hit the same video, useless
  for recovering which video.
- Only de-identified aggregates ship in `data/`. No video, no frames, no
  subject records.
- Redaction is covered by tests, not by convention.

## Requirements

- Python 3.12
- `mcp` 2.2.0 — protocol version `2026-07-28`
- OpenCV 5.0.0 (`opencv-python-headless==5.0.0.93`)

## Running

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m abc_vision_mcp.server --transport streamable-http
```

Tests:

```bash
.venv/Scripts/python -m pytest tests/ -q
```

## Status

Under active development for two 2026 competitions. The trace layer and its
redaction guarantees are complete and tested; the tool surface is being mapped
against the production engine.
