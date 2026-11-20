"""The Fetcher on an in-process transport: redirects, rules T1 and T2, answers' facts, sessions, downloads."""
from __future__ import annotations

import hashlib
import json
import ssl

import httpx
import pytest

from app.checks import ErrorKind, Transport, block_sign, transport_check
from app.docs import Announced, DocsSettings, FileStore, store_document
from app.fetch import FetchFailed
from app.models import SkipReason
from tests.docs.conftest import PDF, stand_in_judge
from tests.fetch.conftest import BASE, html, make_fetcher


def test_redirects_are_walked_hop_by_hop_each_in_its_own_slot():
    def handler(request):
        return {"/a": httpx.Response(302, headers={"location": "/b"}),
                "/b": httpx.Response(301, headers={"location": f"{BASE}/c"})}.get(
            request.url.path, html("<table id='tenders'></table>"))

    fetcher, server, _ = make_fetcher(handler)
    got = fetcher.fetch("p1", f"{BASE}/a")
    assert server.times() == [0.0, 1.0, 2.0]  # three requests reach the portal, one second apart
    assert got.ok and got.final_url == f"{BASE}/c"
    assert got.redirects == (f"{BASE}/a", f"{BASE}/b")
    assert "tenders" in got.text and got.tries == 1 and got.transport is Transport.answered


def test_a_form_post_answered_with_303_continues_as_get():
    def handler(request):
        if request.url.path == "/search":
            assert request.method == "POST" and b"q=bau" in request.content
            return httpx.Response(303, headers={"location": "/results?page=1"})
        return html(f"method={request.method}")

    fetcher, server, _ = make_fetcher(handler)
    got = fetcher.fetch("p1", f"{BASE}/search", method="POST", data={"q": "bau"})
    assert "method=GET" in got.text and server.requests[-1].content == b""


def test_too_many_redirects_end_with_the_last_answer():
    fetcher, server, _ = make_fetcher(lambda r: httpx.Response(302, headers={"location": "/loop"}), max_redirects=3)
    got = fetcher.fetch("p1", f"{BASE}/loop")
    assert got.status == 302 and len(got.redirects) == 3 and len(server.seen) == 4


def test_json_and_query_parameters():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"echo": json.loads(request.content)})
        return httpx.Response(200, json={"page": request.url.params["page"]})

    fetcher, _, _ = make_fetcher(handler)
    assert fetcher.fetch("p1", f"{BASE}/api", params={"page": 2}).json() == {"page": "2"}
    assert fetcher.fetch("p1", f"{BASE}/api", method="POST", json={"size": 100}).json() == {"echo": {"size": 100}}


# == Rule T1: not answering now ==

def test_an_outage_is_tried_again_with_growing_pauses():
    answers = iter([httpx.Response(503), httpx.Response(502), html("ok")])
    fetcher, server, _ = make_fetcher(lambda r: next(answers))
    got = fetcher.fetch("p1", f"{BASE}/list")
    assert got.ok and got.tries == 3
    assert server.times() == [0.0, 1.0, 3.0]  # pauses of 1 s then 2 s (base 2 s, doubling, half fixed)


def test_three_tries_then_the_checks_call_it_an_outage():
    fetcher, server, _ = make_fetcher(lambda r: httpx.Response(503))
    got = fetcher.fetch("p1", f"{BASE}/list")
    assert (got.status, got.tries, got.transport) == (503, 3, Transport.outage) and len(server.seen) == 3
    check = transport_check("run1", got.answer, tries=got.tries, at_slowest_rate=got.at_slowest_rate)
    assert check.name == "outage" and not check.passed


def test_no_answer_at_all_carries_the_kind_of_error():
    def dns(request):
        raise httpx.ConnectError("[Errno -2] Name or service not known", request=request)

    fetcher, _, _ = make_fetcher(dns)
    got = fetcher.fetch("p1", f"{BASE}/list")
    assert got.status is None and got.answer.error is ErrorKind.dns and got.tries == 3

    fetcher, _, _ = make_fetcher(lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)))
    assert fetcher.fetch("p1", f"{BASE}/list").answer.error is ErrorKind.timeout


def test_a_certificate_that_does_not_verify_is_not_tried_again():
    def bad_certificate(request):
        error = httpx.ConnectError("certificate verify failed", request=request)
        error.__cause__ = ssl.SSLCertVerificationError("unable to get local issuer certificate")
        raise error

    fetcher, server, _ = make_fetcher(bad_certificate)
    got = fetcher.fetch("p1", f"{BASE}/list")
    assert got.answer.error is ErrorKind.certificate and got.tries == 1 and len(server.seen) == 1
    assert got.transport is Transport.certificate  # T4: the browser gets one try, never verify=False


def test_a_long_retry_after_is_handed_back_not_waited_for():
    fetcher, server, _ = make_fetcher(lambda r: httpx.Response(503, headers={"retry-after": "3600"}))
    got = fetcher.fetch("p1", f"{BASE}/list")
    assert got.tries == 1 and got.retry_after_seconds == 3600 and len(server.seen) == 1


# == Rule T2: slow down ==

def test_a_rate_limit_halves_the_pace_and_waits_its_retry_after():
    answers = iter([httpx.Response(429, headers={"retry-after": "5"}), html("ok")])
    fetcher, server, _ = make_fetcher(lambda r: next(answers))
    got = fetcher.fetch("p1", f"{BASE}/list")
    assert got.ok and got.tries == 1 and not got.at_slowest_rate
    assert server.times() == [0.0, 5.0]
    assert fetcher.limiter.interval("p1") == 2.0  # kept for the portal


