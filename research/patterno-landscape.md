# What Patterno's own portal list tells us

Researched 20 Nov 2026. Not one of the numbered questions: a measurement that several of them need.

How each claim is known is marked: **measured** (we counted it today), **read** (Patterno's page says it), **ours** (our own reasoning).

## Why this matters

The judges test us on real portals as well as private ones, and Patterno publishes which portals it covers. So their public coverage pages are the best available picture of what our system will meet, and of what "many more portals" means for the Approach criterion.

## What we did

Read Patterno's coverage index and its 29 country pages, one request per second, and counted. `research/tools/patterno_coverage.py` repeats it and writes the counts to `research/sources/patterno-coverage.json`. We keep counts, not their list of addresses.

For 28 countries the page lists every portal address. For Germany it shows the top 100 portals by market share, each tagged with its software type.

## Findings

### Four countries hold 83% of the portals

Patterno states 4,657 portals in 29 countries (**read**).

| Country | Portals | Share |
| --- | --- | --- |
| Italy | 1,318 | 28% |
| Poland | 1,090 | 23% |
| France | 1,021 | 22% |
| Germany | 441 | 9% |
| Czechia | 204 | 4% |
| Austria | 129 | 3% |
| Spain | 111 | 2% |
| 22 other countries | 343 | 7% |

Our research so far looked mostly at Germany, the Netherlands, France and Spain. **Italy and Poland together are half of the list.**

### Ten platforms hold half of all portal addresses

Grouping the 4,286 listed addresses by the platform domain they sit on (**measured**):

| Platform domain | Country | Portal addresses |
| --- | --- | --- |
| `ezamawiajacy.pl` | Poland | 595 |
| `e-marchespublics.com` | France | 573 |
| `logintrade.net` | Poland | 203 |
| `acquistitelematici.it` | Italy | 184 |
| `tuttogare.it` | Italy | 162 |
| `maggiolicloud.it` | Italy | 126 |
| `traspare.com` | Italy | 106 |
| `eb2b.com.pl` | Poland | 91 |
| `achatpublic.com` | France | 58 |
| `vemap.com` | Austria | 52 |

- The 5 largest platforms hold 40% of all addresses; the 10 largest hold 50%; the 50 largest hold 62%.
- 1,229 platforms have a single address. That long tail is 29% of all addresses, and each needs its own learning.
- Poland is the most concentrated (three platforms hold over 80% of its portals); Spain, Czechia, Greece and Finland are the least.

### Germany, by software

Patterno says the top 10 German portals cover 60% of that market (**read**). Summing its market shares by the software type it tags (**measured**, over the 99 ranked portals we could read):

| Software type, as Patterno names it | Share of German tenders |
| --- | --- |
| `cosinex-vmpsatellite` | 23% |
| `netserver` | 11% |
| `healy-hudson` | 11% |
| `evergabe-online` | 8% |
| `evergabe-de` | 8% |
| `subreport` | 8% |
| `itwo-tender` | 7% |
| no type given | 9% |

Patterno describes `subreport` as a Google Web Toolkit single-page app, and `netserver` as a generic portal "used by many German customers" (**read**).

## What it means, by question

- **Q8 test set.** The set should follow the list: at least one portal each on `ezamawiajacy.pl`, `e-marchespublics.com`, `logintrade.net`, `acquistitelematici.it` and `tuttogare.it`, beside the German and Dutch ones already chosen. The organisers asked for 4 countries and 3 software packages; Italy and Poland are where most of their portals are.
- **Q11 reuse.** This is the number the Approach argument needs: a recipe per platform for the ten largest covers up to half of Patterno's portals, and the address itself is the fingerprint (`<buyer>.tuttogare.it`). It is "up to" because one platform can run different versions for different buyers; the canary read decides.
- **Q2 locators.** Label lists should start with Italian and Polish, not end with them.
- **Q6 language.** Polish date parsing is not a side case: 1,090 portals. The Python date parser covers Polish; the main Node one does not.
- **Q12 large portals.** Most of these addresses are one buyer's own space on a shared platform, so most portals will list few tenders (**ours**: an inference from the address pattern, not a count). The fast regime in Q12 and Q13, a list read every 2 minutes and every detail page re-read within minutes, is the common case; the 1,000-tender portal is the exception.
- **Q10 failure rules.** Small lists are the norm, which is the case percentage thresholds handle worst.

## Limits

- Grouping by platform domain undercounts software families, because the same software also runs under buyers' own domains (cosinex in Germany is the clear case), and it cannot tell versions apart.
- Market shares exist only for Germany, and they are Patterno's own figures.
- A portal count is not a tender count. The list does not say how many tenders each portal holds.
- One reading, on one day.

## Source

- Patterno, portal coverage: https://www.patterno.de/de/vergabe-portale/coverage and the country pages under it (read 20 Nov 2026)
