"""
=============================================================================
 cloud_api.py — Firebase (Firestore) REST client  (Phase 2)
-----------------------------------------------------------------------------
 Free-tier design (no Blaze / no credit card):
   As of Feb 2026 Firebase's free Spark plan no longer includes Cloud Storage,
   so we DO NOT use Storage buckets. Instead every image is downscaled +
   JPEG-compressed and stored as a base64 STRING inside the Firestore document.
   Firestore's hard limit is ~1 MiB per document, so we budget each image well
   under that (see _IMG_* below). Full-resolution originals always stay on the
   Pi's MicroSD — only a compressed copy goes to the cloud.

 Firestore layout:
   patients/{patient_id}                         <- patient metadata (desktop writes)
   patients/{patient_id}/captures/{stamp}        <- one capture record (device writes)

 Capture document fields:
   patient_id, stamp, created_at, highest_level, highest_label,
   wound_pct, foot_pct, window_counts (json str),
   sim_orb, sim_hist, sim_ssim, sim_consistent, sim_prev_id,
   captured_name, overlay_name,            <- basenames (paths are Pi-local, not uploaded)
   captured_b64, overlay_b64               <- compressed JPEG, base64 (may be absent)

 Usage from main.py:
   cloud_api.upload_record_async(rec)   # fire-and-forget after each capture
   cloud_api.sync_unsynced()            # flush any offline backlog (call at startup)
=============================================================================
"""

import base64
import io
import json
import os
import threading
import urllib.error
import urllib.request

import config as C

FIREBASE_PROJECT_ID = "ai-assisted-dfu-monitoring-1"
FIREBASE_API_KEY    = "AIzaSyCh6Un4cg6-BR7mvQA3y6UseKraWulJJmw"

_BASE = (
    f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
    f"/databases/(default)/documents"
)

# ---- Image compression budget (keep the whole doc < 1 MiB) ------------------
_IMG_MAX_PX        = 800       # longest side of the cloud copy
_IMG_BYTE_BUDGET   = 300_000   # target max raw JPEG bytes per image (base64 ≈ +33%)
_IMG_MIN_QUALITY   = 35        # don't drop JPEG quality below this
_UPLOAD_IMAGES     = True      # master switch for attaching image strings

# Fields we never push to the cloud (Pi-local absolute paths are useless there).
_SKIP_FIELDS = {"captured_path", "overlay_path", "synced"}


