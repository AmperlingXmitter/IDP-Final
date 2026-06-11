# =============================================================================
#  CLASSIFICATION ENTRY POINT  -  deployment/predict_severity_class.py
#  "highest ulcer level on the foot".  (Pixel ratio lives in segment_wound_size.py)
# -----------------------------------------------------------------------------
#  INPUT  : a single image path (that's all).
#  OUTPUT : a result dict.  Run with --json to print it as one JSON line on
#           stdout so ANY language (Java/C++/PHP/Node/...) can parse it.
#
#  Python :  import sys; sys.path.insert(0, "<project>/deployment")
#            from predict_severity_class import classify
#            result = classify("foot.jpg")
#            level  = result["highest_level"]      # int 0..4  (-1 = nothing)
#            label  = result["highest_label"]      # str, e.g. "Level 2 - Infection"
#
#  CLI    :  python predict_severity_class.py foot.jpg            (human readable)
#            python predict_severity_class.py foot.jpg --json     (machine readable)
#            -> {"highest_level": 2, "highest_label": "Level 2 - Infection",
#                "window_counts": {...}}
# =============================================================================
import os, sys
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")   # silence TF logs on stdout
# self-contained: import the LOCAL copies of config/model/seg_model in this folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse, json
import numpy as np
import tensorflow as tf
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
import config as C

S = C.IMG_SIZE
MAX_SIDE = 768           # downscale big photos before sliding (keeps the Pi in RAM)
_MODEL = None            # cached model so an app pays the load cost only once


def _get_model():
    global _MODEL
    if _MODEL is None:
        path = C.model_path("severity")
        try:
            _MODEL = tf.keras.models.load_model(path, compile=False)
        except Exception as e:
            wpath = path.replace(".keras", ".weights.h5")
            print(f"[warn] full .keras load failed ({type(e).__name__}: {e}). "
                  f"Rebuilding + loading weights from {os.path.basename(wpath)}",
                  file=sys.stderr)
            from model import build_model
            m = build_model(len(C.LEVELS), imagenet=False)
            m.load_weights(wpath)
            _MODEL = m
    return _MODEL


def _windows(h, w, stride):
    ys = list(range(0, max(1, h - S + 1), stride)) or [0]
    xs = list(range(0, max(1, w - S + 1), stride)) or [0]
    if h >= S and ys[-1] != h - S: ys.append(h - S)
    if w >= S and xs[-1] != w - S: xs.append(w - S)
    return [(y, x) for y in ys for x in xs]


# -----------------------------------------------------------------------------
#  MAIN API  -  INPUT = image_path,  OUTPUT = result dict
# -----------------------------------------------------------------------------
def classify(image_path, stride=S // 2, conf=0.5):
    model = _get_model()
    n = len(C.LEVELS)

    raw = tf.io.read_file(image_path)
    raw = tf.image.decode_image(raw, channels=3, expand_animations=False).numpy()
    h, w = raw.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1.0:
        raw = tf.image.resize(raw, [int(h * scale), int(w * scale)]).numpy().astype(np.uint8)
        h, w = raw.shape[:2]
    if h < S or w < S:
        raw = np.pad(raw, ((0, max(0, S - h)), (0, max(0, S - w)), (0, 0)))
        h, w = raw.shape[:2]

    coords = _windows(h, w, stride)
    patches = np.stack([raw[y:y + S, x:x + S].astype(np.float32) for y, x in coords])
    probs = model.predict(preprocess_input(patches), batch_size=C.BATCH, verbose=0)

    levels = np.argmax(probs, axis=1)
    confs = probs.max(axis=1)
    confident = levels[confs >= conf]
    abnormal = confident[confident >= 1]
    if abnormal.size:
        highest_level = int(abnormal.max())
    elif (levels == 0).any():
        highest_level = 0
    else:
        highest_level = -1
    highest_label = C.LEVELS[highest_level] if highest_level >= 0 else "No skin/ulcer detected"

    return {
        "highest_level": highest_level,
        "highest_label": highest_label,
        "window_counts": {C.LEVELS[i]: int((levels == i).sum()) for i in range(n)},
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="path to a foot/leg photo")
    ap.add_argument("--stride", type=int, default=S // 2)
    ap.add_argument("--conf", type=float, default=0.5)
    ap.add_argument("--json", action="store_true", help="print one JSON line to stdout")
    args = ap.parse_args()

    result = classify(args.image, stride=args.stride, conf=args.conf)

    if args.json:
        print(json.dumps(result))                 # <-- the only stdout line
    else:
        print("\n============== CLASSIFICATION ==============")
        print(f"  Image          : {os.path.basename(args.image)}")
        print(f"  HIGHEST LEVEL  : {result['highest_label']}")
        print(f"  window counts  : {result['window_counts']}")
        print("============================================\n")
