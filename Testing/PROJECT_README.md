# DFU Remote Monitoring Device — PROJECT README

> **Audience: Claude / ChatGPT.** Paste this whole file at the start of a chat — it
> describes the entire system accurately and is enough on its own unless debugging a
> specific module. Terse by design; every section is current with the code.

**System.** A Raspberry Pi 5 + Camera Module 3 captures photos of a diabetic foot
ulcer (DFU), an on-device AI grades severity (UT stage) and measures wound size,
results are stored locally and (when online) uploaded to Firebase. Medical staff
review everything in a desktop dashboard. **Screening aid only — NOT a diagnosis;**
all findings are reviewed by a clinician.

**Hard safety rule (never break):** any patient-facing "suggested action" in the
desktop app (healing banner, PDF) may state **logistics only** — "visit clinic",
"contact the doctor", "continue routine monitoring", "capture more readings". It must
**never** give clinical/treatment advice. Centralised in `app._healing_status()`.

---

## Core concept: a SESSION = N images

The unit of measurement is a **session**, not a single photo. One session = **N images**
(`IMAGES_PER_SESSION`, default **3**) captured back-to-back, then analysed **together**.
Both the **per-image** outputs and the **averaged** session result are saved/uploaded.

- **Average UT stage:** map level→letter (A=1,B=2,C=3,D=4), mean the numbers, round to
  the nearest letter (ties round **up** = more severe). Level −1 (no ulcer) excluded.
- **Average wound %, foot %:** mean over the images that produced a value.
- **File naming = moment of FINAL AI output** (not capture time):
  `{PATIENT_ID}_{stamp}_{index}` → a session's images sort together as 1st/2nd/3rd.
- One `session_id = {patient_id}_{stamp}` groups the rows.

---

## Roles

| Role | Owns |
|---|---|
| **ASSISTANT** (trained-AI team) | `new_deployment/` — the AI inference package (the ONLY one; old `deployment/` was deleted). Fixed contract; do not modify except agreed tweaks. |
| **ME** (this Claude) | `Testing/device/` (RPi 5 app) + `Testing/desktop/` (staff app). All application code. |

---

## Repository layout

```
Final/
├── new_deployment/                ← ASSISTANT's AI. Copy to the Pi unchanged. Self-contained.
│   ├── README.md                  ← the AI "contract"
│   ├── predict_severity_class.py  ← classify(image)
│   ├── segment_wound_size.py      ← segment(image, save_overlay=, save_closeup=)
│   ├── model.py / seg_model.py    ← architectures
│   ├── server.py / check_env.py   ← optional HTTP server / env check
│   └── outputs/*.keras            ← severity + segmentation models (TF 2.15.1)
│
└── Testing/                       ← ME's application code
    ├── PROJECT_README.md          ← THIS FILE
    ├── OPERATIONAL_MANUAL.md      ← end-user manual (patients + staff)
    ├── HISTORY_OF_DEVELOPMENT.md  ← how the codebase came to be (iterative story)
    ├── PHASE0_STEPS.md / MAC_AI_TEST.md / phase0_check_pi.sh   ← AI bring-up
    ├── Makefile                   ← single commands (make setup|test|run|clear|seed|app)
    ├── run_device.sh / run_desktop.command
    │
    ├── device/                    ← RPi 5 on-device app  (see device/DEVICE_README.md)
    │   ├── config.py              ← ALL settings & flags + UT maps + fonts. START HERE.
    │   ├── ui_text.py             ← ALL on-screen wording (consent EN/MS/ZH, etc.)
    │   ├── main.py                ← SessionController: capture→AI→save→upload state machine
    │   ├── ui.py                  ← Tkinter kiosk (4.3" DSI 800×480): all screens + snares
    │   ├── camera.py              ← Cam-3 still + rpicam-vid MJPEG live preview
    │   ├── ai.py                  ← in-process bridge to new_deployment; multi-image + averaging
    │   ├── similarity.py          ← within-session positioning check (ORB/hist/SSIM)
    │   ├── storage.py             ← folders, final-AI-time filenames, SQLite session store
    │   ├── cloud_api.py           ← Firestore upload: averaged doc + per-image sub-docs
    │   ├── button.py / light.py / touch_keyboard.py
    │   ├── manage.py              ← single dev commands (setup/test/run/clear/seed)
    │   └── reset_data.py          ← wipe local/cloud data (safe by default)
    │
    └── desktop/                   ← staff dashboard (Mac/Windows)  (see desktop/DESKTOP_README.md)
        ├── app.py                 ← Dash UI + callbacks
        ├── data_source.py         ← LocalSource (sqlite) + FirebaseSource + ds.sessions()/session_trend()
        ├── svg_assets.py          ← avatars, foot outlines, colour-blind cues
        ├── report.py              ← PDF export (reportlab)
        ├── audit.py / debug_utils.py
        ├── seed_demo_data.py      ← writes demo_dfu.db (3-image sessions)
        └── run_desktop.py
```

