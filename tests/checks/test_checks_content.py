"""Step 3 (C1 to C7, D1, F1) on made-up reads. No page is fetched and no model is called."""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.checks import (  # noqa: E402
    Answer, CanaryPage, Cause, CheckSettings, DetailLook, Effect, DownloadFacts, LookOutcome, canary, cause_of,
    confirm, confirm_missing, duplicate_ids, effect_of, file_outcome, files_failed, fingerprint, html_paths,
    json_paths, known_ids_missing, known_tenders_reproduce, null_rates, overlap, paging_complete,
    printed_total, shape, shape_problems, stale, structure, structure_floor, without_bad_values,
)
from app.models import PortalState, Severity, TenderRecord  # noqa: E402

UTC = timezone.utc
CET = timezone(timedelta(hours=1))
NOW = datetime(2026, 11, 20, 14, 2, tzinfo=UTC)


def tender(n: int, **changes) -> TenderRecord:
    values = dict(
        portal_id="p1", tender_id=f"T-{n:04d}", url=f"https://portal.example/t/{n}", title=f"Road works {n}",
        buyer_name="Stadt X", publication_date=date(2026, 11, 10),
        submission_deadline=datetime(2026, 12, 9, 10, 0, tzinfo=CET),
    )
    values.update(changes)
    return TenderRecord(**values)


def tenders(n: int) -> list[TenderRecord]:
    return [tender(i) for i in range(1, n + 1)]


def by_name(rows):
    return {row.name: row for row in rows}


# -- C1 ----------------------------------------------------------------------

def test_c1_passes_on_a_complete_list():
    assert paging_complete("r1", reached_end=True, pages=3).passed
    assert duplicate_ids("r1", ["a", "b", "c"]).passed
    assert printed_total("r1", extracted=23, printed=23).passed
    assert printed_total("r1", extracted=23, printed=None).passed  # the portal prints no total


def test_c1_failures_are_suspects_until_the_list_was_read_again():
    cut = paging_complete("r1", reached_end=False, pages=1)
    twice = duplicate_ids("r1", ["a", "b", "a"])
    short = printed_total("r1", extracted=9, printed=23)
    for row in (cut, twice, short):
        assert effect_of(row) is Effect.suspect and cause_of(row) is Cause.breakage
    assert twice.observed["examples"] == ["a"]
    assert short.message == "The list reads 9 tenders but the portal prints 23."


def test_c1_a_list_that_changed_while_we_paged_clears_on_the_second_read():
    first = printed_total("r1", extracted=22, printed=23)
    cleared = confirm(first, printed_total("r1", extracted=23, printed=23))
    assert cleared.passed and cleared.severity is Severity.info
    confirmed = confirm(first, printed_total("r1", extracted=22, printed=23))
    assert effect_of(confirmed) is Effect.breakage and confirmed.severity is Severity.fail


# -- C2 ----------------------------------------------------------------------

def test_c2_clean_records_have_no_problems():
    assert shape_problems(tenders(5), id_pattern=r"T-\d{4}") == []
    assert all(row.passed for row in shape("r1", tenders(5), id_pattern=r"T-\d{4}"))


@pytest.mark.parametrize("title", ["Road <b>works</b>", "Road works<br/>", "Caf&eacute; fit-out", "A &#8211; B",
                                   "<!-- row -->Road works"])
def test_c2_a_value_with_markup_is_found(title):
    problems = shape_problems([tender(1, title=title)])
    assert [(p.field, p.problem) for p in problems] == [("title", "markup")]


@pytest.mark.parametrize("title", ["R&D services", "AT&T; network", "Works < 5 km & > 2 km", "Lot 3: a<b"])
def test_c2_text_that_only_looks_a_little_like_markup_is_left_alone(title):
    assert shape_problems([tender(1, title=title)]) == []


def test_c2_an_id_that_does_not_have_the_learned_shape_is_found():
    problems = shape_problems([tender(1), tender(2, tender_id="row-17")], id_pattern=r"T-\d{4}")
    assert [(p.tender_id, p.field, p.problem) for p in problems] == [("row-17", "tender_id", "id shape")]


def test_c2_a_value_that_was_extracted_but_could_not_be_read_is_found():
    record = tender(1, submission_deadline=None, raw={"submission_deadline": "9. Dezember, vormittags"})
    assert [(p.field, p.problem) for p in shape_problems([record])] == [("submission_deadline", "not read")]
    # A value the portal does not show at all is not a problem.
    assert shape_problems([tender(1, submission_deadline=None)]) == []


