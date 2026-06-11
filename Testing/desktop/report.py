"""
=============================================================================
 PDF REPORT  (Testing/desktop/report.py)
-----------------------------------------------------------------------------
 Builds a one-page printable PDF for a single patient (spec G: "report"; new
 feature: Export / print patient PDF report). Kept separate from app.py so the
 reporting can grow (or be swapped) without touching the dashboard.

 build_patient_pdf(...) -> bytes  (ready for dcc.send_bytes)

 Design rules honoured here:
   * Screening aid only — every report carries the "not a diagnosis" disclaimer.
   * Suggested action wording is LOGISTICS ONLY (visit clinic / contact doctor /
     routine monitoring). No clinical/medical advice — the caller passes the
     pre-vetted action string; this module never invents treatment guidance.

 reportlab is optional: PDF_AVAILABLE tells the app whether to enable the
 button, so a missing dependency degrades gracefully instead of crashing.
=============================================================================
"""
import base64
import datetime
import io

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, Image)
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.lib.utils import ImageReader
    PDF_AVAILABLE = True
except Exception:                      # reportlab not installed
    PDF_AVAILABLE = False


def _img_flowable(data_uri, max_w, max_h):
    """data URI -> reportlab Image scaled to fit, or None."""
    if not data_uri or "," not in data_uri:
        return None
    try:
        raw = base64.b64decode(data_uri.split(",", 1)[1])
        reader = ImageReader(io.BytesIO(raw))
        iw, ih = reader.getSize()
        scale = min(max_w / iw, max_h / ih)
        return Image(io.BytesIO(raw), width=iw * scale, height=ih * scale)
    except Exception:
        return None


def _trend_drawing(points, width, height):
    """points = [(datetime, wound_pct), ...]  ->  reportlab line chart."""
    pts = [(d, y) for d, y in points if y is not None]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda p: p[0])
    t0 = pts[0][0]
    data = [[((d - t0).total_seconds() / 86400.0, y) for d, y in pts]]

    dwg = Drawing(width, height)
    lp = LinePlot()
    lp.x, lp.y = 28, 22
    lp.width, lp.height = width - 44, height - 40
    lp.data = data
    lp.lines[0].strokeColor = colors.HexColor("#0a84ff")
    lp.lines[0].strokeWidth = 2
    lp.lines[0].symbol = None
    xs = [p[0] for p in data[0]]
    ys = [p[1] for p in data[0]]
    lp.xValueAxis.valueMin = min(xs)
    lp.xValueAxis.valueMax = max(xs)
    lp.xValueAxis.labelTextFormat = lambda v: f"{v:.0f}d"
    lp.yValueAxis.valueMin = max(0.0, min(ys) - 0.5)
    lp.yValueAxis.valueMax = max(ys) + 0.5
    lp.yValueAxis.labelTextFormat = "%.2f"
    dwg.add(lp)
    return dwg


