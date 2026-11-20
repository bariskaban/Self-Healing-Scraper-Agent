"""The real httpx transport against a server inside this test, on 127.0.0.1 (no portal is reached).

The audit of Q4 measured a page behind two redirects sending three requests within 10 ms.
Here the server writes down when each request arrived, and every gap must be one interval.
"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.docs import Announced, DocsSettings, FileStore, store_document
from app.fetch import Fetcher, FetchMode, FetchSettings
from tests.docs.conftest import PDF, stand_in_judge

INTERVAL = 0.2  # 5 requests a second, to keep the test short


class _Handler(BaseHTTPRequestHandler):
    arrivals: list[tuple[float, str]] = []
    routes = {
        "/robots.txt": (200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /private/\n"),
        "/start": (302, {"location": "/middle"}, b""),
        "/middle": (302, {"location": "/tenders"}, b""),
        "/tenders": (200, {"content-type": "text/html"}, b"<html><body><table id='list'></table></body></html>"),
        "/lv.pdf": (200, {"content-type": "application/pdf"}, PDF),
    }

    def do_GET(self) -> None:  # noqa: N802 - the name http.server calls
        _Handler.arrivals.append((time.monotonic(), self.path))
        status, headers, body = self.routes.get(self.path, (404, {}, b"not here"))
        self.send_response(status)
        for k, v in {**headers, "content-length": str(len(body))}.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        return None


@pytest.fixture
def server():
    _Handler.arrivals = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_every_hop_of_a_redirect_chain_waits_for_its_own_slot(server):
    fetcher = Fetcher(FetchSettings(mode=FetchMode.live, requests_per_second=1 / INTERVAL))
    try:
        got = fetcher.fetch("p1", f"{server}/start")
    finally:
        fetcher.close()
    assert got.ok and got.final_url == f"{server}/tenders"
    assert [path for _, path in _Handler.arrivals] == ["/robots.txt", "/start", "/middle", "/tenders"]
    times = [t for t, _ in _Handler.arrivals]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(gap >= INTERVAL * 0.95 for gap in gaps), gaps


def test_a_file_from_the_wire_lands_in_app_docs(server, tmp_path):
    fetcher = Fetcher(FetchSettings(mode=FetchMode.live, requests_per_second=1 / INTERVAL))
    files = FileStore(DocsSettings(data_dir=tmp_path))
    try:
        with fetcher.download("p1", f"{server}/lv.pdf") as download:
            result = store_document(download, Announced(source_url=f"{server}/lv.pdf", name="lv.pdf"),
                                    store=files, judge=stand_in_judge, portal_id="p1", tender_id="T1")
    finally:
        fetcher.close()
    (record,) = result.files
    assert record.deliverable and record.size_bytes == len(PDF)
    assert files.resolve(record.storage_path).read_bytes() == PDF
