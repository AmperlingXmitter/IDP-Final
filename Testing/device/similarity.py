"""
=============================================================================
 SIMILARITY  (Testing/device/similarity.py)
-----------------------------------------------------------------------------
 Compares two wound images to assess capture consistency between visits.

 Original proof-of-concept: deployment/similarity.py (prototype).
 This version is a clean, importable module — no hardcoded paths, no
 module-level side effects.

 Why it matters
 --------------
 The AI models produce more reliable outputs when the wound is captured from
 a consistent angle and distance.  Comparing the new capture to the previous
 one for the same patient gives an early warning if the positioning changed
 significantly (low ORB matches) or the lighting/colour shifted (low hist
 score).  A low SSIM score can also flag large wound-area changes between
 visits, which may be clinically significant.

 Usage
 -----
   import similarity
   comp = similarity.compare_captures(prev_path, new_path)
   if not comp["consistent"]:
       print("Warning: images look very different — check positioning.")
   print(comp)
   # {'orb_matches': 412, 'hist_score': 0.94, 'ssim_score': 0.91,
   #  'consistent': True, 'error': None}

 Thresholds (from the prototype)
 --------------------------------
   ORB_MATCH_THRESHOLD  = 300   (feature matches)
   HIST_SCORE_THRESHOLD = 0.9   (colour histogram correlation, 0–1)
   SSIM_SCORE_THRESHOLD = 0.9   (structural similarity, 0–1)
 Adjust these in code if needed for your use case.

 Dependencies
 ------------
   opencv-python   (cv2)  — always required
   scikit-image           — for SSIM; gracefully skipped if unavailable
=============================================================================
"""
import cv2

try:
    from skimage.metrics import structural_similarity as _ssim_fn
    _SKIMAGE = True
except ImportError:
    _SKIMAGE = False

import config as C

# --------------------------------------------------------------------------- #
#  Thresholds
# --------------------------------------------------------------------------- #
ORB_MATCH_THRESHOLD  = 400   # min ORB feature matches to be "consistent"
HIST_SCORE_THRESHOLD = 0.95   # HSV histogram correlation (0–1)
SSIM_SCORE_THRESHOLD = 0.95   # structural similarity (0–1)


# --------------------------------------------------------------------------- #
#  Low-level comparators (internal)
# --------------------------------------------------------------------------- #

def _orb_compare(img_a, img_b):
    """ORB feature matching — returns number of descriptor matches."""
    gray_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create()
    _, des_a = orb.detectAndCompute(gray_a, None)
    _, des_b = orb.detectAndCompute(gray_b, None)
    if des_a is None or des_b is None:
        return 0
    bf      = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des_a, des_b)
    return len(matches)


def _histogram_compare(img_a, img_b):
    """
    HSV colour histogram correlation.
    Returns float in [0, 1] — higher means more similar colour distribution.
    """
    hsv_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2HSV)
    hsv_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2HSV)
    hist_a = cv2.calcHist([hsv_a], [0, 1], None, [50, 60], [0, 180, 0, 256])
    hist_b = cv2.calcHist([hsv_b], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist_a, hist_a, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    cv2.normalize(hist_b, hist_b, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    return float(cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL))


def _ssim_compare(img_a, img_b):
    """
    Structural Similarity Index.
    Returns float in [0, 1], or None if scikit-image is not installed.
    """
    if not _SKIMAGE:
        return None
    gray_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)
    if gray_a.shape != gray_b.shape:
        gray_b = cv2.resize(gray_b, (gray_a.shape[1], gray_a.shape[0]))
    h, w  = gray_a.shape
    win   = min(7, h, w)
    if win % 2 == 0:
        win -= 1
    if win < 3:
        return None
    score, _ = _ssim_fn(gray_a, gray_b, win_size=win, full=True)
    return float(score)


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #

