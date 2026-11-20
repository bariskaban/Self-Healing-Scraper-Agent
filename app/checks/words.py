"""Plain words for messages and reasons: times, spans, counts and field names.

Clock times are printed in UTC and labelled "UTC", as `app/scheduler.py` prints them:
an operator who watches portals in several countries needs one clock.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# How an operator would name each field of a tender record.
FIELD_WORDS = {
    "tender_id": "id",
    "url": "address",
    "title": "title",
    "buyer_name": "buyer name",
    "publication_date": "publication date",
    "submission_deadline": "deadline",
    "reference_number": "reference number",
    "description": "description",
}


def field_word(field: str) -> str:
    """The plain name of a record field."""
    return FIELD_WORDS.get(field, field.replace("_", " "))


def require_aware(at: datetime, what: str) -> datetime:
    """Refuse a time without an offset (conventions, rule 4)."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError(f"{what} must carry an offset")
    return at


def clock(at: datetime, now: datetime) -> str:
    """'14:02 UTC', or '19 Nov 14:02 UTC' when it falls on another day than `now`."""
    at, now = at.astimezone(timezone.utc), now.astimezone(timezone.utc)
    day = "" if at.date() == now.date() else f"{at.day} {_MONTHS[at.month - 1]} "
    return f"{day}{at:%H:%M} UTC"


def count(n: int, one: str, many: str | None = None) -> str:
    """'1 tender', '23 tenders', '1,000 tenders'."""
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def span(length: timedelta) -> str:
    """'45 minutes', '3 hours', '2 days'."""
    minutes = max(0, round(length.total_seconds() / 60))
    if minutes < 120:
        return count(minutes, "minute")
    hours = round(minutes / 60)
    if hours < 48:
        return count(hours, "hour")
    return count(round(hours / 24), "day")


def share(part: float) -> str:
    """'87%' for 0.87."""
    return f"{round(part * 100)}%"
