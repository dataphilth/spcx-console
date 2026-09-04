"""Remove the position/ladder layer from spcx-console. Idempotent."""
import os, re, sys

def rw(path, fn):
    s = open(path, encoding="utf-8").read()
    n = fn(s)
    if n != s:
        open(path, "w", encoding="utf-8", newline="\n").write(n)
        print("edited ", path)
    else:
        print("already ok", path)

def sub1(s, old, new, must=True):
    if old in s:
        return s.replace(old, new)
    if must and new not in s:
        sys.exit(f"ANCHOR NOT FOUND: {old[:70]!r}")
    return s

# 1. ladder.py
if os.path.exists("spcx/tape/ladder.py"):
    os.remove("spcx/tape/ladder.py"); print("removed spcx/tape/ladder.py")
else:
    print("already ok ladder.py gone")

# 2. config/tape.yaml — drop position: and ladder: blocks
def fix_yaml(s):
    s = re.sub(r"# -+\n# Position of record\..*?(?=# -+\n# Share structure)", "", s, flags=re.S)
    s = re.sub(r"# -+\n# Accumulation ladder\..*?(?=# -+\n# Catalyst calendar)", "", s, flags=re.S)
    s = sub1(s, "# The TAPE layer — price, volatility, options, setups, ladder, catalysts.",
                "# The TAPE layer — price, volatility, options, setups, catalysts.")
    s = sub1(s, "B21 static fire pending; placeholder date", "Sep 15 per reported FCC filing, corroborated 9/2; B21 static fire done 8/28; FAA license outstanding", must=False)
    return s
rw("config/tape.yaml", fix_yaml)

# 3. run.py
def fix_run(s):
    s = sub1(s, "One tape run: bars → measurements → setups → ladder → data/tape.json.\n\nReads data/latest.json (the criteria board) only to gate the ladder. Never writes\nto it.",
                "One tape run: bars → measurements → setups → data/tape.json.\n\nReads data/latest.json (the criteria board) only to stamp its run date. Never writes\nto it.")
    s = sub1(s, "from . import ladder, options, prices, setups, technical", "from . import options, prices, setups, technical")
    s = sub1(s, '"regime", "n_bullish", "n_bearish", "n_neutral", "setups", "active_band", "ladder_paused", "price_source"]',
                '"regime", "n_bullish", "n_bearish", "n_neutral", "setups", "price_source"]')
    s = sub1(s, '    bands = cfg["ladder"]["bands"]\n    for a, b in zip(bands, bands[1:]):\n        if b["high"] > a["low"]:\n            raise ValueError("ladder bands must be listed from highest to lowest and not overlap")\n', "")
    s = sub1(s, 'w = csv.DictWriter(fh, fieldnames=HISTORY_COLS)', 'w = csv.DictWriter(fh, fieldnames=HISTORY_COLS, extrasaction="ignore")')
    s = sub1(s, 'def _basis(lots: list[dict]) -> tuple[float | None, int]:\n    sh = sum(int(lot["shares"]) for lot in lots)\n    if not sh:\n        return None, 0\n    return round(sum(lot["shares"] * lot["price"] for lot in lots) / sh, 2), sh\n\n\n', "")
    s = sub1(s, '    basis, shares = _basis(cfg["position"]["lots"])\n    tech = technical.compute(bars, p, basis, ipo_price)', '    tech = technical.compute(bars, p, ipo_price)')
    s = sub1(s, '    # ---- ladder, gated by the criteria board ----------------------------------\n    if board is None:\n        lp = data_dir / "latest.json"\n        board = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else {}\n    gate = ladder.gate_from_evaluations(board.get("evaluations", []))\n    fills = [lot for lot in cfg["position"]["lots"] if lot.get("band")]\n    lad = ladder.evaluate(tech["close"], cfg["ladder"]["bands"], fills, gate, cfg["ladder"]["rules"],\n                          float(cfg["position"].get("total_budget_dollars") or 0))\n',
                '    # ---- board, read only for its run date ------------------------------------\n    if board is None:\n        lp = data_dir / "latest.json"\n        board = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else {}\n')
    s = sub1(s, '"setups": "|".join(s["id"] for s in st), "active_band": lad["active_band"],\n           "ladder_paused": lad["paused"], "price_source": px_meta["source"]}',
                '"setups": "|".join(s["id"] for s in st), "price_source": px_meta["source"]}')
    s = sub1(s, '    pos = {"shares": shares, "cost_basis": basis, "market_value": round(shares * tech["close"], 2) if shares else 0,\n           "pnl_pct": tech.get("from_basis_pct"), "core_target_shares": cfg["position"]["core_target_shares"],\n           "shares_to_target": max(cfg["position"]["core_target_shares"] - shares, 0),\n           "sleeves": {s: sum(lot["shares"] for lot in cfg["position"]["lots"] if lot.get("sleeve") == s) for s in ("core", "satellite")}}\n\n', "")
    s = sub1(s, '        "ladder": lad, "gate": gate, "position": pos, "noise": cfg.get("noise", []), "history_tail": history[-30:],',
                '        "noise": cfg.get("noise", []), "history_tail": history[-30:],')
    s = sub1(s, '    t, v, lad, a = tape["price"], tape["vol"], tape["ladder"], tape["bias_audit"]', '    t, v, a = tape["price"], tape["vol"], tape["bias_audit"]')
    s = sub1(s, '    L.append(f"  ladder: {lad[\'message\']}")\n', "")
    return s
