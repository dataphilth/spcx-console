# SPCX Range Console

A monitoring instrument for Space Exploration Technologies Corp (Nasdaq: SPCX), a
company that IPO'd in June 2026 with essentially no public track record, three
unrelated businesses under one ticker, and a valuation that assumes all three work.

It answers one question, every weekday, mechanically: **did anything I said in
advance would matter actually happen?**

```
$ python -m spcx.cli evaluate

   L1   clear    Starlink net adds go negative              1.7 M net adds/qtr · fires lt 0 · 0/2 periods
   L2   clear    Connectivity operating income negative     1656 $M · fires lt 0 · 0/2 periods
 ~ L8   nearing  Starship fails to reach orbit by mid-2027  0 flights · by 2027-06-30 (314d remaining)
 ~ L13  nearing  Capex exceeds revenue three quarters       capex 18,369 vs revenue 7,814 (2.35x) · 2/3
   S3   clear    AI segment operating income turns positive -1257 $M · fires gt 0
 ~ S5   nearing  Starship reaches orbit and the catch works Flight 14 attempts both, NET 2026-08-28
```

---

## Why it is built this way

Three design decisions carry the whole thing. Each exists because of a specific way
this kind of project usually fails.

### 1. Symmetric criteria

Most personal research systems are a bull dashboard wearing a lab coat: they track
the conditions that would break the thesis the author holds, and nothing else. So
this one registers both halves. Fifteen conditions that would break the long case,
ten that would break the short case, on the same board, evaluated by the same code.

Colour encodes **distance to threshold, not good news or bad**. A fired bear-side
condition is red for exactly the same reason a fired bull-side one is: something
changed, go read it. `tests/test_config.py` fails the build if either side falls
below five criteria, so the board cannot quietly drift directional.

### 2. Thresholds live in YAML, not in code

`config/criteria.yaml` declares every threshold as data. Moving one is a reviewable
git diff with a date on it. If you find yourself loosening a threshold shortly after
a number moves against you, the history says so in a way that memory will not.

### 3. Collectors never guess

A collector that cannot source a number records a gap and moves on. It does not
carry forward the last value, interpolate, or substitute an estimate. A gap in an
append-only record is recoverable; an unsourced number in an audit trail poisons
every conclusion drawn downstream of it.

Every `Reading` requires `as_of`, `source`, `source_url`, `collector`, and
`confidence` at construction. Derived metrics inherit the *worst* confidence and
the *oldest* as-of date of their inputs, so staleness cannot launder itself
through arithmetic.

---

## The automated / judgment split

This is the honest part, and it is not a limitation to be engineered away.

**Automated** (`collectors/`, runs daily, free sources, no keys):

| Source | What it gives |
|---|---|
| SEC XBRL `companyfacts` | revenue, net income, capex, operating cash flow, cash, share count |
| SEC EDGAR submissions | 8-K, 10-Q, Form 4, 13G/D in the last 14 days |
| stooq | daily close |
| Launch Library 2 | Falcon cadence, Starship flight count |
| Celestrak GP catalogue | Starlink and Kuiper tracked-object counts |

**Judgment** (`config/manual_state.yaml`, updated after each earnings call):

Segment revenue and operating income are tagged in XBRL with a *segment axis*, and
the `companyfacts` API drops dimensional facts. There is no free endpoint that
returns SpaceX's Connectivity/AI/Space split. Neither are Starlink subscribers,
ARPU, or whether a Starship flight actually reached orbit — Launch Library records
that a flight happened, not what trajectory it flew.

Rather than paper over that, manual metrics sit in the same ledger with their own
as-of dates. `spcx check` fails the build when they age past their cadence, which
opens a "judgment pass due" issue. A monitoring system whose manual inputs silently
rot is worse than none at all: it shows confident green while describing a world
six months old.

`spcx brief` renders the prompt for that pass, seeded from current state so it
cannot drift out of sync with the data.

