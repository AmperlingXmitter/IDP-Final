"""
=============================================================================
 DEBUG UTILS  (Testing/desktop/debug_utils.py)
-----------------------------------------------------------------------------
 Lightweight, dependency-free debugging aids so future issues are easier to
 trace. Nothing here can crash the app (every path is guarded).

   dlog(*args)        -> timestamped line to console + (optional) desktop_debug.log
   last_error()       -> the most recent error string captured via capture()
   capture(label, e)  -> record an exception (also dlog'd); returns a short string
   recent(n)          -> last n log lines (in-memory ring buffer) for an on-screen panel
   diagnostics(src)    -> dict snapshot of the active data source (counts, backend)

 Toggle file logging with env DFU_DEBUG=1 (or pass enabled=True to set_enabled).
=============================================================================
"""
import collections
import datetime
import os
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.environ.get("DFU_DEBUG_LOG", os.path.join(HERE, "desktop_debug.log"))

_ENABLED = bool(os.environ.get("DFU_DEBUG"))
_RING = collections.deque(maxlen=300)
_LAST_ERROR = ""


def set_enabled(flag):
    global _ENABLED
    _ENABLED = bool(flag)


def dlog(*args):
    """Timestamped log line → console + ring buffer + file (file only if enabled)."""
    line = f"{datetime.datetime.now():%H:%M:%S} " + " ".join(str(a) for a in args)
    _RING.append(line)
    try:
        print("[dfu]", line)
    except Exception:
        pass
    if _ENABLED:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def capture(label, exc):
    """Record an exception with traceback; return a short user-facing string."""
    global _LAST_ERROR
    short = f"{type(exc).__name__}: {exc}"
    _LAST_ERROR = f"{label}: {short}"
    dlog("ERROR", _LAST_ERROR)
    if _ENABLED:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass
    return short


def last_error():
    return _LAST_ERROR


def recent(n=40):
    return list(_RING)[-n:]


def diagnostics(src):
    """Best-effort snapshot of the active data source for an on-screen debug bar."""
    try:
        d = src.diagnostics()
        return (f"backend={d.get('backend')} · patients={d.get('n_patients')} · "
                f"captures={d.get('n_captures')} · ok={d.get('ok')}")
    except Exception as e:
        return f"diagnostics failed: {type(e).__name__}: {e}"
