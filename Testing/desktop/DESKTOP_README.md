# DFU Desktop App — for medical staff

Apple-Health-style dashboard to review diabetic-foot-ulcer monitoring data. **Staff only,
PIN-gated. Screening aid — not a diagnosis.** Reads the same data the device writes; one
**session** = N images (see PROJECT_README "Core concept").

## Files
| File | Role |
|------|------|
| `app.py` | Dash UI + all callbacks. Flags at top (`STAFF_PIN`, `SHOW_*`, `DEBUG_UI`). |
| `data_source.py` | `LocalSource` (sqlite) + `FirebaseSource`; `ds.sessions()` / `ds.session_trend()`. |
| `svg_assets.py` | gender silhouettes, foot outlines (side/bottom), colour-blind cues. |
| `report.py` | session-aware PDF export (reportlab). |
| `audit.py` / `debug_utils.py` | edit log / soft-fail logging. |
| `seed_demo_data.py` | writes `demo_dfu.db` (4 patients × 9 sessions × 3 images). |
| `run_desktop.py` | native-window launcher (pywebview). |

## Run
```bash
make setup            # from repo root (installs dash, plotly, reportlab, pywebview, …)
make app              # = cd desktop && python run_desktop.py   (or: python app.py → browser :8050)
```
First run / to reset demo data: `python seed_demo_data.py`. Login PIN: `1234` (`STAFF_PIN`).

## Data streams (toggle in the header)
- **Seeded** — local `demo_dfu.db` (demo patients).
- **Database** — live Firestore (what the device uploads).

`_SourceRouter` proxies all data calls to the active source; switching resets to the overview.
Default from `DFU_BACKEND` (local→seeded, firebase→database). Point at a real device DB with
`DFU_DB=/path/to/dfu_local.db`.

## Patient page
- **3 widgets in a row:** UT stage (averaged) · Wound-bed composition (granulation **red** /
  slough **yellow** / necrosis **black**) · Trend (earliest vs latest **average**; "too little data"
  unless ≥2 averages ≥7 days apart). Stage + wound-bed are labelled with the capture date/time.
- **Trend graph:** per-session **error bars** (min→max of that session's readings); the **average**
  point is the stand-out marker; individual readings are small/muted.
- **Measurements:** collapsible **per session**. Header = the average reading; expand to edit
  **Date/Time + foot angle** (apply to all N images) and per-image **Lvl/Wound %**. Save → DB →
  `save-token` → graph/widgets recalculate.
- **Image panel:** **Selected Capture** (picked/latest session) vs **Graph Selection** (earliest vs
  latest average, each with date+time).
- **Patient info:** edit fields, gender **silhouette avatar** (M/F/unspecified), and the
  **multi-point foot picker** — click to drop red/yellow/black markers, side/bottom view dropdown,
  Undo / Clear; saved as `patients.wound_points` JSON.
- **Export PDF** (session-aware) · **Audit log** (header) · healing-status banner (logistics only).

## Tabs
- **Patients** — triage cards (urgent first; stage pill + letter badge; sparkline or "no trend data").
- **List** — sortable table.
- **Cloud (Firebase)** — live Firestore connection test + base64-image round-trip proof.

## Notes
- Colour-blind safety: every severity colour is paired with a **letter** (A–D) and, on the trend, a
  **marker shape** per stage.
- Editable timestamp is the `stamp` **field** (Firestore doc id stays stable) — correcting a date/time
  never breaks image lookups; the graph recalculates.
- Foot-picker markers snap to a ~22 px grid (Dash can't read raw click coords without custom JS).
- `DEBUG_UI=True` adds a diagnostics bar + `desktop_debug.log`; `render_detail`/`show_images` fail soft.
- Package to `.app`/`.exe` with PyInstaller when needed; `make app` is enough for clinic testing.
