# Corrections

Things this project stated and then found to be wrong. They are kept because a
submission that only records its successes is not evidence of anything, and
because in both cases the error was caught by a tool built for the purpose —
which is the actual claim being made here.

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
