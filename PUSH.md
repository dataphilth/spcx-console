# Getting it live

Twenty minutes, in order. Do not skip step 2 — everything downstream assumes the
sources actually resolve, and the two most likely failures are both silent.

---

## 1. Local setup

```bash
cd spcx-console
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

export SPCX_CONTACT="you@example.com"   # the SEC blocks anonymous callers
pytest -q                               # expect 45 passed
```

---

## 2. Verify the sources before trusting anything

```bash
python scripts/verify_sources.py
```

This is read-only and writes nothing. It probes every endpoint and reports what
actually came back. Three things it is specifically looking for:

**The XBRL tags are guesses.** Tag choice varies by filer and by whichever
software prepared the filing. If `verify_sources.py` reports
`tag revenue_quarterly WARN`, it prints the tags this filer really uses — paste
the correct one into `config/metrics.yaml` and re-run. This is the most likely
reason a first run comes back empty, and the failure is silent otherwise: the
collector records a gap and the criterion sits at `unknown` looking calm.

**The stooq symbol may not exist.** stooq returns a bare error string rather than
an HTTP error for unknown symbols, so a naive collector would parse garbage. The
verifier checks for a real CSV header. If `spcx.us` isn't listed, swap the price
collector — the rest of the system does not depend on price for any criterion,
by design.

**The CelesTrak Kuiper group may be renamed.** Amazon rebranded Kuiper to Leo. If
the group returns nothing, `S10` will sit at `unknown` until the group name in
`spcx/collectors/constellation.py` is corrected.

Note the launch verifier deliberately runs three probes and compares two of them.
Every Starship flight so far has flown a suborbital trajectory, and Launch Library
excludes suborbital launches by default — without `include_suborbital=true` the
Starship count returns zero and `L8` evaluates against a number that means
"filtered out", not "hasn't happened". The verifier proves the filter is doing
something rather than assuming it.

---

## 3. First real run

```bash
python -m spcx.cli run
python -m spcx.cli evaluate
```

Read the gap list at the bottom of `run`. Gaps are expected on day one for
anything needing multiple periods — `L10`, `L13`, `S4`, `S9` all need at least
two quarters on record and will report `unknown` until they have them. That is
correct behaviour, not a bug to paper over.

Sanity-check three numbers by hand against the Q2 filing before you trust the
rest: revenue, capex, and cash. If those three match, the tag mapping is right.

---

## 3b. First tape run

```bash
python -m spcx.cli tape         # yfinance → stooq → cache; prints the tape brief
python -m spcx.cli dashboard    # site/tape.html
```

The line to check is the IV one: `IV30 <number>`. If it says `None`, the warnings
above it will say why (no yfinance installed, or the chain call failed). The tape
still runs — IV is simply reported as unavailable, never guessed.

---

## 4. Push

```bash
git init && git add . && git commit -m "SPCX range console"
gh repo create spcx-console --public --source=. --push
```

Then:

```bash
gh secret set SPCX_CONTACT --body "you@example.com"
gh label create status-change --color B3352D --description "A criterion changed status"
gh label create judgment-pass --color C4761E --description "Manual inputs are stale"
```

Settings → Pages → Source: **GitHub Actions**. The `pages.yml` workflow deploys
`site/` on any push that touches it or `data/latest.json`.

Trigger the first scheduled run by hand rather than waiting a day:

```bash
gh workflow run daily.yml
gh run watch
```

---

## 5. Rate limits you will hit if you are careless

| Source | Limit | What happens |
|---|---|---|
| SEC | 10 req/sec, declaring User-Agent required | blocked without `SPCX_CONTACT` |
| Launch Library 2 | ~15 calls/hour on the free tier | 429; use `SPCX_LL2_BASE` pointing at `lldev` while debugging |
| CelesTrak | one download per 2-hour data update | 403, then IP firewalled on repeat |

`spcx/http.py` refuses to retry 4xx responses for exactly this reason. CelesTrak
tightened its policy in March 2026 and now sends repeat callers to the firewall;
a retry loop against it is not a slow failure, it is a ban. The constellation
collector treats CelesTrak's "no update since your last download" 403 as a normal
outcome and records a gap rather than alarming.

Export `SPCX_LL2_BASE=https://lldev.thespacedevs.com/2.3.0/launches/` while
iterating. Same schema, much higher limit, data may lag slightly. Unset it for
production runs.

---

## 6. When something goes wrong later

```bash
python scripts/verify_sources.py      # first thing, always
python -m spcx.cli check              # is the judgment half stale?
python -m spcx.cli evaluate           # what does the record currently say?
git log --oneline -- config/criteria.yaml   # did a threshold move, and when?
```

That last one matters more than it looks. If a criterion's status surprises you,
check whether the criterion changed before assuming the world did.
