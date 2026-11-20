"""Logging (app/logs.py): levels from the environment, no secret in any line, short lines."""
from __future__ import annotations

import io
import logging

import pytest

from app import logs


@pytest.fixture
def clean_logger():
    root = logging.getLogger(logs.ROOT)
    before = (list(root.handlers), root.level)
    root.handlers = []
    yield root
    for handler in root.handlers:
        handler.close()
    root.handlers, root.level = before


def capture(root, environ):
    """configure_logging on `environ`, with the stderr handler pointed at a buffer."""
    logs.configure_logging(environ)
    buffer = io.StringIO()
    handler = next(h for h in root.handlers if isinstance(h, logging.StreamHandler))
    handler.setStream(buffer)
    return buffer


def test_info_is_the_default_and_log_level_sets_it(clean_logger):
    buffer = capture(clean_logger, {})
    logs.get("loop").debug("hidden")
    logs.get("loop").info("shown")
    assert "shown" in buffer.getvalue() and "hidden" not in buffer.getvalue()
    clean_logger.handlers = []
    buffer = capture(clean_logger, {"LOG_LEVEL": "debug"})
    logs.get("loop").debug("now shown")
    assert "now shown" in buffer.getvalue() and "watchtower.loop" in buffer.getvalue()


def test_one_area_can_have_its_own_level(clean_logger):
    buffer = capture(clean_logger, {"LOG_LEVEL": "warning", "LOG_LEVEL_FETCH": "debug"})
    logs.get("fetch").debug("fetch detail")
    logs.get("reader").info("reader detail")
    assert "fetch detail" in buffer.getvalue() and "reader detail" not in buffer.getvalue()
    logging.getLogger("watchtower.fetch").setLevel(logging.NOTSET)


def test_a_bad_level_falls_back_and_configuring_twice_adds_no_second_handler(clean_logger):
    logs.configure_logging({"LOG_LEVEL": "loud"})
    logs.configure_logging({"LOG_LEVEL": "loud"})
    assert clean_logger.level == logging.INFO and len(clean_logger.handlers) == 1


def test_the_key_never_reaches_a_line_whoever_logs_it(clean_logger):
    key = "sk-proj-ABCDEFGH12345678"
    buffer = capture(clean_logger, {"OPENAI_API_KEY": key})
    logs.get("agent").info("calling with %s", key)
    logs.get("agent").info("header Authorization: Bearer sk-other-ZZZZZZZZ99999 sent")
    logs.get("agent").error("oops %s", {"key": key})
    out = buffer.getvalue()
    assert key not in out and "ABCDEFGH12345678" not in out and "ZZZZZZZZ99999" not in out and "***" in out


def test_json_format_gives_one_object_per_line_with_the_portal_and_run(clean_logger):
    import json

    buffer = capture(clean_logger, {"LOG_FORMAT": "json", "LOG_LEVEL": "info"})
    logs.get("reader").info("portal %s: run %s saved: ok", "0123456789ab", "f" * 32)
    logs.get("agent").info(json.dumps({"event": "agent.model_call", "portal_id": "0123456789ab", "run_id": "r1", "ms": 5}))
    first, second = (json.loads(line) for line in buffer.getvalue().splitlines())
    assert first["portal_id"] == "0123456789ab" and first["run_id"] == "f" * 32 and first["logger"] == "watchtower.reader"
    assert first["level"] == "INFO" and "saved" in first["message"]
    assert second["event"] == "agent.model_call" and second["ms"] == 5 and "message" not in second


def test_the_log_file_gets_the_same_lines(clean_logger, tmp_path):
    path = tmp_path / "w.log"
    logs.configure_logging({"LOG_FILE": str(path), "LOG_LEVEL": "info"})
    logs.get("db").info("to the file")
    for handler in clean_logger.handlers:
        handler.flush()
    assert "to the file" in path.read_text()


def test_an_address_loses_its_user_password_fragment_and_secret_parameters():
    url = "https://user:hunter2@portal.example:8443/list?page=2&token=abc123&q=roads&sessionid=zz#frag"
    shown = logs.safe_url(url)
    assert shown == "https://portal.example:8443/list?page=2&token=%2A%2A%2A&q=roads&sessionid=%2A%2A%2A"
    assert "hunter2" not in shown and "abc123" not in shown and "frag" not in shown
    assert logs.safe_url("not a url") == "not a url"


def test_mappings_and_long_values_are_hidden_and_clipped():
    shown = logs.safe_mapping({"Authorization": "Bearer x", "api_key": "k", "q": "y" * 500})
    assert shown["Authorization"] == shown["api_key"] == "***" and len(shown["q"]) < 120
    text = logs.clip("a\n  b   c" + "z" * 400, 20)
    assert "\n" not in text and text.startswith("a b c") and "chars)" in text


def test_timed_logs_start_end_and_a_raise_at_debug_and_nothing_above(clean_logger):
    buffer = capture(clean_logger, {"LOG_LEVEL": "debug"})
    log = logs.get("recipe")

    @logs.timed(log, "work", lambda x: f"x={x}", lambda r: f"gave {r}")
    def work(x):
        if x < 0:
            raise ValueError("negative")
        return x * 2

    assert work(2) == 4
    with pytest.raises(ValueError):
        work(-1)
    out = buffer.getvalue()
    assert "work starts x=2" in out and "work took" in out and "gave 4" in out and "work raised ValueError" in out
    clean_logger.handlers = []
    quiet = capture(clean_logger, {"LOG_LEVEL": "info"})
    assert work(3) == 6 and quiet.getvalue() == ""


def test_a_reader_read_logs_its_decisions_end_to_end(caplog, monkeypatch):
    """The attach of the mock portal says what it did, from the request to the state, without a model."""
    import httpx
    from fastapi.testclient import TestClient

    from app.fetch import Fetcher, FetchMode, FetchSettings, PortalLimiter
    from app.main import create_app
    from mock_portal import MockPortal

    monkeypatch.setenv("LOG_LEVEL", "debug")  # create_app configures logging from the environment
    caplog.set_level(logging.DEBUG, logger="watchtower")
    import os, tempfile
    with tempfile.TemporaryDirectory() as data:
        os.environ["DATA_DIR"] = data
        try:
            mock = MockPortal()
            clock = [0.0]
            limiter = PortalLimiter(1.0, 10.0, clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))
            fetcher = Fetcher(FetchSettings(mode=FetchMode.live), transport=httpx.MockTransport(mock.handle), limiter=limiter,
                              clock=lambda: clock[0], rng=lambda: 0.0)
            with TestClient(create_app(fetch=fetcher, mock=mock)) as client:
                pid = client.post("/portals", json={"url": "https://mock.example"}).json()["id"]
                import time
                for _ in range(300):
                    if client.get(f"/portals/{pid}").json()["state"] == "serving":
                        break
                    time.sleep(0.05)
        finally:
            os.environ.pop("DATA_DIR", None)
    text = "\n".join(r.getMessage() for r in caplog.records)
    for expected in ("attach queued", "read_list took", "check printed_total: pass", "decide: state integrating -> serving",
                     f"portal {pid}: state integrating -> serving", "run", "published 45 tender(s)"):
        assert expected in text, expected
