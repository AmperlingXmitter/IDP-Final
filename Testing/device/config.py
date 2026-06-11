"""
=============================================================================
 DFU DEVICE - CENTRAL CONFIG  (Testing/device/config.py)
-----------------------------------------------------------------------------
 ONE place to flip features on/off for testing (see the FLAGS block).
 Edit values here; every other device module imports from this file.

 >>> PATIENT ID is set here. To change the patient, edit PATIENT_ID below
     and re-deploy this code to the Pi. (Per project spec: pre-set in code.)
=============================================================================
"""
import os

# --------------------------------------------------------------------------- #
#  PATIENT  (pre-set in code; change + redeploy to switch patient)
# --------------------------------------------------------------------------- #
PATIENT_ID = "P001"            # <-- EDIT THIS per patient, then redeploy to Pi

# --------------------------------------------------------------------------- #
#  FLAGS  -  quick on/off switches for testing (section I of the spec)
# --------------------------------------------------------------------------- #
# Hardware
SIMULATE_CAMERA   = False   # True = use a stock test image instead of RPi Cam (laptop testing)
SIMULATE_BUTTON   = True    # True = enable the on-screen / keyboard capture button (UI mode)
# Set BOTH the above True to run the whole flow on a laptop with no Pi hardware.
#
# NOTE: SIMULATE_BUTTON and USE_GPIO_BUTTON are now INDEPENDENT.
#   * SIMULATE_BUTTON = True  -> the screen button + SPACE/ENTER keys trigger a capture.
#   * USE_GPIO_BUTTON = True  -> the physical GPIO 17 button ALSO triggers a capture.
# Leave BOTH True to use the on-screen button AND the GPIO 17 button at the same time
# (the shared lockout guard in button.py keeps it to one capture at a time either way).
# On a laptop with no GPIO, USE_GPIO_BUTTON simply no-ops with a warning — no crash.
USE_GPIO_BUTTON   = True     # True = also wire the physical GPIO button (works alongside the screen button)

# UI
SHOW_UI           = True    # True = fullscreen Tkinter UI; False = headless (console only)
FULLSCREEN        = True    # touchscreen kiosk mode
SHOW_CONSENT      = True    # show the medical-device consent screen on boot

# AI
RUN_AI            = True    # True = run AI; False = skip (capture-only test)
RUN_CLASSIFY      = True    # severity level (the headline medical output)
RUN_SEGMENT       = True    # wound-size %. Slower on the Pi; set False for a quicker loop.
SAVE_OVERLAY      = True    # save the native-res tissue-tinted overlay PNG (needs RUN_SEGMENT)
SAVE_CLOSEUP      = True    # save the cropped wound close-up PNG (new_deployment; shown on Results)
RUN_SIMILARITY    = True    # compare new SESSION's images to each other; logs + DB + optional gate

# --------------------------------------------------------------------------- #
#  MULTI-IMAGE SESSION  (spec A/B: capture N images, then analyse all at once)
# --------------------------------------------------------------------------- #
# How many images make up one capture session. Default 3 (spec). Changing this
# ONE value flows through capture, AI averaging, the UI counter ("Capture x/N"),
# the Results browser (1/N) and the cloud upload — nothing else to edit.
IMAGES_PER_SESSION = 3

# Capture state vs. AI Analysis state are SEPARATE (spec A1). These margins give
# the camera/UI a moment to settle so quick presses never overlap a state change.
CAPTURE_SETTLE_S   = 0.6    # pause before+after each still so the frame is stable
CAPTURE_STATE_MIN_S = 0.5   # min time the "Capturing Image…" screen stays up (avoids flicker)
AI_STATE_MIN_S     = 1.2    # min time the "AI Analysing Images…" screen stays up

# Reject-and-retry if the N session images are too dissimilar to each other
# (different feet / big movement). Off by default — turn on once thresholds are
# tuned at the clinic. Uses similarity.py (ORB/hist/SSIM).
REJECT_DISSIMILAR_SESSION = False
SESSION_SIM_MIN_ORB   = 120   # fewer ORB matches than this between any pair → reject
SESSION_SIM_MIN_HIST  = 0.80  # colour-histogram correlation floor (0–1)

