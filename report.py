#!/usr/bin/env python3
"""Build the daily advisory report (self-contained HTML) from scan JSON."""
import argparse
import html
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import data  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")

CSS = """
:root { color-scheme: light;
  --surface:#fcfcfb; --page:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --border:rgba(11,11,11,0.10); --series:#2a78d6;
  --good:#0ca30c; --goodtext:#006300; --critical:#d03b3b; --warning:#fab219; }
@media (prefers-color-scheme: dark) { :root {
  color-scheme: dark;
  --surface:#1a1a19; --page:#0d0d0d; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --border:rgba(255,255,255,0.10); --series:#3987e5;
  --good:#0ca30c; --goodtext:#0ca30c; --critical:#d03b3b; --warning:#fab219; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--page); color:var(--ink);
  font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; padding:24px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:28px 0 10px; }
.sub { color:var(--ink2); font-size:13px; margin-bottom:18px; }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); gap:14px; }
.card { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:16px; }
.card h3 { margin:0; font-size:17px; display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; }
.chip { font-size:11.5px; color:var(--ink2); border:1px solid var(--border);
  border-radius:99px; padding:2px 9px; white-space:nowrap; }
.conf { margin-left:auto; font-size:12px; color:var(--ink2); }
.rows { display:grid; grid-template-columns:1fr 1fr; gap:4px 16px; margin-top:10px; font-size:13.5px; }
.rows div { display:flex; justify-content:space-between; border-bottom:1px dashed var(--grid); padding:2px 0; }
.rows span:first-child { color:var(--ink2); }
.rows .num { font-variant-numeric:tabular-nums; }
.k-entry { font-weight:600; }
.k-stop span.num::before { content:"⛔ "; } .k-target span.num::before { content:"🎯 "; }
.note { font-size:12.5px; color:var(--ink2); margin-top:10px; }
.spark { margin-top:10px; position:relative; }
.spark svg { display:block; width:100%; height:72px; }
.tip { position:absolute; pointer-events:none; background:var(--surface); border:1px solid var(--border);
  border-radius:6px; padding:2px 7px; font-size:11.5px; color:var(--ink2); display:none; white-space:nowrap; }
table { border-collapse:collapse; width:100%; background:var(--surface);
  border:1px solid var(--border); border-radius:10px; font-size:13px; }
th,td { text-align:right; padding:7px 10px; border-bottom:1px solid var(--grid);
  font-variant-numeric:tabular-nums; }
th:first-child,td:first-child { text-align:left; }
th { color:var(--ink2); font-weight:600; }
.disc { margin-top:26px; font-size:12px; color:var(--muted); max-width:900px; }
.empty { background:var(--surface); border:1px solid var(--border); border-radius:10px;
  padding:22px; color:var(--ink2); font-size:14px; }
.meta { font-size:12px; color:var(--muted); margin-top:8px; }
"""

JS = """
function spark(el){
  const d=JSON.parse(el.dataset.series), svg=el.querySelector('svg'),
        tip=el.querySelector('.tip'), W=svg.viewBox.baseVal.width, H=svg.viewBox.baseVal.height;
  const lo=Math.min(...d.map(p=>p[1])), hi=Math.max(...d.map(p=>p[1])), pad=4;
  const X=i=>pad+i*(W-2*pad)/(d.length-1), Y=v=>H-pad-(v-lo)*(H-2*pad)/(hi-lo||1);
  svg.addEventListener('mousemove',e=>{
    const r=svg.getBoundingClientRect(), i=Math.max(0,Math.min(d.length-1,
      Math.round((e.clientX-r.left)/r.width*(d.length-1))));
    const cur=svg.querySelector('.cursor'); cur.setAttribute('cx',X(i)); cur.setAttribute('cy',Y(d[i][1]));
    cur.style.display='';
    tip.style.display='block'; tip.textContent=d[i][0]+'  '+d[i][1];
    tip.style.left=Math.min(e.clientX-r.left+10, r.width-110)+'px'; tip.style.top='0px';
  });
  svg.addEventListener('mouseleave',()=>{ tip.style.display='none';
    svg.querySelector('.cursor').style.display='none'; });
}
document.querySelectorAll('.spark').forEach(spark);
"""


