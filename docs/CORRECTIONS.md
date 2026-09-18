# Corrections

Things this project stated and then found to be wrong. They are kept because a
submission that only records its successes is not evidence of anything.

The first three were caught by tooling built for the purpose. The fourth was
not: it was caught by people reading the claim against the data, after it had
already shipped. That distinction is left visible rather than smoothed over,
because "our tools catch our mistakes" is a weaker statement than it looks if
the worst one got past them.

---

## 1. The protocol version was overstated

**Claimed:** the server speaks MCP `2026-07-28`.
**True:** `initialize` negotiates `2025-11-25`.

Two version numbers live in the SDK and they are easy to conflate:

| Constant | Value | What it is |
|---|---|---|
| `LATEST_HANDSHAKE_VERSION` | `2025-11-25` | what `initialize` agrees with a client |
| `LATEST_PROTOCOL_VERSION` | `2026-07-28` | the transport revision |

The second is always the higher number, which makes it the tempting one to
quote. It is not the protocol version. The Alexa+ track asks for "spec
2025-11-25 or later", so the correct figure satisfies the requirement anyway —
the overstatement bought nothing and would have been a misrepresentation of
capabilities.

It was caught by `mcp-conformance`, this project's own checker, reporting the
negotiated version against a running server while the draft report said
otherwise. It had been written into five places; all five were corrected.

`protocol_info` now returns both numbers with a note saying which is which, so
the confusion cannot survive a single tool call.

---

## 2. DNS rebinding protection was assumed, and was off

**Assumed:** the SDK's DNS rebinding protection defaults to on.
**True:** it defaults to on *only* when bound to loopback, which is never how a
container runs.

Reading `TransportSecurityMiddleware.__init__` suggests protection is off by
default. Reading `Server.streamable_http_app` suggests it is on. Both are
partly right, and neither tells you what your deployment does. Measured
instead, same build, same code path, changing only the bind address:

```
bound to 127.0.0.1, Host: attacker.example.com  ->  421 rejected
bound to 0.0.0.0,   Host: attacker.example.com  ->  200 served
```

The protection is present while the server is reachable only by the person
writing it, and gone from the moment it is reachable by everyone else. Nothing
in the log marks the transition.

This was found before the first public deployment, not after, and it changed
three things:

1. The server takes `--allowed-host` / `--allowed-origin` (and
   `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS`), and prints a warning naming
   the consequence when it binds a public interface without them.
2. `protocol_info` reports the resulting state — bind address, whether
   protection is on, and the allowlists — so a deployment can be checked
   rather than believed.
3. `mcp-conformance` gained a `host-header` check that sends one request
   carrying a Host nobody serves. It reports an acceptance as a warning and a
   refusal as a pass, while saying plainly that from outside the tool cannot
   tell a refusing server from a refusing CDN.

The general form of this is the reason the conformance tool exists: the
question is never what the source says, it is what the running server does.

---

## 3. A profiler reported 0% and the 0% was fabricated

An early run of `cv2_op_profile.py` reported that OpenCV accounted for 0% of
scan time. It had failed to instrument anything:
`cv2.VideoCapture.read` is read-only and the `setattr` silently did nothing, so
the profiler measured its own empty hooks.

Replaced with a `_TimedCapture` proxy. The corrected measurement is 77% for the
scan phase — which is a different conclusion entirely, and one that was then
used to *decline* the COOL award rather than pursue it, because the phase that
dominates the whole job is 93% MediaPipe and YOLO rather than OpenCV.

The false 0% had already been reported to the working group before it was
found. It was corrected there too.

---

## 4. The failure-cases section contained the project's worst claim

**Claimed:** of the uploads whose identity request went unanswered, "half of
them are five minutes or longer — *the length that most often yields a level*".
**True:** in the shipped export, five minutes or longer is the length band that
has never yielded one.

| Video length | Produced a report | Yielded a level |
|---|---:|---:|
| 60–120 s | 291 | 261 |
| 120–180 s | 75 | 62 |
| 180–300 s | 10 | 3 |
| **300 s and over** | **10** | **0** |

The 390 jobs that did yield a level ran a median of 85.1 s and a maximum of
194.4 s. Not one reached five minutes.

This is the worst error in the project's history for three reasons. It was a
statement about our own failure handling, in the section whose entire purpose
is not overstating. The data that refutes it is
`data/deidentified/production_outcomes_deidentified_20260918.csv`, shipped in
this repository. And `human_approval_dropoff` — which the submission's own
testing instructions tell a judge to call — returned the sentence directly from
the server.

A second claim in the same passage was withdrawn at the same time: "the
perception worked; the hand-off to a human did not." That was never measured.
Those 110 jobs produced no report, so the identity work on them was never
scored; the loop asked for help precisely because it could not resolve identity
alone. Asserting the vision succeeded reversed an "I am not sure" into an "I am
sure", which is the exact move this project exists to refuse.

### How it was found, and what that says

Not by a tool. By reviewers reading the claim against the export.

The correction then had to be made four times, because the first three attempts
each replaced the overstatement with a new one:

| Attempt | What was still wrong |
|---|---|
| 1 | "no upload has ever yielded a level" — true, but stated without the denominator of ten |
| 1 | "the two failures compound each other" — an interaction nobody had tested |
| 2 | kept "the perception worked" |
| 3 | "what we can say is *why* the request never arrived" — causation, again unmeasured |

Each was caught by a different reader. The pattern is more informative than any
single sentence: the impulse was to extract one more conclusion than the data
carried, and it survived three deliberate attempts to remove it.

The number in the final wording was dropped for the same reason. "The app had
four notification types" turned out to depend on whether a two-variant
`finished` notification counts as one type or two — 4 or 5, depending on how
you count. The substantive point held either way (none of them covered "ready
for you to pick"), so the count came out and the claim stayed.

### What changed structurally

The sentence was a fixed string sitting beside numbers it never consulted, so
it could not fail any other way. It is now composed from those numbers, three
of which are newly reported so a reader can check the claim from the same tool
call:

```
long_uploads_in_export                68
long_uploads_that_produced_a_report   10
long_uploads_that_yielded_a_level      0
```

Two regression tests guard it: one asserts every quantity in the prose appears
in the payload, the other asserts the withdrawn phrasings never return.

### Six copies, and the counting was wrong four times

The claim was not in one place. Each time it was declared cleaned up, someone
found another copy:

| Found | Where |
|---|---|
| 1–2 | the tool's `reading`, and the Devpost description |
| 3 | the technical report |
| 4 | a test's own docstring — in the file meant to catch this |
| 5 | two title cards in the submission video, one of them italicised |
| 6 | the tool's **description** — what `tools/list` returns, so the first thing a reader sees |

The sixth is the one worth recording. It survived a deploy *and* the regression
test written specifically to prevent it, because that test checked the
`reading` field and nothing else. A guard scoped to the place the bug was found
is not a guard against the bug; it is a guard against that transcript. The test
now walks every surface a reader can reach — all fourteen tool descriptions and
titles, the server instructions, and every prose field the stats tools return —
and was verified to flag the old text before it was fixed.

The same review turned up two more of the same species: the README reported the
decline rate as 30.2%, which is one reason of six rather than the 42.7% total,
and the module docstring still called 2026-07-28 a protocol version — inside
the very file that correction #1 above is about.

None of the six was found by tooling. All six were found by people reading a
claim against the data, and on four occasions the person doing the declaring
that it was all clean was the same one who had missed the next copy. That
pattern is more useful to a reader of this file than the sentence was.