def build_patient_pdf(meta, rows, *, days, roc, stage_text, status,
                      cap_uri=None, ovl_uri=None):
    """
    meta        : {patient_id, name, dob, gender, wound_site, notes, age}
    rows        : capture rows (oldest->newest) each with stamp/wound_pct/foot_pct
    days        : window currently shown in the dashboard (for the trend + ROC)
    roc         : endpoint rate of change (%/day) over that window, or None
    stage_text  : e.g. "UT Stage C — Ischaemic"
    status      : {"label": "...", "action": "...", "colour": "#.."} — action is
                  LOGISTICS ONLY (already vetted by the caller).
    cap_uri/ovl_uri : latest captured / overlay images as data URIs (optional)
    """
    if not PDF_AVAILABLE:
        raise RuntimeError("reportlab is not installed (pip install reportlab)")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"DFU Report — {meta.get('patient_id','')}")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=18, spaceAfter=2,
                        textColor=colors.HexColor("#1c1c1e"))
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontSize=9,
                         textColor=colors.HexColor("#8e8e93"))
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=10, leading=14)
    el = []

    el.append(Paragraph("DFU Monitoring — Patient Report", h1))
    el.append(Paragraph(
        "Screening aid only — NOT a diagnosis. All findings reviewed by a clinician. "
        f"Generated {datetime.datetime.now():%d %b %Y %H:%M}.", sub))
    el.append(Spacer(1, 8))

    # ---- status banner (logistics-only action) ----
    if status:
        col = colors.HexColor(status.get("colour", "#8e8e93"))
        banner = Table([[Paragraph(
            f"<b>{status.get('label','')}</b> &nbsp;·&nbsp; {status.get('action','')}",
            ParagraphStyle("ban", parent=body, textColor=colors.white))]],
            colWidths=[doc.width])
        banner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), col),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("ROUNDEDCORNERS", [6, 6, 6, 6])]))
        el.append(banner)
        el.append(Spacer(1, 10))

    # ---- patient details ----
    age = meta.get("age")
    gender = {"m": "Male", "f": "Female"}.get(
        (meta.get("gender") or "").lower(), meta.get("gender") or "—")
    info = [
        ["Patient ID", meta.get("patient_id", "—"),
         "Name", meta.get("name") or "—"],
        ["Date of birth", meta.get("dob") or "—",
         "Age", str(age) if age is not None else "—"],
        ["Sex", gender, "Wound site", meta.get("wound_site") or "—"],
    ]
    t = Table(info, colWidths=[doc.width * x for x in (0.18, 0.32, 0.18, 0.32)])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#8e8e93")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#8e8e93")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#e5e5ea"))]))
    el.append(t)
    if meta.get("notes"):
        el.append(Spacer(1, 4))
        el.append(Paragraph(f"<b>Notes:</b> {meta['notes']}", body))
    el.append(Spacer(1, 12))

    # ---- latest assessment metrics ----
    latest = rows[-1] if rows else {}
    def _pct(v):
        return "—" if v is None else f"{v:.2f}%"
    roc_txt = "—" if roc is None else f"{roc:+.2f}%/day"
    metrics = [["Current stage", "Wound area (avg)", f"Rate of change ({days}d)", "Sessions"],
               [stage_text, _pct(latest.get("wound_pct")), roc_txt, str(len(rows))]]
    mt = Table(metrics, colWidths=[doc.width / 4] * 4)
    mt.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#8e8e93")),
        ("FONTSIZE", (0, 1), (-1, 1), 12),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, colors.HexColor("#e5e5ea")),
        ("LINEBELOW", (0, 1), (-1, 1), 0.6, colors.HexColor("#e5e5ea")),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8)]))
    el.append(mt)
    el.append(Spacer(1, 12))

    # ---- trend chart over the visible window ----
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    pts = []
    for r in rows:
        try:
            d = datetime.datetime.strptime(r.get("stamp", ""), "%Y%m%d_%H%M%S")
        except (ValueError, TypeError):
            continue
        if d >= cutoff and r.get("wound_pct") is not None:
            pts.append((d, r["wound_pct"]))
    el.append(Paragraph(f"<b>Wound area trend — past {days} days</b>", body))
    el.append(Spacer(1, 4))
    dwg = _trend_drawing(pts, doc.width, 150)
    if dwg is not None:
        el.append(dwg)
    else:
        el.append(Paragraph("Not enough readings in this window to plot a trend.",
                            sub))
    el.append(Spacer(1, 12))

    # ---- latest images ----
    cap = _img_flowable(cap_uri, doc.width / 2 - 6, 150)
    ovl = _img_flowable(ovl_uri, doc.width / 2 - 6, 150)
    if cap or ovl:
        el.append(Paragraph("<b>Latest session</b>", body))
        el.append(Spacer(1, 4))
        cell_cap = [Paragraph("Captured", sub), cap or Paragraph("—", sub)]
        cell_ovl = [Paragraph("AI overlay", sub), ovl or Paragraph("—", sub)]
        it = Table([[cell_cap, cell_ovl]], colWidths=[doc.width / 2] * 2)
        it.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        el.append(it)

    doc.build(el)
    return buf.getvalue()
