from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import Any
from urllib.parse import urlparse

from apgar.actions.webhook import sign

SECRET = "0123456789abcdef"
_LOCK = Lock()
_SLACK: list[str] = []
_WEBHOOKS: list[dict[str, Any]] = []


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/slack/received":
            self._json({"messages": list(_SLACK)})
            return
        if path == "/webhook/received":
            self._json({"items": list(_WEBHOOKS)})
            return
        self._json({"ok": False}, status=404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        path = urlparse(self.path).path
        if path == "/slack":
            payload = json.loads(raw.decode() or "{}")
            with _LOCK:
                _SLACK.append(str(payload.get("text", "")))
            self._bytes(b"ok")
            return
        if path == "/slack-revoked":
            self._bytes(b"missing", status=404)
            return
        if path == "/webhook":
            self._store_webhook(raw)
            self._json({"ok": True})
            return
        self._json({"ok": False}, status=404)

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _store_webhook(self, raw: bytes) -> None:
        timestamp = self.headers.get("X-Apgar-Timestamp", "")
        signature = self.headers.get("X-Apgar-Signature", "")
        valid = False
        if timestamp.isdigit():
            valid = signature == sign(SECRET, int(timestamp), raw)
        try:
            payload = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            payload = {}
        with _LOCK:
            _WEBHOOKS.append(
                {
                    "signature_valid": valid,
                    "event": payload.get("event") if isinstance(payload, dict) else None,
                    "payload": payload,
                }
            )

    def _json(self, payload: object, status: int = 200) -> None:
        raw = json.dumps(payload).encode()
        self._bytes(raw, status=status, content_type="application/json")

    def _bytes(self, raw: bytes, status: int = 200, content_type: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9098)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), _Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