rw("spcx/tape/run.py", fix_run)

# 4. technical.py — drop cost basis
def fix_tech(s):
    s = sub1(s, "def compute(bars: list[dict], params: dict, cost_basis: float | None, ipo_price: float | None) -> dict:",
                "def compute(bars: list[dict], params: dict, ipo_price: float | None) -> dict:")
    s = sub1(s, '    if cost_basis:\n        out["from_basis_pct"] = _r(100 * (close / cost_basis - 1))\n', "")
    return s
rw("spcx/tape/technical.py", fix_tech)

# 5. dashboard.py
def fix_dash(s):
    s = sub1(s, "  const basis=S.position&&S.position.cost_basis; if(basis){lo=Math.min(lo,basis);hi=Math.max(hi,basis);}\n", "")
    s = sub1(s, """  (S.ladder.bands||[]).forEach(b=>{ if(b.high<lo||b.low>hi) return; const y1=ys(Math.min(b.high,hi)),y2=ys(Math.max(b.low,lo));
    svg+=`<rect x="${m.l}" y="${y1}" width="${W-m.l-m.r}" height="${y2-y1}" fill="#3F6DA8" opacity="${b.active?.10:.035}"/>`;
    svg+=`<text x="${m.l+4}" y="${y1+10}" font-size="10" fill="#5C6B79" font-family="monospace">${b.name} ${b.low}–${b.high}</text>`;});
""", "")
    s = sub1(s, """  if(basis){const y=ys(basis);svg+=`<line x1="${m.l}" x2="${W-m.r}" y1="${y}" y2="${y}" stroke="#5C6B79" stroke-dasharray="4 4"/>`;
    svg+=`<text x="${m.l+130}" y="${y-4}" font-size="11" fill="#33414E" font-family="monospace">basis ${basis}</text>`;}
""", "")
    s = sub1(s, '    t, v, lad, pos, cats, a = (tape["price"], tape["vol"], tape["ladder"], tape["position"], tape["catalysts"],\n                               tape["bias_audit"])',
                '    t, v, cats, a = tape["price"], tape["vol"], tape["catalysts"], tape["bias_audit"]')
    s = sub1(s, """             f'<span>Ladder <b>{"PAUSED" if lad["paused"] else "open"}</b></span></div></div></header>')""",
                """             '</div></div></header>')""")
    s = sub1(s, """        ("Regime", _e(regime), f'RSI {_n(t.get("rsi"), 0)} · SMA20 {_n(t.get("sma20"))} ({_n(t.get("dist_sma20_atr"), 1)} ATR) · SMA50 {_n(t.get("sma50"))}'),
        ("Position", f'{pos["shares"]} sh', f'basis {pos["cost_basis"]} · {_p(pos.get("pnl_pct"))} · {pos["shares_to_target"]} to 100'),
""", """        ("Regime", _e(regime), f'RSI {_n(t.get("rsi"), 0)} · SMA20 {_n(t.get("sma20"))} ({_n(t.get("dist_sma20_atr"), 1)} ATR) · SMA50 {_n(t.get("sma50"))}'),
""")
    s = sub1(s, "<h2>Daily close · ladder bands shaded · dashed = cost basis</h2>", "<h2>Daily close</h2>")
    s = sub1(s, "Tier 2 is damaging; two at once pauses the ladder.", "Tier 2 is damaging on its own; two at once is structural.")
    s = re.sub(r"    # ladder\n.*?    B\.append\(\"</tbody></table></div><ul class='small'>\" \+ \"\"\.join\(f\"<li>\{_e\(r\)\}</li>\" for r in lad\[\"rules\"\]\) \+ \"</ul></div>\"\)\n\n", "", s, flags=re.S)
    s = sub1(s, '    payload = json.dumps({"chart": tape["chart"], "ladder": {"bands": lad["bands"]}, "position": pos}, default=str)',
                '    payload = json.dumps({"chart": tape["chart"]}, default=str)')
    return s
