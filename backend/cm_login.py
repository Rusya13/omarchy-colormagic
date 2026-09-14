#!/usr/bin/env python3
"""One-time Google sign-in for omarchy-colormagic.

Replicates the ColorMagic desktop app's OAuth dance with stdlib only:

1. Starts a loopback callback server on 127.0.0.1 (ephemeral port).
2. Opens the Google consent page in your browser (same public OAuth
   client the desktop app uses, same scopes: openid email profile).
3. Exchanges the returned code (PKCE, no client secret) for an ID token.
4. Calls POST /api/v1/auth/google to mint a 90-day device session.
5. Saves the Bearer token to ~/.config/omarchy/colormagic.json (0600).

Usage:
    python3 cm_login.py [--timeout 180]

Prints one JSON document: {"ok": true, "user": {...}} on success,
{"error": ..., "message": ...} on failure. Safe to run from the bar
panel — the browser step is interactive, the rest is automatic.
"""
import argparse
import base64
import hashlib
import http.server
import json
import os
import queue
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

from colormagic_common import (
    api_base,
    api_request,
    desktop_key,
    err_exit,
    load_config,
    ok_exit,
    save_config,
)

# Public installed-app OAuth client shipped with the ColorMagic desktop app
# (not a secret — it appears in every desktop sign-in URL). Override with
# COLORMAGIC_GOOGLE_CLIENT_ID if the backend allowlist ever changes.
DEFAULT_GOOGLE_CLIENT_ID = (
    "11782290003-vmq7c9facuv8otuldb6d5gumos2ur13q"
    ".apps.googleusercontent.com"
)
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = "openid email profile"

_SUCCESS_PAGE = (
    b"<html><body style='font-family:sans-serif'>"
    b"<h2>Signed in. You can close this tab.</h2>"
    b"<p>Return to your desktop to use ColorMagic.</p>"
    b"</body></html>"
)


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def post_form(url, fields, timeout=30):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode())
        except Exception:
            detail = {}
        desc = detail.get("error_description") or detail.get("error")
        raise RuntimeError("Google request failed: %s" % (desc or e.code))


def make_handler(params_queue):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/oauth2/callback":
                self.send_response(404)
                self.end_headers()
                return
            params_queue.put(urllib.parse.parse_qs(parsed.query))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_SUCCESS_PAGE)

        def log_message(self, *args):
            pass

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Sign omarchy-colormagic in.")
    ap.add_argument("--timeout", type=int, default=180,
                    help="Seconds to wait for the browser callback.")
    args = ap.parse_args()

    cfg = load_config()
    client_id = (
        os.environ.get("COLORMAGIC_GOOGLE_CLIENT_ID")
        or cfg.get("google_client_id")
        or DEFAULT_GOOGLE_CLIENT_ID
    )
    # The ColorMagic OAuth client enforces a secret at code-exchange time
    # (same as the desktop app). Keep it in the 0600 config file or export
    # COLORMAGIC_GOOGLE_CLIENT_SECRET. Never commit it.
    client_secret = (
        os.environ.get("COLORMAGIC_GOOGLE_CLIENT_SECRET")
        or cfg.get("google_client_secret")
    )

    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = _b64url(secrets.token_bytes(16))

    params_queue = queue.Queue()
    try:
        server = http.server.HTTPServer(
            ("127.0.0.1", 0), make_handler(params_queue))
    except OSError as e:
        err_exit("Could not start the local sign-in callback on "
                 "127.0.0.1: %s" % e)
    redirect_uri = "http://127.0.0.1:%d/oauth2/callback" % (
        server.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()

    auth_url = "%s?%s" % (GOOGLE_AUTH_URL, urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }))
    try:
        opened = webbrowser.open(auth_url)
    except Exception:
        opened = False
    if not opened:
        # STDERR only: stdout must stay a single JSON document.
        print("Sign-in browser did not open automatically. "
              "Open this URL manually:\n%s" % auth_url,
              file=sys.stderr)

    try:
        params = params_queue.get(timeout=args.timeout)
    except queue.Empty:
        err_exit("Timed out after %ds with no answer from the browser. "
                 "Complete Google consent, wait for the 'Signed in' page, "
                 "then press Sign in again." % args.timeout,
                 code="login_timeout")
    finally:
        server.shutdown()

    if "error" in params:
        err_exit("Google sign-in refused: %s"
                 % params.get("error", ["unknown"])[0])
    code = (params.get("code") or [""])[0]
    if not code:
        err_exit("Google callback did not include a code.")

    try:
        exchange_fields = {
            "client_id": client_id,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        if client_secret:
            exchange_fields["client_secret"] = client_secret
        token = post_form(GOOGLE_TOKEN_URL, exchange_fields)
    except RuntimeError as e:
        err_exit(str(e))
    id_token = (token.get("id_token") or "").strip()
    if not id_token:
        err_exit("Google did not return an ID token.")

    # Mint a ColorMagic device session (90-day Bearer).
    device_id = cfg.get("device_id") or str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    try:
        linked = api_request(cfg, "POST", "/api/v1/auth/google", {
            "device_id": device_id,
            "session_id": session_id,
            "id_token": id_token,
        }, timeout=30)
    except Exception as e:  # noqa: BLE001 — surfaced as JSON
        err_exit("ColorMagic sign-in failed: %s" % e)

    auth = linked.get("auth") or {}
    bearer = (auth.get("token") or "").strip()
    if not bearer:
        err_exit("ColorMagic did not return a session token.")

    user = linked.get("user") or {}
    cfg.update({
        "auth_token": bearer,
        "token_expires_at": auth.get("expiresAt"),
        "device_id": device_id,
        "session_id": session_id,
        "user": {"email": user.get("email"), "name": user.get("name")},
        "api_base_url": api_base(cfg),
        "desktop_app_key": desktop_key(cfg),
        "google_client_id": client_id,
    })
    if client_secret:
        cfg["google_client_secret"] = client_secret
    save_config(cfg)
    ok_exit(user={"email": user.get("email"), "name": user.get("name")},
            expires_at=auth.get("expiresAt"))


if __name__ == "__main__":
    main()
