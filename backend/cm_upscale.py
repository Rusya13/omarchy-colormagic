#!/usr/bin/env python3
"""Submit an image upscale.

Usage:
    python3 cm_upscale.py --image in.png [--model real-esrgan]
        [--factor 2] [--prompt "..."] [--upscale-prompt "..."]
        [--output-format webp]

Models: real-esrgan (fast, 2x/4x), swinir (sharp, 2x/4x),
clarity (creative, 2x only), ccsr (restore, 2x only).

NOTE: the deployed API had a bug rejecting uploads larger than ~128KB
with HTTP 500 (fixed in colormagic-api, needs `npm run deploy`). If a
large upscale 500s, deploy the API fix and retry.

Prints {"ok": true, "id": ..., "kind": "upscale", "status": "queued"}.
Poll with cm_status.py --kind upscale --id <id>.
"""
import argparse
import json
import os

from colormagic_common import (
    api_upload,
    err_exit,
    friendly_error,
    load_config,
    ok_exit,
    require_auth,
)

UPSCALE_MODELS = ("real-esrgan", "swinir", "clarity", "ccsr")
FOUR_X_MODELS = ("real-esrgan", "swinir")


def main():
    ap = argparse.ArgumentParser(description="Submit a ColorMagic upscale.")
    ap.add_argument("--image", required=True, help="Image file to upscale.")
    ap.add_argument("--model", default="real-esrgan", choices=UPSCALE_MODELS)
    ap.add_argument("--factor", type=int, default=2, choices=(2, 4))
    ap.add_argument("--prompt", default=None, help="Original prompt (context).")
    ap.add_argument("--upscale-prompt", default=None,
                    help="Extra prompt for creative models (clarity/ccsr).")
    ap.add_argument("--output-format", default="webp",
                    choices=["webp", "png", "jpeg"])
    args = ap.parse_args()

    if args.factor == 4 and args.model not in FOUR_X_MODELS:
        err_exit("Model '%s' supports 2x only; use real-esrgan or swinir "
                 "for 4x." % args.model,
                 code="bad_request")
    if not os.path.isfile(args.image):
        err_exit("Image not found: %s" % args.image)

    cfg = load_config()
    auth_err = require_auth(cfg)
    if auth_err:
        print(json.dumps(auth_err))
        return

    fields = {
        "output_format": args.output_format,
        "upscale_type": "native",
        "upscale_model": args.model,
        "upscale_factor": str(args.factor),
    }
    if args.prompt:
        fields["prompt"] = args.prompt
    if args.upscale_prompt:
        fields["upscale_prompt"] = args.upscale_prompt

    try:
        doc = api_upload(cfg, "/api/v1/upscales", fields, "image",
                         args.image, timeout=120)
    except Exception as e:  # noqa: BLE001 — surfaced as JSON
        code, message = friendly_error(e)
        extra = {}
        if "500" in str(e) and os.path.getsize(args.image) > 128 * 1024:
            extra["hint"] = ("Large-upload 500s mean the API-side upscale "
                             "fix is not deployed yet (colormagic-api: "
                             "npm run deploy). Try a smaller image meanwhile.")
        payload = getattr(e, "payload", None)
        if isinstance(payload, dict) and payload.get("activeRequest"):
            extra["active_request"] = payload["activeRequest"]
        err_exit(message, code=code, **extra)

    ok_exit(id=doc.get("id"), kind="upscale",
            status=doc.get("status") or "queued")


if __name__ == "__main__":
    main()