---

## Single commands (Mac + Pi)

From `Testing/` (Makefile) or `Testing/device/` (`python3 manage.py <cmd>`):

| Command | Does |
|---|---|
| `make setup [ARGS=--ai]` | first-time install of deps (`--ai` also installs TensorFlow) |
| `make test` | quick self-check: imports + averaging + storage round-trip + AI-folder present |
| `make run` | launch the device app |
| `make clear [ARGS=--cloud]` | wipe local images + DB (+ Firestore) |
| `make seed [ARGS=N\|--cloud]` | seed N fake **device** sessions locally (+ cloud) |
| `make app` | launch the desktop app |

---

## AI contract (`new_deployment/`)

**Version lock: TF 2.15.1** — the `.keras` files load only under that exact TF/Keras.
Run `python3 check_env.py` first (must print `RESULT: PASS`).

```python
from predict_severity_class import classify
from segment_wound_size import segment

classify("foot.jpg")
# → {"highest_level": 0..4 / -1, "highest_label": str, "window_counts": dict}

segment("foot.jpg", save_overlay=True, save_closeup=True)
# → {"wound_pct": float, "foot_pct": float, "wound_pixels": int, "total_pixels": int,
#    "base_wound_pixels": int, "necrosis_pixels": int, "slough_pixels": int,
#    "overlay_path": str|None,   # original photo, wound tinted by tissue, native res, no chrome
#    "closeup_path": str|None}   # cropped close-up of the wound (shown on Results)
```

- **Overlay tints (match the desktop legend): granulation = RED, slough = YELLOW,
  eschar/necrosis = BLACK.** No matplotlib (Pillow only).
- `device/ai.py` calls these in-process, remaps levels 0–3 → UT labels (`config.UT_LABELS`),
  and temporarily pops the device `config` from `sys.modules` so the AI imports ITS OWN config.
- `ai.analyse_session([img1,img2,img3])` → per-image dicts + averaged summary.

### UT classification (DB + both apps)
| AI level | UT stage | Stored label (line 1) |
|---|---|---|
| 0 | A | UT Stage A – Clean wound |
| 1 | B | UT Stage B – Infected wound |
| 2 | C | UT Stage C – Ischaemic wound |
| 3 | D | UT Stage D – Ischaemic & infected |
| 4 | D | UT Stage D – Severe / advanced |
| −1 | — | (no wound) |

UT tops out at D; level 4 = Stage D "severe/advanced" (deeper red).

---

## Device app — `Testing/device/`

