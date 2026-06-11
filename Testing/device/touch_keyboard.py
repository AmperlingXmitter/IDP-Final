"""
=============================================================================
 ON-SCREEN KEYBOARD  (Testing/device/touch_keyboard.py)
-----------------------------------------------------------------------------
 ask_patient_id(root, current_id="") -> str | None

 Modal Toplevel keyboard designed for the 800×480 capacitive touchscreen.
 Returns the new Patient ID string on Confirm, None on Cancel.
 The Confirm button is disabled while the entry field is empty.

 Layout (5 rows of keys):
   Row 1: Q W E R T Y U I O P
   Row 2: A S D F G H J K L
   Row 3: Z X C V B N M
   Row 4: 1 2 3 4 5 6 7 8 9 0
   Row 5: [⌫ BACK]  [CLR]  [✔ CONFIRM]

 Flag: DEBUG in config.py prints popup open/close events.
=============================================================================
"""
import tkinter as tk
import config as C


# --------------------------------------------------------------------------- #
#  Key layout
# --------------------------------------------------------------------------- #
_ROWS = [
    list("QWERTYUIOP"),
    list("ASDFGHJKL"),
    list("ZXCVBNM"),
    list("1234567890"),
]

_KW   = 62   # standard key width  (px)
_KH   = 44   # key height
_KGAP = 4    # horizontal gap between keys
_RGAP = 5    # vertical gap between rows


def ask_patient_id(root, current_id=""):
    """
    Opens a modal on-screen keyboard centred on the screen.

    Parameters
    ----------
    root       : the Tk root window
    current_id : pre-fill the entry with this string

    Returns
    -------
    str  — the new patient ID if Confirm was pressed
    None — if Cancel / outside-tap / Escape
    """
    result = {"value": None}

    if C.DEBUG:
        print(f"[keyboard] opening popup, current_id={current_id!r}")

    # ------------------------------------------------------------------ Popup
    pop = tk.Toplevel(root)
    pop.overrideredirect(True)        # no title bar on the kiosk
    pop.attributes("-topmost", True)
    pop.configure(bg="black")
    pop.geometry(f"{C.SCREEN_W}x{C.SCREEN_H}+0+0")

    # Dark overlay behind the panel — tapping it cancels
    overlay = tk.Label(pop, bg="black")
    overlay.place(x=0, y=0, width=C.SCREEN_W, height=C.SCREEN_H)
    overlay.bind("<Button-1>", lambda e: pop.destroy())

    # ----------------------------------------------------------------- Panel
    # Measure panel height: entry bar + rows + special row + padding
    n_rows   = len(_ROWS) + 1    # alpha/digit rows + special-key row
    panel_h  = 72 + n_rows * (_KH + _RGAP) + 32 + 12
    panel_y  = (C.SCREEN_H - panel_h) // 2
    panel    = tk.Frame(pop, bg="#1a1a2e", bd=0)
    panel.place(x=0, y=panel_y, width=C.SCREEN_W, height=panel_h)
    # Prevent panel clicks from falling through to the cancel overlay
    panel.bind("<Button-1>", lambda e: "break")

    # ----------------------------------------------------------------- Entry
    ev = tk.StringVar(value=current_id)
    confirm_ref = [None]           # forward reference to Confirm button

    entry_bar = tk.Frame(panel, bg="#263238", height=60)
    entry_bar.pack(fill="x", padx=16, pady=(10, 6))
    entry_bar.pack_propagate(False)

    tk.Label(
        entry_bar, text="Patient ID :",
        fg="#90caf9", bg="#263238",
        font=("DejaVu Sans", 13),
    ).pack(side="left", padx=(10, 6))

    tk.Label(
        entry_bar, textvariable=ev,
        fg="white", bg="#37474f",
        font=("DejaVu Sans", 22, "bold"),
        anchor="w", padx=10, width=9,
    ).pack(side="left", fill="y")

    def _refresh():
        state = "normal" if ev.get().strip() else "disabled"
        if confirm_ref[0]:
            confirm_ref[0].config(state=state)

    # ----------------------------------------------------------------- Keys
    def _press(ch):
        if ch == "⌫":
            ev.set(ev.get()[:-1])
        elif ch == "CLR":
            ev.set("")
        elif ch == "OK":
            v = ev.get().strip()
            if v:
                result["value"] = v
                if C.DEBUG:
                    print(f"[keyboard] confirmed: {v!r}")
                pop.destroy()
        else:
            ev.set(ev.get() + ch)
        _refresh()

    kb = tk.Frame(panel, bg="#1a1a2e")
    kb.pack()

    for row_chars in _ROWS:
        row_f = tk.Frame(kb, bg="#1a1a2e")
        row_f.pack(pady=(_RGAP // 2))
        for ch in row_chars:
            tk.Button(
                row_f, text=ch,
                command=lambda c=ch: _press(c),
                font=("DejaVu Sans", 13, "bold"),
                bg="#263238", fg="white", bd=0,
                activebackground="#455a64", activeforeground="white",
                width=3, height=1,
            ).pack(side="left", padx=_KGAP // 2)

    # Special row: ⌫ Back · CLR · ✔ Confirm
    spec = tk.Frame(kb, bg="#1a1a2e")
    spec.pack(pady=(_RGAP + 2))

    tk.Button(
        spec, text="⌫  Back",
        command=lambda: _press("⌫"),
        font=("DejaVu Sans", 12, "bold"),
        bg="#455a64", fg="white", bd=0,
        activebackground="#546e7a", activeforeground="white",
        width=9, height=1,
    ).pack(side="left", padx=4)

    tk.Button(
        spec, text="CLR",
        command=lambda: _press("CLR"),
        font=("DejaVu Sans", 12, "bold"),
        bg="#b71c1c", fg="white", bd=0,
        activebackground="#c62828", activeforeground="white",
        width=5, height=1,
    ).pack(side="left", padx=4)

    confirm_btn = tk.Button(
        spec, text="✔  Confirm",
        command=lambda: _press("OK"),
        font=("DejaVu Sans", 12, "bold"),
        bg="#2e7d32", fg="white", bd=0,
        activebackground="#388e3c", activeforeground="white",
        width=10, height=1,
        state="normal" if current_id.strip() else "disabled",
    )
    confirm_btn.pack(side="left", padx=4)
    confirm_ref[0] = confirm_btn

    # Cancel link
    tk.Button(
        panel, text="✕  Cancel",
        command=pop.destroy,
        font=("DejaVu Sans", 11),
        bg="#1a1a2e", fg="#78909c", bd=0,
        activebackground="#263238", activeforeground="white",
    ).pack(pady=(4, 0))

    # Keyboard shortcut (laptop testing)
    pop.bind("<Escape>", lambda e: pop.destroy())

    pop.grab_set()
    root.wait_window(pop)
    if C.DEBUG:
        print(f"[keyboard] popup closed, result={result['value']!r}")
    return result["value"]
