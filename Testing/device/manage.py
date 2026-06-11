"""
=============================================================================
 MANAGE  (Testing/device/manage.py)  -  ONE entry point for the dev commands
-----------------------------------------------------------------------------
 Spec C: single commands that work the same on the RPi5 and in the Mac terminal.

   python3 manage.py setup [--ai]  # FIRST-TIME install of dependencies
   python3 manage.py test          # quick self-check / debug (no hardware needed)
   python3 manage.py run           # launch the device app (alias: launch)
   python3 manage.py clear         # wipe local images + DB     (add --cloud too)
   python3 manage.py seed [N]      # seed N fake sessions locally (add --cloud too)

 The repo-root Makefile wraps these as `make setup|test|run|clear|seed`.
=============================================================================
"""
import argparse, os, platform, subprocess, sys, datetime, random

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))   # the Final/ project root


# --------------------------------------------------------------------------- #
#  setup — one-command first-time install (device sim + desktop; AI optional)
# --------------------------------------------------------------------------- #
def cmd_setup(args):
    pip = [sys.executable, "-m", "pip", "install"]
    # Lightweight deps that install cleanly on macOS, Windows and the Pi —
    # enough to run the device in simulation AND the desktop app.
    base = ["pillow", "numpy<2", "opencv-python",
            "dash>=2.16", "plotly>=5.20", "reportlab>=4.0", "pywebview>=5.0"]
    print("[setup] installing app dependencies (device sim + desktop) …")
    rc = subprocess.call(pip + base)
    if rc != 0:
        print("[setup] WARNING: some packages failed — see pip output above.")

    # TensorFlow is platform-specific; only attempt with --ai to avoid breaking
    # setup on machines without a matching wheel.
    is_mac_arm = platform.system() == "Darwin" and platform.machine() == "arm64"
    tf_pkg = "tensorflow-macos==2.15.0" if is_mac_arm else "tensorflow==2.15.1"
    if args.ai:
        print(f"[setup] installing AI ({tf_pkg}) …")
        subprocess.call(pip + [tf_pkg, "numpy<2"])
    else:
        print(f"[setup] AI not installed. To enable RUN_AI=True:")
        print(f"          pip install {tf_pkg} 'numpy<2'   (or re-run: manage.py setup --ai)")

    print("[setup] Raspberry Pi only — OS packages (run once on the Pi):")
    print("          sudo apt install -y python3-picamera2 python3-gpiozero "
          "python3-lgpio python3-tk fonts-noto-cjk")
    print("[setup] done.  Next:  python3 manage.py test")


# --------------------------------------------------------------------------- #
#  test — import every module + run the pure-logic checks (fast, no hardware)
# --------------------------------------------------------------------------- #
def cmd_test(args):
    ok = True
    print("== DFU device self-check ==")

    # 1) every module imports
    mods = ["config", "ui_text", "storage", "ai", "similarity", "camera",
            "button", "light", "cloud_api", "ui", "main"]
    for m in mods:
        try:
            __import__(m)
            print(f"  import {m:<11} OK")
        except Exception as e:
            ok = False
            print(f"  import {m:<11} FAIL -> {e}")

    # 2) UT-stage averaging sanity (spec B2)
    try:
        import ai
        def stage(levels):
            return ai.average_session([{"highest_level": l, "wound_pct": 1.0,
                                        "foot_pct": 99.0} for l in levels])["avg_stage"]
        assert stage([1, 1, 2]) == "B"        # 2,2,3 -> 2.33 -> B
        assert stage([0, 3]) == "C"           # 1,4 -> 2.5 tie -> up -> C
        assert stage([-1, -1]) == "?"         # nothing detected
        print("  averaging      OK")
    except Exception as e:
        ok = False
        print(f"  averaging      FAIL -> {e}")

    # 3) storage round-trip in a temp dir
    try:
        ok = _test_storage() and ok
        print("  storage        OK")
    except Exception as e:
        ok = False
        print(f"  storage        FAIL -> {e}")

    # 4) AI deployment present (does not load TensorFlow)
    import config as C
    if os.path.isdir(C.DEPLOYMENT_DIR):
        print(f"  deployment     OK  ({os.path.basename(C.DEPLOYMENT_DIR)})")
    else:
        ok = False
        print(f"  deployment     FAIL -> not found: {C.DEPLOYMENT_DIR}")

    print("== RESULT:", "PASS ==" if ok else "FAIL ==")
    sys.exit(0 if ok else 1)


