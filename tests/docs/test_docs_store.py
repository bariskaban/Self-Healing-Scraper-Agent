"""Streaming downloads into the store: limits, dedupe, nothing half-written left visible."""
from __future__ import annotations

import hashlib

import pytest

from app.docs import Announced, StaticDownload, TooLarge, is_provisional_id, store_document
from app.models import SkipReason
from tests.docs.conftest import PDF, blobs, stand_in_judge, temp_files

URL = "https://portal.example/docs/1"


def run(store, body, *, headers=None, announced=None, status=200):
    dl = StaticDownload(status=status, headers=headers or {"Content-Type": "application/pdf"}, body=body)
    return store_document(dl, announced or Announced(source_url=URL, name="spec.pdf"), store=store,
                          judge=stand_in_judge, portal_id="p1", tender_id="T-1")


def _pdf(n: int) -> bytes:
    return (b"%PDF-" + b"x" * n)[:n]


@pytest.mark.parametrize("size", [9, 10])
def test_under_and_exactly_at_limit_are_stored(make_store, size):
    store = make_store(max_file_bytes=10)
    res = run(store, [_pdf(size)[:4], _pdf(size)[4:]])
    (rec,) = res.files
    assert rec.skipped is None and rec.size_bytes == size
    assert rec.sha256 == hashlib.sha256(_pdf(size)).hexdigest()
    assert rec.file_id == rec.sha256[:16] and rec.deliverable
    assert store.resolve(rec.storage_path).read_bytes() == _pdf(size)
    assert res.links[0].file_name == "spec.pdf" and res.links[0].file_id == rec.file_id
    assert rec.downloaded_at.utcoffset().total_seconds() == 0


def test_over_limit_mid_stream_leaves_nothing(make_store):
    store = make_store(max_file_bytes=10)
    res = run(store, [_pdf(6), b"y" * 5])
    (rec,) = res.files
    assert rec.skipped == SkipReason.too_large and rec.sha256 is None and rec.storage_path is None
    assert is_provisional_id(rec.file_id)
    assert blobs(store) == [] and temp_files(store) == []


def _never():
    raise AssertionError("body must not be read")
    yield b""  # pragma: no cover


def test_announced_over_limit_skips_without_reading(make_store):
    store = make_store(max_file_bytes=10)
    res = run(store, _never(), announced=Announced(source_url=URL, name="big.zip", size_bytes=11))
    assert res.skipped == SkipReason.too_large and res.files[0].size_bytes == 11
    assert blobs(store) == [] and temp_files(store) == []


def test_content_length_over_limit_skips_without_reading(make_store):
    store = make_store(max_file_bytes=10)
    res = run(store, _never(), headers={"content-length": "11"})
    assert res.skipped == SkipReason.too_large


def test_same_bytes_twice_stored_once(store):
    a = run(store, [PDF])
    b = run(store, [PDF], announced=Announced(source_url=URL + "?copy", name="copy.pdf"))
    assert a.files[0].file_id == b.files[0].file_id
    assert a.files[0].storage_path == b.files[0].storage_path
    assert len(blobs(store)) == 1 and temp_files(store) == []


def test_interrupted_download_leaves_nothing(store):
    def broken():
        yield PDF[:50]
        raise ConnectionError("reset by peer")

    with pytest.raises(ConnectionError):
        run(store, broken())
    assert blobs(store) == [] and temp_files(store) == []


def test_writer_without_commit_leaves_nothing(store):
    with store.writer() as w:
        w.write(b"half")
        assert w.temp_path.exists()
    assert not w.temp_path.exists() and blobs(store) == []


def test_writer_raises_too_large_and_drops_file(store):
    w = store.writer(limit=3)
    with pytest.raises(TooLarge):
        w.write(b"four")
    assert temp_files(store) == []


def test_clean_temp_removes_leftovers(store):
    (store.tmp_dir / "crash.part").write_bytes(b"x")
    assert store.clean_temp() == 1 and temp_files(store) == []


def test_html_where_pdf_expected_is_skipped(store):
    page = b"<!DOCTYPE html><html><form><input type=password></form></html>"
    res = run(store, [page], headers={"Content-Type": "text/html; charset=utf-8"})
    assert res.skipped == SkipReason.login_required
    assert res.files[0].content_type == "text/html"
    assert blobs(store) == [] and temp_files(store) == []
    assert is_provisional_id(res.links[0].file_id)


def test_judge_gets_the_facts(store):
    seen = []

    def judge(facts):
        seen.append(facts)
        return None

    dl = StaticDownload(status=200, headers={"Content-Type": "application/pdf; x=y", "Content-Length": str(len(PDF))},
                        body=[PDF], final_url="https://files.example/x/Plan.pdf")
    store_document(dl, Announced(source_url=URL, size_bytes=len(PDF), content_type="application/pdf"),
                   store=store, judge=judge, portal_id="p1", tender_id="T-1")
    (f,) = seen
    assert f.first_bytes == PDF[: store.settings.sniff_bytes] and f.size_bytes == len(PDF)
    assert f.content_type == "application/pdf" and f.content_length == len(PDF)
    assert f.announced_size == len(PDF) and f.file_name == "Plan.pdf"


def test_http_error_is_skipped(store):
    res = run(store, [b"not found"], status=404)
    assert res.skipped == SkipReason.http_error and blobs(store) == []


def test_open_resolve_and_remove(store):
    rec = run(store, [PDF]).files[0]
    with store.open(rec.storage_path) as fh:
        assert fh.read() == PDF
    with pytest.raises(ValueError):
        store.resolve("../outside")
    with pytest.raises(ValueError):
        store.resolve("files/.tmp/x.part")
    assert store.remove(rec.storage_path) is True
    assert store.remove(rec.storage_path) is False
