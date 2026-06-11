# DFU Device App (RPi5)

On-device flow (spec A):

```
consent → selection (side/bottom) → instructions → live video
        → capture 1/N … N/N   (CAPTURE state)
        → AI analyses all N    (AI ANALYSIS state — separate)
        → results (averaged)   → upload to Firebase
```

One **session** = N images (default 3, set by `IMAGES_PER_SESSION`). The N images
are analysed together; the per-image outputs **and** the averaged output are
saved. Captured/overlay/close-up files are named with the moment of **final AI
output** (`{ID}_{stamp}_{index}…`) so a session's images sort together as
1st / 2nd / 3rd. Everything works fully offline; the cloud sync flushes when
Wi-Fi returns.

## Files
| File | Role |
|------|------|
| `config.py` | **All settings & on/off flags.** Patient ID, `IMAGES_PER_SESSION`, AI deployment path, fonts, UT-stage maps. Start here. |
| `ui_text.py` | **All on-screen wording** (spec D1): consent EN/MS/ZH, screen labels, errors. One place to grammar-check + translate. |
| `main.py` | `SessionController` — drives the capture→AI→results state machine. |
| `ui.py` | Tkinter kiosk for the 4.3" touchscreen (all screens + dotted snares). |
| `camera.py` | RPi Cam 3 still capture + MJPEG live preview (or simulated on a laptop). |
| `ai.py` | In-process bridge to `new_deployment`; `analyse_session()` + averaging. |
| `similarity.py` | Within-session positioning check (`session_consistency`). |
| `storage.py` | Folders, final-AI-time filenames, SQLite **session** store. |
| `cloud_api.py` | Firestore upload: averaged session doc + per-image sub-docs. |
| `button.py` `light.py` `touch_keyboard.py` | GPIO button, WS2812 light, on-screen keyboard. |
| `reset_data.py` | Wipe local/cloud data. `manage.py` | single dev commands. |

## Single commands (spec C) — same on Mac & Pi
```bash
python3 manage.py setup    # FIRST-TIME install of deps   (--ai also installs TensorFlow)
python3 manage.py test     # quick self-check / debug (no hardware)
python3 manage.py run      # launch the app          (alias: launch)
python3 manage.py clear    # wipe local images + DB  (--cloud also wipes Firestore)
python3 manage.py seed 6   # seed 6 fake sessions    (--cloud also uploads)
```
From the repo root you can also use `make setup|test|run|clear|seed`.

## A. Test on a laptop first (no Pi, no camera)
1. `make setup` (or `pip install pillow "numpy<2" opencv-python`; Tkinter ships with Python).
2. In `config.py`: `SIMULATE_CAMERA=True`, `SIMULATE_BUTTON=True`, `RUN_AI=False`,
   `SHOW_UI=True`, `FULLSCREEN=False`, `ENABLE_CLOUD=False`.
3. `python3 manage.py run`. Click the window, then **SPACE/ENTER** = the physical
   button: it advances consent → selection (click a foot) → instructions →
   live, then captures 3 images, "analyses", and shows the result. **ESC** quits.
4. For the Chinese consent text, install a CJK font: `fonts-noto-cjk`.

## B. Run on the Raspberry Pi
1. Phase 0 must pass (the AI loads — see `../PHASE0_STEPS.md`).
2. `sudo apt install -y python3-picamera2 python3-gpiozero python3-lgpio python3-tk fonts-noto-cjk`
3. In `config.py`: `SIMULATE_CAMERA=False`, `SIMULATE_BUTTON=False` (or keep the
   screen button too), `RUN_AI=True`, `FULLSCREEN=True`, `BUTTON_GPIO_PIN=17`,
   `PATIENT_ID="P001"`.
4. Wire the button between the GPIO pin and GND.
5. `source ~/dfu-env/bin/activate && python3 manage.py run`
   (If the AI isn't found: `export DFU_DEPLOYMENT_DIR=/full/path/to/new_deployment`.)

## Key flags (config.py)
- `IMAGES_PER_SESSION` — images per capture session (default 3). Flows everywhere.
- `RUN_AI` / `RUN_CLASSIFY` / `RUN_SEGMENT` — analysis on/off (off = capture-only test).
- `SAVE_OVERLAY` / `SAVE_CLOSEUP` — save the tinted overlay / cropped wound PNGs.
- `REJECT_DISSIMILAR_SESSION` — show a "retake" screen if the N images differ too much.
- `CAPTURE_SETTLE_S` / `CAPTURE_STATE_MIN_S` / `AI_STATE_MIN_S` — state time margins.
- `CAPTURE_LOCKOUT_S` — ignore repeat/long presses after a capture.
- `ENABLE_CLOUD` — queue + upload sessions to Firebase.
- `DEBUG` / `DEBUG_TIMING` — console logging + per-stage timings.
- `PREVIEW_*` — live-preview resolution/fps/smoothing knobs for the 2GB Pi.

## AI deployment
`config.DEPLOYMENT_DIR` points at **`new_deployment`** — the only AI package (lighter:
no matplotlib; native-res tissue-tinted overlay — granulation RED / slough YELLOW /
necrosis BLACK — + cropped wound close-up; less over-segmentation). Override the
location with the `DFU_DEPLOYMENT_DIR` env var. Models load once on first analysis.
