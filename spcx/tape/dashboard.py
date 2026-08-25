"""Render site/tape.html — the board and the tape on one self-contained page.

Data is inlined at render time so the page works on GitHub Pages, as a local
file, and as a published artifact. Styled to match site/index.html.
"""

from __future__ import annotations

import html
import json

CHIP = {"fired": "fired", "nearing": "nearing", "clear": "clear", "unknown": "unknown"}

CSS = """
:root{--paper:#EDF0F3;--panel:#fff;--plate:#16202B;--ink:#0F1720;--muted:#5C6B79;--rule:#C8D1DA;--soft:#E1E7EC;
--conn:#1D7A5F;--ai:#3F6DA8;--space:#C4761E;--clear:#516274;--nearing:#C4761E;--fired:#B3352D;--unknown:#8A97A4;
--bull:#1D7A5F;--bear:#C4761E;--neutral:#3F6DA8;--series:#3F6DA8;
--mono:ui-monospace,"SF Mono","Cascadia Mono",Menlo,Consolas,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 var(--sans)}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
.mast{background:var(--plate);color:#DCE4EC}.in{max-width:1000px;margin:0 auto;padding:0 20px}
.mast .in{padding-top:24px;padding-bottom:22px}
.eyebrow{font:10.5px/1 var(--mono);letter-spacing:.22em;text-transform:uppercase;color:#7E93A6}
h1{font:600 26px/1.2 var(--mono);letter-spacing:-.01em;margin:7px 0 5px;color:#F2F6F9}
.lede{margin:0;font-size:13.5px;color:#9FB1C1;max-width:64ch}
.meta{display:flex;flex-wrap:wrap;gap:18px;margin-top:16px;font:11px/1.4 var(--mono);letter-spacing:.06em;color:#8FA3B5}.meta b{color:#DCE4EC}
main{padding-bottom:64px}.sec{margin:34px 0 12px}
.sec h2{font:600 12px/1.4 var(--mono);letter-spacing:.16em;text-transform:uppercase;margin:0 0 4px}
.sec p{margin:0;font-size:13px;color:var(--muted);max-width:72ch}
.warn{background:#FBF3E8;border:1px solid #E6CDA8;border-left:3px solid var(--nearing);padding:11px 14px;font:12px var(--mono);color:#6B4A15;margin:16px 0 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.tile{background:var(--panel);border:1px solid var(--soft);padding:10px 12px}
.tile .k{font:10px/1.3 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.tile .v{font:600 20px/1.2 var(--mono);margin:4px 0 2px;font-variant-numeric:tabular-nums}
.tile .d{font:11px/1.4 var(--mono);color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--soft);padding:12px 14px;margin-bottom:8px}
.chartbox{position:relative}svg{display:block;width:100%;height:auto}
.tip{position:absolute;pointer-events:none;background:var(--plate);color:#DCE4EC;padding:6px 9px;font:11px/1.4 var(--mono);display:none;white-space:nowrap}
.crit{background:var(--panel);border:1px solid var(--soft);border-left:3px solid var(--clear);margin-bottom:6px;padding:9px 13px}
.crit.nearing{border-left-color:var(--nearing)}.crit.fired{border-left-color:var(--fired)}.crit.unknown{border-left-color:var(--unknown);opacity:.85}
.top{display:flex;align-items:baseline;gap:11px}.cid{font:11px var(--mono);color:var(--muted);min-width:28px}
.clabel{flex:1;font-weight:500;font-size:14px}
.chip{font:9.5px/1.6 var(--mono);letter-spacing:.14em;text-transform:uppercase;padding:2px 7px;border-radius:2px;color:#fff;background:var(--clear);white-space:nowrap}
.chip.nearing{background:var(--nearing)}.chip.fired{background:var(--fired)}.chip.unknown{background:var(--unknown)}
.chip.bullish{background:var(--bull)}.chip.bearish{background:var(--bear)}.chip.neutral{background:var(--neutral)}
.detail{font:11.5px var(--mono);color:var(--muted);margin:5px 0 0 39px}
.setup{background:var(--panel);border:1px solid var(--soft);margin-bottom:8px;padding:11px 14px}
.setup .ev{font:11.5px var(--mono);color:var(--muted);margin:6px 0 8px}
.reads{display:grid;grid-template-columns:1fr 1fr;gap:8px 18px}
.reads b{display:block;font:10px/1.4 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin-bottom:2px}
.reads div{font-size:13.5px;color:#33414E}
@media (max-width:640px){.reads{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--soft);vertical-align:top}
th{font:10px/1.4 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:600}
td.m{font:12px var(--mono)}.tw{overflow-x:auto}.active{background:#EEF3F8}
.cal{background:var(--panel);border:1px solid var(--soft);padding:12px 14px;font:12px/1.7 var(--mono);color:var(--muted)}
.nots{background:var(--panel);border:1px dashed var(--rule);padding:12px 18px}.nots li{font-size:13px;color:#33414E;margin-bottom:4px}
footer{margin-top:44px;padding-top:16px;border-top:1px solid var(--rule);font-size:12px;color:var(--muted);max-width:80ch}
a{color:var(--ai)}.small{font-size:12px;color:var(--muted)}
"""