def compare_captures(path_a, path_b):
    """
    Compare two image files (e.g. previous capture vs. new capture).

    Parameters
    ----------
    path_a : str  — reference image (e.g. the previous capture for this patient)
    path_b : str  — new image to compare against the reference

    Returns
    -------
    dict:
      orb_matches  (int)         number of ORB feature matches
      hist_score   (float)       HSV histogram correlation  0–1
      ssim_score   (float|None)  structural similarity      0–1, or None
      consistent   (bool)        True if all thresholds pass
      error        (str|None)    set if comparison failed (bad path, read error)
    """
    result = {
        "orb_matches": 0,
        "hist_score":  0.0,
        "ssim_score":  None,
        "consistent":  False,
        "error":       None,
    }
    try:
        img_a = cv2.imread(path_a)
        img_b = cv2.imread(path_b)
        if img_a is None or img_b is None:
            result["error"] = (
                f"Could not read image(s): {path_a!r} / {path_b!r}"
            )
            return result

        result["orb_matches"] = _orb_compare(img_a, img_b)
        result["hist_score"]  = _histogram_compare(img_a, img_b)
        result["ssim_score"]  = _ssim_compare(img_a, img_b)
        result["consistent"]  = is_consistent(result)

        if C.DEBUG:
            print(
                f"[similarity] ORB={result['orb_matches']}  "
                f"hist={result['hist_score']:.3f}  "
                f"ssim={result['ssim_score']}  "
                f"consistent={result['consistent']}"
            )
    except Exception as exc:
        result["error"] = str(exc)
        if C.DEBUG:
            print(f"[similarity] comparison failed: {exc}")

    return result


def is_consistent(comp):
    """
    Return True when all available metrics pass their thresholds
    (indicates the two images likely show the same wound area at a
    similar angle and lighting).
    """
    orb_ok  = comp.get("orb_matches", 0)   >= ORB_MATCH_THRESHOLD
    hist_ok = comp.get("hist_score",  0.0) >= HIST_SCORE_THRESHOLD
    ssim    = comp.get("ssim_score")
    ssim_ok = (ssim is None) or (ssim >= SSIM_SCORE_THRESHOLD)
    return orb_ok and hist_ok and ssim_ok


# --------------------------------------------------------------------------- #
#  Session consistency  (spec B "Reject Analysing Photos Too Dissimilar?")
# --------------------------------------------------------------------------- #
def session_consistency(image_paths):
    """
    Compare the N images of ONE capture session to each other (each image vs.
    the first) to decide if they show the same foot at a similar angle/lighting.

    Uses the SESSION thresholds in config (SESSION_SIM_MIN_ORB / _MIN_HIST) — a
    looser bar than the cross-visit thresholds above, because same-session
    photos are seconds apart. Returns the WORST (min) score across the pairs so
    one bad photo is enough to flag the session.

    Returns dict: orb (min int), hist (min float), ssim (min float|None),
    consistent (1 ok / 0 reject), error (str|None).
    """
    out = {"orb": None, "hist": None, "ssim": None, "consistent": 1, "error": None}
    if not image_paths or len(image_paths) < 2:
        return out                      # nothing to compare → treat as consistent

    ref = image_paths[0]
    orbs, hists, ssims = [], [], []
    for p in image_paths[1:]:
        comp = compare_captures(ref, p)
        if comp.get("error"):
            out["error"] = comp["error"]
            return out                  # comparison failed → don't block on it
        orbs.append(comp["orb_matches"])
        hists.append(comp["hist_score"])
        if comp["ssim_score"] is not None:
            ssims.append(comp["ssim_score"])

    out["orb"]  = min(orbs)
    out["hist"] = round(min(hists), 4)
    out["ssim"] = round(min(ssims), 4) if ssims else None
    min_orb  = getattr(C, "SESSION_SIM_MIN_ORB", 120)
    min_hist = getattr(C, "SESSION_SIM_MIN_HIST", 0.80)
    out["consistent"] = 1 if (out["orb"] >= min_orb and out["hist"] >= min_hist) else 0
    if C.DEBUG:
        print(f"[similarity] session: min ORB={out['orb']} min hist={out['hist']} "
              f"-> {'consistent' if out['consistent'] else 'REJECT'}")
    return out
