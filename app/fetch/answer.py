"""What one request ran into, as the `Answer` facts that `app/checks` classifies (Q10, step 1).

The checks decide what an answer means; this module only reads the facts off the wire: the
status, a few headers, where the redirects ended, and signs in the first bytes of a page.
Presence of a sign is not a verdict: a captcha script on a page that arrived blocks nothing
(Q10, "only the outcome counts").
"""
from __future__ import annotations

import re
import ssl
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit

import httpx

from app.checks import Answer, ErrorKind

_PASSWORD_FIELD = re.compile(rb"""type\s*=\s*["']?password""", re.IGNORECASE)
# Ours: path words of login and single-sign-on pages, in the languages of Patterno's portals.
# "auth", "authenticate", "authentification" and "authorize" count; "authority" does not: a
# contracting authority's page is no login page.
_LOGIN_PATH = re.compile(
    r"(^|[/_.-])(log-?in|sign-?in|anmeld\w*|auth(?:enti\w*|ori[sz]\w*)?|sso|cas|connexion|identification|"
    r"accedi|logowanie|zaloguj\w*|inicio-?sesion|acceso)([/_.?-]|$)", re.IGNORECASE)
# Ours: a maintenance notice, in the languages of Patterno's portals (Q10, rule O1: an outage).
_MAINTENANCE = re.compile(
    rb"maintenance|wartungsarbeiten|\bwartung\b|mantenimiento|manutenzione|przerwa techniczna|"
    rb"prace serwisowe|onderhoud|temporarily unavailable|vor\xc3\xbcbergehend nicht (?:verf\xc3\xbcgbar|erreichbar)",
    re.IGNORECASE)
_HEADLINES = re.compile(rb"<(title|h1)[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
# Products whose markers prove a captcha is present (Q10, block signs). Presence only.
_CAPTCHAS: tuple[tuple[str, tuple[bytes, ...]], ...] = (
    ("reCAPTCHA", (b"google.com/recaptcha", b"g-recaptcha", b"recaptcha/api.js")),
    ("hCaptcha", (b"hcaptcha.com", b"h-captcha")),
    ("Cloudflare Turnstile", (b"challenges.cloudflare.com/turnstile", b"cf-turnstile")),
    ("Friendly Captcha", (b"frc-captcha", b"friendlycaptcha")),
    ("ALTCHA", (b"altcha-widget", b"altcha.org")),
    ("DataDome", (b"datadome",)),
    ("PerimeterX", (b"perimeterx", b"px-captcha")),
)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """A header by name, ignoring case (httpx.Headers already does; plain dicts may not)."""
    value = headers.get(name)
    if value is None:
        for key, v in headers.items():
            if key.lower() == name:
                return v
    return value


def looks_like_html(content_type: str | None, first_bytes: bytes) -> bool:
    if content_type and "html" in content_type.lower():
        return True
    head = first_bytes.lstrip()[:64].lower()
    return head.startswith((b"<!doctype html", b"<html"))


def login_path(redirects: Sequence[str], final_url: str) -> str | None:
    """The path of a login or sign-on page we were redirected to, if any."""
    if not redirects:
        return None
    path = urlsplit(final_url).path or "/"
    return path if _LOGIN_PATH.search(path) else None


def captcha_product(first_bytes: bytes) -> str | None:
    low = first_bytes.lower()
    for product, markers in _CAPTCHAS:
        if any(m in low for m in markers):
            return product
    return None


def maintenance_page(status: int, body: bytes) -> bool:
    """A maintenance notice: in the page's title or main heading, or anywhere in a 5xx page."""
    if any(_MAINTENANCE.search(text) for _, text in _HEADLINES.findall(body)):
        return True
    return status >= 500 and bool(_MAINTENANCE.search(body))


def answer_from_response(status: int, headers: Mapping[str, str], first_bytes: bytes, *,
                         final_url: str, redirects: Sequence[str] = (), page_load: bool = True,
                         via: str = "http") -> Answer:
    """The facts of one HTTP answer. `first_bytes` is the start of the body (a page) or empty."""
    content_type = _header(headers, "content-type")
    html = looks_like_html(content_type, first_bytes)
    body = first_bytes if html else b""
    return Answer(
        status=status, via=via, page_load=page_load,
        retry_after=_header(headers, "retry-after") is not None,
        www_authenticate=_header(headers, "www-authenticate") is not None,
        cf_mitigated=_header(headers, "cf-mitigated"),
        login_redirect=login_path(redirects, final_url),
        password_field=bool(_PASSWORD_FIELD.search(body)),
        request_rejected=b"request rejected" in body.lower() and b"support id" in body.lower(),
        incapsula=b"_incapsula_resource" in body.lower(),
        access_denied=b"access denied!" in body.lower(),
        captcha=captcha_product(body) if body else None,
        maintenance=maintenance_page(status, body) if body else False,
    )


def error_kind(exc: BaseException) -> ErrorKind:
    """Why a request got no HTTP answer: timeout, DNS, TLS, certificate or connection."""
    if isinstance(exc, httpx.TimeoutException):
        return ErrorKind.timeout
    seen: set[int] = set()
    cause: BaseException | None = exc
    while cause is not None and id(cause) not in seen:  # httpx wraps the socket and ssl errors
        seen.add(id(cause))
        if isinstance(cause, ssl.SSLCertVerificationError):
            return ErrorKind.certificate
        if isinstance(cause, ssl.SSLError):
            return ErrorKind.tls
        text = str(cause).lower()
        if "certificate verify failed" in text:
            return ErrorKind.certificate
        if any(w in text for w in ("name or service not known", "nodename nor servname", "getaddrinfo",
                                   "temporary failure in name resolution", "no address associated")):
            return ErrorKind.dns
        cause = cause.__cause__ or cause.__context__
    return ErrorKind.connection


def answer_from_error(exc: BaseException, *, page_load: bool = True, via: str = "http") -> Answer:
    """The facts of a request that got no HTTP answer."""
    kind = error_kind(exc)
    detail = str(exc)[:200] if kind is ErrorKind.certificate else None
    return Answer(error=kind, error_detail=detail, via=via, page_load=page_load)
