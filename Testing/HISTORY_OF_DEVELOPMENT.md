# History of Development

This document explains, step by step, how the DFU Monitor codebase came to be — for someone new to
the project. It is a story of decisions and corrections, not a timeline; there are no dates, only the
order in which problems appeared and how each was solved. Where something did not work, that is said
plainly, along with what was written to fix it.

## The starting point

The project began as a messy but working prototype: a single script that could take a photo and run
an early AI model on it, enough to prove the idea but not structured for a real device or clinic. Two
goals shaped everything after: the device had to run on cheap, low-power hardware in rural, low-
connectivity settings, and the medical staff needed a separate, trustworthy way to review results.
That split — a **device** app and a **desktop** app, with an **AI package** in between — became the
backbone of the repository.

## Splitting the AI into a contract

The trained-AI work was deliberately separated from the application code into a self-contained
inference package with a fixed "contract": give it an image path, get back a severity level and a
wound-size measurement as plain data. This let the application code treat the AI as a black box and
let the AI evolve independently. The first version of the package wrote its result overlay using
matplotlib, which was heavy. A later version replaced that with a lightweight Pillow-only overlay,
added a cropped close-up of just the wound for clinicians, and tuned the segmentation to over-detect
less. When that newer package was proven equivalent, the application was pointed at it and the old
package was deleted to avoid confusion.

**The version-lock trap.** The models only load under the exact TensorFlow/Keras version that saved
them; a mismatch produces a misleading "expected N variables, received 0" error that looks like a
broken model but is really a version skew. The fix was to pin the version, ship a `check_env.py` that
loads both models and prints PASS/FAIL, and document the trap prominently so it is never re-diagnosed
from scratch.

## Building the device app

The device app was built as a small state machine around a kiosk touchscreen. Several hardware
realities forced design choices:

- **Tkinter and macOS.** Tkinter must own the main thread, and on macOS doing capture work on that
  thread freezes or crashes the UI. The fix was to run all capture/AI work in a worker thread and push
  updates back to the UI through a thread-safe queue.
- **The camera can't be shared.** The live preview (`rpicam-vid`) and the still capture (`picamera2`)
  cannot both hold the camera at once. The fix was to stop the preview whenever the app leaves the
  live screen, take the still, then restart the preview — which is exactly why capture and analysis
  are separate states.
- **Raspberry Pi 5 GPIO.** The classic `RPi.GPIO` library does not work on the Pi 5's new GPIO chip;
  the code uses `gpiozero` on the `lgpio` backend instead, and degrades gracefully to the on-screen
  button when no GPIO is present (so the same code runs on a laptop).
- **The WS2812 light.** The common PWM/DMA LED library also does not work on the Pi 5; that driver was
  isolated behind one small class so only it needs changing, with a note that a Pi-5 SPI driver is
  required. This remains an open hardware to-do.
- **One capture at a time.** Long presses and bounced buttons caused duplicate captures. A shared
  lockout guard makes both the physical and on-screen buttons honour a single-capture window.
- **Preview lag on a 2 GB Pi.** The first live preview was too slow. A ladder of fixes followed:
  lower resolution and bitrate, reuse one image buffer instead of allocating per frame, skip frames
  that haven't changed, decode JPEGs at reduced scale, and draw framing guides once instead of every
  frame. These are all switchable knobs so the device can be tuned on real hardware.

## Going to the cloud without paying for storage

The plan was to upload images, but the free Firebase tier no longer includes file storage. Rather than
require a paid plan, each image is downscaled and JPEG-compressed into a base64 string stored inside
the database document, kept under the per-document size limit, with full-resolution originals left on
the device. Uploads are fire-and-forget, and an offline backlog is flushed when connectivity returns —
and it stops on the first failure rather than hammering a dead link, which suits low-connectivity use.

## Building the desktop app

The desktop dashboard was built in Dash with an Apple-Health-style look. A few decisions stand out:

- **One interface, two backends.** A common data-source interface means the local SQLite backend and
  the Firestore backend are interchangeable; the UI never knows which it is reading.
