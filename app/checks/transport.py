"""Step 1 of a read (Q10): did each request get an answer, and what did it run into?

The fetch layer hands over plain facts about one answer: the status, a few headers,
the kind of error, and small facts about the body. Nothing here opens a connection.

A block sign is looked at only when the outcome is missing (see `outcome.py`). The
presence of a captcha marker or a password field never classifies as a block here.
"""
from __future__ import annotations

from collections.abc import Collection
from enum import StrEnum
from typing import Literal

from app.models import CheckResult, Severity

from .result import Cause, Facts, failed, note, passed, suspect
from .settings import DEFAULT_SETTINGS, CheckSettings
from .words import count

# HTTP statuses that mean "not answering now" (rule T1; conventions, rule 8).
OUTAGE_STATUSES = frozenset({408, 500, 502, 503, 504, 520, 521, 522, 523, 524})


class ErrorKind(StrEnum):
    """Why a request got no HTTP answer at all."""

    timeout = "timeout"
    dns = "dns"
    tls = "tls"
    connection = "connection"    # reset or refused
    certificate = "certificate"  # the certificate does not verify


_ERROR_WORDS = {
    ErrorKind.timeout: "timeout",
    ErrorKind.dns: "DNS failure",
    ErrorKind.tls: "TLS failure",
    ErrorKind.connection: "connection reset",
    ErrorKind.certificate: "certificate not verified",
}


class Answer(Facts):
    """What one request ran into, as the fetch layer saw it."""

    status: int | None = None
    error: ErrorKind | None = None
    error_detail: str | None = None       # for a certificate, what is wrong with it: "incomplete chain"
    via: Literal["http", "browser"] = "http"
    page_load: bool = True                # False for a file download or an API call
    retry_after: bool = False             # the answer carries a Retry-After header
    over_rate: bool = False               # it came while we sent faster than the portal allows
    www_authenticate: bool = False        # the answer carries WWW-Authenticate
    cf_mitigated: str | None = None       # value of the cf-mitigated header
    login_redirect: str | None = None     # path of the login or single-sign-on page we ended on
    password_field: bool = False          # the page shows a password field
    request_rejected: bool = False        # body says "Request Rejected ... Your support ID is"
    incapsula: bool = False               # an _Incapsula_Resource frame or script
    access_denied: bool = False           # an "Access Denied!" page
    captcha: str | None = None            # product whose marker is on the page or in its cookies
    maintenance: bool = False             # the portal's own maintenance page


class Transport(StrEnum):
    """The class of one answer, before anyone looks at its content."""

    answered = "answered"          # judge it by its outcome
    outage = "outage"              # T1: try again, then an outage
    rate_limited = "rate_limited"  # T2: halve the portal's request rate and go on
    certificate = "certificate"    # T4: try once through the browser, never switch verification off


def classify_answer(answer: Answer) -> Transport:
    """Class of one answer: answered, outage (T1), rate limit (T2) or certificate (T4)."""
    if answer.error is ErrorKind.certificate:
        return Transport.certificate
    if answer.error is not None or answer.status is None:
        return Transport.outage
    if answer.status == 429:
        return Transport.rate_limited
    if answer.status in (403, 503) and (answer.retry_after or answer.over_rate):
        return Transport.rate_limited
    if answer.status in OUTAGE_STATUSES:
        return Transport.outage
    return Transport.answered


def answer_words(answer: Answer) -> str:
    """'HTTP 503', 'DNS failure' and so on, for a message."""
    if answer.error is not None:
        return _ERROR_WORDS[answer.error]
    return f"HTTP {answer.status}" if answer.status is not None else "no answer"


class BlockSign(Facts):
    """A sign that a login or bot wall stands in the way. It counts only when the outcome is missing."""

    name: Literal["login", "captcha", "refused"]
    what: str          # the sign in words, as it goes into the reason
    weak: bool = False  # it only proves a product or a login box is on the page


def block_sign(answer: Answer, usual_signs: Collection[str] = ()) -> BlockSign | None:
    """The strongest block sign an answer carries, from the table in Q10; None when it carries none.

    `usual_signs` names weak signs this portal's pages carried while they worked
    ("password_field", or a captcha product): those are not counted.
    """
    if answer.cf_mitigated == "challenge":
        return BlockSign(name="captcha", what="Cloudflare challenge")
    if answer.status == 401:
        asks = " and asks for a user name and password" if answer.www_authenticate else ""
        return BlockSign(name="login", what=f"answers HTTP 401{asks}")
    password = answer.password_field and "password_field" not in usual_signs
    if answer.login_redirect and password:
        return BlockSign(name="login", what=f"redirects to {answer.login_redirect} and shows a password field")
    if answer.login_redirect:
        return BlockSign(name="login", what=f"redirects to {answer.login_redirect}")
    if not answer.page_load and answer.status in (202, 405):
        return BlockSign(name="captcha", what="AWS WAF challenge" if answer.status == 202 else "AWS WAF captcha")
    if answer.request_rejected:
        return BlockSign(name="refused", what="a 'Request Rejected' page")
    if answer.incapsula:
        return BlockSign(name="captcha", what="Imperva")
    if answer.status == 418 and answer.access_denied:
        return BlockSign(name="refused", what="HTTP 418 with an 'Access Denied!' page")
    if password:
        return BlockSign(name="login", what="shows a password field", weak=True)
    if answer.captcha and answer.captcha not in usual_signs:
        return BlockSign(name="captcha", what=answer.captcha, weak=True)
    if answer.status == 403:
        return BlockSign(name="refused", what="HTTP 403")
    return None


