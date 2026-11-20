"""The types every normaliser shares, and `clean`."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from app.extract.settings import ExtractSettings

# Characters NFKC keeps that are invisible on the page: zero-width space and joiners, word
# joiner, byte order mark, soft hyphen. They would break grounding and comparisons.
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))


def clean(text: str | None) -> str:
    """Unicode NFKC, non-breaking and other spaces to plain spaces, whitespace collapsed, stripped."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).translate(_INVISIBLE)
    return " ".join(text.split())


@dataclass(frozen=True)
class ParseContext:
    """What a value's meaning depends on beyond its own text."""

    zone: ZoneInfo | None          # the portal's time zone (Portal.timezone)
    page_url: str | None           # the address of the page the text came from
    language: str | None           # two letters: the language of the portal's labels
    settings: ExtractSettings = field(default_factory=ExtractSettings)


@dataclass(frozen=True)
class Parsed:
    """One normalised value. `value` is None whenever the text cannot be read with certainty."""

    value: object | None
    raw: str                       # the text as found, cleaned
    problem: str | None            # why value is None, when raw is not empty
    note: str | None = None        # e.g. "date_only": the deadline had no time and became end of day