# Live video preview on idle screen
SHOW_LIVE_PREVIEW  = True     # False = static text only (useful if rpicam-vid unavailable)
PREVIEW_WIDTH      = 320      # 320×180 = 180p  — big lag reduction vs 480×270 on Pi 5
PREVIEW_HEIGHT     = 180      # reduce to 240×135 (or 160×90) if lag persists
PREVIEW_FPS        = 12       # display + capture fps target; in-place update lets us afford more
PREVIEW_BITRATE    = 300000   # 300 kbps — less JPEG data per frame to decode
PREVIEW_FAST_RESIZE = True    # True = BILINEAR upscale to screen (fast); False = LANCZOS (quality)

# Aggressive low-RAM smoothing knobs (Pi 5 2GB) — see camera.py / ui.py
PREVIEW_QUALITY        = 50   # MJPEG encode quality from rpicam-vid (lower = less data to decode)
PREVIEW_BUFFER_COUNT   = 2    # camera buffers; 2 keeps RAM + latency low on a 2GB Pi
PREVIEW_REUSE_PHOTO    = True # reuse ONE Tk PhotoImage via paste() — kills per-frame alloc/GC churn
PREVIEW_SKIP_UNCHANGED = True # skip re-render when no new frame arrived (saves CPU)
PREVIEW_SHOW_CROSSHAIR = True # centre crosshair to help framing

# --- EXTRA smoothness knobs (all safe; tune the ladder below if still laggy) ---
PREVIEW_FLUSH          = True # rpicam-vid --flush: push each frame out immediately (lower latency)
PREVIEW_POLL_HZ        = 30   # how often the UI checks for a new frame (decoupled from camera fps).
                              #   Higher = a fresh frame is painted sooner. SKIP_UNCHANGED makes the
                              #   extra checks almost free (they bail out when no new frame arrived).
PREVIEW_JPEG_DRAFT     = True # PIL draft() fast JPEG decode — big win when capturing >= display size,
                              #   harmless no-op when upscaling. Slightly softer image.
PREVIEW_STATIC_CROSSHAIR = False  # draw the crosshair ONCE as a Tk overlay instead of re-drawing it
                              #   into every frame. Removes per-frame draw cost. Set True for max
                              #   smoothness (look is identical). Needs PREVIEW_SHOW_CROSSHAIR=True.
#
# IF THE PREVIEW IS STILL LAGGY, climb this ladder (cheapest first):
#   1) PREVIEW_STATIC_CROSSHAIR = True            (free; removes per-frame crosshair work)
#   2) PREVIEW_WIDTH/HEIGHT = 256x144 (or 160x90) (less to decode each frame)
#   3) PREVIEW_QUALITY = 40, PREVIEW_BITRATE = 200000   (less JPEG data per frame)
#   4) PREVIEW_FPS = 10                           (fewer frames to decode/paint)
#   5) PREVIEW_FAST_RESIZE = True (already)        (BILINEAR upscale)
# Last resort: SHOW_LIVE_PREVIEW = False (static text only — zero preview cost).

# --------------------------------------------------------------------------- #
#  AUTOFOCUS  (RPi Camera Module 3 only — guarded; ignored on V1/V2/HQ cameras)
# --------------------------------------------------------------------------- #
CAMERA_AUTOFOCUS   = True          # run an AF sweep right before EACH still capture (sharp stills)
PREVIEW_AF_MODE    = "continuous"  # live-preview AF: "continuous" | "auto" | "manual"
PREVIEW_AF_SPEED   = "fast"        # AF speed for continuous mode: "normal" | "fast"
LENS_POSITION      = None          # manual-focus dioptres (e.g. 2.0 ≈ 50cm, 0 = infinity);
                                   #   used when AF mode = "manual" and as a fallback if AF fails.
                                   #   None = let autofocus decide.
