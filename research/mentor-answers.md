# Answers from the mentor

20 Nov 2026, in person with a Patterno mentor. Noted from a rough transcript of the conversation, so the wording is ours and the quotes are approximate. Where the answer was clear it is marked **clear**; where we are reading between the lines it is marked **our reading**.

The mentor speaks for the organisers, so these answers rank with the track description: above the research files and above `DESIGN.md`.

## Answered

| # | Question | Answer | How sure | What we do |
| --- | --- | --- | --- | --- |
| 1 | How long does the harness wait before it scores a portal? How many tenders and documents do the test portals hold? | "We can wait. 20, 30 minutes." A few minutes per website is "definitely okay". The limit is flexible and depends on how much time they have to test. The size of the test portals was not disclosed. | clear | The 10-minute rule for documents stays. A new setting, the attach time limit, defaults to 20 minutes. |
| 1b | All or nothing at the time limit? | They do not want a binary result: with a limit, "we would want to see some kind of results up until then". A variable to set the limit, shown on the dashboard, was welcomed. | clear | At the attach time limit, publish the records validated so far and say how many are still to come. |
| 1c | Results we measured ourselves | A report of our own test runs is welcome, also for portals that take longer than they can wait, and for our self-healing runs on simulated changes. | our reading | A test report goes into the hand-in. |
| 2 | Is a portal `serving` when records are delivered and documents are still downloading? | Yes. "If you have mapped out the documents and they are actually loading, I'd say that's actually okay." | clear | `serving` at the records gate. Documents we know of are listed while their bytes load. |
| 3 | A portal that is down, not changed: `healing` or `failed`? | `healing`, because it may just come back. `failed` is for portals that need a person, such as a login. A portal down "for more than some amount" may also become `failed`. No number was given. | clear | As designed: `healing` at once, `failed` after 60 minutes (a setting), and we keep checking. |
| 3b | May we add a state or a field for an outage? | Yes. The API is an interface: adding to it is fine, as long as the given schema is kept. | clear | Keep the four states. Add a field `cause` to a portal's answer (outage, block, breakage). |
| 4 | How do you change a private portal? | Layout, API and paths can all change. The domain will not: "that would be unreasonable to consider it the same portal". They also expect us to simulate changes ourselves and report how we did. | clear | Identity must survive a change of paths, not of domain. The mock portal's results go into the test report. |
| 5 | Does "1 request per second" count request starts, or requests in flight? | "I think request starts." | clear | A long download may still run when the next request starts. |
| 6 | May we read a portal with the headless browser when it refuses a plain HTTP client? | Yes. | clear | As designed (Q10, rule O1). |
| 7 | Do we obey robots.txt? | By default, yes: "we want to stay legal", and they would not bypass a captcha either. For testing, a flag to ignore robots.txt would be welcome, ideally on the dashboard. | clear | Obey by default. A setting, off by default, ignores it for a test. Captchas are never bypassed. |
| 8 | How much disk does the container have? | Our plan (about 20 GB per 1,000 tenders) "sounds reasonable". They run on virtual machines and can scale. | clear | As designed. |
| 9 | Only some tenders' documents need a login: is the portal `failed`? | Our default is reasonable. | clear | As designed: `failed` only when most are blocked; otherwise those tenders' documents are null. |
| 12 | A deadline shown as a date with no time | Our choice. End of day is "technically" right; null is also fine. | clear | End of day in the portal's zone, as a setting. A missing deadline would also leave us unable to tell `open` from `closed`. |
| 14 | Can an aggregator such as TED be a test portal? | No. "TED exactly will not be a test portal", and aggregators in general are unlikely. TED is fine for finding portals. Aggregators are late, and Patterno wants to be first. | clear | No work on aggregators. Being first is one more reason for short read intervals (Q13). |
| 15 | Where will the real test portals come from? | "Probably they won't be German": Patterno's German coverage is already good. Anything else is possible; Poland was mentioned. | our reading | The test set leads with Italian, Polish and French platforms. |

## Not answered

Our defaults stand for these.

- Whether tender ids stay the same when a private portal changes.
- Whether a page's own sub-requests count toward the limit, and whether the limit is per portal or per host.
- Whether they call refresh after restoring a portal, or wait for us to notice.
- Whether a ZIP's entries are listed in place of the ZIP or beside it.
- Whether `tenderCount` counts every tender or only open ones.
- Which is `id` when a portal shows both its own id and the buyer's reference number.
- How many portals the harness adds at once, and how much memory the container has.

## Also said

From the rest of the conversation. Not answers to our questions, but they bear on what we build and how we present it.

- **What weighs most is a working product at the end.** Twelve teams took this track. The mentor asked teams on other tracks why they had not: most found it too hard for the time available.
- **What Patterno tried before, and what did not work.**
  - A Claude Code skill that does the reading. It "seems to work at first" but is "not really reliable in the end". With current models and a lot of compute it might work.
  - Going around captchas. They tried, found it was not legal, and stopped. They are careful on legal matters in general.

What we take from it:

1. **Finish end to end before widening.** A system that attaches one portal, notices a change and repairs it, running in the container, beats a wider one that does not run. The build order in `DESIGN.md` already says so.
2. **Our argument is reliability.** Their own attempt failed on reliability, not on capability. Ours runs a recipe on a deterministic engine and checks every read, so an agent is not asked to get it right each time. That belongs in the pitch and the video.
3. **Nothing that looks like getting around a captcha**, in the product or in the demo.

## What changes because of these answers

1. **A partial result at the time limit.** Before, a portal that had not reached the records gate delivered nothing. Now, when the attach time limit passes first, the records validated so far are published and the reason says how many are still to come. (Q12)
2. **Documents are listed while they load.** Before, `documents` was null until the bytes were in. Now a known document is listed with its name and announced size, and its `sha256` and `path` are null until it is fetched. `documents` itself is null only when not even the list is known. (Q12)
3. **A `cause` field on a portal.** An outage, a block and a breakage can be told apart without reading the reason sentence. (Q10)
4. **robots.txt is obeyed, with a test switch.** A portal that forbids everything is `failed` with that reason unless the switch is on. (Q10, Q3)
5. **A date-only deadline is end of day**, not null. (Q2)
6. **The test set leads with non-German portals.** (Q8)
7. **A test report in the hand-in**: attach results on the test portals and the mock portal's switch results. (Q8)
8. **Two settings on the dashboard**: the attach time limit and the robots.txt switch. Both are also environment variables.
