#!/usr/bin/env python3
"""Termux Storage Server - a small, dependency-free personal file server."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import mimetypes
import os
import secrets
import shutil
import sys
import threading
import urllib.parse
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as email_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
DEFAULT_STORAGE = APP_DIR / "storage"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB guardrail; change if needed.


def utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_relative_path(raw: str) -> Path:
    decoded = urllib.parse.unquote(raw).replace("\\", "/")
    candidate = Path(decoded)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Invalid path")
    clean = Path(*[part for part in candidate.parts if part not in ("", ".")])
    if not clean.parts:
        raise ValueError("Empty path")
    return clean


def file_info(root: Path, rel: Path) -> dict:
    absolute = root / rel
    stat = absolute.stat()
    return {
        "name": rel.name,
        "path": rel.as_posix(),
        "size": stat.st_size,
        "modified": utc_iso(stat.st_mtime),
        "download": "/download/" + urllib.parse.quote(rel.as_posix()),
    }


class StorageHandler(BaseHTTPRequestHandler):
    server_version = "TermuxStorage/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    @property
    def root(self) -> Path:
        return self.server.storage_root  # type: ignore[attr-defined]

    @property
    def token(self) -> str:
        return self.server.access_token  # type: ignore[attr-defined]

    def send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self) -> bool:
        supplied = self.headers.get("X-Storage-Token", "")
        if not supplied:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            supplied = query.get("token", [""])[0]
        return bool(supplied) and secrets.compare_digest(supplied, self.token)

    def require_auth(self) -> bool:
        if not self.authorized():
            self.send_json({"error": "Unauthorized. Add the X-Storage-Token header."}, 401)
            return False
        return True

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            return self.serve_ui()
        if parsed.path == "/api/health":
            return self.send_json({"ok": True, "app": "termux-storage-server"})
        if parsed.path == "/api/files":
            if not self.require_auth():
                return
            return self.list_files()
        if parsed.path.startswith("/download/"):
            if not self.require_auth():
                return
            return self.download_file(parsed.path[len("/download/"):])
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/api/upload":
            if not self.require_auth():
                return
            return self.upload_file()
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path.startswith("/api/files/"):
            if not self.require_auth():
                return
            return self.delete_file(parsed.path[len("/api/files/"):])
        self.send_error(HTTPStatus.NOT_FOUND)

    def serve_ui(self) -> None:
        index = WEB_DIR / "index.html"
        data = index.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def list_files(self) -> None:
        items = []
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                items.append(file_info(self.root, path.relative_to(self.root)))
        self.send_json({"files": items, "count": len(items)})

    def download_file(self, raw_path: str) -> None:
        try:
            rel = safe_relative_path(raw_path)
            target = self.root / rel
            if not target.is_file():
                raise FileNotFoundError
            size = target.stat().st_size
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(target.name))
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with target.open("rb") as source:
                shutil.copyfileobj(source, self.wfile, length=1024 * 1024)
        except (ValueError, FileNotFoundError):
            self.send_json({"error": "File not found"}, 404)

    def upload_file(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_UPLOAD_BYTES:
                return self.send_json({"error": "Upload is empty or exceeds the 2 GiB limit."}, 413)
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("multipart/form-data"):
                return self.send_json({"error": "Use multipart/form-data."}, 400)
            # cgi.FieldStorage was removed from Python 3.13+. Parse the
            # multipart body with the maintained email parser instead.
            body = self.rfile.read(length)
            message = BytesParser(policy=email_policy).parsebytes(
                b"Content-Type: " + content_type.encode("ascii", "strict") + b"\r\n\r\n" + body
            )
            upload = next(
                (
                    part for part in message.iter_parts()
                    if part.get_param("name", header="content-disposition") == "file"
                ),
                None,
            )
            if upload is None or not upload.get_filename():
                return self.send_json({"error": "No file field was provided."}, 400)
            original_name = Path(os.path.basename(upload.get_filename())).name
            if not original_name or original_name in (".", ".."):
                return self.send_json({"error": "Invalid filename."}, 400)
            safe_name = original_name.replace("\x00", "")
            destination = self.root / safe_name
            if destination.exists():
                stem, suffix = destination.stem, destination.suffix
                destination = self.root / f"{stem}-{secrets.token_hex(3)}{suffix}"
            with destination.open("wb") as output:
                output.write(upload.get_payload(decode=True) or b"")
            return self.send_json({"message": "Uploaded", "file": file_info(self.root, destination.relative_to(self.root))}, 201)
        except Exception as exc:
            self.log_message("upload error: %s", exc)
            return self.send_json({"error": "Upload failed."}, 500)

    def delete_file(self, raw_path: str) -> None:
        try:
            rel = safe_relative_path(raw_path)
            target = self.root / rel
            if not target.is_file():
                raise FileNotFoundError
            target.unlink()
            self.send_json({"message": "Deleted"})
        except (ValueError, FileNotFoundError):
            self.send_json({"error": "File not found"}, 404)


def main() -> None:
    parser = argparse.ArgumentParser(description="Private file storage server for Termux")
    parser.add_argument("--host", default=os.environ.get("STORAGE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("STORAGE_PORT", "8080")))
    parser.add_argument("--storage", default=os.environ.get("STORAGE_DIR", str(DEFAULT_STORAGE)))
    parser.add_argument("--token", default=os.environ.get("STORAGE_TOKEN"))
    args = parser.parse_args()
    token = args.token or secrets.token_urlsafe(24)
    root = Path(args.storage).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((args.host, args.port), StorageHandler)
    httpd.storage_root = root  # type: ignore[attr-defined]
    httpd.access_token = token  # type: ignore[attr-defined]
    print(f"Storage directory: {root}")
    print(f"Listening on: http://{args.host}:{args.port}")
    print(f"Access token: {token}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
