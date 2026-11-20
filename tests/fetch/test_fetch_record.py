"""Record and replay (CONVENTIONS.md, rule 11), the settings, and browser pages from recordings."""
from __future__ import annotations

import gzip
from pathlib import Path

import httpx
import pytest

from app.fetch import (
    Fetcher, FetchMode, FetchSettings, RecordedPage, RecordingTransport, ReplayMiss, save_browsed,
)
from app.models import NetworkEntry
from tests.fetch.conftest import BASE, html

ROOT = Path(__file__).resolve().parents[2]


def portal(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
    if request.url.path == "/start":
        return httpx.Response(302, headers={"location": "/list?page=1"})
    if request.url.path == "/api":  # compressed on the wire, as a real server sends it
        return httpx.Response(200, headers={"content-type": "application/json", "content-encoding": "gzip"},
                              stream=httpx.ByteStream(gzip.compress(b'{"content": [{"id": 450411}], "totalElements": 1}')))
    return html("<table><tr data-oid='17'><td>Schule</td></tr></table>")


def test_what_was_recorded_replays_without_the_portal(tmp_path):
    recorder = Fetcher(FetchSettings(mode=FetchMode.record, recordings_dir=tmp_path, requests_per_second=1000),
                       transport=RecordingTransport(httpx.MockTransport(portal), tmp_path))
    live_page = recorder.fetch("p1", f"{BASE}/start")
    live_api = recorder.fetch("p1", f"{BASE}/api")
    assert sorted(p.name.split(".")[-1] for p in (tmp_path / "portal.example").iterdir()).count("json") == 4

    replayer = Fetcher(FetchSettings(mode=FetchMode.replay, recordings_dir=tmp_path))
    page = replayer.fetch("p1", f"{BASE}/start")
    api = replayer.fetch("p1", f"{BASE}/api")
    assert (page.status, page.final_url, page.redirects, page.text) == (
        live_page.status, live_page.final_url, live_page.redirects, live_page.text)
    assert api.json() == live_api.json() == {"content": [{"id": 450411}], "totalElements": 1}


def test_a_request_never_recorded_is_an_error_not_a_live_fetch(tmp_path):
    replayer = Fetcher(FetchSettings(mode=FetchMode.replay, recordings_dir=tmp_path, ignore_robots_txt=True))
    with pytest.raises(ReplayMiss, match="Ask a person to record"):
        replayer.fetch("p1", f"{BASE}/never")


def test_replay_needs_no_pace(tmp_path):
    recorder = Fetcher(FetchSettings(mode=FetchMode.record, recordings_dir=tmp_path, ignore_robots_txt=True,
                                     requests_per_second=1000),
                       transport=RecordingTransport(httpx.MockTransport(portal), tmp_path))
    recorder.fetch("p1", f"{BASE}/list")
    replayer = Fetcher(FetchSettings(mode=FetchMode.replay, recordings_dir=tmp_path, ignore_robots_txt=True))
    assert not replayer.limiter.enabled
    for _ in range(50):
        assert replayer.fetch("p1", f"{BASE}/list").ok


def test_a_recorded_browser_page_comes_back_with_its_network_calls(tmp_path):
    url = f"{BASE}/aankondigingen"
    save_browsed(tmp_path, RecordedPage(
        url=url, final_url=url,
        html="<html><body><app-root><div class='card' data-id='450432'>Bouw</div></app-root></body></html>",
        network=[NetworkEntry(url=f"{BASE}/papi/publicaties?page=0", resource_type="xhr",
                              content_type="application/json", looks_like_tender_list=True)]))
    replayer = Fetcher(FetchSettings(mode=FetchMode.replay, recordings_dir=tmp_path, ignore_robots_txt=True))
    page = replayer.browse("p1", url)
    assert "450432" in page.html and page.status == 200 and page.answer.via == "browser"
    assert page.network[0].looks_like_tender_list
    with pytest.raises(ReplayMiss):
        replayer.browse("p1", f"{BASE}/other")
    with pytest.raises(NotImplementedError):
        Fetcher(FetchSettings(mode=FetchMode.live)).browse("p1", url)


def test_settings_default_to_replay_and_read_the_environment(tmp_path):
    assert FetchSettings().mode is FetchMode.replay  # never live by accident
    s = FetchSettings.from_env({"FETCH_MODE": "LIVE", "FETCH_RECORDINGS_DIR": str(tmp_path),
                                "IGNORE_ROBOTS_TXT": "true", "FETCH_REQUESTS_PER_SECOND": "0.5",
                                "FETCH_MAX_REDIRECTS": "4"})
    assert (s.mode, s.recordings_dir, s.ignore_robots_txt, s.requests_per_second, s.max_redirects) == (
        FetchMode.live, tmp_path, True, 0.5, 4)
    assert not FetchSettings.from_env({"IGNORE_ROBOTS_TXT": "no"}).ignore_robots_txt
    with pytest.raises(ValueError):
        FetchSettings(requests_per_second=0)


def test_the_container_reads_live():
    assert "FETCH_MODE=live" in (ROOT / "Dockerfile").read_text()