def sparkline_svg(series, entry, stop, target):
    lo = min(min(v for _, v in series), stop)
    hi = max(max(v for _, v in series), target)
    W, H, pad = 340, 72, 4
    def X(i): return pad + i * (W - 2 * pad) / (len(series) - 1)
    def Y(v): return H - pad - (v - lo) * (H - 2 * pad) / (hi - lo or 1)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(series))
    def hline(v, color, dash):
        return (f'<line x1="0" x2="{W}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" '
                f'stroke="{color}" stroke-width="1" stroke-dasharray="{dash}" opacity="0.8"/>')
    return (
        f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" aria-label="6-month closing-price sparkline">'
        f'{hline(target, "var(--good)", "4 3")}{hline(stop, "var(--critical)", "4 3")}'
        f'<polyline points="{pts}" fill="none" stroke="var(--series)" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle class="cursor" r="3.5" fill="var(--series)" stroke="var(--surface)" '
        f'stroke-width="2" style="display:none"/></svg>'
    )


def pattern_family(name):
    if "base breakout" in name:
        return "base breakout"
    if "-high breakout" in name:
        return "55d/52w-high breakout"
    if "bull-flag" in name:
        return "bull-flag pullback"
    return None


def timing_note(sig):
    if sig.get("breakeven_trigger"):
        return ('<div class="note">Exit rules (validated 2026-08-03 study): historically ~66-69% of these '
                'setups end in profit or at breakeven under the 1.5R-target + stop-to-entry rule; most '
                'resolve within ~4 weeks. If still open after ~40 sessions, exit.</div>')
    p = os.path.join(ROOT, "data", f"backtest_stats_{sig['market']}.json")
    if not os.path.exists(p):
        return ""
    stats = json.load(open(p)).get("by_pattern", {}).get(pattern_family(sig["pattern"]))
    if not stats or not stats.get("median_sessions_to_target"):
        return ""
    return (f'<div class="note">History of this pattern (backtest): typically ~'
            f'{int(stats["median_sessions_to_70pct"])} sessions to cover 70% of the move, ~'
            f'{int(stats["median_sessions_to_target"])} to target. If neither stop nor target '
            f'is hit after ~{int(stats["p75_sessions_to_target"])} sessions, the setup is stale — '
            f'consider exiting.</div>')


def card(sig, series):
    c = sig["currency"]
    f = lambda v: f"{c}{v:,}"
    be_row = ""
    if sig.get("breakeven_trigger"):
        be_row = (f'<div><span>Move stop to entry at</span>'
                  f'<span class="num">{f(sig["breakeven_trigger"])}</span></div>')
    sup = f'{f(sig["support"])} (touched {sig["support_strength"]}×)' if sig["support"] else "—"
    res = f(sig["resistance"]) if sig["resistance"] else "blue sky (at highs)"
    sdata = json.dumps([[d, v] for d, v in series])
    return f"""
<div class="card">
  <h3>{html.escape(sig["symbol"])} <span class="chip">{html.escape(sig["pattern"])}</span>
      <span class="conf">confidence {sig["confidence"]}/100</span></h3>
  <div class="spark" data-series='{html.escape(sdata)}'>{sparkline_svg(series, sig["entry"], sig["stop_loss"], sig["target"])}<div class="tip"></div></div>
  <div class="rows">
    <div class="k-entry"><span>Entry (buy above)</span><span class="num">{f(sig["entry"])}</span></div>
    <div><span>Friday close</span><span class="num">{f(sig["close"])}</span></div>
    <div class="k-stop"><span>Stop loss</span><span class="num">{f(sig["stop_loss"])} (−{sig["stop_pct"]}%)</span></div>
    <div class="k-target"><span>Target</span><span class="num">{f(sig["target"])} (+{sig["target_pct"]}%)</span></div>
    {be_row}
    <div><span>Risk : reward</span><span class="num">1 : {sig["risk_reward"]}</span></div>
    <div><span>Breakout volume</span><span class="num">{sig["vol_ratio"]}× average</span></div>
    <div><span>Support below</span><span class="num">{sup}</span></div>
    <div><span>Next resistance</span><span class="num">{res}</span></div>
    <div><span>RSI-14</span><span class="num">{sig["rsi"]}</span></div>
    <div><span>From 52-week high</span><span class="num">−{sig["pct_from_52w_high"]}%</span></div>
  </div>
  <div class="note">{html.escape(sig["note"])}</div>
  {timing_note(sig)}
</div>"""