- **Editable timestamps without breaking links.** Staff need to correct a capture's date/time, but in
  the cloud the document id is a stable key used to find images. The fix was to make the **timestamp a
  field** separate from the document id, so editing it updates the charts without moving the document.
- **Colour-blind safety.** Every severity colour is paired with a letter and a marker shape, so meaning
  survives without colour.
- **Failing soft.** The detail and image views are wrapped so a data error logs and shows a gentle
  message instead of crashing the page.

## The big rework: from single photos to sessions

The most significant change came from a clinical insight: a single photo is fragile, so the device
should take **several photos in one standardised session** and the AI should average them. This one
idea cascaded through the whole system.

- **Storage** changed from one row per photo to a **session** of N rows sharing a `session_id`, with
  the averaged result denormalised onto each row, and files renamed to the **moment of final AI
  output** so a session's images sort together as 1st/2nd/3rd.
- **The AI wrapper** gained a function that analyses all N images and averages them, including a rule
  for averaging the UT stage (A=1…D=4, mean to the nearest letter, ties rounding up to the more severe
  stage).
- **The device UI was rebuilt** into a longer, guided flow: consent → choose foot angle → per-angle
  instructions → live view with **angle-specific dotted alignment guides** → three captures →
  analysis → an averaged result screen, plus a history list grouped by session. The old centre
  crosshair was replaced by the bucket/end-to-end "snare" guides, and the power button became a reset.
- **A single text file** now holds all on-screen wording (including the trilingual consent), so it can
  be grammar-checked and translated in one place. Chinese text needs a CJK font installed on the Pi —
  a small but easy-to-miss dependency.

## Bringing the desktop up to the session model

The desktop then had to understand sessions too.

- A grouping function turns capture rows into sessions for **both** backends; the Firestore session
  document also carries the individual readings so the per-image spread survives.
- The trend graph became **error bars** — one per session, showing the spread of its photos — with the
  **average** as the stand-out point.
- The measurements list became **collapsible by session**, with the average as the header.
- **What broke: edits didn't reach the graph.** Saving an edited date/time and recomputing the graph
  were triggered by the same click and could race, so the graph sometimes read stale data. The fix was
  to make saving write to the database and then bump a token that the graph listens to, forcing the
  recalculation to happen **after** the write.
- The trend number was given a real rule — it needs two average readings at least seven days apart,
  otherwise it says "too little data" rather than inventing a slope from noise.
- The tissue colours were standardised to **granulation red, slough yellow, necrosis black** across the
  widget and the AI overlay so the picture matches the legend.
- The single wound-site picker became a **multi-point foot picker** with side/bottom views and coloured
  markers. **What didn't work cleanly:** Dash cannot report the exact pixel a user clicks on an image
  without custom JavaScript, so markers snap to a grid of clickable cells — a deliberate trade-off for
  a robust, pure-Dash implementation.
- A **data-stream toggle** was added to switch the whole app between seeded demo data and the live
  database at runtime, implemented as a transparent proxy so no data call had to change.
- **Export looked broken but wasn't.** The PDF export actually worked; the real problems were that the
  report tool wasn't installed in some environments, and that it counted raw photos instead of sessions
  (e.g. "27 captures" for nine visits). It was made session-aware and the setup command now installs
  the report tool.

## Tidying up

Late in the project the old AI package was removed once the new one was proven, with every script and
document reference repointed so nothing broke. The day-to-day commands were unified into a small set —
setup, test, run, clear, seed, and launch — wrapped by a Makefile so the same single command works on a
Mac and on the Pi. A first-time `setup` command was added so a fresh machine can install everything in
one step.

## A note on how it was tested

Much of this was developed in an environment without a display, without TensorFlow, and without the
desktop's UI framework installed, and with no internet access to add them. So the testing strategy
leaned on **logic tests**: the pure functions (stage averaging, session grouping, the seven-day trend
rule, storage round-trips, the capture state machine) were exercised directly, and the user interfaces
were checked by **stubbing** their frameworks and running every screen and callback to catch errors a
syntax check cannot. This proves the logic and wiring; the final visual and on-hardware confirmation —
the live camera, the autofocus, the real models, and the rendered dashboards — is done on the actual
devices.
