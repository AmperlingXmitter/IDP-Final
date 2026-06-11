"""
=============================================================================
 CAMERA  (Testing/device/camera.py)
-----------------------------------------------------------------------------
 Captures one still to a given path.
 - Real mode: RPi Camera 3 via picamera2, invoked via subprocess using the
   system Python 3.13 (which has picamera2/libcamera built-in). This avoids
   the libcamera C-extension incompatibility with our Python 3.11 TF venv.
 - SIMULATE_CAMERA mode: copies a stock photo (or makes one) so the whole
   flow can be tested with no camera.
 The rest of the app calls capture_to(path) and does not care which mode.
=============================================================================
"""
import io, os, shutil, subprocess, sys, textwrap, threading, time
import config as C

# System Python that has picamera2 + libcamera
_SYS_PYTHON = "/usr/bin/python3"

# Inline script run by system Python to capture one frame.
# argv: path  w  h  do_autofocus(0/1)  lens_position(float, <0 = auto)
# Autofocus is guarded: on cameras without AF (V1/V2/HQ) it is skipped cleanly.
_CAPTURE_SCRIPT = textwrap.dedent("""
import sys
from picamera2 import Picamera2
try:
    from libcamera import controls
    HAVE_CTRL = True
except Exception:
    HAVE_CTRL = False

path = sys.argv[1]
w, h = int(sys.argv[2]), int(sys.argv[3])
do_af = sys.argv[4] == "1"
lens  = float(sys.argv[5])

cam = Picamera2()
cfg = cam.create_still_configuration(main={"size": (w, h)})
cam.configure(cfg)
cam.start()

# Sharp stills: run a single autofocus sweep right before the capture.
if do_af and HAVE_CTRL:
    try:
        cam.set_controls({"AfMode": controls.AfModeEnum.Auto})
        ok = cam.autofocus_cycle()          # blocks until the AF sweep settles
        print(f"[camera] autofocus cycle ok={ok}")
    except Exception as e:
        # No AF hardware (or driver issue) — fall back to a fixed lens position.
        print(f"[camera] autofocus unavailable, using fixed focus: {e}")
        if lens >= 0:
            try:
                cam.set_controls({"AfMode": controls.AfModeEnum.Manual,
                                  "LensPosition": lens})
            except Exception:
                pass
elif HAVE_CTRL and lens >= 0:
    # Autofocus disabled but a manual lens position was requested.
    try:
        cam.set_controls({"AfMode": controls.AfModeEnum.Manual,
                          "LensPosition": lens})
    except Exception:
        pass

cam.capture_file(path)
cam.stop()
print(f"[camera] captured -> {path}")
""")


def _make_dummy(path):
    """Generate a random placeholder image (no real photo needed)."""
    from PIL import Image
    import numpy as np
    arr = (np.random.rand(C.CAPTURE_HEIGHT, C.CAPTURE_WIDTH, 3) * 255).astype("uint8")
    Image.fromarray(arr).save(path)
    if C.DEBUG:
        print(f"[camera] generated dummy image -> {path}")


