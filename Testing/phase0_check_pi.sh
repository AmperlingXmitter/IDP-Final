#!/usr/bin/env bash
# =============================================================================
#  PHASE 0 - Prove the AI deployment runs on THIS Raspberry Pi.
#  Run this ONCE on the Pi. It does everything: venv -> install TF 2.15.1 ->
#  check_env.py (loads both models) -> smoke test classify + segment.
#
#  USAGE (on the Pi):
#     bash phase0_check_pi.sh                  # uses a generated test image
#     bash phase0_check_pi.sh /path/foot.jpg   # uses your own foot photo (better)
#
#  It auto-finds the 'new_deployment' folder (looks in ./new_deployment,
#  ../new_deployment, ~/dfu-deploy). Override with:  DEPLOY_DIR=/path bash phase0_check_pi.sh
#
#  RESULT TO LOOK FOR:  "RESULT: PASS"  near the end. That means the Pi can run
#  both models and you are clear to start Phase 1.
# =============================================================================
set -u

VENV="${VENV:-$HOME/dfu-env}"
TF_VER="2.15.1"

# ---- 1. locate the deployment folder ---------------------------------------
find_deploy() {
  if [ -n "${DEPLOY_DIR:-}" ] && [ -f "$DEPLOY_DIR/check_env.py" ]; then echo "$DEPLOY_DIR"; return; fi
  for d in "./new_deployment" "../new_deployment" "$HOME/dfu-deploy" "$HOME/dfu/new_deployment" "$(dirname "$0")/../new_deployment"; do
    if [ -f "$d/check_env.py" ]; then (cd "$d" && pwd); return; fi
  done
  echo ""
}
DEPLOY="$(find_deploy)"
if [ -z "$DEPLOY" ]; then
  echo "ERROR: could not find the 'new_deployment' folder (the one with check_env.py)."
  echo "Run this from beside it, or:  DEPLOY_DIR=/full/path/to/new_deployment bash phase0_check_pi.sh"
  exit 1
fi
echo "==> Using deployment folder: $DEPLOY"

# ---- 2. system packages (needed by tensorflow / pillow) --------------------
echo "==> Installing system packages (needs sudo, ~1 min)..."
sudo apt update -y >/dev/null 2>&1
sudo apt install -y python3-venv python3-pip libhdf5-dev >/dev/null 2>&1

# ---- 3. virtual env --------------------------------------------------------
if [ ! -d "$VENV" ]; then
  echo "==> Creating virtual env at $VENV"
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip >/dev/null 2>&1

# ---- 4. python deps (the slow part: TF download ~400MB) --------------------
echo "==> Installing tensorflow==$TF_VER + numpy + pillow + matplotlib (slow, be patient)..."
pip install "tensorflow==${TF_VER}" "numpy<2" pillow matplotlib || {
  echo "ERROR: pip install failed. Check the Pi's internet connection and retry."
  exit 1
}

# ---- 5. make / pick a smoke-test image -------------------------------------
IMG="${1:-}"
if [ -z "$IMG" ]; then
  IMG="/tmp/phase0_test.jpg"
  echo "==> No image given; generating a dummy test image at $IMG"
  echo "    (proves the pipeline RUNS; the result won't be medically meaningful)"
  python - "$IMG" <<'PY'
import sys, numpy as np
from PIL import Image
a = (np.random.rand(480, 640, 3) * 255).astype('uint8')
Image.fromarray(a).save(sys.argv[1])
print("   generated", sys.argv[1])
PY
fi

# ---- 6. THE REAL TESTS -----------------------------------------------------
cd "$DEPLOY"
echo ""
echo "============================================================"
echo " STEP A: check_env.py  (loads both models)"
echo "============================================================"
python check_env.py
ENV_RC=$?

echo ""
echo "============================================================"
echo " STEP B: classification smoke test"
echo "============================================================"
python predict_severity_class.py "$IMG" --json
CLS_RC=$?

echo ""
echo "============================================================"
echo " STEP C: segmentation smoke test (no overlay = faster)"
echo "============================================================"
python segment_wound_size.py "$IMG" --json --no-overlay
SEG_RC=$?

# ---- 7. verdict ------------------------------------------------------------
echo ""
echo "============================================================"
if [ $ENV_RC -eq 0 ] && [ $CLS_RC -eq 0 ] && [ $SEG_RC -eq 0 ]; then
  echo " PHASE 0: PASS  ✅   The Pi runs both models. Ready for Phase 1."
else
  echo " PHASE 0: FAIL  ❌   check_env=$ENV_RC classify=$CLS_RC segment=$SEG_RC"
  echo " If you saw 'expected N variables, received 0' it is a TF version skew:"
  echo "   pip install \"tensorflow==${TF_VER}\"   and run this again."
fi
echo " venv: $VENV   (activate later with:  source $VENV/bin/activate )"
echo "============================================================"
