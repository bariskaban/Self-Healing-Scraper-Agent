# Q3. Explore or map first?

Owner: teammate who took Q1, Q3 and Q4 · Status: **open, no answer in the repo yet**

## Question

Should the learning agent explore from the entry URL toward the tender list, goal-directed? Or should it first map the site (sitemap.xml, link crawl, grouping pages by type) and use the LLM only to label page types?

Constraint: at 1 request/s we get at most 3,600 pages an hour, and attach should finish in minutes.

Also check: how many procurement portals expose structured sources we should probe first. Examples: sitemaps, RSS/Atom, OCDS (Open Contracting Data Standard) feeds, eForms/TED data, or a JSON API visible in network traffic.

Deliverable: the recommended strategy, the requests attach needs under each option, and an ordered checklist of structured sources to probe before crawling HTML.

## Answer

None yet. When it is written, it follows the answer standard in [README.md](README.md).

## Inputs from answered questions

- **Q12:** probing for an API, a feed or an all-documents ZIP is worth a few dozen requests at attach. On the one portal measured, the bulk source cut a 1,000-tender attach from 13,050 requests to 2,010. See [q12-large-portals.md](q12-large-portals.md).
- **Q10:** the learner needs one extra step, a search that returns nothing, to record what the portal's empty list looks like. See [q10-failure-rules.md](q10-failure-rules.md).
- **Measured today:** TenderNed's public API caps its page size at 100 and says so in its error message; Poland's notice API allows 30 requests a minute.
