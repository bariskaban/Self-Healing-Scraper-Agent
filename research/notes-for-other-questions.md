# Notes for other owners' questions (Q4, Q10)

From Danil's research run, 20 Nov 2026. Each point was fact-checked; numbers use the papers' own wording.

## Q4 page views (David)

- **Give the learner trimmed HTML, not an accessibility tree.** "Read More, Think More: Revisiting Observation Reduction for Web Agents" (arXiv:2604.01535, Apr 2026) found that HTML helps higher-capability models, with gains of up to 17.5 percentage points over a compact accessibility tree.
  - Keep `id`, `class`, `href` and `data-*` in the trim, since the recipe's locators are written against them.
  - The cheap spot check can use plain text.
- Measured token counts on real portal pages are coming in a separate note. They will show raw vs trimmed HTML vs markdown vs accessibility tree vs text.

## Q10 failure rules (Goktug)

- **Fake-200 download guard.**
  - Check every downloaded file's Content-Type and magic bytes: `%PDF`; `PK\x03\x04` for ZIP, DOCX and XLSX; `D0 CF 11 E0` for old Office files.
  - Also check for an HTML login form.
  - A login page served with HTTP 200 must never be stored as a tender document. It is a block, and it goes to `failed` with the reason.
- **Structure fingerprint that ignores the tender count.**
  - Hash the sorted, unique set of tag+class skeleton paths, ignoring text, row indices and numeric ids.
  - For JSON APIs, hash the sorted set of key paths.
  - A week with more or fewer tenders then never looks like drift.
- **Why repair acceptance must stay strict.** In "Trustworthy Runtime Error Healing" (arXiv:2609.39086, 30 Sep 2026), automatic healing "proceeded" far more often than it was correct, in every setting tested: 29.43% proceed vs 16.98% correct without their guard. That study heals Python runtime errors, not scrapers, so treat it as a warning, not as evidence about portals. It supports DESIGN.md's rule that a repaired recipe is accepted only if it reproduces the last good records.

## Do not cite (failed the fact-check)

- EAGL as a multi-locator method: it generates a single locator.
- "+13.3% to +20.9%" for HTML vs accessibility tree: not in either paper.
- "Stripping id/class hurt": not found.

## Sources

- https://arxiv.org/html/2604.01535
- https://arxiv.org/abs/2609.39086
