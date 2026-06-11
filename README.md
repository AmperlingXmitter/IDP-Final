# DFU Remote Monitoring Device

A Raspberry Pi 5 captures photos of a diabetic foot ulcer (DFU), an on-device AI grades
severity (UT stage) and wound size, results sync to Firebase, and medical staff review
them in a desktop dashboard. **Screening aid only — not a diagnosis.**

## 🤖 For AI assistants (Claude / ChatGPT): read this first

**Start with [`Testing/PROJECT_README.md`](Testing/PROJECT_README.md).** It is the canonical,
self-contained, token-efficient overview of the entire system — it is normally the ONLY file
you need to understand the repo. Read the rest only when working on a specific area:

| Read | When you need |
|------|----------------|
| **`Testing/PROJECT_README.md`** ← START HERE | The whole system: architecture, the SESSION model (N images), AI contract, schemas, single commands, both apps. |
| `new_deployment/README.md` | The AI inference package — the input→output contract (TF 2.15.1 version-lock). |
| `Testing/device/DEVICE_README.md` | The Raspberry Pi capture app (flow, flags, files). |
| `Testing/desktop/DESKTOP_README.md` | The staff dashboard (data sources, patient page, widgets). |
| `Testing/OPERATIONAL_MANUAL.md` | How end users (patients + staff) actually operate it. |
| `Testing/HISTORY_OF_DEVELOPMENT.md` | Why the code is the way it is — what was tried, broke, and fixed. |

**Key facts to anchor on:** the unit of measurement is a **session = N images** (default 3),
analysed together and averaged. The AI lives in **`new_deployment/`** (the only package).
Device code is `Testing/device/`; desktop code is `Testing/desktop/`. Single commands from
`Testing/`: `make setup | test | run | clear | seed | app`.

**Safety rule that must never be broken:** any patient-facing "suggested action" in the
desktop app may state **logistics only** ("visit clinic", "contact the doctor", "continue
routine monitoring") — never clinical or treatment advice. Centralised in `app._healing_status()`.
