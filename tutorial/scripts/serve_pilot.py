#!/usr/bin/env python3
"""Loopback-only pilot review server with seekable media; standard library only."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import re

from validate import ROOT


def byte_range(value: str, size: int) -> tuple[int, int]:
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if not match or size <= 0 or not any(match.groups()):
        raise ValueError("unsupported range")
    first, last = match.groups()
    start = int(first) if first else max(0, size - int(last))
    end = min(size - 1, int(last)) if first and last else size - 1
    if start >= size or end < start:
        raise ValueError("unsatisfiable range")
    return start, end


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_head(self):
        self.requested_bytes = None
        path = Path(self.translate_path(self.path)).resolve()
        if not path.is_relative_to(Path(self.directory).resolve()):
            self.send_error(403)
            return None
        value = self.headers.get("Range")
        if not value or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        try:
            start, end = byte_range(value, size)
        except ValueError:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        source = path.open("rb")
        source.seek(start)
        self.requested_bytes = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self.requested_bytes))
        self.end_headers()
        return source

    def copyfile(self, source, outputfile):
        try:
            if self.requested_bytes is None:
                return super().copyfile(source, outputfile)
            remaining = self.requested_bytes
            while remaining:
                data = source.read(min(64 * 1024, remaining))
                if not data:
                    break
                outputfile.write(data)
                remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError):
            # Media elements cancel superseded range/preload requests normally.
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4191)
    args = parser.parse_args()
    folder = ROOT / "generated/pilot"
    if not (folder / "index.html").is_file():
        parser.error("assemble the pilot before starting review")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(folder)))
    print(f"Pilot review: http://127.0.0.1:{args.port}/index.html", flush=True)
    server.serve_forever()
