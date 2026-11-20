"""Step 2 (O1 list, O2 file): only the outcome counts."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.checks import (  # noqa: E402
    Answer, Cause, DownloadFacts, Effect, ErrorKind, ListFacts, cause_of, effect_of, file_outcome, list_outcome,
    skip_reason,
)
from app.models import Severity, SkipReason  # noqa: E402

PDF = b"%PDF-1.7\n"
ZIP = b"PK\x03\x04\x14\x00"
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
DOWNLOAD = Answer(status=200, page_load=False)


# -- O1 ----------------------------------------------------------------------

def test_a_list_with_rows_arrived():
    result = list_outcome("r1", ListFacts(rows=23))
    assert result.passed and result.name == "list_outcome" and "23 rows" in result.message


@pytest.mark.parametrize("facts, proof", [
    (ListFacts(rows=0, empty_marker=True), "notice"),
    (ListFacts(rows=0, printed_total=0), "total"),
    (ListFacts(rows=0, api_empty=True), "api"),
])
def test_a_provably_empty_list_arrived(facts, proof):
    result = list_outcome("r1", facts)
    assert result.passed and result.observed["empty"] == proof


def test_an_empty_list_without_proof_is_suspect_not_a_pass():
    result = list_outcome("r1", ListFacts(rows=0))
    assert not result.passed and effect_of(result) is Effect.suspect
    assert cause_of(result) is Cause.breakage and result.severity is Severity.warn
    assert result.observed["second_look"] == "reread"


def test_no_rows_while_the_portal_prints_a_total_is_not_proof_of_empty():
    assert effect_of(list_outcome("r1", ListFacts(rows=0, printed_total=23))) is Effect.suspect


def test_a_captcha_marker_does_not_matter_when_the_list_arrived():
    result = list_outcome("r1", ListFacts(rows=23, answer=Answer(status=200, captcha="reCAPTCHA")))
    assert result.passed and effect_of(result) is Effect.none


def test_a_missing_list_with_a_block_sign_is_a_suspect_block_confirmed_through_the_browser():
    wall = Answer(status=200, login_redirect="/anmelden", password_field=True)
    result = list_outcome("r1", ListFacts(rows=0, answer=wall))
    assert effect_of(result) is Effect.suspect and cause_of(result) is Cause.block
    assert result.observed["block_sign"] == "login" and result.observed["second_look"] == "browser"
    assert result.message == ("Login required: the tender list redirects to /anmelden and shows a password "
                              "field. We do not log in.")


def test_a_cloudflare_challenge_reads_as_bot_protection():
    result = list_outcome("r1", ListFacts(rows=0, answer=Answer(status=403, cf_mitigated="challenge")))
    assert result.message == "Bot protection blocks the tender list (Cloudflare challenge). We do not solve captchas."


def test_http_418_with_an_access_denied_page_is_a_refusal():
    result = list_outcome("r1", ListFacts(rows=0, answer=Answer(status=418, access_denied=True)))
    assert cause_of(result) is Cause.block and result.observed["block_sign"] == "refused"


def test_a_usual_login_box_on_a_broken_list_page_is_a_breakage_not_a_block():
    page = Answer(status=200, password_field=True)
    assert cause_of(list_outcome("r1", ListFacts(rows=0, answer=page))) is Cause.block
    assert cause_of(list_outcome("r1", ListFacts(rows=0, answer=page),
                                 usual_signs={"password_field"})) is Cause.breakage


@pytest.mark.parametrize("answer", [
    Answer(status=200, maintenance=True),
    Answer(status=503),
    Answer(error=ErrorKind.timeout),
])
def test_a_maintenance_page_or_no_answer_is_a_suspect_outage(answer):
    result = list_outcome("r1", ListFacts(rows=0, answer=answer))
    assert effect_of(result) is Effect.suspect and cause_of(result) is Cause.outage


# -- O2 ----------------------------------------------------------------------

@pytest.mark.parametrize("name, first_bytes", [
    ("LV.pdf", PDF), ("unterlagen.zip", ZIP), ("Angebot.docx", ZIP), ("Preise.xlsx", ZIP),
    ("alt.doc", OLE), ("alt.xls", OLE), ("plan.dwg", b"AC1027"), ("README", b"hello"),
])
def test_a_file_whose_first_bytes_fit_its_kind_arrived(name, first_bytes):
    facts = DownloadFacts(file_name=name, answer=DOWNLOAD, first_bytes=first_bytes, size_bytes=1200,
                          announced_size=1200)
    assert file_outcome("r1", facts).passed


@pytest.mark.parametrize("facts, problem", [
    (DownloadFacts(file_name="LV.pdf", answer=Answer(status=404, page_load=False)), "status"),
    (DownloadFacts(file_name="LV.pdf", answer=DOWNLOAD, first_bytes=b"<!DOCTYPE html><html>", size_bytes=900,
                   content_type="text/html; charset=utf-8"), "html"),
    (DownloadFacts(file_name="LV.pdf", answer=DOWNLOAD, first_bytes=b"  <html><body>", size_bytes=900), "html"),
    (DownloadFacts(file_name="LV.pdf", answer=DOWNLOAD, first_bytes=ZIP, size_bytes=900), "first_bytes"),
    (DownloadFacts(file_name="all.zip", answer=DOWNLOAD, first_bytes=PDF, size_bytes=900), "first_bytes"),
    (DownloadFacts(file_name="alt.doc", answer=DOWNLOAD, first_bytes=ZIP, size_bytes=900), "first_bytes"),
    (DownloadFacts(file_name="plan.dwg", answer=DOWNLOAD, first_bytes=b"", size_bytes=0), "empty"),
    (DownloadFacts(file_name="LV.pdf", answer=DOWNLOAD, first_bytes=PDF, size_bytes=900, announced_size=1200), "size"),
])
def test_a_download_that_is_not_the_file_is_a_warning_with_cause_breakage(facts, problem):
    result = file_outcome("r1", facts)
    assert not result.passed and result.name == "file_outcome"
    assert result.observed["problem"] == problem and cause_of(result) is Cause.breakage
    # One file is not the portal: the row warns, it never changes the state alone.
    assert result.severity is Severity.warn and effect_of(result) is Effect.note


def test_a_login_form_served_with_200_in_place_of_a_file_is_a_block():
    form = Answer(status=200, page_load=False, password_field=True)
    result = file_outcome("r1", DownloadFacts(file_name="LV.pdf", answer=form, first_bytes=b"<html><form>",
                                              size_bytes=2100, content_type="text/html"))
    assert cause_of(result) is Cause.block and effect_of(result) is Effect.note
    assert "Login required" in result.message and "LV.pdf" in result.message


def test_an_aws_waf_challenge_on_a_download_is_a_block():
    result = file_outcome("r1", DownloadFacts(file_name="LV.pdf", answer=Answer(status=202, page_load=False)))
    assert cause_of(result) is Cause.block and "AWS WAF" in result.message


def test_a_file_that_does_not_answer_is_an_outage():
    result = file_outcome("r1", DownloadFacts(file_name="LV.pdf", answer=Answer(status=503, page_load=False)))
    assert cause_of(result) is Cause.outage and "HTTP 503" in result.message


def test_an_html_file_may_be_html():
    facts = DownloadFacts(file_name="bekanntmachung.html", answer=DOWNLOAD, first_bytes=b"<!DOCTYPE html>",
                          size_bytes=700, content_type="text/html")
    assert file_outcome("r1", facts).passed


@pytest.mark.parametrize("facts, reason", [
    (DownloadFacts(file_name="LV.pdf", answer=DOWNLOAD, first_bytes=PDF, size_bytes=900), None),
    (DownloadFacts(file_name="LV.pdf", answer=Answer(status=200, page_load=False, login_redirect="/login"),
                   first_bytes=b"<html>", size_bytes=900), SkipReason.login_required),
    (DownloadFacts(file_name="LV.pdf", answer=Answer(status=200, page_load=False, captcha="hCaptcha"),
                   first_bytes=b"<html>", size_bytes=900), SkipReason.captcha),
    (DownloadFacts(file_name="LV.pdf", answer=DOWNLOAD, first_bytes=b"<html>", size_bytes=900), SkipReason.not_a_file),
    (DownloadFacts(file_name="LV.pdf", answer=DOWNLOAD, first_bytes=ZIP, size_bytes=900), SkipReason.not_a_file),
    (DownloadFacts(file_name="LV.pdf", answer=Answer(status=404, page_load=False)), SkipReason.http_error),
    (DownloadFacts(file_name="LV.pdf", answer=Answer(status=403, page_load=False)), SkipReason.http_error),
    (DownloadFacts(file_name="LV.pdf", answer=Answer(error=ErrorKind.timeout, page_load=False)), SkipReason.http_error),
    (DownloadFacts(file_name="LV.pdf", answer=DOWNLOAD, first_bytes=PDF, size_bytes=900, announced_size=1200),
     SkipReason.http_error),
])
def test_a_failed_file_maps_onto_the_skip_reason_of_its_record(facts, reason):
    assert skip_reason(file_outcome("r1", facts)) is reason
