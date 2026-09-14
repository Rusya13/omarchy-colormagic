#!/usr/bin/env python3
"""Shared helpers for omarchy-colormagic backends.

All scripts talk to the ColorMagic Cloud API (Hono worker on Cloudflare)
with stdlib only, and share one config file:

    ~/.config/omarchy/colormagic.json

Config keys (all optional except auth_token once signed in):

    {
      "auth_token": "Bearer session token from cm_login.py",
      "token_expires_at": "ISO-8601 expiry of the session",
      "device_id": "client-generated device UUID",
      "session_id": "client-generated session UUID",
      "user": {"email": "...", "name": "..."},
      "api_base_url": "https://api.colormagic.app  (override for dev)",
      "desktop_app_key": "desktop.colormagic.app   (override for dev)",
      "output_dir": "~/Pictures/ColorMagic        (download location)"
    }

Environment overrides: COLORMAGIC_API_TOKEN, COLORMAGIC_API_BASE_URL,
COLORMAGIC_DESKTOP_KEY, COLORMAGIC_OUTPUT_DIR.
"""
import json
import os
import sys
import urllib.error
import urllib.request

CONFIG_PATH = os.path.expanduser("~/.config/omarchy/colormagic.json")

DEFAULT_API_BASE_URL = "https://api.colormagic.app"
DEFAULT_DESKTOP_APP_KEY = "desktop.colormagic.app"
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/Pictures/ColorMagic")

USER_AGENT = "omarchy-colormagic/0.1"

# Terminal states for generation/upscale jobs (see job-processor.ts).
TERMINAL_STATES = ("succeeded", "failed", "cancelled")


def load_config():
    """Return the config dict merged with environment overrides."""
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f) or {}
        except Exception:
            pass
    if os.environ.get("COLORMAGIC_API_TOKEN"):
        cfg["auth_token"] = os.environ["COLORMAGIC_API_TOKEN"]
    if os.environ.get("COLORMAGIC_API_BASE_URL"):
        cfg["api_base_url"] = os.environ["COLORMAGIC_API_BASE_URL"]
    if os.environ.get("COLORMAGIC_DESKTOP_KEY"):
        cfg["desktop_app_key"] = os.environ["COLORMAGIC_DESKTOP_KEY"]
    if os.environ.get("COLORMAGIC_OUTPUT_DIR"):
        cfg["output_dir"] = os.environ["COLORMAGIC_OUTPUT_DIR"]
    return cfg


def save_config(cfg):
    """Persist config (auth token etc.) with user-only permissions."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)


def api_base(cfg):
    return str(cfg.get("api_base_url") or DEFAULT_API_BASE_URL).rstrip("/")


def desktop_key(cfg):
    return str(cfg.get("desktop_app_key") or DEFAULT_DESKTOP_APP_KEY)


def output_dir(cfg):
    return os.path.expanduser(
        str(cfg.get("output_dir") or DEFAULT_OUTPUT_DIR)
    )


class ApiError(Exception):
    def __init__(self, message, status=None, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def _headers(cfg, content_type=None):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "X-Desktop-Key": desktop_key(cfg),
    }
    if cfg.get("auth_token"):
        headers["Authorization"] = "Bearer %s" % cfg["auth_token"]
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _raise_for_status(url, status, body):
    try:
        payload = json.loads(body.decode("utf-8")) if body else None
    except Exception:
        payload = None
    if isinstance(payload, dict):
        message = (
            payload.get("message") or payload.get("error") or "request failed"
        )
    else:
        message = "request failed"
    raise ApiError("%s (HTTP %d %s)" % (message, status, url),
                   status=status, payload=payload)


def api_request(cfg, method, path, body=None, timeout=30):
    """Send a JSON request. Returns the decoded JSON document.

    Raises ApiError on HTTP errors (including 401/409/422/500).
    """
    url = api_base(cfg) + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers=_headers(cfg, "application/json" if data else None),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        _raise_for_status(url, e.code, e.read())
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def api_upload(cfg, path, fields, file_field, file_path, timeout=120):
    """Multipart file upload. fields maps name->str value.

    Returns the decoded JSON document. Raises ApiError on HTTP errors.
    """
    url = api_base(cfg) + path
    boundary = "----omarchy-colormagic-%d" % os.getpid()
    chunks = []
    for name, value in fields.items():
        if value is None:
            continue
        chunks.append(("--%s\r\n" % boundary).encode())
        chunks.append(
            ('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode()
        )
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    filename = os.path.basename(file_path)
    mime = _guess_mime(file_path)
    chunks.append(("--%s\r\n" % boundary).encode())
    chunks.append(
        ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
         % (file_field, filename)).encode()
    )
    chunks.append(("Content-Type: %s\r\n\r\n" % mime).encode())
    chunks.append(file_bytes)
    chunks.append(b"\r\n")
    chunks.append(("--%s--\r\n" % boundary).encode())
    data = b"".join(chunks)
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers=_headers(cfg, "multipart/form-data; boundary=%s" % boundary),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        _raise_for_status(url, e.code, e.read())
    return json.loads(raw.decode("utf-8")) if raw else {}


def download_file(url, dest_path, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
    return dest_path


def _guess_mime(path):
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "application/octet-stream")


def require_auth(cfg):
    """Return an error envelope dict when signed in state is missing."""
    if not cfg.get("auth_token"):
        return {
            "error": "not_signed_in",
            "message": "Not signed in. Run backend/cm_login.py once "
                       "(or press Sign in) to connect your Google account.",
        }
    return None


def friendly_error(e):
    """Map ApiError to a short user-facing message + machine code."""
    if isinstance(e, ApiError) and e.status == 401:
        return ("session_expired",
                "Session expired or revoked. Sign in again "
                "(backend/cm_login.py) to reconnect.")
    if isinstance(e, ApiError) and e.status == 409:
        active = None
        if isinstance(e.payload, dict):
            active = e.payload.get("activeRequest")
        return ("job_conflict",
                "Another job is already running. Wait for it to finish "
                "or cancel it first. (active: %s)" % (active or "unknown"))
    return ("failed", str(e))


def err_exit(message, code="failed", **extra):
    payload = {"error": code, "message": message}
    payload.update(extra)
    print(json.dumps(payload))
    sys.exit(0)


def ok_exit(**payload):
    payload.setdefault("ok", True)
    print(json.dumps(payload))
    sys.exit(0)
