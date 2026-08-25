"""Setups: pattern detection with BOTH readings attached.

Design rule for staying unbiased: every setup carries a `long_read` and a
`short_read`. The bot never says "buy" or "sell"; it says "this pattern is
present, here is what a long would see and what a short would see." Direction
is a label for the bias audit, not advice.

`direction`: bullish | bearish | neutral   (what the pattern is *conventionally*
read as; used only to check the bot isn't drifting one way over time)
`strength`:  1..3
"""
from __future__ import annotations

import datetime as dt


def _s(id_, name, direction, strength, evidence, long_read, short_read, tag="technical"):
    return {"id": id_, "name": name, "direction": direction, "strength": strength,
            "evidence": evidence, "long_read": long_read, "short_read": short_read, "tag": tag}


def detect(tech: dict, vol: dict, params: dict, catalysts_soon: list[dict]) -> list[dict]:
    out: list[dict] = []
    close = tech.get("close")
    thin = tech.get("bars", 0) < 40

    # ---- Stretch from the mean (ATR units) --------------------------------
    d20 = tech.get("dist_sma20_atr")
    if d20 is not None:
        k = params["extreme_atr_multiple"]
        if d20 <= -k:
            out.append(_s("STRETCH_DOWN", "Stretched below 20-day mean", "bullish", 2 if d20 > -3 else 3,
                          f"Close is {abs(d20):.1f} ATR below SMA20 ({tech.get('sma20')}); ATR ≈ {tech.get('atr_pct')}%/day.",
                          "Mean-reversion long setup: extremes of this size on a 90-vol name historically snap back; "
                          "the risk is that 'oversold' keeps going in a downtrend.",
                          "Trend-continuation context: momentum is with the short, but entering *after* a 2-ATR stretch "
                          "is chasing; the reward is poor unless the move is catalyst-driven."))
        elif d20 >= k:
            out.append(_s("STRETCH_UP", "Stretched above 20-day mean", "bearish", 2 if d20 < 3 else 3,
                          f"Close is {d20:.1f} ATR above SMA20 ({tech.get('sma20')}).",
                          "Momentum is with the long, but adding here is buying a stretched tape; a pullback to the mean "
                          "is the higher-probability entry.",
                          "Mean-reversion short setup: same logic in reverse. On a 25–32% short-interest name, squeezes "
                          "extend further than the math says they should."))

    # ---- RSI extremes --------------------------------------------------------
    r = tech.get("rsi")
    if r is not None:
        if r <= 30:
            out.append(_s("RSI_OVERSOLD", "RSI(14) oversold", "bullish", 1 if r > 25 else 2, f"RSI = {r}.",
                          "Classic oversold reading; works best when it coincides with STRETCH_DOWN or a volume climax.",
                          "Oversold can persist for weeks in a distribution phase — an RSI reading alone is not a reason to cover."))
        elif r >= 70:
            out.append(_s("RSI_OVERBOUGHT", "RSI(14) overbought", "bearish", 1 if r < 75 else 2, f"RSI = {r}.",
                          "Strong tapes stay overbought; treat as a 'don't add here' rather than a 'sell'.",
                          "Overbought reading; works best when it coincides with STRETCH_UP or a buying climax."))

    # ---- Range breakout / breakdown -----------------------------------------
    prh, prl = tech.get("prior_range_high"), tech.get("prior_range_low")
    if close is not None and prh is not None:
        if close > prh:
            out.append(_s("BREAKOUT_20D", "Close above prior 20-day high", "bullish", 2,
                          f"Close {close} > prior 20-day high {prh}. Volume {tech.get('volume_vs_avg')}x average.",
                          "Breakout setup. The confirmation is a hold above the level on the next 1–2 closes; "
                          "failed breakouts on this name have been violent.",
                          "Failed-breakout short setup if the close slips back below the prior high — that's the trigger, "
                          "not the breakout itself."))
        elif close < prl:
            out.append(_s("BREAKDOWN_20D", "Close below prior 20-day low", "bearish", 2,
                          f"Close {close} < prior 20-day low {prl}. Volume {tech.get('volume_vs_avg')}x average.",
                          "Failed-breakdown long setup if price reclaims the prior low — that is the trigger, not the breakdown.",
                          "Breakdown setup; confirmation is a hold below on subsequent closes."))

    # ---- Volume climax ---------------------------------------------------------
    vz, c1 = tech.get("volume_z"), tech.get("chg_1d_pct")
    if vz is not None and c1 is not None and vz >= params["volume_climax_z"]:
        if c1 < 0:
            out.append(_s("VOLUME_CLIMAX_DOWN", "High-volume down day", "bullish", 2,
                          f"Volume z-score {vz} on a {c1}% day; close location {tech.get('close_loc')} (1 = at high).",
                          "Capitulation candidate — high volume on a down day with a close off the lows is the classic "
                          "exhaustion pattern. Close near the low = not yet.",
                          "Distribution: institutions selling into liquidity. If the next day fails to bounce, "
                          "the volume was supply, not capitulation."))
        elif c1 > 0:
            out.append(_s("VOLUME_CLIMAX_UP", "High-volume up day", "bearish", 2,
                          f"Volume z-score {vz} on a +{c1}% day; close location {tech.get('close_loc')}.",
                          "Accumulation if it holds; short-covering if it fades. The follow-through day decides.",
                          "Buying-climax candidate — especially into a lockup or a known event."))

    # ---- Range compression -----------------------------------------------------
    rc = tech.get("range_compression")
    if rc is not None and rc <= 0.5:
        out.append(_s("COMPRESSION", "Range compression", "neutral", 2,
                      f"Last {params['range_window']}-day range is {rc:.0%} of the prior window's.",
                      "Squeeze setup: direction unknown; the expansion tends to be large. A long waits for the upside "
                      "break, not the squeeze itself.",
                      "Same — the short waits for the downside break. Straddle-type exposure is the honest expression."))

    # ---- Trend regime ----------------------------------------------------------
    s20, s50 = tech.get("sma20"), tech.get("sma50")
    if close is not None and s20 is not None:
        if s50 is not None:
            if close > s20 > s50:
                regime = "uptrend"
            elif close < s20 < s50:
                regime = "downtrend"
            else:
                regime = "transition"
        else:
            regime = "above SMA20" if close > s20 else "below SMA20"
        out.append(_s("REGIME", f"Trend regime: {regime}", "neutral", 1,
                      f"Close {close}; SMA20 {s20}; SMA50 {s50 if s50 is not None else 'n/a (warming up)'}.",
                      "Trend-following longs want uptrend + pullback-to-SMA20 entries.",
                      "Trend-following shorts want downtrend + rally-to-SMA20 entries.", tag="regime"))

    # ---- Vol premium ---------------------------------------------------------------
    spread = vol.get("iv_hv_spread")
    if spread is not None:
        if spread >= params["iv_hv_rich_spread"]:
            out.append(_s("PREMIUM_RICH", "Options premium rich vs realized", "neutral", 2,
                          f"IV30 {vol.get('iv30')} vs HV30 {vol.get('hv30')} → spread +{spread:.0f} pts. IV rank {vol.get('iv_rank')} "
                          f"({'meaningful' if vol.get('iv_rank_meaningful') else 'NOT yet meaningful — thin history'}).",
                          "Covered-call writing against the SATELLITE sleeve only is the pre-registered expression. Check the "
                          "catalyst calendar first — rich IV into a Starship flight is rich for a reason.",
                          "Put selling / put spreads for a short's income expression carry the same catalyst caveat.", tag="vol"))
        elif spread <= params["iv_hv_cheap_spread"]:
            out.append(_s("PREMIUM_CHEAP", "Options premium cheap vs realized", "neutral", 2,
                          f"IV30 {vol.get('iv30')} vs HV30 {vol.get('hv30')} → spread {spread:.0f} pts.",
                          "Do NOT write covered calls here — you'd be selling movement below what the stock actually does. "
                          "Long-vol structures (calls, call spreads) are the cheap expression of a long view.",
                          "Long puts / put spreads are the cheap expression of a short view. Cheap is relative: 67-vol is not cheap in absolute terms.", tag="vol"))

    # ---- Catalyst window ------------------------------------------------------------
    for c in catalysts_soon:
        if c["kind"] in ("starship", "earnings") or "28%" in c["event"]:
            out.append(_s("CATALYST_WINDOW", f"Catalyst within {c['days']}d: {c['event']}", "neutral", 3,
                          f"{c['date']} ({c['confidence']} date confidence). Front-expiry expected move "
                          + (f"±{vol['expected_move_pct']}%." if vol.get("expected_move_pct") is not None else "unavailable (no options snapshot)."),
                          "Binary event ahead. New directional entries are a bet on the event, not on the setup. "
                          "Price moves into these are on the noise list; the ladder is what acts on them.",
                          "Same. Note the pattern so far: the market sold into both the Aug 4 print and the Aug 6 unlock, "
                          "then rallied once supply arrived.", tag="catalyst"))
            break

    if thin:
        for s in out:
            s["caveat"] = f"Only {tech.get('bars')} sessions of history — every window here is under-sampled."
    return out


def bias_audit(history: list[dict], window_days: int = 30, today: dt.date | None = None) -> dict:
    """Count bullish vs bearish setups surfaced over the trailing window.

    A healthy unbiased bot on a mean-reverting name should show roughly balanced counts
    over long windows. A persistent skew means either the tape is one-directional (fine)
    or the detection thresholds are asymmetric (fix the config).
    """
    today = today or dt.date.today()
    cutoff = today - dt.timedelta(days=window_days)
    bull = bear = neutral = 0
    for row in history:
        try:
            d = dt.date.fromisoformat(row["date"])
        except Exception:  # noqa: BLE001
            continue
        if d < cutoff:
            continue
        bull += int(row.get("n_bullish", 0))
        bear += int(row.get("n_bearish", 0))
        neutral += int(row.get("n_neutral", 0))
    total = bull + bear
    return {"window_days": window_days, "bullish": bull, "bearish": bear, "neutral": neutral,
            "skew": round((bull - bear) / total, 2) if total else 0.0}