def test_c2_a_deadline_before_publication_takes_both_values_out():
    swapped = tender(1, publication_date=date(2026, 12, 9), submission_deadline=datetime(2026, 11, 10, 10, tzinfo=CET))
    problems = shape_problems([swapped])
    assert {p.field for p in problems} == {"publication_date", "submission_deadline"}
    cleaned = without_bad_values(swapped, problems)
    assert cleaned.publication_date is None and cleaned.submission_deadline is None
    assert cleaned.title == swapped.title


def test_c2_values_are_nulled_and_a_record_with_a_bad_id_is_left_out():
    records = [tender(1, title="<td>Road works</td>"), tender(2, tender_id="<a>7</a>"), tender(3)]
    problems = shape_problems(records)
    cleaned = [without_bad_values(record, problems) for record in records]
    assert cleaned[0].title is None and cleaned[0].buyer_name == "Stadt X"
    assert cleaned[1] is None
    assert cleaned[2] is records[2]


def test_c2_rows_warn_per_field_and_never_change_the_state_alone():
    rows = by_name(shape("r1", [tender(1, title="<b>x</b>"), tender(2), tender(3)]))
    assert not rows["shape.title"].passed and rows["shape.title"].severity is Severity.warn
    assert effect_of(rows["shape.title"]) is Effect.note
    assert rows["shape.title"].message == ("The title of 1 of 3 tenders cannot be used (1 with markup in it). "
                                           "Such a value is sent as null, never as a wrong one.")
    assert rows["shape.buyer_name"].passed


# -- C3 ----------------------------------------------------------------------

def lose(records, field, how_many):
    return [r.model_copy(update={field: None}) if i < how_many else r for i, r in enumerate(records)]


def test_c3_identical_known_tenders_pass_every_field():
    rows = known_tenders_reproduce("r1", tenders(10), tenders(10))
    assert len(rows) == 10 and all(row.passed for row in rows)


@pytest.mark.parametrize("known, alarm", [(3, 2), (10, 3), (50, 5), (500, 14)])
def test_c3_lost_values_alarm_at_the_counts_of_the_research(known, alarm):
    good = tenders(known)
    below = by_name(known_tenders_reproduce("r1", lose(good, "title", alarm - 1), good))["lost.title"]
    at = by_name(known_tenders_reproduce("r1", lose(good, "title", alarm), good))["lost.title"]
    assert below.passed and below.expected == {"alarm_at": alarm}
    assert effect_of(at) is Effect.suspect and cause_of(at) is Cause.breakage


@pytest.mark.parametrize("known, alarm", [(3, 3), (10, 3), (50, 6), (500, 22)])
def test_c3_changed_values_ask_for_a_spot_check_at_the_counts_of_the_research(known, alarm):
    good = tenders(known)

    def change(how_many):
        return [r.model_copy(update={"buyer_name": "Gemeinde Y"}) if i < how_many else r
                for i, r in enumerate(good)]

    below = by_name(known_tenders_reproduce("r1", change(alarm - 1), good))["changed.buyer_name"]
    at = by_name(known_tenders_reproduce("r1", change(alarm), good))["changed.buyer_name"]
    assert below.passed
    assert effect_of(at) is Effect.spot_check and at.severity is Severity.warn


def test_c3_compares_only_tenders_present_in_both_reads():
    good = tenders(10)
    now = good[:4] + [tender(99, title=None)]          # six left the list, one is new and has no title
    rows = by_name(known_tenders_reproduce("r1", now, good))
    assert rows["lost.title"].passed and rows["lost.title"].observed["known"] == 4


def test_c3_a_value_that_was_already_missing_is_not_lost():
    good = lose(tenders(10), "url", 5)
    rows = by_name(known_tenders_reproduce("r1", good, good))
    assert rows["lost.url"].passed and rows["lost.url"].observed["known"] == 5


def test_c3_the_same_instant_in_another_offset_is_not_a_change():
    good = [tender(1)]
    same = [tender(1, submission_deadline=datetime(2026, 12, 9, 9, 0, tzinfo=UTC))]
    assert by_name(known_tenders_reproduce("r1", same, good))["changed.submission_deadline"].observed["changed"] == 0


