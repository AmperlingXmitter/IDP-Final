"""
=============================================================================
 STORAGE  (Testing/device/storage.py)
-----------------------------------------------------------------------------
 - Creates the Image/{...} folders on first run.
 - SESSION model (spec A/B): one capture session = N images. All N share a
   session_id; the AVERAGED result is denormalised onto every row so the
   gallery + desktop can read a session as a single entry.
 - Image LABELLING (spec B): captured / overlay / closeup files are named with
   the moment of FINAL AI output, not the capture time:
       {PATIENT_ID}_{final_stamp}_{index}{suffix}
   so the 3 images of one session sort together as 1st / 2nd / 3rd.
 - Local SQLite store works fully offline; the cloud sync reads unsynced rows.
=============================================================================
"""
import os, shutil, sqlite3, datetime
import config as C


# --------------------------------------------------------------------------- #
#  Folders + filenames
# --------------------------------------------------------------------------- #
def ensure_folders():
    """Create every folder we need if missing (safe to call repeatedly)."""
    for d in C.ALL_FOLDERS:
        os.makedirs(d, exist_ok=True)
    os.makedirs(_tmp_dir(), exist_ok=True)
    if C.DEBUG:
        print(f"[storage] folders ready under {C.IMAGE_ROOT}")


def make_stamp():
    """Timestamp string used in filenames AND the DB. Sorts chronologically.
    For a session this is taken at the moment of FINAL AI output (spec B)."""
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _tmp_dir():
    return os.path.join(C.CAPTURE_FOLDER, "_session_tmp")


def new_session_temp_paths(n):
    """Return N temp capture paths for an in-progress session. They are renamed
    to their final {id}_{stamp}_{i} names by finalize_session() once AI is done."""
    d = _tmp_dir()
    os.makedirs(d, exist_ok=True)
    return [os.path.join(d, f"cap_{i}.jpg") for i in range(1, n + 1)]


def _final_name(pid, stamp, index, suffix, ext):
    """e.g. P001_20260611_142530_1_overlay.png — sorts by patient, time, index."""
    tag = f"_{suffix}" if suffix else ""
    return f"{pid}_{stamp}_{index}{tag}.{ext}"


