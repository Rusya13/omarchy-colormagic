"""Request handling of backend/cm_generate.py against a fake local API.

Run: python3 -m unittest discover -s tests -v
"""
import base64
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import colormagic_common  # noqa: E402
import cm_generate  # noqa: E402


class FakeApi:
    """Records requests and replies with a canned (status, payload)."""

    def __init__(self):
        self.requests = []
        self.reply = (200, {"id": "gen-1", "status": "queued"})
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                outer.requests.append({
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": json.loads(raw) if raw else None,
                })
                status, payload = outer.reply
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.addCleanup(self.api.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {"COLORMAGIC_API_BASE_URL": self.api.url,
               "COLORMAGIC_API_TOKEN": "tok-123"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(colormagic_common, "CONFIG_PATH",
                              os.path.join(self.tmp.name, "none.json"))
        p.start()
        self.addCleanup(p.stop)

    def run_cli(self, *argv):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["cm_generate.py", *argv]), \
                contextlib.redirect_stdout(out):
            try:
                cm_generate.main()
            except SystemExit:
                pass
        return json.loads(out.getvalue())

    def test_text_to_image_request_and_result(self):
        res = self.run_cli("--prompt", "a cat")
        self.assertEqual(res, {"ok": True, "id": "gen-1",
                               "kind": "generation", "status": "queued"})
        (req,) = self.api.requests
        self.assertEqual(req["path"], "/api/v1/generations")
        self.assertEqual(req["headers"]["Authorization"], "Bearer tok-123")
        self.assertEqual(req["headers"]["X-Desktop-Key"],
                         "desktop.colormagic.app")
        self.assertEqual(req["body"], {
            "model": "colormagic-image-klein", "prompt": "a cat",
            "size": "1024x1024", "output_format": "webp"})

    def test_optional_parameters_are_sent_only_when_given(self):
        img = os.path.join(self.tmp.name, "in.png")
        with open(img, "wb") as f:
            f.write(b"\x89PNGdata")
        self.run_cli("--prompt", "p", "--input-image", img,
                     "--strength", "0", "--steps", "0", "--cfg-scale", "3.5",
                     "--negative-prompt", "blur", "--model", "m",
                     "--size", "512x512", "--output-format", "png")
        body = self.api.requests[0]["body"]
        self.assertEqual(base64.b64decode(body.pop("input_image")),
                         b"\x89PNGdata")
        # zero strength/steps are real values and must not be dropped
        self.assertEqual(body, {
            "model": "m", "prompt": "p", "size": "512x512",
            "output_format": "png", "strength": 0.0, "steps": 0,
            "cfg_scale": 3.5, "negative_prompt": "blur"})

    def test_missing_input_image_makes_no_request(self):
        res = self.run_cli("--prompt", "p", "--input-image", "/nope/x.png")
        self.assertEqual(res["error"], "failed")
        self.assertIn("/nope/x.png", res["message"])
        self.assertEqual(self.api.requests, [])

    def test_not_signed_in_makes_no_request(self):
        with mock.patch.dict(os.environ):
            del os.environ["COLORMAGIC_API_TOKEN"]
            res = self.run_cli("--prompt", "p")
        self.assertEqual(res["error"], "not_signed_in")
        self.assertEqual(self.api.requests, [])

    def test_status_defaults_to_queued(self):
        self.api.reply = (200, {"id": "g2"})
        self.assertEqual(self.run_cli("--prompt", "p")["status"], "queued")

    def test_401_maps_to_session_expired(self):
        self.api.reply = (401, {"message": "bad token"})
        res = self.run_cli("--prompt", "p")
        self.assertEqual(res["error"], "session_expired")

    def test_409_reports_active_request(self):
        self.api.reply = (409, {"message": "busy", "activeRequest": "gen-0"})
        res = self.run_cli("--prompt", "p")
        self.assertEqual(res["error"], "job_conflict")
        self.assertEqual(res["active_request"], "gen-0")

    def test_other_http_error_surfaces_server_message(self):
        self.api.reply = (500, {"message": "boom"})
        res = self.run_cli("--prompt", "p")
        self.assertEqual(res["error"], "failed")
        self.assertIn("boom", res["message"])
        self.assertNotIn("active_request", res)


if __name__ == "__main__":
    unittest.main()
