# =============================================================================
#  SEGMENTATION ENTRY POINT  -  deployment/segment_wound_size.py
#  Pixel ratio of wound vs foot/skin (U-Net trained on FUSeg).
# -----------------------------------------------------------------------------
#  INPUT  : a single image path (that's all).
#  OUTPUT : a result dict.  Run with --json to print it as one JSON line on
#           stdout so ANY language (Java/C++/PHP/Node/...) can parse it.
#
#  Python :  import sys; sys.path.insert(0, "<project>/deployment")
#            from segment_wound_size import segment
#            result = segment("foot.jpg")
#            wound  = result["wound_pct"]          # float, e.g. 3.5
#            foot   = result["foot_pct"]           # float, e.g. 96.5
#
#  CLI    :  python segment_wound_size.py foot.jpg            (human readable)
#            python segment_wound_size.py foot.jpg --json     (machine readable)
#            -> {"wound_pct": 3.5, "foot_pct": 96.5, "wound_pixels": 9173,
#                "total_pixels": 262144, "overlay_path": "outputs/seg_foot.jpg.png"}
# =============================================================================
import os, sys
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")   # silence TF logs on stdout
# self-contained: import the LOCAL copies of config/model/seg_model in this folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse, json
import numpy as np
import tensorflow as tf
import config as C
import seg_model  # noqa: F401  (registers dice_coef / bce_dice_loss for loading)

_MODEL = None


def _get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = tf.keras.models.load_model(C.SEG_MODEL, compile=False)
    return _MODEL


# -----------------------------------------------------------------------------
#  NON-GRANULATION WOUND-TISSUE RECOVERY  (no retraining needed)
#  The U-Net is trained on FUSeg, which is dominated by RED/PINK granulation
#  wounds, so it learns "red == wound" and under-detects other tissue types that
#  are still part of the wound (here, ~27% of FUSeg wounds are <50% red):
#     * eschar / gangrene / dry scab  -> BLACK / very dark
#     * slough (devitalised tissue)   -> YELLOW / tan
#     * pus / exudate                 -> PALE yellow / white / greenish
#  We use the U-Net mask as a SEED and region-grow it THROUGH adjacent tissue of
#  those colours, bounded to a region around the wound. Growth requires an
#  existing U-Net detection nearby and stops at healthy skin + at a bounded
#  radius, so shadows / callus / background elsewhere can't create phantom
#  wounds. Clinically correct for size tracking: all of this IS the wound.
#    necrosis_v      : brightness (0-255) below which a pixel is "dark" eschar.
#    recover_slough  : also recover yellow slough + pale pus/exudate.
#    necrosis_reach  : how far recovery may spread (fraction of image size).
# -----------------------------------------------------------------------------
def _dilate(mask, r):
    """Pure-numpy binary dilation by radius r (4-connected), no scipy/cv2 needed."""
    if r <= 0 or not mask.any():
        return mask
    m = mask.copy()
    for _ in range(int(r)):
        m[:-1, :] |= mask[1:, :]; m[1:, :] |= mask[:-1, :]
        m[:, :-1] |= mask[:, 1:]; m[:, 1:] |= mask[:, :-1]
        mask = m.copy()
    return m


def _rgb_to_hsv(rgb):
    """Vectorised RGB(uint8)->HSV. Returns h in [0,360), s and v in [0,1]."""
    a = rgb.astype(np.float32) / 255.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx = a.max(-1); mn = a.min(-1); d = mx - mn
    v = mx
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    dd = np.where(d > 1e-6, d, 1.0)
    h = np.where(mx == r, ((g - b) / dd) % 6,
        np.where(mx == g, (b - r) / dd + 2, (r - g) / dd + 4)) * 60.0
    return h % 360.0, s, v


def _recoverable_tissue(raw, necrosis_v=60, recover_slough=True):
    """Boolean masks of wound tissue the U-Net tends to MISS, by clinical type.
    Returns (recoverable, dark, slough)."""
    bright = raw.astype(np.int32).max(axis=2)          # value channel 0-255
    dark = bright < necrosis_v                          # eschar / gangrene / scab
    slough = np.zeros_like(dark)
    if recover_slough:
        h, s, v = _rgb_to_hsv(raw)
        nd = ~dark
        yellow_tan = nd & (h >= 22) & (h <= 70) & (v > 0.30) & (s > 0.25)   # slough
        pale_pus   = nd & (h >= 22) & (h <= 100) & (s <= 0.45) & (v > 0.55)  # pus/exudate
        slough = yellow_tan | pale_pus
    return (dark | slough), dark, slough


