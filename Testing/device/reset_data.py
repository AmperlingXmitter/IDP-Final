"""
=============================================================================
 RESET DATA  (Testing/device/reset_data.py)   —  START FRESH (destructive)
-----------------------------------------------------------------------------
 Wipes collected DATA so you can begin a clean test run. Handles BOTH:
   * RPi5 (local) : saved images on the MicroSD + every row in the local DB.
   * Firebase     : every capture document in Firestore (optionally patients too).

 SAFE BY DEFAULT: it only PRINTS what it would delete (a dry run) until you
 add --yes. Nothing is removed without --yes.

 Examples
 --------
   python3 reset_data.py --local                 # dry-run: list local files/rows
   python3 reset_data.py --local --yes           # actually wipe local images + DB rows
   python3 reset_data.py --cloud --yes           # wipe all Firestore CAPTURES
   python3 reset_data.py --all --yes             # wipe local + cloud captures
   python3 reset_data.py --cloud --include-patients --yes   # also delete patient docs
   python3 reset_data.py --all --include-logs --yes         # also clear device Logs/

 What is kept
 ------------
   * Folder structure (only the files inside Image/* are removed).
   * The captures TABLE (emptied, not dropped — schema stays).
   * Patient roster in Firestore unless --include-patients is given.
   * Your code, config, and the AI model — untouched.
=============================================================================
"""
import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

import config as C

# Reuse the SAME Firebase project/key the device uploads with.
try:
    from cloud_api import FIREBASE_PROJECT_ID, FIREBASE_API_KEY
except Exception:
    FIREBASE_PROJECT_ID = os.environ.get("DFU_FB_PROJECT", "ai-assisted-dfu-monitoring-1")
    FIREBASE_API_KEY    = os.environ.get("DFU_FB_KEY", "")

_FS = "https://firestore.googleapis.com/v1"
_BASE = f"{_FS}/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents"

# Image folders whose CONTENTS get cleared (folders themselves are kept).
_IMG_FOLDERS = [C.CAPTURE_FOLDER, C.RESIZED_FOLDER,
                C.SEGMENTED_FOLDER, C.OVERLAY_FOLDER, C.CLOSEUP_FOLDER]


# --------------------------------------------------------------------------- #
#  Local (RPi5 MicroSD)
# --------------------------------------------------------------------------- #
def _list_local_files(folders):
    files = []
    for d in folders:
        if os.path.isdir(d):
            for name in os.listdir(d):
                p = os.path.join(d, name)
                if os.path.isfile(p):
                    files.append(p)
    return files


def reset_local(do_it, include_logs):
    folders = list(_IMG_FOLDERS) + ([C.LOG_FOLDER] if include_logs else [])
    files = _list_local_files(folders)

    # count DB rows
    n_rows = 0
    if os.path.exists(C.DB_PATH):
        try:
            con = sqlite3.connect(C.DB_PATH)
            n_rows = con.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
            con.close()
        except Exception as e:
            print(f"[reset] (local) could not read DB: {e}")

    print(f"[reset] LOCAL: {len(files)} image/log file(s) across {len(folders)} folder(s), "
          f"{n_rows} capture row(s) in {os.path.basename(C.DB_PATH)}")
    if not do_it:
        for p in files[:12]:
            print("   would delete:", p)
        if len(files) > 12:
            print(f"   …and {len(files) - 12} more")
        return

    removed = 0
    for p in files:
        try:
            os.remove(p); removed += 1
        except Exception as e:
            print(f"   ! could not delete {p}: {e}")
    print(f"[reset] LOCAL: deleted {removed}/{len(files)} file(s)")

    if os.path.exists(C.DB_PATH):
        try:
            con = sqlite3.connect(C.DB_PATH)
            con.execute("DELETE FROM captures")
            con.commit()
            con.execute("VACUUM")
            con.close()
            print(f"[reset] LOCAL: emptied captures table ({n_rows} row(s) removed)")
        except Exception as e:
            print(f"[reset] LOCAL: could not clear DB: {e}")


