#!/bin/bash
# =============================================================================
#  ONE-COMMAND LAUNCHER — RPi Device App (Raspberry Pi)
# -----------------------------------------------------------------------------
#  Run on the Pi:
#      bash ~/Testing/run_device.sh
#
#  Edit feature flags in device/config.py first (SIMULATE_*, SHOW_UI, RUN_AI,
#  ENABLE_CLOUD, CAMERA_AUTOFOCUS, PREVIEW_*). For the physical button set
#  SIMULATE_BUTTON=False; for the real camera set SIMULATE_CAMERA=False.
# =============================================================================
cd "$(dirname "$0")/device" || { echo "device folder not found"; exit 1; }

# Activate the project virtualenv from Phase 0 if it exists.
if [ -d "$HOME/dfu-env" ]; then
    # shellcheck disable=SC1091
    source "$HOME/dfu-env/bin/activate"
    echo "[run] activated venv: $HOME/dfu-env"
fi

# Make sure Tk can find the DSI display when launched over SSH/RPi Connect.
export DISPLAY="${DISPLAY:-:0}"

echo "[run] starting DFU device app…  (Ctrl-C to stop)"
python3 main.py
