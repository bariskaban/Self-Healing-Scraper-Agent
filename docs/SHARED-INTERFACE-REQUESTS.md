# Requests for the shared interfaces

For the people who approve changes to `app/models.py` and `app/schema.sql`. Each entry is a field the code of stream A needs and does not have, taken from the code as it is on 20 Nov 2026. Nothing here is changed yet: each is a pull request of its own (`CLAUDE.md`). Where this file and the code disagree, the code is right.

One thing holds for every entry: `app/schema.sql` is run with `CREATE TABLE IF NOT EXISTS`, and `app/db.py` has no migration step. A new column reaches only a database made after the change. A `DATA_DIR` that already holds a database needs an `ALTER TABLE ... ADD COLUMN` (or, for a changed primary key, a rebuilt table), or to be started empty.

## 1. The facts of an incident (`Incident` in `app/reader.py`)

**Today.** The loop keeps one `Incident` per portal in memory (`ReadLoop._incidents`). The reader and the loop read and write it; `decide` in `app/state.py` gets it as `ReadFacts`. A restart empties it.

**Proposed.** A record `PortalIncident` in `app/models.py` and a table `portal_incidents`, one row per portal (`portal_id TEXT PRIMARY KEY REFERENCES portals(id) ON DELETE CASCADE`), with these fields. The names are the ones the code uses.

| Field | Type and default | What it is | Written by | Read by |
| --- | --- | --- | --- | --- |
| `outage_since` | `datetime \| None = None` | when the portal stopped answering | `_Read._apply` | `ReadFacts.outage_since`: the 60-minute rule that turns `healing` into `failed` |
| `outage_retries` | `int = 0` | tries made in this outage | `ReadLoop._plan_next` | `next_outage_retry` (the ladder 1, 2, 4, 8, 15, 30 minutes) |
| `broken_since` | `datetime \| None = None` | when a breakage was first confirmed | `_Read._apply` | `ReadFacts.broken_since` |
| `repair_attempts` | `int = 0` | repairs started in this incident | `_Read._repair` | `ReadFacts.repair_attempts_used`: the cap on repairs |
| `repairs_tried` | `list[str] = []` (JSON) | one line per repair that did not work | `_Read._repair` | `ReadFacts.repairs_tried`: the reason shown for `failed` |
| `repairs_today` | `int = 0` | repairs started on `repairs_day` | `_Read._repair` | `ReadFacts.repairs_today`: the cap per day |
| `repairs_day` | `date \| None = None` (the code holds the ISO text) | the UTC day `repairs_today` counts | `_Read._repair` | `_Read._decide` |
| `given_up_structures` | `list[str] = []` (JSON; a set in the code) | structure fingerprints a repair was given up on | `_Read._apply` | `ReadFacts.structure_given_up`: no new repair while the page looks the same |
| `failed_at` | `datetime \| None = None` | when the portal became `failed` | `_Read._apply`, `ReadLoop._plan_next` | `next_failed_check` (5 min, 15 min, 1 h, then every 6 h) |
| `failed_checks` | `int = 0` | scheduled checks made since `failed_at` | `ReadLoop._plan_next` | `next_failed_check` |
| `last_check_at` | `datetime \| None = None` | when the portal was last read | `ReadLoop._plan_next` | `may_check_on_refresh`: a failed portal is checked at most once a minute |
| `next_try_at` | `datetime \| None = None` | when the next try is planned while not `serving` | `ReadLoop._plan_next` | `ReadFacts.next_try_at`: the time named in the reason |
| `last_full_started_at` | `datetime \| None = None` | start of the last full read that passed | `_Read._apply` | `next_read`: the interval is counted from it |
| `list_seconds` | `float = 0.0` | how long the list took in that read | `_Read._apply` | `read_plan`: the read interval |
| `list_pages` | `int = 1` | how many pages the list had | `_Read._apply` | `read_plan`: whether the first page is read alone |
| `newest_first` | `bool = False` | the list is sorted newest first | `_Read._apply` | `read_plan` |

The last three are also in the active recipe (`Expectations.list_read_seconds`, `Expectations.list_pages`, `ListFacts.newest_first`), so they could be read from there instead of stored twice.

**What breaks without it.** After a restart every count starts again. A portal that has not answered for 50 minutes gets a fresh 60 minutes before it reads `failed`. The repair caps (per incident and per day) are forgotten, so a restart buys more model calls than the budget allows. A structure that was given up on is repaired again. A `failed` portal is checked again after 5 minutes instead of waiting its 6 hours.

