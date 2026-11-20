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


# == An answer that breaks off after its headers ==

class _BreaksOff(httpx.SyncByteStream):
    """A body that starts and then fails, as a stalled or reset connection does."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def __iter__(self):
        yield b"%PDF-1.4 "
        raise self.error


def test_a_body_that_breaks_off_is_no_answer_and_is_tried_again():
    fetcher, server, _ = make_fetcher(lambda r: httpx.Response(
        200, headers={"content-type": "text/html"}, stream=_BreaksOff(httpx.ReadTimeout("stalled"))))
    got = fetcher.fetch("p1", f"{BASE}/list")
    assert (got.status, got.answer.error, got.tries, got.body) == (None, ErrorKind.timeout, 3, b"")
    assert len(server.seen) == 3 and got.transport is Transport.outage

    answers = iter([httpx.Response(200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(b"not gzip")),
                    html("ok")])
    fetcher, _, _ = make_fetcher(lambda r: next(answers))
    got = fetcher.fetch("p1", f"{BASE}/list")  # a body that does not decode, then a good one
    assert got.ok and got.tries == 2


def test_a_download_that_breaks_off_raises_fetch_failed_not_an_httpx_error(tmp_path):
    fetcher, _, _ = make_fetcher(lambda r: httpx.Response(
        200, headers={"content-type": "application/pdf"}, stream=_BreaksOff(httpx.ReadError("reset"))))
    files = FileStore(DocsSettings(data_dir=tmp_path))
    with pytest.raises(FetchFailed) as caught:
        with fetcher.download("p1", f"{BASE}/files/a.pdf") as download:
            store_document(download, Announced(source_url=f"{BASE}/files/a.pdf"), store=files,
                           judge=stand_in_judge, portal_id="p1", tender_id="T1")
    assert caught.value.answer.error is ErrorKind.connection and caught.value.url == f"{BASE}/files/a.pdf"


# == Addresses, text and headers ==

def test_params_are_added_to_a_query_already_in_the_address():
    fetcher, server, _ = make_fetcher(lambda r: html("x"))
    fetcher.fetch("p1", f"{BASE}/search?type=open&lang=de", params={"page": 2})
    assert dict(server.requests[-1].url.params) == {"type": "open", "lang": "de", "page": "2"}
    fetcher.fetch("p1", f"{BASE}/search?page=1&type=open", params={"page": 2})  # the same name: params wins
    assert dict(server.requests[-1].url.params) == {"type": "open", "page": "2"}


def test_text_finds_the_charset_in_the_header_the_page_or_the_bytes():
    words = "Straßenbau Köln"

    def page(content_type: str, body: bytes) -> str:
        fetcher, _, _ = make_fetcher(lambda r: httpx.Response(200, headers={"content-type": content_type},
                                                              content=body))
        return fetcher.fetch("p1", f"{BASE}/x").text

    latin = words.encode("iso-8859-1")
    assert page('text/html; charset="iso-8859-1"', latin) == words       # quoted in the header
    assert page("text/html; charset=ISO-8859-1", latin) == words
    assert page("text/html", b"<meta charset='iso-8859-1'>" + latin).endswith(words)
    assert page("text/html", b'<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-2">'
                + "Łódź".encode("iso-8859-2")).endswith("Łódź")
    assert page("text/html", words.encode("utf-8")) == words             # nothing named: UTF-8
    assert page("text/html", words.encode("cp1252")) == words            # nothing named and not UTF-8
    assert page("text/html; charset=no-such-charset", words.encode("utf-8")) == words


def test_a_redirect_to_another_host_does_not_carry_the_callers_credentials():
    def handler(request):
        if request.url.host == "portal.example" and request.url.path == "/a":
            return httpx.Response(302, headers={"location": request.url.params["to"]})
        return html("x")

    sent = {"Authorization": "Bearer secret", "Cookie": "sid=1", "Proxy-Authorization": "Basic x",
            "X-Requested-With": "XMLHttpRequest", "Content-Type": "application/x-www-form-urlencoded"}
    fetcher, server, _ = make_fetcher(handler)
    fetcher.fetch("p1", f"{BASE}/a", params={"to": "https://files.example/x"}, method="POST", data={"q": "1"},
                  headers=sent)
    first, last = server.requests[0], server.requests[-1]
    assert first.headers["authorization"] == "Bearer secret" and first.headers["content-type"] == sent["Content-Type"]
    assert last.url.host == "files.example" and last.method == "GET"
    assert not {"authorization", "cookie", "proxy-authorization", "content-type"} & set(last.headers)
    assert last.headers["x-requested-with"] == "XMLHttpRequest"
    assert sent["Authorization"] == "Bearer secret"  # the caller's own dict is left alone

    fetcher, server, _ = make_fetcher(handler)  # the same host: the credentials go along
    fetcher.fetch("p1", f"{BASE}/a", params={"to": "/b"}, headers=sent)
    assert server.requests[-1].headers["authorization"] == "Bearer secret"
    assert server.requests[-1].headers["content-type"] == sent["Content-Type"]  # a GET all along: untouched


@pytest.mark.parametrize("location", ["mailto:office@portal.example", "javascript:void(0)", "ftp://portal.example/f",
                                      "http://"])
def test_a_location_that_is_no_web_address_ends_the_walk_with_the_redirect_itself(location):
    fetcher, server, _ = make_fetcher(lambda r: httpx.Response(302, headers={"location": location}))
    got = fetcher.fetch("p1", f"{BASE}/a")
    assert (got.status, got.final_url, got.redirects, got.tries) == (302, f"{BASE}/a", (), 1)
    assert len(server.seen) == 1


@pytest.mark.parametrize("path, login", [
    ("/authority/123/tenders", False), ("/authorities", False), ("/contracting-authority/list", False),
    ("/auth", True), ("/auth/login", True), ("/authenticate", True), ("/Authentication", True),
    ("/authentification", True), ("/oauth2/authorize", True), ("/authorization", True), ("/anmelden", True),
])
def test_an_authority_page_is_not_a_login_page(path, login):
    def handler(request):
        if request.url.path == "/tenders":
            return httpx.Response(301, headers={"location": path})
        return html("<table id='tenders'></table>")

    fetcher, _, _ = make_fetcher(handler)
    answer = fetcher.fetch("p1", f"{BASE}/tenders").answer
    assert (answer.login_redirect == path) is login
    assert (block_sign(answer) is not None) is login