JS = """
(function(){
  const S = window.__TAPE__; const box = document.getElementById('chart'); if(!box) return;
  const data = S.chart; if(!data || data.length < 2){ box.innerHTML='<div class="small">Not enough bars to chart.</div>'; return; }
  const W=1000,H=300,m={t:14,r:54,b:26,l:8};
  const xs=i=>m.l+(W-m.l-m.r)*i/(data.length-1);
  let lo=Math.min(...data.map(d=>d.l)),hi=Math.max(...data.map(d=>d.h));
  const basis=S.position&&S.position.cost_basis; if(basis){lo=Math.min(lo,basis);hi=Math.max(hi,basis);}
  const pad=(hi-lo)*.06; lo-=pad; hi+=pad; const ys=v=>m.t+(H-m.t-m.b)*(1-(v-lo)/(hi-lo));
  let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Daily close, last ${data.length} sessions">`;
  (S.ladder.bands||[]).forEach(b=>{ if(b.high<lo||b.low>hi) return; const y1=ys(Math.min(b.high,hi)),y2=ys(Math.max(b.low,lo));
    svg+=`<rect x="${m.l}" y="${y1}" width="${W-m.l-m.r}" height="${y2-y1}" fill="#3F6DA8" opacity="${b.active?.10:.035}"/>`;
    svg+=`<text x="${m.l+4}" y="${y1+10}" font-size="10" fill="#5C6B79" font-family="monospace">${b.name} ${b.low}–${b.high}</text>`;});
  for(let i=0;i<=5;i++){const v=lo+(hi-lo)*i/5,y=ys(v);
    svg+=`<line x1="${m.l}" x2="${W-m.r}" y1="${y}" y2="${y}" stroke="#E1E7EC"/>`;
    svg+=`<text x="${W-m.r+4}" y="${y+4}" font-size="11" fill="#5C6B79" font-family="monospace">${v.toFixed(0)}</text>`;}
  if(basis){const y=ys(basis);svg+=`<line x1="${m.l}" x2="${W-m.r}" y1="${y}" y2="${y}" stroke="#5C6B79" stroke-dasharray="4 4"/>`;
    svg+=`<text x="${m.l+130}" y="${y-4}" font-size="11" fill="#33414E" font-family="monospace">basis ${basis}</text>`;}
  const path=data.map((d,i)=>`${i?'L':'M'}${xs(i).toFixed(1)},${ys(d.c).toFixed(1)}`).join(' ');
  svg+=`<path d="${path}" fill="none" stroke="#3F6DA8" stroke-width="2" stroke-linejoin="round"/>`;
  const last=data[data.length-1]; svg+=`<circle cx="${xs(data.length-1)}" cy="${ys(last.c)}" r="4" fill="#3F6DA8" stroke="#fff" stroke-width="2"/>`;
  [0,Math.floor(data.length/2),data.length-1].forEach(i=>{svg+=`<text x="${xs(i)}" y="${H-8}" font-size="11" fill="#5C6B79" font-family="monospace" text-anchor="${i===0?'start':i===data.length-1?'end':'middle'}">${data[i].d}</text>`;});
  svg+=`<line id="xh" x1="0" x2="0" y1="${m.t}" y2="${H-m.b}" stroke="#5C6B79" style="display:none"/><circle id="hp" r="5" fill="#3F6DA8" stroke="#fff" stroke-width="2" style="display:none"/>`;
  svg+=`<rect x="${m.l}" y="${m.t}" width="${W-m.l-m.r}" height="${H-m.t-m.b}" fill="transparent" id="hit"/></svg><div class="tip" id="tip"></div>`;
  box.innerHTML=svg;
  const el=box.querySelector('svg'),hit=el.querySelector('#hit'),xh=el.querySelector('#xh'),hp=el.querySelector('#hp'),tip=document.getElementById('tip');
  hit.addEventListener('mousemove',e=>{const r=el.getBoundingClientRect();const px=(e.clientX-r.left)*W/r.width;
    const i=Math.max(0,Math.min(data.length-1,Math.round((px-m.l)/(W-m.l-m.r)*(data.length-1))));const d=data[i];
    xh.setAttribute('x1',xs(i));xh.setAttribute('x2',xs(i));xh.style.display='block';hp.setAttribute('cx',xs(i));hp.setAttribute('cy',ys(d.c));hp.style.display='block';
    const prev=i>0?data[i-1].c:null;const chg=prev?((d.c/prev-1)*100).toFixed(1):null;
    tip.innerHTML=`<b>${d.d}</b><br>close ${d.c.toFixed(2)}${chg!==null?` (${chg>0?'+':''}${chg}%)`:''}<br>range ${d.l.toFixed(2)}–${d.h.toFixed(2)}<br>vol ${(d.v/1e6).toFixed(1)}M`;
    tip.style.display='block';const bx=box.getBoundingClientRect();let tx=e.clientX-bx.left+14;if(tx+170>bx.width)tx=e.clientX-bx.left-180;tip.style.left=tx+'px';tip.style.top=(e.clientY-bx.top-10)+'px';});
  hit.addEventListener('mouseleave',()=>{tip.style.display='none';xh.style.display='none';hp.style.display='none';});
})();
"""


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


