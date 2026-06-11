"""
=============================================================================
 DFU DEVICE - MAIN  (Testing/device/main.py)
-----------------------------------------------------------------------------
 New flow (spec A):
   consent -> selection (side/bottom) -> instructions -> live video
            -> [ capture 1/N, 2/N … N/N ]  (CAPTURE state)
            -> AI analyses all N at once   (AI ANALYSIS state, separate)
            -> results (averaged) + Firebase upload

 The Capture state and the AI Analysis state are SEPARATE (spec A1), each with
 a small time margin so quick presses never collide with a state change.

 Two run modes (SHOW_UI in config.py):
   * SHOW_UI=True  : Tkinter kiosk. SessionController drives the screens; capture
                     work runs in a worker thread, UI updated via a queue.
   * SHOW_UI=False : headless console loop (capture-only / AI testing).

 Run:  python3 main.py     (laptop = SIMULATE_*; Pi = real-hardware flags)
=============================================================================
"""
import os, sys, time, threading
import config as C
import storage, camera, ai
from button import CaptureButton
from light import Light
import cloud_api

# Similarity is optional — only imported when needed.
_sim = None
if C.RUN_SIMILARITY or C.REJECT_DISSIMILAR_SESSION:
    try:
        import similarity as _sim
    except ImportError as _e:
        print(f"[main] WARNING: similarity import failed ({_e}); disabled")
        C.RUN_SIMILARITY = False
        C.REJECT_DISSIMILAR_SESSION = False


def log(msg):
    if C.DEBUG:
        print(f"[main] {msg}")


# --------------------------------------------------------------------------- #
#  SessionController — owns the N-image capture session + AI + save + upload.
#  The UI calls these handlers; the controller posts screen states back to it.
# --------------------------------------------------------------------------- #
class SessionController:
    def __init__(self, btn, light):
        self.btn   = btn
        self.light = light
        self.ui    = None
        self.N     = C.IMAGES_PER_SESSION
        self.angle = "side"               # set on the Selection screen
        self.captured  = 0                # images taken so far this session
        self.busy      = False            # True during a capture or AI analysis
        self.temp_paths = storage.new_session_temp_paths(self.N)

    def attach_ui(self, ui):
        self.ui = ui

    # ---- queries the UI uses to render the live screen --------------------
    def index(self):  return min(self.captured + 1, self.N)   # 1-based "Capture i/N"
    def count(self):  return self.N
    def locked(self): return self.captured > 0                # Patient ID lock (spec A5)

    # ---- navigation helpers ----------------------------------------------
    def set_angle(self, angle):
        self.angle = angle
        log(f"foot angle = {angle}")

    def begin_session(self):
        """Start a fresh session buffer (counter 0/N, clean temp files)."""
        self.captured = 0
        self.busy = False
        storage.cleanup_session_temp()
        self.temp_paths = storage.new_session_temp_paths(self.N)

    # ---- actions ----------------------------------------------------------
    def on_capture(self):
        """Capture button / physical press on the live screen."""
        if self.busy or not self.btn.accept():
            return                       # lockout guard: one capture at a time
        self.busy = True
        idx = self.captured + 1
        self.ui.post("capturing", {"i": idx, "n": self.N})
        threading.Thread(target=self._capture_worker, args=(idx,), daemon=True).start()

    def _capture_worker(self, idx):
        t0 = time.monotonic()
        try:
            time.sleep(C.CAPTURE_SETTLE_S)          # let the frame settle (margin)
            self.light.flash_on()
            try:
                camera.capture_to(self.temp_paths[idx - 1])
            finally:
                self.light.flash_off()
            log(f"captured {idx}/{self.N} -> {self.temp_paths[idx-1]}")
            time.sleep(C.CAPTURE_SETTLE_S)          # margin after the still
            _hold_min(t0, C.CAPTURE_STATE_MIN_S)    # keep "Capturing…" up briefly
            self.captured = idx

            if self.captured < self.N:
                self.busy = False
                self.ui.post("live")                # back to live for the next shot
            else:
                self._run_analysis()                # all N taken → AI state
        except Exception as e:
            print(f"[main] ERROR during capture: {e}")
            self.busy = False
            self.ui.post("live")

    def _run_analysis(self):
        """AI ANALYSIS state: analyse all N images at once, then results."""
        self.ui.post("analysing", {"n": self.N})
        t0 = time.monotonic()
        paths = self.temp_paths[:self.N]

        # Optional positioning check across the N images (spec B).
        sim = None
        if (C.RUN_SIMILARITY or C.REJECT_DISSIMILAR_SESSION) and _sim is not None:
            sim = _sim.session_consistency(paths)
        if (C.REJECT_DISSIMILAR_SESSION and sim and sim.get("consistent") == 0):
            log("session rejected: images too dissimilar — asking to retake")
            _hold_min(t0, C.AI_STATE_MIN_S)
            self.begin_session()
            self.ui.post("retake")
            return

        # Analyse (or build a placeholder when RUN_AI is off for a capture test).
        if C.RUN_AI:
            summary = ai.analyse_session(paths)
        else:
            log("RUN_AI is False -> skipping analysis (capture-only test)")
            summary = _placeholder_summary(paths)

        rec = storage.finalize_session(
            C.PATIENT_ID, paths, summary, sim=sim, foot_angle=self.angle)
        print(f"[main] SESSION {rec['session_id']}: stage {rec['avg_stage']} | "
              f"wound {rec['avg_wound_pct']}%")

        if C.ENABLE_CLOUD:
            cloud_api.upload_session_async(rec)     # fire-and-forget, low-connectivity safe

        _hold_min(t0, C.AI_STATE_MIN_S)             # keep "AI Analysing…" up briefly
        self.begin_session()                        # reset buffer for the next session
        self.ui.post("results", {"session": rec, "origin": "session"})

    def on_reset(self):
        """Reset button / physical reset: back to consent, 0/N, flash off."""
        log("reset")
        self.busy = False
        self.light.mode = 0                         # Flash Off
        self.light.apply_static()
        self.begin_session()
        if self.ui:
            self.ui.set_light_label(self.light.mode_name)
        self.ui.post("consent")

    def on_done(self):
        """Results dismissed from a live session → return to the live screen."""
        self.ui.post("live")

    def on_light(self):
        return self.light.cycle()