def block_sentence(sign: BlockSign, subject: str) -> str:
    """The reason sentence for a block of `subject` ('the tender list', 'the file LV.pdf')."""
    if sign.name == "login":
        return f"Login required: {subject} {sign.what}. We do not log in."
    if sign.name == "captcha":
        return f"Bot protection blocks {subject} ({sign.what}). We do not solve captchas."
    return f"The portal refuses {subject} ({sign.what}). We do not work around a refusal."


def _second_look(answer: Answer) -> str:
    return "browser" if answer.via == "http" else "reread"


def transport_check(run_id: str, answer: Answer, *, tries: int = 1, at_slowest_rate: bool = False,
                    settings: CheckSettings = DEFAULT_SETTINGS) -> CheckResult:
    """T1, T2, T4: `outage` or `rate_limited` for the last answer of a request after `tries` tries."""
    kind = classify_answer(answer)
    words = answer_words(answer)
    seen = {"status": answer.status, "error": answer.error.value if answer.error else None,
            "via": answer.via, "tries": tries}
    if kind is Transport.answered:
        return passed(run_id, "outage", f"The portal answered ({words}).", observed=seen)
    if kind is Transport.rate_limited:
        if not at_slowest_rate:
            return note(run_id, "rate_limited",
                        f"The portal asked us to slow down ({words}). Its request rate was halved.", observed=seen)
        pace = f"one request per {settings.slowest_request_interval_seconds:g} seconds"
        return failed(run_id, "rate_limited", f"The portal still answers {words} at {pace}, our slowest rate.",
                      cause=Cause.outage, observed={**seen, "detail": f"{words} at our slowest rate"})
    if kind is Transport.certificate:
        fault = f" ({answer.error_detail})" if answer.error_detail else ""
        if answer.via == "http":
            return suspect(run_id, "outage",
                           f"The portal's certificate cannot be verified in the plain client{fault}.",
                           if_confirmed=Cause.outage, second_look="browser", observed=seen)
        return failed(run_id, "outage",
                      f"The portal's certificate cannot be verified{fault}, in the plain client and in the "
                      "browser. We do not read a site we cannot verify.",
                      cause=Cause.outage, observed={**seen, "certificate": True})
    if tries < settings.request_tries:
        return suspect(run_id, "outage", f"No answer on try {tries} of {settings.request_tries} ({words}).",
                       if_confirmed=Cause.outage, second_look="retry", observed=seen)
    detail = f"{words}, {count(tries, 'try', 'tries')}"
    return failed(run_id, "outage", f"The portal did not answer ({detail}).", cause=Cause.outage,
                  observed={**seen, "detail": detail})


def block_check(run_id: str, answer: Answer, *, outcome_missing: bool, subject: str = "the tender list",
                usual_signs: Collection[str] = ()) -> CheckResult | None:
    """`login`, `captcha` or `refused` for a block sign on the page; None when the page carries none."""
    sign = block_sign(answer, usual_signs)
    if sign is None:
        return None
    seen = {"sign": sign.what, "via": answer.via, "status": answer.status}
    if not outcome_missing:
        return passed(run_id, sign.name, f"The page carries a sign of a wall ({sign.what}), but {subject} arrived. "
                      "Nothing is blocked.", severity=Severity.block, observed=seen)
    return suspect(run_id, sign.name, block_sentence(sign, subject), if_confirmed=Cause.block,
                   second_look=_second_look(answer), observed=seen)


def robots_check(run_id: str, *, forbids_every_path: bool, ignored: bool = False) -> CheckResult:
    """`robots`: a portal whose robots.txt forbids every path is a block, unless the test switch is on."""
    seen = {"forbids_every_path": forbids_every_path, "ignored": ignored}
    if not forbids_every_path:
        return passed(run_id, "robots", "robots.txt allows us to read the portal.",
                      severity=Severity.block, observed=seen)
    if ignored:
        return passed(run_id, "robots", "robots.txt forbids every path; the test switch tells us to ignore it.",
                      severity=Severity.block, observed=seen)
    return failed(run_id, "robots", "The portal's robots.txt forbids every path. We obey it.",
                  cause=Cause.block, observed=seen)