def test_c3_one_lost_value_on_a_single_known_tender_is_reread_and_then_spot_checked():
    good = [tender(1)]
    now = lose(good, "submission_deadline", 1)
    first = by_name(known_tenders_reproduce("r1", now, good))["lost.submission_deadline"]
    assert effect_of(first) is Effect.suspect and first.observed["if_confirmed"] == "spot_check"
    again = by_name(known_tenders_reproduce("r1", now, good))["lost.submission_deadline"]
    assert effect_of(confirm(first, again)) is Effect.spot_check
    back = by_name(known_tenders_reproduce("r1", good, good))["lost.submission_deadline"]
    assert confirm(first, back).passed


# -- C4 ----------------------------------------------------------------------

def looks(ids, outcome):
    return [DetailLook(tender_id=tender_id, outcome=outcome) for tender_id in ids]


def test_c4_all_known_open_tenders_listed_passes():
    good = tenders(3)
    assert known_ids_missing("r1", good, [t.tender_id for t in good], now=NOW).passed
    assert known_ids_missing("r1", [], [], now=NOW).passed


def test_c4_one_withdrawn_tender_in_a_portal_of_three_is_accepted_once_its_page_says_so():
    good = tenders(3)
    first = known_ids_missing("r1", good, ["T-0001", "T-0002"], now=NOW)
    assert effect_of(first) is Effect.suspect and first.observed["second_look"] == "detail_pages"
    assert first.observed["look_at"] == ["T-0003"] and first.observed["mass"] is False
    result = confirm_missing(first, looks(["T-0003"], LookOutcome.withdrawn))
    assert result.passed and result.severity is Severity.info
    assert result.observed["withdrawn"] == ["T-0003"] and result.observed["first"]["missing"] == 1
    assert result.message == ("The list no longer shows 1 of 3 known open tenders. "
                              "The 1 page we looked at says: 1 withdrawn.")


def test_c4_one_missing_tender_whose_page_still_shows_it_open_is_a_breakage():
    first = known_ids_missing("r1", tenders(3), ["T-0001", "T-0002"], now=NOW)
    result = confirm_missing(first, looks(["T-0003"], LookOutcome.still_open))
    assert effect_of(result) is Effect.breakage and result.severity is Severity.fail
    assert "T-0003" in result.message and "still shows it open" in result.message


def test_c4_a_page_that_does_not_say_is_not_accepted_and_one_that_does_not_answer_is_an_outage():
    first = known_ids_missing("r1", tenders(3), ["T-0001", "T-0002"], now=NOW)
    assert effect_of(confirm_missing(first, looks(["T-0003"], LookOutcome.unclear))) is Effect.breakage
    assert effect_of(confirm_missing(first, looks(["T-0003"], LookOutcome.no_answer))) is Effect.outage


def test_c4_tenders_whose_deadline_passed_or_that_were_closed_are_not_missed():
    past = tender(1, submission_deadline=NOW - timedelta(hours=1))
    unknown = tender(2, submission_deadline=None)
    closed = tender(3, listed=False)
    cancelled = tender(4, withdrawn=True)
    result = known_ids_missing("r1", [past, unknown, closed, cancelled, tender(5)], ["T-0005"], now=NOW)
    assert result.passed and result.observed["known"] == 1


def test_c4_looks_at_no_more_than_five_pages_latest_deadline_first():
    good = [tender(i, submission_deadline=NOW + timedelta(days=i)) for i in range(1, 21)]
    first = known_ids_missing("r1", good, [t.tender_id for t in good[:13]], now=NOW)
    assert first.observed["missing"] == 7
    assert first.observed["look_at"] == ["T-0020", "T-0019", "T-0018", "T-0017", "T-0016"]
    with pytest.raises(ValueError):
        confirm_missing(first, looks(["T-0020"], LookOutcome.closed))  # four pages were not looked at


@pytest.mark.parametrize("known, alarm", [(3, 3), (10, 5), (50, 9), (500, 42)])
def test_c4_a_mass_disappearance_starts_at_the_counts_of_the_research(known, alarm):
    good = tenders(known)
    ids = [t.tender_id for t in good]
    below = known_ids_missing("r1", good, ids[alarm - 1:], now=NOW)
    at = known_ids_missing("r1", good, ids[alarm:], now=NOW)
    assert below.observed["mass"] is False and at.observed["mass"] is True
    assert at.expected == {"alarm_at": alarm}


