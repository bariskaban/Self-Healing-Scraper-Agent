"""A status the portal words as closed has no place on a record: what happens to it today, pinned.

`TenderRecord` knows `withdrawn` and `listed` only. Until it has a field for the portal's own
"closed" (docs/SHARED-INTERFACE-REQUESTS.md), such a tender comes out open while it is listed
and its deadline is ahead. The executor keeps the portal's word and says so in a dry run.
Run: pytest tests/recipe/test_closed_status.py
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.extract import ParseContext
from app.models import TenderStatus
from app.recipe.build import field, label
from app.recipe.locate import parse_page
from app.recipe.resolve import fill_record, read_fields
from app.recipe.run import CachedPage, closed_by_the_portal, dry_run, settle
from app.recipe.schema import FieldName as F, NodeKind, ValueType as T
from tests.recipe.examples import STATUS_DE, html_table_portal
from tests.recipe.test_run import BASE, _detail_page, html_pages

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)  # before every deadline on the example pages
STATUS = field(F.status, label("Status"), type=T.status, words=STATUS_DE)
DEADLINE = field(F.submission_deadline, label("Frist"), type=T.datetime)


def fields_of(word: str):
    doc = parse_page(f"<html><body><dl><dt>Status</dt><dd>{word}</dd>"
                     "<dt>Frist</dt><dd>2027-03-12T10:00+01:00</dd></dl></body></html>",
                     NodeKind.html, "https://x.example/", "text/html")
    return read_fields([STATUS, DEADLINE], doc, ParseContext(zone=None, page_url=None, language="de"))


def test_a_tender_the_portal_calls_closed_while_it_lists_it_comes_out_open_with_the_word_kept():
    closed = fields_of("Beendet")
    assert closed[F.status].value == "closed"
    for record in (fill_record("p1", "T1", closed), settle("p1", {"T1": closed}, last_good=None)["T1"]):
        assert (record.withdrawn, record.listed) == (False, True)
        assert record.effective_status(NOW) is TenderStatus.open  # the portal says closed: the gap
        assert record.raw["status"] == "Beendet"                  # its word is not lost
    assert closed_by_the_portal({"T1": closed, "T2": fields_of("Laufend"), "T3": fields_of("Aufgehoben")}) == ["T1"]

    # The two words a record does have a place for are unchanged.
    assert fill_record("p1", "T3", fields_of("Aufgehoben")).effective_status(NOW) is TenderStatus.withdrawn
    assert fill_record("p1", "T2", fields_of("Laufend")).effective_status(NOW) is TenderStatus.open


def test_a_dry_run_says_that_a_closed_status_is_not_delivered_and_still_passes():
    pages = html_pages()
    pages[3] = CachedPage(f"{BASE}/ausschreibungen/2026-0002", _detail_page(2, status="Beendet"))
    result = dry_run(html_table_portal(), pages, url=BASE, timezone="Europe/Berlin")
    assert result.ok and result.problems == []  # a note, not a reason to refuse the recipe
    (note,) = result.notes
    assert "1 listed tender(s) as closed" in note and "2026-0002" in note and "delivered as open" in note
    record = next(r for r in result.records if r.tender_id == "2026-0002")
    assert record.raw["status"] == "Beendet" and record.effective_status(NOW) is TenderStatus.open

    assert dry_run(html_table_portal(), html_pages(), url=BASE, timezone="Europe/Berlin").notes == []