def _n(v, nd=2, none="—"):
    try:
        return none if v is None else f"{float(v):,.{nd}f}"
    except (TypeError, ValueError):
        return _e(v)


def _p(v):
    try:
        return "—" if v is None else f"{float(v):+.1f}%"
    except (TypeError, ValueError):
        return "—"


def _crit(e: dict) -> str:
    st = CHIP.get(e.get("status"), "unknown")
    extra = f" · {e['stale_days']}d old" if e.get("stale_days") is not None else ""
    return (f'<div class="crit {st}"><div class="top"><span class="cid">{_e(e["criterion_id"])}</span>'
            f'<span class="clabel">{_e(e["label"])}</span><span class="chip {st}">{st}</span></div>'
            f'<div class="detail">tier {e["tier"]} · {_e(e.get("detail") or "—")}{_e(extra)}</div></div>')


def render(board: dict, tape: dict, full_document: bool = True) -> str:
    t, v, lad, pos, cats, a = (tape["price"], tape["vol"], tape["ladder"], tape["position"], tape["catalysts"],
                               tape["bias_audit"])
    evals = board.get("evaluations", [])
    summ = board.get("summary", {})
    order = {"fired": 0, "nearing": 1, "unknown": 2, "clear": 3}
    evals = sorted(evals, key=lambda e: (order.get(e["status"], 9), e["tier"], e["criterion_id"]))
    regime = next((s["name"].split(": ", 1)[1] for s in tape["setups"] if s["id"] == "REGIME"), "—")
    B: list[str] = []

    B.append('<header class="mast"><div class="in"><div class="eyebrow">Space Exploration Technologies Corp · Nasdaq SPCX</div>'
             '<h1>Range Console · Tape</h1><p class="lede">The criteria board, and what the tape is doing while we wait for it to move. '
             'Every setup below carries a long read and a short read; nothing here is a criterion and nothing here says buy or sell.</p>'
             f'<div class="meta"><span>Board run <b>{_e(board.get("run_date", "—"))}</b></span><span>Tape <b>{_e(t["date"])}</b> via <b>{_e(tape["meta"]["price_source"]["source"])}</b></span>'
             f'<span>Fired <b>{_e(", ".join(summ.get("fired", [])) or "none")}</b></span><span>Nearing <b>{_e(", ".join(summ.get("nearing", [])) or "none")}</b></span>'
             f'<span>Ladder <b>{"PAUSED" if lad["paused"] else "open"}</b></span></div></div></header>')
    B.append('<main class="in">')
    if tape["meta"]["warnings"]:
        B.append('<div class="warn">' + "<br>".join(_e(w) for w in tape["meta"]["warnings"]) + "</div>")

    # tiles
    tiles = [
        ("Close", _n(t["close"]), f'{_p(t.get("chg_1d_pct"))} 1d · {_p(t.get("chg_5d_pct"))} 5d · {_p(t.get("chg_20d_pct"))} 20d'),
        ("From ATH / ATL", _p(t["from_ath_pct"]), f'ATH {t["ath"]} {t["ath_date"]} · ATL {t["atl"]} · {_p(t["from_atl_pct"])} off low'),
        ("ATR20", f'{_n(t.get("atr_pct"), 1)}%/day', f'${_n(t.get("atr"))} · HV10 {_n(t.get("hv10"), 0)} · HV30 {_n(t.get("hv30"), 0)}'),
        ("IV30 vs HV30", f'{_n(v.get("iv30"), 0)} / {_n(v.get("hv30"), 0)}',
         f'spread {_n(v.get("iv_hv_spread"), 0)} · IV rank {_n(v.get("iv_rank"), 0)} ({v.get("iv_history_days")}d{"" if v.get("iv_rank_meaningful") else ", thin"}) · exp move ±{_n(v.get("expected_move_pct"), 1)}%'
         + (" · carried" if v.get("carried") else "")),
        ("Regime", _e(regime), f'RSI {_n(t.get("rsi"), 0)} · SMA20 {_n(t.get("sma20"))} ({_n(t.get("dist_sma20_atr"), 1)} ATR) · SMA50 {_n(t.get("sma50"))}'),
        ("Position", f'{pos["shares"]} sh', f'basis {pos["cost_basis"]} · {_p(pos.get("pnl_pct"))} · {pos["shares_to_target"]} to 100'),
    ]
    B.append('<div class="sec"><h2>Tape</h2><p>Context only. Volatility is explicitly not a criterion.</p></div><div class="tiles">'
             + "".join(f'<div class="tile"><div class="k">{_e(k)}</div><div class="v">{_e(val)}</div><div class="d">{_e(d)}</div></div>' for k, val, d in tiles) + "</div>")
    B.append('<div class="sec"><h2>Daily close · ladder bands shaded · dashed = cost basis</h2></div><div class="panel chartbox"><div id="chart"></div></div>')

    # catalysts
    B.append('<div class="sec"><h2>Catalysts</h2><p>Date confidence is about the date, not the event.</p></div><div class="cal">')
    if cats["upcoming"]:
        B.append("<br>".join(f'T-{c["days"]}d · {_e(c["date"])} · {_e(c["event"])} · {_e(c["confidence"])}' + (f' · tests {_e(", ".join(c["tests"]))}' if c.get("tests") else "") for c in cats["upcoming"]))
    else:
        B.append(f'nothing inside {cats["lookahead_days"]} days')
    B.append('<br><span class="small">horizon: ' + " · ".join(f'{_e(c["date"])} {_e(c["event"][:48])}' for c in cats["horizon"][:6]) + "</span></div>")

    # setups
    B.append('<div class="sec"><h2>Setups present — both readings, no side taken</h2><p>The direction chip is a label for the bias audit, not a view.</p></div>')
    real = [s for s in tape["setups"] if s["id"] != "REGIME"]
    if not real:
        B.append('<div class="panel small">None. Nothing stretched, nothing broke out, no catalyst in window. That is a reading too.</div>')
    for s in real:
        B.append(f'<div class="setup"><div class="top"><span class="cid">{_e(s["id"])}</span><span class="clabel">{_e(s["name"])}</span>'
                 f'<span class="chip {s["direction"]}">{s["direction"]} · {s["strength"]}/3</span></div><div class="ev">{_e(s["evidence"])}'
                 + (f' · {_e(s["caveat"])}' if s.get("caveat") else "") + '</div>'
                 f'<div class="reads"><div><b>Long read</b>{_e(s["long_read"])}</div><div><b>Short read</b>{_e(s["short_read"])}</div></div></div>')
    B.append(f'<div class="small">Bias audit, trailing {a["window_days"]}d: {a["bullish"]} bullish-labelled vs {a["bearish"]} bearish-labelled setups · skew {a["skew"]:+.2f} (0 = balanced).</div>')

    # board
    B.append('<div class="sec"><h2>Conditions that would break the long case</h2><p>Tier 1 is structural — one is enough. Tier 2 is damaging; two at once pauses the ladder.</p></div>')
    B.extend(_crit(e) for e in evals if e.get("case") == "long")
    B.append('<div class="sec"><h2>Conditions that would break the short case</h2><p>The symmetric half. Each is falsifiable too.</p></div>')
    B.extend(_crit(e) for e in evals if e.get("case") == "short")

    # ladder
    B.append(f'<div class="sec"><h2>Accumulation ladder</h2><p>{_e(lad["message"])}</p></div><div class="panel">')
    if lad["paused"]:
        B.append(f'<div class="warn" style="margin:0 0 10px">{_e(lad["pause_reason"])}</div>')
    if not lad["budget_set"]:
        B.append('<div class="small">No total budget set in config/tape.yaml — bands are aspirational until funded.</div>')
    B.append('<div class="tw"><table><thead><tr><th>Band</th><th>Range</th><th>Planned</th><th>Fills</th><th>Gate</th><th>Note</th></tr></thead><tbody>')
    for b in lad["bands"]:
        B.append(f'<tr class="{"active" if b["active"] else ""}"><td class="m">{_e(b["name"])}{" ◀" if b["active"] else ""}</td><td class="m">{b["low"]}–{b["high"]}</td>'
                 f'<td class="m">{b["planned_shares"] or "unfunded"}</td><td class="m">{b["fills"]}</td><td class="m">{"criteria check" if b["gated"] else "—"}</td><td class="small">{_e(b.get("note") or "")}</td></tr>')
    B.append("</tbody></table></div><ul class='small'>" + "".join(f"<li>{_e(r)}</li>" for r in lad["rules"]) + "</ul></div>")

    # noise + unresolved
    B.append('<div class="sec"><h2>Not signal</h2><p>Written down in advance so a loud news cycle cannot promote itself.</p></div><div class="nots"><ul>'
             + "".join(f"<li>{_e(n)}</li>" for n in tape.get("noise", [])) + "</ul></div>")
    if board.get("unresolved"):
        B.append('<div class="sec"><h2>Unresolved</h2><p>The research backlog. Each pass attempts one.</p></div><div class="nots"><ul>'
                 + "".join(f'<li><span class="cid">{_e(q.get("id"))}</span> {_e(q.get("text"))}</li>' for q in board["unresolved"]) + "</ul></div>")

    B.append(f'<footer>{_e(tape["meta"]["disclaimer"])} · tape run {_e(tape["meta"]["run_at"])} · criteria v{_e(board.get("criteria_version", "—"))}. '
             'Manual states are only as fresh as their as-of dates; <code>spcx check</code> says when they have aged out.</footer></main>')

    payload = json.dumps({"chart": tape["chart"], "ladder": {"bands": lad["bands"]}, "position": pos}, default=str)
    body = f"<style>{CSS}</style>\n" + "\n".join(B) + f"\n<script>window.__TAPE__={payload};</script>\n<script>{JS}</script>\n"
    if not full_document:
        return "<title>SPCX Range Console</title>\n" + body
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>SPCX Range Console · Tape</title></head><body>' + body + "</body></html>")
