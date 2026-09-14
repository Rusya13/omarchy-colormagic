#!/usr/bin/env python3
"""Submit an image generation (text-to-image or image edit).

Edit mode: pass --input-image <file> with an edit prompt. klein/turbo
accept seed images (strength controls how much changes); prune REQUIRES
an input image.

Usage:
    python3 cm_generate.py --prompt "..." [--model colormagic-image-klein]
        [--size 1024x1024] [--input-image in.png] [--strength 0.6]
        [--output-format webp] [--negative-prompt "..."] [--steps N]
        [--cfg-scale N]

Prints {"ok": true, "id": ..., "kind": "generation", "status": "queued"}.
Poll with cm_status.py --kind generation --id <id>.
"""
import argparse
import base64
import json
import os

from colormagic_common import (
    api_request,
    err_exit,
    friendly_error,
    load_config,
    ok_exit,
    require_auth,
)


def file_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def main():
    ap = argparse.ArgumentParser(description="Submit a ColorMagic generation.")
    ap.add_argument("--prompt", required=True, help="Text prompt.")
    ap.add_argument("--model", default="colormagic-image-klein",
                    help="Model id (see cm_models.py).")
    ap.add_argument("--size", default="1024x1024", help="WxH output size.")
    ap.add_argument("--input-image", default=None,
                    help="Image file to edit (img2img).")
    ap.add_argument("--strength", type=float, default=None,
                    help="Edit strength 0..1 (img2img only).")
    ap.add_argument("--output-format", default="webp",
                    choices=["webp", "png", "jpeg"])
    ap.add_argument("--negative-prompt", default=None)
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--cfg-scale", type=float, default=None)
    args = ap.parse_args()

    cfg = load_config()
    auth_err = require_auth(cfg)
    if auth_err:
        print(json.dumps(auth_err))
        return

    body = {
        "model": args.model,
        "prompt": args.prompt,
        "size": args.size,
        "output_format": args.output_format,
    }
    if args.input_image:
        if not os.path.isfile(args.input_image):
            err_exit("Input image not found: %s" % args.input_image)
        body["input_image"] = file_to_base64(args.input_image)
    if args.strength is not None:
        body["strength"] = args.strength
    if args.negative_prompt:
        body["negative_prompt"] = args.negative_prompt
    if args.steps is not None:
        body["steps"] = args.steps
    if args.cfg_scale is not None:
        body["cfg_scale"] = args.cfg_scale

    try:
        doc = api_request(cfg, "POST", "/api/v1/generations", body,
                          timeout=60)
    except Exception as e:  # noqa: BLE001 — surfaced as JSON
        code, message = friendly_error(e)
        active = getattr(e, "payload", None)
        extra = {}
        if isinstance(active, dict) and active.get("activeRequest"):
            extra["active_request"] = active["activeRequest"]
        err_exit(message, code=code, **extra)

    ok_exit(id=doc.get("id"), kind="generation",
            status=doc.get("status") or "queued")


if __name__ == "__main__":
    main()
