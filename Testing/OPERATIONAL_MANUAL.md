# DFU Monitor — Operational Manual

A simple guide for using the Diabetic Foot Ulcer (DFU) Monitor. There are two parts:

- **Part 1 — Using the device** (for the person taking the photos: a patient, carer, or clinic helper).
- **Part 2 — Using the desktop app** (for medical staff reviewing results).

> **Important:** This device is a **screening aid only — it is not a diagnosis.** Every result is
> reviewed by a doctor. If you are worried about a wound, contact your care team.

---

# Part 1 — Using the device

The device is a small screen with a camera and one button. You take **three photos** of the foot
in one go; the device then analyses them and shows a result.

## What you need
- The DFU Monitor, powered on.
- Good, even lighting on the foot.
- The foot clean and dry, with the ulcer visible.

## Step by step

**1. Consent screen.**
When the device turns on it shows a consent message in English, Malay, and Chinese. It explains that
the device photographs your foot to help staff monitor a diabetic foot ulcer, that your data is
protected under Malaysia's Personal Data Protection Act 2010 (PDPA), and that this is screening only.
**Press the button once** (or tap "Agree & Continue") to continue.

**2. Choose the foot angle.**
Pick which part of the foot has the ulcer:
- **Side of foot** — the ulcer is on the side.
- **Bottom of foot (sole)** — the ulcer is underneath.

Each option shows a small foot picture with a red dot as an example. Tap your choice (it highlights),
then press **Confirm**.

**3. Read the instructions.**
The next screens show how to hold and line up the foot for your chosen angle, with a picture of what
the camera should see. Use the **◀ ▶** arrows to move through the pages. On the last page press
**I Understand**.

**4. Line up the foot and take three photos.**
You now see the live camera view with **dotted guide lines (snares)**:
- **Side view:** a bucket shape — rest the flat sole on the bottom line, with the toes and heel
  against the two short side lines.
- **Bottom view:** two tall lines — put the toes against one line and the heel against the other.

Hold the camera **straight above / square to the foot**, keep still, and press the button (or tap
**Capture**). The button counts up: **Capture 1/3 → 2/3 → 3/3**. After each press the screen briefly
shows "Capturing Image…". Re-line the foot the same way between photos.

**5. Wait for the analysis.**
After the third photo the screen shows **"AI Analysing Images…"** while it studies all three together.

**6. Read the result.**
The **Results** screen shows the three analysed images (use **◀ ▶** to browse, 1/3 · 2/3 · 3/3) and
the **UT stage** (a letter A–D with a short description and a colour). It does **not** show a wound
percentage — that detail is for staff. Press the button or tap **Done** when finished; the device
returns to the camera ready for the next person.

## Other things on screen
- **Patient ID** (top): set before you start the three photos. It **locks** once the first photo is
  taken so it can't change mid-session.
- **⚡ Flash** (top right): cycles the light off / flash / steady on.
- **🗂 Captured Images** (bottom right): a history list, grouped by visit, showing date, ID, stage,
  and wound size. Tap an entry to view its result again.
- **⟲ Reset** (bottom left): starts over from the consent screen and clears the photo count.
- **◀ Back**: appears on the selection, instructions, and history screens.

## If something goes wrong
- **"Please Retake":** the three photos looked too different from each other (the foot moved or the
  lighting changed). Line the foot up the same way for all three and capture again.
- **Camera view is blank or laggy:** make sure nothing covers the lens; the live view uses a low
  resolution on purpose for smoothness — the saved photos are full quality.
- **Nothing happens when you press the button:** wait a moment — the device ignores extra presses for
  a few seconds after a photo so it never takes duplicates.

## Privacy
Your images and results are only shared with your care team and stored securely. Full-resolution
photos stay on the device; only smaller copies are sent to the secure cloud when the device is online.

---

# Part 2 — Using the desktop app (medical staff)

The desktop app shows every patient's readings for review. Open it with **`make app`** (or
`python run_desktop.py`). It opens in its own window.

## Sign in
Enter the staff **PIN** (default `1234`; change before clinic use). The app is for staff only.

## Choose the data you're viewing
A toggle in the top bar switches between:
- **Seeded** — built-in demo patients (for training/testing).
- **Database** — the live data uploaded by devices.

## Patients overview
Patients appear as cards, **most urgent first**. A card shows name and age, the **UT stage**
(colour + letter), the latest wound size, and a small trend line (or "no trend data" if there aren't
enough readings). A red border and "▲ URGENT" mark patients needing attention (advanced stage, or the
wound growing quickly). Click a card to open the patient.

## The patient page
At the top are three summary widgets:
- **UT stage** — the averaged stage for the most recent visit, with its date and time.
- **Wound bed composition** — the tissue mix, coloured **granulation = red, slough = yellow,
  necrosis = black**, with the capture date and time.
- **Trend** — the change in wound size, comparing the **earliest and latest average readings** shown.
  It needs at least two average readings **seven or more days apart**; otherwise it says
  "Too little data to produce a trend."

Below that:
- **Wound area trend graph** — each visit is one point (the average) with an **error bar** showing the
  spread of that visit's three photos. Use the "Past N days" box to change the window.
- **Measurements** — a collapsible list, one row per visit. Click a row to expand it. Inside you can
  correct the **date/time** and **foot angle** (these apply to all three photos of that visit) and the
  per-photo **level / wound %**. Press **💾 Save edits** — the graph and widgets recalculate.
- **Images** — switch between **Selected Capture** (the visit you picked) and **Graph Selection**
  (compares the earliest vs latest average reading, each labelled with its date and time).

## Patient details and wound markers
Open a patient's info box to edit name, date of birth, sex, and notes. The **sex** sets a silhouette
picture (male / female / unspecified). The **foot picker** lets you mark wound positions: choose a
colour (red / yellow / black), pick **side** or **bottom** view, and click the foot to drop markers.
Use **Undo** or **Clear view**, then **Save patient**.

## Reports and history
- **⤓ Export PDF** produces a one-page patient report (stage, trend, latest images). It reads
  "Screening aid only — not a diagnosis" and any suggested action is **logistics only** (e.g. "visit
  clinic"), never treatment advice.
- **🕓 Audit log** (top bar) lists every edit made in the app.

## If something looks wrong
- **"No patients found":** you may be on the wrong data source — try the other toggle, or (for demo
  data) re-create it with `python seed_demo_data.py`.
- **"Image not available":** you're viewing a device's local database from another computer, so the
  image files aren't here. The numbers are still correct; use the cloud/database source to see images.
- **Export says "Install reportlab":** run `make setup` once to install the report tool.
