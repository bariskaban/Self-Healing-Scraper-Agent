"""Step 1 (T1, T2, T4) and the block signs of research/q10-failure-rules.md. No request is made."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.checks import (  # noqa: E402
    Answer, Cause, Effect, ErrorKind, Transport, block_check, block_sign, cause_of, classify_answer,
    effect_of, robots_check, transport_check,
)
from app.models import Severity  # noqa: E402


@pytest.mark.parametrize("status", [408, 500, 502, 503, 504, 520, 521, 522, 523, 524])
def test_t1_statuses_are_the_outage_class(status):
    assert classify_answer(Answer(status=status)) is Transport.outage


@pytest.mark.parametrize("error", [ErrorKind.timeout, ErrorKind.dns, ErrorKind.tls, ErrorKind.connection])
def test_t1_errors_are_the_outage_class(error):
    assert classify_answer(Answer(error=error)) is Transport.outage


@pytest.mark.parametrize("answer", [
    Answer(status=429),
    Answer(status=403, retry_after=True),
    Answer(status=503, retry_after=True),
    Answer(status=403, over_rate=True),   # Poland's portal answers 403 above 30 requests a minute
])
def test_t2_rate_limits(answer):
    assert classify_answer(answer) is Transport.rate_limited


@pytest.mark.parametrize("status", [200, 202, 301, 401, 403, 404, 418])
def test_other_statuses_are_judged_by_their_outcome(status):
    assert classify_answer(Answer(status=status)) is Transport.answered


def test_t4_certificate_is_its_own_class():
    assert classify_answer(Answer(error=ErrorKind.certificate)) is Transport.certificate


def test_an_answer_passes_the_transport_check():
    result = transport_check("r1", Answer(status=200))
    assert result.passed and result.name == "outage"


def test_a_503_is_tried_three_times_before_it_is_an_outage():
    first = transport_check("r1", Answer(status=503), tries=1)
    assert effect_of(first) is Effect.suspect and first.observed["second_look"] == "retry"
    third = transport_check("r1", Answer(status=503), tries=3)
    assert effect_of(third) is Effect.outage and cause_of(third) is Cause.outage
    assert third.name == "outage" and third.severity is Severity.outage
    assert "HTTP 503" in third.message and "3 tries" in third.message


def test_a_429_is_a_warning_while_slowing_down_works():
    result = transport_check("r1", Answer(status=429))
    assert result.name == "rate_limited" and result.severity is Severity.warn
    assert effect_of(result) is Effect.note


def test_a_rate_limit_at_the_slowest_rate_is_an_outage():
    result = transport_check("r1", Answer(status=429), at_slowest_rate=True)
    assert result.name == "rate_limited" and effect_of(result) is Effect.outage
    assert "one request per 10 seconds" in result.message


def test_certificate_goes_through_the_browser_once_then_is_an_outage():
    plain = transport_check("r1", Answer(error=ErrorKind.certificate, error_detail="incomplete chain"))
    assert effect_of(plain) is Effect.suspect and plain.observed["second_look"] == "browser"
    browser = transport_check("r1", Answer(error=ErrorKind.certificate, error_detail="incomplete chain",
                                           via="browser"))
    assert effect_of(browser) is Effect.outage
    assert "certificate" in browser.message and "incomplete chain" in browser.message


@pytest.mark.parametrize("answer, name, words", [
    (Answer(status=401, www_authenticate=True), "login", "HTTP 401"),
    (Answer(status=200, login_redirect="/anmelden", password_field=True), "login", "/anmelden"),
    (Answer(status=200, login_redirect="/sso/login"), "login", "/sso/login"),
    (Answer(status=200, password_field=True), "login", "password field"),
    (Answer(status=403, cf_mitigated="challenge"), "captcha", "Cloudflare challenge"),
    (Answer(status=202, page_load=False), "captcha", "AWS WAF challenge"),
    (Answer(status=405, page_load=False), "captcha", "AWS WAF captcha"),
    (Answer(status=200, request_rejected=True), "refused", "Request Rejected"),
    (Answer(status=200, incapsula=True), "captcha", "Imperva"),
    (Answer(status=418, access_denied=True), "refused", "HTTP 418"),
    (Answer(status=200, captcha="reCAPTCHA"), "captcha", "reCAPTCHA"),
    (Answer(status=403), "refused", "HTTP 403"),
])
def test_block_signs_from_the_research_table(answer, name, words):
    sign = block_sign(answer)
    assert sign is not None and sign.name == name and words in sign.what


@pytest.mark.parametrize("answer", [
    Answer(status=200),
    Answer(status=418),                    # a teapot without the access-denied page
    Answer(status=202),                    # 202 on a page load is not the AWS WAF sign
    Answer(status=200, access_denied=True),
    Answer(status=404),
])
def test_answers_without_a_block_sign(answer):
    assert block_sign(answer) is None


def test_signs_a_working_page_always_carried_are_not_counted():
    answer = Answer(status=200, password_field=True, captcha="reCAPTCHA")
    assert block_sign(answer, usual_signs={"password_field", "reCAPTCHA"}) is None
    assert block_sign(answer, usual_signs={"password_field"}).name == "captcha"
    # A strong sign still counts.
    assert block_sign(Answer(status=200, login_redirect="/login", password_field=True),
                      usual_signs={"password_field"}).name == "login"


def test_a_captcha_marker_alone_is_never_a_block():
    answer = Answer(status=200, captcha="reCAPTCHA")
    assert classify_answer(answer) is Transport.answered
    row = block_check("r1", answer, outcome_missing=False)
    assert row.passed and row.name == "captcha" and effect_of(row) is Effect.none
    assert "Nothing is blocked" in row.message


def test_a_block_sign_with_a_missing_outcome_is_a_suspect_block():
    row = block_check("r1", Answer(status=418, access_denied=True), outcome_missing=True)
    assert row.name == "refused" and effect_of(row) is Effect.suspect
    assert cause_of(row) is Cause.block and row.observed["second_look"] == "browser"
    assert block_check("r1", Answer(status=200), outcome_missing=True) is None


def test_robots_txt_that_forbids_every_path_is_a_block_unless_switched_off():
    blocked = robots_check("r1", forbids_every_path=True)
    assert effect_of(blocked) is Effect.block and "robots.txt" in blocked.message
    assert robots_check("r1", forbids_every_path=True, ignored=True).passed
    assert robots_check("r1", forbids_every_path=False).passed