AF_WINDOW          = None          # (x, y, w, h) normalised 0..1 AF region, or None for full-frame

# Cloud (Phase 2 - off until that phase is built/tested)
ENABLE_CLOUD      = True   # True = queue + upload to Firebase

# Segmentation sensitivity (lower = easier to detect wound, more false positives)
# Wound area showing 0.0%? Try lowering to 0.3 or 0.2 to see if model detects anything.
SEG_THRESHOLD     = 0.5     # 0.0–1.0; default from FUSeg training is 0.5

# Debug
DEBUG             = True    # extra console logging (timestamps, timings, paths)
DEBUG_TIMING      = True    # print how long each stage takes

# --------------------------------------------------------------------------- #
#  BUTTON behaviour  (prevent repeat / long-press double captures)
# --------------------------------------------------------------------------- #
BUTTON_GPIO_PIN   = 17      # BCM pin the capture button is wired to
BUTTON_BOUNCE_S   = 0.10    # debounce window (seconds)
CAPTURE_LOCKOUT_S = 3.0     # ignore any further press for this long after a capture

# --------------------------------------------------------------------------- #
#  CAMERA
# --------------------------------------------------------------------------- #
CAPTURE_WIDTH     = 1920
CAPTURE_HEIGHT    = 1080
SIM_IMAGE_PATH    = "/Users/mac/Documents/Universiti Malaya/IDP/Final/Testing/device/sample_dfu.jpg"      # if SIMULATE_CAMERA: path to a test foot photo ("" = auto-generate)

# --------------------------------------------------------------------------- #
#  DISPLAY  (4.3" DSI, 800x480)
# --------------------------------------------------------------------------- #
SCREEN_W          = 800
SCREEN_H          = 480

# --------------------------------------------------------------------------- #
#  WS2812 LIGHT  (only used when ENABLE_LIGHT = True)
# --------------------------------------------------------------------------- #
ENABLE_LIGHT    = True
LIGHT_COUNT     = 16        # however many LEDs you have
LIGHT_PIN       = 10        # GPIO 10 = SPI0 MOSI (Pin 19)
LIGHT_BRIGHTNESS = 128      # 0–255

# --------------------------------------------------------------------------- #
#  PATHS  -  images saved on the Pi MicroSD, sorted by name (ID + timestamp)
# --------------------------------------------------------------------------- #
ROOT          = os.path.dirname(os.path.abspath(__file__))
# Where to find the ASSISTANT's AI deployment folder. Adjust on the Pi if needed.
# NOTE: points at new_deployment (the ASSISTANT's current AI: lighter — no
# matplotlib — native-res tinted overlay + cropped wound close-up, less over-
# segmentation). This is now the ONLY AI package (the old 'deployment' folder
# was removed). Override the location with the DFU_DEPLOYMENT_DIR env var.
DEPLOYMENT_DIR = os.environ.get(
    "DFU_DEPLOYMENT_DIR",
    os.path.abspath(os.path.join(ROOT, "..", "..", "new_deployment")),
)

IMAGE_ROOT       = os.path.join(ROOT, "Image")
CAPTURE_FOLDER   = os.path.join(IMAGE_ROOT, "Captured_Images")
RESIZED_FOLDER   = os.path.join(IMAGE_ROOT, "Resized_Images")
SEGMENTED_FOLDER = os.path.join(IMAGE_ROOT, "Segmented_Images")
OVERLAY_FOLDER   = os.path.join(IMAGE_ROOT, "Overlay_Images")
CLOSEUP_FOLDER   = os.path.join(IMAGE_ROOT, "Closeup_Images")   # cropped wound (new AI)
LOG_FOLDER       = os.path.join(ROOT, "Logs")

ALL_FOLDERS = [IMAGE_ROOT, CAPTURE_FOLDER, RESIZED_FOLDER,
               SEGMENTED_FOLDER, OVERLAY_FOLDER, CLOSEUP_FOLDER, LOG_FOLDER]