def capture_to(path):
    """Capture (or simulate) one still image saved to `path`. Returns `path`."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if C.SIMULATE_CAMERA:
        if C.SIM_IMAGE_PATH and os.path.exists(C.SIM_IMAGE_PATH):
            shutil.copyfile(C.SIM_IMAGE_PATH, path)
            if C.DEBUG:
                print(f"[camera] (sim) copied {C.SIM_IMAGE_PATH} -> {path}")
        else:
            _make_dummy(path)
        return path

    # Real capture via system Python subprocess
    _do_af = "1" if getattr(C, "CAMERA_AUTOFOCUS", True) else "0"
    _lens  = getattr(C, "LENS_POSITION", None)
    _lens  = str(_lens) if _lens is not None else "-1"
    result = subprocess.run(
        [_SYS_PYTHON, "-c", _CAPTURE_SCRIPT,
         path, str(C.CAPTURE_WIDTH), str(C.CAPTURE_HEIGHT), _do_af, _lens],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"[camera] capture subprocess failed:\n{result.stderr.strip()}"
        )
    if C.DEBUG:
        print(result.stdout.strip())
    return path


def shutdown():
    """No persistent process to shut down in subprocess mode."""
    pass


# --------------------------------------------------------------------------- #
#  Live video preview stream
# --------------------------------------------------------------------------- #
class VideoStream:
    """
    Provides a continuous stream of JPEG frames for the idle-screen preview.

    Real camera  : launches `rpicam-vid --codec mjpeg` and parses JPEG frames
                   out of its stdout.  Runs on the Pi without needing picamera2
                   in the 3.11 venv.
    Simulate mode: periodically reloads SIM_IMAGE_PATH so the preview updates
                   if you swap the file while testing (static otherwise).

    Usage:
        vs = VideoStream()
        vs.start()
        frame_bytes = vs.get_frame()   # latest JPEG bytes, or None
        vs.stop()
    """
    _SOI = b'\xff\xd8'
    _EOI = b'\xff\xd9'

    def __init__(self):
        self._proc    = None
        self._frame   = None          # latest raw JPEG bytes
        self._lock    = threading.Lock()
        self._running = False

    @staticmethod
    def _autofocus_args():
        """rpicam-vid autofocus flags for the live preview (Camera Module 3).

        On cameras without AF these flags are simply ignored by rpicam-vid, so
        they are safe to pass unconditionally — but we still gate on config so
        you can force a fixed lens position for a fixed-distance jig.
        """
        mode = getattr(C, "PREVIEW_AF_MODE", "continuous")
        if mode not in ("continuous", "auto", "manual"):
            return []
        args = [f"--autofocus-mode={mode}"]
        if mode == "manual":
            lens = getattr(C, "LENS_POSITION", None)
            if lens is not None:
                args.append(f"--lens-position={lens}")
        else:
            # --autofocus-speed only applies to continuous/auto AF
            spd = getattr(C, "PREVIEW_AF_SPEED", "normal")
            if spd in ("normal", "fast"):
                args.append(f"--autofocus-speed={spd}")
        win = getattr(C, "AF_WINDOW", None)
        if win and len(win) == 4:
            args.append("--autofocus-window={},{},{},{}".format(*win))
        return args

    def start(self):
        self._running = True
        if C.SIMULATE_CAMERA:
            threading.Thread(target=self._sim_loop, daemon=True).start()
        else:
            cmd = [
                "rpicam-vid",
                "--output", "-",
                "--codec", "mjpeg",
                f"--width={C.PREVIEW_WIDTH}",
                f"--height={C.PREVIEW_HEIGHT}",
                f"--framerate={C.PREVIEW_FPS}",
                f"--bitrate={C.PREVIEW_BITRATE}",   # cap bitrate → less JPEG data per frame
                f"--quality={getattr(C, 'PREVIEW_QUALITY', 50)}",        # lower MJPEG quality → faster decode
                f"--buffer-count={getattr(C, 'PREVIEW_BUFFER_COUNT', 2)}",  # fewer buffers → less RAM/latency
                "--timeout=0",
                "--nopreview",
                "--denoise=off",    # skip ISP noise reduction → lower per-frame latency
                "--sharpness=0",    # skip sharpening pass (not needed for a live preview)
            ]
            if getattr(C, "PREVIEW_FLUSH", True):
                cmd.append("--flush")   # push each encoded frame out immediately (lower latency)
            cmd += self._autofocus_args()
            try:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                threading.Thread(target=self._mjpeg_loop, daemon=True).start()
                if C.DEBUG:
                    print(f"[camera] VideoStream started: {' '.join(cmd)}")
            except FileNotFoundError:
                # rpicam-vid not found (e.g., on macOS) — fall back to sim loop
                if C.DEBUG:
                    print("[camera] rpicam-vid not found; VideoStream using sim fallback")
                threading.Thread(target=self._sim_loop, daemon=True).start()

    def _mjpeg_loop(self):
        """Read raw bytes from rpicam-vid stdout, extract complete JPEG frames."""
        buf = b""
        while self._running and self._proc:
            try:
                chunk = self._proc.stdout.read(65536)
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
            # Extract every complete JPEG (SOI … EOI) from the buffer
            while True:
                s = buf.find(self._SOI)
                if s == -1:
                    buf = b""
                    break
                e = buf.find(self._EOI, s + 2)
                if e == -1:
                    buf = buf[s:]          # keep from start of partial frame
                    break
                frame = buf[s:e + 2]
                buf = buf[e + 2:]
                with self._lock:
                    self._frame = frame    # keep only the latest frame

    def _sim_loop(self):
        """Simulated preview: reload SIM_IMAGE_PATH periodically."""
        while self._running:
            try:
                path = C.SIM_IMAGE_PATH
                if path and os.path.exists(path):
                    with open(path, "rb") as f:
                        data = f.read()
                    with self._lock:
                        self._frame = data
            except Exception as e:
                if C.DEBUG:
                    print(f"[camera] sim preview error: {e}")
            time.sleep(1.0)

    def get_frame(self):
        """Return the latest JPEG bytes, or None if no frame yet."""
        with self._lock:
            return self._frame

    def stop(self):
        """Stop the stream and kill the subprocess."""
        self._running = False
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
        if C.DEBUG:
            print("[camera] VideoStream stopped")