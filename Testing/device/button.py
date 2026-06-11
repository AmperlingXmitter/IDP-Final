"""
=============================================================================
 BUTTON  (Testing/device/button.py)
-----------------------------------------------------------------------------
 A single capture trigger with protection against repeat / long-press
 double-fires (spec F: "Only 1 capture at a time").

 Two ways it is used:
   * UI mode  : attach(callback) wires the real GPIO button to a handler.
                The simulated button is a KEY PRESS inside the UI (see ui.py) -
                we do NOT read the terminal here (that crashes Tkinter on macOS).
   * Headless : wait_for_press() / wait_for_dismiss() block in a console loop.

 accept() is the shared lockout guard used by BOTH the GPIO button and the
 UI key/onscreen button so the 1-capture-at-a-time rule holds either way.
=============================================================================
"""
import time
import config as C


class CaptureButton:
    def __init__(self):
        self._last_accepted = 0.0
        self._btn = None

        # The physical GPIO button is wired whenever USE_GPIO_BUTTON is on —
        # INDEPENDENT of SIMULATE_BUTTON. This lets the on-screen/key button
        # (SIMULATE_BUTTON) and the GPIO 17 button run at the same time.
        # Backwards compatible: if USE_GPIO_BUTTON isn't defined, fall back to
        # the old behaviour (GPIO only when not simulating).
        use_gpio = getattr(C, "USE_GPIO_BUTTON", not C.SIMULATE_BUTTON)
        if use_gpio:
            try:
                from gpiozero import Button   # Pi only (lgpio backend on Pi 5)
                self._btn = Button(C.BUTTON_GPIO_PIN, bounce_time=C.BUTTON_BOUNCE_S)
                if C.DEBUG:
                    print(f"[button] GPIO {C.BUTTON_GPIO_PIN} ready "
                          f"(alongside screen button: {C.SIMULATE_BUTTON})")
            except Exception as e:
                # No GPIO on this machine (e.g. laptop testing). Degrade to the
                # screen/key button only instead of crashing the whole device.
                self._btn = None
                print(f"[button] GPIO {C.BUTTON_GPIO_PIN} unavailable "
                      f"({type(e).__name__}: {e}) — using screen/key button only")

    # ---- shared lockout guard ---------------------------------------------
    def accept(self):
        """True if a press should be accepted (not inside the lockout window)."""
        if (time.monotonic() - self._last_accepted) < C.CAPTURE_LOCKOUT_S:
            if C.DEBUG:
                print("[button] press ignored (lockout active)")
            return False
        self._last_accepted = time.monotonic()
        return True

    # ---- UI mode: wire the hardware button to a callback ------------------
    def attach(self, callback):
        """Call `callback()` on each full press+release of the real button.
        No-op in SIMULATE_BUTTON mode (the UI key handles it instead)."""
        if self._btn is not None:
            self._btn.when_released = callback   # callback does its own accept()
            if C.DEBUG:
                print("[button] hardware button attached to handler")

    # ---- headless console mode --------------------------------------------
    #  Prefer the real GPIO button if one is wired; otherwise (or when
    #  simulating with no hardware) fall back to ENTER. UI mode (SHOW_UI=True)
    #  is the path that runs BOTH inputs at once via attach() + key bindings.
    def wait_for_press(self):
        """Block until ONE accepted press (console mode only)."""
        while True:
            if self._btn is not None and not C.SIMULATE_BUTTON:
                self._btn.wait_for_press()
                self._btn.wait_for_release()
            else:
                input("[button] (sim) press ENTER to capture... ")
            if self.accept():
                return

    def wait_for_dismiss(self):
        """One press to dismiss the consent screen (console mode only)."""
        if self._btn is not None and not C.SIMULATE_BUTTON:
            self._btn.wait_for_press()
            self._btn.wait_for_release()
        else:
            input("[button] (sim) press ENTER to agree & continue... ")
