# Q7. Schemas for every internal record

Owner: teammate who took Q5, Q7 and Q8 · Status: **open, no answer in the repo yet**

## Question

Draft the schemas for every internal record, so workstreams can build in parallel.

Records
- Recipe (depends on Q1).
- Portal: state, reason, software fingerprint, current recipe version.
- Run: kind, times, result, check results, tokens and cost, errors.
- Tender: the output contract, plus an internal content hash and where it came from.
- File.
- Agent step trace (what the dashboard shows as "what the system did").
- Portal snapshot handed to a repair: pages and network log.
- Validator check result.

Also check OCDS and eForms field definitions, so our tender record maps cleanly onto them.

Deliverable: Pydantic models with one-line field descriptions, and the SQLite tables they map to.

## Answer

None yet. When it is written, it follows the answer standard in [README.md](README.md).

## Inputs from answered questions

- **Q10:** a check result is the rule id, the verdict (pass, suspect, cleared, failed), the counts and the evidence. A run stores its check results and the reason sentence. A portal stores its own request-rate limit. See [q10-failure-rules.md](q10-failure-rules.md).
- **Q12:** a tender needs read bookkeeping (last seen in the list, last detail read, hash of its list row), and a document entry must be able to exist before its bytes do. See [q12-large-portals.md](q12-large-portals.md).
- **Q14:** a failed portal stores the structure fingerprint it gave up on, the time of the next check and today's repair count. See [q14-failed-retry.md](q14-failed-retry.md).
- **Q6:** Pydantic models can serve the API contract, the recipe and the model's strict output schema at once.