# --------------------------------------------------------------------------- #
#  Local database
# --------------------------------------------------------------------------- #
def _connect():
    con = sqlite3.connect(C.DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    """Create the captures table if missing, then migrate new columns."""
    con = _connect()
    con.execute("""
        CREATE TABLE IF NOT EXISTS captures (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id    TEXT    NOT NULL,
            session_id    TEXT,                   -- groups the N images of one session
            image_index   INTEGER,                -- 1..N within the session
            n_images      INTEGER,                -- how many images in the session
            foot_angle    TEXT,                   -- 'side' or 'bottom' (chosen on Selection)
            stamp         TEXT    NOT NULL,        -- 20260611_142530 (final AI-output time)
            captured_path TEXT    NOT NULL,
            overlay_path  TEXT,                    -- native-res tissue-tinted overlay
            closeup_path  TEXT,                    -- cropped wound (shown on Results)
            highest_level INTEGER,                 -- this image: 0..4, -1 none, NULL if AI off
            highest_label TEXT,
            stage         TEXT,                    -- this image's UT stage letter (A..D / ?)
            wound_pct     REAL,
            foot_pct      REAL,
            window_counts TEXT,                    -- JSON string
            -- session AVERAGES (denormalised onto every row):
            avg_level     INTEGER,
            avg_stage     TEXT,                    -- A..D or ?
            avg_label     TEXT,
            avg_wound_pct REAL,
            avg_foot_pct  REAL,
            -- within-session similarity (positioning consistency):
            sim_orb       INTEGER,
            sim_hist      REAL,
            sim_ssim      REAL,
            sim_consistent INTEGER,                -- 1 ok, 0 inconsistent, NULL not checked
            sim_prev_id   INTEGER,
            base_wound_px INTEGER,
            necrosis_px   INTEGER,
            slough_px     INTEGER,
            synced        INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT    NOT NULL
        )
    """)
    con.commit()
    con.close()
    _migrate_db()
    if C.DEBUG:
        print(f"[storage] DB ready: {C.DB_PATH}")


def _migrate_db():
    """Idempotent: add columns introduced in later versions to an existing DB."""
    new_cols = [
        ("session_id", "TEXT"), ("image_index", "INTEGER"), ("n_images", "INTEGER"),
        ("foot_angle", "TEXT"), ("closeup_path", "TEXT"), ("stage", "TEXT"),
        ("avg_level", "INTEGER"), ("avg_stage", "TEXT"), ("avg_label", "TEXT"),
        ("avg_wound_pct", "REAL"), ("avg_foot_pct", "REAL"),
        ("sim_orb", "INTEGER"), ("sim_hist", "REAL"), ("sim_ssim", "REAL"),
        ("sim_consistent", "INTEGER"), ("sim_prev_id", "INTEGER"),
        ("base_wound_px", "INTEGER"), ("necrosis_px", "INTEGER"), ("slough_px", "INTEGER"),
    ]
    con = _connect()
    for col, ctype in new_cols:
        try:
            con.execute(f"ALTER TABLE captures ADD COLUMN {col} {ctype}")
        except sqlite3.OperationalError:
            pass   # column already exists
    con.commit()
    con.close()


_COLUMNS = [
    "patient_id", "session_id", "image_index", "n_images", "foot_angle", "stamp",
    "captured_path", "overlay_path", "closeup_path",
    "highest_level", "highest_label", "stage", "wound_pct", "foot_pct",
    "window_counts", "avg_level", "avg_stage", "avg_label",
    "avg_wound_pct", "avg_foot_pct",
    "sim_orb", "sim_hist", "sim_ssim", "sim_consistent", "sim_prev_id",
    "base_wound_px", "necrosis_px", "slough_px",
]


def _insert_row(con, rec):
    cols = ", ".join(_COLUMNS)
    qs   = ", ".join("?" for _ in _COLUMNS)
    cur = con.execute(
        f"INSERT INTO captures ({cols}, synced, created_at) VALUES ({qs}, 0, ?)",
        [rec.get(c) for c in _COLUMNS]
        + [datetime.datetime.now().isoformat(timespec="seconds")],
    )
    return cur.lastrowid


# --------------------------------------------------------------------------- #
#  Finalize a session: rename images to final-AI-output time + save N rows
# --------------------------------------------------------------------------- #
def finalize_session(patient_id, temp_capture_paths, summary, sim=None,
                     foot_angle=None):
    """
    temp_capture_paths : the N temp capture files (in capture order).
    summary            : dict from ai.analyse_session() (per_image + averages).
    sim                : optional dict {orb, hist, ssim, consistent} for the session.
    foot_angle         : 'side' or 'bottom' (chosen on the Selection screen).

    Renames every captured/overlay/closeup file to the FINAL-AI-output timestamp
    and inserts one DB row per image (averages denormalised onto each).
    Returns a session record dict ready for the cloud + the Results screen.
    """
    stamp      = make_stamp()                       # moment of final AI output
    session_id = f"{patient_id}_{stamp}"
    per_image  = summary.get("per_image", [])
    n          = summary.get("n_images", len(temp_capture_paths))
    sim        = sim or {}

    con = _connect()
    rows = []
    for i, tmp in enumerate(temp_capture_paths, start=1):
        ai_res = per_image[i - 1] if i - 1 < len(per_image) else {}

        # 1) captured image -> final name
        cap_final = os.path.join(
            C.CAPTURE_FOLDER, _final_name(patient_id, stamp, i, "", "jpg"))
        _safe_move(tmp, cap_final)

        # 2) overlay (native-res tinted) -> Overlay_Images
        ovl_final = None
        if ai_res.get("overlay_src") and os.path.exists(ai_res["overlay_src"]):
            ovl_final = os.path.join(
                C.OVERLAY_FOLDER, _final_name(patient_id, stamp, i, "overlay", "png"))
            _safe_move(ai_res["overlay_src"], ovl_final)

        # 3) cropped close-up -> Closeup_Images (shown on Results when present)
        clo_final = None
        if ai_res.get("closeup_src") and os.path.exists(ai_res["closeup_src"]):
            clo_final = os.path.join(
                C.CLOSEUP_FOLDER, _final_name(patient_id, stamp, i, "closeup", "png"))
            _safe_move(ai_res["closeup_src"], clo_final)

        rec = {
            "patient_id": patient_id, "session_id": session_id,
            "image_index": i, "n_images": n, "foot_angle": foot_angle,
            "stamp": stamp,
            "captured_path": cap_final, "overlay_path": ovl_final,
            "closeup_path": clo_final,
            "highest_level": ai_res.get("highest_level"),
            "highest_label": ai_res.get("highest_label"),
            "stage": ai_res.get("stage"),
            "wound_pct": ai_res.get("wound_pct"),
            "foot_pct": ai_res.get("foot_pct"),
            "window_counts": ai_res.get("window_counts"),
            "avg_level": summary.get("avg_level"),
            "avg_stage": summary.get("avg_stage"),
            "avg_label": summary.get("avg_label"),
            "avg_wound_pct": summary.get("avg_wound_pct"),
            "avg_foot_pct": summary.get("avg_foot_pct"),
            "sim_orb": sim.get("orb"), "sim_hist": sim.get("hist"),
            "sim_ssim": sim.get("ssim"), "sim_consistent": sim.get("consistent"),
            "sim_prev_id": None,
            "base_wound_px": ai_res.get("base_wound_px"),
            "necrosis_px": ai_res.get("necrosis_px"),
            "slough_px": ai_res.get("slough_px"),
        }
        rec["id"] = _insert_row(con, rec)
        rows.append(rec)
    con.commit()
    con.close()
    if C.DEBUG:
        print(f"[storage] saved session {session_id}: {len(rows)} image(s), "
              f"avg stage {summary.get('avg_stage')}")

    return {
        "session_id": session_id, "patient_id": patient_id, "stamp": stamp,
        "n_images": n, "foot_angle": foot_angle,
        "avg_level": summary.get("avg_level"), "avg_stage": summary.get("avg_stage"),
        "avg_label": summary.get("avg_label"),
        "avg_wound_pct": summary.get("avg_wound_pct"),
        "avg_foot_pct": summary.get("avg_foot_pct"),
        "sim_consistent": sim.get("consistent"),
        "images": rows,
    }


def _safe_move(src, dst):
    try:
        shutil.move(src, dst)
    except Exception as e:
        if C.DEBUG:
            print(f"[storage] move failed {src} -> {dst}: {e}")


def cleanup_session_temp():
    """Remove any leftover temp captures (e.g. after a reset mid-session)."""
    d = _tmp_dir()
    if os.path.isdir(d):
        for f in os.listdir(d):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass


# --------------------------------------------------------------------------- #
#  Reads — sessions (for the grouped gallery) and individual rows
# --------------------------------------------------------------------------- #
def get_sessions(limit=200):
    """
    One entry per session, newest first (spec A9 grouped list). Each entry:
        session_id, patient_id, stamp, n_images,
        avg_level, avg_stage, avg_label, avg_wound_pct, avg_foot_pct,
        thumb_path (1st image's captured photo), sim_consistent.
    """
    con = _connect()
    # Use the 1st image of each session as the thumbnail + representative row.
    rows = [dict(r) for r in con.execute("""
        SELECT * FROM captures
        WHERE image_index = 1 OR image_index IS NULL
        ORDER BY id DESC LIMIT ?
    """, (limit,))]
    con.close()
    for r in rows:
        r["thumb_path"] = r.get("captured_path")
    return rows


def get_session(session_id):
    """All image rows of one session, ordered 1..N (for the Results browser)."""
    con = _connect()
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM captures WHERE session_id=? ORDER BY image_index",
        (session_id,))]
    con.close()
    return rows