def test_c4_a_mass_disappearance_also_needs_the_list_to_be_whole():
    good = tenders(10)
    first = known_ids_missing("r1", good, [t.tender_id for t in good[5:]], now=NOW)
    closed = looks(first.observed["look_at"], LookOutcome.closed)
    refused = confirm_missing(first, closed)
    assert effect_of(refused) is Effect.breakage and "5 of 10" in refused.message
    assert confirm_missing(first, closed, structure_intact=True).passed
    assert confirm_missing(first, closed, printed_total_agrees=True).passed
    assert confirm_missing(first, closed, proven_empty=True).passed
    # Even a whole list does not excuse a tender whose own page shows it open.
    one_open = closed[:-1] + looks([first.observed["look_at"][-1]], LookOutcome.still_open)
    assert effect_of(confirm_missing(first, one_open, structure_intact=True)) is Effect.breakage


def test_c4_after_a_week_without_a_good_read_more_tenders_may_have_left():
    good = tenders(50)
    ids = [t.tender_id for t in good]
    assert known_ids_missing("r1", good, ids[9:], now=NOW).observed["mass"] is True
    late = known_ids_missing("r1", good, ids[9:], now=NOW, since_last_good=timedelta(days=7))
    assert late.observed["rate"] == 0.126 and late.observed["mass"] is False


def test_c4_refuses_a_time_without_an_offset():
    with pytest.raises(ValueError):
        known_ids_missing("r1", tenders(3), [], now=datetime(2026, 11, 20, 14, 2))


# -- C5 ----------------------------------------------------------------------

def new_rows(n, nulls):
    return [tender(100 + i, buyer_name=None if i < nulls else "Stadt X") for i in range(n)]


@pytest.mark.parametrize("nulls, earlier_rows, suspect", [
    (3, 20, True),     # 3 nulls among 3 new rows, none in 20 before
    (2, 20, False),
    (2, 200, True),    # with 200 earlier rows, 2 among 3 is significant
    (3, 5, False),     # five rows do not establish a rate
])
def test_c5_fisher_cases_from_the_research(nulls, earlier_rows, suspect):
    row = by_name(null_rates("r1", new_rows(3, nulls), earlier_nulls={}, earlier_rows=earlier_rows))
    result = row["null_rate.buyer_name"]
    assert (effect_of(result) is Effect.suspect) is suspect
    assert result.passed is not suspect


def test_c5_a_field_that_was_often_missing_before_is_not_an_alarm():
    rows = by_name(null_rates("r1", new_rows(10, 4), earlier_nulls={"buyer_name": 90}, earlier_rows=200))
    assert rows["null_rate.buyer_name"].passed and rows["null_rate.title"].passed


def test_c5_nothing_to_compare_passes():
    assert all(row.passed for row in null_rates("r1", [], earlier_nulls={}, earlier_rows=200))
    assert all(row.passed for row in null_rates("r1", new_rows(3, 3), earlier_nulls={}, earlier_rows=0))


# -- C6 ----------------------------------------------------------------------

def page(n, **read):
    values = dict(tender_id=f"T-{n:04d}", title=f"Road works {n}", read_id=f"T-{n:04d}", read_title=f"Road works {n}")
    values.update(read)
    return CanaryPage(**values)


def test_c6_two_known_pages_and_a_valid_file_pass():
    result = canary("r1", [page(1), page(2)], file_valid=True)
    assert result.message == ("The 2 known tender pages gave the same id and title as before, "
                              "and the known file is valid.")
    assert canary("r1", [page(1), page(2)]).passed  # a portal without a known file


def test_c6_must_fail_twice_to_be_a_breakage():
    bad = canary("r1", [page(1), page(2, read_title="Stadt X")], file_valid=True)
    assert effect_of(bad) is Effect.suspect and "T-0002" in bad.message
    assert confirm(bad, canary("r1", [page(1), page(2)], file_valid=True)).passed
    assert effect_of(confirm(bad, bad)) is Effect.breakage
    assert effect_of(canary("r1", [page(1), page(2)], file_valid=False)) is Effect.suspect


# -- C7 ----------------------------------------------------------------------

def list_page(rows, table_class="results", cell="title"):
    body = "".join(
        f'<tr class="row {"odd" if i % 2 else "even"}" id="t{i}"><td class="{cell}"><a href="/t/{i}">Works {i}</a>'
        f'</td><td class="deadline">0{i}.12.2026</td></tr>' for i in range(1, rows + 1))
    return (f'<html><head><title>Tenders</title></head><body><div id="main"><h1>Tenders</h1>'
            f'<table class="{table_class}"><thead><tr><th>Title</th><th>Deadline</th></tr></thead>'
            f'<tbody>{body}</tbody></table><p class="total">{rows} results</p></div></body></html>')


