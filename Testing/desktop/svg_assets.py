"""
=============================================================================
 SVG ASSETS  (Testing/desktop/svg_assets.py)
-----------------------------------------------------------------------------
 Small, self-contained SVG generators used by the desktop app. Kept in their
 own file (spec J: multiple files) so app.py stays focused on layout/callbacks.

 Provides:
   gender_avatar_datauri(gender, ...)   -> generic male/female/neutral silhouette
                                           (spec #2: replace "?" with a silhouette)
   foot_diagram_datauri(selected, ...)  -> left+right foot map with a marked site
   FOOT_ZONES                           -> {code: (cx, cy, label)} for click overlay
   FOOT_VIEW_W / FOOT_VIEW_H            -> SVG canvas size the zones are placed in
   STAGE_SYMBOL / STAGE_LETTER          -> colour-blind cues (shape + letter)

 Every generator returns a base64 data URI so it can drop straight into
 html.Img(src=...). No external assets, no network.
=============================================================================
"""
import base64

# Colour-blind safety (spec choice "add shape/letter cues, keep colours"):
# every severity colour is ALSO paired with a unique letter AND a unique
# Plotly marker symbol, so meaning survives without colour.
STAGE_LETTER = {0: "A", 1: "B", 2: "C", 3: "D", 4: "D", -1: "–"}
STAGE_SYMBOL = {0: "circle", 1: "square", 2: "diamond",
                3: "triangle-up", 4: "x", -1: "circle-open"}

_GREY = "#8e8e93"


def _data_uri(svg):
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# --------------------------------------------------------------------------- #
#  Gender silhouette (head + shoulders bust on a soft disc)
# --------------------------------------------------------------------------- #
def gender_avatar_datauri(gender, size=64, fg="#9aa0a6", bg="#eef0f3"):
    """Generic silhouette. gender: 'M'/'male', 'F'/'female', anything else =
    neutral. Deliberately non-photographic — it conveys recorded sex only."""
    g = (gender or "").strip().lower()
    c = size / 2
    head_r = size * 0.17
    head_cy = size * 0.34

    if g in ("f", "female", "woman", "w"):
        # Female: hair framing the head + a slightly narrower, rounded bust.
        body = (
            f'<path d="M {c-size*0.30} {size*0.92} '
            f'C {c-size*0.30} {size*0.60}, {c-size*0.16} {size*0.50}, {c} {size*0.50} '
            f'C {c+size*0.16} {size*0.50}, {c+size*0.30} {size*0.60}, {c+size*0.30} {size*0.92} Z" '
            f'fill="{fg}"/>'
        )
        hair = (f'<path d="M {c-head_r*1.5} {head_cy} '
                f'a {head_r*1.5} {head_r*1.7} 0 1 1 {head_r*3} 0 '
                f'l {-head_r*0.4} {head_r*0.9} l {-head_r*0.5} {-head_r*0.5} '
                f'l {-head_r*1.2} 0 l {-head_r*0.5} {head_r*0.5} Z" fill="{fg}"/>')
        head = f'<circle cx="{c}" cy="{head_cy}" r="{head_r}" fill="{fg}"/>'
        inner = hair + head + body
    elif g in ("m", "male", "man"):
        # Male: broader shoulders, no hair frame.
        body = (
            f'<path d="M {c-size*0.34} {size*0.92} '
            f'C {c-size*0.34} {size*0.58}, {c-size*0.18} {size*0.49}, {c} {size*0.49} '
            f'C {c+size*0.18} {size*0.49}, {c+size*0.34} {size*0.58}, {c+size*0.34} {size*0.92} Z" '
            f'fill="{fg}"/>'
        )
        head = f'<circle cx="{c}" cy="{head_cy}" r="{head_r}" fill="{fg}"/>'
        inner = head + body
    else:
        # Neutral (no gender recorded) — generic person, lighter so it reads
        # as "unset" rather than an error glyph like "?".
        fg = "#b9bec6"
        body = (
            f'<path d="M {c-size*0.32} {size*0.92} '
            f'C {c-size*0.32} {size*0.58}, {c-size*0.17} {size*0.49}, {c} {size*0.49} '
            f'C {c+size*0.17} {size*0.49}, {c+size*0.32} {size*0.58}, {c+size*0.32} {size*0.92} Z" '
            f'fill="{fg}"/>'
        )
        head = f'<circle cx="{c}" cy="{head_cy}" r="{head_r}" fill="{fg}"/>'
        inner = head + body

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">'
        f'<defs><clipPath id="cp"><circle cx="{c}" cy="{c}" r="{c}"/></clipPath></defs>'
        f'<circle cx="{c}" cy="{c}" r="{c}" fill="{bg}"/>'
        f'<g clip-path="url(#cp)">{inner}</g></svg>'
    )
    return _data_uri(svg)


# --------------------------------------------------------------------------- #
#  Foot diagram (plantar view of both feet) + tappable wound-site zones
# --------------------------------------------------------------------------- #
FOOT_VIEW_W = 240
FOOT_VIEW_H = 200

