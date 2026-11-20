# Q14. Retrying failed portals

Owner: Goktug (leftover) · Researched 20 Nov 2026 · Status: **answered**. This replaces the answer that was proposed without research.

How each claim is known is marked: **measured**, **read**, **search**, **ours** (see [README.md](README.md)).

## Question

What do we do with a portal that is `failed`, so that model cost stays capped and a portal that comes back is served again?

The proposed answer was: every 6 hours, check each failed portal without calling the model. If it is still blocked or unchanged, it stays failed. If the portal now responds differently, run one repair attempt.

## Decision

**Keep the two ideas in the proposal: checking costs no model call, and a repair is tried once when the portal has changed. Change when we check.**

- **Every refresh call on a failed portal checks it at once**, at most once a minute.
- **On our own we check 5 minutes, 15 minutes and 1 hour after it failed, then every 6 hours**, each time shifted by up to 20% at random. A portal blocked by a login or a bot wall is checked every 6 hours from the start.
- **Before a portal that stopped answering is called `failed`, we retry it after 1, 2, 4, 8, 15 and 30 minutes** while it reads `healing`. That is the first hour (Q10).

What a check does, with no model call:

| What the check finds | What happens |
| --- | --- |
| The old recipe's read passes every check | `serving` |
| Still blocked, or still not answering | Stays `failed`; the reason gets the time of this check |
| The portal answers, the read fails, and the page's structure is the one we already gave up on | Stays `failed` |
| The portal answers, the read fails, and the page's structure is new | **One** repair attempt. At most one per new structure, and three per portal per day. |

We choose this for three reasons:

1. **Six hours alone misses the case the judges are most likely to try**: they break a private portal, see `failed`, put it back and watch. They call refresh every few minutes; a check on refresh recovers the portal while they look, and costs no tokens.
2. **Portals that come back mostly come back soon.** Short outages and maintenance end in minutes to an hour, so the early checks are close together and the later ones far apart.
3. **Model cost is capped by what we see, not by the clock.** A repair needs a page we have not already failed on. Refresh calls cannot buy repairs.

## The alternatives, and why they lose here

| Alternative | Why it loses |
| --- | --- |
| Every 6 hours, fixed (the proposal) | A portal restored five minutes after failing reads `failed` for up to six hours, unless someone refreshes, and the proposal does not say a refresh checks. |
| Every hour, fixed (draft 2) | Better, but still an hour late for a short outage, and 24 checks a day for ever on a portal behind a login. |
| Stay failed until a person acts | "A person is needed" describes the state, not a promise to wait. The brief asks us to get back to correct delivery on our own. |
| Run a repair on every check | Every refresh on an unrepairable portal would spend tokens. This is the drain draft 2 already ruled out. |
| Keep retrying fast for ever | Impolite to a portal that is down, and pointless against a login wall. Every source below says to back off. |

## Evidence

- **Randomised, growing pauses are the standard.** Google's SRE book: "Always use randomized exponential backoff when scheduling retries" and "Limit retries per request. Don't retry a given request indefinitely" (**read**). AWS: "the no-jitter exponential backoff approach is the clear loser" (**read**).
- **A crawler that meets errors slows down and comes back.** Google: "5xx and 429 server errors prompt Google's crawlers to temporarily slow down", and "Once the server starts responding with a 2xx status code, Google gradually increases the crawl rate" (**read**). It states no fixed time at which it gives up; the nearest it comes is "multiple days".
- **A server can say when to return.** RFC 9110: with a 503, `Retry-After` "indicates how long the service is expected to be unavailable" (**read**). When it is sent, the next check is at that time, up to an hour.
- **What libraries ship:** Scrapy retries twice with no pause; Celery three times, three minutes apart, with a 10-minute cap on its growing pause (**read**: their source). These are for single requests inside a job, not for a portal that is down for hours.
- **Kubernetes** restarts a crashing container after 10 seconds, doubling to a 5-minute cap (**search** only).
- **A check is cheap:** one to three requests, against 86,400 a day allowed per portal (**ours**).

## Numbers that are our own choice

No source gives the steps themselves. The shape, close together first and then far apart with a random shift, is sourced; these values are **ours**:

- 5 minutes, 15 minutes, 1 hour, then 6 hours for a failed portal; 20% random shift.
- 1, 2, 4, 8, 15, 30 minutes while `healing` after an outage.
- One check a minute at most on refresh; three repairs a day at most.

## What would change the decision

- If the mentors say they will not call refresh after restoring a portal, tighten the later steps: every hour instead of every six.
- If a long outage should read `healing` and not `failed` (Q10's question for the mentors), only the label moves; the checks stay.

## For the mentors

After you restore a portal that we reported `failed`, do you call refresh, or wait for us to notice? Not answered on 20 Nov ([mentor-answers.md](mentor-answers.md)); our default stands. The mentor did confirm that an outage reads `healing` and that `failed` is for portals that need a person.

## Prototype first (about 1.5 hours)

On the mock portal: answer 503 for 3 minutes, then recover; show a login wall, then remove it; change the layout twice in a row. Check the state, the reason text, and that the number of model calls is 0, 0 and 2.

## Effect on other questions

- **Q7 schemas:** a portal stores the structure fingerprint it gave up on, the time of the next check, and today's repair count.
- **Q8 benchmark:** the three mock sequences above.
- **Q10:** the outage steps are its "Outage" row.
- **DESIGN.md:** replace "read again on refresh and once an hour".

## Sources

Read on 20 Nov 2026.

- Google SRE book, "Addressing Cascading Failures": https://sre.google/sre-book/addressing-cascading-failures/
- AWS Architecture Blog, "Exponential Backoff And Jitter": https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
- Google, how HTTP status codes affect its crawlers: https://developers.google.com/crawling/docs/troubleshooting/http-status-codes ; reducing the crawl rate: https://developers.google.com/crawling/docs/crawlers-fetchers/reduce-crawl-rate
- RFC 9110, sections 10.2.3 and 15.6.4: https://www.rfc-editor.org/rfc/rfc9110.txt
- Scrapy 2.20.0 `scrapy/settings/default_settings.py`; Celery 5.7.0 `celery/app/task.py` (package sources)
- Search only: Kubernetes pod lifecycle, https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
