#!/bin/bash
# =============================================================================
#  ONE-COMMAND LAUNCHER — Staff Desktop App (macOS)
# -----------------------------------------------------------------------------
#  Double-click this file in Finder, OR run:
#      bash "/Users/mac/Documents/Universiti Malaya/IDP/Final/Testing/run_desktop.command"
#
#  Read from the cloud instead of the demo DB:
#      DFU_BACKEND=firebase bash ".../Testing/run_desktop.command"
# =============================================================================
cd "$(dirname "$0")/desktop" || { echo "desktop folder not found"; exit 1; }

echo "[run] installing desktop deps (first run may take a minute)…"
python3 -m pip install -q -r requirements-desktop.txt || {
    echo "[run] pip install failed — check your Python/pip"; exit 1; }

# Seed the demo DB once if we're on the local backend and have no DB yet.
if [ "${DFU_BACKEND:-local}" = "local" ] && [ -z "$DFU_DB" ] && [ ! -f demo_dfu.db ]; then
    echo "[run] seeding demo data…"
    python3 seed_demo_data.py
fi

echo "[run] launching DFU Monitor — Staff   (login PIN: 1234)"
echo "[run] backend: ${DFU_BACKEND:-local}"
python3 run_desktop.py
