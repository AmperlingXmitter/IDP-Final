# Phase 0 — Prove the AI runs on your Raspberry Pi

**Goal:** confirm the Pi can load and run both AI models before we build anything on top.
Do this **on the Pi itself** (it needs the camera/OS later anyway). ~15–20 min, mostly download time.

I already verified on my side that all AI scripts compile cleanly and both model files
(`severity_best.keras`, `segment_best.keras`) are intact. What can't be tested off-device is
the actual model load — that needs TensorFlow 2.15.1 on the Pi. That's what these steps do.

---

## Easiest path — one command

1. Copy the whole `Final` project (or at least the `new_deployment/` and `Testing/` folders) onto the Pi.
2. Open a terminal on the Pi, `cd` into the folder that contains `new_deployment` and `Testing`.
3. Run:

   ```bash
   bash Testing/phase0_check_pi.sh
   ```

   Optional but better — point it at a real foot photo so the result is meaningful:

   ```bash
   bash Testing/phase0_check_pi.sh /home/pi/Pictures/foot.jpg
   ```

4. Wait for it to finish. **Look for the last line:**
   - `PHASE 0: PASS ✅` → done. Tell me and I start Phase 1.
   - `PHASE 0: FAIL ❌` → copy the full output back to me and I'll fix it.

The script creates a Python virtual env at `~/dfu-env`, installs the right TensorFlow,
runs `check_env.py`, then smoke-tests classification and segmentation.

---

## What a PASS looks like

```
RESULT: PASS - this machine can run both models. Good to deploy.
...
{"highest_level": 1, "highest_label": "Level 1 - Ulcer/Wound", "window_counts": {...}}
{"wound_pct": 3.5, "foot_pct": 96.5, "wound_pixels": 9173, "total_pixels": 262144, "overlay_path": null}
...
PHASE 0: PASS ✅
```

(With the dummy random image the numbers will be meaningless — that's fine. We only care that
both models **load and run without error**.)

---

## If the one-command path fails — manual steps

Run these on the Pi, one block at a time:

```bash
# 1. system deps
sudo apt update && sudo apt install -y python3-venv python3-pip libhdf5-dev

# 2. virtual env
python3 -m venv ~/dfu-env
source ~/dfu-env/bin/activate
pip install --upgrade pip

# 3. python deps (matches the version that trained the models)
pip install "tensorflow==2.15.1" "numpy<2" pillow

# 4. go into the new_deployment folder (wherever you copied it)
cd /path/to/new_deployment

# 5. the real test
python check_env.py            # must say: RESULT: PASS
python predict_severity_class.py /path/to/foot.jpg --json
python segment_wound_size.py    /path/to/foot.jpg --json --no-overlay
```

### Common problem
`FAIL ... expected N variables, received 0` → the Pi has the wrong TensorFlow version.
Fix with `pip install "tensorflow==2.15.1"` (inside the venv) and re-run `python check_env.py`.

---

## When this passes

Reply **"Phase 0 passed"** (or paste the output) and I'll start Phase 1: the device capture app
in `/Testing` — consent screen, button capture, AI processing, timestamped saves, on-screen result.

You won't need to touch the Pi again until Phase 1 code is ready to test.
