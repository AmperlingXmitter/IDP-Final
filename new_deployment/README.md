# DFU AI — Deployment Package (inference)

Self-contained package that runs the two trained models on a foot/leg photo.
**Copy this whole folder to the target machine (Raspberry Pi included) — it needs
nothing else.** Input is one image path; output is one line of JSON.

| Model | Script | Answers |
|-------|--------|---------|
| Severity classifier (MobileNetV2) | `predict_severity_class.py` | the **highest ulcer severity level** on the foot (0–4) |
| Wound segmenter (U-Net) | `segment_wound_size.py` | the **wound-vs-foot pixel ratio** (+ tissue breakdown + overlay) |

> ## ⚠️ READ THIS FIRST — version lock
> The `.keras` models were saved with **TensorFlow 2.15.1 / Keras 2.15**. They
> only load on that version. A mismatch gives
> `Layer '...' expected 1 variables, but received 0` — that is a version skew,
> **not** a broken model. Install exactly `tensorflow==2.15.1` (see
> `requirements.txt`) and run `python3 check_env.py` before anything else.

---

## 1. What's in this folder

```
deployment/
├── README.md                  ← you are here
├── requirements.txt           ← pinned dependencies (tensorflow==2.15.1)
├── check_env.py               ← run FIRST: verifies the machine can load both models
│
├── predict_severity_class.py  ← ENTRY POINT 1 — severity level
├── segment_wound_size.py      ← ENTRY POINT 2 — wound size / tissue
├── server.py                  ← OPTIONAL persistent HTTP server (loads models once)
│
├── config.py                  ← paths + settings (no need to edit)
├── model.py                   ← classifier architecture (support file)
├── seg_model.py               ← segmenter architecture + loss (support file)
│
├── outputs/                   ← the trained models live here
│   ├── severity_best.keras        (classifier)
│   ├── segment_best.keras         (segmenter)
│   ├── severity_best.weights.h5   (classifier weights — fallback only)
│   ├── seg_<image>.png            (overlay, written at runtime)
│   └── closeups/                  (cropped wound close-ups, written at runtime)
│
└── samples/                   ← two CC-licensed photos for smoke-testing
    ├── sample_foot.jpg            (a wound)
    └── sample_normal.jpg          (normal legs)
```

---

## 2. Setup (once, on the target machine)

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip libhdf5-dev   # Pi/Debian
python3 -m venv ~/dfu-env
source ~/dfu-env/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# On a Raspberry Pi, add:  --extra-index-url https://www.piwheels.org/simple
```

**Verify the machine can load the models (do this before wiring into anything):**
```bash
python3 check_env.py          # prints TF/Keras version + actually loads both models
# RESULT: PASS  -> good to go
```
If it says `FAIL ... expected N variables, received 0`, the TF version is wrong →
`pip install tensorflow==2.15.1` and re-check.

**Smoke test with the bundled samples:**
```bash
python3 predict_severity_class.py samples/sample_foot.jpg
python3 segment_wound_size.py     samples/sample_foot.jpg
```

---

## 3. The contract (how any language talks to it)

- Run: `python3 <script> <image> --json`
- **stdout** = exactly one JSON line → parse this.
- **stderr** = TensorFlow logs/warnings → ignore (or redirect with `2>/dev/null`).
- **exit code** 0 = success, non-zero = error.

```
$ python3 predict_severity_class.py samples/sample_foot.jpg --json
{"highest_level": 2, "highest_label": "Level 2 - Infection", "window_counts": {...}}

$ python3 segment_wound_size.py samples/sample_foot.jpg --json
{"wound_pct": 3.5, "foot_pct": 96.5, "wound_pixels": 9173, "total_pixels": 262144,
 "base_wound_pixels": 7100, "necrosis_pixels": 1500, "slough_pixels": 573,
 "overlay_path": "outputs/seg_sample_foot.jpg.png",
 "closeup_path": "outputs/closeups/closeup_sample_foot.jpg.png"}
```
> Pass `--no-overlay` and/or `--no-closeup` when calling from an app that only
> needs the numbers (skips the PNG writes → faster, no disk). Both paths then
> return `null`.

### Output fields

**`predict_severity_class.py`**
| Key | Type | Meaning |
|-----|------|---------|
| `highest_level` | int | 0–4, or **−1** if no skin/ulcer detected |
| `highest_label` | str | e.g. `"Level 2 - Infection"` |
| `window_counts` | obj | how many image windows fell in each level (diagnostic) |

Levels: 0 Normal · 1 Ulcer/Wound · 2 Infection · 3 Ischaemia · 4 Both

**`segment_wound_size.py`**
| Key | Type | Meaning |
|-----|------|---------|
| `wound_pct` | float | **wound area as % of the image** (the headline number) |
| `foot_pct` | float | `100 − wound_pct` |
| `wound_pixels` | int | total wound pixels |
| `total_pixels` | int | image pixels |
| `base_wound_pixels` | int | wound detected by the U-Net (red granulation) |
| `necrosis_pixels` | int | dark eschar/gangrene recovered (see §6) |
| `slough_pixels` | int | yellow slough / pale pus recovered (see §6) |
| `overlay_path` | str/null | overlay PNG (original photo + tissue-tinted wound, native resolution, **no text/background**), or null with `--no-overlay` |
| `closeup_path` | str/null | cropped close-up of the wound saved under `outputs/closeups/` for the clinician, or null with `--no-closeup` |

The overlay is the photo itself with the wound tinted by tissue type (granulation =
red, slough/pus = yellow, eschar/necrosis = black) at the original image size — no titles,
borders, or percentages baked in (those values are in the JSON for your app to
display). The close-up is a clean cropped photo of just the wound region (bounding
box + margin), written to the `closeups/` subfolder.

---

## 4. Integration — pick one

| Method | Best when | Cost |
|--------|-----------|------|
| **A. In-process Python** | your app is Python | none — fastest |
| **B. Subprocess `--json`** | another language, **occasional** images | reloads model **every call** (~3–10 s on Pi) |
| **C. Persistent server** | another language, **many** images | loads model **once**, then ~instant per call |

### A — Python (in-process)
```python
import sys; sys.path.insert(0, "/home/pi/dfu-deploy")
from predict_severity_class import classify
from segment_wound_size import segment