# --------------------------------------------------------------------------- #
#  Cloud (Firestore REST)
# --------------------------------------------------------------------------- #
def _runquery_capture_names():
    """Collection-group query → every capture document's full resource name."""
    url = f"{_BASE}:runQuery?key={FIREBASE_API_KEY}"
    body = json.dumps({"structuredQuery": {
        "from": [{"collectionId": "captures", "allDescendants": True}],
        "select": {"fields": [{"fieldPath": "patient_id"}]},
    }}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    names = []
    for row in data:
        doc = row.get("document")
        if doc and doc.get("name"):
            names.append(doc["name"])
    return names


def _list_patient_names():
    url = f"{_BASE}/patients?key={FIREBASE_API_KEY}&pageSize=300&mask.fieldPaths=name"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [d["name"] for d in data.get("documents", []) if d.get("name")]
    except Exception:
        return []


def _delete_doc(full_name):
    """full_name = 'projects/.../documents/patients/P001/captures/2026...'."""
    url = f"{_FS}/{full_name}?key={FIREBASE_API_KEY}"
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def reset_cloud(do_it, include_patients):
    if not FIREBASE_API_KEY:
        print("[reset] CLOUD: no Firebase API key configured — skipping cloud reset")
        return
    try:
        cap_names = _runquery_capture_names()
    except urllib.error.HTTPError as e:
        print(f"[reset] CLOUD: query failed HTTP {e.code}: "
              f"{e.read().decode(errors='replace')[:200]}")
        return
    except Exception as e:
        print(f"[reset] CLOUD: query failed ({e}) — offline?")
        return

    pat_names = _list_patient_names() if include_patients else []
    print(f"[reset] CLOUD: {len(cap_names)} capture doc(s)"
          + (f" + {len(pat_names)} patient doc(s)" if include_patients else "")
          + f" in project '{FIREBASE_PROJECT_ID}'")
    if not do_it:
        for n in cap_names[:12]:
            print("   would delete:", n.split("/documents/")[-1])
        if len(cap_names) > 12:
            print(f"   …and {len(cap_names) - 12} more")
        return

    ok = 0
    for n in cap_names:
        try:
            _delete_doc(n); ok += 1
        except Exception as e:
            print(f"   ! delete failed ({n.split('/')[-1]}): {e}")
    print(f"[reset] CLOUD: deleted {ok}/{len(cap_names)} capture doc(s)")

    if include_patients:
        okp = 0
        for n in pat_names:
            try:
                _delete_doc(n); okp += 1
            except Exception as e:
                print(f"   ! patient delete failed: {e}")
        print(f"[reset] CLOUD: deleted {okp}/{len(pat_names)} patient doc(s)")


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Reset collected DFU data (destructive).")
    ap.add_argument("--local", action="store_true", help="wipe RPi5 images + DB rows")
    ap.add_argument("--cloud", action="store_true", help="wipe Firestore captures")
    ap.add_argument("--all", action="store_true", help="wipe both local and cloud")
    ap.add_argument("--include-patients", action="store_true",
                    help="also delete patient docs in Firestore (default: keep them)")
    ap.add_argument("--include-logs", action="store_true",
                    help="also clear the device Logs/ folder")
    ap.add_argument("--yes", action="store_true",
                    help="actually delete (without this it is a dry run)")
    args = ap.parse_args()

    do_local = args.local or args.all
    do_cloud = args.cloud or args.all
    if not (do_local or do_cloud):
        ap.print_help()
        print("\n[reset] Nothing selected. Use --local, --cloud, or --all.")
        return

    mode = "LIVE DELETE" if args.yes else "DRY RUN (no changes — add --yes to delete)"
    print("=" * 60)
    print(f" DFU data reset — {mode}")
    print(f"   local={do_local}  cloud={do_cloud}  "
          f"include_patients={args.include_patients}  include_logs={args.include_logs}")
    print("=" * 60)

    if do_local:
        reset_local(args.yes, args.include_logs)
    if do_cloud:
        reset_cloud(args.yes, args.include_patients)

    if not args.yes:
        print("\n[reset] Dry run only. Re-run with --yes to apply.")


if __name__ == "__main__":
    main()
