# Running this on AWS

The OpenCV AI Competition 2026 requires every entry to "use OpenCV 5 for
substantive image or video analysis and run a meaningful component on AWS".
This document is how that component is deployed, what it costs, and what is
deliberately not on AWS.

---

## What runs there

The **rally detection pass** — the engine's `core/scan.py`, over OpenCV 5.

It is the right piece to move for reasons that are structural rather than
convenient:

- It is the only pass that touches every sampled frame of the video. At
  `STRIDE_SEC = 0.12`, an eight-minute clip is roughly 4,000 rounds of decode →
  `resize(INTER_AREA)` → `cvtColor(BGR2GRAY)` → background stack →
  `connectedComponentsWithStats`. If anything in this product is "substantive
  video analysis", it is this.
- Its output **is a plan**: the rally list decides which stretches of video
  every later stage looks at. A visual result choosing where the next stage
  runs is the shape the Agentic Vision criterion asks for, and it was already
  the architecture.
- It imports `cv2`, `numpy` and the standard library. Nothing else. No PyTorch,
  no ONNX Runtime, no MediaPipe. That is what makes the image ~200 MB.

## What does not run there, and why

| Stage | Why it stays local |
|---|---|
| Pose (`core/pose/`) | MediaPipe. Large, and its arm64 story is unresolved — see the open question below. |
| Serve segmentation | 53.8% of total runtime, and measured to be 93.1% MediaPipe + YOLO. Moving it buys cloud cost, not cloud value. |
| Identity lock | Needs the frozen ranker and the enrolled player's appearance. Runs where the video already is. |

Saying this plainly is the point. An architecture diagram that showed
everything on AWS would be easier to draw and would not be true.

---

## Deployment: App Runner

App Runner rather than ECS or EKS, for one reason that matters more than
elegance: **no VPC, and therefore no NAT Gateway**. A default CDK `Vpc()`
provisions two or three NAT Gateways at roughly US$65–100/month, which would
consume the entire free-tier credit allowance while doing nothing. App Runner
takes a container and returns an HTTPS URL.

That URL is also what the submission checklist calls "a working web endpoint".

### Steps

```bash
# 1. Build. Stages the engine slice, then builds the image.
bash infra/build.sh

# 2. Push to ECR (one-time repository creation shown).
aws ecr create-repository --repository-name abc-vision-mcp
aws ecr get-login-password | docker login --username AWS --password-stdin \
    <account>.dkr.ecr.<region>.amazonaws.com
bash infra/build.sh --push <account>.dkr.ecr.<region>.amazonaws.com/abc-vision-mcp:v1

# 3. Create the App Runner service pointing at that image, port 8931.
```

### Before the first deploy

Four things that are cheap now and expensive to discover later:

1. **A budget.** AWS Budgets, US$50, alerting at 50/80/100% on both actual and
   forecast spend. Do this before anything is running.
2. **Service quotas.** A new account's default limits are low. If a later stage
   fans out, the request to raise them takes 24–48 hours to approve — so file
   it early even if it is not needed yet.
3. **One region, chosen once.** Mixing regions produces cross-region data
   charges that are small individually and confusing in aggregate.
4. **Log retention.** CloudWatch defaults to never expiring. Set it to 14 days.

### Cost

| Item | Estimate |
|---|---|
| App Runner, 1 vCPU / 2 GB, mostly idle | ~US$5–15/month |
| ECR storage, one ~200 MB image | < US$0.10/month |
| CloudWatch logs, 14-day retention | ~US$1–3/month |
| S3, if video upload is added | ~US$2/month |
| **Total** | **~US$10–20/month** |

Against US$200 of new-account credit. The pursuit of the COOL award, which
would have added Graviton instance time, was dropped for reasons unrelated to
cost — see below.

---

## Observability

CloudWatch gets structured JSON, one line per stage, using **the same stage
names the local engine writes to `data/stats/timings.jsonl`**:
`queue_wait`, `model_load`, `scan`, `serve_split`, `subject_lock`, `analyze`,
`report_build`, `draft`.

Same names on both sides means cloud and local timings can be compared directly
rather than approximately — which is the only way to answer "is it slower up
there, and where".

---

## The open question: Graviton

The Best Use of COOL award needs COOL executing the core workload on Graviton
or the Arm side of a documented hybrid. This entry does not pursue it, and the
reason is worth recording because it is a measurement, not a preference.

`core/scan.py:548-551` documents a regression from 2026-08-19:

> ffmpeg-side scaling shifted pixels by a mean 2.1/255 and the frozen ranker
> flipped rally verdicts on all three test videos.

The ranker in `models/ranker_arm_c.npz` was trained and frozen on pixels
produced by stock OpenCV's `INTER_AREA`. COOL's headline optimisations are
`resize` and `cvtColor` — precisely the two operations a 2.1/255 difference
already proved this model is sensitive to. The engine's own benchmarking
harness states the principle:

> A speedup that changed the answer is not a speedup, it is a regression with
> good timing.

Profiling separately showed COOL could reach roughly 3–6% of end-to-end
runtime, because the dominant cost is MediaPipe pose and YOLO detection, which
COOL does not touch. High risk of changing the answer, in exchange for a small
share of the runtime.

A second, unresolved question sits behind it: whether MediaPipe publishes an
arm64 wheel. Two independent reviews of this codebase disagreed on the answer,
which is why `mediapipe` is excluded from the container rather than assumed
either way. The scan path does not need it, so the image ships without it and
the question stays open rather than being answered by guesswork.
