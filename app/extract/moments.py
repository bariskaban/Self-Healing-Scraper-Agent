"""Dates and datetimes: strptime formats first, then ISO 8601, then month names through dateparser.

The order and the refusals are the point of this file (CONVENTIONS.md rules 3 and 4):

1. `spec.formats`, in order, as strptime formats: on the text as found, then with trailing words
   such as "Uhr" removed. A format with %z keeps the offset it reads. A format that does not read
   a day, a month and a year is not used (strptime would fill the missing part in with a 1), and
   a zone the format spells out as plain text ("...%SZ", "%H:%M UTC") is kept as the offset.
2. ISO 8601 (`2026-12-09`, `2026-12-09T10:00`, `2026-12-09T10:00:00+01:00`, `...Z`).
3. Only when the text has a day, a month written as a word and a four-digit year, in that order:
   our own reading (day, month word, year, time, offset), which is then confirmed by dateparser,
   restricted to absolute dates, day before month, day, month and year required. The text is
   refused when the two disagree, when it holds anything else with digits in it, when it names a
   zone we do not read, when it gives the time as a word ("midi", "noon"), or when the time
   follows a word that is not a lead-in of the month's language ("à", "um", "om", "at", "ore":
   the table `_LEAD_INS`), as in "dans 12 h", which is a duration. dateparser sees the
   text as written first. Only when it cannot read that at all does it see the same text with
   the parts we read spelled plainly ("1er" as "1", "16 h 30" as "16:30:00", "Maerz" as "März"),
   so it still refuses the words around the date that it does not know.

A purely numeric date with no format ("03/04/2026") is never read: which number is the day is a
guess. A wall-clock time is placed in the portal's zone with zoneinfo. On a switch day, a time
that does not exist (02:30 when clocks jump from 02:00 to 03:00) is refused, and a time that
exists twice (02:30 when clocks go back) is read as its first occurrence, the earlier instant
(summer time), so a deadline is never placed later than the portal could have meant.

An offset written in the text wins over the portal's zone. A zone name that belongs to the
portal's own zone but to the other half of the year ("MEZ" on a July date in Europe/Berlin) is
refused: the page is either loose with the name or means it, and that is a guess of one hour.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.extract.core import ParseContext

DATE_ONLY = "date_only"

# Words that may follow a time and say nothing more: "10:00 Uhr", "10 h", "10:00 uur", "godz.".
_TRAILING_WORDS = {"uhr", "h", "hrs", "hr", "uur", "u", "godz", "godz.", "ore", "heures", "horas", "hod", "hod."}
_TIME_DIRECTIVES = re.compile(r"%[HIMXcRT]")
_DIRECTIVE = re.compile(r"%(.)")
# A "Z" a format spells out after the time, as in "%Y-%m-%dT%H:%M:%SZ": the text is in UTC.
_LITERAL_Z = re.compile(r"(?<![A-Za-z])Z(?![A-Za-z0-9])")

_ISO = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d{1,6})?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?)?"  # an offset only after a time: fromisoformat reads "+01:00" as 01:00
)

# == Month names (DE, FR, ES, NL, PL, IT and EN), full and abbreviated ==

_MONTHS: dict[str, list[str]] = {
    "de": ["januar jänner jan", "februar feber feb", "märz maerz mär mrz", "april apr", "mai",
           "juni jun", "juli jul", "august aug", "september sep sept", "oktober okt", "november nov",
           "dezember dez"],
    "fr": ["janvier janv", "février fevrier févr fevr fév fev", "mars", "avril avr", "mai", "juin",
           "juillet juil juill", "août aout", "septembre sept", "octobre oct", "novembre nov",
           "décembre decembre déc dec"],
    "es": ["enero ene", "febrero feb", "marzo mar", "abril abr", "mayo may", "junio jun", "julio jul",
           "agosto ago", "septiembre setiembre sep sept", "octubre oct", "noviembre nov",
           "diciembre dic"],
    "nl": ["januari jan", "februari feb", "maart mrt", "april apr", "mei", "juni jun", "juli jul",
           "augustus aug", "september sep sept", "oktober okt", "november nov", "december dec"],
    "pl": ["styczeń stycznia sty", "luty lutego lut", "marzec marca mar", "kwiecień kwietnia kwi",
           "maj maja", "czerwiec czerwca cze", "lipiec lipca lip", "sierpień sierpnia sie",
           "wrzesień września wrz", "październik października paź", "listopad listopada lis",
           "grudzień grudnia gru"],
    "it": ["gennaio gen", "febbraio feb", "marzo mar", "aprile apr", "maggio mag", "giugno giu",
           "luglio lug", "agosto ago", "settembre set sett", "ottobre ott", "novembre nov",
           "dicembre dic"],
    "en": ["january jan", "february feb", "march mar", "april apr", "may", "june jun", "july jul",
           "august aug", "september sep sept", "october oct", "november nov", "december dec"],
}

# word -> {language: month number}
_MONTH_WORDS: dict[str, dict[str, int]] = {}
for _lang, _names in _MONTHS.items():
    for _number, _words in enumerate(_names, start=1):
        for _word in _words.split():
            _MONTH_WORDS.setdefault(_word, {})[_lang] = _number

# What may stand between the date and its time, by language: "12 décembre 2026 à 12 h",
# "9. Dezember 2026 um 10 Uhr", "9 dicembre 2026 alle ore 12:00". After any other word the number
# may be something else ("dans 12 h" is a duration, "après 12 h" is not a deadline at twelve).
_LEAD_INS: dict[str, tuple[str, ...]] = {
    "de": ("um",),
    "fr": ("à", "a"),
    "es": ("a las", "a la"),
    "nl": ("om",),
    "pl": ("o", "godz.", "godz", "o godz.", "o godz"),
    "it": ("ore", "alle", "alle ore"),
    "en": ("at",),
}
# A comma or a dash may come before the lead-in, or stand alone: "2026, 10 Uhr", "2026 - 12:00".
_LEAD_IN_MARKS = ",-–—"
# A word that belongs to the year and comes before all of that: "9 grudnia 2026 r. godz. 10:00".
_YEAR_WORDS: dict[str, tuple[str, ...]] = {"pl": ("roku", "r.", "r")}

_MONTH_ALT = "|".join(sorted(map(re.escape, _MONTH_WORDS), key=len, reverse=True))
# Day, month word, four-digit year: "9. Dezember 2026", "15 de diciembre de 2026", "12 déc. 2026".
# The first of the month may carry its ordinal mark: "1er décembre" (also what NFKC makes of a
# superscript "er"), "1° dicembre", "1º de enero" (which NFKC turns into "1o").
_WORD_DATE = re.compile(
    rf"(?<!\d)(?P<day>\d{{1,2}})(?P<ordinal>er|°|o)?\.?\s*(?:de\s+)?(?P<month>{_MONTH_ALT})(?!\w)\.?,?\s*"
    rf"(?:de\s+)?(?P<year>\d{{4}})(?!\d)",
    re.IGNORECASE,
)
_TWELVE_HOUR = re.compile(r"(?<!\w)[ap]\.?\s?m\.?(?!\w)", re.IGNORECASE)
_TIME = re.compile(r"(?<![\d:.])(\d{1,2})\s*(?::|h|\.)\s*(\d{2})(?:\s*:\s*(\d{2}))?(?![\d:])", re.IGNORECASE)
# A full hour with its unit and no minutes: "12 h", "12h", "12 heures", "10 Uhr", "10 uur".
_HOUR_ONLY = re.compile(r"(?<![\d:.])(\d{1,2})\s*(?:heures?|h|uhr|uur)(?!\w)", re.IGNORECASE)
# A clock unit with no number before it. Right after the year it means the "year" was a time
# ("9. Dezember 2030 Uhr" is half past eight in the evening, in a year the text does not give).
_CLOCK_UNIT = re.compile(r"\s*(?:uhr|uur|heures?|hrs?|h|ore|horas|godz)(?!\w)", re.IGNORECASE)
# A time of day written as a word. We read no time from it, and the end of the day would be wrong.
_CLOCK_WORDS = re.compile(
    r"(?<!\w)(?:midnight|noon|midday|minuit|midi|mitternacht|mittags?|middernacht|middag|medianoche|"
    r"mediod[ií]a|mezzanotte|mezzogiorno|północy?|południe|południa)(?!\w)",
    re.IGNORECASE,
)
# An offset written in the text: "UTC+02:00", "GMT+1", "(UTC)", "CET", "+01:00" after a space.
_NAMED_OFFSETS = {"UTC": 0, "GMT": 0, "WET": 0, "WEST": 60, "CET": 60, "MEZ": 60, "CEST": 120, "MESZ": 120,
                  "EET": 120, "EEST": 180}
# The German names of the zone names zoneinfo uses.
_ZONE_NAME_ALIASES = {"MEZ": "CET", "MESZ": "CEST"}
_OFFSET = re.compile(
    r"\(?\s*(?<![A-Za-z])(?:"
    r"(?P<base>UTC|GMT)(?:\s*(?P<sign>[+\-−])\s*(?P<h>\d{1,2})(?::?(?P<m>\d{2}))?)?"
    r"|(?P<name>CEST|CET|MESZ|MEZ|EEST|EET|WEST|WET)"
    r"|(?<=\s)(?P<sign2>[+\-])(?P<h2>\d{2}):?(?P<m2>\d{2})"
    r")(?![\w])\s*\)?"
)


class Moment:
    """What the text says: a date, and a time when it has one, and an offset when it carries one.

    `name` is the zone name the offset was written as ("CET", "MEZ", "UTC"), when it was a name.
    """

    __slots__ = ("day", "wall", "offset", "name")

    def __init__(self, day: date, wall: time | None, offset: timezone | None, name: str | None = None) -> None:
        self.day, self.wall, self.offset, self.name = day, wall, offset, name


def read_date(text: str, formats: list[str], context: ParseContext) -> tuple[date | None, str | None]:
    """A calendar date as written (an offset or time in the text is ignored)."""
    moment, problem = _read(text, formats, context)
    if moment is None:
        return None, problem
    return moment.day, None


def read_datetime(text: str, formats: list[str], context: ParseContext
                  ) -> tuple[datetime | None, str | None, str | None]:
    """An aware datetime, its problem when None, and a note ("date_only")."""
    moment, problem = _read(text, formats, context)
    if moment is None:
        return None, problem, None
    note = None
    wall = moment.wall
    if wall is None:
        if context.settings.date_only_deadline == "null":
            return None, "date without time", None
        if moment.offset is not None:
            return None, "offset without time", None
        wall, note = time(23, 59, 59), DATE_ONLY
    naive = datetime.combine(moment.day, wall)
    if moment.offset is not None:
        if moment.name and context.zone is not None and not _name_fits(moment.name, naive, context.zone):
            return None, "zone name does not match the date in the portal's zone", None
        return naive.replace(tzinfo=moment.offset), None, note
    if context.zone is None:
        return None, "no time zone", None
    aware, problem = place_in_zone(naive, context.zone)
    return aware, problem, (note if aware is not None else None)


def place_in_zone(naive: datetime, zone: ZoneInfo) -> tuple[datetime | None, str | None]:
    """The wall-clock time in the zone; None for a time the switch day skips; the first of two."""
    first = naive.replace(tzinfo=zone, fold=0)
    back = first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
    if back != naive:
        return None, "time does not exist in the zone"
    return first, None


def _name_fits(name: str, naive: datetime, zone: ZoneInfo) -> bool:
    """False when the name is one of the portal zone's own two names, but not the one in force then.

    A name of another zone ("UTC" on a Berlin portal, "CET" on a Lisbon one) fits: the page's
    offset stands. In the hour that exists twice, either of the zone's names fits.
    """
    name = _ZONE_NAME_ALIASES.get(name, name)
    own = {datetime(naive.year, month, 1, 12, tzinfo=zone).tzname() for month in (1, 7)}
    if name not in own:
        return True
    return name in {naive.replace(tzinfo=zone, fold=fold).tzname() for fold in (0, 1)}


# == Reading ==

def _read(text: str, formats: list[str], context: ParseContext) -> tuple[Moment | None, str | None]:
    settings = context.settings
    moment = _by_formats(text, formats) or _by_iso(text)
    if moment is None and _WORD_DATE.search(text):
        moment, problem = _by_words(text, context)
        if moment is None:
            return None, problem
    if moment is None:
        return None, "not a date in a known format"
    if not settings.min_year <= moment.day.year <= settings.max_year:
        return None, "year out of range"
    return moment, None


def _strip_trailing(text: str) -> str:
    words = text.split(" ")
    while len(words) > 1 and words[-1].casefold() in _TRAILING_WORDS:
        words.pop()
    return " ".join(words)


def _by_formats(text: str, formats: list[str]) -> Moment | None:
    candidates = [text]
    stripped = _strip_trailing(text)
    if stripped != text:
        candidates.append(stripped)
    for fmt in formats:
        if "%Z" in fmt:  # strptime reads a zone name but drops it: the wall clock would be misplaced
            continue
        if not _reads_a_whole_date(fmt):
            continue
        usable, literal_offset, name = _literal_offset(fmt)
        if not usable:
            continue
        for candidate in candidates:
            try:
                parsed = datetime.strptime(candidate, fmt)
            except (ValueError, TypeError):
                continue
            wall = parsed.time() if _TIME_DIRECTIVES.search(fmt) else None
            if "%z" in fmt:
                return Moment(parsed.date(), wall, parsed.tzinfo)  # type: ignore[arg-type]
            return Moment(parsed.date(), wall, literal_offset, name)
    return None


def _reads_a_whole_date(fmt: str) -> bool:
    """Whether a strptime format reads a day, a month and a year: strptime fills a missing one in."""
    seen = set(_DIRECTIVE.findall(fmt.replace("%%", "")))
    if seen & {"c", "x"}:
        return True
    return bool(seen & {"Y", "y"}) and ("j" in seen or ("d" in seen and bool(seen & {"m", "b", "B"})))


def _literal_offset(fmt: str) -> tuple[bool, timezone | None, str | None]:
    """The zone a format spells out as plain text: (usable, offset, zone name).

    "%Y-%m-%dT%H:%M:%SZ" and "%d.%m.%Y %H:%M UTC" match a text in UTC, and strptime says nothing
    about it. With %z the offset comes from the text itself. Two zones, or one we cannot read,
    make the format unusable.
    """
    if "%z" in fmt:
        return True, None, None
    literal = _DIRECTIVE.sub(" ", fmt.replace("%%", ""))
    found = list(_OFFSET.finditer(literal))
    zulu = len(_LITERAL_Z.findall(literal))
    if not found and not zulu:
        return True, None, None
    if len(found) + zulu > 1:
        return False, None, None
    if zulu:
        return True, timezone.utc, "UTC"
    offset = _offset_of(found[0])
    return offset is not None, offset, _name_of(found[0])


def _by_iso(text: str) -> Moment | None:
    if not _ISO.fullmatch(text):
        return None
    try:
        if len(text) == 10:
            return Moment(date.fromisoformat(text), None, None)
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return Moment(parsed.date(), parsed.time(), parsed.tzinfo)  # type: ignore[arg-type]


def _by_words(text: str, context: ParseContext) -> tuple[Moment | None, str | None]:
    """A date with its month as a word. Our own reading, confirmed by dateparser."""
    matches = list(_WORD_DATE.finditer(text))
    if len(matches) != 1:
        return None, "more than one date"
    match = matches[0]
    if re.search(r"\d", text[:match.start()]):
        return None, "unexpected numbers around the date"
    day, word, year = int(match.group("day")), match.group("month").casefold(), int(match.group("year"))
    if match.group("ordinal") and day != 1:
        return None, "day unclear"
    month, languages = _month_of(word, context.language)
    if month is None:
        return None, "month name unclear"
    try:
        own_day = date(year, month, day)
    except ValueError:
        return None, "not a real date"

    rest = text[match.end():]
    if _TWELVE_HOUR.search(rest):
        return None, "12-hour clock"
    if _CLOCK_WORDS.search(rest):
        return None, "time written as a word"
    offset: timezone | None = None
    name: str | None = None
    offsets = list(_OFFSET.finditer(rest))
    if len(offsets) > 1:
        return None, "more than one offset"
    if offsets:
        # A bare "-12:00" after a time may be the end of a range ("10:00 -12:00"), not an offset.
        if offsets[0].group("sign2") == "-":
            return None, "offset unclear"
        offset, name = _offset_of(offsets[0]), _name_of(offsets[0])
        if offset is None:
            return None, "offset unclear"
        rest = rest[:offsets[0].start()] + " " + rest[offsets[0].end():]
    # The second reader sees everything but the offset we read.
    plain = text[:match.end()] + rest
    times = list(_TIME.finditer(rest)) or list(_HOUR_ONLY.finditer(rest))
    if len(times) > 1:
        return None, "more than one time"
    wall: time | None = None
    spelled = rest
    if times:
        t = times[0]
        if not _is_lead_in(rest[:t.start()], languages):
            return None, "time after a word that is not a lead-in"
        try:
            wall = time(int(t.group(1)), *(int(part or 0) for part in t.groups()[1:]))
        except ValueError:
            return None, "not a real time"
        spelled = f"{rest[:t.start()]} {wall.isoformat()} {rest[t.end():]}"
        rest = rest[:t.start()] + rest[t.end():]
    elif _CLOCK_UNIT.match(rest):
        return None, "time unclear"
    if re.search(r"\d", rest):
        return None, "unexpected numbers around the date"

    seen = _dateparser(plain, languages)
    if seen is None:
        # The same text with what we read spelled plainly; every other word is still in it.
        canonical = _MONTHS[languages[0]][month - 1].split()[0]
        seen = _dateparser(f"{text[:match.start()]}{day} {canonical} {year}{spelled}", languages)
    if seen is None:
        return None, "date not confirmed"
    if seen.tzinfo is not None:  # "EST", "MSK", "Z": a zone the second reader saw and we do not read
        return None, "zone name not read"
    if seen.date() != own_day:
        return None, "date readings disagree"
    if (seen.hour, seen.minute, seen.second) != ((wall.hour, wall.minute, wall.second) if wall else (0, 0, 0)):
        return None, "time readings disagree"
    return Moment(own_day, wall, offset, name), None


def _is_lead_in(between: str, languages: list[str]) -> bool:
    """Whether the text between the date and the time is nothing, a comma or dash, or a lead-in.

    The lead-ins are those of the languages the month word belongs to, the portal's first.
    """
    words = between.casefold().strip()
    for language in languages:
        for year_word in _YEAR_WORDS.get(language, ()):
            if words == year_word or words.startswith((year_word + " ", year_word + ",")):
                words = words[len(year_word):]
                break
    words = words.strip().lstrip(_LEAD_IN_MARKS).strip()
    return not words or any(words in _LEAD_INS.get(language, ()) for language in languages)


def _month_of(word: str, language: str | None) -> tuple[int | None, list[str]]:
    """The month a word names, and the languages to give dateparser. None when languages disagree."""
    readings = _MONTH_WORDS.get(word.rstrip(".")) or {}
    language = (language or "").lower()[:2] or None
    if language in readings:
        return readings[language], [language] + [lang for lang in readings if lang != language]
    months = set(readings.values())
    if len(months) != 1:
        return None, []
    return months.pop(), sorted(readings)


def _name_of(m: re.Match[str]) -> str | None:
    """The zone name an offset was written as; None for a number ("UTC+2", "+01:00")."""
    if m.group("name"):
        return m.group("name")
    return m.group("base") if m.group("base") and not m.group("sign") else None


def _offset_of(m: re.Match[str]) -> timezone | None:
    if m.group("name"):
        return timezone(timedelta(minutes=_NAMED_OFFSETS[m.group("name")]))
    if m.group("base"):
        if not m.group("sign"):
            return timezone.utc
        sign, hours, minutes = m.group("sign"), int(m.group("h")), int(m.group("m") or 0)
    else:
        sign, hours, minutes = m.group("sign2"), int(m.group("h2")), int(m.group("m2"))
    if hours > 14 or minutes >= 60:
        return None
    total = timedelta(hours=hours, minutes=minutes)
    return timezone(-total if sign in "-−" else total)


_SETTINGS = {
    "DATE_ORDER": "DMY",
    "STRICT_PARSING": True,
    "REQUIRE_PARTS": ["day", "month", "year"],
    "PARSERS": ["absolute-time"],
}
# RETURN_AS_TIMEZONE_AWARE is left at its default on purpose: the answer then carries a zone
# exactly when dateparser saw one in the text, which is how a zone name we do not read is caught.


def _dateparser(text: str, languages: list[str]) -> datetime | None:
    import dateparser  # slow to import and to warm up: only loaded when a month name is seen

    try:
        result = dateparser.parse(text, languages=languages, settings=_SETTINGS)
    except Exception:  # an unknown language or an internal error: not a reading
        return None
    return result if isinstance(result, datetime) else None