# code -> (cx, cy, human label).  Codes are stored verbatim in patients.wound_site.
FOOT_ZONES = {
    "L-toes":     (62, 36,  "Left toes"),
    "L-forefoot": (60, 78,  "Left forefoot"),
    "L-midfoot":  (66, 120, "Left midfoot"),
    "L-heel":     (70, 168, "Left heel"),
    "R-toes":     (178, 36, "Right toes"),
    "R-forefoot": (180, 78, "Right forefoot"),
    "R-midfoot":  (174, 120,"Right midfoot"),
    "R-heel":     (170, 168,"Right heel"),
}


def _foot_outline(cx_off, mirror=False):
    """A simple plantar foot outline centred near x=cx_off."""
    s = -1 if mirror else 1
    # Big toe + ball + arch + heel, drawn as a smooth blob.
    return (
        f'<path d="M {cx_off} 12 '
        f'C {cx_off + s*26} 12, {cx_off + s*32} 50, {cx_off + s*30} 78 '
        f'C {cx_off + s*29} 104, {cx_off + s*22} 120, {cx_off + s*22} 140 '
        f'C {cx_off + s*22} 170, {cx_off + s*12} 190, {cx_off} 190 '
        f'C {cx_off - s*12} 190, {cx_off - s*22} 170, {cx_off - s*22} 140 '
        f'C {cx_off - s*22} 120, {cx_off - s*29} 104, {cx_off - s*30} 78 '
        f'C {cx_off - s*32} 50, {cx_off - s*26} 12, {cx_off} 12 Z" '
        f'fill="#f3f4f6" stroke="#c7c7cc" stroke-width="1.5"/>'
    )


def foot_diagram_datauri(selected=None, w=FOOT_VIEW_W, h=FOOT_VIEW_H,
                         mark_colour="#ff3b30"):
    """Both feet, left labelled L and right labelled R, with the selected
    wound-site zone marked. selected = a FOOT_ZONES code or None."""
    left  = _foot_outline(62, mirror=False)
    right = _foot_outline(178, mirror=True)
    labels = (
        f'<text x="62" y="200" text-anchor="middle" font-size="11" '
        f'fill="#8e8e93" font-family="sans-serif">L</text>'
        f'<text x="178" y="200" text-anchor="middle" font-size="11" '
        f'fill="#8e8e93" font-family="sans-serif">R</text>'
    )
    mark = ""
    if selected in FOOT_ZONES:
        cx, cy, _lbl = FOOT_ZONES[selected]
        mark = (
            f'<circle cx="{cx}" cy="{cy}" r="11" fill="{mark_colour}" '
            f'fill-opacity="0.25" stroke="{mark_colour}" stroke-width="2"/>'
            f'<circle cx="{cx}" cy="{cy}" r="3.5" fill="{mark_colour}"/>'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {FOOT_VIEW_W} {FOOT_VIEW_H}">'
        f'{left}{right}{labels}{mark}</svg>'
    )
    return _data_uri(svg)


def foot_zone_label(code):
    z = FOOT_ZONES.get(code)
    return z[2] if z else "Not recorded"


# --------------------------------------------------------------------------- #
#  Multi-point wound-marker picker (spec A2): a foot outline you can drop
#  multiple coloured points on, with a side / bottom (plantar) view.
#  Tissue colours match the rest of the app: red / yellow / black.
# --------------------------------------------------------------------------- #
PICK_W, PICK_H = 220, 240
MARKER_COLOURS = {"red": "#e0301e", "yellow": "#f2c200", "black": "#111111"}


def foot_outline_datauri(view="bottom", w=PICK_W, h=PICK_H):
    """Just the foot outline for the chosen view ('bottom' = plantar / sole,
    'side' = lateral profile). Points are overlaid as HTML by the app."""
    if view == "side":
        foot = ('<path d="M30,170 Q26,140 70,134 L168,130 Q196,130 196,150 '
                'Q196,168 165,170 L70,176 Q40,180 30,170 Z" '
                'fill="#f3f4f6" stroke="#c7c7cc" stroke-width="2"/>')
        ankle = ('<path d="M72,134 Q66,92 96,86 Q126,84 128,132 Z" '
                 'fill="#f3f4f6" stroke="#c7c7cc" stroke-width="2"/>')
        label = "Side view"
        inner = ankle + foot
    else:
        sole = ('<ellipse cx="110" cy="138" rx="46" ry="82" '
                'fill="#f3f4f6" stroke="#c7c7cc" stroke-width="2"/>')
        toes = "".join(
            f'<ellipse cx="{cx}" cy="{cy}" rx="8" ry="10" '
            f'fill="#f3f4f6" stroke="#c7c7cc" stroke-width="1.5"/>'
            for cx, cy in [(84, 54), (98, 46), (112, 46), (126, 50), (136, 60)])
        label = "Bottom (sole) view"
        inner = sole + toes
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {PICK_W} {PICK_H}">{inner}'
        f'<text x="{PICK_W/2}" y="{PICK_H-6}" text-anchor="middle" font-size="11" '
        f'fill="#8e8e93" font-family="sans-serif">{label}</text></svg>'
    )
    return _data_uri(svg)
