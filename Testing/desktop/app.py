"""
=============================================================================
 DESKTOP APP  (Testing/desktop/app.py)  —  MEDICAL STAFF only
-----------------------------------------------------------------------------
 Apple Health–inspired light dashboard for diabetic-foot-ulcer monitoring.

 Design goals (spec G):
   * At-a-glance triage   — all patients as cards, most urgent first, the UT
                            severity stage is the headline on every card.
   * Health-app feel      — light theme, rounded cards, soft shadows, sparklines.
   * Drill-down detail    — full-width patient-info squircle, scalable trend,
                            captured/overlay viewer, baseline-vs-latest compare,
                            editable records, foot-site map, PDF export.
   * Cloud verify tab     — live Firestore connection test.

 Accessibility (colour-blind safety): every severity colour is ALSO paired
 with a unique LETTER (A–D) and a unique marker SHAPE, so meaning survives
 without colour. Red is used for severity AND reserved for the URGENT flag.

 Backends (data_source.py):  DFU_BACKEND=local (default) | firebase
 Run:  python run_desktop.py  (native window)  |  python app.py (browser)
=============================================================================
"""
import base64
import datetime
import json
import math
import os

from dash import (Dash, dcc, html, dash_table,
                  Input, Output, State, ctx, no_update, ALL)
from dash.dash_table.Format import Format, Scheme
import plotly.graph_objects as go

import data_source as ds
import svg_assets as svg
import report
import audit
import debug_utils as dbg

# --------------------------------------------------------------------------- #
#  FLAGS  — flip features on/off quickly for testing (spec I)
# --------------------------------------------------------------------------- #
STAFF_PIN           = "1234"   # Change before clinic deployment (Phase 2: Firebase Auth)
SHOW_HEALING_BANNER = True     # status strip + suggested action (logistics only)
SHOW_COMPARE        = True     # baseline-vs-latest image compare toggle
SHOW_FOOT_DIAGRAM   = True     # tappable foot map for wound site
ENABLE_PDF_REPORT   = True     # "Export PDF" button (needs reportlab)
DEBUG_UI            = False    # True = print callback traces to the console

HERE     = os.path.dirname(os.path.abspath(__file__))
BACKEND  = os.environ.get("DFU_BACKEND", "local")          # "local" | "firebase"
DB_PATH  = os.environ.get("DFU_DB", os.path.join(HERE, "demo_dfu.db"))

# Two data streams staff can toggle between at runtime (spec E "Toggle Data
# Stream"): SEEDED demo data (local demo DB) vs the live DATABASE (Firestore).
class _SourceRouter:
    """Transparent proxy: SRC.captures(...) etc. route to the active backend."""
    def __init__(self, seeded, database, mode):
        self._srcs = {"seeded": seeded, "database": database}
        self.mode = mode if mode in self._srcs else "seeded"

    def set_mode(self, m):
        if m in self._srcs:
            self.mode = m

    @property
    def active(self):
        return self._srcs[self.mode]

    def __getattr__(self, name):              # delegate everything else to active
        return getattr(self._srcs[self.mode], name)


_DEFAULT_MODE = "database" if BACKEND == "firebase" else "seeded"
SRC = _SourceRouter(ds.get_source("local", DB_PATH), ds.FirebaseSource(), _DEFAULT_MODE)
FB  = SRC._srcs["database"]                   # Cloud-verify tab reuses the same client


if DEBUG_UI:
    dbg.set_enabled(True)


def _dbg(*a):
    if DEBUG_UI:
        dbg.dlog(*a)


# --------------------------------------------------------------------------- #
#  Apple-Health-ish palette  (meaning kept in sync with severity levels)
# --------------------------------------------------------------------------- #
BG       = "#f2f2f7"
CARD     = "#ffffff"
INK      = "#1c1c1e"
SUBTLE   = "#8e8e93"
HAIR     = "#e5e5ea"
BLUE     = "#0a84ff"
RED      = "#ff3b30"
GREEN    = "#34c759"
AMBER    = "#ff9500"

LVL_COLOUR = {0: "#34c759", 1: "#ffcc00", 2: "#ff9500",
              3: "#ff3b30", 4: "#c41e1e", -1: "#c7c7cc"}
STAGE_LETTER = svg.STAGE_LETTER                          # colour-blind cue (letter)
STAGE_SYMBOL = svg.STAGE_SYMBOL                          # colour-blind cue (shape)
STAGE_SHORT  = {0: "UT Stage A", 1: "UT Stage B", 2: "UT Stage C",
                3: "UT Stage D", 4: "UT Stage D", -1: "Unstaged"}
STAGE_DESC   = {0: "Clean", 1: "Infected", 2: "Ischaemic",
                3: "Ischaemic + Infected",
                4: "Severe / advanced — extensive ischaemia & infection",
                -1: "No wound staged yet"}

# UT labels for the editable Label dropdown (first line only — matches stored data)
UT_DROPDOWN = ["UT Stage A – Clean wound",
               "UT Stage B – Infected wound",
               "UT Stage C – Ischaemic wound",
               "UT Stage D – Ischaemic & infected",
               "UT Stage D – Severe / advanced"]

# Tissue colours (spec E1): granulation = red, slough = yellow, necrosis = black.
# SAME scheme is used by the AI overlay in new_deployment so the image legend and
# this Wound Bed Composition widget match.
TISSUE = [("Granulation", "base_wound_px", "#e0301e"),   # red
          ("Slough",      "slough_px",     "#f2c200"),   # yellow
          ("Necrosis",    "necrosis_px",   "#111111")]   # black

FONT = ('-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, '
        "Helvetica, Arial, system-ui, sans-serif")


# --------------------------------------------------------------------------- #
#  Small visual helpers
# --------------------------------------------------------------------------- #
def _ring_datauri(colour, frac, centre, size=92, stroke=11):
    """Apple-activity-ring style donut with text (the stage letter) in the middle."""
    frac = max(0.0, min(1.0, frac))
    r = (size - stroke) / 2
    c = size / 2
    circ = 2 * math.pi * r
    dash = circ * frac
    svg_str = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">'
        f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="{HAIR}" '
        f'stroke-width="{stroke}"/>'
        f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="{colour}" '
        f'stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-dasharray="{dash:.1f} {circ:.1f}" transform="rotate(-90 {c} {c})"/>'
        f'<text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" '
        f'font-family="{FONT}" font-size="{size*0.36:.0f}" font-weight="700" '
        f'fill="{INK}">{centre}</text></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg_str.encode()).decode()


