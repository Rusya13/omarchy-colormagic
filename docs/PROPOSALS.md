# Proposals

| # | Item | Gain | Effort | Risk |
|---|---|---|---|---|
| 1 | Delete root `cm_login.py` (stale copy of `backend/cm_login.py`) | One source of truth; no one runs the version that fails at exchange | 5 min | Low; check nothing in the installed copy points at it |
| 2 | Install the plugin as a symlink to this repo (projects.toml says it is not installed here as of 2026-10-08) | Edits take effect; matches rus.audio and rus.tray | 5 min | Low (rus to run `omarchy plugin add`) |
| 3 | Actions: checkout v4 to v7, setup-python v5 to latest | Current versions | 10 min | Low; majors, so not done here |
| 4 | Run the unit tests in CI (only compile runs now) | Catches regressions | 10 min | Low |
| 5 | Tests for `cm_upscale.py` and `cm_status.py` | Only `cm_generate` is tested | 1 to 2 h | Low |
| 6 | Confirm the "deploy the upscale fix" README note is still needed in `colormagic-api` | Removes a stale prerequisite | 10 min | Low |
| 7 | Pin a min Omarchy version in the manifest if the plugin API supports it | Clear errors | 15 min | Low |

No stack change: stdlib Python and QML is the right size for this plugin.