### Flow (spec A)
```
consent (EN/MS/ZH, PDPA 2010; press once)
  → selection (side OR bottom of foot, with silhouette + red ulcer dot)
  → instructions (per-angle, paged, with a snare schematic)
  → live video (angle-specific DOTTED snares; "Capture i/N"; Reset; Patient-ID locks mid-session)
     → CAPTURE state  ×N   ("Capturing Image…", brief)      [separate state + time margins]
     → AI ANALYSIS state    ("AI Analysing Images…")          [analyse all N at once]
        → [optional] reject if the N images are too dissimilar → "Please Retake"
        → storage.finalize_session(): rename to final-AI time, save N rows
        → cloud_api.upload_session_async()
     → RESULTS (N overlays, cropped if available; AVERAGED stage + colour; NO wound %; arrows 1/N; Done)
  → Captured Images list (grouped per session) ↔ Results(selected) per dismiss logic
```
Capture state and AI state are **separate** with `CAPTURE_SETTLE_S` / `CAPTURE_STATE_MIN_S` /
`AI_STATE_MIN_S` margins so quick presses never collide. Snares: **side** = bucket (flat base +
two short uprights); **bottom** = two tall uprights (toes/heel). Reset → back to consent, 0/N, flash off.

### Buttons & run modes
- Physical **GPIO 17** button and on-screen button are **independent** flags
  (`USE_GPIO_BUTTON`, `SIMULATE_BUTTON`); leave both True to use both. Shared lockout in
  `button.py` enforces one capture at a time. Physical button is multi-purpose (capture / back /
  dismiss) via `ui.physical_press`.
- `SHOW_UI=True` → Tkinter kiosk (work in a worker thread, UI via thread-safe `queue`; Tk owns the
  main thread — required on macOS). `SHOW_UI=False` → headless console loop.

### Key `config.py` flags
```python
PATIENT_ID = "P001"            # change + redeploy to switch patient
IMAGES_PER_SESSION = 3         # flows through capture, AI averaging, UI counter, results, cloud
SIMULATE_CAMERA / SIMULATE_BUTTON / USE_GPIO_BUTTON
SHOW_UI / FULLSCREEN / SHOW_CONSENT
RUN_AI / RUN_CLASSIFY / RUN_SEGMENT / SAVE_OVERLAY / SAVE_CLOSEUP / RUN_SIMILARITY
REJECT_DISSIMILAR_SESSION      # show "Please Retake" if the N images differ too much
ENABLE_CLOUD / ENABLE_LIGHT
DEBUG / DEBUG_TIMING
BUTTON_GPIO_PIN=17 / CAPTURE_LOCKOUT_S / CAPTURE_SETTLE_S / *_STATE_MIN_S
PREVIEW_* (live-preview resolution/fps/smoothness ladder)
FONT_* (UI font sizes, large for elderly)  ·  UT_* maps  ·  DEPLOYMENT_DIR (→ new_deployment)
```
Live preview pipeline: `rpicam-vid --codec mjpeg` → JPEG frames → Canvas image (reused via
`PhotoImage.paste()`); dotted snares are Canvas line items drawn once. Stills are a separate
`picamera2` subprocess at full res with an AF sweep. CJK consent text needs `fonts-noto-cjk`.

---

## Shared SQLite schema

### `captures` (device writes, desktop reads) — session-aware
```
id, patient_id, session_id, image_index(1..N), n_images, foot_angle('side'|'bottom'),
stamp("YYYYMMDD_HHMMSS" = final AI-output time), captured_path, overlay_path, closeup_path,
highest_level(0..4/-1/NULL), highest_label, stage('A'..'D'/'?'), wound_pct, foot_pct, window_counts,
avg_level, avg_stage, avg_label, avg_wound_pct, avg_foot_pct,   -- session averages (denormalised on every row)
sim_orb, sim_hist, sim_ssim, sim_consistent(1/0/NULL), sim_prev_id,
base_wound_px, necrosis_px, slough_px, synced(0/1), created_at
```
Migrations are idempotent (`storage._migrate_db`, desktop `LocalSource._ensure_capture_cols`).

### `patients` (desktop-managed; device never writes it)
```
patient_id PK, name, dob, notes, gender('M'/'F'/''), wound_site, wound_points(JSON), created_at
```
`wound_points` = manual DFU markers: `[{"view":"side"|"bottom","x":int,"y":int,"colour":"red"|"yellow"|"black"}]`.