---

## The tape layer (added 2026-08-25)

The board says what would change the thesis. The tape layer says what the price
is doing while we wait — and is walled off from the board by construction:
nothing in it is a criterion, nothing in it can move a criterion's status, and it
only *reads* `data/latest.json` (to pause the accumulation ladder when a long-case
Tier-1 fires, or two long-case Tier-2s fire).

```
$ python -m spcx.cli tape         # bars + options chain → data/tape.json, data/tape_history.csv
$ python -m spcx.cli dashboard    # → site/tape.html (board + tape on one page)
```

What it measures: ATR20, HV10/30, SMA20/50 distance in ATR units, RSI14, 20-day
range and compression, volume z-score, distance from ATH/ATL/IPO/cost basis. From
the listed options chain (added 2026-08-25): the full ATM term structure, IV30/IV90
by total-variance interpolation, front-expiry expected move, 25Δ skew at the front
and ~30-day expiries (Black-Scholes r=0 on each contract's own IV), open-interest
walls by strike inside 60 days, put/call OI, a dealer-gamma proxy (Σ γ·OI·100·S²·1%,
calls long / puts short convention), day-over-day IV and skew change, IV rank over
stored history (labelled "thin" under 60 sessions), and Yahoo's copy of the
exchange-reported short interest (medium confidence, bi-monthly).

What it does *not* have, and would cost money: intraday trades, options flow /
sweeps, real dealer positioning, borrow rates. The Brier scores in `data/forecasts.yaml`
are the honest test of whether the free tier earns a paid one.

What it surfaces: setups — stretch, RSI extremes, 20-day breakout/breakdown,
volume climax, compression, premium rich/cheap, put/call skew rich, IV jump,
price near an OI wall, catalyst window. **Every setup
carries a long read and a short read.** The direction chip is a label for a
trailing 30-day bias audit that counts which way the labels lean, so drift in the
thresholds is visible; it is not a view. The layer never says buy or sell.

What it enforces: the ladder in `config/tape.yaml` — bands, share counts, budget,
the repeat-purchase rule, the below-$105 criteria-check gate, and the pause rule
above. Bands ship unfunded (`shares: 0`) and the page says so until they are not.

Dependencies: `yfinance` is optional. Without it the tape uses stooq for bars and
reports IV as unavailable. Tests need neither.

---

## Calibration

The reason a research log is not the same as hindsight.

```
$ python -m spcx.cli forecast add \
    "Q3 2026 capex exceeds Q3 2026 revenue" 0.8 2026-12-15 --criterion L13
$ python -m spcx.cli forecast score

{ "n": 12, "brier": 0.147, "base_rate_brier": 0.213,
  "beats_base_rate": true, "bias_reading": "roughly calibrated" }
```

Recording a probability *before* resolution and scoring it afterward is the only
mechanism that tells you whether the criteria carry information or merely narrate.
The scored comparison is against the base rate, not against zero — four forecasts
at 90% that resolve three-of-four true score **worse** than someone who just said
75% every time, and the test suite asserts exactly that case.

If this ever generates trade ideas, this is the file that decides whether they are
worth anything.

---

## Layout

```
config/
  criteria.yaml        25 conditions, thresholds as versioned data
  metrics.yaml         metric registry: which collector, what cadence, auto or manual
  manual_state.yaml    the judgment half + unresolved research backlog
spcx/
  models.py            Reading / Snapshot / Evaluation — provenance required at construction
  evaluate.py          the engine: threshold, compare, streak, manual rules
  collectors/          one module per source; registry pattern; gaps over guesses
  diff.py              status-change detection (never value-change)
  forecast.py          Brier scoring against base rate
  brief.py             judgment-pass prompt, generated from live state
  cli.py               run · evaluate · check · brief · forecast
data/
  snapshots/*.json     append-only, one per run, git-committed
  latest.json          the view layer's entry point
  forecasts.yaml       the calibration log
site/index.html        static Pages view of latest.json
site/tape.html         board + tape, self-contained, regenerated by `spcx dashboard`
config/tape.yaml       position, ladder, catalysts, signal thresholds (context, never criteria)
spcx/tape/             prices · options · technical · setups · ladder · catalysts · run · dashboard
tests/                 45 tests, run before every collection
```

---

## Running it

See [PUSH.md](PUSH.md) for the full runbook. The short version:

```bash
pip install -r requirements-dev.txt
export SPCX_CONTACT="you@example.com"   # the SEC requires a declaring contact

pytest -q                        # 45 tests
python scripts/verify_sources.py # probe every endpoint before trusting a run
python -m spcx.cli run           # collect, evaluate, write a snapshot
python -m spcx.cli evaluate      # re-evaluate the record without collecting
python -m spcx.cli check         # fail if the judgment half has gone stale
python -m spcx.cli brief         # print the judgment-pass prompt
python -m spcx.cli tape          # price / vol / setups / ladder → data/tape.json (context only)
python -m spcx.cli dashboard     # render site/tape.html
```

GitHub Actions runs `daily.yml` at 21:30 UTC on weekdays: tests, then collect,
then commit the snapshot. It opens an issue only on a **change of criterion
status** — never on a change of value. A metric that moves every day would train
you to ignore the channel, which is how monitoring systems become decorative
around month six.

Set `SPCX_CONTACT` as a repository secret. Enable Pages with source "GitHub
Actions" for the dashboard.

---

## Tests worth reading

The suite targets the ways this class of system goes wrong quietly rather than
loudly:

- `test_streak_dedupes_by_period_not_by_snapshot` — reading the same 10-Q for 29
  consecutive days must not produce a 29-quarter streak. Consecutive counts run
  over distinct fiscal periods, not over daily snapshots. This is the bug that
  silently ruins the whole record.
- `test_missing_data_is_unknown_not_clear` — absence of evidence renders as
  `unknown`, never as reassurance.
- `test_deadline_criterion_cannot_fire_before_its_deadline` — "fails to happen by
  D" is not missed while there is time on the clock. This was a live bug, caught
  by writing the test.
- `test_restatement_supersedes_rather_than_appends` — a corrected figure replaces
  the original for its period instead of extending a streak.
- `test_overconfidence_loses_to_the_base_rate` — the scoring is real.

## Two bugs worth naming

Both were found before the first live run, and both would have been silent.

**Suborbital launches are excluded by default.** Launch Library filters to orbital
launches unless `include_suborbital=true` is passed. Every Starship flight to date
flew a suborbital trajectory, so the Starship count would have returned zero — and
`L8` ("Starship fails to reach orbit") would have evaluated against a number
meaning "filtered out" rather than "hasn't happened", and looked entirely
plausible doing it. `verify_sources.py` runs both filters and compares them rather
than trusting the parameter is doing anything.

**CelesTrak now firewalls repeat callers.** It enforces one download per two-hour
data update as of March 2026, returning 403 with an explanatory body. A retry loop
against that is not a slow failure, it is a ban. `spcx/http.py` refuses to retry
any 4xx, and the constellation collector reads CelesTrak's "no update since your
last download" as a normal outcome rather than an error.

---

## What this is not

Not a trading system, not a signal generator, and not investment advice. It holds
no position and knows nothing about one. It reports which pre-registered conditions
have moved and how far the rest are from their thresholds. Whether any of that
should change anyone's mind is a separate question that the code does not answer
and is not designed to.

Seeded from the SEC-filed Q2 2026 earnings release (4 August 2026), the 424B4 and
FWP lockup documents, and a press refresh dated 20 August 2026. Several inputs are
explicitly unreconciled — see `unresolved` in `config/manual_state.yaml`, which is
the research backlog rather than an oversight.

MIT.
