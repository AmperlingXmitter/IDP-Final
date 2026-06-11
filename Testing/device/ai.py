"""
=============================================================================
 AI WRAPPER  (Testing/device/ai.py)
-----------------------------------------------------------------------------
 Thin bridge to the ASSISTANT's AI in C.DEPLOYMENT_DIR (now new_deployment) via
 Method A — in-process Python (fastest, per DEPLOYMENT.md). It adds the folder
 to sys.path and calls:
     classify(image_path) -> highest_level, highest_label, window_counts
     segment(image_path)  -> wound_pct, foot_pct, tissue px, overlay_path,
                             closeup_path   (cropped wound, new_deployment only)

 Models load once (the deployment caches them) so only the FIRST call is slow.

 Multi-image session (spec B2)
 -----------------------------
   analyse_session([img1, img2, img3])  ->  per-image outputs + AVERAGED outputs.
   The UT stage is averaged with A=1..D=4 and rounded to the nearest letter.
   File naming / moving is NOT done here — storage.finalize_session() renames
   everything to the moment of FINAL AI output (spec B "Image Labelling").
=============================================================================
"""
import os, sys, json, time
import config as C

_loaded = False


def _ensure_imported():
    """Add DEPLOYMENT_DIR to sys.path and import the two entry modules once."""
    global _loaded, classify, segment
    if _loaded:
        return
    if not os.path.isdir(C.DEPLOYMENT_DIR):
        raise FileNotFoundError(
            f"deployment folder not found: {C.DEPLOYMENT_DIR}\n"
            "Set DFU_DEPLOYMENT_DIR env var or fix DEPLOYMENT_DIR in config.py")
    sys.path.insert(0, C.DEPLOYMENT_DIR)
    # The device's config.py is cached as sys.modules['config']. Temporarily
    # pop it so the deployment imports ITS OWN config.py (IMG_SIZE, ALPHA, …).
    _device_cfg = sys.modules.pop("config", None)
    try:
        from predict_severity_class import classify as _classify   # noqa
        from segment_wound_size import segment as _segment         # noqa
    finally:
        if _device_cfg is not None:
            sys.modules["config"] = _device_cfg
    globals()["classify"] = _classify
    globals()["segment"] = _segment
    _loaded = True
    if C.DEBUG:
        print(f"[ai] deployment imported from {C.DEPLOYMENT_DIR}")


def warm_up():
    """Import + load models now (e.g. during consent) so the first capture is
    fast. First classify()/segment() call triggers the actual model load."""
    _ensure_imported()
    if C.DEBUG:
        print("[ai] warming models…")


# --------------------------------------------------------------------------- #
#  Single-image inference  (raw — no file moving; paths point at deployment out)
# --------------------------------------------------------------------------- #
def analyse_one(image_path):
    """
    Run classify + segment on ONE image, honouring RUN_CLASSIFY / RUN_SEGMENT.
    Returns a raw dict. overlay_src / closeup_src point at the deployment's
    output folder; storage.finalize_session() moves+renames them later.
    """
    _ensure_imported()
    out = {
        "highest_level": None, "highest_label": None, "window_counts": None,
        "wound_pct": None, "foot_pct": None,
        "base_wound_px": None, "necrosis_px": None, "slough_px": None,
        "overlay_src": None, "closeup_src": None,
    }

    if C.RUN_CLASSIFY:
        t0 = time.monotonic()
        cls = classify(image_path)
        if C.DEBUG_TIMING:
            print(f"[ai] classify: {time.monotonic()-t0:.2f}s -> {cls['highest_label']}")
        level = cls["highest_level"]
        out["highest_level"] = level
        # Per-image UT label (Stages A–D); fall back to deployment label if level
        # is outside the map (e.g. -1 = nothing detected).
        out["highest_label"] = C.UT_LABELS.get(level, cls["highest_label"])
        out["window_counts"] = json.dumps(cls.get("window_counts", {}))

    if C.RUN_SEGMENT:
        t1 = time.monotonic()
        seg = segment(image_path, thresh=C.SEG_THRESHOLD,
                      save_overlay=C.SAVE_OVERLAY, save_closeup=C.SAVE_CLOSEUP)
        if C.DEBUG_TIMING:
            print(f"[ai] segment : {time.monotonic()-t1:.2f}s -> wound {seg['wound_pct']}%")
        out["wound_pct"]    = seg.get("wound_pct")
        out["foot_pct"]     = seg.get("foot_pct")
        out["base_wound_px"] = seg.get("base_wound_pixels")
        out["necrosis_px"]  = seg.get("necrosis_pixels")
        out["slough_px"]    = seg.get("slough_pixels")
        out["overlay_src"]  = seg.get("overlay_path")     # native-res tinted overlay
        out["closeup_src"]  = seg.get("closeup_path")     # cropped wound (display)

    return out