rw("spcx/tape/dashboard.py", fix_dash)

# 6. setups.py wording
def fix_setups(s):
    s = sub1(s, "the cheap long expression is call spreads, or selling puts against the ladder \"\n                          \"bands you'd buy at anyway (assignment IS the plan there).",
                "the cheap long expression is call spreads, or selling puts at levels a long \"\n                          \"view would own anyway.")
    s = sub1(s, "Price moves into these are on the noise list; the ladder is what acts on them.", "Price moves into these are on the noise list.")
    return s
rw("spcx/tape/setups.py", fix_setups)

# 7. docstrings / README / workflow
rw("spcx/tape/__init__.py", lambda s: sub1(s, "price, volatility, options, setups, ladder, catalysts.", "price, volatility, options, setups, catalysts."))
def fix_cli(s):
    s = sub1(s, "spcx tape         price, vol, options, setups, ladder → data/tape.json", "spcx tape         price, vol, options, setups → data/tape.json")
    s = sub1(s, 'help="price / vol / setups / ladder context (never criteria)"', 'help="price / vol / setups context (never criteria)"')
    return s
rw("spcx/cli.py", fix_cli)
def fix_readme(s):
    s = sub1(s, "only *reads* `data/latest.json` (to pause the accumulation ladder when a long-case\nTier-1 fires, or two long-case Tier-2s fire).",
                "only *reads* `data/latest.json` (to stamp the board's run date beside its own).")
    s = re.sub(r"What it enforces: the ladder in `config/tape\.yaml`.*?until they are not\.\n\n", "", s, flags=re.S)
    s = sub1(s, "config/tape.yaml       position, ladder, catalysts, signal thresholds", "config/tape.yaml       share structure, catalysts, signal thresholds")
    s = sub1(s, "prices · options · technical · setups · ladder · catalysts · run · dashboard", "prices · options · technical · setups · catalysts · run · dashboard")
    s = sub1(s, "# price / vol / setups / ladder → data/tape.json", "# price / vol / setups → data/tape.json")
    return s
rw("README.md", fix_readme)
rw(".github/workflows/daily.yml", lambda s: sub1(s, "Tape (price, vol, setups, ladder — context, never criteria)", "Tape (price, vol, setups — context, never criteria)"))

# 8. tests
def fix_tests(s):
    s = sub1(s, "symmetric setups, ladder gating.", "symmetric setups.")
    s = sub1(s, "from spcx.tape import ladder, setups, technical", "from spcx.tape import setups, technical")
    s = sub1(s, "    t = technical.compute(synthetic_bars(), PARAMS, 137.85, 135.0)", "    t = technical.compute(synthetic_bars(), PARAMS, 135.0)")
    s = sub1(s, '    assert t["from_basis_pct"] == pytest.approx(0.44, abs=0.05)\n', '    assert t["from_ipo_pct"] == pytest.approx(2.56, abs=0.05)\n')
    s = re.sub(r"def test_ladder_pauses_on_long_tier1_fired_only\(\):.*?\n\n\n", "", s, flags=re.S)
    s = sub1(s, '    assert tape["price"]["close"] == 138.46 and tape["ladder"]["active_band"] == "Current"\n    assert tape["gate"]["paused"] is False\n',
                '    assert tape["price"]["close"] == 138.46\n    for dead in ("ladder", "gate", "position"):\n        assert dead not in tape, f"{dead} is a retired key — the tape holds no position"\n    assert "position" not in json.dumps(tape).lower().replace("positioning", "")\n')
    s = sub1(s, '    assert "ladder:" in txt and "bias audit" in txt', '    assert "ladder" not in txt and "bias audit" in txt')
    s = sub1(s, '''def test_tape_config_is_ordered_and_unfunded_by_default():
    cfg = tape_run.load_tape_config()
    bands = cfg["ladder"]["bands"]
    assert all(a["low"] >= b["high"] for a, b in zip(bands, bands[1:]))
    assert cfg["position"]["total_budget_dollars"] == 0  # until Phil funds it
''', '''def test_tape_config_carries_no_position():
    cfg = tape_run.load_tape_config()
    assert "position" not in cfg and "ladder" not in cfg
    assert cfg["share_structure"]["public_float_b"] > 0 and cfg["catalysts"]
''')
    return s
rw("tests/test_tape.py", fix_tests)
print("done")