def _grow_into_wound_tissue(raw, base_mask, necrosis_v=60, recover_slough=True,
                            travel_mult=0.0, min_travel_frac=0.025):
    """Region-grow the U-Net detection THROUGH contiguous non-granulation wound
    tissue (dark eschar + yellow slough + pale pus), bounded so it stops at
    healthy skin and within a bounded radius of the seed. No-op without a seed.
    Returns (final_mask, eschar_added, slough_added).

    The reach is `min_travel_frac` of the image (a fixed margin cleanup), so the
    recovery acts as a light safety net around what the U-Net already finds.
    `travel_mult` (default 0) optionally adds reach proportional to the wound
    size; it is off by default because, with a well-trained segmenter, a large
    proportional reach over-segments heavily necrotic limbs."""
    if not base_mask.any():
        z = np.zeros_like(base_mask)
        return base_mask, z, z
    recoverable, dark, slough = _recoverable_tissue(raw, necrosis_v, recover_slough)
    seed_radius = (base_mask.sum() / np.pi) ** 0.5      # equiv-disc radius of the seed
    big = max(raw.shape[:2])
    # Reach = a fixed fraction of the image (min_travel_frac), optionally extended
    # for large wounds (travel_mult, default 0), clamped to [8 px, 30% of frame].
    floor = min_travel_frac * big
    r_max = int(np.clip(max(travel_mult * seed_radius, floor), 8, 0.30 * big))
    # Region-grow as a GEODESIC flood through contiguous recoverable tissue: the
    # frontier advances from the seed along the wound, re-derived each step (NOT a
    # fixed disc ROI), so it follows ELONGATED shapes along their length while the
    # step budget (r_max) still bounds how far it can travel into a dark/pale bg.
    allowed = base_mask | recoverable
    region = base_mask.copy()
    for _ in range(r_max // 2 + 2):                     # bounded geodesic distance from seed
        grown = _dilate(region, 2) & allowed
        if grown.sum() == region.sum():
            break
        region = grown
    added = region & (~base_mask)
    eschar_added = added & dark
    slough_added = added & slough & (~dark)
    return region, eschar_added, slough_added


# -----------------------------------------------------------------------------
#  MAIN API  -  INPUT = image_path,  OUTPUT = result dict
# -----------------------------------------------------------------------------
def segment(image_path, thresh=0.5, save_overlay=True, save_closeup=True, out_dir=C.OUTPUT_DIR,
            grow_necrosis=True, recover_slough=True, necrosis_v=60, necrosis_reach=0.025):
    model = _get_model()
    size = C.SEG_IMG_SIZE

    raw = tf.image.decode_image(tf.io.read_file(image_path), channels=3,
                                expand_animations=False).numpy()
    H, W = raw.shape[:2]
    inp = tf.image.resize(raw, [size, size]).numpy() / 255.0
    pred = model.predict(inp[None], verbose=0)[0, :, :, 0]
    prob = tf.image.resize(pred[..., None], [H, W]).numpy()[:, :, 0]
    base_mask = prob >= thresh

    # Recover non-granulation wound tissue (dark eschar + yellow slough/pus).
    if grow_necrosis:
        mask, eschar, slough = _grow_into_wound_tissue(
            raw, base_mask, necrosis_v=necrosis_v, recover_slough=recover_slough,
            min_travel_frac=necrosis_reach)
    else:
        z = np.zeros_like(base_mask); mask, eschar, slough = base_mask, z, z

    wound_px = int(mask.sum())
    base_px = int(base_mask.sum())
    necrosis_px = int(eschar.sum())
    slough_px = int(slough.sum())
    total = int(H * W)
    wound_pct = 100.0 * wound_px / total
    foot_pct = 100.0 - wound_pct

    overlay_path = _save_overlay(raw, base_mask, eschar, slough, image_path, out_dir) if save_overlay else None
    closeup_path = _save_closeup(raw, mask, image_path, out_dir) if save_closeup else None

    return {
        "wound_pct": round(wound_pct, 2),
        "foot_pct": round(foot_pct, 2),
        "wound_pixels": wound_px,
        "total_pixels": total,
        "base_wound_pixels": base_px,      # U-Net only (red/granulation)
        "necrosis_pixels": necrosis_px,    # dark eschar/gangrene recovered
        "slough_pixels": slough_px,        # yellow slough + pale pus recovered
        "overlay_path": overlay_path,      # photo + tissue-tinted wound, native res, NO chrome
        "closeup_path": closeup_path,      # cropped close-up of the wound (closeups/ subfolder)
    }


def _save_overlay(raw, base_mask, eschar, slough, image_path, out_dir, alpha=0.45):
    """Save the ORIGINAL photo with the wound tinted by tissue type, at the photo's
    native resolution. No background panel, no text (those numbers are in the JSON
    for the app to render). Tints follow the clinical legend used by the desktop
    app: granulation = RED, slough/pus = YELLOW, eschar/necrosis = BLACK.
    Uses Pillow only (no matplotlib needed)."""
    try:
        from PIL import Image
        os.makedirs(out_dir, exist_ok=True)
        out = raw.astype(np.float32).copy()
        gran = base_mask & (~eschar) & (~slough)
        # granulation = red, eschar/necrosis = black, slough/pus = yellow
        for m, col in ((gran, (224, 48, 30)), (eschar, (17, 17, 17)), (slough, (242, 194, 0))):
            if m.any():
                for c in range(3):
                    out[..., c][m] = (1 - alpha) * out[..., c][m] + alpha * col[c]
        path = os.path.join(out_dir, "seg_" + os.path.basename(image_path) + ".png")
        Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(path)
        return path
    except Exception as e:
        print(f"  (overlay skipped: {e})", file=sys.stderr)
        return None


def _save_closeup(raw, mask, image_path, out_dir, pad_frac=0.15, sub="closeups"):
    """Crop the wound region (bounding box + margin) out of the ORIGINAL photo and
    save it, unmarked, to a `closeups/` subfolder — a clean zoomed-in image of just
    the wound for the clinician to review. Returns the path, or None if no wound."""
    try:
        from PIL import Image
        if not mask.any():
            return None
        ys, xs = np.where(mask)
        y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
        ph = int((y1 - y0 + 1) * pad_frac) + 8           # margin around the wound
        pw = int((x1 - x0 + 1) * pad_frac) + 8
        H, W = raw.shape[:2]
        y0, y1 = max(0, y0 - ph), min(H, y1 + ph + 1)
        x0, x1 = max(0, x0 - pw), min(W, x1 + pw + 1)
        d = os.path.join(out_dir, sub)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "closeup_" + os.path.basename(image_path) + ".png")
        Image.fromarray(raw[y0:y1, x0:x1].astype(np.uint8)).save(path)
        return path
    except Exception as e:
        print(f"  (closeup skipped: {e})", file=sys.stderr)
        return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="path to a foot photo")
    ap.add_argument("--thresh", type=float, default=0.5)
    ap.add_argument("--no-overlay", action="store_true", help="skip saving the overlay PNG")
    ap.add_argument("--no-closeup", action="store_true", help="skip saving the cropped wound close-up")
    ap.add_argument("--no-necrosis", action="store_true",
                    help="disable ALL non-granulation recovery (eschar + slough/pus)")
    ap.add_argument("--no-slough", action="store_true",
                    help="recover dark eschar only; skip yellow slough / pale pus")
    ap.add_argument("--necrosis-v", type=int, default=60,
                    help="darkness cutoff 0-255 for eschar (higher = catch more dark tissue)")
    ap.add_argument("--necrosis-reach", type=float, default=0.025,
                    help="how far recovery spreads from the wound (frac of image; "
                         "higher = recover more / risk over-segmenting, ~0.02-0.05)")
    ap.add_argument("--json", action="store_true", help="print one JSON line to stdout")
    args = ap.parse_args()

    result = segment(args.image, thresh=args.thresh, save_overlay=not args.no_overlay,
                     save_closeup=not args.no_closeup,
                     grow_necrosis=not args.no_necrosis, recover_slough=not args.no_slough,
                     necrosis_v=args.necrosis_v, necrosis_reach=args.necrosis_reach)

    if args.json:
        print(json.dumps(result))                 # <-- the only stdout line
    else:
        print("\n================ SEGMENTATION ================")
        print(f"  Image      : {os.path.basename(args.image)}")
        print(f"  Wound      : {result['wound_pct']:.2f}%  ({result['wound_pixels']} px)")
        print(f"    U-Net    : {result['base_wound_pixels']} px  (red/granulation)")
        print(f"    Eschar   : {result['necrosis_pixels']} px  (dark necrotic recovered)")
        print(f"    Slough   : {result['slough_pixels']} px  (yellow slough/pus recovered)")
        print(f"  Foot/skin  : {result['foot_pct']:.2f}%")
        if result["overlay_path"]:
            print(f"  Overlay    -> {result['overlay_path']}")
        if result["closeup_path"]:
            print(f"  Close-up   -> {result['closeup_path']}")
        print("==============================================\n")