def _test_storage():
    import tempfile, shutil, config as C
    d = tempfile.mkdtemp()
    save = {k: getattr(C, k) for k in
            ("IMAGE_ROOT", "CAPTURE_FOLDER", "OVERLAY_FOLDER", "CLOSEUP_FOLDER",
             "RESIZED_FOLDER", "SEGMENTED_FOLDER", "LOG_FOLDER", "ALL_FOLDERS", "DB_PATH")}
    try:
        C.IMAGE_ROOT = os.path.join(d, "Image")
        C.CAPTURE_FOLDER = os.path.join(C.IMAGE_ROOT, "Captured_Images")
        C.OVERLAY_FOLDER = os.path.join(C.IMAGE_ROOT, "Overlay_Images")
        C.CLOSEUP_FOLDER = os.path.join(C.IMAGE_ROOT, "Closeup_Images")
        C.RESIZED_FOLDER = os.path.join(C.IMAGE_ROOT, "R")
        C.SEGMENTED_FOLDER = os.path.join(C.IMAGE_ROOT, "S")
        C.LOG_FOLDER = os.path.join(d, "Logs")
        C.ALL_FOLDERS = [C.IMAGE_ROOT, C.CAPTURE_FOLDER, C.OVERLAY_FOLDER,
                         C.CLOSEUP_FOLDER, C.RESIZED_FOLDER, C.SEGMENTED_FOLDER, C.LOG_FOLDER]
        C.DB_PATH = os.path.join(d, "t.db")
        import importlib, storage
        importlib.reload(storage)
        storage.ensure_folders(); storage.init_db()
        tmp = storage.new_session_temp_paths(3)
        for p in tmp:
            open(p, "wb").write(b"x")
        summ = {"n_images": 3, "avg_level": 1, "avg_stage": "B", "avg_label": "UT Stage B",
                "avg_wound_pct": 2.0, "avg_foot_pct": 98.0,
                "per_image": [{"overlay_src": None, "closeup_src": None} for _ in range(3)]}
        rec = storage.finalize_session("PTEST", tmp, summ, foot_angle="side")
        assert len(storage.get_session(rec["session_id"])) == 3
        assert len(storage.get_sessions()) == 1
        return True
    finally:
        for k, v in save.items():
            setattr(C, k, v)
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------- #
#  run / launch — start the device app
# --------------------------------------------------------------------------- #
def cmd_run(args):
    print("[manage] launching main.py …  (Ctrl-C to stop)")
    sys.exit(subprocess.call([sys.executable, os.path.join(HERE, "main.py")]))


# --------------------------------------------------------------------------- #
#  clear — wipe local images + DB (and optionally Firestore)
# --------------------------------------------------------------------------- #
def cmd_clear(args):
    cmd = [sys.executable, os.path.join(HERE, "reset_data.py"),
           "--all" if args.cloud else "--local", "--yes"]
    sys.exit(subprocess.call(cmd))


