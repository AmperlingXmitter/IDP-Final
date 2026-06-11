# Test the AI on your Mac (Phase 0, without the Pi)

Since the Pi is being replaced, you can prove the AI models load and run **on your Mac now**.
This is the same check as Phase 0. Your `base` conda env is Python 3.12 (too new for TF 2.15),
so make a dedicated Python 3.11 env — this also keeps it away from your `base` packages.

## Steps

```bash
# 1. dedicated env (Python 3.11; TF 2.15 needs <=3.11)
conda create -n dfu python=3.11 -y
conda activate dfu

# 2. install TensorFlow that matches the trained models
#    Apple Silicon (M1/M2/M3 - most likely your Mac):
pip install "tensorflow-macos==2.15.0" "numpy<2" pillow
#    Intel Mac instead:
#    pip install "tensorflow==2.15.1" "numpy<2" pillow

# 3. the real test (loads BOTH models)
cd "/Users/mac/Documents/Universiti Malaya/IDP/Final/new_deployment"
python check_env.py                      # look for: RESULT: PASS
python predict_severity_class.py /path/to/foot.jpg --json
python segment_wound_size.py     /path/to/foot.jpg --json --no-overlay
```

- **`RESULT: PASS`** → the AI works; the model files are good. The RPi 5 will use the same
  TF 2.15.1 (the `phase0_check_pi.sh` script handles the Pi side).
- **`FAIL ... expected N variables, received 0`** → TF/Keras version mismatch. Tell me the exact
  TF + Keras versions it printed and I'll pin the right combo.

## Then test the full AI flow on the Mac (optional, nice)
In `Testing/device/config.py` set `SHOW_UI=False`, `RUN_AI=True`, `SIMULATE_CAMERA=True`,
`SIMULATE_BUTTON=True`, point `SIM_IMAGE_PATH` at a real foot photo, then from the `dfu` env:
```bash
cd "/Users/mac/Documents/Universiti Malaya/IDP/Final/Testing/device"
python main.py        # headless: press ENTER to capture, watch the AI result print
```
(Headless mode has no Tk window, so the macOS Tk issue can't occur — good for AI testing.)
