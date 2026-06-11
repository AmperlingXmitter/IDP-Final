"""
=============================================================================
 DATA SOURCE  (Testing/desktop/data_source.py)
-----------------------------------------------------------------------------
 The desktop app talks ONLY to this layer, never directly to a DB or the cloud.
 Two interchangeable backends with the SAME interface:

   LocalSource(db_path)        -> the SQLite file the device writes (offline)
   FirebaseSource()            -> Firestore over REST (the cloud, free tier)

 Pick one with get_source("local"|"firebase").  The UI code is identical for
 both.  Images:
   - LocalSource  reads JP/PNG files from disk and base64-encodes them.
   - FirebaseSource reads the compressed base64 string stored in each capture
     document (free-tier design — no Cloud Storage bucket needed).

 Common interface every source provides:
   patients()                          -> triage list (urgent first)
   captures(patient_id)                -> capture rows oldest -> newest
   rate_of_change(pid, days)           -> wound %/day slope
   update_capture(row_id, dict)        -> edit a row (testing)
   get_patient(pid)                    -> {patient_id, name, dob, notes} | {}
   upsert_patient(pid, name, dob, notes)
   get_capture_images(row)             -> (captured_data_uri|None, overlay_data_uri|None)
   diagnostics()                       -> {ok, backend, message, n_patients, n_captures, sample}

 'stamp' is "YYYYMMDD_HHMMSS"; parsed to datetimes for the graphs.
=============================================================================
"""
import base64
import datetime
import io
import json
import os
import sqlite3
import statistics
import urllib.error
import urllib.parse
import urllib.request

# --------------------------------------------------------------------------- #
#  Shared palette + UT stage names  (kept in sync with device ai.py/config.py)
# --------------------------------------------------------------------------- #
LEVEL_COLOURS = {0: "#2e7d32", 1: "#f9a825", 2: "#ef6c00",
                 3: "#c62828", 4: "#6a1b9a", -1: "#546e7a"}

# UT Diabetic Wound Classification (matches the labels the device stores).
# UT staging tops out at Stage D; AI level 4 is reported as Stage D (most
# severe) with a "severe/advanced" descriptor rather than a new stage.
LEVEL_NAMES = {0: "UT A · Clean", 1: "UT B · Infected",
               2: "UT C · Ischaemic", 3: "UT D · Isch.+Infected",
               4: "UT D · Severe", -1: "No wound"}

# --------------------------------------------------------------------------- #
#  Triage thresholds  — EDIT THESE to tune what counts as "needs attention"
# --------------------------------------------------------------------------- #
URGENT_LEVEL       = 2      # UT stage C (ischaemia) or worse → urgent
URGENT_ROC_PER_DAY = 0.2    # wound growing faster than this (%/day) → urgent

# Optional Pillow (image resize before base64). Falls back to raw bytes.
try:
    from PIL import Image as _PILImage
    _PIL = True
except ImportError:
    _PIL = False


# --------------------------------------------------------------------------- #
#  Helpers shared by every backend
# --------------------------------------------------------------------------- #
def parse_stamp(stamp):
    """'20260609_142530' -> datetime, or None on bad input."""
    try:
        return datetime.datetime.strptime(stamp, "%Y%m%d_%H%M%S")
    except (ValueError, TypeError):
        return None