def table(sigs):
    rows = "".join(
        f'<tr><td>{s["symbol"]}</td><td>{html.escape(s["pattern"])}</td>'
        f'<td>{s["currency"]}{s["entry"]:,}</td><td>{s["currency"]}{s["stop_loss"]:,}</td>'
        f'<td>{s["currency"]}{s["target"]:,}</td><td>1:{s["risk_reward"]}</td>'
        f'<td>{s["confidence"]}</td></tr>'
        for s in sigs)
    return ('<table><thead><tr><th>Symbol</th><th>Pattern</th><th>Entry</th><th>Stop</th>'
            f'<th>Target</th><th>R:R</th><th>Conf.</th></tr></thead><tbody>{rows}</tbody></table>')


def section(scan):
    name = "India — NSE (Nifty 500 universe)" if scan["market"] == "india" else "US — S&P 500"
    sigs = scan["signals"]
    skips = sum(scan["data_quality_skips"].values())
    body = ""
    if not sigs:
        body = ('<div class="empty">No conservative setups today. The scan ran, the market simply '
                "didn't offer a clean high-probability breakout — sitting out is a position too.</div>")
    else:
        cards = ""
        for s in sigs:
            df = data.load_history(scan["market"], s["symbol"])
            series = [(str(d.date()), round(float(v), 2)) for d, v in df["Close"].tail(126).items()]
            cards += card(s, series)
        body = f'<div class="cards">{cards}</div><h2>Summary table</h2>{table(sigs)}'
    meta = (f'<div class="meta">Scanned {scan["universe_size"]} stocks · data through {sigs[0]["date"] if sigs else scan["scan_date"]} · '
            f'{skips} excluded by data-quality/liquidity gates</div>')
    return f'<h2>{name}</h2>{meta}{body}'


def balanced_section(market, day):
    p = os.path.join(OUT, f"scan_{market}_{day}_balanced.json")
    if not os.path.exists(p):
        return ""
    scan = json.load(open(p))
    name = "India" if market == "india" else "US"
    cons_p = os.path.join(OUT, f"scan_{market}_{day}.json")
    cons_syms = {s["symbol"] for s in json.load(open(cons_p))["signals"]} if os.path.exists(cons_p) else set()
    act = [s for s in scan["signals"] if not s.get("watch") and s["symbol"] not in cons_syms]
    watch = [s for s in scan["signals"] if s.get("watch")]
    head = (f'<h2>Balanced risk — additional ideas, {name} <span style="font-weight:400;color:var(--ink2);'
            f'font-size:13px">(looser filters: volume ≥1.25×, stops to 8%, RR ≥ 1:1.5 — take smaller positions)</span></h2>')
    parts = [head]
    if act:
        parts.append(table(act))
    else:
        parts.append('<div class="meta">No additional actionable balanced setups beyond the conservative list.</div>')
    if watch:
        rows = "".join(
            f'<tr><td>{s["symbol"]}</td><td>{html.escape(s["pattern"])}</td>'
            f'<td>{s["currency"]}{s["entry"]:,}</td><td>{s["currency"]}{s["stop_loss"]:,}</td>'
            f'<td>{s["currency"]}{s["target"]:,}</td><td>{s["confidence"]}</td></tr>' for s in watch)
        parts.append('<h2 style="font-size:15px">Watchlist — forming setups (NOT yet trades)</h2>'
                     '<table><thead><tr><th>Symbol</th><th>Pattern</th><th>Becomes a buy above</th>'
                     f'<th>Then stop</th><th>Then target</th><th>Conf.</th></tr></thead><tbody>{rows}</tbody></table>')
    return "".join(parts)