def _hold_min(t0, min_s):
    """Keep a transient state visible for at least `min_s` seconds (avoids a
    jarring flicker when capture/AI finishes almost instantly in sim mode)."""
    remaining = min_s - (time.monotonic() - t0)
    if remaining > 0:
        time.sleep(remaining)


def _placeholder_summary(paths):
    """Session summary when RUN_AI is off (capture-only test) — no AI numbers."""
    per_image = [{"index": i + 1, "highest_level": None, "highest_label": None,
                  "stage": "?", "wound_pct": None, "foot_pct": None,
                  "window_counts": None, "overlay_src": None, "closeup_src": None}
                 for i in range(len(paths))]
    return {"n_images": len(paths), "avg_level": None, "avg_stage": "?",
            "avg_label": "AI off (capture test)", "avg_wound_pct": None,
            "avg_foot_pct": None, "per_image": per_image}


# --------------------------------------------------------------------------- #
#  UI mode (event-driven, macOS + Pi safe)
# --------------------------------------------------------------------------- #
def run_ui(ctrl):
    from ui import DeviceUI
    ui = DeviceUI(ctrl)
    ctrl.attach_ui(ui)

    ui.set_light_label(ctrl.light.mode_name)
    # Physical button is multi-purpose (capture / back / dismiss) — the UI
    # dispatches it based on the current screen (see ui.physical_press).
    ctrl.btn.attach(ui.physical_press)

    if C.RUN_AI:
        threading.Thread(target=_safe_warm, daemon=True).start()

    ui.post("consent" if C.SHOW_CONSENT else "live")
    ui.run()


# --------------------------------------------------------------------------- #
#  Headless console mode (no Tk — capture-only / AI testing on a laptop)
# --------------------------------------------------------------------------- #
def run_headless(ctrl):
    if C.SHOW_CONSENT:
        print("\n*** CONSENT: press ENTER to agree & continue ***")
        ctrl.btn.wait_for_dismiss()
    if C.RUN_AI:
        _safe_warm()
    while True:
        ctrl.begin_session()
        for i in range(1, ctrl.N + 1):
            print(f"\nReady. Press ENTER to capture image {i}/{ctrl.N}.")
            ctrl.btn.wait_for_press()
            ctrl.light.flash_on()
            try:
                camera.capture_to(ctrl.temp_paths[i - 1])
            finally:
                ctrl.light.flash_off()
            print(f"[main] captured {i}/{ctrl.N}")
            ctrl.captured = i
        print("[main] analysing all images…")
        try:
            summary = ai.analyse_session(ctrl.temp_paths) if C.RUN_AI \
                else _placeholder_summary(ctrl.temp_paths)
            sim = _sim.session_consistency(ctrl.temp_paths) if _sim else None
            rec = storage.finalize_session(C.PATIENT_ID, ctrl.temp_paths, summary,
                                           sim=sim, foot_angle=ctrl.angle)
            print(f"[main] RESULT: stage {rec['avg_stage']} | "
                  f"wound {rec['avg_wound_pct']}%")
            if C.ENABLE_CLOUD:
                cloud_api.upload_session_async(rec)
        except Exception as e:
            print(f"[main] ERROR during analysis: {e}")


def _safe_warm():
    try:
        ai.warm_up()
    except Exception as e:
        print(f"[main] WARNING: AI warm-up failed: {e}")


def main():
    print("=" * 56)
    print(" DFU Device starting")
    print(f"  Patient ID    : {C.PATIENT_ID}")
    print(f"  Images/session: {C.IMAGES_PER_SESSION}")
    print(f"  SIM camera/btn: {C.SIMULATE_CAMERA}/{C.SIMULATE_BUTTON}")
    print(f"  GPIO button   : {getattr(C, 'USE_GPIO_BUTTON', not C.SIMULATE_BUTTON)} "
          f"(pin {C.BUTTON_GPIO_PIN})")
    print(f"  UI/AI/cloud/led: {C.SHOW_UI}/{C.RUN_AI}/{C.ENABLE_CLOUD}/{C.ENABLE_LIGHT}")
    print(f"  AI deployment : {C.DEPLOYMENT_DIR}")
    print("=" * 56)

    storage.ensure_folders()
    storage.init_db()
    storage.cleanup_session_temp()      # clear any temp captures from a crash/reset

    # Low-connectivity friendly: push any sessions that didn't upload last time.
    if C.ENABLE_CLOUD:
        cloud_api.sync_unsynced_async()

    btn   = CaptureButton()
    light = Light()
    ctrl  = SessionController(btn, light)

    try:
        if C.SHOW_UI:
            run_ui(ctrl)
        else:
            run_headless(ctrl)
    finally:
        light.shutdown()
        camera.shutdown()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[main] stopped by user")
    sys.exit(0)