def compute_roc(rows, days):
    """Least-squares slope of wound_pct over the last `days`, in %/day.
    Returns None if fewer than 2 usable points."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    pts = []
    for r in rows:
        dt = parse_stamp(r.get("stamp"))
        if dt and dt >= cutoff and r.get("wound_pct") is not None:
            pts.append((dt.timestamp() / 86400.0, r["wound_pct"]))
    if len(pts) < 2:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    return round(slope, 4)


def roc_endpoints(rows, days):
    """Rate of change using ONLY the FIRST and LAST reading within the window
    (spec item #10): %/day = (last_wound - first_wound) / (days between them).

    This matches exactly what a clinician reads off the visible trend graph:
    if the graph shows the past 7 days, the rate uses the first and last point
    that appear in that 7-day view. Returns None if fewer than 2 usable points
    or if both readings share the same timestamp."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    pts = []
    for r in rows:
        dt = parse_stamp(r.get("stamp"))
        if dt and dt >= cutoff and r.get("wound_pct") is not None:
            pts.append((dt, r["wound_pct"]))
    if len(pts) < 2:
        return None
    pts.sort(key=lambda p: p[0])
    (first_dt, first_y), (last_dt, last_y) = pts[0], pts[-1]
    span_days = (last_dt - first_dt).total_seconds() / 86400.0
    if span_days <= 0:
        return None
    return round((last_y - first_y) / span_days, 4)


# --------------------------------------------------------------------------- #
#  SESSIONS  (spec E1: a "session" = the N images captured together)
#  Group capture rows into sessions and expose the AVERAGE reading + the spread
#  of the individual readings (for the trend error bars). Works for both
#  backends: LOCAL stores N rows per session (shared session_id/stamp); FIREBASE
#  stores one averaged doc per session that also carries image_wound_pcts (JSON)
#  so the per-image spread can still be drawn.
# --------------------------------------------------------------------------- #
def _first_not_none(members, key):
    for m in members:
        if m.get(key) is not None:
            return m.get(key)
    return None


def sessions(rows):
    """Group capture rows into sessions, newest LAST (chronological).
    Each session dict: session_id, patient_id, stamp, dt, n_images,
    avg_level/stage/label, avg_wound_pct, avg_foot_pct, wound_vals (the
    individual readings for the error bar), wound_min/max, foot_angle,
    tissue {base_wound_px, slough_px, necrosis_px} sums, members[], rep."""
    import json
    groups, order = {}, []
    for r in rows:
        key = r.get("session_id") or r.get("stamp")
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)

    out = []
    for key in order:
        members = sorted(groups[key], key=lambda m: (m.get("image_index") or 0))
        stamp = _first_not_none(members, "stamp")
        vals = [m["wound_pct"] for m in members if m.get("wound_pct") is not None]
        stored_avg = _first_not_none(members, "avg_wound_pct")

        # firebase single-doc session may carry the per-image spread as JSON
        img_arr = None
        raw_arr = _first_not_none(members, "image_wound_pcts")
        if raw_arr is not None:
            try:
                parsed = json.loads(raw_arr) if isinstance(raw_arr, str) else raw_arr
                img_arr = [v for v in parsed if v is not None]
            except Exception:
                img_arr = None

        if stored_avg is not None:
            avg_wound = stored_avg
        elif vals:
            avg_wound = round(sum(vals) / len(vals), 2)
        elif img_arr:
            avg_wound = round(sum(img_arr) / len(img_arr), 2)
        else:
            avg_wound = None

        spread = vals if len(vals) > 1 else (img_arr if (img_arr and len(img_arr) > 1) else vals)
        fvals = [m["foot_pct"] for m in members if m.get("foot_pct") is not None]
        stored_favg = _first_not_none(members, "avg_foot_pct")
        avg_level = _first_not_none(members, "avg_level")
        if avg_level is None:                 # firebase doc: highest_level holds the avg
            avg_level = _first_not_none(members, "highest_level")

        tissue = {}
        for k in ("base_wound_px", "slough_px", "necrosis_px"):
            s = sum(m.get(k) or 0 for m in members)
            tissue[k] = s if s > 0 else None

        out.append({
            "session_id": key,
            "patient_id": _first_not_none(members, "patient_id"),
            "stamp": stamp, "dt": parse_stamp(stamp),
            "n_images": _first_not_none(members, "n_images") or len(members),
            "avg_level": avg_level,
            "avg_stage": _first_not_none(members, "avg_stage"),
            "avg_label": _first_not_none(members, "avg_label")
                         or _first_not_none(members, "highest_label"),
            "avg_wound_pct": avg_wound,
            "avg_foot_pct": stored_favg if stored_favg is not None
                            else (round(sum(fvals) / len(fvals), 2) if fvals else None),
            "wound_vals": spread,
            "wound_min": min(spread) if spread else None,
            "wound_max": max(spread) if spread else None,
            "foot_angle": _first_not_none(members, "foot_angle"),
            "tissue": tissue,
            "members": members,
            "rep": members[0] if members else {},
        })
    out.sort(key=lambda s: (s["dt"] or datetime.datetime.min))
    return out


