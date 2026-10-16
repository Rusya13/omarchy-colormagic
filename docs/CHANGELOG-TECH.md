# Technical changelog

From git history. Content and SEO changes do not apply to this project (no site).

- 2026-10-08: CI workflow compiles `backend` Python files; permissions set to `contents: read` (FL-685).
- 2026-10-08: tests for `cm_generate` against a fake API (FL-686).
- 2026-10-01: `cm_login.py` added to the repo (it existed only in the installed copy). Note: the root-level file is the older version.
- 2026-09-14: Google client secret sent at code exchange (the OAuth client requires it); sign-in hardening (single stdout document, lenient parse, longer error display); QtQuick.Controls import fix.
- 2026-09-14: initial commit: generate, upscale, edit.
