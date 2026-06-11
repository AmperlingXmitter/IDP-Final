"""
=============================================================================
 SEED DEMO DATA  (Testing/desktop/seed_demo_data.py)
-----------------------------------------------------------------------------
 Creates a demo SQLite DB (same schema the device writes) with a few patients
 and a time series, so you can run/test the desktop app WITHOUT a device.

     python seed_demo_data.py            # writes ./demo_dfu.db

 Delete demo_dfu.db any time to reset.

 Labels use the UT Diabetic Wound Classification system to match ai.py output:
   Level 0 → UT Stage A – Clean wound (no infection, no ischaemia)
   Level 1 → UT Stage B – Infected wound (nonischaemic)
   Level 2 → UT Stage C – Ischaemic wound (noninfected)
   Level 3 → UT Stage D – Ischaemic & infected
=============================================================================
"""
import os, sqlite3, datetime, json, random

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_dfu.db")

# --------------------------------------------------------------------------- #
#  Schema: same as device/storage.py  +  desktop-only patients table
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL,
    session_id TEXT, image_index INTEGER, n_images INTEGER, foot_angle TEXT,
    stamp TEXT NOT NULL, captured_path TEXT NOT NULL,
    overlay_path TEXT, closeup_path TEXT,
    highest_level INTEGER, highest_label TEXT, stage TEXT,
    wound_pct REAL, foot_pct REAL, window_counts TEXT,
    avg_level INTEGER, avg_stage TEXT, avg_label TEXT,
    avg_wound_pct REAL, avg_foot_pct REAL,
    sim_orb INTEGER, sim_hist REAL, sim_ssim REAL,
    sim_consistent INTEGER, sim_prev_id INTEGER,
    base_wound_px INTEGER, necrosis_px INTEGER, slough_px INTEGER,
    synced INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS patients (
    patient_id TEXT PRIMARY KEY,
    name       TEXT,
    dob        TEXT,
    notes      TEXT,
    gender     TEXT,
    wound_site TEXT,
    wound_points TEXT,
    created_at TEXT NOT NULL DEFAULT ''
);
"""

# UT Stage labels — must match ai.py / config.UT_LABELS
UT_LABELS = {
    0: "UT Stage A – Clean wound\n(no infection, no ischaemia)",
    1: "UT Stage B – Infected wound\n(nonischaemic)",
    2: "UT Stage C – Ischaemic wound\n(noninfected)",
    3: "UT Stage D – Ischaemic & infected",
}

# (patient_id, level, wound% start, weekly_trend, name, dob, notes, gender, wound_site)
# Different clinical stories to exercise the triage sorting.
# wound_site codes match svg_assets.FOOT_ZONES (e.g. "R-forefoot", "L-heel").
PATIENTS = [
    ("P001", 2, 6.0,  0.9,  "Ahmad bin Razali",   "1958-03-14",
     "Type 2 DM 20 yrs. Right plantar ulcer. Monitor for ischaemia.",
     "M", "R-forefoot"),
    ("P002", 1, 3.5, -0.4,  "Siti Nurul Aini",    "1965-11-02",
     "Healing well on antibiotics. Wound shrinking steadily.",
     "F", "L-toes"),
    ("P003", 3, 8.0,  0.2,  "Rajan s/o Krishnan", "1951-07-29",
     "Peripheral arterial disease. Vascular referral pending.",
     "M", "R-heel"),
    ("P004", 0, 0.3,  0.0,  "Lim Boon Seng",      "1972-05-18",
     "Stage A, routine monitoring. No active infection or ischaemia.",
     "M", ""),
]


def main():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    now = datetime.datetime.now()

    # ---- Capture time series — each visit is one 3-IMAGE SESSION (spec E1) ----
    N_IMAGES   = 3
    FOOT_ANGLE = {"P001": "bottom", "P002": "side", "P003": "bottom", "P004": "side"}
    LVL_STAGE  = {0: "A", 1: "B", 2: "C", 3: "D"}

    for pid, level, w0, weekly, name, dob, notes, gender, site in PATIENTS:
        angle = FOOT_ANGLE.get(pid, "side")
        stage = LVL_STAGE[level]
        label = UT_LABELS[level]
        split = {0: (0.92, 0.06, 0.02), 1: (0.75, 0.20, 0.05),
                 2: (0.58, 0.25, 0.17), 3: (0.42, 0.30, 0.28)}[level]
        prev_session = False
        for wk in range(8, -1, -1):          # 8 weeks ago → today (oldest first)
            dt    = now - datetime.timedelta(weeks=wk)
            stamp = dt.strftime("%Y%m%d_%H%M%S")
            session_id = f"{pid}_{stamp}"
            base_wound = max(0.0, w0 + weekly * (8 - wk) + random.uniform(-0.3, 0.3))

            # 3 individual image readings jittered around the visit's wound size
            img_wounds = [round(max(0.0, base_wound + random.uniform(-0.6, 0.6)), 2)
                          for _ in range(N_IMAGES)]
            avg_wound = round(sum(img_wounds) / N_IMAGES, 2)
            avg_foot  = round(max(0.0, 100.0 - avg_wound * 5), 2)

            # Session-level positioning similarity (first visit has none)
            if prev_session:
                sim_consistent = 1
                sim_orb  = random.randint(310, 480)
                sim_hist = round(random.uniform(0.91, 0.99), 4)
                sim_ssim = round(random.uniform(0.90, 0.97), 4)
            else:
                sim_consistent = sim_orb = sim_hist = sim_ssim = None

            for i, w in enumerate(img_wounds, 1):
                foot_pct = round(max(0.0, 100.0 - w * 5), 2)
                wtot = int(w / 100.0 * 65536)
                base_px, slough_px, necrosis_px = (int(wtot * split[0]),
                                                   int(wtot * split[1]),
                                                   int(wtot * split[2]))
                con.execute("""
                    INSERT INTO captures
                      (patient_id, session_id, image_index, n_images, foot_angle,
                       stamp, captured_path, overlay_path, closeup_path,
                       highest_level, highest_label, stage, wound_pct, foot_pct,
                       window_counts, avg_level, avg_stage, avg_label,
                       avg_wound_pct, avg_foot_pct,
                       sim_orb, sim_hist, sim_ssim, sim_consistent, sim_prev_id,
                       base_wound_px, necrosis_px, slough_px, synced, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                    (pid, session_id, i, N_IMAGES, angle,
                     stamp, f"Image/Captured_Images/{pid}_{stamp}_{i}.jpg",
                     f"Image/Overlay_Images/{pid}_{stamp}_{i}_overlay.png" if wk < 8 else None,
                     f"Image/Closeup_Images/{pid}_{stamp}_{i}_closeup.png" if wk < 8 else None,
                     level, label, stage, w, foot_pct,
                     json.dumps({}), level, stage, label, avg_wound, avg_foot,
                     sim_orb, sim_hist, sim_ssim, sim_consistent, None,
                     base_px, necrosis_px, slough_px,
                     dt.isoformat(timespec="seconds")))
            prev_session = True

    # ---- Patient metadata ----
    now_iso = now.isoformat(timespec="seconds")
    for pid, _level, _w0, _weekly, name, dob, notes, gender, site in PATIENTS:
        con.execute("""
            INSERT OR REPLACE INTO patients
                (patient_id, name, dob, notes, gender, wound_site, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (pid, name, dob, notes, gender, site, now_iso))

    con.commit()
    n_cap = con.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
    n_pat = con.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    con.close()
    print(f"Seeded {n_cap} captures for {n_pat} patients → {DB}")
    print("Labels use UT Stage A–D classification (matches ai.py output).")


if __name__ == "__main__":
    main()
