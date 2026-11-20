"""The normalisers: each value type, six languages, summer and winter time, and null over guess.

No network, no files, no model: `parse` is a pure function.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.extract import ExtractSettings, Parsed, ParseContext, clean, parse
from app.extract.words import ISO_ALPHA2
from app.recipe.schema import Pair, ValueSpec, ValueType as T

BERLIN = ZoneInfo("Europe/Berlin")
PAGE = "https://vergabe.example.de/ausschreibungen/liste?seite=2"


def spec(type_: T, formats: list[str] | None = None, words: dict[str, str] | None = None,
         pattern: str | None = None) -> ValueSpec:
    return ValueSpec(type=type_, formats=formats or [],
                     words=[Pair(name=k, value=v) for k, v in (words or {}).items()], pattern=pattern)


def ctx(zone: ZoneInfo | None = BERLIN, language: str | None = "de", page_url: str | None = PAGE,
        **settings: object) -> ParseContext:
    return ParseContext(zone=zone, page_url=page_url, language=language, settings=ExtractSettings(**settings))


def offset(dt: datetime) -> timedelta:
    assert dt.tzinfo is not None
    return dt.utcoffset()  # type: ignore[return-value]


H1, H2 = timedelta(hours=1), timedelta(hours=2)


# == clean ==

def test_clean_collapses_whitespace_and_normalises():
    assert clean("  09.12.2026  10:00\n\tUhr ") == "09.12.2026 10:00 Uhr"
    assert clean("Straßen­bau​") == "Straßenbau"
    assert clean("１２") == "12"  # full-width digits, NFKC
    assert clean(None) == "" and clean("   ") == ""


@pytest.mark.parametrize("raw", [None, "", "   ", " \n"])
@pytest.mark.parametrize("type_", list(T))
def test_empty_text_is_nothing_without_a_problem(raw, type_):
    assert parse(spec(type_), raw, ctx()) == Parsed(value=None, raw="", problem=None)


# == text and id ==

def test_text_is_cleaned():
    p = parse(spec(T.text), "  Straßenbauarbeiten\n  B 96  ", ctx())
    assert p.value == "Straßenbauarbeiten B 96" and p.raw == "Straßenbauarbeiten B 96" and p.problem is None


def test_text_pattern_group_whole_match_and_no_match():
    assert parse(spec(T.text, pattern=r"Vergabenr\.:\s*(\S+)"), "Vergabenr.: VG-2026/117 (EU)", ctx()).value == "VG-2026/117"
    assert parse(spec(T.text, pattern=r"VG-\d{4}/\d+"), "Vergabenr.: VG-2026/117 (EU)", ctx()).value == "VG-2026/117"
    p = parse(spec(T.text, pattern=r"Vergabenr\.:\s*(\S+)"), "Aktenzeichen 117", ctx())
    assert p.value is None and p.problem == "pattern did not match" and p.raw == "Aktenzeichen 117"


def test_bad_pattern_is_none_not_an_error():
    p = parse(spec(T.text, pattern=r"(unclosed"), "abc", ctx())
    assert p.value is None and p.problem


def test_pattern_sees_only_the_start_of_a_very_long_text():
    # Python's re has no timeout: the text a recipe's pattern runs over is cut at a setting.
    long = "x" * 30 + " Vergabenr.: VG-2026/117"
    s = spec(T.text, pattern=r"Vergabenr\.:\s*(\S+)")
    assert parse(s, long, ctx()).value == "VG-2026/117"
    p = parse(s, long, ctx(pattern_text_limit=40))
    assert p.value is None and p.problem == "pattern did not match" and p.raw == long
    assert parse(spec(T.text, pattern=r"x+"), long, ctx(pattern_text_limit=5)).value == "xxxxx"
    assert parse(spec(T.text), long, ctx(pattern_text_limit=5)).value == long  # no pattern, no cut
    assert ExtractSettings().pattern_text_limit == 20_000
    assert ExtractSettings.from_env({"EXTRACT_PATTERN_TEXT_LIMIT": "500"}).pattern_text_limit == 500
    with pytest.raises(ValueError):
        ExtractSettings(pattern_text_limit=0)


def test_id_is_text():
    assert parse(spec(T.id), " 2026/S 231-701234 ", ctx()).value == "2026/S 231-701234"


# == url ==

@pytest.mark.parametrize("raw, expected", [
    ("/ausschreibungen/4711", "https://vergabe.example.de/ausschreibungen/4711"),
    ("detail?id=4711", "https://vergabe.example.de/ausschreibungen/detail?id=4711"),
    ("../dokumente/LV Los 1.pdf", "https://vergabe.example.de/dokumente/LV%20Los%201.pdf"),
    ("//files.example.de/a.zip", "https://files.example.de/a.zip"),
    ("https://other.example.org/x?y=1", "https://other.example.org/x?y=1"),
    ("HTTP://Other.example.org/x", "HTTP://Other.example.org/x"),
])
def test_links_are_made_absolute(raw, expected):
    assert parse(spec(T.url), raw, ctx()).value == expected


@pytest.mark.parametrize("raw", ["javascript:void(0)", "JavaScript:openDoc(4711)", "mailto:vergabe@example.de",
                                 "#", "#top", "tel:+4930123", "ftp://example.de/a.pdf"])
def test_non_links_are_none(raw):
    p = parse(spec(T.url), raw, ctx())
    assert p.value is None and p.problem and p.raw


def test_relative_link_without_page_is_none():
    p = parse(spec(T.url), "/a/b", ctx(page_url=None))
    assert p.value is None and p.problem
    assert parse(spec(T.url), "https://x.example/a", ctx(page_url=None)).value == "https://x.example/a"


# == datetime: formats, six languages, zones ==

DE_FORMATS = ["%d.%m.%Y %H:%M", "%d.%m.%Y"]


def test_german_deadline_with_uhr_in_winter():
    p = parse(spec(T.datetime, DE_FORMATS), "09.12.2026 10:00 Uhr", ctx())
    assert p.value == datetime(2026, 12, 9, 10, 0, tzinfo=BERLIN)
    assert offset(p.value) == H1 and p.value.isoformat() == "2026-12-09T10:00:00+01:00"
    assert p.raw == "09.12.2026 10:00 Uhr" and p.problem is None and p.note is None


def test_summer_time_after_the_switch():
    p = parse(spec(T.datetime, DE_FORMATS), "30.03.2027 10:00", ctx())
    assert p.value.isoformat() == "2027-03-30T10:00:00+02:00"
    # the day before the switch (28 March 2027) is still winter time
    assert offset(parse(spec(T.datetime, DE_FORMATS), "27.03.2027 10:00", ctx()).value) == H1


def test_time_skipped_by_the_spring_switch_is_none():
    p = parse(spec(T.datetime, DE_FORMATS), "28.03.2027 02:30", ctx())
    assert p.value is None and p.problem == "time does not exist in the zone"


def test_time_repeated_by_the_autumn_switch_is_the_first_one():
    p = parse(spec(T.datetime, DE_FORMATS), "31.10.2027 02:30", ctx())
    assert p.value.isoformat() == "2027-10-31T02:30:00+02:00"


@pytest.mark.parametrize("raw, language, zone, expected", [
    ("12 décembre 2026 à 12h00", "fr", "Europe/Paris", "2026-12-12T12:00:00+01:00"),
    ("15 de diciembre de 2026 14:00", "es", "Europe/Madrid", "2026-12-15T14:00:00+01:00"),
    ("9 december 2026 10:00 uur", "nl", "Europe/Amsterdam", "2026-12-09T10:00:00+01:00"),
    ("9 grudnia 2026 r. godz. 10:00", "pl", "Europe/Warsaw", "2026-12-09T10:00:00+01:00"),
    ("9 dicembre 2026 ore 12:00", "it", "Europe/Rome", "2026-12-09T12:00:00+01:00"),
    ("9. Dezember 2026, 10:00 Uhr", "de", "Europe/Berlin", "2026-12-09T10:00:00+01:00"),
    ("Mittwoch, 9. Dezember 2026 10.00 Uhr", "de", "Europe/Berlin", "2026-12-09T10:00:00+01:00"),
    ("30 maart 2027 10:00", "nl", "Europe/Amsterdam", "2027-03-30T10:00:00+02:00"),
    ("12 déc. 2026 12h00", "fr", "Europe/Paris", "2026-12-12T12:00:00+01:00"),
])
def test_month_names_in_six_languages(raw, language, zone, expected):
    p = parse(spec(T.datetime), raw, ctx(zone=ZoneInfo(zone), language=language))
    assert p.value is not None, p.problem
    assert p.value.isoformat() == expected and p.note is None


def test_month_name_without_context_language_is_still_read_when_unambiguous():
    p = parse(spec(T.datetime), "9 grudnia 2026 r. godz. 10:00", ctx(zone=ZoneInfo("Europe/Warsaw"), language=None))
    assert p.value.isoformat() == "2026-12-09T10:00:00+01:00"


def test_iso_with_its_own_offset_is_kept():
    p = parse(spec(T.datetime), "2026-12-09T10:00:00+01:00", ctx(zone=ZoneInfo("Europe/Lisbon")))
    assert p.value.isoformat() == "2026-12-09T10:00:00+01:00"
    z = parse(spec(T.datetime), "2026-12-09T09:00:00Z", ctx())
    assert offset(z.value) == timedelta(0) and z.value == datetime(2026, 12, 9, 10, tzinfo=BERLIN)


def test_iso_without_offset_is_placed_in_the_zone():
    assert parse(spec(T.datetime), "2027-03-30T10:00", ctx()).value.isoformat() == "2027-03-30T10:00:00+02:00"


def test_iso_used_when_no_format_matches():
    p = parse(spec(T.datetime, ["%d.%m.%Y %H:%M"]), "2026-12-09T10:00:00", ctx())
    assert p.value.isoformat() == "2026-12-09T10:00:00+01:00"


def test_ted_style_offset_with_a_matching_format():
    p = parse(spec(T.datetime, ["%d/%m/%Y %H:%M:%S (UTC%z)"]), "05/05/2026 13:00:00 (UTC+02:00)", ctx(zone=None))
    assert p.value.isoformat() == "2026-05-05T13:00:00+02:00"


def test_offset_written_after_a_month_name_is_kept():
    p = parse(spec(T.datetime), "9 December 2026 10:00 (UTC)", ctx(language="en"))
    assert p.value.isoformat() == "2026-12-09T10:00:00+00:00"
    p = parse(spec(T.datetime), "9. Dezember 2026 10:00 MEZ", ctx(zone=None))
    assert p.value.isoformat() == "2026-12-09T10:00:00+01:00"


def test_no_zone_and_no_offset_is_none():
    p = parse(spec(T.datetime, DE_FORMATS), "09.12.2026 10:00", ctx(zone=None))
    assert p.value is None and p.problem == "no time zone"


def test_date_only_deadline_end_of_day():
    p = parse(spec(T.datetime, DE_FORMATS), "09.12.2026", ctx())
    assert p.value.isoformat() == "2026-12-09T23:59:59+01:00" and p.note == "date_only"
    p = parse(spec(T.datetime), "2027-06-30", ctx())
    assert p.value.isoformat() == "2027-06-30T23:59:59+02:00" and p.note == "date_only"
    p = parse(spec(T.datetime), "15 de diciembre de 2026", ctx(zone=ZoneInfo("Europe/Madrid"), language="es"))
    assert p.value.isoformat() == "2026-12-15T23:59:59+01:00" and p.note == "date_only"


def test_date_only_deadline_null_setting():
    p = parse(spec(T.datetime, DE_FORMATS), "09.12.2026", ctx(date_only_deadline="null"))
    assert p.value is None and p.problem == "date without time"


def test_date_only_without_zone_is_none():
    assert parse(spec(T.datetime, DE_FORMATS), "09.12.2026", ctx(zone=None)).value is None


@pytest.mark.parametrize("raw", ["03/04/2026", "03/04/2026 10:00", "03.04.2026", "4/3/26", "12-11-2026"])
def test_numeric_date_without_format_is_refused(raw):
    for type_ in (T.date, T.datetime):
        p = parse(spec(type_), raw, ctx())
        assert p.value is None and p.problem and p.raw == raw


def test_year_out_of_range_is_refused():
    assert parse(spec(T.datetime, ["%d.%m.%Y %H:%M"]), "09.12.26 10:00", ctx()).value is None
    assert parse(spec(T.date, ["%d.%m.%Y"]), "09.12.1926", ctx()).problem == "year out of range"
    assert parse(spec(T.date), "2206-12-09", ctx()).problem == "year out of range"
    assert parse(spec(T.date), "2206-12-09", ctx(max_year=2300)).value == date(2206, 12, 9)


@pytest.mark.parametrize("raw", [
    "Dezember 2026",                         # no day
    "9. Dezember",                           # no year
    "31. Februar 2026 10:00",                # not a real date
    "9. Dezember 2026 25:00",                # not a real time
    "9. Dezember 2026 10:00 bis 12:00",      # two times
    "9. Dezember 2026 oder 10. Dezember 2026",  # two dates
    "Frist: 3 Tage nach dem 9. Dezember 2026",  # other numbers
    "morgen 10:00",                          # relative
    "in 2 Wochen",
    "Siehe Vergabeunterlagen",
    "9 Dezember 2026 10:00 GMT+25",          # impossible offset
    "9 December 2026 2:00 PM",               # 12-hour clock: dateparser alone read it as 02:00 once
    "9 December 2026 2:00PM",
    "December 9, 2026 10:00",                # month before day
    "12 décembre 2026 sous 12 h",            # a word around the date that nobody knows
    "2 er décembre 2026",                    # not an ordinal
    "2er décembre 2026",                     # only the first of the month is written "1er"
    "9. Dezember 2030 Uhr",                  # the "year" is a time: 20:30, in no year
    "9. Dezember 2026 10:00 -12:00",         # a range, not an offset twelve hours west
    "9. Dezember 2026 10:00 -12:00 Uhr",
    "9 December 2026 10:00 EST",             # a zone name we do not read
    "9 December 2026 10:00 MSK",
    "9 December 2026 10:00 Z",
    "9 December 2026 10:00 cet",
    "9 décembre 2026 est 12:00",
    "12 décembre 2026 à midi",               # the time as a word: not the end of the day
    "9 December 2026 noon",
    "9 December 2026 midnight",
    "9. Dezember 2026 mittags",
    "2026-12-09+01:00",                      # an offset without a time
    "2026-12-09Z",
])
def test_unreadable_dates_never_become_values(raw):
    for type_ in (T.date, T.datetime):
        p = parse(spec(type_, DE_FORMATS), raw, ctx())
        assert p.value is None and p.problem, (raw, type_, p)


# == datetime: French ordinals and hours ==

PARIS = ZoneInfo("Europe/Paris")


@pytest.mark.parametrize("raw, expected, note", [
    ("1er décembre 2026", "2026-12-01T23:59:59+01:00", "date_only"),
    ("1ER DÉCEMBRE 2026", "2026-12-01T23:59:59+01:00", "date_only"),
    ("1ᵉʳ décembre 2026", "2026-12-01T23:59:59+01:00", "date_only"),   # modifier letters: NFKC makes "1er"
    ("1ᴱᴿ décembre 2026", "2026-12-01T23:59:59+01:00", "date_only"),   # and "1ER"
    ("lundi 1er juin 2026", "2026-06-01T23:59:59+02:00", "date_only"),
    ("Le 1er décembre 2026 à 12h00", "2026-12-01T12:00:00+01:00", None),
    ("1er décembre 2026 à 16 h 30", "2026-12-01T16:30:00+01:00", None),
    ("mardi 1er décembre 2026 à 16 h 30", "2026-12-01T16:30:00+01:00", None),
    # The weekday is not checked against the date: 1 December 2026 is a Tuesday.
    ("lundi 1er décembre 2026 à 16 h 30", "2026-12-01T16:30:00+01:00", None),
    ("LUNDI 1ER DÉCEMBRE 2026 À 16 H 30", "2026-12-01T16:30:00+01:00", None),
    ("12 décembre 2026 à 12 h 00", "2026-12-12T12:00:00+01:00", None),
    ("12 décembre 2026 12 h 00", "2026-12-12T12:00:00+01:00", None),
    ("12 décembre 2026 à 12 h", "2026-12-12T12:00:00+01:00", None),
    ("12 décembre 2026 à 12h", "2026-12-12T12:00:00+01:00", None),
    ("12 décembre 2026 12 h", "2026-12-12T12:00:00+01:00", None),
    ("12 DÉCEMBRE 2026 À 12 H", "2026-12-12T12:00:00+01:00", None),
    ("12 décembre 2026 à 12 heures", "2026-12-12T12:00:00+01:00", None),
    ("12 décembre 2026 à 12h00", "2026-12-12T12:00:00+01:00", None),
    ("12 fév. 2027 à 9 h 05", "2027-02-12T09:05:00+01:00", None),
    ("30 juin 2027 à 12 h 00", "2027-06-30T12:00:00+02:00", None),
])
def test_french_first_of_month_and_hours(raw, expected, note):
    p = parse(spec(T.datetime), raw, ctx(zone=PARIS, language="fr"))
    assert p.value is not None, p.problem
    assert p.value.isoformat() == expected and p.note == note
    assert parse(spec(T.date), raw, ctx(zone=PARIS, language="fr")).value == p.value.date()


@pytest.mark.parametrize("raw, language, zone, expected", [
    ("1° dicembre 2026 ore 12:00", "it", "Europe/Rome", "2026-12-01T12:00:00+01:00"),
    ("1º de enero de 2027 14:00", "es", "Europe/Madrid", "2027-01-01T14:00:00+01:00"),
    ("9. Dezember 2026, 10 Uhr", "de", "Europe/Berlin", "2026-12-09T10:00:00+01:00"),
    ("9 december 2026 om 10 uur", "nl", "Europe/Amsterdam", "2026-12-09T10:00:00+01:00"),
    ("9. Maerz 2027 10:00", "de", "Europe/Berlin", "2027-03-09T10:00:00+01:00"),
    ("9 sett. 2026 10:00", "it", "Europe/Rome", "2026-09-09T10:00:00+02:00"),
    ("9 de sept. de 2026 10:00", "es", "Europe/Madrid", "2026-09-09T10:00:00+02:00"),
    ("9 mrt 2027 10:00", "nl", "Europe/Amsterdam", "2027-03-09T10:00:00+01:00"),
])
def test_ordinals_full_hours_and_spellings_in_other_languages(raw, language, zone, expected):
    p = parse(spec(T.datetime), raw, ctx(zone=ZoneInfo(zone), language=language))
    assert p.value is not None, p.problem
    assert p.value.isoformat() == expected


# == datetime: what stands between the date and its time ==

@pytest.mark.parametrize("raw, language", [
    # An hour with no minutes after a word that is not a lead-in: a duration, or not the deadline.
    ("12 décembre 2026 dans 12 h", "fr"),
    ("12 décembre 2026 dans 12 heures", "fr"),
    ("12 décembre 2026 en 12 h", "fr"),
    ("12 décembre 2026 + 12 h", "fr"),
    ("12 décembre 2026 +12h", "fr"),
    ("12 décembre 2026 après 12 h", "fr"),
    ("12 décembre 2026 environ 12 h", "fr"),
    ("12 décembre 2026 et 12 h", "fr"),
    ("12 décembre 2026 le 12 h", "fr"),
    ("12 décembre 2026 (12 h)", "fr"),
    ("9. Dezember 2026 in 10 Uhr", "de"),
    ("9 december 2026 in 10 uur", "nl"),
    ("9 December 2026 in 10 h", "en"),
    # The same with minutes.
    ("12 décembre 2026 dans 12 h 00", "fr"),
    ("12 décembre 2026 dans 12 h 30", "fr"),
    ("12 décembre 2026 dans 12:00", "fr"),
    ("12 décembre 2026 après 12:00", "fr"),
    ("9. Dezember 2026 in 10:00", "de"),
    ("9. Dezember 2026 und 10.00 Uhr", "de"),
    ("9 December 2026 in 10:00", "en"),
    ("9 December 2026 after 10:00", "en"),
    ("9 dicembre 2026 circa 10:00", "it"),
    ("9 de diciembre de 2026 en 10:00", "es"),
    ("9 grudnia 2026 za 10:00", "pl"),
    # A lead-in of a language the month word does not belong to.
    ("12 March 2027 um 10:00", "en"),
])
def test_time_after_a_word_that_is_not_a_lead_in_is_refused(raw, language):
    for type_ in (T.datetime, T.date):
        p = parse(spec(type_), raw, ctx(language=language))
        assert p.value is None and p.problem == "time after a word that is not a lead-in", (raw, type_, p)


@pytest.mark.parametrize("raw, language, zone, expected", [
    ("12 décembre 2026 12 h", "fr", "Europe/Paris", "2026-12-12T12:00:00+01:00"),
    ("12 décembre 2026 à 12 h", "fr", "Europe/Paris", "2026-12-12T12:00:00+01:00"),
    ("12 décembre 2026 a 12h", "fr", "Europe/Paris", "2026-12-12T12:00:00+01:00"),
    ("12 DÉCEMBRE 2026 À 12 HEURES", "fr", "Europe/Paris", "2026-12-12T12:00:00+01:00"),
    ("12 décembre 2026, 12 h", "fr", "Europe/Paris", "2026-12-12T12:00:00+01:00"),
    ("12 décembre 2026 - 12 h", "fr", "Europe/Paris", "2026-12-12T12:00:00+01:00"),
    ("12 décembre 2026 – 12 h 00", "fr", "Europe/Paris", "2026-12-12T12:00:00+01:00"),
    ("12 décembre 2026, à 12 h 00", "fr", "Europe/Paris", "2026-12-12T12:00:00+01:00"),
    ("12 décembre 2026 - à 12:00", "fr", "Europe/Paris", "2026-12-12T12:00:00+01:00"),
    ("9. Dezember 2026 10 Uhr", "de", "Europe/Berlin", "2026-12-09T10:00:00+01:00"),
    ("9. Dezember 2026 um 10 Uhr", "de", "Europe/Berlin", "2026-12-09T10:00:00+01:00"),
    ("9. Dezember 2026, um 10 Uhr", "de", "Europe/Berlin", "2026-12-09T10:00:00+01:00"),
    ("9. Dezember 2026 um 10.00 Uhr", "de", "Europe/Berlin", "2026-12-09T10:00:00+01:00"),
    ("9. Dezember 2026 um 10:00 Uhr MEZ", "de", "Europe/Berlin", "2026-12-09T10:00:00+01:00"),
    ("9 december 2026 10 uur", "nl", "Europe/Amsterdam", "2026-12-09T10:00:00+01:00"),
    ("9 december 2026, om 10 uur", "nl", "Europe/Amsterdam", "2026-12-09T10:00:00+01:00"),
    ("9 december 2026 om 10.00 uur", "nl", "Europe/Amsterdam", "2026-12-09T10:00:00+01:00"),
    ("9 December 2026 at 10:00", "en", "Europe/London", "2026-12-09T10:00:00+00:00"),
    ("9 December 2026, at 10:00", "en", "Europe/London", "2026-12-09T10:00:00+00:00"),
    ("9 December 2026 at 10 h", "en", "Europe/London", "2026-12-09T10:00:00+00:00"),
    ("9 December 2026 UTC 10:00", "en", "Europe/London", "2026-12-09T10:00:00+00:00"),
    ("9 dicembre 2026 ore 10:00", "it", "Europe/Rome", "2026-12-09T10:00:00+01:00"),
    ("9 dicembre 2026 alle 10:00", "it", "Europe/Rome", "2026-12-09T10:00:00+01:00"),
    ("9 dicembre 2026 alle ore 10:00", "it", "Europe/Rome", "2026-12-09T10:00:00+01:00"),
    ("9 dicembre 2026 - ore 10:00", "it", "Europe/Rome", "2026-12-09T10:00:00+01:00"),
    ("9 de diciembre de 2026 a las 10:00", "es", "Europe/Madrid", "2026-12-09T10:00:00+01:00"),
    ("9 de diciembre de 2026, a las 10:00", "es", "Europe/Madrid", "2026-12-09T10:00:00+01:00"),
    ("9 grudnia 2026 o 10:00", "pl", "Europe/Warsaw", "2026-12-09T10:00:00+01:00"),
    ("9 grudnia 2026 godz. 10:00", "pl", "Europe/Warsaw", "2026-12-09T10:00:00+01:00"),
    ("9 grudnia 2026 o godz. 10:00", "pl", "Europe/Warsaw", "2026-12-09T10:00:00+01:00"),
    ("9 grudnia 2026 r. 10:00", "pl", "Europe/Warsaw", "2026-12-09T10:00:00+01:00"),
    ("9 grudnia 2026 r. o godz. 10:00", "pl", "Europe/Warsaw", "2026-12-09T10:00:00+01:00"),
    ("9 grudnia 2026 r., godz. 10:00", "pl", "Europe/Warsaw", "2026-12-09T10:00:00+01:00"),
    ("9 grudnia 2026 roku o godz. 10:00", "pl", "Europe/Warsaw", "2026-12-09T10:00:00+01:00"),
    # Ordinary cell texts: nothing, a comma or a dash before the time.
    ("12 mars 2027 10:00", "fr", "Europe/Paris", "2027-03-12T10:00:00+01:00"),
    ("12 mars 2027, 10:00", "fr", "Europe/Paris", "2027-03-12T10:00:00+01:00"),
    ("12 mars 2027 - 10:00", "fr", "Europe/Paris", "2027-03-12T10:00:00+01:00"),
    ("12. März 2027 10:00 Uhr", "de", "Europe/Berlin", "2027-03-12T10:00:00+01:00"),
])
def test_time_right_after_the_date_or_after_a_lead_in_is_read(raw, language, zone, expected):
    p = parse(spec(T.datetime), raw, ctx(zone=ZoneInfo(zone), language=language))
    assert p.value is not None, p.problem
    assert p.value.isoformat() == expected and p.note is None


def test_lead_in_rule_leaves_dates_read_by_a_format_alone():
    # The rule is about dates with the month as a word; a recipe's own format is what it says.
    p = parse(spec(T.datetime, ["%d.%m.%Y %H:%M"]), "12.03.2027 10:00", ctx())
    assert p.value.isoformat() == "2027-03-12T10:00:00+01:00"
    p = parse(spec(T.datetime, ["Deadline: %d %B %Y %H:%M"]), "Deadline: 12 March 2027 10:00", ctx(language="en"))
    assert p.value.isoformat() == "2027-03-12T10:00:00+01:00"


@pytest.mark.parametrize("raw, expected", [
    # Test cases from pull request 32 by Danil: the French dates named in docs/HANDOFF.md (Q2).
    ("1er décembre 2026 à 10h00", "2026-12-01T10:00:00+01:00"),
    ("Le 1er décembre 2026 à 9 h 30", "2026-12-01T09:30:00+01:00"),
    ("1er avril 2027 à 12 h 00", "2027-04-01T12:00:00+02:00"),      # summer time
    ("1er décembre 2026 à 12 h 00 et 14 h 00", None),                # two times
    ("2er décembre 2026 10:00", None),                               # only the first takes "er"
])
def test_french_dates_from_pull_request_32(raw, expected):
    p = parse(spec(T.datetime), raw, ctx(zone=PARIS, language="fr"))
    if expected is None:
        assert p.value is None and p.problem and p.raw == raw
    else:
        assert p.value is not None, p.problem
        assert p.value.isoformat() == expected and p.note is None


def test_every_month_word_is_read_and_names_one_month_in_every_language():
    from app.extract.moments import _MONTH_WORDS, _MONTHS

    assert set(_MONTHS) == {"de", "fr", "es", "nl", "pl", "it", "en"}
    for word, readings in _MONTH_WORDS.items():
        assert len(set(readings.values())) == 1, word
    for language, names in _MONTHS.items():
        assert len(names) == 12
        for month, words in enumerate(names, start=1):
            for word in words.split():
                for written in (f"15 {word} 2027", f"15 {word.upper()}. 2027"):
                    assert parse(spec(T.date), written, ctx(language=language)).value == date(2027, month, 15), written


# == datetime: zones written on the page ==

def test_zone_name_of_the_other_season_is_refused():
    # "MEZ" on a summer date in Berlin: either loose wording or an hour off. Not ours to pick.
    for raw in ["9. Juli 2026 10:00 MEZ", "9. Juli 2026 10:00 CET", "9. Dezember 2026 10:00 MESZ"]:
        p = parse(spec(T.datetime), raw, ctx())
        assert p.value is None and p.problem == "zone name does not match the date in the portal's zone", raw
    p = parse(spec(T.datetime), "9 July 2026 10:00 GMT", ctx(zone=ZoneInfo("Europe/London"), language="en"))
    assert p.value is None and p.problem
    assert parse(spec(T.date), "9. Juli 2026 10:00 MEZ", ctx()).value == date(2026, 7, 9)


def test_zone_name_that_fits_or_belongs_to_another_zone_is_kept():
    assert parse(spec(T.datetime), "9. Juli 2026 10:00 MESZ", ctx()).value.isoformat() == "2026-07-09T10:00:00+02:00"
    assert parse(spec(T.datetime), "9. Dezember 2026 10:00 MEZ", ctx()).value.isoformat() == "2026-12-09T10:00:00+01:00"
    # Another zone's name, and a number, are what the page says.
    lisbon = ctx(zone=ZoneInfo("Europe/Lisbon"), language="en")
    assert parse(spec(T.datetime), "9 December 2026 10:00 CET", lisbon).value.isoformat() == "2026-12-09T10:00:00+01:00"
    assert parse(spec(T.datetime), "9. Juli 2026 10:00 UTC", ctx()).value.isoformat() == "2026-07-09T10:00:00+00:00"
    assert parse(spec(T.datetime), "9. Juli 2026 10:00 UTC+1", ctx()).value.isoformat() == "2026-07-09T10:00:00+01:00"
    # In the hour that exists twice, the name says which one is meant.
    assert parse(spec(T.datetime), "31. Oktober 2027 02:30 MEZ", ctx()).value.isoformat() == "2027-10-31T02:30:00+01:00"
    assert parse(spec(T.datetime), "31. Oktober 2027 02:30 MESZ", ctx()).value.isoformat() == "2027-10-31T02:30:00+02:00"


def test_zone_spelled_out_in_a_format_is_kept():
    # The format matched the "Z", so the text is in UTC, not in the portal's zone.
    p = parse(spec(T.datetime, ["%Y-%m-%dT%H:%M:%SZ"]), "2026-12-09T09:00:00Z", ctx())
    assert p.value.isoformat() == "2026-12-09T09:00:00+00:00"
    p = parse(spec(T.datetime, ["%d.%m.%Y %H:%M UTC"]), "09.12.2026 09:00 UTC", ctx())
    assert p.value.isoformat() == "2026-12-09T09:00:00+00:00"
    p = parse(spec(T.datetime, ["%d/%m/%Y %H:%M (UTC+2)"]), "05/05/2026 13:00 (UTC+2)", ctx())
    assert p.value.isoformat() == "2026-05-05T13:00:00+02:00"
    p = parse(spec(T.datetime, ["%d.%m.%Y %H:%M Uhr MEZ"]), "09.12.2026 10:00 Uhr MEZ", ctx())
    assert p.value.isoformat() == "2026-12-09T10:00:00+01:00"
    assert parse(spec(T.datetime, ["%d.%m.%Y %H:%M Uhr MEZ"]), "09.07.2026 10:00 Uhr MEZ", ctx()).value is None
    assert parse(spec(T.datetime, ["%d.%m.%Y %H:%M MEZ/UTC"]), "09.12.2026 10:00 MEZ/UTC", ctx()).value is None
    # A "T" or a "Z" inside a word of the format is not a zone.
    p = parse(spec(T.datetime, ["Zeit: %d.%m.%Y %H:%M"]), "Zeit: 09.12.2026 10:00", ctx())
    assert p.value.isoformat() == "2026-12-09T10:00:00+01:00"


@pytest.mark.parametrize("fmt, raw", [
    ("%m/%Y", "12/2026"),                 # no day: strptime would say the 1st
    ("%B %Y", "December 2026"),
    ("%d.%m. %H:%M", "09.12. 10:00"),     # no year
    ("%d %Y", "09 2026"),                 # no month
    ("%H:%M", "10:00"),
])
def test_format_that_does_not_read_a_whole_date_is_not_used(fmt, raw):
    for type_ in (T.date, T.datetime):
        p = parse(spec(type_, [fmt]), raw, ctx())
        assert p.value is None and p.problem, (fmt, type_, p)


def test_formats_with_names_day_of_year_and_two_digit_years_are_used():
    assert parse(spec(T.date, ["%d %B %Y"]), "9 December 2026", ctx()).value == date(2026, 12, 9)
    assert parse(spec(T.date, ["%d-%b-%y"]), "09-Dec-26", ctx()).value == date(2026, 12, 9)
    assert parse(spec(T.date, ["%Y-%j"]), "2026-343", ctx()).value == date(2026, 12, 9)
    assert parse(spec(T.date, ["%d.%m.%y"]), "09.12.99", ctx()).problem == "year out of range"  # read as 1999


def test_zone_name_format_is_not_used():
    # %Z reads "UTC" but drops it: the wall clock would land in Berlin
    p = parse(spec(T.datetime, ["%d.%m.%Y %H:%M %Z"]), "09.12.2026 10:00 UTC", ctx())
    assert p.value is None


# == date ==

def test_dates():
    assert parse(spec(T.date, ["%d.%m.%Y"]), "20.11.2026", ctx()).value == date(2026, 11, 20)
    assert parse(spec(T.date, ["%d/%m/%Y"]), "03/04/2026", ctx()).value == date(2026, 4, 3)
    assert parse(spec(T.date), "2026-11-20", ctx()).value == date(2026, 11, 20)
    assert parse(spec(T.date), "20 listopada 2026", ctx(language="pl")).value == date(2026, 11, 20)
    assert parse(spec(T.date), "2026-11-20T08:15:00+01:00", ctx()).value == date(2026, 11, 20)


def test_date_pattern_then_format():
    s = spec(T.date, ["%d.%m.%Y"], pattern=r"am (\d{2}\.\d{2}\.\d{4})")
    assert parse(s, "Veröffentlicht am 20.11.2026 um 08:00", ctx()).value == date(2026, 11, 20)


# == cpv ==

@pytest.mark.parametrize("raw, expected", [
    ("45233120-6 Straßenbauarbeiten", ["45233120"]),
    ("45233120", ["45233120"]),
    ("45000000-7 Bauarbeiten, 45233120-6 Straßenbauarbeiten; 71322000-1 Ingenieurleistungen",
     ["45000000", "45233120", "71322000"]),
    ("Hauptteil: 45233120-6\nZusatzteil: 45233120 - 6, 45112500-0", ["45233120", "45112500"]),
    ("CPV: 72000000-5 (IT-Dienste), 48000000-8", ["72000000", "48000000"]),
])
def test_cpv_codes(raw, expected):
    p = parse(spec(T.cpv), raw, ctx())
    assert p.value == expected and p.problem is None


@pytest.mark.parametrize("raw", ["Straßenbauarbeiten", "4523312-6", "452331206", "Tel. 030 12345678",
                                 "Aktenzeichen 20261209"])
def test_no_cpv_code_is_none(raw):
    p = parse(spec(T.cpv), raw, ctx())
    assert p.value is None and p.problem


# == word maps ==

PROC = {"Offenes Verfahren": "open", "Öffentliche Ausschreibung": "open", "Nicht offenes Verfahren": "restricted",
        "Verhandlungsverfahren": "negotiated", "Beschränkte Ausschreibung": "restricted"}


def test_words_exact_match_ignores_case_and_spacing():
    s = spec(T.procedure, words=PROC)
    assert parse(s, "offenes   verfahren", ctx()).value == "open"
    assert parse(s, "NICHT OFFENES VERFAHREN", ctx()).value == "restricted"
    assert isinstance(parse(s, "Offenes Verfahren", ctx()).value, str)


def test_words_contained_match_when_only_one():
    s = spec(T.procedure, words=PROC)
    assert parse(s, "Verhandlungsverfahren mit Teilnahmewettbewerb", ctx()).value == "negotiated"
    assert parse(s, "Verfahrensart: Offenes Verfahren (EU)", ctx()).value == "open"
    # Both "nicht offenes verfahren" and "offenes verfahren" are contained, with different values.
    # The longer word is not preferred: two values is ambiguous (an exact match would have won).
    assert parse(s, "Nicht offenes Verfahren nach VgV", ctx()).problem == "ambiguous"


def test_words_ambiguous_and_unknown():
    s = spec(T.procedure, words=PROC)
    p = parse(s, "Offenes Verfahren oder Verhandlungsverfahren", ctx())
    assert p.value is None and p.problem == "ambiguous"
    p = parse(s, "Wettbewerblicher Dialog", ctx())
    assert p.value is None and p.problem == "unknown word"
    # two words, same value: not ambiguous
    assert parse(s, "Offenes Verfahren / Öffentliche Ausschreibung", ctx()).value == "open"


def test_short_codes_match_whole_words_only():
    s = spec(T.nature, words={"W": "works", "D": "services", "L": "supplies"})
    assert parse(s, "W", ctx()).value == "works"
    assert parse(s, "Works", ctx()).problem == "unknown word"


def test_status_and_nature():
    status = spec(T.status, words={"Laufend": "open", "Beendet": "closed", "Aufgehoben": "withdrawn"})
    assert parse(status, "laufend", ctx()).value == "open"
    assert parse(status, "Verfahren aufgehoben", ctx()).value == "withdrawn"
    assert parse(status, "In Bearbeitung", ctx()).value is None
    nature = spec(T.nature, words={"Bauleistung": "works", "Dienstleistung": "services", "Lieferleistung": "supplies"})
    assert parse(nature, "Bauleistung", ctx()).value == "works"


def test_word_map_value_outside_the_contract_is_none():
    p = parse(spec(T.status, words={"Laufend": "running"}), "Laufend", ctx())
    assert p.value is None and p.problem


def test_no_word_map_is_none_never_a_default():
    p = parse(spec(T.status), "Laufend", ctx())
    assert p.value is None and p.problem


# == country and postal code ==

@pytest.mark.parametrize("raw, expected", [
    ("DE", "DE"), ("US", "US"), ("NLD", "NL"), ("Deutschland", "DE"), ("deutschland", "DE"),
    ("Germany", "DE"), ("France", "FR"), ("España", "ES"), ("Polska", "PL"), ("Italia", "IT"),
    ("Nederland", "NL"), ("Österreich", "AT"), ("Belgique", "BE"), ("Norge", "NO"), ("EL", "GR"),
])
def test_countries(raw, expected):
    assert parse(spec(T.country), raw, ctx()).value == expected


@pytest.mark.parametrize("raw", ["XX", "de", "Berlin", "Bayern", "Deutschland, Berlin", "USA", "EU"])
def test_not_countries(raw):
    p = parse(spec(T.country), raw, ctx())
    assert p.value is None and p.problem


def test_country_word_map_first():
    s = spec(T.country, words={"Nederland": "NL", "NLD": "NL", "Holland": "nl"})
    assert parse(s, "Holland", ctx()).value == "NL"
    assert parse(s, "BE", ctx()).value == "BE"  # falls through to the ISO code
    assert parse(spec(T.country, words={"Inland": "Deutschland"}), "Inland", ctx()).value is None


def test_iso_list_is_complete():
    assert len(ISO_ALPHA2) == 249


@pytest.mark.parametrize("raw", ["10115", "D-10115", "1012 AB", "75001", "00-950", "D02 X285", "SW1A 1AA"])
def test_postal_codes(raw):
    assert parse(spec(T.postal_code), raw, ctx()).value == raw


@pytest.mark.parametrize("raw", ["Berlin", "12", "10115 Berlin Mitte", "10115;", "D-"])
def test_not_postal_codes(raw):
    p = parse(spec(T.postal_code), raw, ctx())
    assert p.value is None and p.problem


# == settings ==

def test_settings_from_env():
    s = ExtractSettings.from_env({"EXTRACT_DATE_ONLY_DEADLINE": "null", "EXTRACT_MIN_YEAR": "2010"})
    assert s.date_only_deadline == "null" and s.min_year == 2010 and s.max_year == 2100
    assert ExtractSettings.from_env({}) == ExtractSettings()
    with pytest.raises(ValueError):
        ExtractSettings(date_only_deadline="noon")


def test_default_context_settings():
    assert ParseContext(zone=None, page_url=None, language=None).settings == ExtractSettings()


# == the rule: nothing unreadable becomes a value ==

GARBAGE = ["n/a", "-", "—", "siehe Unterlagen", "???", "0", "null", "undefined", "<span></span>",
           "Lorem ipsum dolor sit amet"]


@pytest.mark.parametrize("raw", GARBAGE)
@pytest.mark.parametrize("type_", [T.date, T.datetime, T.cpv, T.status, T.procedure, T.nature, T.country,
                                   T.postal_code])
def test_garbage_is_never_a_value(raw, type_):
    words = {"Laufend": "open"} if type_ is T.status else {"Offenes Verfahren": "open"} \
        if type_ is T.procedure else {"Bauleistung": "works"} if type_ is T.nature else None
    p = parse(spec(type_, DE_FORMATS if type_ in (T.date, T.datetime) else None, words), raw, ctx())
    assert p.value is None and p.problem and p.raw == clean(raw)


def test_aware_datetimes_only():
    for raw in ["09.12.2026 10:00", "2026-12-09", "9. Dezember 2026 10:00", "2026-12-09T10:00:00Z"]:
        value = parse(spec(T.datetime, DE_FORMATS), raw, ctx()).value
        assert isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
        assert value.astimezone(timezone.utc)  # a real instant