def session_trend(sess_list, days, min_gap_days=7):
    """Trend over the SESSION AVERAGE points within the visible `days` window.
    Spec E1: needs >=2 average points separated by >=7 days, else 'too little
    data'. Returns dict: ok, reason, n, earliest, latest, roc_per_day,
    total_change, span_days. earliest/latest are session dicts (for labels)."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    pts = [s for s in sess_list
           if s.get("avg_wound_pct") is not None and s.get("dt") and s["dt"] >= cutoff]
    pts.sort(key=lambda s: s["dt"])
    if len(pts) < 2:
        return {"ok": False, "reason": "too_little_data", "n": len(pts),
                "earliest": pts[0] if pts else None,
                "latest": pts[-1] if pts else None}
    earliest, latest = pts[0], pts[-1]
    span = (latest["dt"] - earliest["dt"]).total_seconds() / 86400.0
    if span < min_gap_days:
        return {"ok": False, "reason": "too_little_data", "n": len(pts),
                "earliest": earliest, "latest": latest, "span_days": round(span, 1)}
    roc = (latest["avg_wound_pct"] - earliest["avg_wound_pct"]) / span
    return {"ok": True, "n": len(pts), "earliest": earliest, "latest": latest,
            "roc_per_day": round(roc, 4),
            "total_change": round(latest["avg_wound_pct"] - earliest["avg_wound_pct"], 2),
            "span_days": round(span, 1)}


def age_from_dob(dob):
    """'1958-03-14' -> integer age in whole years, or None if unparseable."""
    if not dob:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            b = datetime.datetime.strptime(str(dob).strip(), fmt).date()
            break
        except ValueError:
            b = None
    if b is None:
        return None
    today = datetime.date.today()
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def _is_urgent(latest, roc):
    """Triage rule for the 'needs attention' highlight.
    Thresholds are the module constants above — edit those to tune."""
    lvl = latest.get("highest_level")
    if lvl is not None and lvl >= URGENT_LEVEL:
        return True
    if roc is not None and roc > URGENT_ROC_PER_DAY:
        return True
    return False


def summarise_patient(pid, rows, meta, roc):
    """Build one triage-list row from a patient's captures + metadata."""
    latest = rows[-1]
    meta = meta or {}
    series = [r.get("wound_pct") for r in rows]
    n_pts  = sum(1 for v in series if v is not None)
    return {
        "patient_id":  pid,
        "name":        meta.get("name") or "",
        "gender":      meta.get("gender") or "",
        "dob":         meta.get("dob") or "",
        "age":         age_from_dob(meta.get("dob")),
        "wound_site":  meta.get("wound_site") or "",
        "n":           len(rows),
        "level":       latest.get("highest_level"),
        "level_name":  LEVEL_NAMES.get(latest.get("highest_level"), "?"),
        "wound_pct":   latest.get("wound_pct"),
        "wound_series": series,            # for the card sparkline
        "has_trend":   n_pts >= 2,         # spec #1/#4: show "no trend data" if False
        "last_seen":   latest.get("dt"),
        "roc_per_day": roc,
        "urgent":      _is_urgent(latest, roc),
    }


def _sort_triage(out):
    out.sort(key=lambda p: (not p["urgent"],
                            -(p["level"] if p["level"] is not None else -1),
                            -(p["roc_per_day"] or 0)))
    return out


