#!/usr/bin/env python3
"""Fetch the ColorMagic model catalog.

Usage:
    python3 cm_models.py

Prints {"ok": true, "models": [{id, output, sizes, supported_params}]}
suitable for populating the panel's model/size dropdowns.
"""
import json

from colormagic_common import (
    api_request,
    err_exit,
    friendly_error,
    load_config,
    ok_exit,
    require_auth,
)


def main():
    cfg = load_config()
    auth_err = require_auth(cfg)
    if auth_err:
        print(json.dumps(auth_err))
        return
    try:
        doc = api_request(cfg, "GET", "/api/v1/models", timeout=20)
        try:
            session = api_request(cfg, "GET", "/api/v1/auth/session",
                                  timeout=20)
        except Exception:
            session = {}
    except Exception as e:  # noqa: BLE001 — surfaced as JSON
        code, message = friendly_error(e)
        err_exit(message, code=code)
    ok_exit(models=doc.get("data") or [],
            user=(session.get("user") or {}))


if __name__ == "__main__":
    main()
