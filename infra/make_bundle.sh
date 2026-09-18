#!/usr/bin/env bash
# Build the source bundle CodeBuild will compile, without needing Docker.
#
# The bundle is the repository plus the engine slice. It is uploaded to a
# private S3 bucket in the owner's own AWS account, so the engine is never in
# the GitHub repository (where competition reviewers can see it) and never in
# a public registry.
#
#   bash infra/make_bundle.sh
#   -> infra/dist/abc-vision-mcp-source.zip
#
# Then, from AWS CloudShell (which is already authenticated, so no access keys
# ever leave the machine):
#   aws s3 cp abc-vision-mcp-source.zip s3://<bucket>/source.zip
#
# Requires: python (for zipping). No Docker, no AWS CLI locally.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="${ABC_ENGINE_PATH:-/d/BADMINTON_COACH_APP_V1}"
SLICE="$ROOT/infra/engine_slice"
DIST="$ROOT/infra/dist"
OUT="$DIST/abc-vision-mcp-source.zip"

# Identical allowlist to infra/build.sh. Named files only -- a bundle that
# copied a directory and pruned afterwards would leak the first time someone
# added a file to the engine.
FILES=(
  "core/__init__.py"
  "core/scan.py"
  "core/metrics.py"
  "core/court.py"
  "core/shuttle/__init__.py"
  "core/shuttle/detect.py"
  "core/shuttle/bg_core.py"
  "core/identity/__init__.py"
  "core/identity/lock.py"
  "core/identity/signature.py"
  "models/ranker_arm_c.npz"
)

echo "engine  $ENGINE"
echo "out     $OUT"
echo

[ -d "$ENGINE" ] || { echo "error: engine checkout not found at $ENGINE" >&2; exit 1; }

rm -rf "$SLICE" "$DIST"
mkdir -p "$SLICE" "$DIST"

missing=0
for rel in "${FILES[@]}"; do
  if [ ! -f "$ENGINE/$rel" ]; then
    echo "missing: $rel" >&2
    missing=1
    continue
  fi
  mkdir -p "$SLICE/$(dirname "$rel")"
  cp "$ENGINE/$rel" "$SLICE/$rel"
done
[ "$missing" -eq 0 ] || { echo >&2; echo "error: engine checkout incomplete; not bundling." >&2; exit 1; }

# Refuse to bundle if anything that should never travel reached the slice.
if find "$SLICE" \( -name "*.mp4" -o -name "*.mov" -o -name "*.csv" -o -name "*.log" \
     -o -name "*admin_key*" -o -name "*.json" \) | grep -q .; then
  echo "error: engine slice contains data files. Refusing to bundle." >&2
  find "$SLICE" \( -name "*.mp4" -o -name "*.mov" -o -name "*.csv" -o -name "*.log" \
     -o -name "*admin_key*" -o -name "*.json" \) >&2
  exit 1
fi

echo "engine slice: $(find "$SLICE" -type f | wc -l) files"

python - "$ROOT" "$OUT" <<'PY'
import os, sys, zipfile

root, out = sys.argv[1], sys.argv[2]

# What CodeBuild needs, and nothing else. The venv, the traces, the caches and
# the local git history are all excluded -- a smaller bundle is also a smaller
# thing to reason about when asking "what did I just upload".
INCLUDE_DIRS = ("src", "infra/engine_slice", "data/deidentified")
INCLUDE_FILES = ("requirements.txt", "infra/Dockerfile", "infra/buildspec.yml")
SKIP_PARTS = {"__pycache__", ".venv", ".git", ".pytest_cache", "dist", "traces"}

n = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for rel in INCLUDE_FILES:
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            z.write(p, rel.replace("\\", "/"))
            n += 1
    for d in INCLUDE_DIRS:
        base = os.path.join(root, d)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x not in SKIP_PARTS]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root).replace("\\", "/")
                z.write(full, rel)
                n += 1
print("bundled %d files" % n)
PY

echo
echo "bundle  $OUT  ($(du -h "$OUT" | cut -f1))"
echo
echo "next, in AWS CloudShell (already authenticated -- no keys to hand over):"
echo "  1. upload this zip with Actions > Upload file"
echo "  2. aws s3 mb s3://abc-vision-build-\$(aws sts get-caller-identity --query Account --output text)"
echo "  3. aws s3 cp abc-vision-mcp-source.zip s3://<that bucket>/source.zip"
