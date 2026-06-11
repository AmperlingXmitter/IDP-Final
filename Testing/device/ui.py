"""
=============================================================================
 UI  (Testing/device/ui.py)  -  lightweight Tkinter kiosk for the 4.3" screen
-----------------------------------------------------------------------------
 Flow (spec A)
 -------------
   consent → selection → instructions → live
           → capturing (×N)  → analysing  → results → (dismiss) → live
   live → gallery_list (Captured Images) → results(selected) → gallery_list

 Screen states (handled by _screen_<name>):
   consent, selection, instructions, live, capturing, analysing,
   results, retake, gallery_list

 Physical button (multi-purpose, via physical_press) — spec "Back Button":
   consent       : agree → selection
   selection     : back  → consent
   instructions  : back  → selection
   live          : CAPTURE  (controller decides the lockout)
   capturing/analysing : ignored (locked during capture + AI)
   results       : dismiss (session → live, gallery → gallery_list)
   retake        : start over → live
   gallery_list  : back → live

 All on-screen wording lives in ui_text.py (spec D1). All fonts/margins come
 from config.py (spec D2/D3). The live preview is a Canvas: the MJPEG frame is
 the background image and the alignment SNARES are dotted Canvas lines drawn
 once on top (spec A6) — no per-frame redraw cost.
=============================================================================
"""

import io, os, queue, tkinter as tk
import config as C
import storage
import ui_text as T

# Optional: PIL for image display.
try:
    from PIL import Image, ImageTk
    _PIL = True
except ImportError:
    _PIL = False

# Convenience aliases from config.
M = C.UI_MARGIN

# Per-language font family for the consent screen (Pi needs fonts-noto-cjk for
# the Chinese block; falls back to the default font if that family is missing).
_LANG_FAMILY = {"en": C.UI_FONT_FAMILY, "ms": C.UI_FONT_FAMILY,
                "zh": "Noto Sans CJK SC"}

# Snare appearance (dotted, high-contrast so it reads in any lighting — spec A6).
_SNARE_BRIGHT = "#00e5ff"
_SNARE_DARK   = "#06222b"
_SNARE_DASH   = (3, 7)

# Thumbnail size for the Captured-Images list.
_LIST_THUMB_W, _LIST_THUMB_H = 96, 72

# Loading spinner frames (cheap rotating quadrant — minimal CPU, spec A5).
_SPIN_FRAMES = ["◐", "◓", "◑", "◒"]