def get_all_records(limit=200):
    """Every row, newest-first (legacy / debugging)."""
    con = _connect()
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM captures ORDER BY id DESC LIMIT ?", (limit,))]
    con.close()
    return rows


def get_record_by_id(row_id):
    con = _connect()
    row = con.execute("SELECT * FROM captures WHERE id=?", (row_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def get_last_capture_for_patient(patient_id):
    """Most recent row for a patient (used by cross-visit checks), or None."""
    con = _connect()
    row = con.execute(
        "SELECT * FROM captures WHERE patient_id=? ORDER BY id DESC LIMIT 1",
        (patient_id,)).fetchone()
    con.close()
    return dict(row) if row else None


# --------------------------------------------------------------------------- #
#  Cloud sync helpers
# --------------------------------------------------------------------------- #
def unsynced_records():
    con = _connect()
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM captures WHERE synced=0 ORDER BY id")]
    con.close()
    return rows


def unsynced_sessions():
    """Distinct session_ids that still have unsynced rows (cloud uploads by
    session, not by image)."""
    con = _connect()
    ids = [r[0] for r in con.execute(
        "SELECT DISTINCT session_id FROM captures WHERE synced=0 "
        "AND session_id IS NOT NULL ORDER BY session_id")]
    con.close()
    return ids


def mark_session_synced(session_id):
    con = _connect()
    con.execute("UPDATE captures SET synced=1 WHERE session_id=?", (session_id,))
    con.commit()
    con.close()


def mark_synced(row_id):
    con = _connect()
    con.execute("UPDATE captures SET synced=1 WHERE id=?", (row_id,))
    con.commit()
    con.close()