def _bytes_to_data_uri(raw, mime):
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _file_to_data_uri(path, max_px=900):
    """Load an image file, downscale, return a data URI (or None)."""
    if not path or not os.path.exists(path):
        return None
    try:
        if _PIL:
            img = _PILImage.open(path)
            img.thumbnail((max_px, max_px), _PILImage.LANCZOS)
            buf = io.BytesIO()
            ext = os.path.splitext(path)[1].lower()
            fmt = "PNG" if ext == ".png" else "JPEG"
            img.save(buf, format=fmt, quality=85)
            return _bytes_to_data_uri(buf.getvalue(),
                                      "image/png" if fmt == "PNG" else "image/jpeg")
        with open(path, "rb") as f:
            raw = f.read()
        ext = os.path.splitext(path)[1].lower()
        return _bytes_to_data_uri(raw, "image/png" if ext == ".png" else "image/jpeg")
    except Exception:
        return None


# =========================================================================== #
#  LOCAL SQLite backend
# =========================================================================== #
class LocalSource:
    backend = "local"

    def __init__(self, db_path):
        self.db_path = db_path
        self._ensure_patients_table()
        self._ensure_capture_cols()

    def _con(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    # ---- patients table --------------------------------------------------
    #  Columns added over time (gender, wound_site) are migrated in-place so an
    #  older demo_dfu.db keeps working without a manual reseed.
    _PATIENT_EXTRA_COLS = {"gender": "TEXT", "wound_site": "TEXT",
                           "wound_points": "TEXT"}    # JSON: manual DFU markers

    def _ensure_capture_cols(self):
        """Add foot_angle to an existing captures table if it pre-dates it (so
        staff can edit side/bottom on demo DBs without a reseed)."""
        try:
            con = self._con()
            have = {r["name"] for r in con.execute("PRAGMA table_info(captures)")}
            if have and "foot_angle" not in have:
                con.execute("ALTER TABLE captures ADD COLUMN foot_angle TEXT")
            con.commit()
            con.close()
        except Exception:
            pass

    def _ensure_patients_table(self):
        try:
            con = self._con()
            con.execute("""
                CREATE TABLE IF NOT EXISTS patients (
                    patient_id TEXT PRIMARY KEY,
                    name       TEXT,
                    dob        TEXT,
                    notes      TEXT,
                    gender     TEXT,
                    wound_site TEXT,
                    created_at TEXT NOT NULL DEFAULT ''
                )
            """)
            # Migrate older DBs that pre-date the gender / wound_site columns.
            have = {r["name"] for r in con.execute("PRAGMA table_info(patients)")}
            for col, typ in self._PATIENT_EXTRA_COLS.items():
                if col not in have:
                    con.execute(f"ALTER TABLE patients ADD COLUMN {col} {typ}")
            con.commit()
            con.close()
        except Exception:
            pass

    def get_patient(self, patient_id):
        try:
            con = self._con()
            row = con.execute(
                "SELECT * FROM patients WHERE patient_id=?", (patient_id,)
            ).fetchone()
            con.close()
            return dict(row) if row else {}
        except Exception:
            return {}

    def upsert_patient(self, patient_id, name=None, dob=None, notes=None,
                       gender=None, wound_site=None, wound_points=None):
        con = self._con()
        con.execute("""
            INSERT INTO patients
                (patient_id, name, dob, notes, gender, wound_site, wound_points, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(patient_id) DO UPDATE SET
                name=excluded.name, dob=excluded.dob, notes=excluded.notes,
                gender=excluded.gender, wound_site=excluded.wound_site,
                wound_points=excluded.wound_points
        """, (patient_id, name or "", dob or "", notes or "",
              gender or "", wound_site or "", wound_points or "",
              datetime.datetime.now().isoformat(timespec="seconds")))
        con.commit()
        con.close()

    # ---- captures --------------------------------------------------------
    def captures(self, patient_id):
        con = self._con()
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM captures WHERE patient_id=? ORDER BY stamp", (patient_id,))]
        con.close()
        for r in rows:
            dt = parse_stamp(r["stamp"])
            r["dt"] = dt.isoformat() if dt else None
        return rows

    def patients(self):
        con = self._con()
        ids = [r["patient_id"] for r in con.execute(
            "SELECT DISTINCT patient_id FROM captures ORDER BY patient_id")]
        con.close()
        out = []
        for pid in ids:
            rows = self.captures(pid)
            if not rows:
                continue
            roc = roc_endpoints(rows, 30)
            out.append(summarise_patient(pid, rows, self.get_patient(pid), roc))
        return _sort_triage(out)

    def rate_of_change(self, patient_id, days=30):
        return compute_roc(self.captures(patient_id), days)

    def roc_window(self, patient_id, days=30):
        """Endpoint rate of change (first vs last reading in the window)."""
        return roc_endpoints(self.captures(patient_id), days)

    def update_capture(self, row_id, fields):
        # 'stamp' is editable so the capture date/time can be corrected (spec #7);
        # 'foot_angle' is the side/bottom selection (spec E1).
        allowed = {"highest_level", "highest_label", "wound_pct",
                   "foot_pct", "patient_id", "stamp", "foot_angle"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        cols = ", ".join(f"{k}=?" for k in sets)
        con = self._con()
        con.execute(f"UPDATE captures SET {cols} WHERE id=?",
                    (*sets.values(), row_id))
        con.commit()
        con.close()

    def get_capture_images(self, row):
        return (_file_to_data_uri(row.get("captured_path")),
                _file_to_data_uri(row.get("overlay_path")))

    def diagnostics(self):
        try:
            con = self._con()
            n_caps = con.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
            con.close()
            pats = self.patients()
            return {"ok": True, "backend": "local",
                    "message": f"Connected to {os.path.basename(self.db_path)}",
                    "n_patients": len(pats), "n_captures": n_caps,
                    "sample": pats[:5]}
        except Exception as e:
            return {"ok": False, "backend": "local", "message": str(e),
                    "n_patients": 0, "n_captures": 0, "sample": []}


# =========================================================================== #
#  FIREBASE (Firestore REST) backend  — free tier, images as base64 strings
# =========================================================================== #
FIREBASE_PROJECT_ID = os.environ.get("DFU_FB_PROJECT", "ai-assisted-dfu-monitoring-1")
FIREBASE_API_KEY    = os.environ.get("DFU_FB_KEY",
                                     "AIzaSyCh6Un4cg6-BR7mvQA3y6UseKraWulJJmw")

_CAP_SCALAR_FIELDS = [
    "patient_id", "stamp", "created_at", "highest_level", "highest_label",
    "wound_pct", "foot_pct", "window_counts",
    "sim_orb", "sim_hist", "sim_ssim", "sim_consistent", "sim_prev_id",
    "base_wound_px", "necrosis_px", "slough_px",
    "captured_name", "overlay_name",
    # session fields written by the device (spec E1): lets the desktop draw the
    # per-image spread + averages + foot angle from a single averaged doc.
    "n_images", "avg_stage", "foot_angle",
    "image_wound_pcts", "image_levels", "image_stages",
]


def _fs_decode(value):
    """Firestore value dict -> python scalar."""
    if "stringValue" in value:    return value["stringValue"]
    if "integerValue" in value:   return int(value["integerValue"])
    if "doubleValue" in value:    return float(value["doubleValue"])
    if "booleanValue" in value:   return bool(value["booleanValue"])
    if "nullValue" in value:      return None
    if "timestampValue" in value: return value["timestampValue"]
    return None


def _fs_doc_fields(doc):
    return {k: _fs_decode(v) for k, v in (doc.get("fields") or {}).items()}


def _fs_encode(value):
    if value is None:            return {"nullValue": None}
    if isinstance(value, bool):  return {"booleanValue": value}
    if isinstance(value, int):   return {"integerValue": str(value)}
    if isinstance(value, float): return {"doubleValue": value}
    return {"stringValue": str(value)}


class FirebaseSource:
    backend = "firebase"

    def __init__(self, project_id=None, api_key=None, timeout=20):
        self.project_id = project_id or FIREBASE_PROJECT_ID
        self.api_key    = api_key or FIREBASE_API_KEY
        self.timeout    = timeout
        self.base = (f"https://firestore.googleapis.com/v1/projects/"
                     f"{self.project_id}/databases/(default)/documents")

    # ---- low-level REST --------------------------------------------------
    def _get(self, path, params=None):
        query = [("key", self.api_key)] + list(params or [])
        url = f"{self.base}/{path}?{urllib.parse.urlencode(query, doseq=True)}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _patch(self, path, fields, update_mask=None):
        query = [("key", self.api_key)]
        for fp in (update_mask or list(fields.keys())):
            query.append(("updateMask.fieldPaths", fp))
        url = f"{self.base}/{path}?{urllib.parse.urlencode(query, doseq=True)}"
        body = json.dumps({"fields": {k: _fs_encode(v) for k, v in fields.items()}}
                          ).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="PATCH",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _list(self, path, params=None, page_size=300):
        """List documents under a collection, following pagination."""
        docs, token = [], None
        base_params = list(params or []) + [("pageSize", str(page_size))]
        while True:
            p = list(base_params)
            if token:
                p.append(("pageToken", token))
            data = self._get(path, p)
            docs.extend(data.get("documents", []))
            token = data.get("nextPageToken")
            if not token:
                break
        return docs

    @staticmethod
    def _id_from_name(name):
        return name.rsplit("/", 1)[-1] if name else None

    # ---- patients --------------------------------------------------------
    def _patient_ids(self):
        """All patient IDs. showMissing=true surfaces parents that only have a
        captures subcollection (the device never writes the parent doc)."""
        try:
            docs = self._list("patients",
                              params=[("showMissing", "true"),
                                      ("mask.fieldPaths", "name")])
            ids = [self._id_from_name(d.get("name")) for d in docs]
            ids = [i for i in ids if i]
            if ids:
                return sorted(set(ids))
        except Exception:
            pass
        # Fallback: discover patient IDs from the captures collection group.
        try:
            return sorted(self._collection_group_patient_ids())
        except Exception:
            return []

    def _collection_group_patient_ids(self):
        url = (f"https://firestore.googleapis.com/v1/projects/{self.project_id}"
               f"/databases/(default)/documents:runQuery?key={self.api_key}")
        body = json.dumps({"structuredQuery": {
            "from": [{"collectionId": "captures", "allDescendants": True}],
            "select": {"fields": [{"fieldPath": "patient_id"}]},
        }}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ids = set()
        for row in data:
            doc = row.get("document")
            if doc:
                f = _fs_doc_fields(doc)
                if f.get("patient_id"):
                    ids.add(f["patient_id"])
        return ids

    def get_patient(self, patient_id):
        try:
            doc = self._get(f"patients/{patient_id}")
            f = _fs_doc_fields(doc)
            return {"patient_id": patient_id,
                    "name": f.get("name", ""), "dob": f.get("dob", ""),
                    "notes": f.get("notes", ""),
                    "gender": f.get("gender", ""),
                    "wound_site": f.get("wound_site", ""),
                    "wound_points": f.get("wound_points", "")}
        except Exception:
            return {}

    def upsert_patient(self, patient_id, name=None, dob=None, notes=None,
                       gender=None, wound_site=None, wound_points=None):
        self._patch(f"patients/{patient_id}",
                    {"name": name or "", "dob": dob or "", "notes": notes or "",
                     "gender": gender or "", "wound_site": wound_site or "",
                     "wound_points": wound_points or ""},
                    update_mask=["name", "dob", "notes", "gender", "wound_site",
                                 "wound_points"])

    # ---- captures --------------------------------------------------------
    def captures(self, patient_id):
        mask = [("mask.fieldPaths", f) for f in _CAP_SCALAR_FIELDS]
        try:
            docs = self._list(f"patients/{patient_id}/captures", params=mask)
        except Exception:
            return []
        rows = []
        for d in docs:
            r = _fs_doc_fields(d)
            r.setdefault("patient_id", patient_id)
            # The Firestore document ID is a STABLE key (set once by the device).
            # The editable timestamp lives in the 'stamp' FIELD, which is what the
            # trends / graphs / ROC all read. Keeping them separate means staff can
            # correct a capture's date/time (the field) without ever moving the
            # document — nothing downstream breaks.
            doc_id = self._id_from_name(d.get("name"))
            r["doc_id"] = doc_id
            r["stamp"]  = r.get("stamp") or doc_id     # display/trend timestamp (editable)
            r["id"]     = f"{patient_id}/{doc_id}"     # edit key = stable document id
            dt = parse_stamp(r["stamp"])
            r["dt"] = dt.isoformat() if dt else None
            rows.append(r)
        rows.sort(key=lambda r: r.get("stamp") or "")
        return rows

    def patients(self):
        out = []
        for pid in self._patient_ids():
            rows = self.captures(pid)
            if not rows:
                continue
            roc = roc_endpoints(rows, 30)
            out.append(summarise_patient(pid, rows, self.get_patient(pid), roc))
        return _sort_triage(out)

    def rate_of_change(self, patient_id, days=30):
        return compute_roc(self.captures(patient_id), days)

    def roc_window(self, patient_id, days=30):
        """Endpoint rate of change (first vs last reading in the window)."""
        return roc_endpoints(self.captures(patient_id), days)

    def update_capture(self, row_id, fields):
        # row_id is "patient_id/doc_id" for the Firebase backend. 'stamp' is the
        # editable timestamp FIELD (it is NOT the document id, so editing it is safe
        # and the trends/graphs that read the field update accordingly).
        if "/" not in str(row_id):
            return
        pid, doc_id = str(row_id).split("/", 1)
        allowed = {"highest_level", "highest_label", "wound_pct", "foot_pct",
                   "stamp", "foot_angle"}
        sets = {k: v for k, v in fields.items()
                if k in allowed and v is not None}
        if not sets:
            return
        try:
            self._patch(f"patients/{pid}/captures/{doc_id}", sets,
                        update_mask=list(sets.keys()))
        except Exception:
            pass

    def get_capture_images(self, row):
        """Fetch only the two base64 image fields for one capture, on demand.
        Uses the stable document id (doc_id), not the editable 'stamp' field."""
        pid    = row.get("patient_id")
        doc_id = row.get("doc_id") or row.get("stamp")
        if not pid or not doc_id:
            return (None, None)
        try:
            doc = self._get(f"patients/{pid}/captures/{doc_id}",
                            params=[("mask.fieldPaths", "captured_b64"),
                                    ("mask.fieldPaths", "overlay_b64")])
            f = _fs_doc_fields(doc)
        except Exception:
            return (None, None)

        def _uri(b64):
            if not b64:
                return None
            try:
                return _bytes_to_data_uri(base64.b64decode(b64), "image/jpeg")
            except Exception:
                return None

        return (_uri(f.get("captured_b64")), _uri(f.get("overlay_b64")))

    def diagnostics(self):
        """Live connection test for the verify tab."""
        try:
            ids = self._patient_ids()
            total_caps, sample = 0, []
            for pid in ids:
                rows = self.captures(pid)
                total_caps += len(rows)
                roc = compute_roc(rows, 30)
                if rows:
                    sample.append(summarise_patient(pid, rows,
                                                    self.get_patient(pid), roc))
            return {"ok": True, "backend": "firebase",
                    "message": f"Connected to Firestore project '{self.project_id}'",
                    "n_patients": len(ids), "n_captures": total_caps,
                    "sample": _sort_triage(sample)[:8]}
        except urllib.error.HTTPError as e:
            return {"ok": False, "backend": "firebase",
                    "message": f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}",
                    "n_patients": 0, "n_captures": 0, "sample": []}
        except Exception as e:
            return {"ok": False, "backend": "firebase",
                    "message": f"{type(e).__name__}: {e}",
                    "n_patients": 0, "n_captures": 0, "sample": []}


# --------------------------------------------------------------------------- #
#  Factory
# --------------------------------------------------------------------------- #
def get_source(backend="local", db_path=None):
    if backend == "firebase":
        return FirebaseSource()
    return LocalSource(db_path)
