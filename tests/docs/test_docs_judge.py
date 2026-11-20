"""app/docs and app/checks together: the file outcome test (O2) as the judge of store_document."""
from __future__ import annotations

from app.checks import Answer, Effect, cause_of, effect_of, files_failed
from app.docs import Announced, StaticDownload, outcome_judge, store_document
from app.models import SkipReason
from tests.docs.conftest import PDF, blobs

LOGIN_PAGE = b"<!DOCTYPE html><html><body><form><input type='password' name='pw'></form></body></html>"
ERROR_PAGE = b"<!DOCTYPE html><html><body><h1>Seite nicht gefunden</h1></body></html>"


def fetch(store, results, body, *, name="LV.pdf", status=200, headers=None, **judge_options):
    download = StaticDownload(status=status, headers=headers or {"Content-Type": "application/pdf"}, body=[body])
    return store_document(download, Announced(source_url=f"https://portal.example/files/{name}", name=name),
                          store=store, judge=outcome_judge("r1", results, **judge_options),
                          portal_id="p1", tender_id="T-1")


def test_a_real_file_is_stored_and_its_row_passes(store):
    results = []
    stored = fetch(store, results, PDF)
    assert stored.skipped is None and stored.files[0].deliverable
    assert [(r.name, r.passed) for r in results] == [("file_outcome", True)]


def test_a_web_page_in_place_of_the_file_is_not_stored(store):
    results = []
    stored = fetch(store, results, ERROR_PAGE, headers={"Content-Type": "text/html"})
    assert stored.skipped is SkipReason.not_a_file and blobs(store) == []
    assert not results[0].passed and results[0].observed["problem"] == "html"


def test_a_login_page_in_place_of_the_file_is_login_required(store):
    results = []
    stored = fetch(store, results, LOGIN_PAGE, headers={"Content-Type": "text/html"})
    assert stored.skipped is SkipReason.login_required and blobs(store) == []
    assert cause_of(results[0]).value == "block"


def test_an_error_status_is_an_http_error(store):
    results = []
    assert fetch(store, results, b"gone", status=404).skipped is SkipReason.http_error


def test_content_length_is_only_held_against_the_bytes_when_asked(store):
    headers = {"Content-Type": "application/pdf", "Content-Length": str(len(PDF) + 50)}
    assert fetch(store, [], PDF, headers=headers).skipped is None  # a decoded body may differ from the header
    assert fetch(store, [], PDF, headers=headers, trust_content_length=True).skipped is SkipReason.http_error


def test_the_network_layer_can_say_more_about_the_answer(store):
    results = []
    stored = fetch(store, results, ERROR_PAGE, headers={"Content-Type": "text/html"},
                   answer_for=lambda facts: Answer(status=facts.status, page_load=False, cf_mitigated="challenge"))
    assert stored.skipped is SkipReason.captcha


def test_the_rows_of_a_read_feed_the_files_check(store):
    # One login page among files that arrive: the rest are published and the portal is not failed.
    results = []
    for i in range(4):
        fetch(store, results, PDF + bytes([i]), name=f"file{i}.pdf")
    fetch(store, results, LOGIN_PAGE, name="geheim.pdf", headers={"Content-Type": "text/html"})
    verdict = files_failed("r1", results, earlier_failed=0, earlier_files=40, retried=True)
    assert effect_of(verdict) is Effect.note and "the rest are published" in verdict.message
