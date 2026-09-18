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

## Deployment: EC2 behind CloudFront

**App Runner was the plan and it is not available on this account.** It is
worth recording why, because the reasoning that chose it was sound and the
obstacle had nothing to do with the reasoning.

App Runner was picked for one reason that matters more than elegance: no VPC,
and therefore **no NAT Gateway**. A default CDK `Vpc()` provisions two or three
NAT Gateways at roughly US$65-100/month, which would consume an entire
free-tier credit allowance while doing nothing. App Runner takes a container
and returns an HTTPS URL.

On a newly created account it also returns this:

```
SubscriptionRequiredException when calling CreateService:
The AWS Access Key Id needs a subscription for the service
```

That is account-level, not regional, and not a permissions problem — even
`apprunner list-services` is refused. Lightsail container services, the obvious
substitute, answered `you've either reached or will exceed your maximum limit`:
a quota of zero. Both are managed-container services, and a new account has
that whole category locked. Probing the rest of the account:

| Service | Result |
|---|---|
| App Runner | refused, account not subscribed |
| Lightsail containers | quota 0 |
| ECS | cluster created fine |
| EC2 | `RunInstances` permitted |
| Lambda | works; concurrency quota 10, not the usual 1000 |

So the constraint is real and general, and the fix is to stop asking for a
managed container.

### Why not Lambda

Lambda is free at this traffic and was the first alternative considered. It was
rejected on behaviour, not cost. Five of the fourteen tools are a session:
`open_identity_session` then `propose_identity`, `score_identity_plan`,
`compare_identity_plans`, `explain_identity_difference`. That session lives in
a module-level dict, which survives a warm Lambda sandbox and does not survive
a cold start. The agentic loop is the thing this submission is *about*, and a
version of it that works most of the time and silently forgets the rest of the
time is worse than one that is honestly unavailable.

### What actually runs

```
viewer ──https──> CloudFront ──http:8931──> EC2 t3.micro ──> container ──> ECR (private)
```

- **CloudFront** supplies the HTTPS certificate. A bare EC2 instance cannot get
  one: AWS will not issue a public certificate for `*.compute.amazonaws.com`,
  and there is no domain to use instead. CloudFront's own
  `*.cloudfront.net` certificate solves this at no cost.
- **An Elastic IP** is what makes the origin addressable at all. CloudFront
  origins must be DNS names, not addresses, and an instance's public DNS name
  is derived from its public address — so without an Elastic IP the origin name
  changes every time the instance stops.
- **The security group admits only CloudFront**, via the managed prefix list
  `com.amazonaws.global.cloudfront.origin-facing`. Port 8931 is not open to the
  internet. There is no SSH: port 22 is closed, no key pair exists, and
  administration goes through SSM Session Manager.
- **The instance pulls from a private ECR repository** using an instance role
  with `AmazonEC2ContainerRegistryReadOnly`. The engine slice inside that image
  never leaves the account.

Live: **https://d2xks2we90iwvv.cloudfront.net/mcp**

### The Host header, which is not a footnote

The MCP Python SDK enables DNS rebinding protection automatically — and only
when the bind address is `127.0.0.1`, `localhost` or `::1`. Every container
binds `0.0.0.0`. Measured against this server, same build, changing nothing but
the bind address:

```
bound to 127.0.0.1, Host: attacker.example.com  ->  421 rejected
bound to 0.0.0.0,   Host: attacker.example.com  ->  200 served
```

The protection is present while the server is reachable only by its author and
absent from the moment it is reachable by anyone else, and nothing in the log
marks the transition. This deployment therefore asks for it explicitly:

```
MCP_ALLOWED_HOSTS=ec2-15-135-51-139.ap-southeast-2.compute.amazonaws.com,d2xks2we90iwvv.cloudfront.net
MCP_ALLOWED_ORIGINS=https://d2xks2we90iwvv.cloudfront.net
```

`protocol_info` reports the resulting state, so it can be checked rather than
believed:

```json
"transport_security": {
  "bound_to": "0.0.0.0:8931",
  "dns_rebinding_protection": true,
  "allowed_hosts": ["ec2-15-135-51-139...", "d2xks2we90iwvv.cloudfront.net"]
}
```

`mcp-conformance` gained a `host-header` check for this; it sends one request
carrying a Host nobody serves and reports what came back.

### Steps

The engine slice never touches a developer laptop's Docker daemon or any public
registry. The path is: local bundle → the owner's own private S3 → CodeBuild in
the same account → the owner's own private ECR.

```bash
# 1. Stage the engine slice and zip the build context. Refuses to run if any
#    data file (video, csv, log, admin key) reached the slice.
bash infra/make_bundle.sh

# 2. In CloudShell -- already authenticated, so no access key is ever created.
aws s3 cp abc-vision-mcp-source.zip s3://abc-vision-build-<account>/source.zip
aws codebuild start-build --project-name abc-vision-mcp

# 3. Roll the instance onto the new image. Re-runs the launch script itself,
#    so the running container cannot drift from the launch definition.
aws ssm send-command --instance-ids <id> --document-name AWS-RunShellScript     --parameters commands='bash /var/lib/cloud/instance/scripts/part-001'
```

### Before the first deploy

Four things that are cheap now and expensive to discover later:

1. **A budget.** AWS Budgets, US$50, alerting at 50/80/100% on both actual and
   forecast spend. Do this before anything is running.
2. **Service quotas.** A new account's default limits are low, and some
   services are not available at all — see the table above. Find out by asking
   the API, early, rather than by having a deployment fail.
3. **One region, chosen once.** Mixing regions produces cross-region data
   charges that are small individually and confusing in aggregate.
4. **Log retention.** CloudWatch defaults to never expiring. Set it to 14 days.

### Cost

| Item | Estimate |
|---|---|
| EC2 t3.micro, running continuously | ~US$9.50/month |
| EBS 10 GB gp3 | ~US$1/month |
| Elastic IP, while associated | free |
| CloudFront, within the always-free 1 TB tier | ~US$0 |
| ECR storage, one ~227 MB image | < US$0.10/month |
| CloudWatch logs, 14-day retention | ~US$1-3/month |
| **Total** | **~US$12-14/month** |

Cheaper than the App Runner plan it replaced, against a US$50 budget alarm.
The pursuit of the COOL award, which would have added Graviton instance time,
was dropped for reasons unrelated to cost — see below.

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
