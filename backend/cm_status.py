#!/usr/bin/env python3
"""Poll, cancel, download, or locate ColorMagic jobs.

Single-shot by design — the bar panel re-runs it on a timer while a job
is active, so every invocation stays short:

    python3 cm_status.py --kind generation --id <id> [--download [DIR]]
    python3 cm_status.py --kind upscale --id <id> --cancel
    python3 cm_status.py --latest [--dir DIR]

With --download and a succeeded job, result images are saved to DIR
(default: output_dir from config) and their local paths are included as
"files". Prints one JSON document, e.g.:

    {"ok": true, "id": ..., "kind": ..., "status": "processing",
     "error": null, "files": []}
"""
import argparse
import json
import os
import time
import urllib.parse

from colormagic_common import (
    TERMINAL_STATES,
    api_request,
    download_file,
    err_exit,
    friendly_error,
    load_config,
    ok_exit,
    output_dir,
    require_auth,
)

KINDS = ("generation", "upscale")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def show_job(cfg, kind, job_id):
    path = "/api/v1/%ss/%s" % (kind, job_id)
    return api_request(cfg, "GET", path, timeout=20)


def cancel_job(cfg, kind, job_id):
    path = "/api/v1/%ss/%s/cancel" % (kind, job_id)
    return api_request(cfg, "POST", path, {}, timeout=20)


def result_urls(doc):
    result = doc.get("result") or {}
    urls = []
    for item in result.get("data") or []:
        url = (item or {}).get("url")
        if url:
            urls.append(url)
    return urls


def download_results(cfg, kind, doc, dest_dir):
    files = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for i, url in enumerate(result_urls(doc)):
        parsed = urllib.parse.urlparse(url)
        ext = os.path.splitext(parsed.path)[1].lower() or ".webp"
        name = "colormagic-%s-%s-%s-%d%s" % (
            kind, doc.get("id", "job"), stamp, i, ext)
        dest = os.path.join(dest_dir, name)
        download_file(url, dest)
        files.append(dest)
    return files


def latest_image(search_dir):
    newest = (None, -1.0)
    for root, _dirs, names in os.walk(search_dir):
        for name in names:
            if not name.lower().endswith(IMAGE_EXTS):
                continue
            path = os.path.join(root, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime > newest[1]:
                newest = (path, mtime)
    return newest[0]


def summarize(doc, kind, files):
    return {
        "id": doc.get("id"),
        "kind": kind,
        "status": doc.get("status") or "unknown",
        "error": doc.get("error"),
        "latency": doc.get("latency"),
        "request": doc.get("request"),
        "result_urls": result_urls(doc),
        "files": files,
        "done": (doc.get("status") in TERMINAL_STATES),
    }


def main():
    ap = argparse.ArgumentParser(description="Inspect ColorMagic jobs.")
    ap.add_argument("--kind", choices=KINDS,
                    help="generation or upscale (required unless --latest).")
    ap.add_argument("--id", default=None, help="Job id.")
    ap.add_argument("--download", nargs="?", const="", default=None,
                    metavar="DIR",
                    help="Download result images (default: output dir).")
    ap.add_argument("--cancel", action="store_true",
                    help="Cancel a queued/processing job.")
    ap.add_argument("--latest", action="store_true",
                    help="Print the newest image in the output dir.")
    ap.add_argument("--dir", default=None,
                    help="Directory for --download/--latest (default: config).")
    args = ap.parse_args()

    cfg = load_config()
    if args.download:
        dest_dir = os.path.expanduser(args.download)
    elif args.dir:
        dest_dir = os.path.expanduser(args.dir)
    else:
        dest_dir = output_dir(cfg)

    if args.latest:
        path = latest_image(dest_dir) if os.path.isdir(dest_dir) else None
        if not path:
            err_exit("No images found in %s yet." % dest_dir,
                     code="not_found")
        ok_exit(path=path)
        return

    if not args.kind or not args.id:
        err_exit("--kind and --id are required (or use --latest).",
                 code="bad_request")

    auth_err = require_auth(cfg)
    if auth_err:
        print(json.dumps(auth_err))
        return

    try:
        if args.cancel:
            doc = cancel_job(cfg, args.kind, args.id)
        else:
            doc = show_job(cfg, args.kind, args.id)
    except Exception as e:  # noqa: BLE001 — surfaced as JSON
        code, message = friendly_error(e)
        err_exit(message, code=code)

    files = []
    if args.download is not None and doc.get("status") == "succeeded":
        try:
            files = download_results(cfg, args.kind, doc, dest_dir or ".")
        except Exception as e:  # noqa: BLE001 — surfaced as JSON
            err_exit("Job succeeded but download failed: %s" % e,
                     code="download_failed",
                     **summarize(doc, args.kind, []))

    payload = summarize(doc, args.kind, files)
    ok_exit(**payload)


if __name__ == "__main__":
    main()