Not a schema change, but related: `Portal.next_read_at` and `Portal.consecutive_failures` exist and the loop writes neither. The next read is kept in `ReadLoop._due`; the dashboard reads it from the loop and falls back to the empty column.

## 2. The row hash of a tender

**Today.** `plan_incremental_read` compares what the list shows of a tender with what it showed last time. The reader keeps that hash in `TenderRecord.raw["_row_hash"]` (`ROW_HASH` in `app/reader.py`: written in `_Read._records`, read in `_Read._read_and_decide`).

**Proposed.** `TenderRecord.row_hash: str = ""` and `tenders.row_hash TEXT NOT NULL DEFAULT ''`. Empty means "the tender's own page was not read whole", as today.

**What breaks without it.** Nothing fails. But `raw` is described as "values as extracted before normalization", keyed by field name, and it now carries a key that is no field. Code that walks `raw` must know to skip it, and the hash is stored inside every tender's JSON text.

## 3. A portal's own "closed"

**Today.** A recipe's status field maps the portal's words to `open`, `closed` or `withdrawn` (`ValueType.status`). `fill_record` in `app/recipe/resolve.py` stores `withdrawn` and nothing else. `TenderRecord.effective_status` says `closed` only when the tender left the list or its deadline passed. So a tender the portal words as closed ("Beendet") while it still lists it, with its deadline ahead, is delivered as `open`. The portal's word is kept in `raw["status"]`, and `dry_run` adds a note that names such tenders (`DryRun.notes`, `closed_by_the_portal`). `tests/recipe/test_closed_status.py` pins this.

**Proposed.** `TenderRecord.closed_by_portal: bool = Field(False, description="Portal marks it closed while it is still listed")` and `tenders.closed_by_portal INTEGER NOT NULL DEFAULT 0`. In `app/models.py`: `effective_status` returns `closed` when it is set (after the test for `withdrawn`), and `compute_hash` takes it in, so that `lastChangedAt` moves when a portal closes a tender. Then, in our code: `fill_record` sets it from `value(FieldName.status) == "closed"`, and `_last_value` in `app/recipe/resolve.py` returns `"closed"` for it, so a lone status locator can be compared with the last good read.

**What breaks without it.** The delivered `status` is wrong for exactly these tenders, on every portal that closes a tender before it takes it off the list.

## 4. One check row per file (`run_checks`)

**Today.** `run_checks` has the primary key `(run_id, name)` and `Database.add_checks` replaces a row with the same key. Every download is judged by `file_outcome`, which gives a row named `file_outcome`. The reader collects these rows in a list, hands them to `files_failed`, and stores only that one summary row: storing them all would leave the last file's row.

**Proposed.** `CheckResult.subject: str = Field("", description="What the check looked at when a run has several of one name: a file's address")`, `run_checks.subject TEXT NOT NULL DEFAULT ''`, and `PRIMARY KEY (run_id, name, subject)`. `Database.add_checks` upserts on the three columns and `_check` reads the new one. `file_outcome` (`app/checks`) and the row the reader builds for a download that did not arrive (`_Read._one_document`) set `subject` to the file's address. `_Read._save_run` then stores the file rows, and `_Read._apply` can count the failed files of the last good read.

**What breaks without it.** `files_failed` is called with `earlier_failed=0, earlier_files=0` on every read (`_Read._apply`), because no earlier read left its file rows. Its comparison with earlier reads has nothing to compare with, so only "every file failed" can raise the alarm. And the timeline cannot say which file failed and why; it shows one example in the summary row.

## 5. A skip reason for an unreadable ZIP entry (`SkipReason`)

**Today.** `app/docs/archive.py` marks an entry of a ZIP it cannot unpack (encrypted, damaged, a compression method Python does not know) as `SkipReason.not_a_file`, whose meaning is "the link led to an HTML page, not a document".

**Proposed.** `SkipReason.unreadable = "unreadable"`, with the comment "an archive entry that cannot be unpacked: encrypted or damaged". `files.skipped` is plain text with no `CHECK`, so `app/schema.sql` needs no change. `app/docs/archive.py` uses it at the one place; the reader's count of blocked documents (`login_required`, `captcha`) is not touched.

**What breaks without it.** Nothing fails, and the public API does not show skip reasons. The record says something untrue: an operator who reads `not_a_file` looks for a page behind the link, when the file is there and one entry in it is encrypted.

## Not a schema change: fixed in code

`Recipe.parent_version` exists and `_Read._store_recipe` did not set it, so the dashboard could not show a recipe change after a repair. It now sets it to the version that was active (`tests/test_reader_recipes.py`). The same function now stores one software name in `Recipe.fingerprint` and `Portal.fingerprint`: the recipe's `family` when it names one.
