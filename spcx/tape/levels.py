"""Moving-average levels and cross events — what chart-watchers are looking at.

Traders act on these lines because other traders watch them, so the tape reports
when price crosses them. It reports the event and how it has held since. It does
not call the move.

Two rules keep this honest:

1. A moving average is only real once its window is full. A "200-day" built from
   86 sessions is an 86-day average. The bot still computes it, because charting
   platforms draw it and traders react to it, but every reading off a short
   window is stamped PARTIAL with the bar count.
2. Golden / death crosses (50 over / under 200) are never called on a partial
   window. Until the 200 is full the state says "not callable" and when it fills.

Timeframe is daily today. Everything is keyed by timeframe so a 4H series can
slot in once there is an intraday bar source.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

DEFAULTS = {"windows": [50, 200], "cross_lookback": 5, "golden_pair": [50, 200]}


def _r(x, nd=2):
    return None if x is None else round(x, nd)


def ma_series(closes: list[float], window: int) -> list[float]:
    """Simple moving average at every bar; a bar with fewer than `window` bars behind it averages what exists."""
    out, run = [], 0.0
    for i, c in enumerate(closes):
        run += c
        if i >= window:
            run -= closes[i - window]
        out.append(run / min(i + 1, window))
    return out


def _side(a: float, b: float) -> int:
    return 1 if a > b else -1 if a < b else 0


def _crosses(a: list[float], b: list[float], first_valid: int) -> list[tuple[int, int]]:
    """(bar index, +1 up / -1 down) wherever series a crosses series b, from first_valid on.

    A touch (a == b) does not count as a cross; the side is carried from the last bar that was on one.
    """
    out, last = [], 0
    for i in range(first_valid, len(a)):
        s = _side(a[i], b[i])
        if s == 0:
            continue
        if last and s != last:
            out.append((i, s))
        last = s
    return out


def _sessions_until_full(have: int, need: int, last_bar: str, bars_per_day: int = 1) -> str | None:
    """Rough date the window fills: weekdays only, holidays ignored, so it can run a few days early."""
    if have >= need:
        return None
    d, left = date.fromisoformat(last_bar[:10]), -(-(need - have) // bars_per_day)
    while left:
        d += timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d.isoformat()


def aggregate_4h(hourly: list[dict], now: datetime | None = None) -> list[dict]:
    """Hourly extended-hours bars (US/Eastern wall-clock `ts`) -> 4H bars on the 04/08/12/16 ET grid.

    That grid tiles the 4:00-20:00 extended session into four bars a day, the way charting
    platforms draw 4H with extended hours on. A regular-session bar stamped 09:30 lands in the
    08:00 bucket. When `now` (ET, naive) is given, a bucket still in progress is dropped: a cross
    on a half-built bar can vanish by its close.
    """
    buckets: dict[str, list[dict]] = {}
    for r in sorted(hourly, key=lambda r: r["ts"]):
        hh = int(r["ts"][11:13])
        if not 4 <= hh < 20:
            continue
        key = f"{r['ts'][:10]}T{4 + 4 * ((hh - 4) // 4):02d}:00"
        buckets.setdefault(key, []).append(r)
    out = []
    for key in sorted(buckets):
        rows = buckets[key]
        if now is not None and datetime.fromisoformat(key) + timedelta(hours=4) > now:
            continue
        out.append({"date": key, "open": rows[0]["open"], "high": max(r["high"] for r in rows),
                    "low": min(r["low"] for r in rows), "close": rows[-1]["close"],
                    "volume": sum(int(r.get("volume") or 0) for r in rows)})
    return out


def analyze(bars: list[dict], cfg: dict | None = None, timeframe: str = "1D", fresh_bars: int = 1,
            bars_per_day: int = 1) -> dict:
    """MA state plus events. An event is the latest cross inside the last `fresh_bars` bars —
    1 for the daily (one new bar per run), 4 for 4H (a run sees a day of new 4H bars)."""
    cfg = {**DEFAULTS, **(cfg or {})}
    bars = sorted(bars, key=lambda b: b["date"])
    n = len(bars)
    out: dict = {"timeframe": timeframe, "bars": n, "lines": [], "pair": None, "events": [],
                 "last_bar": bars[-1]["date"] if bars else None}
    if n < 2:
        return out
    closes = [b["close"] for b in bars]
    dates = [b["date"] for b in bars]
    close, last = closes[-1], dates[-1]
    lookback = max(int(cfg["cross_lookback"]), fresh_bars)
    first_fresh = n - max(1, fresh_bars)
    series = {}

    for w in cfg["windows"]:
        ma = ma_series(closes, w)
        series[w] = ma
        full = n >= w
        line = {"window": w, "value": _r(ma[-1]), "full": full, "have": min(n, w), "need": w,
                "fills_on": _sessions_until_full(n, w, last, bars_per_day),
                "side": {1: "above", -1: "below", 0: "on"}[_side(close, ma[-1])],
                "dist_pct": _r(100 * (close / ma[-1] - 1)), "last_cross": None}
        # A price/MA cross needs at least a handful of bars in the average to mean anything.
        xs = _crosses(closes, ma, first_valid=min(max(5, w // 4), n - 1))
        recent = [x for x in xs if x[0] >= n - lookback]
        if recent:
            i, s = recent[-1]
            held = all(_side(c, m) == s for c, m in zip(closes[i + 1:], ma[i + 1:]))
            line["last_cross"] = {"date": dates[i], "dir": "up" if s > 0 else "down", "bars_ago": n - 1 - i,
                                  "held": held, "full_at_cross": i + 1 >= w}
        out["lines"].append(line)

        fresh = [x for x in xs if x[0] >= first_fresh]
        if fresh:
            i, s = fresh[-1]
            prior = [x for x in xs if i - lookback <= x[0] < i]
            reverses = dates[prior[-1][0]] if prior and prior[-1][1] != s else None
            out["events"].append({
                "kind": "price_cross", "timeframe": timeframe, "window": w, "dir": "up" if s > 0 else "down",
                "date": dates[i], "close": _r(closes[i]), "ma": _r(ma[i]), "prev_close": _r(closes[i - 1]),
                "prev_ma": _r(ma[i - 1]), "dist_pct": _r(100 * (closes[i] / ma[i] - 1)), "full": i + 1 >= w,
                "have": min(i + 1, w), "reverses_cross_on": reverses, "crosses_in_window": len(fresh),
                "held_since": all(_side(c, m) == s for c, m in zip(closes[i + 1:], ma[i + 1:])),
            })

    fast, slow = cfg["golden_pair"]
    if fast in series and slow in series:
        pair = {"fast": fast, "slow": slow, "callable": n >= slow,
                "fills_on": _sessions_until_full(n, slow, last, bars_per_day), "state": None, "since": None}
        if n >= slow:
            a, b = series[fast], series[slow]
            xs = _crosses(a, b, first_valid=slow - 1)
            pair["state"] = {1: "fast above slow", -1: "fast below slow", 0: "equal"}[_side(a[-1], b[-1])]
            if xs:
                pair["since"] = dates[xs[-1][0]]
                i, s = xs[-1]
                if i >= first_fresh:
                    out["events"].append({
                        "kind": "golden_cross" if s > 0 else "death_cross", "timeframe": timeframe, "date": dates[i],
                        "fast": fast, "slow": slow, "fast_ma": _r(a[i]), "slow_ma": _r(b[i]), "close": _r(closes[i]),
                        "full": True,
                    })
        out["pair"] = pair
    return out


# ---------------------------------------------------------------------------
# Events → setups (both reads, like every other setup) and → a notice for GitHub.
# ---------------------------------------------------------------------------

def _partial_note(e: dict) -> str:
    return (f" PARTIAL WINDOW: this '{e['window']}' line averages only {e['have']} sessions — it is what charting "
            f"platforms draw, not a true {e['window']}-bar average." if not e.get("full") else "")


def to_setups(levels: dict) -> list[dict]:
    from .setups import _s

    out = []
    tf = levels.get("timeframe", "1D")
    for e in levels.get("events", []):
        if e["kind"] == "price_cross":
            w, up = e["window"], e["dir"] == "up"
            sfx = "" if tf == "1D" else f"_{tf}"
            unit = "day" if tf == "1D" else "bar"
            strength = (3 if w >= 200 else 2) if e["full"] else 1
            rev = f" Reverses the cross {'down' if up else 'up'} on {e['reverses_cross_on']}." if e.get("reverses_cross_on") else ""
            many = (f" {e['crosses_in_window']} crosses in the window — a chop, not a clean break."
                    if e.get("crosses_in_window", 1) > 1 else "")
            since = "" if e["date"] == levels.get("last_bar") else (
                " Has held since." if e.get("held_since") else " Has NOT held since.")
            ev = (f"{tf} bar {e['date']} closed {e['close']} vs SMA{w} {e['ma']} ({e['dist_pct']:+.1f}%); prior bar "
                  f"{e['prev_close']} vs {e['prev_ma']}.{rev}{many}{since}{_partial_note(e)}")
            if up:
                out.append(_s(f"CROSS_UP_SMA{w}{sfx}", f"Closed above the {w}-{unit} SMA ({tf})", "bullish", strength, ev,
                              "Reclaiming a widely watched average draws trend-followers and systematic buyers; the "
                              "confirmation is the next one or two closes holding above it.",
                              "One close over a line is not a trend. A slip back under it inside a few bars is the "
                              "failed-reclaim setup, and those tend to move fast.", tag="levels"))
            else:
                out.append(_s(f"CROSS_DOWN_SMA{w}{sfx}", f"Closed below the {w}-{unit} SMA ({tf})", "bearish", strength, ev,
                              "Losing the line is only damage if it sticks. A reclaim within a few bars is the "
                              "failed-breakdown setup, and those squeeze hard on a crowded short.",
                              "Losing a widely watched average invites trend-followers and systematic sellers; the "
                              "confirmation is the next one or two closes holding below it.", tag="levels"))
        elif e["kind"] in ("golden_cross", "death_cross"):
            golden = e["kind"] == "golden_cross"
            ev = (f"{tf} bar {e.get('date', '')}: SMA{e['fast']} {e['fast_ma']} crossed {'above' if golden else 'below'} SMA{e['slow']} "
                  f"{e['slow_ma']}; close {e['close']}. Both windows full.")
            out.append(_s(("GOLDEN_CROSS" if golden else "DEATH_CROSS") + ("" if tf == "1D" else f"_{tf}"),
                          f"{'Golden' if golden else 'Death'} cross: {e['fast']} {'over' if golden else 'under'} {e['slow']} ({tf})",
                          "bullish" if golden else "bearish", 2, ev,
                          ("The most-watched trend signal in retail charting just printed. It lags price by weeks; "
                           "the move it describes has mostly happened.") if golden else
                          ("Lags price by weeks: by the time it prints, much of the decline is in. Death crosses have "
                           "marked lows about as often as they have started legs down."),
                          ("Same lag, mirrored: golden crosses have marked tops about as often as they have started "
                           "legs up. Watch whether price holds above the 50.") if golden else
                          ("The most-watched trend signal in retail charting just printed to the downside. It lags; "
                           "the question is whether price holds below the 50."), tag="levels"))
    return out


def state_line(levels: dict) -> str:
    """One line of plain text: where price sits against each average."""
    tf = levels.get("timeframe", "1D")
    parts = []
    for ln in levels.get("lines", []):
        tag = "" if ln["full"] else f" PARTIAL {ln['have']}/{ln['need']}"
        x = ln.get("last_cross")
        xs = (f", crossed {x['dir']} {x['date']} ({'held' if x['held'] else 'failed'})" if x else "")
        parts.append(f"SMA{ln['window']} {ln['value']}{tag} ({ln['side']}, {ln['dist_pct']:+.1f}%{xs})")
    pr = levels.get("pair")
    if pr:
        parts.append(f"{pr['fast']}/{pr['slow']}: " + (f"{pr['state']} since {pr['since'] or 'start of full window'}" if pr["callable"]
                                                       else f"not callable until ~{pr['fills_on']}"))
    ext = " (ext hours)" if levels.get("extended_hours") else ""
    return f"levels {tf}{ext}: " + " · ".join(parts)


def notice_markdown(levels_by_tf: list[dict], ticker: str) -> str | None:
    """Issue body when an MA event fired on the latest bar; None when nothing did."""
    events = [e for lv in levels_by_tf for e in lv.get("events", [])]
    if not events:
        return None
    L = [f"## {ticker} — moving-average event", "",
         "Context, not a criterion and not a signal. Reported because traders watch these lines.", ""]
    for e in events:
        if e["kind"] == "price_cross":
            L.append(f"- **{e['timeframe']} close {'above' if e['dir'] == 'up' else 'below'} SMA{e['window']}** on {e['date']}: "
                     f"close {e['close']} vs {e['ma']} ({e['dist_pct']:+.1f}%)"
                     + (f"; reverses the cross on {e['reverses_cross_on']}" if e.get("reverses_cross_on") else "")
                     + (f"; {e['crosses_in_window']} crosses in the window (chop)" if e.get("crosses_in_window", 1) > 1 else "")
                     + ("" if e.get("held_since", True) else "; has NOT held since")
                     + (f". _Partial window: {e['have']}/{e['window']} sessions._" if not e["full"] else "."))
        else:
            L.append(f"- **{e['timeframe']} {'golden' if e['kind'] == 'golden_cross' else 'death'} cross** on {e['date']}: "
                     f"SMA{e['fast']} {e['fast_ma']} vs SMA{e['slow']} {e['slow_ma']}.")
    L += ["", "Whether it held shows on the tape page over the next few sessions (`held` / `failed`)."]
    return "\n".join(L) + "\n"