# --------------------------------------------------------------------------- #
#  Image -> compressed base64 string
# --------------------------------------------------------------------------- #
def _compress_to_b64(path, max_px=_IMG_MAX_PX, budget=_IMG_BYTE_BUDGET):
    """Downscale + JPEG-compress an image until it fits `budget` raw bytes,
    then return a base64 ASCII string (no data-URI prefix). None on failure."""
    if not path or not os.path.exists(path):
        return None
    try:
        from PIL import Image
    except ImportError:
        if C.DEBUG:
            print("[cloud] Pillow not available — cannot compress images")
        return None
    try:
        img = Image.open(path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((max_px, max_px), Image.LANCZOS)

        quality = 80
        while True:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            raw = buf.getvalue()
            if len(raw) <= budget or quality <= _IMG_MIN_QUALITY:
                break
            quality -= 10
        return base64.b64encode(raw).decode("ascii")
    except Exception as e:
        if C.DEBUG:
            print(f"[cloud] image compress failed ({path}): {e}")
        return None


# --------------------------------------------------------------------------- #
#  Firestore value encoding
# --------------------------------------------------------------------------- #
def _to_firestore(value):
    if value is None:            return {"nullValue": None}
    if isinstance(value, bool):  return {"booleanValue": value}
    if isinstance(value, int):   return {"integerValue": str(value)}
    if isinstance(value, float): return {"doubleValue": value}
    return {"stringValue": str(value)}


def _build_payload(rec):
    """Turn a capture record dict into a Firestore document body, attaching
    compressed base64 images and dropping Pi-local paths."""
    fields = {k: _to_firestore(v) for k, v in rec.items() if k not in _SKIP_FIELDS}

    # Keep human-readable basenames (handy in the console) without the path.
    cap_path = rec.get("captured_path")
    ovl_path = rec.get("overlay_path")
    if cap_path:
        fields["captured_name"] = _to_firestore(os.path.basename(cap_path))
    if ovl_path:
        fields["overlay_name"] = _to_firestore(os.path.basename(ovl_path))

    if _UPLOAD_IMAGES:
        cap_b64 = _compress_to_b64(cap_path)
        if cap_b64:
            fields["captured_b64"] = _to_firestore(cap_b64)
        ovl_b64 = _compress_to_b64(ovl_path)
        if ovl_b64:
            fields["overlay_b64"] = _to_firestore(ovl_b64)

    return json.dumps({"fields": fields}).encode("utf-8")


# --------------------------------------------------------------------------- #
#  Upload one record
# --------------------------------------------------------------------------- #
def upload_record(rec: dict) -> bool:
    patient_id = rec.get("patient_id", "unknown")
    stamp      = rec.get("stamp", "unknown")
    url = (f"{_BASE}/patients/{patient_id}/captures/{stamp}"
           f"?key={FIREBASE_API_KEY}")
    try:
        payload = _build_payload(rec)
    except Exception as e:
        print(f"[cloud] payload build failed: {e}")
        return False

    if C.DEBUG:
        print(f"[cloud] uploading {patient_id}/{stamp}  ({len(payload)//1024} KiB)")

    req = urllib.request.Request(
        url, data=payload, method="PATCH",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
            print(f"[cloud] ✓ uploaded record {rec.get('id')} → {patient_id}/{stamp}")
            return True
    except urllib.error.HTTPError as e:
        print(f"[cloud] HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    except Exception as e:
        print(f"[cloud] error (offline?): {e}")
    return False


def upload_record_async(rec: dict) -> None:
    """Fire-and-forget. Marks the row synced in the local DB on success."""
    def _run():
        if upload_record(rec):
            _mark_synced_safe(rec.get("id"))
    threading.Thread(target=_run, daemon=True).start()


# --------------------------------------------------------------------------- #
#  Upload a whole SESSION  (spec C: averaged session doc + per-image subdocs)
# -----------------------------------------------------------------------------
#  Firestore layout (free Spark plan, no Storage bucket — images are base64):
#    patients/{pid}/captures/{session_id}            <- averaged headline doc
#         highest_level/label/wound_pct/foot_pct = AVERAGES (desktop reads these
#         as one row), plus avg_stage, n_images, sim_*, per-image scalar arrays,
#         and the 1st image's captured_b64/overlay_b64 as a representative thumb.
#    patients/{pid}/captures/{session_id}/images/{i} <- one doc per image, each
#         with that image's captured_b64 + overlay_b64 + closeup_b64 (kept well
#         under Firestore's ~1 MiB/doc limit by splitting images across docs).
# --------------------------------------------------------------------------- #
def _build_session_payload(session):
    """Averaged headline doc for patients/{pid}/captures/{session_id}."""
    imgs = session.get("images", [])
    rep  = imgs[0] if imgs else {}
    fields = {
        "patient_id":    _to_firestore(session.get("patient_id")),
        "stamp":         _to_firestore(session.get("stamp")),
        "created_at":    _to_firestore(rep.get("created_at")),
        # Averages mapped onto the headline fields the desktop already reads:
        "highest_level": _to_firestore(session.get("avg_level")),
        "highest_label": _to_firestore(session.get("avg_label")),
        "wound_pct":     _to_firestore(session.get("avg_wound_pct")),
        "foot_pct":      _to_firestore(session.get("avg_foot_pct")),
        # Session extras:
        "avg_stage":     _to_firestore(session.get("avg_stage")),
        "n_images":      _to_firestore(session.get("n_images")),
        "foot_angle":    _to_firestore(session.get("foot_angle")),
        "sim_consistent": _to_firestore(session.get("sim_consistent")),
        "image_levels":  _to_firestore(json.dumps([i.get("highest_level") for i in imgs])),
        "image_stages":  _to_firestore(json.dumps([i.get("stage") for i in imgs])),
        "image_wound_pcts": _to_firestore(json.dumps([i.get("wound_pct") for i in imgs])),
    }
    # Representative thumbnail = 1st image (so existing single-image viewers work).
    if rep.get("captured_path"):
        fields["captured_name"] = _to_firestore(os.path.basename(rep["captured_path"]))
        if _UPLOAD_IMAGES:
            b = _compress_to_b64(rep.get("captured_path"))
            if b:
                fields["captured_b64"] = _to_firestore(b)
    # Prefer the cropped close-up as the representative overlay (it's what the
    # Results screen shows); fall back to the full overlay.
    rep_ovl = rep.get("closeup_path") or rep.get("overlay_path")
    if rep_ovl:
        fields["overlay_name"] = _to_firestore(os.path.basename(rep_ovl))
        if _UPLOAD_IMAGES:
            b = _compress_to_b64(rep_ovl)
            if b:
                fields["overlay_b64"] = _to_firestore(b)
    return json.dumps({"fields": fields}).encode("utf-8")


def _build_image_payload(img):
    """One per-image doc: that image's captured + overlay + closeup base64."""
    fields = {
        "image_index":   _to_firestore(img.get("image_index")),
        "highest_level": _to_firestore(img.get("highest_level")),
        "stage":         _to_firestore(img.get("stage")),
        "wound_pct":     _to_firestore(img.get("wound_pct")),
        "foot_pct":      _to_firestore(img.get("foot_pct")),
        "base_wound_px": _to_firestore(img.get("base_wound_px")),
        "necrosis_px":   _to_firestore(img.get("necrosis_px")),
        "slough_px":     _to_firestore(img.get("slough_px")),
    }
    if _UPLOAD_IMAGES:
        for key, path in (("captured_b64", img.get("captured_path")),
                          ("overlay_b64",  img.get("overlay_path")),
                          ("closeup_b64",  img.get("closeup_path"))):
            b = _compress_to_b64(path)
            if b:
                fields[key] = _to_firestore(b)
    return json.dumps({"fields": fields}).encode("utf-8")


def _patch(url, payload):
    req = urllib.request.Request(url, data=payload, method="PATCH",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def upload_session(session: dict) -> bool:
    """Upload the averaged session doc + one doc per image. Returns success."""
    pid = session.get("patient_id", "unknown")
    sid = session.get("session_id", "unknown")
    base = f"{_BASE}/patients/{pid}/captures/{sid}"
    try:
        if C.DEBUG:
            print(f"[cloud] uploading session {pid}/{sid} "
                  f"({session.get('n_images')} images)")
        _patch(f"{base}?key={FIREBASE_API_KEY}", _build_session_payload(session))
        for img in session.get("images", []):
            idx = img.get("image_index")
            _patch(f"{base}/images/{idx}?key={FIREBASE_API_KEY}",
                   _build_image_payload(img))
        print(f"[cloud] ✓ uploaded session {pid}/{sid}")
        return True
    except urllib.error.HTTPError as e:
        print(f"[cloud] HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    except Exception as e:
        print(f"[cloud] session upload error (offline?): {e}")
    return False


def upload_session_async(session: dict) -> None:
    """Fire-and-forget session upload; marks rows synced locally on success."""
    def _run():
        if upload_session(session):
            try:
                import storage
                storage.mark_session_synced(session.get("session_id"))
            except Exception as e:
                print(f"[cloud] mark_session_synced failed: {e}")
    threading.Thread(target=_run, daemon=True).start()


def _mark_synced_safe(row_id):
    if row_id is None:
        return
    try:
        import storage
        storage.mark_synced(row_id)
    except Exception as e:
        print(f"[cloud] mark_synced failed: {e}")


# --------------------------------------------------------------------------- #
#  Offline backlog flush  (low-connectivity friendly)
# --------------------------------------------------------------------------- #
def sync_unsynced() -> int:
    """Flush every locally-stored SESSION that hasn't synced yet. Returns the
    count of sessions uploaded. Safe to call at startup and whenever Wi-Fi
    returns. Runs in the calling thread — wrap in a thread to avoid blocking.

    Low-connectivity friendly: stops on the first failure (likely offline) so it
    doesn't hammer a dead link, and retries the remaining backlog next time."""
    try:
        import storage
        session_ids = storage.unsynced_sessions()
    except Exception as e:
        print(f"[cloud] could not read unsynced sessions: {e}")
        return 0
    if not session_ids:
        if C.DEBUG:
            print("[cloud] no backlog to sync")
        return 0
    print(f"[cloud] flushing {len(session_ids)} unsynced session(s)…")
    done = 0
    for sid in session_ids:
        rows = storage.get_session(sid)
        if not rows:
            continue
        head = rows[0]
        session = {
            "session_id": sid, "patient_id": head.get("patient_id"),
            "stamp": head.get("stamp"), "n_images": head.get("n_images"),
            "avg_level": head.get("avg_level"), "avg_stage": head.get("avg_stage"),
            "avg_label": head.get("avg_label"),
            "avg_wound_pct": head.get("avg_wound_pct"),
            "avg_foot_pct": head.get("avg_foot_pct"),
            "sim_consistent": head.get("sim_consistent"),
            "images": rows,
        }
        if upload_session(session):
            storage.mark_session_synced(sid)
            done += 1
        else:
            print("[cloud] upload failed; will retry backlog later")
            break
    print(f"[cloud] backlog sync complete: {done}/{len(session_ids)} session(s)")
    return done


def sync_unsynced_async() -> None:
    threading.Thread(target=sync_unsynced, daemon=True).start()
