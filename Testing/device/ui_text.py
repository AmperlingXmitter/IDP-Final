"""
=============================================================================
 UI TEXT  (Testing/device/ui_text.py)  -  ONE place for ALL on-screen wording
-----------------------------------------------------------------------------
 Spec D1: keep every user-facing string here so it is easy to (a) grammar-check
 and (b) translate. Nothing in the UI hard-codes prose — it pulls from here.

 Layout
 ------
   CONSENT is shown in THREE languages stacked on one screen (spec A2):
       top = English, middle = Malay, bottom = Simplified Chinese.
   Other screens use English ("clear & direct", spec). To add a language later,
   give those screens the same TITLE/BODY trio and let the UI stack or switch
   them — the structure mirrors CONSENT so it is a small change.

 Conventions
 -----------
   * Plain, short sentences (older patients, small screen).
   * "{i}" / "{n}" placeholders are filled with .format(i=..., n=...) by the UI.
   * Malaysian law (PDPA 2010) is named explicitly in the consent text.
=============================================================================
"""

# --------------------------------------------------------------------------- #
#  CONSENT  (trilingual — all three shown together, English → Malay → Chinese)
#  PDPA 2010 = Malaysia's Personal Data Protection Act 2010.
# --------------------------------------------------------------------------- #
CONSENT_TITLE = "Consent — Medical Device"

CONSENT = {
    # English (top)
    "en": {
        "title": "Consent — Medical Device",
        "body": (
            "This device takes photos of your foot to help medical staff "
            "monitor a diabetic foot ulcer. It is a screening aid only — not a "
            "diagnosis. All results are reviewed by a doctor.\n"
            "Your personal data is protected under Malaysia's Personal Data "
            "Protection Act 2010 (PDPA). Your images and results are shared "
            "only with your care team and stored securely.\n"
            "Press the button once to agree and continue."
        ),
    },
    # Malay (middle)
    "ms": {
        "title": "Kebenaran — Peranti Perubatan",
        "body": (
            "Peranti ini mengambil gambar kaki anda untuk membantu kakitangan "
            "perubatan memantau ulser kaki diabetik. Ia hanya alat saringan — "
            "bukan diagnosis. Semua keputusan disemak oleh doktor.\n"
            "Data peribadi anda dilindungi di bawah Akta Perlindungan Data "
            "Peribadi 2010 (PDPA) Malaysia. Imej dan keputusan anda dikongsi "
            "hanya dengan pasukan penjagaan anda dan disimpan dengan selamat.\n"
            "Tekan butang sekali untuk bersetuju dan teruskan."
        ),
    },
    # Simplified Chinese (bottom)
    "zh": {
        "title": "知情同意 — 医疗设备",
        "body": (
            "本设备会拍摄您足部的照片，帮助医护人员监测糖尿病足溃疡。"
            "这仅是筛查辅助工具，并非诊断。所有结果均由医生审核。\n"
            "您的个人资料受马来西亚《2010年个人资料保护法令》(PDPA) 保护。"
            "您的图像和结果仅与您的护理团队共享，并安全存储。\n"
            "按一次按钮即表示同意并继续。"
        ),
    },
}

CONSENT_AGREE_BTN = "Agree & Continue"

# --------------------------------------------------------------------------- #
#  USER SELECTION  (choose which angle of the foot — spec A3)
# --------------------------------------------------------------------------- #
SELECT_TITLE     = "Select the Foot Angle"
SELECT_QUESTION  = "Which part of the foot has the ulcer?"
SELECT_SIDE      = "Side of foot"
SELECT_BOTTOM    = "Bottom of foot"
SELECT_CONFIRM   = "Confirm"

# --------------------------------------------------------------------------- #
#  USER INSTRUCTIONS  (per chosen angle, multi-page — spec A4)
#  Each entry is a list of pages; each page = (heading, body). The UI shows
#  "1/N", "2/N"… with left/right arrows and a "I Understand" button on the last.
# --------------------------------------------------------------------------- #
INSTRUCT_TITLE = "How to Capture"
INSTRUCT_UNDERSTAND_BTN = "I Understand"

INSTRUCTIONS = {
    "side": [
        ("Rest the foot on its side",
         "Turn the foot so the SIDE with the ulcer faces the camera."),
        ("Line up with the guides",
         "Put the flat sole on the bottom guide line. Rest the toes and heel "
         "against the two short side guides — like sitting in a bucket."),
        ("Hold straight and steady",
         "Hold the camera straight above, square to the foot. Keep still, "
         "then press Capture. Three photos will be taken."),
    ],
    "bottom": [
        ("Show the sole",
         "Lift the foot so the BOTTOM (sole) with the ulcer faces the camera."),
        ("Line up with the guides",
         "Put the toes against one side guide and the heel against the other, "
         "so the whole sole fills the space between them."),
        ("Hold straight and steady",
         "Hold the camera straight on, square to the sole. Keep still, then "
         "press Capture. Three photos will be taken."),
    ],
}

# --------------------------------------------------------------------------- #
#  LIVE VIDEO SCREEN  (spec A5)
# --------------------------------------------------------------------------- #
CAPTURE_BTN     = "Capture {i}/{n}"     # e.g. "Capture 1/3"
CAPTURING_MSG   = "Capturing Image…"
ANALYSING_MSG   = "AI Analysing Images…"
RESET_BTN       = "⟲ Reset"
ID_PREFIX       = "ID: {pid}"
ID_LOCKED_HINT  = "ID locked during capture"

# --------------------------------------------------------------------------- #
#  RESULTS SCREEN  (spec A7 — 3 overlays + averaged stage, no wound %)
# --------------------------------------------------------------------------- #
RESULTS_TITLE   = "Results"
RESULTS_DONE_BTN = "Done"
RESULTS_NAV     = "{i} / {n}"           # which of the N overlays is shown
RESULTS_NO_ULCER = "No ulcer detected"

# --------------------------------------------------------------------------- #
#  LIST OF CAPTURED IMAGES  (spec A9)
# --------------------------------------------------------------------------- #
GALLERY_TITLE   = "Captured Images"
GALLERY_EMPTY   = "No captures yet."
GALLERY_ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}   # extended in code for n>3

# --------------------------------------------------------------------------- #
#  RETAKE / ERROR  (session-similarity gate — spec B / "reject dissimilar")
# --------------------------------------------------------------------------- #
RETAKE_TITLE    = "Please Retake"
RETAKE_BODY     = (
    "The photos look too different from each other. Line the foot up the same "
    "way for all photos, then capture again."
)
RETAKE_BTN      = "Retake"

# --------------------------------------------------------------------------- #
#  COMMON
# --------------------------------------------------------------------------- #
BACK_BTN   = "◀ Back"
NEXT_BTN   = "Next ▶"
PREV_BTN   = "◀ Prev"


def ordinal(i):
    """1->'1st', 2->'2nd', 3->'3rd', 4->'4th'… (used for image labels)."""
    if i in GALLERY_ORDINAL:
        return GALLERY_ORDINAL[i]
    if 10 <= (i % 100) <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(i % 10, "th")
    return f"{i}{suf}"