cls = classify("foot.jpg")                 # input: just the image path
seg = segment("foot.jpg", save_overlay=False)

level     = cls["highest_level"]           # <- OUTPUT (int)
label     = cls["highest_label"]           # <- OUTPUT (str)
wound_pct = seg["wound_pct"]               # <- OUTPUT (float)
```

### B — Subprocess `--json` (any language)
Run `python3 <script> <image> --json`, capture **stdout**, JSON-parse it.
`PY` = `/home/pi/dfu-env/bin/python3`, `DIR` = `/home/pi/dfu-deploy`.

**PHP**
```php
<?php
$py = "/home/pi/dfu-env/bin/python3";
$script = "/home/pi/dfu-deploy/segment_wound_size.py";
$cmd = escapeshellarg($py)." ".escapeshellarg($script)." ".escapeshellarg($image)." --json --no-overlay 2>/dev/null";
$r = json_decode(shell_exec($cmd), true);
$wound_pct = $r["wound_pct"];              // <- OUTPUT
```

**Node.js**
```js
const { execFile } = require("child_process");
execFile("/home/pi/dfu-env/bin/python3",
  ["/home/pi/dfu-deploy/predict_severity_class.py", image, "--json"],
  (err, stdout) => {
    const r = JSON.parse(stdout);
    const level = r.highest_level;         // <- OUTPUT
  });
```

**Java**
```java
ProcessBuilder pb = new ProcessBuilder(
    "/home/pi/dfu-env/bin/python3",
    "/home/pi/dfu-deploy/segment_wound_size.py", image, "--json", "--no-overlay");
pb.redirectErrorStream(false);             // keep TF logs out of stdout
Process p = pb.start();
String stdout = new String(p.getInputStream().readAllBytes());
p.waitFor();
JSONObject r = new JSONObject(stdout.trim());
double woundPct = r.getDouble("wound_pct");   // <- OUTPUT
```

**C++ (popen + nlohmann/json)**
```cpp
std::string run(const std::string& cmd){ std::string o; char b[256];
  FILE* p = popen(cmd.c_str(), "r"); while(fgets(b,sizeof(b),p)) o+=b; pclose(p); return o; }
auto r = nlohmann::json::parse(run(
  "/home/pi/dfu-env/bin/python3 /home/pi/dfu-deploy/predict_severity_class.py "+image+" --json 2>/dev/null"));
int level = r["highest_level"];            // <- OUTPUT
```

### C — Persistent server (any language, many images)
```bash
source ~/dfu-env/bin/activate
python3 /home/pi/dfu-deploy/server.py          # listens on 127.0.0.1:8077
```
Then HTTP GET (no model reload per call):
```bash
curl "http://127.0.0.1:8077/classify?image=/path/foot.jpg"
curl "http://127.0.0.1:8077/segment?image=/path/foot.jpg"
curl "http://127.0.0.1:8077/health"
```
```js
// Node.js
const r = await (await fetch(`http://127.0.0.1:8077/segment?image=${encodeURIComponent(image)}`)).json();
const woundPct = r.wound_pct;              // <- OUTPUT
```
Run it as a `systemd` service or `nohup python3 server.py &` to survive reboots.

---

## 5. Tuning (optional — defaults are good)

CLI flags on `segment_wound_size.py` (also available as `server.py` query params,
e.g. `&necrosis_reach=0.06`):

| Flag | Default | Effect |
|------|---------|--------|
| `--thresh F` | 0.5 | U-Net confidence cutoff; **lower** (0.3) detects more |
| `--necrosis-v N` | 60 | darkness cutoff for eschar; **higher** catches more dark tissue |
| `--necrosis-reach F` | 0.045 | how far recovery spreads from the wound (~0.03–0.08) |
| `--no-slough` | off | recover dark eschar only (skip yellow slough/pus) |
| `--no-necrosis` | off | U-Net only (disable all recovery) |

---

## 6. Why `wound_pixels` is split into three

The U-Net was trained mostly on **red granulation** wounds, so on its own it
under-detects other wound tissue. The segmenter therefore grows the U-Net's
detection into adjacent **dark eschar/gangrene** (`necrosis_pixels`) and **yellow
slough / pale pus** (`slough_pixels`). All three together = `wound_pixels`, which
is the clinically correct wound extent for size tracking. It is seed-anchored and
bounded, so it cannot invent a wound from shadows/skin. For progression tracking,
keep these settings **consistent** between the baseline and follow-up photo.

---

## 7. Troubleshooting

| Symptom | Cause → Fix |
|---------|-------------|
| `expected N variables, received 0` | TF version skew → `pip install tensorflow==2.15.1`, re-run `check_env.py` |
| `No module named keras.src.engine` | same (Keras 3 installed) → install TF 2.15.1 |
| JSON line is mixed with other text | you merged stderr into stdout → keep them separate / add `2>/dev/null` |
| Slow (~3–10 s) per call | model reloads each subprocess → use **Method C** (server) |
| Overlay PNG not written | `matplotlib` missing or `--no-overlay` set → `pip install matplotlib` |

**Defensive parsing:** stdout should be exactly one JSON line. To be extra safe,
parse the **last non-empty line** of stdout and always read **stderr separately**.
