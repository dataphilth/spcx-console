"""Daily OHLCV bars with an on-disk cache.

Priority: yfinance (optional dependency) → stooq → data/prices.csv. Every fetch is
merged into the cache so history accumulates regardless of which source answered.
A run with no fresh source still runs, but flags the bars as stale.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from pathlib import Path

from ..http import get

log = logging.getLogger(__name__)
COLUMNS = ["date", "open", "high", "low", "close", "volume"]
STOOQ = "https://stooq.com/q/d/l/?s={sym}.us&i=d"


def _row(d: str, o, h, lo, c, v) -> dict | None:
    try:
        r = {"date": d[:10], "open": float(o), "high": float(h), "low": float(lo), "close": float(c),
             "volume": int(float(v or 0))}
    except (TypeError, ValueError):
        return None
    date.fromisoformat(r["date"])
    return r


def fetch_yfinance(ticker: str) -> list[dict]:
    import yfinance as yf  # optional; absent in the test environment

    hist = yf.Ticker(ticker).history(period="1y", auto_adjust=False)
    if hist is None or hist.empty:
        raise RuntimeError("yfinance returned no rows")
    out = []
    for idx, r in hist.iterrows():
        row = _row(str(idx)[:10], r["Open"], r["High"], r["Low"], r["Close"], r.get("Volume", 0))
        if row:
            out.append(row)
    return out


def fetch_stooq(ticker: str) -> list[dict]:
    url = STOOQ.format(sym=ticker.lower())
    text = get(url).decode()
    if "No data" in text[:200] or "Date" not in text[:100]:
        raise RuntimeError("stooq returned no usable CSV")
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        row = _row(r.get("Date", ""), r.get("Open"), r.get("High"), r.get("Low"), r.get("Close"), r.get("Volume"))
        if row:
            out.append(row)
    return out


def load_cache(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        rows = [_row(r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"]) for r in csv.DictReader(fh)]
    return [r for r in rows if r]


def save_cache(bars: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(bars)


def merge(cached: list[dict], fresh: list[dict]) -> list[dict]:
    by = {r["date"]: r for r in cached}
    by.update({r["date"]: r for r in fresh})
    return [by[k] for k in sorted(by)]


def get_bars(ticker: str, cache_path: Path, offline: bool = False, today: date | None = None) -> tuple[list[dict], dict]:
    today = today or date.today()
    cached = load_cache(cache_path)
    meta = {"source": "cache", "stale": False, "errors": []}
    fresh: list[dict] = []
    if not offline:
        for name, fn in (("yfinance", fetch_yfinance), ("stooq", fetch_stooq)):
            try:
                fresh = fn(ticker)
                meta["source"] = name
                break
            except Exception as exc:  # noqa: BLE001 — keep going on any failure
                log.warning("price source %s failed: %s", name, exc)
                meta["errors"].append(f"{name}: {exc}")
    bars = merge(cached, fresh) if fresh else cached
    if not bars:
        raise RuntimeError("no price bars from any source and no cache")
    save_cache(bars, cache_path)
    last = date.fromisoformat(bars[-1]["date"])
    meta.update(last_bar=bars[-1]["date"], rows=len(bars), bar_age_days=(today - last).days)
    if meta["bar_age_days"] > 4 or (not fresh and not offline):
        meta["stale"] = True
    if offline:
        meta["source"] = "cache (offline)"
    return bars, meta
