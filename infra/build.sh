#!/usr/bin/env bash
# Stage the engine slice and build the container image.
#
# The slice is an allowlist, not a copy-and-prune. The engine checkout holds
# production data and credentials alongside its source; a build that copied a
# directory and then excluded the bad parts would leak the first time someone
# added a file. So every path that enters the image is named below, and
# anything not named does not travel.
#
# Usage:
#   bash infra/build.sh                       # build only
#   bash infra/build.sh --push <ecr-uri>      # build and push to ECR
#
# Requires: docker. ABC_ENGINE_PATH points at the engine checkout
# (default: D:\BADMINTON_COACH_APP_V1).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="${ABC_ENGINE_PATH:-/d/BADMINTON_COACH_APP_V1}"
SLICE="$ROOT/infra/engine_slice"
IMAGE="${IMAGE:-abc-vision-mcp:local}"

# Exactly what the scan and identity paths import, verified by reading the
# import statements rather than by trial and error:
#   core/scan.py      -> cv2, numpy, core.shuttle.detect, core.metrics
#   core/shuttle/*    -> cv2, numpy
#   core/identity/*   -> cv2, numpy
#   core/court.py     -> stdlib only
# The ranker is 15 KB of numpy weights and is the only model needed.
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

echo "engine   $ENGINE"
echo "slice    $SLICE"
echo "image    $IMAGE"
echo

if [ ! -d "$ENGINE" ]; then
  echo "error: engine checkout not found at $ENGINE" >&2
  echo "       set ABC_ENGINE_PATH to the right place" >&2
  exit 1
fi

rm -rf "$SLICE"
mkdir -p "$SLICE"

missing=0
for rel in "${FILES[@]}"; do
  src="$ENGINE/$rel"
  if [ ! -f "$src" ]; then
    echo "missing: $rel" >&2
    missing=1
    continue
  fi
  mkdir -p "$SLICE/$(dirname "$rel")"
  cp "$src" "$SLICE/$rel"
done

if [ "$missing" -ne 0 ]; then
  echo >&2
  echo "error: the engine checkout is incomplete; not building." >&2
  echo "       (the checkout is known to be missing eight core modules --" >&2
  echo "        see 待辦_非比賽.md. None of the files above should be among" >&2
  echo "        them, so investigate rather than working around this.)" >&2
  exit 1
fi

# Belt and braces: refuse to build if anything that should never travel has
# somehow reached the slice. Cheap, and the failure it prevents is the one that
# cannot be undone once an image is pushed.
if find "$SLICE" \( -name "*.mp4" -o -name "*.mov" -o -name "*admin_key*" \
     -o -name "*.json" -o -name "*.csv" -o -name "*.log" \) | grep -q .; then
  echo "error: the engine slice contains data files. Refusing to build." >&2
  find "$SLICE" \( -name "*.mp4" -o -name "*.mov" -o -name "*admin_key*" \
     -o -name "*.json" -o -name "*.csv" -o -name "*.log" \) >&2
  exit 1
fi

echo "staged $(find "$SLICE" -type f | wc -l) files, $(du -sh "$SLICE" | cut -f1)"
echo

docker build -f "$ROOT/infra/Dockerfile" -t "$IMAGE" "$ROOT"

echo
echo "built $IMAGE"

if [ "${1:-}" = "--push" ]; then
  TARGET="${2:?usage: build.sh --push <ecr-uri>}"
  docker tag "$IMAGE" "$TARGET"
  docker push "$TARGET"
  echo "pushed $TARGET"
fi