def test_a_403_with_retry_after_is_a_rate_limit_not_a_block():
    answers = iter([httpx.Response(403, headers={"retry-after": "1"}), html("ok")])
    fetcher, _, _ = make_fetcher(lambda r: next(answers))
    assert fetcher.fetch("p1", f"{BASE}/list").ok


def test_still_rate_limited_at_the_slowest_pace_is_reported():
    fetcher, server, _ = make_fetcher(lambda r: httpx.Response(429))
    got = fetcher.fetch("p1", f"{BASE}/list")
    assert got.at_slowest_rate and got.status == 429 and len(server.seen) == 5
    assert server.times() == [0.0, 1.0, 3.0, 7.0, 15.0]  # 1, 2, 4, 8 s apart: the pace halves each time
    check = transport_check("run1", got.answer, tries=got.tries, at_slowest_rate=got.at_slowest_rate)
    assert check.name == "rate_limited" and not check.passed


# == The facts of an answer, for the checks ==

def test_a_redirect_to_a_login_page_with_a_password_field_is_a_login_sign():
    def handler(request):
        if request.url.path == "/tenders":
            return httpx.Response(302, headers={"location": "/anmelden?next=/tenders"})
        return html("<form><input type='password' name='pw'></form>")

    fetcher, _, _ = make_fetcher(handler)
    answer = fetcher.fetch("p1", f"{BASE}/tenders").answer
    assert answer.login_redirect == "/anmelden" and answer.password_field
    assert block_sign(answer).name == "login"


def test_bot_walls_and_captchas_are_read_off_headers_and_pages():
    pages = {
        "/cf": html("Just a moment", 403, {"cf-mitigated": "challenge"}),
        "/f5": html("Request Rejected. Your support ID is: 123"),
        "/imperva": html("<iframe src='/_Incapsula_Resource?x=1'></iframe>"),
        "/recaptcha": html("<div class='g-recaptcha'></div>"),
        "/basic": httpx.Response(401, headers={"www-authenticate": "Basic realm=x"}),
        "/maintenance": html("<h1>Wartungsarbeiten</h1> Bitte später.", 503),
        "/footer": html("<p>Wartung: jeden Sonntag 2-4 Uhr</p><table id='list'></table>"),
    }
    fetcher, _, _ = make_fetcher(lambda r: pages[r.url.path])
    facts = {path: fetcher.fetch("p1", f"{BASE}{path}").answer for path in pages}
    assert facts["/cf"].cf_mitigated == "challenge"
    assert facts["/f5"].request_rejected and facts["/imperva"].incapsula
    assert facts["/recaptcha"].captcha == "reCAPTCHA"
    assert facts["/basic"].www_authenticate
    assert facts["/maintenance"].maintenance
    assert not facts["/footer"].maintenance  # a word in a footer is not a maintenance page


def test_each_portal_keeps_its_own_cookies():
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(200, headers={"set-cookie": "JSESSIONID=abc; Path=/"}, text="ok")
        return httpx.Response(200, text=request.headers.get("cookie", "none"))

    fetcher, _, _ = make_fetcher(handler)
    fetcher.fetch("p1", f"{BASE}/start")
    assert fetcher.fetch("p1", f"{BASE}/list").text == "JSESSIONID=abc"
    assert fetcher.fetch("p2", f"{BASE}/list").text == "none"
    fetcher.forget("p1")
    assert fetcher.fetch("p1", f"{BASE}/list").text == "none"


# == Downloads, as app/docs takes them ==

def test_a_download_streams_into_app_docs(tmp_path):
    fetcher, _, _ = make_fetcher(lambda r: httpx.Response(200, headers={"content-type": "application/pdf"},
                                                          content=PDF))
    files = FileStore(DocsSettings(data_dir=tmp_path))
    with fetcher.download("p1", f"{BASE}/files/lv.pdf") as download:
        result = store_document(download, Announced(source_url=f"{BASE}/files/lv.pdf", name="lv.pdf"),
                                store=files, judge=stand_in_judge, portal_id="p1", tender_id="T1")
    (record,) = result.files
    assert record.deliverable and record.sha256 == hashlib.sha256(PDF).hexdigest()


def test_a_login_page_in_place_of_a_file_is_handed_over_for_app_docs_to_judge(tmp_path):
    pages = {"/files/a.pdf": html("<form><input type=password></form>"),  # 200, but a page
             "/files/b.pdf": html("Forbidden", 403)}
    fetcher, _, _ = make_fetcher(lambda r: pages[r.url.path])
    files = FileStore(DocsSettings(data_dir=tmp_path))
    reasons = []
    for path in pages:
        with fetcher.download("p1", f"{BASE}{path}") as download:
            result = store_document(download, Announced(source_url=f"{BASE}{path}"), store=files,
                                    judge=stand_in_judge, portal_id="p1", tender_id="T1")
        reasons.append(result.skipped)
    assert reasons == [SkipReason.login_required, SkipReason.http_error]


def test_a_download_with_no_answer_raises():
    def reset(request):
        raise httpx.ConnectError("connection reset by peer", request=request)

    fetcher, _, _ = make_fetcher(reset)
    with pytest.raises(FetchFailed) as caught:
        with fetcher.download("p1", f"{BASE}/files/a.pdf"):
            pass
    assert caught.value.tries == 3 and caught.value.answer.error is ErrorKind.connection