def paper_section(market, profile="conservative"):
    suffix = "" if profile == "conservative" else f"_{profile}"
    p = os.path.join(OUT, f"paper_book_{market}{suffix}.json")
    if not os.path.exists(p):
        return ""
    b = json.load(open(p))
    name = "India" if market == "india" else "US"
    s = b["stats"]
    head = (f'<h2>Paper-trading book ({profile}) — {name} <span style="font-weight:400;color:var(--ink2);'
            f'font-size:13px">(since {b["since"]}, simulated with standard rules)</span></h2>')
    if s.get("trades"):
        stats = (f'<div class="meta">Closed trades: {s["trades"]} · win rate {int(s["win_rate"]*100)}% · '
                 f'average {s["avg_r"]:+.2f}R · total {s["total_r"]:+.2f}R '
                 f'(R = one unit of risk; at ₹1,000 risked per trade, total ≈ ₹{int(s["total_r"]*1000):+,})</div>')
    else:
        stats = '<div class="meta">No closed trades yet.</div>'
    def tbl(rows, cols, labels):
        if not rows:
            return ""
        body = "".join("<tr>" + "".join(f"<td>{r.get(c, '')}</td>" for c in cols) + "</tr>" for r in rows)
        return ("<table><thead><tr>" + "".join(f"<th>{l}</th>" for l in labels) +
                f"</tr></thead><tbody>{body}</tbody></table>")
    parts = [head, stats]
    if b["pending"]:
        parts.append("<h3>Awaiting entry trigger</h3>" + tbl(
            b["pending"], ["symbol", "pattern", "signal_date", "entry", "stop_loss", "target", "sessions_left"],
            ["Symbol", "Pattern", "Signal", "Entry", "Stop", "Target", "Sessions left"]))
    if b["open"]:
        parts.append("<h3>Open positions</h3>" + tbl(
            b["open"], ["symbol", "entered", "entry", "current", "unrealized_r", "unrealized_pct", "sessions_held"],
            ["Symbol", "Entered", "Entry", "Now", "Unreal. R", "Unreal. %", "Sessions"]))
    if b["closed"]:
        parts.append("<h3>Closed trades</h3>" + tbl(
            b["closed"], ["symbol", "entered", "exit_date", "result", "r_multiple", "pnl_pct", "sessions_held"],
            ["Symbol", "Entered", "Exited", "Result", "R", "P&L %", "Sessions"]))
    if b["expired_untriggered"]:
        parts.append(f'<div class="meta">{b["expired_untriggered"]} signal(s) expired without triggering — no trade, no loss.</div>')
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=str(date.today()))
    ap.add_argument("--markets", default="india,us")
    args = ap.parse_args()

    sections = []
    for m in args.markets.split(","):
        p = os.path.join(OUT, f"scan_{m}_{args.date}.json")
        if os.path.exists(p):
            sections.append(section(json.load(open(p))))
    for m in args.markets.split(","):
        sections.append(balanced_section(m, args.date))
    for m in args.markets.split(","):
        sections.append(paper_section(m, "conservative"))
        sections.append(paper_section(m, "balanced"))
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Swing Scan — {args.date}</title><style>{CSS}</style></head><body>
<h1>Daily Swing Scan</h1>
<div class="sub">{args.date} · conservative setups only: confirmed breakouts, volume-backed, risk:reward ≥ 1:2</div>
{"".join(sections)}
<div class="disc"><strong>How to read this:</strong> every idea is conditional — nothing is a buy at market.
Place a trigger (GTT) order at the entry with the stop-loss attached; if the entry never triggers, no trade.
Risk no more than 1–2% of capital per position. <strong>Disclaimer:</strong> generated by an automated
technical scanner for personal study; not investment advice, not SEBI-registered research. Markets can and
do invalidate any pattern.</div>
<script>{JS}</script></body></html>"""
    out = os.path.join(OUT, f"swing_report_{args.date}.html")
    with open(out, "w") as fp:
        fp.write(doc)
    print(out)


if __name__ == "__main__":
    main()
