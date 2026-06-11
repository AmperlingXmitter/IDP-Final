"""
=============================================================================
 LIGHT  (Testing/device/light.py)  -  WS2812 ring/strip + flash control
-----------------------------------------------------------------------------
 Three modes, cycled by the small corner button on the UI:
     0  Flash Off    - light never turns on
     1  Flash On     - light turns on only WHILE a picture is taken
     2  Light On     - light stays on continuously

 The actual WS2812 driver is OPTIONAL and gated by config.ENABLE_LIGHT, so the
 app runs fine on a laptop (or a Pi without the LED wired) - it just prints.

 NOTE for Raspberry Pi 5: the classic rpi_ws281x (PWM/DMA) library does NOT
 work on the Pi 5's new GPIO chip. Use a Pi-5-compatible driver when you wire
 the LED (e.g. the SPI method, or a 'Pi5Neo' / 'rpi5-ws2812' package). The
 driver code is isolated in _hw_* below so you only change it in one place.
=============================================================================
"""
import config as C

MODES = ["Flash Off", "Flash On", "Light On"]
FLASH_OFF, FLASH_ON, LIGHT_ON = 0, 1, 2


class Light:
    def __init__(self):
        self.mode = FLASH_OFF
        self._dev = None
        if C.ENABLE_LIGHT:
            self._hw_init()
        self.apply_static()

    @property
    def mode_name(self):
        return MODES[self.mode]

    def cycle(self):
        """Advance to the next mode (called by the UI corner button)."""
        self.mode = (self.mode + 1) % len(MODES)
        if C.DEBUG:
            print(f"[light] mode -> {self.mode_name}")
        self.apply_static()
        return self.mode_name

    # ---- called by the capture cycle --------------------------------------
    def flash_on(self):
        if self.mode == FLASH_ON:
            self._set(True)

    def flash_off(self):
        if self.mode == FLASH_ON:
            self._set(False)

    def apply_static(self):
        """Light On -> steady on; the two Flash modes -> off between captures."""
        self._set(self.mode == LIGHT_ON)

    def shutdown(self):
        self._set(False)

    # ---- low-level on/off --------------------------------------------------
    def _set(self, on):
        if self._dev is None:
            return
        self._hw_set(on)

    # ===== HARDWARE DRIVER (edit only here when wiring the real LED) ========
    def _hw_init(self):
        try:
            from rpi5_ws2812.ws2812 import WS2812SpiDriver
            driver = WS2812SpiDriver(spi_bus=0, spi_device=0, led_count=C.LIGHT_COUNT)
            self._dev = driver.get_strip()
            if C.DEBUG:
                print("[light] rpi5-ws2812 SPI driver started")
        except Exception as e:
            print(f"[light] WARNING: LED driver unavailable ({e}); running no-op")
            self._dev = None

    def _hw_set(self, on):
        if self._dev is None:
            return
        from rpi5_ws2812.ws2812 import Color
        self._dev.set_all_pixels(Color(255, 255, 255) if on else Color(0, 0, 0))
        self._dev.show()