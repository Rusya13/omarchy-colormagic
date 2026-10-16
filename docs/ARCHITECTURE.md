# Architecture

A bar plugin for the Omarchy shell. The UI is QML. All network work is done by small Python scripts that print one JSON document each.

## Components
- `Panel.qml`: bar icon, popup, tabs (Generate, Upscale), poll timer, notifications. Runs inside the Omarchy shell.
- `manifest.json`: plugin id `rus.colormagic`, version 0.1.0, one `bar-widget` entry point, default settings.
- `backend/colormagic_common.py`: config loading, HTTP helpers (urllib), multipart upload, errors.
- `backend/cm_login.py`: Google loopback OAuth, then exchanges for a 90-day ColorMagic device session.
- `backend/cm_models.py`: model catalog and the signed-in user.
- `backend/cm_generate.py`: text-to-image and image-edit jobs.
- `backend/cm_upscale.py`: upscale jobs (multipart).
- `backend/cm_status.py`: poll, cancel, download, find latest output.
- `cm_login.py` (repo root): an older copy of `backend/cm_login.py` without the client secret. Not used by the panel. See PROPOSALS.
- `tests/test_cm_generate.py`: tests against a fake local API.

## Data flow
Panel runs a script with `Quickshell.Io.Process`, reads one JSON document from stdout, and updates the UI. A job is submitted, the panel polls `cm_status.py` every `pollIntervalSec`, then downloads the result to `outputDir` and sends a desktop notification.

## External services
- `api.colormagic.app` (repo `colormagic-api`, Cloudflare Worker). Needs the `X-Desktop-Key` header and the Bearer session token. One active job per account (`job_conflict` if a second is sent).
- Google OAuth (sign-in only).

## State and secrets
- `~/.config/omarchy/colormagic.json` (mode 0600): session token, optional Google client secret. Never in the repo.
- Output images in `~/Pictures/ColorMagic` (shared with the ColorMagic desktop app).

## Environment variables (names only)
`COLORMAGIC_API_TOKEN`, `COLORMAGIC_API_BASE_URL`, `COLORMAGIC_DESKTOP_KEY`, `COLORMAGIC_OUTPUT_DIR`, `COLORMAGIC_GOOGLE_CLIENT_ID`, `COLORMAGIC_GOOGLE_CLIENT_SECRET`.
