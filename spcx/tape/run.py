"""One tape run: bars → measurements → setups → ladder → data/tape.json.

Reads data/latest.json (the criteria board) only to gate the ladder. Never writes
to it. Appends one row per bar-date to data/tape_history.csv — the tape layer's
own memory, and what the bias audit reads.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import date, datetime
from pathlib import Path

import yaml

from ..store import ROOT
from . import catalysts as cat
from . import ladder, options, prices, setups, technical

log = logging.getLogger(__name__)
TAPE_CONFIG = ROOT / "config" / "tape.yaml"
DATA = ROOT / "data"
HISTORY_COLS = ["date", "close", "chg_1d_pct", "atr_pct", "hv30", "iv30", "iv_hv_spread", "rsi", "from_ath_pct",
                "regime", "n_bullish", "n_bearish", "n_neutral", "setups", "active_band", "ladder_paused", "price_source"]


def load_tape_config(path: Path = TAPE_CONFIG) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cats = []
    for c in cfg.get("catalysts", []):
        c = dict(c)
        c["date"] = c["date"] if isinstance(c["date"], date) else date.fromisoformat(str(c["date"]))
        cats.append(c)
    cfg["catalysts"] = sorted(cats, key=lambda c: c["date"])
    bands = cfg["ladder"]["bands"]
    for a, b in zip(bands, bands[1:]):
        if b["high"] > a["low"]:
            raise ValueError("ladder bands must be listed from highest to lowest and not overlap")
    return cfg


def _history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _append_history(row: dict, path: Path) -> list[dict]:
    rows = [r for r in _history(path) if r.get("date") != row["date"]]
    rows.append({k: ("" if row.get(k) is None else row.get(k)) for k in HISTORY_COLS})
    rows.sort(key=lambda r: r["date"])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HISTORY_COLS)
        w.writeheader()
        w.writerows(rows)
    return rows


def _basis(lots: list[dict]) -> tuple[float | None, int]:
    sh = sum(int(lot["shares"]) for lot in lots)
    if not sh:
        return None, 0
    return round(sum(lot["shares"] * lot["price"] for lot in lots) / sh, 2), sh


def run(ticker: str, ipo_price: float | None, offline: bool = False, today: date | None = None,
        cfg: dict | None = None, data_dir: Path = DATA, board: dict | None = None) -> dict:
    today = today or date.today()
    cfg = cfg or load_tape_config()
    p = cfg["signals"]
    data_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    bars, px_meta = prices.get_bars(ticker, data_dir / "prices.csv", offline=offline, today=today)
    if px_meta["stale"]:
        warnings.append(f"PRICE BARS STALE — last bar {px_meta['last_bar']} via {px_meta['source']}; errors: {px_meta['errors']}")
    basis, shares = _basis(cfg["position"]["lots"])
    tech = technical.compute(bars, p, basis, ipo_price)
    chart = technical.chart_series(bars, p.get("history_bars_for_chart", 90))

    # ---- options ---------------------------------------------------------
    iv_path = data_dir / "iv_history.csv"
    snap = None
    if not offline:
        try:
            snap = options.fetch_snapshot(ticker, tech["close"], today)
            options.append_history(snap, iv_path)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"OPTIONS CHAIN UNAVAILABLE — {exc}. IV carried from the last snapshot if one exists.")
    hist_iv = options.load_history(iv_path)
    if snap is None and hist_iv:
        snap = {k: (None if v == "" else v) for k, v in hist_iv[-1].items()}
        snap["carried"] = True
    vol = {"iv30": None, "iv90": None, "iv_front": None, "expected_move_pct": None, "expected_move_usd": None,
           "put_call_oi": None, "hv30": tech.get("hv30"), "hv10": tech.get("hv10"), "snapshot_date": None, "carried": False}
    if snap:
        for k in ("iv30", "iv90", "iv_front", "expected_move_pct", "expected_move_usd", "put_call_oi", "front_expiry", "front_dte",
                  "skew25_front", "skew25_30d", "gex_musd_per_1pct", "total_call_oi", "total_put_oi",
                  "short_pct_float", "short_shares_m", "short_days_to_cover", "short_as_of"):
            v = snap.get(k)
            try:
                vol[k] = float(v) if v not in (None, "") and k not in ("front_expiry", "short_as_of") else (v if v != "" else None)
            except (TypeError, ValueError):
                vol[k] = v
        vol["term"] = snap.get("term") or []          # only present on a live snapshot, not a carried one
        vol["oi_walls"] = snap.get("oi_walls") or {}
        vol["snapshot_date"] = snap.get("date")
        vol["carried"] = bool(snap.get("carried"))
    vol["iv30_chg_1d"] = options.iv_change(hist_iv, today.isoformat(), "iv30") if hist_iv else None
    vol["skew_chg_1d"] = options.iv_change(hist_iv, today.isoformat(), "skew25_30d") if hist_iv else None
    if vol["iv30"] is not None and vol["hv30"] is not None:
        vol["iv_hv_spread"] = round(float(vol["iv30"]) - float(vol["hv30"]), 1)
        vol["term_slope"] = round(float(vol["iv90"]) - float(vol["iv30"]), 1) if vol.get("iv90") is not None else None
    else:
        vol["iv_hv_spread"] = None
    vol.update({f"iv_{k}" if k in ("rank", "percentile") else k: v
                for k, v in options.rank(hist_iv, vol["iv30"], p["min_history_for_ivrank"]).items()})
    vol["iv_rank_meaningful"] = vol.pop("meaningful", False)

    # ---- catalysts + setups ----------------------------------------------
    la = p["catalyst_lookahead_days"]
    cats = {"upcoming": cat.upcoming(cfg["catalysts"], today, la), "recent": cat.recent(cfg["catalysts"], today),
            "horizon": cat.horizon(cfg["catalysts"], today), "lookahead_days": la}
    st = setups.detect(tech, vol, p, cats["upcoming"])
    n_bull = sum(1 for s in st if s["direction"] == "bullish")
    n_bear = sum(1 for s in st if s["direction"] == "bearish")
    n_neut = sum(1 for s in st if s["direction"] == "neutral")

    # ---- ladder, gated by the criteria board ----------------------------------
    if board is None:
        lp = data_dir / "latest.json"
        board = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else {}
    gate = ladder.gate_from_evaluations(board.get("evaluations", []))
    fills = [lot for lot in cfg["position"]["lots"] if lot.get("band")]
    lad = ladder.evaluate(tech["close"], cfg["ladder"]["bands"], fills, gate, cfg["ladder"]["rules"],
                          float(cfg["position"].get("total_budget_dollars") or 0))

    # ---- history + bias audit ----------------------------------------------------
    regime = next((s["name"].split(": ", 1)[1] for s in st if s["id"] == "REGIME"), None)
    row = {"date": tech["date"], "close": tech["close"], "chg_1d_pct": tech.get("chg_1d_pct"), "atr_pct": tech.get("atr_pct"),
           "hv30": tech.get("hv30"), "iv30": vol.get("iv30"), "iv_hv_spread": vol.get("iv_hv_spread"), "rsi": tech.get("rsi"),
           "from_ath_pct": tech.get("from_ath_pct"), "regime": regime, "n_bullish": n_bull, "n_bearish": n_bear,
           "n_neutral": n_neut, "setups": "|".join(s["id"] for s in st), "active_band": lad["active_band"],
           "ladder_paused": lad["paused"], "price_source": px_meta["source"]}
    history = _append_history(row, data_dir / "tape_history.csv")
    audit = setups.bias_audit(history, 30, today)

    pos = {"shares": shares, "cost_basis": basis, "market_value": round(shares * tech["close"], 2) if shares else 0,
           "pnl_pct": tech.get("from_basis_pct"), "core_target_shares": cfg["position"]["core_target_shares"],
           "shares_to_target": max(cfg["position"]["core_target_shares"] - shares, 0),
           "sleeves": {s: sum(lot["shares"] for lot in cfg["position"]["lots"] if lot.get("sleeve") == s) for s in ("core", "satellite")}}

    tape = {
        "meta": {"run_at": datetime.now().isoformat(timespec="seconds"), "today": today.isoformat(), "ticker": ticker,
                 "price_source": px_meta, "warnings": warnings, "board_run_date": board.get("run_date"),
                 "disclaimer": "Context only. Not a criterion, not a signal, not investment advice. Nothing here trades."},
        "price": tech, "chart": chart, "vol": vol, "catalysts": cats, "setups": st, "bias_audit": audit,
        "ladder": lad, "gate": gate, "position": pos, "noise": cfg.get("noise", []), "history_tail": history[-30:],
    }
    (data_dir / "tape.json").write_text(json.dumps(tape, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return tape


def brief(tape: dict) -> str:
    """Plain-text summary for the CLI. Setups carry both reads by construction."""
    t, v, lad, a = tape["price"], tape["vol"], tape["ladder"], tape["bias_audit"]
    L = [f"tape {t['date']} · close {t['close']} ({t.get('chg_1d_pct', 0):+.1f}%) · src {tape['meta']['price_source']['source']}"]
    for w in tape["meta"]["warnings"]:
        L.append(f"  ! {w}")
    L.append(f"  ATR20 {t.get('atr_pct')}%/d · HV10 {t.get('hv10')} · HV30 {t.get('hv30')} · IV30 {v.get('iv30')} "
             f"(spread {v.get('iv_hv_spread')}) · RSI {t.get('rsi')} · from ATH {t.get('from_ath_pct')}% · regime "
             f"{next((s['name'].split(': ', 1)[1] for s in tape['setups'] if s['id'] == 'REGIME'), 'n/a')}")
    if v.get("skew25_30d") is not None or v.get("gex_musd_per_1pct") is not None or v.get("short_pct_float") is not None:
        walls = v.get("oi_walls") or {}
        cw = ", ".join(str(w["strike"]) for w in (walls.get("calls") or [])[:3]) or "—"
        pw = ", ".join(str(w["strike"]) for w in (walls.get("puts") or [])[:3]) or "—"
        L.append(f"  structure: 25Δ skew {v.get('skew25_30d')} pts (front {v.get('skew25_front')}) · IV30 Δ1d {v.get('iv30_chg_1d')} · "
                 f"P/C OI {v.get('put_call_oi')} · call walls {cw} · put walls {pw} · gamma proxy {v.get('gex_musd_per_1pct')} $M/1% · "
                 f"short {v.get('short_pct_float')}% float, {v.get('short_days_to_cover')}d to cover (as of {v.get('short_as_of')})")
        term = v.get("term") or []
        if term:
            L.append("  term: " + " · ".join(f"{t_['expiry'][5:]} {t_['atm_iv']}" for t_ in term))
    for c in tape["catalysts"]["upcoming"]:
        L.append(f"  T-{c['days']}d {c['date']} {c['event']} ({c['confidence']})")
    for s in tape["setups"]:
        if s["id"] == "REGIME":
            continue
        L.append(f"  [{s['id']}] {s['name']}")
        L.append(f"      long:  {s['long_read']}")
        L.append(f"      short: {s['short_read']}")
    L.append(f"  ladder: {lad['message']}")
    L.append(f"  bias audit {a['window_days']}d: {a['bullish']} bull-labelled / {a['bearish']} bear-labelled · skew {a['skew']:+.2f}")
    return "\n".join(L)
