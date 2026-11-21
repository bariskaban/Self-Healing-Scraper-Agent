"""Record and replay at the network layer (CONVENTIONS.md, rule 11; Q8).

Both are httpx transports, so everything above them (redirects, retries, robots.txt, the
rate limiter) behaves the same live, recording or replaying. Each exchange is one request
and its answer; redirects are walked by the fetcher, so each hop is its own exchange.

Layout: <root>/<host>/<key>.json holds the request line and the answer's status and
headers; <key>.body holds the body exactly as the server sent it (still compressed if it was).
The key is the SHA-256 of the method, the full address and the request body.

A request with no recording raises `ReplayMiss`, which the fetcher does not catch: a missing
recording is something a person records, never something fetched live (CLAUDE.md).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from app import logs
from app.models import NetworkEntry

log = logs.get("fetch.record")


class ReplayMiss(LookupError):
    """No recording for this request. Ask a person to record the portal (FETCH_MODE=record)."""


class RecordedPage(BaseModel):
    """A page as the headless browser left it: <root>/<host>/browse-<sha256 of the address>.json.

    The live browser writes these in record mode; a hand-made one is fine for a test.
    """

    url: str
    final_url: str
    status: int | None = 200
    headers: list[tuple[str, str]] = Field(default_factory=lambda: [("content-type", "text/html; charset=utf-8")])
    html: str
    network: list[NetworkEntry] = Field(default_factory=list)


def browse_path(root: Path, url: str) -> Path:
    return _host_dir(Path(root), httpx.URL(url)) / f"browse-{hashlib.sha256(url.encode('utf-8')).hexdigest()}.json"


def save_browsed(root: Path, page: RecordedPage) -> Path:
    path = browse_path(root, page.url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page.model_dump_json(indent=1), encoding="utf-8")
    return path


def load_browsed(root: Path, url: str) -> RecordedPage:
    path = browse_path(root, url)
    if not path.is_file():
        raise ReplayMiss(f"No recorded browser page for {url} under {root}. "
                         "Ask a person to record this portal with FETCH_MODE=record.")
    return RecordedPage.model_validate_json(path.read_text(encoding="utf-8"))


def exchange_key(request: httpx.Request) -> str:
    content = request.read() if not isinstance(request.stream, httpx.ByteStream) else bytes(request.content)
    head = f"{request.method} {request.url}\n".encode("utf-8")
    return hashlib.sha256(head + content).hexdigest()


def _host_dir(root: Path, url: httpx.URL) -> Path:
    host = re.sub(r"[^A-Za-z0-9.-]", "_", url.netloc.decode("ascii", "replace")) or "_"
    return root / host


def _paths(root: Path, request: httpx.Request) -> tuple[Path, Path]:
    key = exchange_key(request)
    folder = _host_dir(root, request.url)
    return folder / f"{key}.json", folder / f"{key}.body"


class RecordingTransport(httpx.BaseTransport):
    """Passes each request to the real transport and writes the exchange down.

    Bodies are held in memory while they are written, so recording is for test portals,
    not for the 1 GB archives the brief warns about.
    """

    def __init__(self, inner: httpx.BaseTransport, root: Path) -> None:
        self.inner = inner
        self.root = Path(root)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        try:
            if response.is_stream_consumed:  # built in memory: its content is already decoded
                body = response.content
                headers = [(k, v) for k, v in response.headers.multi_items()
                           if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
            else:  # from the wire: kept as the server sent it, compressed if it was
                body = b"".join(response.iter_raw())
                headers = list(response.headers.multi_items())
        finally:
            response.close()
        meta_path, body_path = _paths(self.root, request)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(body)
        log.debug("recorded %s %s -> %s, %d bytes, in %s", request.method, logs.safe_url(str(request.url)),
                  response.status_code, len(body), meta_path.parent)
        meta_path.write_text(json.dumps({
            "method": request.method, "url": str(request.url), "status": response.status_code,
            "headers": [[k, v] for k, v in headers],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        return httpx.Response(response.status_code, headers=headers, stream=httpx.ByteStream(body), request=request)

    def close(self) -> None:
        self.inner.close()


class ReplayTransport(httpx.BaseTransport):
    """Answers every request from the recordings, and nothing else."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        meta_path, body_path = _paths(self.root, request)
        if not meta_path.is_file():
            log.warning("replay miss: %s %s (looked under %s)", request.method, logs.safe_url(str(request.url)), self.root)
            raise ReplayMiss(f"No recording for {request.method} {request.url} under {self.root}. "
                             "Ask a person to record this portal with FETCH_MODE=record.")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        body = body_path.read_bytes() if body_path.is_file() else b""
        log.debug("replayed %s %s -> %s, %d bytes", request.method, logs.safe_url(str(request.url)), meta["status"], len(body))
        # As a stream, so httpx decodes it once, exactly as it decodes an answer from the wire.
        return httpx.Response(meta["status"], headers=[tuple(h) for h in meta["headers"]],
                              stream=httpx.ByteStream(body), request=request)