def test_c7_more_or_fewer_tenders_never_look_like_a_change():
    assert fingerprint(html_paths(list_page(3))) == fingerprint(html_paths(list_page(40)))
    assert fingerprint(html_paths(list_page(1))) == fingerprint(html_paths(list_page(2)))


def test_c7_text_and_numeric_ids_are_ignored():
    a = '<div class="tender tender-4711"><span class="title">Road works</span></div>'
    b = '<div class="tender tender-9"><span class="title">Bridge repair, lot 2</span></div>'
    assert html_paths(a) == html_paths(b) == {"div.tender.tender-#", "div.tender.tender-#/span.title"}


def test_c7_rows_without_end_tags_do_not_nest_deeper_with_every_row():
    two = "<table><tr><td>a<td>b<tr><td>c<td>d</table><ul><li>x<li>y</ul>"
    five = "<table>" + "<tr><td>a<td>b" * 5 + "</table><ul>" + "<li>x" * 5 + "</ul>"
    assert html_paths(two) == html_paths(five) == {"table", "table/tr", "table/tr/td", "ul", "ul/li"}


def test_c7_json_key_paths_ignore_values_positions_and_numeric_keys():
    one = {"total": 1, "items": [{"id": 7, "title": "a", "buyer": {"name": "x"}}]}
    many = {"total": 3, "items": [{"id": i, "title": "t", "buyer": {"name": "y"}} for i in range(3)]}
    assert json_paths(one) == json_paths(many) == {
        "total", "items", "items[]", "items[].id", "items[].title", "items[].buyer", "items[].buyer.name"}
    assert json_paths({"byId": {"17": {"a": 1}, "18": {"a": 2}}}) == {"byId", "byId.#", "byId.#.a"}
    renamed = {"total": 1, "results": [{"id": 7, "name": "a", "buyer": {"name": "x"}}]}
    assert overlap(json_paths(one), json_paths(renamed)) < 0.5


def test_c7_an_equal_hash_is_unchanged():
    stored = html_paths(list_page(3))
    result = structure("r1", html_paths(list_page(25)), stored, floor=0.9)
    assert result.passed and result.name == "structure" and "unchanged" in result.message


def test_c7_a_small_difference_above_the_floor_passes_and_a_change_asks_for_a_spot_check():
    stored = html_paths(list_page(3))
    banner = list_page(3).replace("<h1>", '<div class="banner">Maintenance on Sunday</div><h1>')
    small = structure("r1", html_paths(banner), stored, floor=0.8)
    assert small.passed and small.observed["overlap"] < 1
    changed = structure("r1", html_paths(list_page(3, table_class="grid", cell="name")), stored, floor=0.8)
    assert not changed.passed and changed.severity is Severity.warn
    assert effect_of(changed) is Effect.spot_check          # never a failure alone
    assert structure("r1", html_paths("<p>x</p>"), stored, floor=0.8, page="detail").name == "structure.detail"


def test_c7_the_floor_is_the_lowest_overlap_at_attach_minus_the_margin():
    a, b, c = {"x", "y", "z", "w"}, {"x", "y", "z"}, {"x", "y"}
    assert structure_floor([a, b, c]) == pytest.approx(0.5 - 0.1)
    assert structure_floor([a]) == pytest.approx(0.9)
    assert structure_floor([a, c], CheckSettings(structure_floor_margin=0.7)) == 0.0


# -- D1 ----------------------------------------------------------------------

def good_file(n):
    return file_outcome("r1", DownloadFacts(file_name=f"doc{n}.pdf", answer=Answer(status=200, page_load=False),
                                            first_bytes=b"%PDF-1.7", size_bytes=10))


def bad_file(n, answer=Answer(status=404, page_load=False)):
    return file_outcome("r1", DownloadFacts(file_name=f"doc{n}.pdf", answer=answer, first_bytes=b"<html>",
                                            size_bytes=10))


LOGIN_FORM = Answer(status=200, page_load=False, password_field=True)
DOWN = Answer(status=503, page_load=False)