# --------------------------------------------------------------------------- #
#  UT-stage averaging  (PURE function — unit-tested without TensorFlow)
# --------------------------------------------------------------------------- #
def average_session(per_image):
    """
    Average a list of per-image dicts into one session summary (spec B2).

      * UT stage: convert each image's level -> UT letter -> number (A=1..D=4),
        take the mean, round to the NEAREST letter (ties round UP = more severe,
        the clinically safer choice). Images with level -1 (no ulcer/skin
        detected) are excluded from the stage average.
      * avg_level: mean of valid levels, rounded (back-compat headline number).
      * avg_wound_pct / avg_foot_pct: mean over images that produced a value.

    Returns dict: avg_stage ('A'..'D' or '?'), avg_label, avg_level,
    avg_wound_pct, avg_foot_pct.
    """
    levels = [p.get("highest_level") for p in per_image]

    stage_nums = []
    for lv in levels:
        if lv is None or lv < 0:          # -1 / None → no ulcer; skip in average
            continue
        letter = C.LEVEL_TO_STAGE.get(lv)
        if letter:
            stage_nums.append(C.UT_STAGE_NUM[letter])

    if stage_nums:
        mean_num  = sum(stage_nums) / len(stage_nums)
        nearest   = max(1, min(4, int(mean_num + 0.5)))   # nearest; .5 → up
        avg_stage = C.UT_NUM_STAGE[nearest]
        avg_label = C.UT_STAGE_LABELS[avg_stage]
    else:
        avg_stage = "?"
        avg_label = "No ulcer detected"

    valid_levels = [lv for lv in levels if lv is not None and lv >= 0]
    if valid_levels:
        avg_level = int(sum(valid_levels) / len(valid_levels) + 0.5)
    elif levels:
        avg_level = -1
    else:
        avg_level = None

    wps = [p["wound_pct"] for p in per_image if p.get("wound_pct") is not None]
    fps = [p["foot_pct"]  for p in per_image if p.get("foot_pct")  is not None]
    avg_wound = round(sum(wps) / len(wps), 2) if wps else None
    avg_foot  = round(sum(fps) / len(fps), 2) if fps else None

    return {
        "avg_stage": avg_stage,
        "avg_label": avg_label,
        "avg_level": avg_level,
        "avg_wound_pct": avg_wound,
        "avg_foot_pct": avg_foot,
    }


# --------------------------------------------------------------------------- #
#  Whole-session inference  (analyse all N images, then average)
# --------------------------------------------------------------------------- #
def analyse_session(image_paths):
    """
    Analyse every image in `image_paths` (the N session captures) and return:
        { "n_images": N,
          "per_image": [ {index, highest_level, highest_label, stage, wound_pct,
                          foot_pct, tissue px, window_counts,
                          overlay_src, closeup_src}, … ],
          "avg_stage", "avg_label", "avg_level", "avg_wound_pct", "avg_foot_pct" }
    Does NOT move/rename files (storage.finalize_session does, using the final
    AI-output timestamp).
    """
    per_image = []
    for i, path in enumerate(image_paths, start=1):
        res = analyse_one(path)
        lv = res.get("highest_level")
        res["index"] = i
        res["stage"] = C.LEVEL_TO_STAGE.get(lv) if (lv is not None and lv >= 0) else "?"
        per_image.append(res)
        if C.DEBUG:
            print(f"[ai] image {i}/{len(image_paths)}: stage {res['stage']} "
                  f"wound {res.get('wound_pct')}%")

    summary = average_session(per_image)
    summary["n_images"] = len(image_paths)
    summary["per_image"] = per_image
    if C.DEBUG:
        print(f"[ai] SESSION avg: stage {summary['avg_stage']} "
              f"wound {summary['avg_wound_pct']}%")
    return summary


# --------------------------------------------------------------------------- #
#  Back-compat: single-image analyse() used by the headless console loop.
# --------------------------------------------------------------------------- #
def analyse(image_path, stamp=None):
    """One image, flat dict (legacy headless path). Overlay/closeup left in the
    deployment output folder; caller may move them if desired."""
    res = analyse_one(image_path)
    res["overlay_path"] = res.get("overlay_src")
    res["closeup_path"] = res.get("closeup_src")
    return res
