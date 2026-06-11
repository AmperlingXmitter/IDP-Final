"""
=============================================================================
 AUDIT LOG  (Testing/desktop/audit.py)
-----------------------------------------------------------------------------
 Records every EDIT made from the desktop app (capture rows + patient info) to
 a small local SQLite file, so there's a reviewable trail of who changed what
 and when. Backend-agnostic: it logs the action regardless of whether the live
 data source is local SQLite or Firebase.

 Deliberately defensive — logging must NEVER crash the app, so every call is
 wrapped and failures are swallowed (with an optional debug print).

 API:
   record(target_type, target_id, action, detail="", backend="", user="staff")
   recent(limit=200)  -> list[dict] newest first
   table_rows(limit)  -> rows shaped for the desktop DataTable
=============================================================================
"""
import datetime
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT_DB = os.environ.get("DFU_AUDIT_DB", os.path.join(HERE, "audit_log.db"))


def _con():
    con = sqlite3.connect(AUDIT_DB)
    con.row_factory = sqlite3.Row
    return con


def _ensure():
    con = _con()
    con.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            user        TEXT,
            backend     TEXT,
            target_type TEXT,      -- 'capture' | 'patient'
            target_id   TEXT,
            action      TEXT,      -- 'edit' | 'create' | 'delete'
            detail      TEXT       -- human-readable change summary
        )
    """)
    con.commit()
    con.close()


def record(target_type, target_id, action, detail="", backend="", user="staff"):
    """Append one audit entry. Never raises."""
    try:
        _ensure()
        con = _con()
        con.execute(
            "INSERT INTO audit_log (ts,user,backend,target_type,target_id,action,detail)"
            " VALUES (?,?,?,?,?,?,?)",
            (datetime.datetime.now().isoformat(timespec="seconds"),
             user, backend, target_type, str(target_id), action, detail))
        con.commit()
        con.close()
    except Exception as e:
        if os.environ.get("DFU_DEBUG"):
            print(f"[audit] could not record: {e}")


def recent(limit=200):
    try:
        _ensure()
        con = _con()
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]
        con.close()
        return rows
    except Exception:
        return []


def table_rows(limit=200):
    """Shaped for the desktop DataTable (When / Who / Type / Target / Change)."""
    out = []
    for r in recent(limit):
        out.append({
            "when":   (r.get("ts") or "").replace("T", "  "),
            "who":    r.get("user") or "",
            "type":   r.get("target_type") or "",
            "target": r.get("target_id") or "",
            "action": r.get("action") or "",
            "detail": r.get("detail") or "",
        })
    return out


def diff_summary(old, new, fields):
    """Build 'a: x→y; b: u→v' for changed fields only (helper for callers)."""
    parts = []
    for f in fields:
        ov, nv = old.get(f), new.get(f)
        if str(ov) != str(nv):
            parts.append(f"{f}: {ov!r}→{nv!r}")
    return "; ".join(parts)