# --------------------------------------------------------------------------- #
#  seed — create fake sessions in the local DB (+ optional cloud)
# --------------------------------------------------------------------------- #
def cmd_seed(args):
    import config as C, storage, ai, cloud_api
    storage.ensure_folders(); storage.init_db()
    patients = ["P001", "P002", "P003"]
    level_pool = [0, 1, 1, 2, 2, 3, 4]
    n = args.count
    made = 0
    for s in range(n):
        pid = patients[s % len(patients)]
        when = datetime.datetime.now() - datetime.timedelta(days=(n - s) * 2,
                                                             hours=random.randint(0, 6))
        stamp = when.strftime("%Y%m%d_%H%M%S")
        session_id = f"{pid}_{stamp}"
        levels = [random.choice(level_pool) for _ in range(C.IMAGES_PER_SESSION)]
        per_image = [{"highest_level": lv, "wound_pct": round(random.uniform(1, 12), 2),
                      "foot_pct": None} for lv in levels]
        for p in per_image:
            p["foot_pct"] = round(100 - p["wound_pct"], 2)
        summ = ai.average_session(per_image)
        rows = []
        con = storage._connect()
        for i, p in enumerate(per_image, start=1):
            cap = os.path.join(C.CAPTURE_FOLDER, f"{pid}_{stamp}_{i}.jpg")
            ovl = os.path.join(C.OVERLAY_FOLDER, f"{pid}_{stamp}_{i}_overlay.png")
            clo = os.path.join(C.CLOSEUP_FOLDER, f"{pid}_{stamp}_{i}_closeup.png")
            _fake_image(cap, p["wound_pct"]); _fake_image(ovl, p["wound_pct"], tint=True)
            _fake_image(clo, p["wound_pct"], tint=True, crop=True)
            stg = C.LEVEL_TO_STAGE.get(p["highest_level"], "?")
            rec = {"patient_id": pid, "session_id": session_id, "image_index": i,
                   "n_images": C.IMAGES_PER_SESSION, "foot_angle":
                   random.choice(["side", "bottom"]), "stamp": stamp,
                   "captured_path": cap, "overlay_path": ovl, "closeup_path": clo,
                   "highest_level": p["highest_level"],
                   "highest_label": C.UT_LABELS.get(p["highest_level"]), "stage": stg,
                   "wound_pct": p["wound_pct"], "foot_pct": p["foot_pct"],
                   "window_counts": None, "avg_level": summ["avg_level"],
                   "avg_stage": summ["avg_stage"], "avg_label": summ["avg_label"],
                   "avg_wound_pct": summ["avg_wound_pct"], "avg_foot_pct": summ["avg_foot_pct"],
                   "sim_orb": None, "sim_hist": None, "sim_ssim": None,
                   "sim_consistent": 1, "sim_prev_id": None,
                   "base_wound_px": None, "necrosis_px": None, "slough_px": None}
            rec["id"] = storage._insert_row(con, rec)
            rows.append(rec)
        con.commit(); con.close()
        made += 1
        if args.cloud:
            session = {"session_id": session_id, "patient_id": pid, "stamp": stamp,
                       "n_images": C.IMAGES_PER_SESSION, **summ, "sim_consistent": 1,
                       "foot_angle": rows[0]["foot_angle"], "images": rows}
            cloud_api.upload_session(session)
    print(f"[manage] seeded {made} session(s) "
          f"({C.IMAGES_PER_SESSION} images each){' + cloud' if args.cloud else ''}")


def _fake_image(path, wound_pct, tint=False, crop=False):
    """Generate a tiny placeholder foot photo with a red 'wound' blob."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        open(path, "wb").write(b"")
        return
    w, h = (120, 120) if crop else (320, 240)
    img = Image.new("RGB", (w, h), (216, 180, 138))           # skin tone
    d = ImageDraw.Draw(img)
    r = max(6, int((wound_pct / 100) ** 0.5 * min(w, h)))
    cx, cy = w // 2, h // 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r],
              fill=(200, 60, 40) if not tint else (255, 90, 0))
    img.save(path, quality=70)


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="DFU device dev commands")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("setup", help="first-time install of dependencies")
    st.add_argument("--ai", action="store_true", help="also install TensorFlow (AI)")
    sub.add_parser("test", help="quick self-check / debug")
    sub.add_parser("run", help="launch the device app")
    sub.add_parser("launch", help="alias of run")
    c = sub.add_parser("clear", help="wipe local images + DB")
    c.add_argument("--cloud", action="store_true", help="also wipe Firestore captures")
    s = sub.add_parser("seed", help="seed fake sessions")
    s.add_argument("count", nargs="?", type=int, default=6, help="how many sessions")
    s.add_argument("--cloud", action="store_true", help="also upload to Firestore")
    args = ap.parse_args()
    {"setup": cmd_setup, "test": cmd_test, "run": cmd_run, "launch": cmd_run,
     "clear": cmd_clear, "seed": cmd_seed}[args.cmd](args)


if __name__ == "__main__":
    main()
