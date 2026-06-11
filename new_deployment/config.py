"""
Deployment configuration (inference only).

Everything the two entry scripts need is here. Paths resolve relative to THIS
folder, so the whole `deployment/` directory is self-contained and portable —
copy it anywhere (Raspberry Pi included) and it just works.

You normally do not need to edit anything in here.
"""
import os

# --- paths -------------------------------------------------------------------
ROOT = os.path.dirname(os.path.abspath(__file__))          # this deployment/ folder
OUTPUT_DIR = os.path.join(ROOT, "outputs")                 # models + saved overlays
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- severity classifier (MobileNetV2) ---------------------------------------
IMG_SIZE   = 160        # model input size; must match the trained model
ALPHA      = 0.5        # MobileNetV2 width multiplier; must match the trained model
BATCH      = 32         # inference batch size for the sliding window
LR         = 1e-3       # only used if the weights-only fallback rebuilds the model
FINETUNE_LR = 1e-5      # ditto (kept so model.py imports cleanly)

# 5-level severity ladder. Index == level == severity rank (0 = least severe).
LEVELS = [
    "Level 0 - Normal",
    "Level 1 - Ulcer/Wound",
    "Level 2 - Infection",
    "Level 3 - Ischaemia",
    "Level 4 - Both",
]

TASKS = {"severity": {"classes": LEVELS, "model": "severity_best.keras"}}

def model_path(task):
    return os.path.join(OUTPUT_DIR, TASKS[task]["model"])

# --- wound segmenter (U-Net) -------------------------------------------------
SEG_IMG_SIZE = 224                                         # U-Net input size
SEG_LR       = 1e-3                                        # only used if model is rebuilt
SEG_MODEL    = os.path.join(OUTPUT_DIR, "segment_best.keras")
