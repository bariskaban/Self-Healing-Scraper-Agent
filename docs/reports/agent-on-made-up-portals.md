# The learner and the repairer on eight made-up portals

Run on 20 Nov 2026, about 23:00 UTC, on the development key. Model `gpt-6.2-sol`, reasoning `medium`, learn prompt 3, `main` at `ed03b9e` plus `bench/variants.py`. One run per portal: these are single runs, not averages.

## What was run

`bench/variants.py` holds eight portals that do not exist. Each shows the mock portal's seed tenders the way a real portal family shows its own, so the truth is exact. They answer inside the process; no request went to any portal. `python -m bench.run_variants` runs the learner once per portal, then runs the learned recipe over every page of the portal (no model) and compares each tender with the truth. With `--repair-from` it switches each portal to its changed face (every class, id and `data-*` hook renamed; the JSON API moved to `/api/v3` with its keys in snake_case), confirms that the old recipe now reads nothing, and runs one repair.

## Learn

| Portal | Trait | Result | Tenders | Fields wrong or missing | Documents | Calls | Cost | Cached input | Seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `json_api` | app shell; JSON API named in a script | learned | 45 of 45 | none | 45 of 45 | 10 | $0.138 | 81% | 58 |
| `de_netserver` | German; rows with `data-oid`, no link | learned | 30 of 30 | none (see note) | 30 of 30 | 11 | $0.160 | 81% | 74 |
| `pl_offset` | Polish; offset paging; numeric id | learned | 45 of 45 | none | 45 of 45 | 6 | $0.108 | 74% | 45 |
| `fr_cards` | French; dates with month names | learned | 45 of 45 | none | 45 of 45 | 10 | $0.148 | 81% | 68 |
| `it_detail` | Italian; deadline only on the tender page | learned | 45 of 45 | none | 45 of 45 | 6 | $0.111 | 74% | 46 |
| `docs_page` | one page, no total; files on their own page | learned | 24 of 24 | none | 24 of 24 | 9 | $0.133 | 80% | 55 |
| `login_wall` | every page leads to a login | gave up, as it should | | | | 2 | $0.042 | 46% | 4 |
| `empty` | the list says there are no tenders | gave up | | | | 9 | $0.089 | 81% | 28 |

Fields compared: address, title, buyer, publication date, deadline, reference number, CPV codes, procedure type, contract nature, and the number of documents. Total: $0.93.

Note on `de_netserver`: the run counted all 30 addresses as wrong. The recipe built the address with `&Category=InvitationToTender`, as the row's own attributes say, and the truth in the first version of the variant left that parameter out. The portal serves both. The truth was corrected afterwards; the repair run below used the corrected one.

## Repair, after the redesign

Before each repair the old recipe matched 0 tenders on the changed portal.

| Portal | Result | Tenders | Fields wrong or missing | Documents | Calls | Cost | Seconds |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `json_api` | repaired | 45 of 45 | none | 45 of 45 | 8 | $0.097 | 37 |
| `de_netserver` | repaired | 30 of 30 | none | 30 of 30 | 7 | $0.111 | 46 |
| `pl_offset` | repaired | 45 of 45 | none | 45 of 45 | 5 | $0.086 | 31 |
| `fr_cards` | repaired | 45 of 45 | none | 45 of 45 | 8 | $0.120 | 53 |
| `it_detail` | repaired | 45 of 45 | none | 45 of 45 | 6 | $0.103 | 40 |
| `docs_page` | repaired | 24 of 24 | none | 24 of 24 | 6 | $0.094 | 34 |

Total: $0.61. Every repair kept the tenders' ids.

## What this does and does not show

- The learner handled a JSON API behind an app shell, rows without links, three ways of paging, four languages and month-name dates, and a documents page of its own, first time, at $0.11 to $0.16 a portal.
- These portals are small and clean: at most 45 tenders, consistent markup, no cookies, no forms to submit, no JavaScript-only content, pages of a few kilobytes. The two real portals measured so far cost $0.72 and $0.74 to learn, five times as much. Read these numbers as "the mechanism works across shapes", not as the cost of a real portal.
- The redesign is one kind of change (renamed hooks and keys). Labels, addresses and the order of things stayed. A portal that moves to other addresses or other label words was not tried here; the mock portal's `layout_changed` covers part of that.
- The repairs ran through `repair()` directly. The reader's trial read and its checks were not part of this run (they were in the live run on the mock portal).
- `empty` took 9 calls and $0.09 to give up; a portal with no tenders today cannot be learned at all, and comes out `failed` rather than "serving, 0 tenders".
- Not tried: a captcha page, a portal that is slow or rate limited, a list of thousands of tenders, documents behind a form or in a ZIP per tender, ids that appear nowhere but in a script.