# ============================================================================ #
class DeviceUI:

    def __init__(self, controller):
        self.ctrl = controller
        self.root = tk.Tk()
        self.root.title("DFU Monitor")
        self.root.configure(bg="black")
        if C.FULLSCREEN:
            self.root.attributes("-fullscreen", True)
        self.root.geometry(f"{C.SCREEN_W}x{C.SCREEN_H}")

        self._q = queue.Queue()
        self._light_label = "Flash Off"
        self._current_screen = "consent"

        # Live-preview state
        self._video_stream = None
        self._preview_job  = None
        self._preview_canvas = None
        self._preview_img_id = None
        self._preview_ph = None
        self._preview_w = C.SCREEN_W
        self._preview_h = C.SCREEN_H
        self._last_frame_obj = None

        # Spinner / per-screen transient state
        self._spin_job = None
        self._sel_angle = None            # selection: pending choice before Confirm
        self._instr_pages = []            # instructions: list of (heading, body)
        self._instr_page = 0
        self._res_session = None          # results: session dict being shown
        self._res_origin = "session"
        self._res_idx = 0

        # GC anchors for PhotoImage objects
        self._tk_imgs = []

        # Root frame
        self._frame = tk.Frame(self.root, bg="black")
        self._frame.pack(fill="both", expand=True)

        # Keyboard shortcuts (development/testing)
        self.root.bind("<space>",     lambda e: self.physical_press())
        self.root.bind("<Return>",    lambda e: self.physical_press())
        self.root.bind("<Escape>",    lambda e: self.root.destroy())
        self.root.bind("<BackSpace>", lambda e: self._go_back())

        self._poll()

    # ======================================================================== #
    #  Public API
    # ======================================================================== #
    def set_light_label(self, text):
        self._light_label = text
        self.post("_relight")

    def post(self, screen, data=None):
        self._q.put((screen, data or {}))

    def run(self):
        self.root.mainloop()

    def physical_press(self):
        scr = self._current_screen
        if scr == "consent":
            self.post("selection")
        elif scr == "selection":
            self.post("consent")
        elif scr == "instructions":
            self.post("selection")
        elif scr == "live":
            self.ctrl.on_capture()
        elif scr == "results":
            self._dismiss_results()
        elif scr == "retake":
            self.post("live")
        elif scr == "gallery_list":
            self.post("live")
        # capturing / analysing: ignored

    # ======================================================================== #
    #  Queue poller
    # ======================================================================== #
    def _poll(self):
        try:
            while True:
                screen, data = self._q.get_nowait()
                if screen == "_relight":
                    self._refresh_flash_btn()
                    continue
                # Free the camera when leaving the live screen.
                if self._current_screen == "live" and screen != "live":
                    self._stop_video()
                self._current_screen = screen
                handler = getattr(self, f"_screen_{screen}", self._screen_live)
                handler(data)
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    # ======================================================================== #
    #  Helpers
    # ======================================================================== #
    def _font(self, size, bold=False, family=None):
        fam = family or C.UI_FONT_FAMILY
        return (fam, size, "bold") if bold else (fam, size)

    def _clear(self):
        if self._preview_job is not None:
            self.root.after_cancel(self._preview_job)
            self._preview_job = None
        if self._spin_job is not None:
            self.root.after_cancel(self._spin_job)
            self._spin_job = None
        for w in self._frame.winfo_children():
            w.destroy()
        self._tk_imgs.clear()
        self._preview_canvas = None
        self._preview_img_id = None

    def _go_back(self):
        """BACKSPACE / soft-back: mirror the physical button's back behaviour."""
        scr = self._current_screen
        if scr in ("selection",):
            self.post("consent")
        elif scr == "instructions":
            self.post("selection")
        elif scr == "gallery_list":
            self.post("live")
        elif scr == "results":
            self._dismiss_results()

    def _load_tk_image(self, path, max_w, max_h):
        if not _PIL or not path or not os.path.exists(path):
            return None
        try:
            img = Image.open(path)
            img.thumbnail((max_w, max_h), Image.LANCZOS)
            ph = ImageTk.PhotoImage(img)
            self._tk_imgs.append(ph)
            return ph
        except Exception as e:
            if C.DEBUG:
                print(f"[ui] image load failed ({path}): {e}")
            return None

    @staticmethod
    def _bind_recursive(widget, event, callback):
        widget.bind(event, callback)
        for child in widget.winfo_children():
            DeviceUI._bind_recursive(child, event, callback)

    # ---- loading spinner (cheap; one Label updated via after) -------------
    def _start_spinner(self, label):
        def tick(i=0):
            try:
                label.config(text=_SPIN_FRAMES[i % len(_SPIN_FRAMES)])
            except tk.TclError:
                return
            self._spin_job = self.root.after(150, tick, i + 1)
        tick()

    # ======================================================================== #
    #  Live preview (Canvas: MJPEG background + dotted snares on top)
    # ======================================================================== #
    def _start_video(self):
        if not C.SHOW_LIVE_PREVIEW:
            return
        try:
            import camera
            self._video_stream = camera.VideoStream()
            self._video_stream.start()
        except Exception as e:
            if C.DEBUG:
                print(f"[ui] VideoStream start failed: {e}")
            self._video_stream = None

    def _stop_video(self):
        if self._video_stream is not None:
            try:
                self._video_stream.stop()
            except Exception:
                pass
            self._video_stream = None
        if self._preview_job is not None:
            self.root.after_cancel(self._preview_job)
            self._preview_job = None

    def _schedule_preview(self):
        """Pull the latest MJPEG frame and paint it as the canvas background.
        Reuses one PhotoImage via paste() to avoid per-frame allocation (2GB Pi)."""
        cv = self._preview_canvas
        if cv is None or self._current_screen != "live":
            return
        fb = self._video_stream.get_frame() if self._video_stream else None
        is_new = fb is not None and fb is not self._last_frame_obj
        if fb is not None and _PIL and (
                is_new or not getattr(C, "PREVIEW_SKIP_UNCHANGED", True)):
            try:
                self._last_frame_obj = fb
                w, h = self._preview_w, self._preview_h
                im = Image.open(io.BytesIO(fb))
                if getattr(C, "PREVIEW_JPEG_DRAFT", True):
                    try:
                        im.draft("RGB", (w, h))
                    except Exception:
                        pass
                img = im.convert("RGB").resize(
                    (w, h),
                    Image.BILINEAR if C.PREVIEW_FAST_RESIZE else Image.LANCZOS)
                if (getattr(C, "PREVIEW_REUSE_PHOTO", True)
                        and self._preview_ph is not None
                        and (self._preview_ph.width(), self._preview_ph.height()) == (w, h)):
                    self._preview_ph.paste(img)            # in place — no new alloc
                else:
                    self._preview_ph = ImageTk.PhotoImage(img)
                    cv.itemconfig(self._preview_img_id, image=self._preview_ph)
            except Exception:
                pass
        poll_hz  = getattr(C, "PREVIEW_POLL_HZ", C.PREVIEW_FPS)
        interval = max(15, int(1000 / max(1, poll_hz)))
        self._preview_job = self.root.after(interval, self._schedule_preview)

    # ---- snare + foot drawing (shared by live + instruction schematic) ----
    def _draw_snares(self, canvas, w, h, angle):
        """Dotted alignment guides (spec A6). 'side' = bucket (flat base + two
        short uprights); 'bottom' = two tall uprights for toes/heel."""
        def dotted(x0, y0, x1, y1):
            canvas.create_line(x0, y0, x1, y1, fill=_SNARE_DARK,
                               width=8, dash=_SNARE_DASH, capstyle="round")
            canvas.create_line(x0, y0, x1, y1, fill=_SNARE_BRIGHT,
                               width=4, dash=_SNARE_DASH, capstyle="round")

        if angle == "bottom":
            x1, x2 = int(w * 0.22), int(w * 0.78)
            top, bot = int(h * 0.12), int(h * 0.82)
            dotted(x1, top, x1, bot)
            dotted(x2, top, x2, bot)
        else:  # side → bucket
            left, right = int(w * 0.13), int(w * 0.87)
            base, up = int(h * 0.78), int(h * 0.40)
            dotted(left, base, right, base)   # flat bottom (sole)
            dotted(left, base, left, up)      # heel upright
            dotted(right, base, right, up)    # toe upright

    def _draw_foot(self, canvas, w, h, angle):
        """Simple foot silhouette with a red dot showing an example ulcer
        location (spec A3). Drawn from ovals so it reads at a glance."""
        skin = "#d8b48a"
        if angle == "bottom":   # sole facing camera — tall foot
            canvas.create_oval(w*.34, h*.20, w*.66, h*.86, fill=skin, outline="")
            for fx in (0.39, 0.46, 0.53, 0.60):
                canvas.create_oval(w*fx-6, h*.12, w*fx+8, h*.26, fill=skin, outline="")
            canvas.create_oval(w*.46, h*.52, w*.54, h*.60, fill="#c62828", outline="white")
        else:                   # side profile — long foot + ankle
            canvas.create_oval(w*.15, h*.46, w*.86, h*.74, fill=skin, outline="")
            canvas.create_oval(w*.13, h*.40, w*.34, h*.78, fill=skin, outline="")  # heel
            canvas.create_oval(w*.20, h*.18, w*.40, h*.58, fill=skin, outline="")  # ankle
            canvas.create_oval(w*.66, h*.52, w*.74, h*.60, fill="#c62828", outline="white")

    # ======================================================================== #
    #  Shared overlay buttons (standardised margins + large fonts)
    # ======================================================================== #
    def _add_back_button(self, command):
        tk.Button(self._frame, text=T.BACK_BTN, command=command,
                  font=self._font(C.FONT_BUTTON, True),
                  bg="#e65100", fg="white", bd=0,
                  activebackground="#bf360c", activeforeground="white",
                  padx=14, pady=8).place(relx=0.0, rely=0.0, anchor="nw", x=M, y=M)

    def _add_reset_button(self):
        """Bottom-left RESET (replaces the old power button, spec A5)."""
        tk.Button(self._frame, text=T.RESET_BTN, command=self.ctrl.on_reset,
                  font=self._font(C.FONT_SMALL, True),
                  bg="#455a64", fg="white", bd=0,
                  activebackground="#37474f", activeforeground="white",
                  padx=10, pady=8, cursor="hand2"
                  ).place(relx=0.0, rely=1.0, anchor="sw", x=M, y=-M)

    def _add_flash_button(self):
        is_on = self._light_label == "Light On"
        self._light_btn = tk.Label(
            self._frame, text=f"⚡ {self._light_label}",
            font=self._font(C.FONT_SMALL), bg="#f9a825" if is_on else "#37474f",
            fg="white", padx=10, pady=6, cursor="hand2")
        self._light_btn.place(relx=1.0, rely=0.0, anchor="ne", x=-M, y=M)
        self._light_btn.bind("<Button-1>", lambda e: self.set_light_label(self.ctrl.on_light()))

    def _refresh_flash_btn(self):
        try:
            if hasattr(self, "_light_btn") and self._light_btn.winfo_exists():
                is_on = self._light_label == "Light On"
                self._light_btn.config(text=f"⚡ {self._light_label}",
                                       bg="#f9a825" if is_on else "#37474f")
        except tk.TclError:
            pass

    def _add_capture_button(self):
        i, n = self.ctrl.index(), self.ctrl.count()
        tk.Button(self._frame, text=T.CAPTURE_BTN.format(i=i, n=n),
                  command=self.ctrl.on_capture,
                  font=self._font(C.FONT_BUTTON, True),
                  bg="#1565c0", fg="white", bd=0,
                  activebackground="#1976d2", activeforeground="white",
                  padx=28, pady=12, cursor="hand2"
                  ).place(relx=0.5, rely=1.0, anchor="s", y=-M)

    def _add_gallery_button(self):
        """Bottom-right access to the Captured-Images list."""
        n = len(storage.get_sessions(limit=1))
        tk.Button(self._frame, text="🗂", command=lambda: self.post("gallery_list"),
                  font=self._font(C.FONT_HEADING),
                  bg="#263238" if n else "#1c2226", fg="white", bd=0,
                  activebackground="#37474f", activeforeground="white",
                  padx=12, pady=6, cursor="hand2"
                  ).place(relx=1.0, rely=1.0, anchor="se", x=-M, y=-M)

    def _add_patient_id(self):
        """Top-centre Patient ID. Editable BEFORE the first capture; locked
        once a session is in progress (spec A5)."""
        if self.ctrl.locked():
            tk.Label(self._frame, text=T.ID_PREFIX.format(pid=C.PATIENT_ID),
                     font=self._font(C.FONT_SMALL), bg="#1c313a", fg="#78909c",
                     padx=8, pady=4).place(relx=0.5, rely=0.0, anchor="n", y=M)
        else:
            self._pid_btn = tk.Button(
                self._frame, text=T.ID_PREFIX.format(pid=C.PATIENT_ID),
                command=self._edit_patient_id, font=self._font(C.FONT_SMALL),
                bg="#1c313a", fg="#90caf9", bd=1, relief="solid",
                padx=8, pady=4, cursor="hand2")
            self._pid_btn.place(relx=0.5, rely=0.0, anchor="n", y=M)

    def _edit_patient_id(self):
        try:
            import touch_keyboard as kb
            new_id = kb.ask_patient_id(self.root, C.PATIENT_ID)
            if new_id:
                C.PATIENT_ID = new_id
                if hasattr(self, "_pid_btn"):
                    self._pid_btn.config(text=T.ID_PREFIX.format(pid=C.PATIENT_ID))
        except Exception as e:
            if C.DEBUG:
                print(f"[ui] Patient ID edit failed: {e}")

    # ---- shared full-screen drag-to-scroll (touch anywhere — spec D4) -----
    def _make_scrollable(self, bg):
        canvas = tk.Canvas(self._frame, bg=bg, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        inner = tk.Frame(canvas, bg=bg)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        drag = {"y": 0, "moved": False}

        def press(e):
            drag["y"] = e.widget.winfo_rooty() + e.y
            drag["moved"] = False

        def move(e):
            ny = e.widget.winfo_rooty() + e.y
            dy = ny - drag["y"]
            drag["y"] = ny
            if abs(dy) > 3:
                drag["moved"] = True
            if dy:
                canvas.yview_scroll(int(-dy / 6), "units")
        for w in (canvas, inner):
            w.bind("<ButtonPress-1>", press)
            w.bind("<B1-Motion>", move)
        return canvas, inner, drag, press, move

    # ======================================================================== #
    #  SCREEN: consent  (trilingual; PDPA 2010 highlighted)
    # ======================================================================== #
    def _screen_consent(self, data):
        self._clear()
        self._frame.configure(bg="black")

        tk.Button(self._frame, text=f"✔  {T.CONSENT_AGREE_BTN}",
                  command=lambda: self.post("selection"),
                  font=self._font(C.FONT_BUTTON, True),
                  bg="#2e7d32", fg="white", bd=0,
                  activebackground="#388e3c", activeforeground="white",
                  padx=20, pady=12, cursor="hand2").pack(side="bottom", pady=M)

        _, inner, *_ = self._make_scrollable("black")

        tk.Label(inner, text=T.CONSENT_TITLE, fg="white", bg="black",
                 font=self._font(C.FONT_TITLE, True),
                 wraplength=C.SCREEN_W - 40).pack(pady=(12, 4), padx=20)
        # Highlighted Malaysian law banner (spec A2).
        tk.Label(inner, text="⚖  Personal Data Protection Act 2010 (PDPA), Malaysia",
                 fg="#ffd54f", bg="black", font=self._font(C.FONT_SMALL, True),
                 wraplength=C.SCREEN_W - 40).pack(pady=(0, 8), padx=20)

        for lang in ("en", "ms", "zh"):
            block = T.CONSENT[lang]
            fam = _LANG_FAMILY[lang]
            tk.Label(inner, text=block["title"], fg="#90caf9", bg="black",
                     font=self._font(C.FONT_BODY, True, family=fam),
                     wraplength=C.SCREEN_W - 60).pack(pady=(8, 2), padx=24)
            tk.Label(inner, text=block["body"], fg="#e0e0e0", bg="black",
                     font=self._font(C.FONT_BODY, family=fam), justify="left",
                     wraplength=C.SCREEN_W - 60).pack(padx=28, pady=(0, 6))

    # ======================================================================== #
    #  SCREEN: selection  (side vs bottom of foot)
    # ======================================================================== #
    def _screen_selection(self, data):
        self._clear()
        self._frame.configure(bg="#101820")
        self._sel_angle = self._sel_angle or None

        self._add_back_button(lambda: self.post("consent"))

        tk.Label(self._frame, text=T.SELECT_TITLE, fg="white", bg="#101820",
                 font=self._font(C.FONT_TITLE, True)).pack(pady=(M + 4, 2))
        tk.Label(self._frame, text=T.SELECT_QUESTION, fg="#b0bec5", bg="#101820",
                 font=self._font(C.FONT_BODY)).pack(pady=(0, 8))

        choices = tk.Frame(self._frame, bg="#101820")
        choices.pack(expand=True)
        self._sel_cards = {}

        def make_card(angle, label):
            card = tk.Frame(choices, bg="#1c2a33", bd=3, relief="flat",
                            highlightthickness=3, highlightbackground="#1c2a33")
            card.pack(side="left", padx=18)
            cw, ch = 230, 200
            cv = tk.Canvas(card, width=cw, height=ch, bg="#1c2a33",
                           highlightthickness=0)
            cv.pack(padx=8, pady=(8, 2))
            self._draw_foot(cv, cw, ch, angle)
            tk.Label(card, text=label, fg="white", bg="#1c2a33",
                     font=self._font(C.FONT_BODY, True)).pack(pady=(0, 8))
            self._bind_recursive(card, "<Button-1>", lambda e, a=angle: self._select_angle(a))
            self._sel_cards[angle] = card

        make_card("side", T.SELECT_SIDE)
        make_card("bottom", T.SELECT_BOTTOM)

        self._confirm_btn = tk.Button(
            self._frame, text=T.SELECT_CONFIRM, command=self._confirm_selection,
            font=self._font(C.FONT_BUTTON, True), bg="#37474f", fg="#90a4ae",
            bd=0, padx=26, pady=12, state="disabled")
        self._confirm_btn.pack(side="bottom", pady=M)
        if self._sel_angle:
            self._select_angle(self._sel_angle)

    def _select_angle(self, angle):
        self._sel_angle = angle
        for a, card in getattr(self, "_sel_cards", {}).items():
            sel = (a == angle)
            card.config(highlightbackground="#00e5ff" if sel else "#1c2a33",
                        bg="#10323b" if sel else "#1c2a33")
            for child in card.winfo_children():
                try:
                    child.config(bg="#10323b" if sel else "#1c2a33")
                except tk.TclError:
                    pass
        self._confirm_btn.config(state="normal", bg="#1565c0", fg="white",
                                 activebackground="#1976d2", cursor="hand2")

    def _confirm_selection(self):
        if not self._sel_angle:
            return
        self.ctrl.set_angle(self._sel_angle)
        self.post("instructions")

    # ======================================================================== #
    #  SCREEN: instructions  (per-angle, multi-page)
    # ======================================================================== #
    def _screen_instructions(self, data):
        self._clear()
        self._frame.configure(bg="#101820")
        angle = self.ctrl.angle
        self._instr_pages = T.INSTRUCTIONS.get(angle, T.INSTRUCTIONS["side"])
        self._instr_page = 0
        self._add_back_button(lambda: self.post("selection"))
        self._render_instruction_page()

    def _render_instruction_page(self):
        # Clear everything except the back button by rebuilding a body frame.
        for w in self._frame.winfo_children():
            info = w.place_info()
            if info.get("anchor") == "nw":      # keep the back button
                continue
            w.destroy()

        angle = self.ctrl.angle
        page = self._instr_page
        total = len(self._instr_pages)
        heading, body = self._instr_pages[page]

        tk.Label(self._frame, text=T.INSTRUCT_TITLE, fg="white", bg="#101820",
                 font=self._font(C.FONT_TITLE, True)).pack(pady=(M + 2, 0))
        tk.Label(self._frame, text=f"{page + 1}/{total}", fg="#90caf9",
                 bg="#101820", font=self._font(C.FONT_SMALL, True)).pack()

        body_row = tk.Frame(self._frame, bg="#101820")
        body_row.pack(expand=True, fill="both", padx=10)

        # Left arrow (disabled on first page)
        self._instr_arrow(body_row, "◀", -1, side="left", enabled=page > 0)

        centre = tk.Frame(body_row, bg="#101820")
        centre.pack(side="left", expand=True, fill="both")
        # Schematic: the expected live screen (foot + snares) for this angle.
        cw, ch = 250, 180
        cv = tk.Canvas(centre, width=cw, height=ch, bg="#000000",
                       highlightthickness=1, highlightbackground="#37474f")
        cv.pack(pady=(6, 6))
        self._draw_foot(cv, cw, ch, angle)
        self._draw_snares(cv, cw, ch, angle)
        tk.Label(centre, text=heading, fg="white", bg="#101820",
                 font=self._font(C.FONT_HEADING, True),
                 wraplength=C.SCREEN_W - 180).pack()
        tk.Label(centre, text=body, fg="#cfd8dc", bg="#101820",
                 font=self._font(C.FONT_BODY), justify="center",
                 wraplength=C.SCREEN_W - 180).pack(pady=(2, 4))

        self._instr_arrow(body_row, "▶", +1, side="right",
                          enabled=page < total - 1)

        # On the last page: "I Understand" → live.
        if page == total - 1:
            tk.Button(self._frame, text=f"✔  {T.INSTRUCT_UNDERSTAND_BTN}",
                      command=lambda: self.post("live"),
                      font=self._font(C.FONT_BUTTON, True), bg="#2e7d32",
                      fg="white", bd=0, activebackground="#388e3c",
                      padx=22, pady=12, cursor="hand2").pack(side="bottom", pady=M)

    def _instr_arrow(self, parent, glyph, direction, side, enabled):
        tk.Button(parent, text=glyph,
                  command=(lambda: self._instr_nav(direction)) if enabled else None,
                  font=self._font(C.FONT_TITLE, True),
                  bg="#263238" if enabled else "#141c20",
                  fg="white" if enabled else "#37474f",
                  state="normal" if enabled else "disabled",
                  bd=0, padx=10, cursor="hand2").pack(side=side, fill="y")

    def _instr_nav(self, direction):
        self._instr_page = max(0, min(len(self._instr_pages) - 1,
                                      self._instr_page + direction))
        self._render_instruction_page()

    # ======================================================================== #
    #  SCREEN: live  (preview + angle snares + capture/reset/flash/gallery/id)
    # ======================================================================== #
    def _screen_live(self, data):
        self._clear()
        self._frame.configure(bg="black")
        angle = self.ctrl.angle

        if C.SHOW_LIVE_PREVIEW and _PIL:
            self._preview_w, self._preview_h = C.SCREEN_W, C.SCREEN_H
            self._preview_ph = None
            self._last_frame_obj = None
            cv = tk.Canvas(self._frame, width=C.SCREEN_W, height=C.SCREEN_H,
                           bg="black", highlightthickness=0)
            cv.place(x=0, y=0, relwidth=1.0, relheight=1.0)
            self._preview_canvas = cv
            self._preview_img_id = cv.create_image(0, 0, anchor="nw")
            self._draw_snares(cv, C.SCREEN_W, C.SCREEN_H, angle)   # dotted, once
            self._start_video()
            self._schedule_preview()
        else:
            cv = tk.Canvas(self._frame, bg="#101820", highlightthickness=0)
            cv.place(x=0, y=0, relwidth=1.0, relheight=1.0)
            self._draw_snares(cv, C.SCREEN_W, C.SCREEN_H, angle)
            tk.Label(self._frame, text=f"Patient {C.PATIENT_ID}\n(no live preview)",
                     fg="white", bg="#101820",
                     font=self._font(C.FONT_HEADING, True)).place(relx=0.5, rely=0.4,
                                                                  anchor="center")

        # Overlaid controls (drawn on top of the canvas).
        self._add_patient_id()
        self._add_flash_button()
        self._add_capture_button()
        self._add_reset_button()
        self._add_gallery_button()

    # ======================================================================== #
    #  SCREEN: capturing / analysing  (separate states, animated loaders)
    # ======================================================================== #
    def _screen_capturing(self, data):
        i, n = data.get("i", self.ctrl.index()), data.get("n", self.ctrl.count())
        self._loading_screen(T.CAPTURING_MSG, sub=f"{i} / {n}", bg="#0d1b2a")

    def _screen_analysing(self, data):
        self._loading_screen(T.ANALYSING_MSG,
                             sub=f"{data.get('n', self.ctrl.count())} images",
                             bg="#1a0d2a")

    def _loading_screen(self, message, sub, bg):
        self._clear()
        self._frame.configure(bg=bg)
        wrap = tk.Frame(self._frame, bg=bg)
        wrap.place(relx=0.5, rely=0.5, anchor="center")
        spin = tk.Label(wrap, text=_SPIN_FRAMES[0], fg="#00e5ff", bg=bg,
                        font=self._font(40, True))
        spin.pack(pady=(0, 10))
        tk.Label(wrap, text=message, fg="white", bg=bg,
                 font=self._font(C.FONT_TITLE, True)).pack()
        tk.Label(wrap, text=sub, fg="#90a4ae", bg=bg,
                 font=self._font(C.FONT_BODY)).pack(pady=(4, 0))
        self._start_spinner(spin)

    # ======================================================================== #
    #  SCREEN: results  (N overlays + averaged stage; no wound %; no back btn)
    # ======================================================================== #
    def _screen_results(self, data):
        self._clear()
        if data.get("session") is not None:
            self._res_session = data["session"]
            self._res_origin = data.get("origin", "session")
            self._res_idx = 0

        sess = self._res_session or {}
        stage = sess.get("avg_stage", "?")
        colour = C.UT_STAGE_COLOURS.get(stage, C.UT_STAGE_COLOURS["?"])
        label = sess.get("avg_label") if stage != "?" else T.RESULTS_NO_ULCER
        self._frame.configure(bg=colour)

        # Done button (dismiss) — no Back button on Results (spec A7).
        tk.Button(self._frame, text=f"✔  {T.RESULTS_DONE_BTN}",
                  command=self._dismiss_results,
                  font=self._font(C.FONT_BUTTON, True), bg="#ffffff", fg=colour,
                  bd=0, padx=26, pady=10, cursor="hand2").pack(side="bottom", pady=M)

        # Averaged stage label (with description + colour background).
        tk.Label(self._frame, text=label or "—", fg="white", bg=colour,
                 font=self._font(C.FONT_HEADING, True),
                 wraplength=C.SCREEN_W - 80, justify="center"
                 ).pack(side="bottom", pady=(2, 2))

        self._res_area = tk.Frame(self._frame, bg=colour)
        self._res_area.pack(fill="both", expand=True)
        self._render_result_image()

    def _render_result_image(self):
        for w in self._res_area.winfo_children():
            w.destroy()
        sess = self._res_session or {}
        imgs = sess.get("images", [])
        colour = C.UT_STAGE_COLOURS.get(sess.get("avg_stage", "?"),
                                        C.UT_STAGE_COLOURS["?"])
        n = len(imgs)
        if n == 0:
            tk.Label(self._res_area, text="No images", fg="white", bg=colour,
                     font=self._font(C.FONT_BODY)).pack(expand=True)
            return
        self._res_idx %= n
        row = imgs[self._res_idx]
        # Prefer the cropped close-up (spec A7 "cropped version if available").
        path = (row.get("closeup_path") or row.get("overlay_path")
                or row.get("captured_path"))

        nav = tk.Frame(self._res_area, bg=colour)
        nav.pack(fill="both", expand=True)
        has_arrows = n > 1
        self._res_arrow(nav, "◀", -1, "left", has_arrows, colour)
        centre = tk.Frame(nav, bg=colour)
        centre.pack(side="left", fill="both", expand=True)
        ph = self._load_tk_image(path, C.SCREEN_W - 150, C.SCREEN_H - 170)
        if ph:
            tk.Label(centre, image=ph, bg=colour).pack(pady=(M, 2))
        tk.Label(centre, text=T.RESULTS_NAV.format(i=self._res_idx + 1, n=n),
                 fg="white", bg=colour, font=self._font(C.FONT_SMALL, True)).pack()
        self._res_arrow(nav, "▶", +1, "right", has_arrows, colour)

    def _res_arrow(self, parent, glyph, direction, side, enabled, colour):
        tk.Button(parent, text=glyph,
                  command=(lambda: self._res_nav(direction)) if enabled else None,
                  font=self._font(C.FONT_TITLE, True),
                  bg="#ffffff" if enabled else colour,
                  fg=colour if enabled else colour,
                  state="normal" if enabled else "disabled",
                  bd=0, padx=10, cursor="hand2").pack(side=side, fill="y")

    def _res_nav(self, direction):
        self._res_idx += direction
        self._render_result_image()

    def _dismiss_results(self):
        if self._res_origin == "gallery":
            self.post("gallery_list")
        else:
            self.ctrl.on_done()       # → live (counter reset by controller)

    # ======================================================================== #
    #  SCREEN: retake  (session images too dissimilar)
    # ======================================================================== #
    def _screen_retake(self, data):
        self._clear()
        self._frame.configure(bg="#5d4037")
        wrap = tk.Frame(self._frame, bg="#5d4037")
        wrap.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(wrap, text="⚠", fg="#ffd54f", bg="#5d4037",
                 font=self._font(40, True)).pack()
        tk.Label(wrap, text=T.RETAKE_TITLE, fg="white", bg="#5d4037",
                 font=self._font(C.FONT_TITLE, True)).pack(pady=(4, 4))
        tk.Label(wrap, text=T.RETAKE_BODY, fg="#efebe9", bg="#5d4037",
                 font=self._font(C.FONT_BODY), justify="center",
                 wraplength=C.SCREEN_W - 120).pack()
        tk.Button(self._frame, text=T.RETAKE_BTN, command=lambda: self.post("live"),
                  font=self._font(C.FONT_BUTTON, True), bg="#ffffff", fg="#5d4037",
                  bd=0, padx=26, pady=10, cursor="hand2").pack(side="bottom", pady=M)

    # ======================================================================== #
    #  SCREEN: gallery_list  (Captured Images — grouped by session)
    # ======================================================================== #
    def _screen_gallery_list(self, data):
        self._clear()
        self._frame.configure(bg="#1a1a2e")

        header = tk.Frame(self._frame, bg="#16213e", height=C.UI_BTN_H_SM + 6)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Button(header, text=T.BACK_BTN, command=lambda: self.post("live"),
                  font=self._font(C.FONT_BUTTON, True), bg="#e65100", fg="white",
                  bd=0, activebackground="#bf360c", padx=14, pady=4
                  ).pack(side="left", padx=M, pady=4)
        tk.Label(header, text=T.GALLERY_TITLE, fg="white", bg="#16213e",
                 font=self._font(C.FONT_HEADING, True)).pack(side="left", padx=8)

        sessions = storage.get_sessions()
        if not sessions:
            tk.Label(self._frame, text=T.GALLERY_EMPTY, fg="#90a4ae", bg="#1a1a2e",
                     font=self._font(C.FONT_HEADING)).pack(expand=True)
            return

        _, inner, drag, press, move = self._make_scrollable("#1a1a2e")
        for s in sessions:
            self._add_session_row(inner, s, drag, press, move)

    def _add_session_row(self, parent, s, drag, press, move):
        row = tk.Frame(parent, bg="#263238", pady=6, padx=8, cursor="hand2")
        row.pack(fill="x", padx=6, pady=3)

        ph = self._load_tk_image(s.get("thumb_path"), _LIST_THUMB_W, _LIST_THUMB_H)
        if ph:
            tk.Label(row, image=ph, bg="#263238").pack(side="left", padx=(0, 10))
        else:
            tk.Frame(row, width=_LIST_THUMB_W, height=_LIST_THUMB_H,
                     bg="#37474f").pack(side="left", padx=(0, 10))

        txt = tk.Frame(row, bg="#263238")
        txt.pack(side="left", fill="both", expand=True)

        stamp = s.get("stamp", "")
        dt = (f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}  {stamp[9:11]}:{stamp[11:13]}"
              if len(stamp) == 15 else stamp)
        stage = s.get("avg_stage", "?")
        colour = C.UT_STAGE_COLOURS.get(stage, C.UT_STAGE_COLOURS["?"])
        wp = s.get("avg_wound_pct")
        wp_txt = f"   ·   Wound {wp:.1f}%" if wp is not None else ""
        n = s.get("n_images") or 0
        wrap = C.SCREEN_W - _LIST_THUMB_W - 70

        tk.Label(txt, text=f"ID {s.get('patient_id','?')}   ·   {dt}   ·   {n} imgs",
                 fg="#90caf9", bg="#263238", font=self._font(C.FONT_SMALL),
                 wraplength=wrap, justify="left").pack(anchor="w")
        stage_txt = (s.get("avg_label") or "—").split("\n")[0] if stage != "?" \
            else T.RESULTS_NO_ULCER
        tk.Label(txt, text=stage_txt + wp_txt, fg="white", bg="#263238",
                 font=self._font(C.FONT_BODY, True),
                 wraplength=wrap, justify="left").pack(anchor="w")

        tk.Frame(row, width=8, bg=colour).pack(side="right", fill="y")

        def on_tap(e, sid=s.get("session_id")):
            if not drag["moved"]:
                self._open_session(sid)
        self._bind_recursive(row, "<ButtonPress-1>", press)
        self._bind_recursive(row, "<B1-Motion>", move)
        self._bind_recursive(row, "<ButtonRelease-1>", on_tap)

    def _open_session(self, session_id):
        rows = storage.get_session(session_id)
        if not rows:
            return
        head = rows[0]
        sess = {
            "session_id": session_id, "avg_stage": head.get("avg_stage"),
            "avg_label": head.get("avg_label"),
            "avg_wound_pct": head.get("avg_wound_pct"),
            "n_images": head.get("n_images") or len(rows), "images": rows,
        }
        self.post("results", {"session": sess, "origin": "gallery"})
