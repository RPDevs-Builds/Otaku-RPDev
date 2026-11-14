#!/usr/bin/env python3
"""
kodi_e2e_mock_server.py — Local HTTP Mock Daemon for Headless Kodi E2E Suite
=============================================================================
Provides a fast, deterministic loopback HTTP server (127.0.0.1) for offline
and hermetic integration testing in Kodi 21 & 22 Flatpak runtimes.

Endpoints served:
  - POST /v1         : Mock FlareSolverr v3 solver (returns 200 with HTML solution + cookies)
  - GET  /v1         : FlareSolverr health check
  - GET  /ms         : Mock Megacloud / solver extraction endpoint
  - GET  /ms/get     : Megacloud solver with ?url= query parameter
  - GET  /get        : Generic solver with ?url= query parameter
  - GET  /anime/*    : Mock anime metadata catalog (Frieren, top anime, seasons)
  - GET  /video.mkv  : Serves sample_chapters.mkv with full HTTP Range (bytes=) support
  - HEAD /video.mkv  : HTTP Range probe header response for video players
  - GET  /sub.srt    : Serves sample.srt subtitle file
  - HEAD /sub.srt    : Subtitle header probe response

Usage:
  # Standalone CLI mode:
  python3 scripts/kodi_e2e_mock_server.py [--port 0] [--host 127.0.0.1]

  # Programmatic import:
  from scripts.kodi_e2e_mock_server import LocalMockServer
  with LocalMockServer() as server:
      base_url = server.get_base_url()
"""

import argparse
import http.server
import json
import os
import re
import socketserver
import sys
import threading
import time
import urllib.parse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA_FIXTURES_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "media")
SAMPLE_MKV = os.path.join(MEDIA_FIXTURES_DIR, "sample_chapters.mkv")
SAMPLE_SRT = os.path.join(MEDIA_FIXTURES_DIR, "sample.srt")


class MockServerHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Silence default request stderr logging during automated test runs
        if os.environ.get("MOCK_SERVER_VERBOSE") == "1":
            sys.stderr.write(f"[MockServer] {format % args}\n")

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""

        # /v1 — FlareSolverr mock
        if path == "/v1":
            target_url = "http://127.0.0.1/mock_target"
            if raw_body:
                try:
                    data = json.loads(raw_body.decode("utf-8", "ignore"))
                    target_url = data.get("url") or target_url
                except Exception:
                    pass

            now_ms = int(time.time() * 1000)
            mock_html = (
                "<!DOCTYPE html><html><head><title>Otaku Mock FlareSolverr Page</title></head>"
                "<body><div id=\"content\">Mock Decoded Payload</div>"
                "<div class=\"server-item\"><a href=\"/watch?ep=1\" data-id=\"52991\">Episode 1</a></div>"
                "</body></html>"
            )
            response_payload = {
                "status": "ok",
                "message": "Challenge not detected!",
                "startTimestamp": now_ms,
                "endTimestamp": now_ms + 10,
                "version": "v3.3.21",
                "solution": {
                    "url": target_url,
                    "status": 200,
                    "headers": {"content-type": "text/html; charset=utf-8"},
                    "response": mock_html,
                    "cookies": [
                        {
                            "name": "cf_clearance",
                            "value": "mock_cf_clearance_e2e_token_12345",
                            "domain": "127.0.0.1",
                            "path": "/",
                            "httpOnly": False,
                            "secure": False,
                        }
                    ],
                    "userAgent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                },
            }
            body_bytes = json.dumps(response_payload).encode("utf-8")
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
            return

        # Generic 404 for unhandled POST
        self.send_response(404)
        self.end_headers()

    def do_HEAD(self):
        self._handle_get_or_head(is_head=True)

    def do_GET(self):
        self._handle_get_or_head(is_head=False)

    def _handle_get_or_head(self, is_head=False):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 1. /v1 health check
        if path == "/v1":
            body = json.dumps({"status": "ok", "message": "FlareSolverr Mock Server Running", "version": "v3.3.21"}).encode("utf-8")
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not is_head:
                self.wfile.write(body)
            return

        # 2. Megacloud / solver endpoints: /ms, /ms/get, /get
        if path in ("/ms", "/ms/get", "/get"):
            host_header = self.headers.get("Host", f"127.0.0.1:{self.server.server_port}")
            base_url = f"http://{host_header}"
            sources = [
                {
                    "file": f"{base_url}/video.mkv",
                    "type": "mp4",
                    "label": "1080p",
                }
            ]
            tracks = [
                {
                    "file": f"{base_url}/sub.srt",
                    "label": "English",
                    "kind": "captions",
                    "default": True,
                }
            ]
            resp_obj = {
                "sources": sources,
                "tracks": tracks,
                "intro": {"start": 0, "end": 2},
                "outro": {"start": 4, "end": 5},
            }
            body = json.dumps(resp_obj).encode("utf-8")
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not is_head:
                self.wfile.write(body)
            return

        # 3. /video.mkv — Serves sample_chapters.mkv with full HTTP Range bytes= support
        if path == "/video.mkv":
            if not os.path.exists(SAMPLE_MKV):
                self.send_response(404)
                self.end_headers()
                return

            total_size = os.path.getsize(SAMPLE_MKV)
            range_header = self.headers.get("Range")

            if range_header:
                # Range header format: bytes=start-end or bytes=start-
                range_match = re.match(r"^bytes=(\d+)-(\d+)?$", range_header.strip())
                if not range_match:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{total_size}")
                    self.end_headers()
                    return

                start = int(range_match.group(1))
                end = int(range_match.group(2)) if range_match.group(2) else total_size - 1

                if start >= total_size or end < start or end >= total_size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{total_size}")
                    self.end_headers()
                    return

                chunk_len = end - start + 1
                self.send_response(206)
                self._send_cors_headers()
                self.send_header("Content-Type", "video/x-matroska")
                self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
                self.send_header("Content-Length", str(chunk_len))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

                if not is_head:
                    with open(SAMPLE_MKV, "rb") as vf:
                        vf.seek(start)
                        bytes_to_send = chunk_len
                        buf_size = 64 * 1024
                        while bytes_to_send > 0:
                            read_len = min(buf_size, bytes_to_send)
                            chunk = vf.read(read_len)
                            if not chunk:
                                break
                            try:
                                self.wfile.write(chunk)
                            except (BrokenPipeError, ConnectionResetError):
                                break
                            bytes_to_send -= len(chunk)
                return

            # No Range header -> 200 OK full video
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "video/x-matroska")
            self.send_header("Content-Length", str(total_size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()

            if not is_head:
                with open(SAMPLE_MKV, "rb") as vf:
                    shutil_buf_size = 64 * 1024
                    while True:
                        chunk = vf.read(shutil_buf_size)
                        if not chunk:
                            break
                        try:
                            self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            break
            return

        # 4. /sub.srt — Serves sample.srt subtitle
        if path == "/sub.srt":
            if not os.path.exists(SAMPLE_SRT):
                self.send_response(404)
                self.end_headers()
                return

            total_size = os.path.getsize(SAMPLE_SRT)
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(total_size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()

            if not is_head:
                with open(SAMPLE_SRT, "rb") as sf:
                    try:
                        self.wfile.write(sf.read())
                    except (BrokenPipeError, ConnectionResetError):
                        pass
            return

        # 5. /anime/* — Mock anime catalog and metadata responses
        if path.startswith("/anime/"):
            sub_id = path[len("/anime/"):].strip("/")
            mock_anime = {
                "id": 52991 if not sub_id.isdigit() else int(sub_id),
                "mal_id": 52991 if not sub_id.isdigit() else int(sub_id),
                "title": {
                    "romaji": "Sousou no Frieren",
                    "english": "Frieren: Beyond Journey's End",
                    "native": "葬送のフリーレン",
                },
                "format": "TV",
                "status": "FINISHED",
                "episodes": 28,
                "season": "FALL",
                "seasonYear": 2023,
                "averageScore": 91,
                "description": "During their decade-long quest to defeat the Demon King...",
                "coverImage": {
                    "extraLarge": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx154587-n2bGQMykh7Ny.png",
                },
                "bannerImage": "https://s4.anilist.co/file/anilistcdn/media/anime/banner/154587-iv4LGomNU2QU.jpg",
                "genres": ["Adventure", "Drama", "Fantasy"],
            }
            body = json.dumps(mock_anime).encode("utf-8")
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not is_head:
                self.wfile.write(body)
            return

        # Fallback 404
        self.send_response(404)
        self.end_headers()


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class LocalMockServer:
    """Ephemeral HTTP mock daemon for Kodi E2E testing."""

    def __init__(self, host="127.0.0.1", port=0):
        self.host = host
        self.requested_port = port
        self.server = None
        self.thread = None
        self.port = 0

    def start(self):
        self.server = ThreadingHTTPServer((self.host, self.requested_port), MockServerHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        # Verify server accepts connections before returning
        for _ in range(50):
            try:
                import urllib.request
                with urllib.request.urlopen(f"http://{self.host}:{self.port}/v1", timeout=1.0) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                time.sleep(0.05)
        return self

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.server = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
            self.thread = None

    def get_base_url(self):
        return f"http://{self.host}:{self.port}"

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def main():
    parser = argparse.ArgumentParser(description="Ephemeral mock HTTP server for Kodi E2E testing.")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8191, help="Port to bind (default: 8191, 0 for dynamic)")
    args = parser.parse_args()

    server = LocalMockServer(host=args.host, port=args.port)
    server.start()
    print(f"Mock server listening on {server.get_base_url()}")
    print("Press Ctrl+C to terminate.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping mock server...")
    finally:
        server.stop()
        print("Mock server stopped.")


if __name__ == "__main__":
    main()
