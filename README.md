# omarchy-colormagic

A native Omarchy Quattro bar plugin for the **ColorMagic API**
(`api.colormagic.app`) — generate images, upscale photos or screenshots,
and edit pictures without leaving your desktop.

The bar icon opens a popup panel with two tabs:

- **Generate** — text-to-image, or image edit when you attach an input
  picture (strength slider controls how much changes).
- **Upscale** — upscale any file, the latest generated image, or a fresh
  screen-region screenshot (2x/4x, fast/sharp/creative/restore models).

Jobs run in the background: the panel polls until they finish, downloads
results to your output folder (default `~/Pictures/ColorMagic`, shared
with the ColorMagic desktop gallery), shows a thumbnail with
Open / Upscale-this / Folder actions, and sends a clickable desktop
notification on completion.

This project is not affiliated with Omarchy. It talks to the ColorMagic
API service (see `../colormagic-api`).

## Architecture

The plugin keeps the UI inside the shell and all network work in small
Python helpers that the shell runs on demand (stdlib only — no
dependencies, no services):

- `Panel.qml` runs inside the Omarchy shell: bar icon, popup, tabs,
  polling timer, completion notifications.
- `backend/cm_login.py` — one-time Google sign-in (same loopback OAuth
  flow as the desktop app). Mints a 90-day device session and stores the
  Bearer token in `~/.config/omarchy/colormagic.json` (mode 0600).
- `backend/cm_models.py` — model catalog + signed-in user (panel dropdowns).
- `backend/cm_generate.py` — submit text-to-image or image-edit jobs.
- `backend/cm_upscale.py` — submit upscale jobs (multipart upload).
- `backend/cm_status.py` — poll/cancel jobs, download results, locate the
  latest output image.
- `backend/colormagic_common.py` — shared config/API helpers.
- `Quickshell.Io.Process` bridges QML and the scripts: each script prints
  one JSON document; QML parses stdout and feeds the UI.

Everything runs as your user. The API needs `X-Desktop-Key` plus the
Bearer session token — both handled by the backends.

## Install

```sh
omarchy plugin add https://github.com/Rusya13/omarchy-colormagic.git --enable
```

Then open the panel from the bar and press **Sign in** (or run the
helper directly once):

```sh
~/.config/omarchy/plugins/rus.colormagic/backend/cm_login.py
```

This opens Google in your browser; approve, and the session is saved to
`~/.config/omarchy/colormagic.json`. Sessions last 90 days — sign in
again when the panel reports an expired session.

### Prerequisite: deploy the upscale fix

Upscales of images larger than ~128KB return HTTP 500 from the API until
the `bytesToBase64` fix in `colormagic-api` is deployed:

```sh
cd ../colormagic-api && npm run deploy
```

(`cm_upscale.py` detects this case and tells you.) Generations and small
upscales work regardless.

## CLI usage

Every backend script is usable from a terminal too:

```sh
cd ~/.config/omarchy/plugins/rus.colormagic/backend

# catalog
python3 cm_models.py

# text-to-image (returns a job id immediately)
python3 cm_generate.py --prompt "a clockwork city, soft light" \
    --model colormagic-image-klein --size 1024x1024

# image edit (img2img)
python3 cm_generate.py --prompt "same street, night rain" \
    --input-image in.png --strength 0.6

# upscale (models: real-esrgan, swinir, clarity, ccsr; clarity/ccsr are 2x only)
python3 cm_upscale.py --image photo.png --model swinir --factor 2

# poll + download on success
python3 cm_status.py --kind generation --id <id> --download
python3 cm_status.py --kind upscale --id <id> --download ~/Pictures

# cancel / latest output
python3 cm_status.py --kind generation --id <id> --cancel
python3 cm_status.py --latest
```

Only one job runs at a time per account (API-side gate). If a submit
returns `job_conflict`, wait for the active job or cancel it first.

## Settings

Configurable from the plugin settings (see `manifest.json`):

| Key | Default | Purpose |
| `apiBaseUrl` | `https://api.colormagic.app` | API endpoint |
| `outputDir` | `~/Pictures/ColorMagic` | Finished-image downloads |
| `pollIntervalSec` | `3` | Job poll cadence |
| `jobTimeoutSec` | `300` | Stop polling after |
| `defaultModel` / `defaultSize` | klein / 1024x1024 | Generate defaults |
| `upscaleModel` / `upscaleFactor` | real-esrgan / 2 | Upscale defaults |
| `notifyOnComplete` / `notifyOnFailure` | true | Notifications |

Auth material can also be supplied via environment
(`COLORMAGIC_API_TOKEN`, `COLORMAGIC_API_BASE_URL`,
`COLORMAGIC_DESKTOP_KEY`, `COLORMAGIC_OUTPUT_DIR`,
`COLORMAGIC_GOOGLE_CLIENT_ID`), which override the config file.

## Omarchy theme support

The panel follows Omarchy's shared theme API: popup background/text,
accent, urgent and muted colors come from the active theme, while fills,
borders, corner radii and font sizing use the shell's `Style` tokens.
Switching themes with `omarchy theme set <name>` updates the plugin
automatically, including light themes.
