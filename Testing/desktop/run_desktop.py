"""
=============================================================================
 RUN DESKTOP  (Testing/desktop/run_desktop.py)
-----------------------------------------------------------------------------
 Launches the Dash app inside a NATIVE desktop window (pywebview) so medical
 staff get an app, not a browser tab. Same pattern as your example app.

     python run_desktop.py

 The Dash server runs on a background thread (127.0.0.1, local only); pywebview
 opens a window pointed at it. Closing the window stops everything.
=============================================================================
"""
import os, threading, time
import webview                      # pip install pywebview
from app import app                 # the Dash app

HOST, PORT = "127.0.0.1", 8050
# Set DFU_DEBUG=1 to enable Dash dev tools (in-browser error overlay + logging).
_DEBUG = bool(os.environ.get("DFU_DEBUG"))


def _serve():
    # threaded server so the UI window stays responsive
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False,
            dev_tools_ui=_DEBUG, dev_tools_props_check=_DEBUG)


def main():
    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    time.sleep(1.0)                 # give the server a moment to come up
    webview.create_window("DFU Monitor — Staff", f"http://{HOST}:{PORT}",
                          width=1200, height=800)
    webview.start()                 # blocks until the window is closed


if __name__ == "__main__":
    main()