def _sparkline_datauri(values, colour, w=132, h=40):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None                                  # caller shows "no trend data"
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    pad = 3
    pts = []
    for i, v in enumerate(vals):
        x = pad + i * (w - 2 * pad) / (n - 1)
        y = h - pad - (v - lo) / rng * (h - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    poly = " ".join(pts)
    last_x, last_y = pts[-1].split(",")
    svg_str = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
        f'<polyline points="{poly}" fill="none" stroke="{colour}" '
        f'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="2.6" fill="{colour}"/></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg_str.encode()).decode()


def _pct2(v):
    """Wound %/Foot % — always 2 decimal places (spec #8)."""
    return "—" if v is None else f"{v:.2f}%"


def _roc_text(roc):
    if roc is None:
        return "—"
    arrow = "▲" if roc > 0 else ("▼" if roc < 0 else "▬")
    word  = "worsening" if roc > 0 else ("improving" if roc < 0 else "stable")
    return f"{arrow} {roc:+.2f}%/day · {word}"


def _to_int(v):
    try:    return int(v)
    except (TypeError, ValueError):  return None


def _to_float(v):
    try:    return float(v)
    except (TypeError, ValueError):  return None


def _sim_label(v):
    if v is None:   return ""
    return "OK" if v else "DIFFER"


def _name_age(name_or_meta, age=None):
    """'Name, Age' if a birthdate/age is known, else just the name (spec #3)."""
    if isinstance(name_or_meta, dict):
        name = name_or_meta.get("name") or name_or_meta.get("patient_id") or ""
        age = name_or_meta.get("age")
        if age is None:
            age = ds.age_from_dob(name_or_meta.get("dob"))
    else:
        name = name_or_meta or ""
    return f"{name}, {age}" if (name and age is not None) else (name or "")


# --------------------------------------------------------------------------- #
#  Healing status + SUGGESTED ACTION
#  IMPORTANT: action text is LOGISTICS ONLY (visit clinic / contact doctor /
#  routine monitoring / capture more). Never any clinical/treatment advice.
# --------------------------------------------------------------------------- #
def _healing_status(roc, urgent, has_trend):
    if urgent:
        return {"label": "Needs attention",
                "action": "Recommend prompt clinic review — please contact the care team.",
                "colour": RED}
    if not has_trend or roc is None:
        return {"label": "Not enough data",
                "action": "Capture more readings to establish a trend.",
                "colour": SUBTLE}
    if roc > 0.2:
        return {"label": "Worsening",
                "action": "Recommend a clinic visit — please contact the doctor.",
                "colour": RED}
    if roc > 0.0:
        return {"label": "Slightly worsening",
                "action": "Consider a clinic visit / contact the doctor.",
                "colour": AMBER}
    if roc < -0.1:
        return {"label": "Improving",
                "action": "Continue routine monitoring.",
                "colour": GREEN}
    return {"label": "Stable",
            "action": "Continue routine monitoring.",
            "colour": BLUE}


# --------------------------------------------------------------------------- #
#  App + global CSS
# --------------------------------------------------------------------------- #
app = Dash(__name__, title="DFU Monitor — Staff",
           suppress_callback_exceptions=True)
server = app.server

app.index_string = """<!DOCTYPE html>
<html>
<head>{%metas%}<title>{%title%}</title>{%favicon%}{%css%}
<style>
  html,body {margin:0;background:#f2f2f7;}
  * {box-sizing:border-box;}
  ::-webkit-scrollbar {width:10px;height:10px;}
  ::-webkit-scrollbar-thumb {background:#c7c7cc;border-radius:6px;}
  .pcard {transition:transform .12s ease, box-shadow .12s ease; cursor:pointer;}
  .pcard:hover {transform:translateY(-3px); box-shadow:0 8px 24px rgba(0,0,0,.12);}
  .pill-btn {transition:filter .12s ease;}
  .pill-btn:hover {filter:brightness(1.06);}
  .footzone:hover {background:rgba(10,132,255,.18) !important;}
  [id*="footcell"]:hover {background:rgba(10,132,255,.16) !important; border-radius:50%;}
  .icon-btn {background:transparent;border:none;cursor:pointer;color:#0a84ff;
             font-size:13px;padding:2px 6px;border-radius:7px;}
  .icon-btn:hover {background:#eef4ff;}
  input, textarea {font-family:inherit;}
  .dash-spreadsheet-container .dash-spreadsheet-inner table {font-family:inherit;}
  .tab-bar .tab {font-weight:600 !important;}
</style></head>
<body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body>
</html>"""

CARD_STYLE = {"background": CARD, "borderRadius": "18px", "padding": "18px",
              "boxShadow": "0 1px 3px rgba(0,0,0,.08)"}
LABEL_STYLE = {"color": SUBTLE, "fontSize": "12px", "fontWeight": "600",
               "letterSpacing": ".02em", "display": "block", "marginBottom": "5px"}
INPUT_STYLE = {"width": "100%", "padding": "9px 11px", "fontSize": "14px",
               "border": f"1px solid {HAIR}", "borderRadius": "10px",
               "background": "#fbfbfd", "color": INK, "outline": "none"}
PRIMARY_BTN = {"background": BLUE, "color": "#fff", "border": "none",
               "borderRadius": "10px", "padding": "10px 16px", "fontSize": "14px",
               "fontWeight": "600", "cursor": "pointer"}
GHOST_BTN = {"background": "#fff", "color": BLUE, "border": f"1px solid {HAIR}",
             "borderRadius": "10px", "padding": "8px 14px", "fontSize": "14px",
             "fontWeight": "600", "cursor": "pointer"}

_TBL_HDR  = {"backgroundColor": "#f7f7fa", "color": SUBTLE, "fontWeight": "600",
             "border": "none", "borderBottom": f"1px solid {HAIR}",
             "fontSize": "12px", "textTransform": "uppercase"}
_TBL_CELL = {"backgroundColor": CARD, "color": INK, "border": "none",
             "borderBottom": f"1px solid {HAIR}", "padding": "9px 10px",
             "fontSize": "13px", "fontFamily": FONT}


def _stage_badge(lvl_k, colour, size=20):
    """Small colour + LETTER chip (colour-blind safe identity for a stage)."""
    return html.Span(STAGE_LETTER.get(lvl_k, "–"),
                     style={"display": "inline-flex", "alignItems": "center",
                            "justifyContent": "center", "width": f"{size}px",
                            "height": f"{size}px", "borderRadius": "7px",
                            "background": colour, "color": "#fff",
                            "fontWeight": "800", "fontSize": f"{size*0.6:.0f}px",
                            "flex": "0 0 auto"})


# --------------------------------------------------------------------------- #
#  Patient overview card (main page)
# --------------------------------------------------------------------------- #
def _patient_card(p):
    pid    = p["patient_id"]
    lvl    = p.get("level")
    lvl_k  = lvl if lvl is not None else -1
    colour = LVL_COLOUR.get(lvl_k, "#c7c7cc")
    urgent = p.get("urgent")
    has_trend = p.get("has_trend")
    series = p.get("wound_series") or []
    spark  = _sparkline_datauri(series, colour) if has_trend else None

    # spec #2: gender silhouette as the profile picture (never a "?")
    avatar = html.Div(style={"position": "relative", "flex": "0 0 auto"}, children=[
        html.Img(src=svg.gender_avatar_datauri(p.get("gender"), size=60),
                 style={"width": "60px", "height": "60px", "borderRadius": "50%"}),
        # stage letter badge pinned to the avatar (colour + letter cue)
        html.Div(_stage_badge(lvl_k, colour, size=22),
                 style={"position": "absolute", "right": "-3px", "bottom": "-3px"}),
    ])

    # spec #1/#4: grey "no trend data" instead of "—" / "?"
    if has_trend:
        trend_block = html.Img(src=spark, style={"height": "40px"})
        roc = p.get("roc_per_day")
        roc_block = html.Div(_roc_text(roc),
                             style={"color": RED if (roc or 0) > 0 else SUBTLE,
                                    "fontSize": "12px", "marginTop": "8px",
                                    "fontWeight": "600"})
    else:
        trend_block = html.Div("no trend data",
                               style={"color": SUBTLE, "fontSize": "12px",
                                      "fontStyle": "italic", "alignSelf": "center"})
        roc_block = html.Div("no trend data",
                             style={"color": SUBTLE, "fontSize": "12px",
                                    "marginTop": "8px", "fontStyle": "italic"})

    return html.Div(
        id={"type": "pcard", "pid": pid}, n_clicks=0, className="pcard",
        style={**CARD_STYLE, "padding": "16px",
               "border": f"2px solid {RED}" if urgent else "2px solid transparent"},
        children=[
            html.Div(style={"display": "flex", "gap": "14px", "alignItems": "center"},
                     children=[
                avatar,
                html.Div(style={"minWidth": "0", "flex": "1"}, children=[
                    html.Div(_name_age(p), style={"fontWeight": "700",
                              "fontSize": "16px", "color": INK, "whiteSpace": "nowrap",
                              "overflow": "hidden", "textOverflow": "ellipsis"}),
                    html.Div(pid, style={"color": SUBTLE, "fontSize": "12px",
                                         "marginBottom": "6px"}),
                    html.Span(STAGE_SHORT.get(lvl_k, "Unstaged"),
                              style={"background": colour, "color": "#fff",
                                     "fontWeight": "700", "fontSize": "12px",
                                     "padding": "3px 10px", "borderRadius": "999px"}),
                    (html.Span("▲ URGENT", style={
                        "background": RED, "color": "#fff", "fontWeight": "700",
                        "fontSize": "11px", "padding": "3px 9px",
                        "borderRadius": "999px", "marginLeft": "6px"})
                     if urgent else ""),
                ]),
            ]),
            html.Div(style={"display": "flex", "alignItems": "flex-end",
                            "justifyContent": "space-between", "marginTop": "12px"},
                     children=[
                html.Div([
                    html.Div("Wound area", style={"color": SUBTLE, "fontSize": "11px"}),
                    html.Div(_pct2(p.get("wound_pct")),
                             style={"fontSize": "22px", "fontWeight": "700", "color": INK}),
                ]),
                trend_block,
            ]),
            roc_block,
        ])


# --------------------------------------------------------------------------- #
#  Detail-view building blocks
# --------------------------------------------------------------------------- #
def _metric(title, value, accent=BLUE, sub=None):
    return html.Div(style={**CARD_STYLE, "flex": "1", "minWidth": "150px",
                           "borderTop": f"4px solid {accent}"}, children=[
        html.Div(title, style={"color": SUBTLE, "fontSize": "12px",
                               "fontWeight": "600"}),
        html.Div(value, style={"fontSize": "22px", "fontWeight": "700",
                               "color": INK, "marginTop": "4px"}),
        html.Div(sub or "", style={"color": SUBTLE, "fontSize": "12px",
                                   "marginTop": "2px"}),
    ])


# Stage letter → severity level (for colour when only the letter is stored).
LETTER_LEVEL = {"A": 0, "B": 1, "C": 2, "D": 3}


def _stage_colour(session):
    """Colour for a session's averaged stage (by level, falling back to letter)."""
    lvl = session.get("avg_level")
    if lvl is None:
        lvl = LETTER_LEVEL.get(session.get("avg_stage"), -1)
    return LVL_COLOUR.get(lvl if lvl is not None else -1, "#c7c7cc"), \
        (lvl if lvl is not None else -1)


def _sess_dt_label(s):
    dt = s.get("dt")
    return dt.strftime("%d %b %Y · %H:%M") if dt else (s.get("stamp") or "—")


def _focus_session(sess_list, sid):
    """The session the UT-stage + wound-bed widgets describe: the picked one,
    else the latest."""
    if not sess_list:
        return None
    if sid:
        for s in sess_list:
            if s.get("session_id") == sid:
                return s
    return sess_list[-1]


def _capture_caption(s):
    """'Average of 3 images · 12 Jun 2026 · 14:25' — tells staff exactly which
    averaged measurement a widget is showing (spec E1)."""
    n = s.get("n_images") or 1
    word = "image" if n == 1 else "images"
    return f"Average of {n} {word} · {_sess_dt_label(s)}"


# ---- UT STAGE widget (no picture square — spec E1) ------------------------- #
def _stage_widget(s):
    if not s:
        return html.Div(style={**CARD_STYLE, "flex": "1", "minWidth": "190px"},
                        children=[html.Div("UT stage", style={"color": SUBTLE,
                                  "fontSize": "12px", "fontWeight": "600"}),
                                  html.Div("No captures", style={"color": SUBTLE})])
    colour, lvl_k = _stage_colour(s)
    letter = s.get("avg_stage") or STAGE_LETTER.get(lvl_k, "–")
    short = f"UT Stage {letter}" if letter in ("A", "B", "C", "D") else "Unstaged"
    return html.Div(style={**CARD_STYLE, "flex": "1", "minWidth": "190px",
                           "borderTop": f"4px solid {colour}"}, children=[
        html.Div("UT stage (averaged)", style={"color": SUBTLE, "fontSize": "12px",
                 "fontWeight": "600"}),
        html.Div(short, style={"fontSize": "24px", "fontWeight": "800",
                 "color": colour, "marginTop": "2px"}),
        html.Div(STAGE_DESC.get(lvl_k, ""), style={"color": INK, "fontSize": "12px"}),
        html.Div(_capture_caption(s), style={"color": SUBTLE, "fontSize": "11px",
                 "marginTop": "8px", "borderTop": f"1px solid {HAIR}", "paddingTop": "6px"}),
    ])


# ---- WOUND BED COMPOSITION widget (red/yellow/black + capture label) ------- #
def _woundbed_card(s):
    if not s:
        return html.Div(style={**CARD_STYLE, "flex": "1", "minWidth": "200px"},
                        children=[html.Div("Wound bed composition",
                                  style={"fontWeight": "700", "color": INK})])
    t = s.get("tissue", {}) or {}
    vals = [(name, t.get(key) or 0, col) for name, key, col in TISSUE]
    total = sum(v for _, v, _ in vals)
    head = html.Div("Wound bed composition", style={"fontWeight": "700", "color": INK,
                    "marginBottom": "8px"})
    caption = html.Div(_capture_caption(s), style={"color": SUBTLE, "fontSize": "11px",
              "marginTop": "8px", "borderTop": f"1px solid {HAIR}", "paddingTop": "6px"})
    if total <= 0:
        return html.Div(style={**CARD_STYLE, "flex": "1", "minWidth": "200px"}, children=[
            head, html.Div("No tissue breakdown for this capture.",
                  style={"color": SUBTLE, "fontSize": "13px"}), caption])
    segs, legend = [], []
    for name, v, col in vals:
        pct = v / total * 100
        segs.append(html.Div(style={"width": f"{pct}%", "background": col, "height": "100%"}))
        legend.append(html.Div(style={"display": "flex", "alignItems": "center",
                                      "gap": "6px"}, children=[
            html.Span(style={"width": "11px", "height": "11px", "borderRadius": "3px",
                             "background": col, "display": "inline-block", "flex": "0 0 auto"}),
            html.Span(f"{name} {pct:.0f}%",
                      style={"fontSize": "12px", "color": INK, "whiteSpace": "nowrap"})]))
    return html.Div(style={**CARD_STYLE, "flex": "1", "minWidth": "200px"}, children=[
        head,
        html.Div(style={"display": "flex", "height": "18px", "borderRadius": "9px",
                        "overflow": "hidden", "background": HAIR}, children=segs),
        html.Div(style={"display": "flex", "gap": "14px", "marginTop": "10px",
                        "flexWrap": "wrap"}, children=legend),
        caption,
    ])


# ---- TREND widget (earliest vs latest average reading, or too-little-data) -- #
def _reading_line(label, s):
    return html.Div(style={"display": "flex", "justifyContent": "space-between",
                           "gap": "10px"}, children=[
        html.Span(label, style={"color": SUBTLE, "fontSize": "12px"}),
        html.Span(_sess_dt_label(s) if s else "—",
                  style={"color": INK, "fontSize": "12px", "fontWeight": "600"})])


def _trend_widget(tr):
    head = html.Div("Trend · wound area", style={"fontWeight": "700", "color": INK,
                    "marginBottom": "6px"})
    if not tr.get("ok"):
        return html.Div(style={**CARD_STYLE, "flex": "1", "minWidth": "210px",
                               "borderTop": f"4px solid {SUBTLE}"}, children=[
            head,
            html.Div("Too little data to produce a trend.",
                     style={"color": INK, "fontWeight": "700", "fontSize": "14px"}),
            html.Div("Need at least 2 average readings 7+ days apart.",
                     style={"color": SUBTLE, "fontSize": "12px", "marginTop": "4px"}),
        ])
    total = tr["total_change"]
    colour = RED if total > 0 else (GREEN if total < 0 else SUBTLE)
    arrow = "▲" if total > 0 else ("▼" if total < 0 else "→")
    return html.Div(style={**CARD_STYLE, "flex": "1", "minWidth": "210px",
                           "borderTop": f"4px solid {colour}"}, children=[
        head,
        html.Div(f"{arrow} {abs(total):.2f}%  over {tr['span_days']:.0f} days",
                 style={"fontSize": "20px", "fontWeight": "800", "color": colour}),
        html.Div(f"{tr['roc_per_day']:+.3f} %/day", style={"color": SUBTLE,
                 "fontSize": "12px", "marginBottom": "6px"}),
        html.Div("Comparing earliest & latest average readings on the graph:",
                 style={"color": SUBTLE, "fontSize": "11px", "marginBottom": "4px"}),
        _reading_line("Earliest reading", tr.get("earliest")),
        _reading_line("Latest reading", tr.get("latest")),
    ])


def _trend_fig(sess_list, days):
    """Wound-area trend over SESSION AVERAGES. Each session is one error bar
    (min..max of its readings); the AVERAGE point stands out (stage-coloured,
    larger, white-ringed) while the individual readings are small + muted."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    ax, ay, e_lo, e_hi, cols, syms, txt = [], [], [], [], [], [], []
    ix, iy = [], []
    for s in sess_list:
        dt = s.get("dt")
        if not dt or dt < cutoff or s.get("avg_wound_pct") is None:
            continue
        a = s["avg_wound_pct"]
        lo, hi = s.get("wound_min"), s.get("wound_max")
        ax.append(dt); ay.append(a)
        e_lo.append(a - lo if lo is not None else 0)
        e_hi.append(hi - a if hi is not None else 0)
        _c, lvl_k = _stage_colour(s)
        cols.append(_c); syms.append(STAGE_SYMBOL.get(lvl_k, "circle"))
        letter = s.get("avg_stage") or STAGE_LETTER.get(lvl_k, "–")
        txt.append(f"UT {letter} · {s.get('n_images', 1)} imgs")
        for v in (s.get("wound_vals") or []):
            ix.append(dt); iy.append(v)
    fig = go.Figure()
    if ix:                                   # individual readings (muted)
        fig.add_trace(go.Scatter(
            x=ix, y=iy, mode="markers", name="readings",
            marker={"color": "rgba(142,142,147,.45)", "size": 7, "symbol": "circle"},
            hovertemplate="%{x|%d %b %H:%M}<br>reading %{y:.2f}%<extra></extra>"))
    fig.add_trace(go.Scatter(                 # averages (stand out) + error bars
        x=ax, y=ay, mode="lines+markers", name="average",
        line={"color": BLUE, "width": 3, "shape": "spline"},
        marker={"color": cols, "symbol": syms, "size": 14,
                "line": {"color": "#fff", "width": 2}},
        error_y={"type": "data", "symmetric": False, "array": e_hi, "arrayminus": e_lo,
                 "color": "rgba(10,132,255,.45)", "thickness": 1.5, "width": 6},
        text=txt,
        hovertemplate="%{x|%d %b %Y %H:%M}<br>Average %{y:.2f}%<br>%{text}<extra></extra>",
        fill="tozeroy", fillcolor="rgba(10,132,255,.06)"))
    fig.update_layout(
        template="plotly_white", paper_bgcolor=CARD, plot_bgcolor=CARD,
        margin={"l": 46, "r": 18, "t": 16, "b": 36}, height=290, showlegend=False,
        font={"family": FONT, "color": INK},
        yaxis={"title": "Wound area (%)", "gridcolor": HAIR, "zeroline": False,
               "hoverformat": ".2f", "tickformat": ".2f"},
        xaxis={"gridcolor": HAIR, "hoverformat": "%d %b %Y %H:%M",
               "tickformatstops": [
                   {"dtickrange": [None, 3600000], "value": "%H:%M"},
                   {"dtickrange": [3600000, 86400000], "value": "%H:%M\n%d %b"},
                   {"dtickrange": [86400000, None], "value": "%d %b %Y"}]})
    return fig


# ---- Collapsible session-grouped measurements list (spec E1) --------------- #
def _records_list(sess_list):
    """Each session is a collapsible block: the average reading is the always-
    visible header; expanding reveals editable session Date/Time (applies to all
    N images) + the individual image readings."""
    if not sess_list:
        return html.Div("No measurements yet.",
                        style={"color": SUBTLE, "fontSize": "14px", "padding": "8px"})
    blocks = []
    for s in reversed(sess_list):                       # newest first
        sid = s.get("session_id")
        colour, lvl_k = _stage_colour(s)
        letter = s.get("avg_stage") or STAGE_LETTER.get(lvl_k, "–")
        dt = s.get("dt")
        date_s = dt.strftime("%Y-%m-%d") if dt else ""
        time_s = dt.strftime("%H:%M") if dt else ""
        wp = s.get("avg_wound_pct")
        pos = _sim_label((s.get("rep") or {}).get("sim_consistent"))

        angle = (s.get("foot_angle") or "").lower()
        angle_txt = {"side": "Side", "bottom": "Bottom"}.get(angle, "—")
        summary = html.Summary(style={"listStyle": "none", "cursor": "pointer",
                                      "padding": "10px 12px", "display": "flex",
                                      "alignItems": "center", "gap": "12px",
                                      "borderLeft": f"5px solid {colour}"}, children=[
            html.Span(f"{date_s}  {time_s}", style={"fontWeight": "700", "color": INK,
                      "fontSize": "13px", "minWidth": "130px"}),
            html.Span(f"UT {letter}", style={"fontWeight": "800", "color": colour,
                      "fontSize": "13px"}),
            html.Span(f"Wound {_pct2(wp)}", style={"color": INK, "fontSize": "13px"}),
            html.Span(f"{s.get('n_images', 1)} imgs", style={"color": SUBTLE,
                      "fontSize": "12px"}),
            html.Span(f"{angle_txt} view", style={"color": SUBTLE, "fontSize": "12px"}),
            html.Span(pos, style={"color": ("#b8860b" if pos == "DIFFER" else SUBTLE),
                      "fontSize": "12px", "fontWeight": "600", "marginLeft": "auto"}),
        ])

        # member readings — Lvl + Wound% are editable (spec A4); Foot% read-only
        col = lambda t: html.Span(t, style={"minWidth": "64px", "color": SUBTLE,
                                            "fontSize": "11px"})
        member_rows = [html.Div(style={"display": "flex", "gap": "12px",
                       "alignItems": "center", "padding": "3px 0", "fontSize": "12px",
                       "color": INK}, children=[
            html.Span(f"Image {m.get('image_index') or i+1}", style={"minWidth": "64px",
                      "color": SUBTLE}),
            html.Span("Lvl", style={"color": SUBTLE, "fontSize": "11px"}),
            dcc.Input(id={"type": "img-lvl", "rid": str(m.get("id"))},
                      value=m.get("highest_level"), type="number", min=-1, max=4, step=1,
                      style={**INPUT_STYLE, "width": "58px", "padding": "4px 6px"}),
            html.Span("Wound %", style={"color": SUBTLE, "fontSize": "11px"}),
            dcc.Input(id={"type": "img-wound", "rid": str(m.get("id"))},
                      value=m.get("wound_pct"), type="number", min=0, step=0.01,
                      style={**INPUT_STYLE, "width": "78px", "padding": "4px 6px"}),
            html.Span(f"Foot {_pct2(m.get('foot_pct'))}", style={"color": SUBTLE}),
        ]) for i, m in enumerate(s.get("members", []))]

        body = html.Div(style={"padding": "8px 14px 14px 17px", "background": "#fbfbfd"},
                        children=[
            html.Div("Capture date/time + foot angle (applies to all images in this "
                     "session):", style={"color": SUBTLE, "fontSize": "12px",
                     "marginBottom": "6px"}),
            html.Div(style={"display": "flex", "gap": "8px", "alignItems": "center",
                            "marginBottom": "10px", "flexWrap": "wrap"}, children=[
                dcc.Input(id={"type": "sess-date", "sid": sid}, value=date_s,
                          type="text", placeholder="YYYY-MM-DD",
                          style={**INPUT_STYLE, "width": "130px", "padding": "6px 8px"}),
                dcc.Input(id={"type": "sess-time", "sid": sid}, value=time_s,
                          type="text", placeholder="HH:MM",
                          style={**INPUT_STYLE, "width": "90px", "padding": "6px 8px"}),
                dcc.Dropdown(id={"type": "sess-angle", "sid": sid},
                             options=[{"label": "Side", "value": "side"},
                                      {"label": "Bottom", "value": "bottom"}],
                             value=(angle or None), placeholder="Foot angle",
                             clearable=False,
                             style={"width": "130px", "fontSize": "13px"}),
                html.Button("📷 Show images", id={"type": "sess-pick", "sid": sid},
                            n_clicks=0, className="pill-btn", style=GHOST_BTN),
            ]),
            html.Div("Individual readings (Lvl & Wound % editable):",
                     style={"color": SUBTLE, "fontSize": "12px", "marginBottom": "2px"}),
            *member_rows,
        ])
        blocks.append(html.Details([summary, body], open=(s is sess_list[-1]),
                      style={"background": CARD, "border": f"1px solid {HAIR}",
                             "borderRadius": "10px", "marginBottom": "8px",
                             "overflow": "hidden"}))
    return html.Div(blocks)


# --------------------------------------------------------------------------- #
#  Multi-point wound-marker picker (spec A2): click the foot to drop coloured
#  points; switch side/bottom view; points saved as JSON in patients.wound_points.
# --------------------------------------------------------------------------- #
def _count_points(meta):
    try:
        return len(json.loads(meta.get("wound_points") or "[]"))
    except Exception:
        return 0


def _foot_picker():
    step = 22
    cells = [html.Button(
        id={"type": "footcell", "x": cx, "y": cy}, n_clicks=0,
        style={"position": "absolute", "left": f"{cx-step//2}px", "top": f"{cy-step//2}px",
               "width": f"{step}px", "height": f"{step}px", "border": "none",
               "background": "transparent", "cursor": "crosshair", "padding": "0"})
        for cy in range(14, svg.PICK_H - 18, step)
        for cx in range(12, svg.PICK_W - 8, step)]
    return html.Div([
        html.Div("Mark wound positions — pick a colour, click the foot", style=LABEL_STYLE),
        html.Div(style={"display": "flex", "gap": "12px", "alignItems": "center",
                        "justifyContent": "center", "marginBottom": "6px",
                        "flexWrap": "wrap"}, children=[
            dcc.Dropdown(id="foot-view", clearable=False,
                         options=[{"label": "Bottom (sole)", "value": "bottom"},
                                  {"label": "Side", "value": "side"}],
                         value="bottom", style={"width": "150px", "fontSize": "13px"}),
            dcc.RadioItems(id="marker-colour", value="red", inline=True,
                           options=[{"label": " Red", "value": "red"},
                                    {"label": " Yellow", "value": "yellow"},
                                    {"label": " Black", "value": "black"}],
                           style={"fontSize": "13px"}, labelStyle={"marginRight": "8px"}),
        ]),
        html.Div(style={"position": "relative", "width": f"{svg.PICK_W}px",
                        "height": f"{svg.PICK_H}px", "margin": "0 auto"}, children=[
            html.Img(id="foot-outline-img", src=svg.foot_outline_datauri("bottom"),
                     style={"position": "absolute", "top": 0, "left": 0}),
            *cells,
            html.Div(id="foot-markers", style={"position": "absolute", "top": 0, "left": 0,
                     "width": "100%", "height": "100%", "pointerEvents": "none"}),
        ]),
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "10px",
                        "justifyContent": "center", "marginTop": "4px"}, children=[
            html.Span(id="foot-count", style={"fontSize": "12px", "color": SUBTLE}),
            html.Button("Undo", id="foot-undo", n_clicks=0, className="icon-btn"),
            html.Button("Clear view", id="foot-clear", n_clicks=0, className="icon-btn"),
        ]),
    ])


# ============================================================================ #
#  Layout
# ============================================================================ #
def _login_view():
    return html.Div(id="login-view",
        style={"display": "flex", "alignItems": "center",
               "justifyContent": "center", "minHeight": "100vh"},
        children=[html.Div(style={**CARD_STYLE, "width": "330px", "padding": "40px",
                                  "textAlign": "center", "borderRadius": "22px"},
            children=[
                html.Div("🩺", style={"fontSize": "46px"}),
                html.H2("DFU Monitor", style={"margin": "6px 0 2px", "color": INK}),
                html.Div("Staff access only", style={"color": SUBTLE,
                         "fontSize": "13px", "marginBottom": "22px"}),
                dcc.Input(id="pin-input", type="password", placeholder="Enter PIN",
                          debounce=True,
                          style={**INPUT_STYLE, "textAlign": "center",
                                 "fontSize": "20px", "letterSpacing": "8px",
                                 "marginBottom": "12px"}),
                html.Button("Sign In", id="login-btn", n_clicks=0, className="pill-btn",
                            style={**PRIMARY_BTN, "width": "100%", "padding": "11px"}),
                html.Div(id="login-error", style={"color": RED, "fontSize": "13px",
                                                  "marginTop": "10px", "minHeight": "16px"}),
                html.Div("Screening aid only — not a diagnosis.",
                         style={"color": "#c7c7cc", "fontSize": "11px",
                                "marginTop": "18px"}),
            ])])


def _header():
    badge = "Live database (Firestore)" if _DEFAULT_MODE == "database" \
        else "Seeded demo data"
    return html.Div(style={"display": "flex", "alignItems": "center",
                           "justifyContent": "space-between",
                           "padding": "16px 26px", "background": CARD,
                           "borderBottom": f"1px solid {HAIR}"},
        children=[
            html.Div([
                html.Span("🩺 ", style={"fontSize": "20px"}),
                html.Span("DFU Monitor", style={"fontWeight": "700",
                          "fontSize": "19px", "color": INK}),
                html.Span("  Staff Dashboard", style={"color": SUBTLE, "fontSize": "14px"}),
            ]),
            html.Div([
                # Data-stream toggle: seeded demo data ↔ live database (spec E)
                html.Span("Data:", style={"color": SUBTLE, "fontSize": "12px",
                          "marginRight": "6px"}),
                dcc.RadioItems(id="data-toggle", value=_DEFAULT_MODE, inline=True,
                    options=[{"label": " Seeded", "value": "seeded"},
                             {"label": " Database", "value": "database"}],
                    style={"display": "inline-block", "fontSize": "12px",
                           "marginRight": "12px"},
                    labelStyle={"marginRight": "8px"}),
                html.Span(f"Source: {badge}", id="source-badge",
                          style={"color": SUBTLE, "fontSize": "12px", "marginRight": "14px"}),
                html.Button("🕓 Audit log", id="audit-btn", n_clicks=0,
                            className="pill-btn", style={**GHOST_BTN, "marginRight": "8px"}),
                html.Button("Sign Out", id="logout-btn", n_clicks=0,
                            className="pill-btn", style=GHOST_BTN),
            ], style={"display": "flex", "alignItems": "center"}),
        ])


def _audit_overlay():
    """Full-screen modal listing recent edits made from the app."""
    return html.Div(id="audit-overlay",
        style={"display": "none", "position": "fixed", "inset": "0",
               "background": "rgba(0,0,0,.35)", "zIndex": "1000",
               "alignItems": "center", "justifyContent": "center"},
        children=[html.Div(style={**CARD_STYLE, "width": "min(900px, 92vw)",
                                  "maxHeight": "82vh", "overflow": "auto"}, children=[
            html.Div(style={"display": "flex", "justifyContent": "space-between",
                            "alignItems": "center", "marginBottom": "10px"}, children=[
                html.Div([
                    html.Div("Audit log — edits made from this app",
                             style={"fontWeight": "700", "fontSize": "16px", "color": INK}),
                    html.Div("Every record/patient edit is logged locally for review.",
                             style={"color": SUBTLE, "fontSize": "12px"}),
                ]),
                html.Button("✕ Close", id="audit-close", n_clicks=0,
                            className="pill-btn", style=GHOST_BTN),
            ]),
            dash_table.DataTable(
                id="audit-table", page_size=15, sort_action="native",
                columns=[{"name": "When", "id": "when"},
                         {"name": "Who", "id": "who"},
                         {"name": "Type", "id": "type"},
                         {"name": "Target", "id": "target"},
                         {"name": "Action", "id": "action"},
                         {"name": "Change", "id": "detail"}],
                style_header=_TBL_HDR, style_cell={**_TBL_CELL, "whiteSpace": "normal",
                         "height": "auto", "maxWidth": "300px"},
                style_as_list_view=True),
        ])])


def _patient_info_box():
    """Full-width squircle across the top of the detail page (spec individual #1/#2)."""
    return html.Div(style={**CARD_STYLE, "marginBottom": "16px"}, children=[
        # header: summary + minimise/edit/export
        html.Div(style={"display": "flex", "alignItems": "center",
                        "justifyContent": "space-between"}, children=[
            html.Div(style={"display": "flex", "alignItems": "center", "gap": "12px"},
                     children=[
                html.Img(id="info-avatar", src=svg.gender_avatar_datauri(None, size=44),
                         style={"width": "44px", "height": "44px", "borderRadius": "50%"}),
                html.Div([
                    html.Div(id="info-summary", style={"fontWeight": "700",
                             "fontSize": "18px", "color": INK}),
                    html.Div(id="info-subline", style={"color": SUBTLE, "fontSize": "12px"}),
                ]),
            ]),
            html.Div([
                html.Button("✎ Edit", id="info-edit-btn", n_clicks=0,
                            className="pill-btn", style={**GHOST_BTN, "marginRight": "8px"}),
                html.Button("▲ Minimise", id="info-min-btn", n_clicks=0,
                            className="pill-btn", style=GHOST_BTN),
            ]),
        ]),
        # body (hidden when minimised)
        html.Div(id="info-body", children=[
            html.Hr(style={"border": "none", "borderTop": f"1px solid {HAIR}",
                           "margin": "14px 0"}),
            html.Div(style={"display": "flex", "gap": "22px", "flexWrap": "wrap"},
                     children=[
                # read-only display rows (each with a ✎)
                html.Div(id="info-display", style={"flex": "1", "minWidth": "280px"}),
                # edit form (hidden unless editing)
                html.Div(id="info-edit-fields", style={"flex": "1", "minWidth": "280px",
                                                       "display": "none"}, children=[
                    html.Label("Full name", style=LABEL_STYLE),
                    dcc.Input(id="patient-name", type="text", style=INPUT_STYLE),
                    html.Div(style={"height": "10px"}),
                    html.Div(style={"display": "flex", "gap": "10px"}, children=[
                        html.Div(style={"flex": "1"}, children=[
                            html.Label("Date of birth (YYYY-MM-DD)", style=LABEL_STYLE),
                            dcc.Input(id="patient-dob", type="text",
                                      placeholder="YYYY-MM-DD", style=INPUT_STYLE)]),
                        html.Div(style={"flex": "1"}, children=[
                            html.Label("Sex", style=LABEL_STYLE),
                            dcc.Dropdown(id="patient-gender", clearable=False,
                                options=[{"label": "Male", "value": "M"},
                                         {"label": "Female", "value": "F"},
                                         {"label": "Unspecified", "value": ""}],
                                value="", style={"fontSize": "14px"})]),
                    ]),
                    html.Div(style={"height": "10px"}),
                    html.Label("Clinical notes", style=LABEL_STYLE),
                    dcc.Textarea(id="patient-notes",
                                 style={**INPUT_STYLE, "height": "70px", "resize": "vertical"}),
                    html.Div(style={"height": "12px"}),
                    html.Div([
                        html.Button("💾 Save patient", id="save-patient", n_clicks=0,
                                    className="pill-btn", style=PRIMARY_BTN),
                        html.Button("Cancel", id="info-cancel", n_clicks=0,
                                    className="pill-btn", style={**GHOST_BTN, "marginLeft": "8px"}),
                        html.Span(id="patient-save-note",
                                  style={"marginLeft": "10px", "color": GREEN, "fontSize": "13px"}),
                    ]),
                ]),
                # foot diagram (right side of the info box)
                (html.Div(style={"flex": "0 0 auto"}, children=[_foot_picker()])
                 if SHOW_FOOT_DIAGRAM else html.Div()),
            ]),
        ]),
    ])


def _patients_tab():
    return html.Div(style={"padding": "22px 26px"}, children=[
        # ---------- overview grid ----------
        html.Div(id="overview-wrap", children=[
            html.Div(style={"display": "flex", "alignItems": "center",
                            "justifyContent": "space-between", "marginBottom": "14px"},
                     children=[
                html.Div([
                    html.H2("Patients", style={"margin": "0", "color": INK}),
                    html.Div(id="overview-sub", style={"color": SUBTLE, "fontSize": "13px"}),
                ]),
                html.Button("↻ Reload", id="reload", n_clicks=0,
                            className="pill-btn", style=GHOST_BTN),
            ]),
            html.Div(id="overview-grid",
                     style={"display": "grid",
                            "gridTemplateColumns": "repeat(auto-fill, minmax(300px, 1fr))",
                            "gap": "16px"}),
        ]),

        # ---------- detail ----------
        html.Div(id="detail-wrap", style={"display": "none"}, children=[
            html.Div(style={"display": "flex", "justifyContent": "space-between",
                            "alignItems": "center", "marginBottom": "12px"}, children=[
                html.Button("← All patients", id="back-to-all", n_clicks=0,
                            className="pill-btn", style=GHOST_BTN),
                html.Div([
                    html.Button("⤓ Export PDF", id="export-btn", n_clicks=0,
                                className="pill-btn", style=GHOST_BTN)
                    if ENABLE_PDF_REPORT else html.Span(),
                    html.Span(id="export-note", style={"marginLeft": "10px",
                              "color": SUBTLE, "fontSize": "12px"}),
                ]),
            ]),

            # healing-status banner (suggested action = logistics only)
            (html.Div(id="healing-banner", style={"display": "none"})
             if SHOW_HEALING_BANNER else html.Div(id="healing-banner",
                                                  style={"display": "none"})),

            # full-width patient info squircle
            _patient_info_box(),

            # two columns
            html.Div(style={"display": "flex", "gap": "16px", "alignItems": "stretch",
                            "height": "calc(100vh - 360px)", "minHeight": "440px"},
                     children=[
                # LEFT — scrollable
                html.Div(id="left-col", style={"flex": "3", "minWidth": "420px",
                         "overflowY": "auto", "overflowX": "hidden", "paddingRight": "6px"},
                         children=[
                    # 3 widgets in one row: UT stage | wound bed | trend (spec E1)
                    html.Div(id="cards", style={"display": "flex", "gap": "14px",
                             "flexWrap": "wrap", "marginBottom": "16px",
                             "alignItems": "stretch"}),
                    html.Div(style={**CARD_STYLE, "marginBottom": "16px"}, children=[
                        html.Div(style={"display": "flex", "justifyContent": "space-between",
                                        "alignItems": "center", "marginBottom": "6px",
                                        "flexWrap": "wrap", "gap": "8px"}, children=[
                            html.Div("Wound area trend", style={"fontWeight": "700", "color": INK}),
                            html.Div(style={"display": "flex", "alignItems": "center",
                                            "gap": "8px"}, children=[
                                html.Span("Past", style={"color": SUBTLE, "fontSize": "13px"}),
                                dcc.Input(id="range-days", type="number", value=30, min=1,
                                          step=1, debounce=True,
                                          style={**INPUT_STYLE, "width": "72px",
                                                 "padding": "6px 8px", "textAlign": "center"}),
                                html.Span("days", style={"color": SUBTLE, "fontSize": "13px"}),
                                html.Button("↺ 30d", id="range-reset", n_clicks=0,
                                            className="pill-btn", style=GHOST_BTN),
                            ]),
                        ]),
                        dcc.Graph(id="trend", config={"displayModeBar": False}),
                    ]),
                    # Measurements — collapsible, grouped by session (spec E1)
                    html.Div(style={**CARD_STYLE}, children=[
                        html.Div(style={"display": "flex", "justifyContent": "space-between",
                                        "alignItems": "center", "marginBottom": "8px"},
                                 children=[
                            html.Div("Measurements", style={"fontWeight": "700", "color": INK}),
                            html.Div([
                                html.Button("💾 Save edits", id="save", n_clicks=0,
                                            className="pill-btn", style=GHOST_BTN),
                                html.Span(id="save-note", style={"marginLeft": "10px",
                                          "color": GREEN, "fontSize": "13px"}),
                            ]),
                        ]),
                        html.Div("Each row is one capture session (the average of its "
                                 "images). Click to expand the individual readings and "
                                 "edit the capture date/time.",
                                 style={"color": SUBTLE, "fontSize": "12px",
                                        "marginBottom": "8px"}),
                        html.Div(id="records-list"),
                    ]),
                ]),
                # RIGHT — not scrollable; images fill the height
                html.Div(style={"flex": "2", "minWidth": "300px", "display": "flex",
                                "flexDirection": "column"}, children=[
                    html.Div(style={**CARD_STYLE, "flex": "1", "display": "flex",
                                    "flexDirection": "column", "overflow": "hidden"},
                             children=[
                        html.Div(style={"display": "flex", "justifyContent": "space-between",
                                        "alignItems": "center", "marginBottom": "10px"},
                                 children=[
                            html.Div(id="image-title", style={"fontWeight": "700", "color": INK}),
                            (dcc.RadioItems(id="img-mode",
                                options=[{"label": " Selected Capture", "value": "latest"},
                                         {"label": " Graph Selection", "value": "compare"}],
                                value="latest", inline=True,
                                style={"fontSize": "13px"},
                                labelStyle={"marginLeft": "10px"})
                             if SHOW_COMPARE else html.Span()),
                        ]),
                        html.Div(id="image-panel", style={"flex": "1", "display": "flex",
                                 "flexDirection": "column", "gap": "10px", "minHeight": "0"}),
                    ]),
                ]),
            ]),
        ]),
    ])


def _list_tab():
    return html.Div(style={"padding": "22px 26px"}, children=[
        html.Div(style={"display": "flex", "justifyContent": "space-between",
                        "alignItems": "center", "marginBottom": "14px"}, children=[
            html.H2("All patients — list", style={"margin": "0", "color": INK}),
            html.Button("↻ Reload", id="reload-list", n_clicks=0,
                        className="pill-btn", style=GHOST_BTN),
        ]),
        html.Div("Compact view for many patients. Click a row to open the patient.",
                 style={"color": SUBTLE, "fontSize": "13px", "marginBottom": "10px"}),
        html.Div(style={**CARD_STYLE, "padding": "6px"}, children=[
            dash_table.DataTable(
                id="list-table", row_selectable="single", sort_action="native",
                columns=[{"name": "ID", "id": "patient_id"},
                         {"name": "Name", "id": "name"},
                         {"name": "Age", "id": "age"},
                         {"name": "Stage", "id": "stage"},
                         {"name": "Wound %", "id": "wound"},
                         {"name": "Δ %/day", "id": "roc"},
                         {"name": "Captures", "id": "n"},
                         {"name": "Status", "id": "status"}],
                style_header=_TBL_HDR, style_cell=_TBL_CELL, style_as_list_view=True,
                style_data_conditional=[
                    {"if": {"filter_query": '{status} = "URGENT"'},
                     "backgroundColor": "#fff5f5", "fontWeight": "bold"}]),
        ]),
    ])


def _cloud_tab():
    return html.Div(style={"padding": "22px 26px", "maxWidth": "1000px"}, children=[
        html.H2("Cloud (Firebase) — data verification",
                style={"margin": "0 0 4px", "color": INK}),
        html.Div("Live test that the desktop app can pull capture data — and an "
                 "image — directly from Firestore. Independent of the dashboard's "
                 "active data source.",
                 style={"color": SUBTLE, "fontSize": "13px", "marginBottom": "16px"}),
        html.Button("⟳ Test connection & pull data", id="cloud-test", n_clicks=0,
                    className="pill-btn", style=PRIMARY_BTN),
        html.Div(id="cloud-status", style={"marginTop": "18px"}),
    ])


def _debug_bar():
    """Thin diagnostics strip, only shown when DEBUG_UI is on."""
    if not DEBUG_UI:
        return html.Div(id="debug-bar", style={"display": "none"})
    return html.Div(id="debug-bar",
        style={"background": "#1c1c1e", "color": "#9aff9a", "fontSize": "11px",
               "fontFamily": "monospace", "padding": "4px 26px",
               "whiteSpace": "pre-wrap"})


def _main_view():
    return html.Div(id="main-view", style={"display": "none"}, children=[
        _header(),
        _debug_bar(),
        dcc.Tabs(id="tabs", value="tab-patients", className="tab-bar",
                 colors={"border": HAIR, "primary": BLUE, "background": BG},
                 children=[
                     dcc.Tab(label="Patients", value="tab-patients", children=_patients_tab()),
                     dcc.Tab(label="List", value="tab-list", children=_list_tab()),
                     dcc.Tab(label="Cloud (Firebase)", value="tab-cloud", children=_cloud_tab()),
                 ]),
        _audit_overlay(),
    ])


app.layout = html.Div(style={"fontFamily": FONT, "background": BG,
                             "minHeight": "100vh", "color": INK}, children=[
    dcc.Store(id="auth-state", storage_type="memory", data=False),
    dcc.Store(id="selected-pid", storage_type="memory"),
    dcc.Store(id="raw-records", storage_type="memory"),
    dcc.Store(id="save-token", storage_type="memory", data=0),       # serialises save→recalc
    dcc.Store(id="selected-session", storage_type="memory", data=""),  # which session's images
    dcc.Store(id="data-mode", storage_type="memory", data=_DEFAULT_MODE),  # seeded|database
    dcc.Store(id="info-min", storage_type="memory", data=False),
    dcc.Store(id="info-edit", storage_type="memory", data=False),
    dcc.Store(id="wound-points", storage_type="memory", data=[]),  # manual DFU markers
    dcc.Store(id="audit-open", storage_type="memory", data=False),
    dcc.Download(id="dl-report"),
    _login_view(),
    _main_view(),
])


# ============================================================================ #
#  Auth callbacks
# ============================================================================ #
@app.callback(Output("auth-state", "data"), Output("login-error", "children"),
              Input("login-btn", "n_clicks"), Input("pin-input", "value"),
              prevent_initial_call=True)
def do_login(_n, pin_val):
    if ctx.triggered_id not in ("login-btn", "pin-input"):
        return no_update, no_update
    if pin_val == STAFF_PIN:
        return True, ""
    if pin_val:
        return False, "Incorrect PIN — please try again."
    return no_update, no_update


@app.callback(Output("auth-state", "data", allow_duplicate=True),
              Input("logout-btn", "n_clicks"), prevent_initial_call=True)
def do_logout(_n):
    return False


@app.callback(Output("login-view", "style"), Output("main-view", "style"),
              Input("auth-state", "data"))
def toggle_view(auth):
    centred = {"display": "flex", "alignItems": "center",
               "justifyContent": "center", "minHeight": "100vh"}
    return ({"display": "none"}, {}) if auth else (centred, {"display": "none"})


# ============================================================================ #
#  Overview + list  (either Reload refreshes BOTH tabs — spec UI comment)
# ============================================================================ #
# Switch the active data stream (seeded ↔ database) and refresh (spec E)
@app.callback(Output("data-mode", "data"), Output("source-badge", "children"),
              Output("selected-pid", "data", allow_duplicate=True),
              Input("data-toggle", "value"), prevent_initial_call=True)
def switch_source(mode):
    SRC.set_mode(mode)
    label = "Seeded demo data" if mode == "seeded" else "Live database (Firestore)"
    return mode, f"Source: {label}", ""        # reset selection → back to overview


@app.callback(Output("overview-grid", "children"), Output("overview-sub", "children"),
              Input("auth-state", "data"),
              Input("reload", "n_clicks"), Input("reload-list", "n_clicks"),
              Input("selected-pid", "data"),
              Input("save", "n_clicks"), Input("save-patient", "n_clicks"),
              Input("data-mode", "data"))
def load_overview(auth, _r, _rl, _pid, _s, _sp, _dm):
    if not auth:
        return no_update, no_update
    pats = SRC.patients()
    if not pats:
        empty = html.Div("No patients found in this data source.",
                         style={"color": SUBTLE, "padding": "30px"})
        return [empty], "0 patients"
    n_urgent = sum(1 for p in pats if p.get("urgent"))
    return [_patient_card(p) for p in pats], \
           f"{len(pats)} patient(s) · {n_urgent} need attention"


@app.callback(Output("list-table", "data"),
              Input("auth-state", "data"),
              Input("reload-list", "n_clicks"), Input("reload", "n_clicks"),
              Input("save", "n_clicks"), Input("save-patient", "n_clicks"),
              Input("data-mode", "data"))
def load_list(auth, _rl, _r, _s, _sp, _dm):
    if not auth:
        return no_update
    rows = []
    for p in SRC.patients():
        roc = p.get("roc_per_day")
        rows.append({
            "patient_id": p["patient_id"], "name": p.get("name", ""),
            "age": p.get("age") if p.get("age") is not None else "—",
            "stage": STAGE_SHORT.get(p.get("level"), "Unstaged"),
            "wound": _pct2(p.get("wound_pct")),
            "roc": (f"{roc:+.2f}" if roc is not None else "—"),
            "n": p.get("n"), "status": "URGENT" if p.get("urgent") else ""})
    return rows


@app.callback(Output("selected-pid", "data"),
              Input({"type": "pcard", "pid": ALL}, "n_clicks"),
              Input("back-to-all", "n_clicks"),
              prevent_initial_call=True)
def pick_patient(_clicks, _back):
    trig = ctx.triggered_id
    if trig == "back-to-all":
        return None
    if isinstance(trig, dict) and ctx.triggered and ctx.triggered[0]["value"]:
        return trig["pid"]
    return no_update


@app.callback(Output("selected-pid", "data", allow_duplicate=True),
              Output("tabs", "value"),
              Input("list-table", "selected_rows"), State("list-table", "data"),
              prevent_initial_call=True)
def pick_from_list(sel, data):
    if sel and data and 0 <= sel[0] < len(data):
        return data[sel[0]]["patient_id"], "tab-patients"
    return no_update, no_update


@app.callback(Output("overview-wrap", "style"), Output("detail-wrap", "style"),
              Input("selected-pid", "data"))
def toggle_detail(pid):
    if pid:
        return {"display": "none"}, {"display": "block"}
    return {"display": "block"}, {"display": "none"}


# ============================================================================ #
#  Trend range  (Past N days, default 30, reset-to-30 — spec #5)
# ============================================================================ #
@app.callback(Output("range-days", "value"),
              Input("range-reset", "n_clicks"), prevent_initial_call=True)
def reset_range(_n):
    return 30


# ============================================================================ #
#  Detail render  (metrics, woundbed, trend, records, banner)
# ============================================================================ #
@app.callback(
    Output("cards", "children"), Output("trend", "figure"),
    Output("records-list", "children"), Output("raw-records", "data"),
    Output("healing-banner", "children"), Output("healing-banner", "style"),
    Input("selected-pid", "data"), Input("range-days", "value"),
    Input("save-token", "data"), Input("selected-session", "data"))
def render_detail(pid, days, _tok, sel_sid):
    try:
        return _render_detail_impl(pid, days, sel_sid)
    except Exception as e:
        dbg.capture("render_detail", e)
        return ([], go.Figure(), [], [],
                ("⚠ render error (see debug log)" if DEBUG_UI else ""),
                {"display": "none"})


def _render_detail_impl(pid, days, sel_sid):
    if not pid:
        return [], go.Figure(), [], [], "", {"display": "none"}
    days = days if (isinstance(days, (int, float)) and days and days > 0) else 30
    rows  = SRC.captures(pid)
    sess  = ds.sessions(rows)                       # group N images per session
    trend = ds.session_trend(sess, days)            # 2 avg pts >=7 days apart?
    focus = _focus_session(sess, sel_sid)           # widget subject (picked/latest)

    roc       = trend.get("roc_per_day")            # over the average readings
    has_trend = trend.get("ok", False)
    latest_lvl = sess[-1].get("avg_level") if sess else None
    urgent = ds._is_urgent({"highest_level": latest_lvl}, roc) if sess else False

    # 3 widgets in one row: UT stage | wound bed | trend (spec E1)
    cards = [_stage_widget(focus), _woundbed_card(focus), _trend_widget(trend)]

    if SHOW_HEALING_BANNER and rows:
        st = _healing_status(roc, urgent, has_trend)
        banner_children = html.Div(style={"display": "flex", "alignItems": "center",
                                          "gap": "12px"}, children=[
            html.Span(st["label"], style={"fontWeight": "800", "fontSize": "15px",
                      "color": "#fff", "background": "rgba(0,0,0,.14)",
                      "padding": "3px 12px", "borderRadius": "999px"}),
            html.Span(st["action"], style={"color": "#fff", "fontSize": "14px",
                      "fontWeight": "600"}),
        ])
        banner_style = {**CARD_STYLE, "background": st["colour"], "marginBottom": "16px",
                        "padding": "12px 16px"}
    else:
        banner_children, banner_style = "", {"display": "none"}

    return (cards, _trend_fig(sess, days), _records_list(sess), rows,
            banner_children, banner_style)


# patient name/age + sub-line + avatar live in the info-box header
@app.callback(Output("info-summary", "children"), Output("info-subline", "children"),
              Output("info-avatar", "src"),
              Input("selected-pid", "data"), Input("save-patient", "n_clicks"))
def render_info_header(pid, _sp):
    if not pid:
        return "", "", svg.gender_avatar_datauri(None, size=44)
    meta = SRC.get_patient(pid)
    age = ds.age_from_dob(meta.get("dob"))
    sub = pid + (f" · DOB {meta['dob']}" if meta.get("dob") else "")
    _np = _count_points(meta)
    if _np:
        sub += f" · {_np} wound marker(s)"
    return _name_age(meta) or pid, sub, svg.gender_avatar_datauri(meta.get("gender"), size=44)


# ============================================================================ #
#  Patient info: display rows, edit toggle, minimise, foot site, save
# ============================================================================ #
def _disp_row(label, value, field):
    return html.Div(style={"display": "flex", "alignItems": "baseline", "gap": "8px",
                           "padding": "7px 0", "borderBottom": f"1px solid {HAIR}"},
                    children=[
        html.Div(label, style={"width": "120px", "color": SUBTLE, "fontSize": "12px",
                               "fontWeight": "600", "flex": "0 0 auto"}),
        html.Div(value or "—", style={"flex": "1", "color": INK, "fontSize": "14px",
                                      "whiteSpace": "pre-wrap"}),
        html.Button("✎", id={"type": "field-edit", "field": field}, n_clicks=0,
                    className="icon-btn", title=f"Edit {label.lower()}"),
    ])


@app.callback(Output("info-display", "children"),
              Input("selected-pid", "data"), Input("save-patient", "n_clicks"))
def render_info_display(pid, _sp):
    if not pid:
        return ""
    meta = SRC.get_patient(pid)
    age = ds.age_from_dob(meta.get("dob"))
    gender = {"m": "Male", "f": "Female"}.get((meta.get("gender") or "").lower(),
                                              "Unspecified")
    return [
        _disp_row("Full name", meta.get("name"), "name"),
        _disp_row("Date of birth",
                  (meta.get("dob") or "") + (f"  (age {age})" if age is not None else ""),
                  "dob"),
        _disp_row("Sex", gender, "gender"),
        _disp_row("Wound markers", f"{_count_points(meta)} point(s) marked", "site"),
        _disp_row("Clinical notes", meta.get("notes"), "notes"),
    ]


# load the editable field values when a patient is opened
@app.callback(Output("patient-name", "value"), Output("patient-dob", "value"),
              Output("patient-gender", "value"), Output("patient-notes", "value"),
              Output("wound-points", "data"),
              Input("selected-pid", "data"))
def load_patient_fields(pid):
    if not pid:
        return "", "", "", "", []
    meta = SRC.get_patient(pid)
    try:
        pts = json.loads(meta.get("wound_points") or "[]")
    except Exception:
        pts = []
    return (meta.get("name", ""), meta.get("dob", ""), meta.get("gender", "") or "",
            meta.get("notes", ""), pts)


# edit-mode toggle (header button, any field ✎, cancel, save, patient change)
@app.callback(Output("info-edit", "data"),
              Input("info-edit-btn", "n_clicks"),
              Input({"type": "field-edit", "field": ALL}, "n_clicks"),
              Input("info-cancel", "n_clicks"), Input("save-patient", "n_clicks"),
              Input("selected-pid", "data"),
              State("info-edit", "data"), prevent_initial_call=True)
def toggle_edit(_e, _fe, _c, _sp, _pid, cur):
    trig = ctx.triggered_id
    if trig == "selected-pid" or trig in ("info-cancel", "save-patient"):
        return False
    if trig == "info-edit-btn" or isinstance(trig, dict):
        return True
    return cur


@app.callback(Output("info-display", "style"), Output("info-edit-fields", "style"),
              Input("info-edit", "data"))
def apply_edit_mode(editing):
    if editing:
        return {"display": "none"}, {"flex": "1", "minWidth": "280px", "display": "block"}
    return ({"flex": "1", "minWidth": "280px", "display": "block"},
            {"flex": "1", "minWidth": "280px", "display": "none"})


# minimise toggle
@app.callback(Output("info-min", "data"),
              Input("info-min-btn", "n_clicks"), Input("selected-pid", "data"),
              State("info-min", "data"), prevent_initial_call=True)
def toggle_min(_n, _pid, cur):
    if ctx.triggered_id == "selected-pid":
        return False
    return not cur


@app.callback(Output("info-body", "style"), Output("info-min-btn", "children"),
              Input("info-min", "data"))
def apply_min(minimised):
    if minimised:
        return {"display": "none"}, "▼ Expand"
    return {"display": "block"}, "▲ Minimise"


# wound-marker points: add on foot click, undo / clear-view (spec A2)
@app.callback(Output("wound-points", "data", allow_duplicate=True),
              Input({"type": "footcell", "x": ALL, "y": ALL}, "n_clicks"),
              Input("foot-undo", "n_clicks"), Input("foot-clear", "n_clicks"),
              State("wound-points", "data"), State("foot-view", "value"),
              State("marker-colour", "value"), prevent_initial_call=True)
def edit_points(_cells, _undo, _clear, pts, view, colour):
    pts = list(pts or [])
    trig = ctx.triggered_id
    if trig == "foot-undo":
        for i in range(len(pts) - 1, -1, -1):
            if pts[i].get("view") == view:
                del pts[i]
                break
        return pts
    if trig == "foot-clear":
        return [p for p in pts if p.get("view") != view]
    if isinstance(trig, dict) and trig.get("type") == "footcell" \
            and ctx.triggered and ctx.triggered[0]["value"]:
        pts.append({"view": view, "x": trig["x"], "y": trig["y"],
                    "colour": colour or "red"})
    return pts


@app.callback(Output("foot-outline-img", "src"), Output("foot-markers", "children"),
              Output("foot-count", "children"),
              Input("wound-points", "data"), Input("foot-view", "value"))
def render_foot(pts, view):
    pts = pts or []
    here = [p for p in pts if p.get("view") == view]
    dots = [html.Div(style={"position": "absolute", "left": f"{p['x']-6}px",
            "top": f"{p['y']-6}px", "width": "12px", "height": "12px",
            "borderRadius": "50%", "border": "2px solid #fff",
            "background": svg.MARKER_COLOURS.get(p.get("colour"), "#e0301e"),
            "boxShadow": "0 0 2px rgba(0,0,0,.6)"}) for p in here]
    return (svg.foot_outline_datauri(view or "bottom"), dots,
            f"{len(here)} on this view · {len(pts)} total")


@app.callback(Output("patient-save-note", "children"),
              Input("save-patient", "n_clicks"), State("selected-pid", "data"),
              State("patient-name", "value"), State("patient-dob", "value"),
              State("patient-gender", "value"), State("patient-notes", "value"),
              State("wound-points", "data"), prevent_initial_call=True)
def save_patient_info(_n, pid, name, dob, gender, notes, points):
    if not pid:
        return "No patient selected."
    try:
        old = SRC.get_patient(pid) or {}
        pts_json = json.dumps(points or [])
        SRC.upsert_patient(pid, name=name or "", dob=dob or "", notes=notes or "",
                           gender=gender or "", wound_site=old.get("wound_site") or "",
                           wound_points=pts_json)
        new = {"name": name or "", "dob": dob or "", "notes": notes or "",
               "gender": gender or "", "wound_points": pts_json}
        detail = audit.diff_summary(
            {**old, "wound_points": old.get("wound_points") or "[]"}, new,
            ["name", "dob", "gender", "wound_points", "notes"])
        audit.record("patient", pid, "edit", detail or "(no field changes)", BACKEND)
        return "Saved ✓"
    except Exception as e:
        _dbg("save_patient_info error:", e)
        return f"Error: {e}"


# ============================================================================ #
#  Records: save edits (date+time -> stamp, label, 2dp values)  — spec #7/#8/#9
# ============================================================================ #
@app.callback(Output("save-note", "children"), Output("save-token", "data"),
              Input("save", "n_clicks"),
              State({"type": "sess-date", "sid": ALL}, "value"),
              State({"type": "sess-date", "sid": ALL}, "id"),
              State({"type": "sess-time", "sid": ALL}, "value"),
              State({"type": "sess-time", "sid": ALL}, "id"),
              State({"type": "sess-angle", "sid": ALL}, "value"),
              State({"type": "sess-angle", "sid": ALL}, "id"),
              State({"type": "img-lvl", "rid": ALL}, "value"),
              State({"type": "img-lvl", "rid": ALL}, "id"),
              State({"type": "img-wound", "rid": ALL}, "value"),
              State({"type": "img-wound", "rid": ALL}, "id"),
              State("raw-records", "data"), State("save-token", "data"),
              prevent_initial_call=True)
def save_edits(_n, dates, date_ids, times, time_ids, angles, angle_ids,
               lvls, lvl_ids, wounds, wound_ids, raw, token):
    """Session date/time + foot angle apply to all N images; per-image Lvl &
    Wound % are individual. Writing here then bumping save-token forces
    render_detail to RECALCULATE the graph/trend/widgets (spec E1)."""
    if not raw:
        return "", no_update
    date_by  = {i["sid"]: v for i, v in zip(date_ids or [], dates or [])}
    time_by  = {i["sid"]: v for i, v in zip(time_ids or [], times or [])}
    angle_by = {i["sid"]: v for i, v in zip(angle_ids or [], angles or [])}
    lvl_by   = {i["rid"]: v for i, v in zip(lvl_ids or [], lvls or [])}
    wnd_by   = {i["rid"]: v for i, v in zip(wound_ids or [], wounds or [])}

    members = {}
    for r in raw:                                  # group member rows by session
        members.setdefault(r.get("session_id") or r.get("stamp"), []).append(r)

    n_sess = 0
    for sid, mem in members.items():
        d = (date_by.get(sid) or "").strip()
        t = (time_by.get(sid) or "").strip()
        new_angle = (angle_by.get(sid) or "").strip()
        changed = False

        if d or t:
            parsed = None
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
                try:
                    parsed = datetime.datetime.strptime(f"{d} {t or '00:00'}", fmt)
                    break
                except ValueError:
                    parsed = None
            if parsed is None:
                return f"⚠ Bad date/time ({d} {t}). Use YYYY-MM-DD and HH:MM.", no_update
            cur = ds.parse_stamp(mem[0].get("stamp"))
            if not (cur and parsed.replace(second=0) == cur.replace(second=0)):
                new_stamp = parsed.strftime("%Y%m%d_%H%M%S")
                for m in mem:
                    SRC.update_capture(m["id"], {"stamp": new_stamp})
                audit.record("session", sid, "edit", f"date/time → {d} {t or '00:00'}", BACKEND)
                changed = True

        if new_angle and new_angle != (mem[0].get("foot_angle") or ""):
            for m in mem:
                SRC.update_capture(m["id"], {"foot_angle": new_angle})
            audit.record("session", sid, "edit", f"foot angle → {new_angle}", BACKEND)
            changed = True
        if changed:
            n_sess += 1

    # per-image Lvl / Wound % corrections (spec A4)
    raw_by_rid = {str(r.get("id")): r for r in raw}
    n_img = 0
    for rid in set(list(lvl_by) + list(wnd_by)):
        cur = raw_by_rid.get(rid)
        if not cur:
            continue
        upd = {}
        if rid in lvl_by:
            nl = _to_int(lvl_by.get(rid))
            if nl != cur.get("highest_level"):
                upd["highest_level"] = nl
        if rid in wnd_by:
            nw = _to_float(wnd_by.get(rid))
            if nw is not None and nw != cur.get("wound_pct"):
                upd["wound_pct"] = nw
        if upd:
            try:
                SRC.update_capture(cur["id"], upd)
            except Exception as e:
                _dbg("save_edits img error:", e)
                return f"Error saving image {rid}: {e}", no_update
            n_img += 1

    if not (n_sess or n_img):
        return "No changes.", (token or 0) + 1
    note = f"Saved ✓ ({n_sess} session(s), {n_img} image(s))"
    return note, (token or 0) + 1


# ============================================================================ #
#  Image panel: Latest (captured + overlay) or Compare (baseline vs latest)
# ============================================================================ #
def _img_or_placeholder(uri, max_h=None):
    if uri:
        st = {"maxWidth": "100%", "borderRadius": "12px", "objectFit": "contain"}
        st["maxHeight"] = max_h or "100%"
        return html.Img(src=uri, style=st)
    return html.Div("Image not available",
                    style={"color": "#c7c7cc", "fontSize": "12px", "padding": "30px 0",
                           "background": "#f7f7fa", "borderRadius": "12px",
                           "textAlign": "center"})


@app.callback(Output("image-panel", "children"), Output("image-title", "children"),
              Input("selected-session", "data"), Input("raw-records", "data"),
              Input("img-mode", "value"), Input("range-days", "value"))
def show_images(sel_sid, raw_data, mode, days):
    try:
        return _show_images_impl(sel_sid, raw_data, mode, days)
    except Exception as e:
        dbg.capture("show_images", e)
        return html.Div("Could not load images.", style={"color": SUBTLE}), "Images"


def _img_block(label, sub, uri):
    return html.Div(style={"flex": "1", "minHeight": "0", "display": "flex",
            "flexDirection": "column", "textAlign": "center"}, children=[
        html.Div(label, style={"color": INK, "fontSize": "12px", "fontWeight": "700"}),
        html.Div(sub, style={"color": SUBTLE, "fontSize": "11px", "marginBottom": "6px"}),
        html.Div(_img_or_placeholder(uri), style={"flex": "1", "display": "flex",
                 "alignItems": "center", "justifyContent": "center", "minHeight": "0"}),
    ])


def _show_images_impl(sel_sid, raw_data, mode, days):
    if not raw_data:
        return html.Div("No records.", style={"color": SUBTLE}), "Images"
    sess = ds.sessions(raw_data)
    if not sess:
        return html.Div("No records.", style={"color": SUBTLE}), "Images"

    # ---- Graph Selection: earliest vs latest AVERAGE reading on the graph ----
    if mode == "compare" and SHOW_COMPARE:
        days = days if (isinstance(days, (int, float)) and days and days > 0) else 30
        tr = ds.session_trend(sess, days)
        e, l = tr.get("earliest"), tr.get("latest")
        if not e or not l or e is l:
            return (html.Div("Need at least 2 average readings in the selected "
                             "range to compare.", style={"color": SUBTLE,
                             "padding": "20px", "textAlign": "center"}),
                    "Graph Selection")
        bcap, _ = SRC.get_capture_images(e.get("rep") or {})
        lcap, _ = SRC.get_capture_images(l.get("rep") or {})
        bw, lw = e.get("avg_wound_pct"), l.get("avg_wound_pct")
        if bw not in (None, 0) and lw is not None:
            change = (lw - bw) / bw * 100.0
            heal = f"{abs(change):.0f}% {'smaller' if change < 0 else 'larger'}"
            heal_col = GREEN if change < 0 else RED
        else:
            heal, heal_col = "—", SUBTLE
        panel = [
            html.Div(f"Latest vs earliest average: {heal}",
                     style={"textAlign": "center", "fontWeight": "700",
                            "color": heal_col, "marginBottom": "8px"}),
            _img_block("Earliest Reading", f"{_sess_dt_label(e)} · {_pct2(bw)}", bcap),
            _img_block("Latest Reading", f"{_sess_dt_label(l)} · {_pct2(lw)}", lcap),
        ]
        return panel, "Graph Selection (earliest → latest average)"

    # ---- Selected Capture: the picked session (or latest) ----
    focus = _focus_session(sess, sel_sid)
    rep = (focus or {}).get("rep") or {}
    cap_uri, ovl_uri = SRC.get_capture_images(rep)
    dt_str = _sess_dt_label(focus) if focus else ""
    sub = f"Average of {focus.get('n_images', 1)} images" if focus else ""
    return ([_img_block("Captured (1st image)", sub, cap_uri),
             _img_block("AI overlay (1st image)", sub, ovl_uri)],
            f"📷 Selected capture · {dt_str}")


# selected session for the image panel (reset on patient change; set on "Show images")
@app.callback(Output("selected-session", "data", allow_duplicate=True),
              Input("selected-pid", "data"), prevent_initial_call=True)
def _reset_selected_session(_pid):
    return ""


@app.callback(Output("selected-session", "data", allow_duplicate=True),
              Input({"type": "sess-pick", "sid": ALL}, "n_clicks"),
              prevent_initial_call=True)
def _pick_session(_clicks):
    trig = ctx.triggered_id
    if isinstance(trig, dict) and ctx.triggered and ctx.triggered[0]["value"]:
        return trig["sid"]
    return no_update


# ============================================================================ #
#  PDF export
# ============================================================================ #
@app.callback(Output("dl-report", "data"), Output("export-note", "children"),
              Input("export-btn", "n_clicks"),
              State("selected-pid", "data"), State("range-days", "value"),
              prevent_initial_call=True)
def export_pdf(_n, pid, days):
    if not pid:
        return no_update, "Open a patient first."
    if not report.PDF_AVAILABLE:
        return no_update, "Install reportlab to enable PDF export (run: make setup)."
    days = days if (isinstance(days, (int, float)) and days and days > 0) else 30
    rows = SRC.captures(pid)
    sess = ds.sessions(rows)                         # report on SESSIONS, not images
    if not sess:
        return no_update, "No measurements to export for this patient."
    meta = SRC.get_patient(pid)
    meta["age"] = ds.age_from_dob(meta.get("dob"))

    # One synthetic "row" per session (its average) so the report's count + trend
    # match the dashboard.
    avg_rows = [{"stamp": s["stamp"], "wound_pct": s.get("avg_wound_pct"),
                 "foot_pct": s.get("avg_foot_pct"), "highest_level": s.get("avg_level")}
                for s in sess]
    trend = ds.session_trend(sess, days)
    roc = trend.get("roc_per_day")
    latest = sess[-1]
    lvl_k = latest.get("avg_level") if latest.get("avg_level") is not None else -1
    letter = latest.get("avg_stage") or STAGE_LETTER.get(lvl_k, "–")
    stage_text = (f"UT Stage {letter} — {STAGE_DESC.get(lvl_k,'')}"
                  if letter in ("A", "B", "C", "D")
                  else f"{STAGE_SHORT.get(lvl_k,'Unstaged')} — {STAGE_DESC.get(lvl_k,'')}")
    urgent = ds._is_urgent({"highest_level": latest.get("avg_level")}, roc)
    status = _healing_status(roc, urgent, trend.get("ok", False))
    cap_uri, ovl_uri = SRC.get_capture_images(latest.get("rep") or {})
    try:
        pdf = report.build_patient_pdf(meta, avg_rows, days=days, roc=roc,
                                       stage_text=stage_text, status=status,
                                       cap_uri=cap_uri, ovl_uri=ovl_uri)
    except Exception as e:
        dbg.capture("export_pdf", e)
        return no_update, f"Export failed: {e}"
    fname = f"DFU_{pid}_{datetime.datetime.now():%Y%m%d_%H%M}.pdf"
    return dcc.send_bytes(pdf, fname), "Exported ✓"


# ============================================================================ #
#  Cloud verify tab
# ============================================================================ #
@app.callback(Output("cloud-status", "children"), Input("cloud-test", "n_clicks"),
              prevent_initial_call=True)
def cloud_test(_n):
    diag = FB.diagnostics()
    ok = diag.get("ok")
    banner = html.Div(style={**CARD_STYLE,
                             "borderLeft": f"6px solid {GREEN if ok else RED}",
                             "marginBottom": "16px"}, children=[
        html.Div(("✓ Connected to Firebase" if ok else "✗ Could not pull from Firebase"),
                 style={"fontWeight": "700", "fontSize": "16px",
                        "color": GREEN if ok else RED}),
        html.Div(diag.get("message", ""), style={"color": SUBTLE, "fontSize": "13px",
                 "marginTop": "4px", "wordBreak": "break-word"}),
    ])
    if not ok:
        return [banner, html.Div(
            "Check internet access, the Firestore project ID/API key in "
            "data_source.py, and that the database security rules allow reads.",
            style={"color": SUBTLE, "fontSize": "13px"})]

    metrics = html.Div(style={"display": "flex", "gap": "14px", "marginBottom": "16px"},
                       children=[
        _metric("Patients in cloud", str(diag.get("n_patients", 0)), BLUE),
        _metric("Captures in cloud", str(diag.get("n_captures", 0)), GREEN),
    ])
    sample = diag.get("sample", [])
    table = dash_table.DataTable(
        columns=[{"name": "Patient", "id": "patient_id"},
                 {"name": "Name", "id": "name"},
                 {"name": "Stage", "id": "stage"},
                 {"name": "Wound %", "id": "wound"},
                 {"name": "Captures", "id": "n"}],
        data=[{"patient_id": p["patient_id"], "name": p.get("name", ""),
               "stage": STAGE_SHORT.get(p.get("level"), "Unstaged"),
               "wound": _pct2(p.get("wound_pct")), "n": p.get("n")}
              for p in sample],
        style_header=_TBL_HDR, style_cell=_TBL_CELL, style_as_list_view=True)

    img_proof = html.Div()
    if sample:
        pid0 = sample[0]["patient_id"]
        caps = FB.captures(pid0)
        if caps:
            cap_uri, ovl_uri = FB.get_capture_images(caps[-1])
            if cap_uri or ovl_uri:
                img_proof = html.Div(style={**CARD_STYLE, "marginTop": "16px"}, children=[
                    html.Div(f"Image pulled from Firestore (patient {pid0}) — "
                             "confirms base64 images round-trip:",
                             style={"fontWeight": "700", "color": INK, "marginBottom": "10px"}),
                    html.Div(style={"display": "flex", "gap": "12px"}, children=[
                        html.Img(src=cap_uri, style={"maxHeight": "200px",
                                 "borderRadius": "12px"}) if cap_uri else "",
                        html.Img(src=ovl_uri, style={"maxHeight": "200px",
                                 "borderRadius": "12px"}) if ovl_uri else "",
                    ]),
                ])
            else:
                img_proof = html.Div("Records found, but no image strings stored yet.",
                                     style={"color": SUBTLE, "fontSize": "13px",
                                            "marginTop": "12px"})
    return [banner, metrics,
            html.Div("Patients pulled from Firestore:",
                     style={"fontWeight": "700", "color": INK, "margin": "4px 0 8px"}),
            html.Div(table, style={**CARD_STYLE, "padding": "6px"}),
            img_proof]


# ============================================================================ #
#  Audit log overlay
# ============================================================================ #
@app.callback(Output("audit-open", "data"),
              Input("audit-btn", "n_clicks"), Input("audit-close", "n_clicks"),
              State("audit-open", "data"), prevent_initial_call=True)
def toggle_audit(_o, _c, cur):
    return ctx.triggered_id == "audit-btn" and not cur


@app.callback(Output("audit-overlay", "style"), Output("audit-table", "data"),
              Input("audit-open", "data"),
              Input("save", "n_clicks"), Input("save-patient", "n_clicks"))
def render_audit(is_open, _s, _sp):
    base = {"position": "fixed", "inset": "0", "background": "rgba(0,0,0,.35)",
            "zIndex": "1000", "alignItems": "center", "justifyContent": "center"}
    rows = audit.table_rows(300)
    if is_open:
        return {**base, "display": "flex"}, rows
    return {**base, "display": "none"}, rows


# ============================================================================ #
#  Debug bar (only active when DEBUG_UI=True)
# ============================================================================ #
@app.callback(Output("debug-bar", "children"),
              Input("auth-state", "data"), Input("reload", "n_clicks"),
              Input("selected-pid", "data"))
def render_debug_bar(auth, _r, pid):
    if not DEBUG_UI or not auth:
        return ""
    parts = [f"🐞 DEBUG · {dbg.diagnostics(SRC)}",
             f"sel={pid or '-'}"]
    if dbg.last_error():
        parts.append("lastError=" + dbg.last_error())
    return "  |  ".join(parts)


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    app.run(debug=True, port=8050)