# --------------------------------------------------------------------------- #
#  LOCAL DATABASE  (works offline; Phase 2 syncs this to the cloud)
# --------------------------------------------------------------------------- #
DB_PATH = os.path.join(ROOT, "dfu_local.db")

# --------------------------------------------------------------------------- #
#  UT (University of Texas) DIABETIC WOUND CLASSIFICATION
#  Maps AI level (0–3) to clinical UT stage label.
#  Level 4 and -1 fall back to the deployment's own label.
# --------------------------------------------------------------------------- #
#  UT staging tops out at Stage D. If the AI emits a level above D's range,
#  it is still reported as Stage D (the most severe UT stage) but with a
#  description noting it is more advanced/severe.
UT_LABELS = {
    0: "UT Stage A – Clean wound\n(no infection, no ischaemia)",
    1: "UT Stage B – Infected wound\n(nonischaemic)",
    2: "UT Stage C – Ischaemic wound\n(noninfected)",
    3: "UT Stage D – Ischaemic & infected",
    4: "UT Stage D – Severe / advanced\n(extensive ischaemia & infection)",
}

# --------------------------------------------------------------------------- #
#  UT STAGE AVERAGING  (spec B2)
#  Each AI level (0–4) maps to a UT stage letter; letters carry a number
#  (A=1, B=2, C=3, D=4). To average a session we convert each image's stage to
#  its number, take the mean, and pick the letter whose number is closest.
# --------------------------------------------------------------------------- #
LEVEL_TO_STAGE = {0: "A", 1: "B", 2: "C", 3: "D", 4: "D"}   # level -1 (none) handled in code
UT_STAGE_NUM   = {"A": 1, "B": 2, "C": 3, "D": 4}
UT_NUM_STAGE   = {1: "A", 2: "B", 3: "C", 4: "D"}

# Stage-letter → short description + background colour for the (averaged) Results
# screen. Colours escalate green→red so medical staff read severity at a glance.
UT_STAGE_LABELS = {
    "A": "UT Stage A – Clean wound\n(no infection, no ischaemia)",
    "B": "UT Stage B – Infected wound\n(nonischaemic)",
    "C": "UT Stage C – Ischaemic wound\n(noninfected)",
    "D": "UT Stage D – Ischaemic & infected",
}
UT_STAGE_COLOURS = {
    "A": "#2e7d32",   # green
    "B": "#f9a825",   # amber
    "C": "#ef6c00",   # orange
    "D": "#c62828",   # red
    "?": "#546e7a",   # no ulcer detected / unknown — grey-blue
}

# --------------------------------------------------------------------------- #
#  UI LAYOUT CONSTANTS  (keeps button positions consistent across screens)
# --------------------------------------------------------------------------- #
UI_MARGIN      = 8    # px from edge/corner for all corner & edge buttons
UI_BTN_H_SM    = 40   # height for small buttons (Back, Flash)
UI_BTN_H_LG    = 56   # height for large action buttons (Capture, Agree)

# --------------------------------------------------------------------------- #
#  UI TEXT  -  ALL on-screen wording now lives in ONE place: ui_text.py
#  (spec D1 — single file for grammar checking + multilingual support).
#  Consent / selection / instruction / results strings are no longer here.
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
#  FONTS  (spec D2 — large enough for elderly users on the 4.3" screen)
#  One ladder of sizes used everywhere so type stays consistent + readable.
# --------------------------------------------------------------------------- #
UI_FONT_FAMILY = "DejaVu Sans"
FONT_TITLE   = 22   # screen titles
FONT_HEADING = 18   # section headings / stage label
FONT_BODY    = 15   # body text (min comfortable size for older eyes)
FONT_BUTTON  = 17   # button labels
FONT_SMALL   = 13   # captions / secondary info (kept >=13 for legibility)
FONT_MIN     = 13   # below this, switch to a scrollable area instead (spec D4)