---

## Desktop app — `Testing/desktop/`

Medical staff only, PIN-gated (`STAFF_PIN`, default `1234`). Apple-Health light theme.
Tabs: **Patients**, **List**, **Cloud (Firebase)**.

### Data streams — runtime toggle (spec E)
Header toggle switches the active source between **Seeded** demo data (local `demo_dfu.db`) and
the live **Database** (Firestore). Implemented as a transparent `_SourceRouter` proxy; switching
resets to the overview and refreshes both tabs. Default from `DFU_BACKEND` (local→seeded,
firebase→database). `ds.sessions(rows)` groups rows into sessions for BOTH backends (Firestore
session docs carry `image_wound_pcts` so the per-image spread survives).

### Patient page (spec E1)
- **3 widgets in one row:** **UT stage** (averaged, no picture, capture date label) · **Wound bed
  composition** (granulation RED / slough YELLOW / necrosis BLACK; capture date label) · **Trend**
  (compares earliest vs latest **average** readings; needs ≥2 averages ≥7 days apart else
  "Too little data").
- **Trend graph:** per-session **error bars** (min→max of that session's readings); the **average**
  point stands out (stage-coloured, larger, white ring); individual readings are small/muted.
- **Measurements list:** collapsible **per session** — average row as header; expand for the
  individual readings + editable **Date/Time + foot-angle dropdown** (apply to all N images) and
  per-image **Lvl/Wound%** edits. Saving writes the DB then bumps a `save-token` so the graph
  recalculates (fixes the old stale-graph race).
- **Image panel:** **Selected Capture** (the picked/latest session's images) and **Graph Selection**
  (earliest vs latest average, each labelled with date+time).
- **Patient info squircle:** per-field edit, minimise, **gender silhouette avatar** (male/female/
  unspecified), and the **multi-point foot picker** (click to drop red/yellow/black markers,
  side/bottom view dropdown, Undo/Clear → saved as `wound_points`).
- **Export PDF** (`report.py`, session-aware) · **Audit log** button · healing-status banner.

### `data_source.py` interface (both backends identical)
```
patients()                          # triage list, urgent first (gender/age/has_trend/wound_series)
captures(pid)                       # rows oldest→newest; stamp→dt
sessions(rows)                      # group into sessions: avg_*, wound_min/max/vals, tissue, members[], rep
session_trend(sessions, days)       # earliest/latest avg, roc, ok=False ("too little data") if <2 / <7d
update_capture(id, fields)          # editable: highest_level/label, wound_pct, foot_pct, STAMP, foot_angle
get_patient(pid) / upsert_patient(pid, name, dob, notes, gender, wound_site, wound_points)
get_capture_images(row)             # (captured_uri, overlay_uri): disk (local) or base64 (firebase)
diagnostics()                       # {ok, backend, message, n_patients, n_captures, sample}
```
Triage thresholds (top of `data_source.py`): `URGENT_LEVEL=2`, `URGENT_ROC_PER_DAY=0.2`.

### Firebase: editable timestamp (important)
A capture/session lives at `patients/{pid}/captures/{docId}`. The **document id is a stable key**;
the **editable timestamp is the `stamp` field** (what trends/ROC read). Staff can correct a date/time
without moving the doc or breaking image lookups.

### Flags / env
```
STAFF_PIN, SHOW_HEALING_BANNER, SHOW_COMPARE, SHOW_FOOT_DIAGRAM, ENABLE_PDF_REPORT, DEBUG_UI
env: DFU_BACKEND, DFU_DB, DFU_AUDIT_DB, DFU_DEBUG, DFU_FB_PROJECT, DFU_FB_KEY
```

---

## Cloud (Firebase / Firestore)
Free Spark plan, **no Cloud Storage**: images are downscaled + JPEG-compressed to **base64 string
fields** (< 1 MiB/doc). Layout per session:
- `patients/{pid}/captures/{session_id}` — averaged headline (`highest_level/label/wound_pct` =
  averages, plus `avg_stage`, `n_images`, `foot_angle`, `image_wound_pcts`, a representative image).
- `patients/{pid}/captures/{session_id}/images/{i}` — each image's captured/overlay/closeup base64.

`cloud_api.upload_session_async()` fires after each session; `sync_unsynced()` flushes the offline
backlog at startup (low-connectivity friendly: stops on first failure, retries later). Reads use
pure `urllib`. **Security:** API-key only → test-mode rules for now; add Firebase Auth before real
patients.

---

## Install on Pi (summary)
Copy `new_deployment/` + `Testing/` to the Pi (device app + AI only; desktop stays on Mac/Windows).
```bash
sudo apt install -y python3-picamera2 python3-gpiozero python3-lgpio python3-tk fonts-noto-cjk
source ~/dfu-env/bin/activate            # venv with TF 2.15.1 (Phase 0)
make setup --ARGS=--ai                   # or: pip install pillow "numpy<2" opencv-python tensorflow==2.15.1
# config.py: SIMULATE_CAMERA=False, USE_GPIO_BUTTON=True, SHOW_UI=True, FULLSCREEN=True, RUN_AI=True
make run                                 # or: cd device && python3 main.py
```
Pi 5 uses **lgpio** (not RPi.GPIO). If `opencv-python` won't build on ARM, `RUN_SIMILARITY=False`
(auto-disabled on import failure in `main.py`).

---

## Phase status
| Phase | What | Status |
|---|---|---|
| 0 | AI runs (models load + scripts) | ✅ Mac · ⏳ Pi pending |
| 1 | Device capture app (multi-image sessions, new UI flow) | ✅ Code complete + logic-tested · ⏳ Pi hardware test |
| 2 | Cloud upload (session docs, base64) + offline sync | ✅ Implemented · ⏳ live-Pi test |
| 3 | Desktop dashboard (sessions, error bars, foot picker, toggle, export) | ✅ Complete · ⏳ visual confirm |
| AI | `new_deployment` (lighter, cropped close-up, red/yellow/black overlay) | ✅ Done; old `deployment/` removed |

---

## Known TODOs / caveats
1. **Hardware/GUI test pending:** device UI + GPIO + Cam-3 preview/AF on the Pi; desktop visuals in a
   browser (the desktop is verified by logic/stub tests, not rendered). Run `make run` / `make app`.
2. **Cloud live test:** confirm a real session appears in Firestore; lock down rules / add Auth.
3. **WS2812 on Pi 5:** `light.py` needs an SPI driver (`rpi5-ws2812`); PWM/DMA libs don't work on Pi 5.
4. **Foot picker** snaps markers to a ~22 px grid (Dash can't read arbitrary click coords without
   custom JS) — pixel-precise placement would need a clientside callback.
5. **Pi-local image paths:** opening a Pi `dfu_local.db` from another machine shows "Image not
   available" (paths are Pi-local); numbers still work. Use the Firebase backend to see images.

---

## Quick-test sequences
- **Laptop device sim (no Pi/cam/TF):** `config.py` → `SIMULATE_CAMERA=True, RUN_AI=False,
  RUN_SIMILARITY=False, SHOW_UI=True, FULLSCREEN=False`; `make run` (SPACE/ENTER = physical button).
- **Desktop:** `make app` (PIN 1234). Reset demo data: `cd desktop && python3 seed_demo_data.py`.
- **Reset everything:** `make clear` (add `ARGS=--cloud` for Firestore too).

### Debugging checklist to paste into a chat
1. Exact error (last ~20 lines). 2. Relevant `config.py` flags. 3. Which step failed. 4. `python3
--version`, `pip show tensorflow` (AI), `pip show opencv-python` (similarity). For desktop, set
`DEBUG_UI=True` and include `desktop_debug.log`.