def test_d1_no_failures_passes():
    files = [good_file(i) for i in range(8)]
    assert files_failed("r1", files, earlier_failed=0, earlier_files=40, retried=False).passed
    assert files_failed("r1", [], earlier_failed=0, earlier_files=40, retried=False).passed


def test_d1_one_failed_file_is_not_the_portal():
    files = [good_file(i) for i in range(8)] + [bad_file(8)]
    result = files_failed("r1", files, earlier_failed=1, earlier_files=40, retried=True)
    assert effect_of(result) is Effect.note and result.severity is Severity.warn
    assert "Downloads failed for 1 of 9 files; the rest are published" in result.message


def test_d1_the_exact_test_decides_against_the_earlier_failure_share():
    files = [good_file(i) for i in range(7)] + [bad_file(i) for i in range(7, 10)]
    alarm = files_failed("r1", files, earlier_failed=0, earlier_files=200, retried=True)
    assert effect_of(alarm) is Effect.breakage and "Downloads failed for 3 of 10 files" in alarm.message
    usual = files_failed("r1", files, earlier_failed=60, earlier_files=200, retried=True)
    assert effect_of(usual) is Effect.note


def test_d1_failed_files_are_tried_once_more_before_the_alarm_counts():
    files = [bad_file(1), bad_file(2)]
    first = files_failed("r1", files, earlier_failed=0, earlier_files=0, retried=False)
    assert effect_of(first) is Effect.suspect and first.observed["second_look"] == "retry"
    second = files_failed("r1", files, earlier_failed=0, earlier_files=0, retried=True)
    assert effect_of(confirm(first, second)) is Effect.breakage
    recovered = files_failed("r1", [good_file(1), good_file(2)], earlier_failed=0, earlier_files=0, retried=True)
    assert confirm(first, recovered).passed


def test_d1_every_file_failing_always_counts_from_two_files_on():
    assert effect_of(files_failed("r1", [bad_file(1), bad_file(2)], earlier_failed=50, earlier_files=100,
                                  retried=True)) is Effect.breakage
    assert effect_of(files_failed("r1", [bad_file(1)], earlier_failed=0, earlier_files=5,
                                  retried=True)) is Effect.note


@pytest.mark.parametrize("answer, effect", [(LOGIN_FORM, Effect.block), (DOWN, Effect.outage)])
def test_d1_above_the_threshold_the_shared_cause_decides(answer, effect):
    files = [bad_file(i, answer) for i in range(6)]
    result = files_failed("r1", files, earlier_failed=0, earlier_files=40, retried=True)
    assert effect_of(result) is effect and "Downloads failed for 6 of 6 files" in result.message


def test_d1_a_wall_in_front_of_some_documents_does_not_fail_the_portal():
    # The mentor: failed only when most are blocked; otherwise those documents are left out.
    files = [good_file(i) for i in range(14)] + [bad_file(i, LOGIN_FORM) for i in range(14, 20)]
    result = files_failed("r1", files, earlier_failed=0, earlier_files=200, retried=True)
    assert effect_of(result) is Effect.note and "A wall stands in front of 6 of 20 files" in result.message


# -- F1 ----------------------------------------------------------------------

def test_f1_serving_with_no_passing_read_for_three_intervals_is_stale():
    interval = timedelta(minutes=2)
    fresh = stale("r1", state=PortalState.serving, last_good_at=NOW - timedelta(minutes=6), now=NOW,
                  read_interval=interval)
    old = stale("r1", state=PortalState.serving, last_good_at=NOW - timedelta(minutes=42), now=NOW,
                read_interval=interval)
    assert fresh.passed
    assert effect_of(old) is Effect.outage and old.name == "stale"
    assert old.message == "No read has passed since 13:20 UTC. Reads are not completing."


def test_f1_applies_only_to_a_serving_portal_and_reads_its_setting():
    args = dict(last_good_at=NOW - timedelta(hours=5), now=NOW, read_interval=timedelta(minutes=2))
    assert stale("r1", state=PortalState.healing, **args).passed
    assert stale("r1", state=PortalState.failed, **args).passed
    assert stale("r1", state=PortalState.serving, last_good_at=NOW - timedelta(minutes=7), now=NOW,
                 read_interval=timedelta(minutes=2), settings=CheckSettings(stale_after_intervals=4)).passed
    with pytest.raises(ValueError):
        stale("r1", state=PortalState.serving, last_good_at=NOW, now=datetime(2026, 11, 20, 14, 2),
              read_interval=timedelta(minutes=2))
