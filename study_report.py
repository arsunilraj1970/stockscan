#!/usr/bin/env python3
"""Consolidated 90-session walk-forward study report (self-contained HTML)."""
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
S = json.load(open(os.path.join(OUT, "study.json")))

CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--border:rgba(11,11,11,.10);--series:#2a78d6;--good:#0ca30c;--goodtext:#006300;
--critical:#d03b3b;--warning:#fab219;}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--surface:#1a1a19;--page:#0d0d0d;--ink:#fff;
--ink2:#c3c2b7;--grid:#2c2c2a;--border:rgba(255,255,255,.10);--series:#3987e5;--goodtext:#0ca30c;}}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:14.5px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:24px;max-width:1080px}
h1{font-size:21px;margin:0}h2{font-size:16.5px;margin:28px 0 8px}
.sub{color:var(--ink2);font-size:12.5px;margin:4px 0 14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.tile .v{font-size:22px;font-weight:650}.tile .l{font-size:12px;color:var(--ink2)}.tile .s{font-size:11.5px;color:var(--muted)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin-top:10px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{text-align:right;padding:5px 8px;border-bottom:1px solid var(--grid);font-variant-numeric:tabular-nums}
th:first-child,td:first-child{text-align:left}th{color:var(--ink2);font-weight:600}
.pos{color:var(--goodtext);font-weight:600}.neg{color:var(--critical);font-weight:600}
.rec{border:1.5px solid var(--good);animation:pg 1.8s infinite}
@keyframes pg{0%,100%{box-shadow:0 0 0 0 rgba(12,163,12,.3)}50%{box-shadow:0 0 0 7px rgba(12,163,12,0)}}
svg text{font:11px system-ui;fill:var(--ink2)}
details{margin-top:8px}summary{cursor:pointer;color:var(--series);font-size:13px}
.disc{margin-top:24px;font-size:11.5px;color:var(--muted)}
.badge{font-size:11px;border-radius:99px;padding:2px 9px;border:1px solid var(--border);color:var(--ink2)}
.badge.ok{background:var(--good);color:#fff;border-color:var(--good)}
"""


def line_chart(points, w=980, h=180, ref=None):
    if not points:
        return ""
    xs = list(range(len(points)))
    ys = [p[1] for p in points]
    lo, hi = min(ys + [0]), max(ys + [0])
    pad = 26
    def X(i): return pad + i * (w - 2 * pad) / max(len(xs) - 1, 1)
    def Y(v): return h - 22 - (v - lo) * (h - 44) / (hi - lo or 1)
    poly = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    zero = f'<line x1="{pad}" x2="{w-pad}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="var(--grid)"/>'
    labels = (f'<text x="{pad}" y="{h-6}">{points[0][0]}</text>'
              f'<text x="{w-140}" y="{h-6}">{points[-1][0]}</text>'
              f'<text x="4" y="{Y(hi)+4:.1f}">{hi:+.0f}R</text><text x="4" y="{Y(lo):.1f}">{lo:+.0f}R</text>')
    return (f'<svg viewBox="0 0 {w} {h}" width="100%">{zero}'
            f'<polyline points="{poly}" fill="none" stroke="var(--series)" stroke-width="2"/>{labels}</svg>')


def target_chart(curve, w=520, h=210):
    pad = 40
    def X(k): return pad + (k - 0.5) * (w - 2 * pad) / 2.0
    def Y(v): return h - 30 - v * (h - 60)
    pts = " ".join(f"{X(c['target']):.0f},{Y(c['win_rate']):.0f}" for c in curve)
    ref = f'<line x1="{pad}" x2="{w-10}" y1="{Y(.6):.0f}" y2="{Y(.6):.0f}" stroke="var(--warning)" stroke-dasharray="5 4"/><text x="{w-115}" y="{Y(.6)-5:.0f}">60% success line</text>'
    dots = "".join(
        f'<circle cx="{X(c["target"]):.0f}" cy="{Y(c["win_rate"]):.0f}" r="4" fill="var(--series)"/>'
        f'<text x="{X(c["target"])-12:.0f}" y="{Y(c["win_rate"])-10:.0f}">{round(c["win_rate"]*100)}%</text>'
        f'<text x="{X(c["target"])-14:.0f}" y="{h-8}">{c["target"]}R</text>'
        f'<text x="{X(c["target"])-16:.0f}" y="{Y(c["win_rate"])+18:.0f}" style="fill:{"var(--goodtext)" if c["expectancy_r"]>0 else "var(--critical)"}">{c["expectancy_r"]:+.2f}</text>'
        for c in curve)
    return (f'<svg viewBox="0 0 {w} {h}" width="100%">{ref}'
            f'<polyline points="{pts}" fill="none" stroke="var(--series)" stroke-width="2"/>{dots}'
            f'<text x="{pad}" y="14">Win rate vs target size (label under dot = expectancy R/trade after costs)</text></svg>')


def weekly_table(days):
    weeks = defaultdict(lambda: {"signals": 0, "triggered": 0, "resolved": 0, "wins": 0, "r": 0.0})
    for d in days:
        wk = d["date"][:7] + "-w" + str((int(d["date"][8:10]) - 1) // 7 + 1)
        w = weeks[wk]
        for k in ("signals", "triggered", "resolved", "wins"):
            w[k] += d[k]
        w["r"] += d["r"]
    rows = "".join(
        f'<tr><td>{k}</td><td>{v["signals"]}</td><td>{v["triggered"]}</td><td>{v["resolved"]}</td>'
        f'<td>{v["wins"]}</td><td class="{"pos" if v["r"]>=0 else "neg"}">{v["r"]:+.1f}R</td></tr>'
        for k, v in sorted(weeks.items()))
    return ('<table><thead><tr><th>Week</th><th>Signals</th><th>Triggered</th><th>Resolved</th>'
            f'<th>Wins</th><th>R (closed)</th></tr></thead><tbody>{rows}</tbody></table>')


def daily_table(days):
    rows = "".join(
        f'<tr><td>{d["date"]}</td><td>{d["signals"]}</td><td>{d["triggered"]}</td>'
        f'<td>{d["resolved"]}</td><td>{d["wins"]}</td>'
        f'<td class="{"pos" if d["r"]>=0 else "neg"}">{d["r"]:+.1f}</td></tr>'
        for d in days if d["signals"])
    return ('<details><summary>Show every day (days with signals)</summary><table><thead><tr>'
            '<th>Date</th><th>Signals</th><th>Triggered</th><th>Resolved</th><th>Wins</th><th>R</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></details>')


def variants_table(variants, rec_key):
    rows = ""
    for v in variants[:9]:
        key = (v["filter"], v["target"], v["breakeven_at"])
        star = key == rec_key
        style = ' style="font-weight:650"' if star else ""
        rows += (f'<tr{style}><td>{"→ " if star else ""}Target {v["target"]}R'
                 f'{", stop→breakeven at +" + str(v["breakeven_at"]) + "R" if v["breakeven_at"] else ""}</td>'
                 f'<td>{v["filter"].replace("_", " ")}</td><td>{v["n"]}</td>'
                 f'<td>{round(v["success_rate"]*100)}%</td><td>{round(v["win_rate"]*100)}%</td>'
                 f'<td class="{"pos" if v["expectancy_r"]>0 else "neg"}">{v["expectancy_r"]:+.3f}R</td></tr>')
    return ('<table><thead><tr><th>Exit strategy</th><th>Filter</th><th>Trades</th>'
            '<th>Success (no-loss)</th><th>Strict win</th><th>Expectancy/trade</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


ws = S["window_summary"]
wv = {("all", 2.5, None): None, ("all", 1.5, 0.5): None, ("no_base_breakout", 1.5, 0.5): None}
for v in S["window_variants"]:
    wv[(v["filter"], v["target"], v["breakeven_at"])] = v
rec_win = wv[("no_base_breakout", 1.5, 0.5)]
curve_pts = [(c["date"], c["cum_r"]) for c in S["equity_curve"]]

html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StockScan — 90-Session Study</title><style>{CSS}</style></head><body>
<h1>90-Session Walk-Forward Study &amp; Success-Improvement Analysis</h1>
<div class="sub">Signal window {S["window_start"]} → {S["window_end"]} · both markets · conservative engine ·
generated {S["generated"]} · {S["note_costs"]}</div>

<div class="tiles">
<div class="tile"><div class="l">Signals in window</div><div class="v">{sum(d["signals"] for d in S["walkforward_daily"])}</div><div class="s">{sum(d["triggered"] for d in S["walkforward_daily"])} triggered</div></div>
<div class="tile"><div class="l">Current rules — success</div><div class="v">{round(ws["win_rate"]*100)}%</div><div class="s">{ws["wins"]} of {ws["n"]} resolved; {ws["unresolved"]} still open</div></div>
<div class="tile"><div class="l">Current rules — result</div><div class="v neg">{sum(d["r"] for d in S["walkforward_daily"]):+.0f}R</div><div class="s">closed trades, window</div></div>
<div class="tile rec"><div class="l">Re-engineered exits — success</div><div class="v pos">{round(rec_win["success_rate"]*100)}%</div><div class="s">same window, same signals</div></div>
<div class="tile rec"><div class="l">Re-engineered — expectancy</div><div class="v pos">{rec_win["expectancy_r"]:+.2f}R</div><div class="s">per trade, after costs</div></div>
</div>

<h2>Equity curve — current rules, window trades (by exit date)</h2>
<div class="card">{line_chart(curve_pts)}
<div class="sub">This window was hostile: repeated stop-outs with few 2.5R winners. Two honest caveats:
(1) losses resolve faster than wins (the stop is nearer than the target), so a recent window undercounts
wins still in progress — {ws["unresolved"]} trades are open; (2) even allowing for that, the window
underperforms the 14-month average (29% → 24% resolved win rate). Pattern quality was uniformly weak:
bull-flags {round(S["window_by_family"].get("bull-flag",{}).get("win_rate",0)*100)}%,
high breakouts {round(S["window_by_family"].get("high breakout",{}).get("win_rate",0)*100)}%,
base breakouts {round(S["window_by_family"].get("base breakout",{}).get("win_rate",0)*100)}% of resolved trades.</div></div>

<h2>Daily results, consolidated weekly</h2>
<div class="card">{weekly_table(S["walkforward_daily"])}{daily_table(S["walkforward_daily"])}</div>

<h2>Miss analysis — why the success ratio is low, and what actually fixes it</h2>
<div class="card">
<p style="margin:4px 0">The misses are not entry mistakes: winners and losers look nearly identical on every
entry-day factor (earlier analysis), and no entry filter tested improves results except dropping the
base-breakout pattern. The real problem is the <strong>exit geometry</strong>: a 2.5R target sits far away while
the stop sits close, so price must travel a long way flawlessly. Most trades that die at the stop had
already been profitable first — their gains were simply never protected. That is an exit problem, not a
selection problem.</p>
<p style="margin:10px 0 4px"><strong>Win rate vs target size</strong> — shrinking the target raises the hit
rate, but a &gt;60% strict win rate only appears at targets ≤0.75R where expectancy dies after costs.
The dashed line is your 60% goal:</p>
{target_chart(S["target_curve"])}
<p style="margin:10px 0 4px">The route to &gt;60% <em>with</em> positive expectancy is protecting profits:
<strong>take the target at 1.5R and move the stop to breakeven once the trade is +0.5R</strong>. Then a trade
has three endings — full win (+1.5R), harmless scratch (≈0R), or full loss (−1R) — and the no-loss rate
clears 60% while expectancy improves ~20-fold over the current rules:</p>
{variants_table(S["variants"], ("no_base_breakout", 1.5, 0.5))}
</div>

<h2>Validation in the hostile window</h2>
<div class="card rec">
<p style="margin:4px 0">The decisive test: apply the recommended rules to the <em>same 90 hostile sessions</em>
above, same signals, no hindsight in selection:</p>
<table><thead><tr><th>Rules</th><th>Success (no-loss)</th><th>Strict win</th><th>Expectancy/trade</th></tr></thead>
<tbody>
<tr><td>Current (2.5R target, fixed stop)</td><td>{round(wv[("all",2.5,None)]["success_rate"]*100)}%</td><td>{round(wv[("all",2.5,None)]["win_rate"]*100)}%</td><td class="neg">{wv[("all",2.5,None)]["expectancy_r"]:+.3f}R</td></tr>
<tr><td>Recommended (1.5R target, BE at +0.5R)</td><td>{round(wv[("all",1.5,.5)]["success_rate"]*100)}%</td><td>{round(wv[("all",1.5,.5)]["win_rate"]*100)}%</td><td class="pos">{wv[("all",1.5,.5)]["expectancy_r"]:+.3f}R</td></tr>
<tr style="font-weight:650"><td>→ Recommended + drop base breakouts</td><td>{round(rec_win["success_rate"]*100)}%</td><td>{round(rec_win["win_rate"]*100)}%</td><td class="pos">{rec_win["expectancy_r"]:+.3f}R</td></tr>
</tbody></table>
<p class="sub" style="margin:8px 0 0">A strategy that stays profitable in the worst stretch of the year is a
far stronger claim than one that shines on average. Breadth-based market filters were also tested and
<strong>rejected</strong> — they reduced total profit.</p></div>

<h2>Recommendation <span class="badge ok">validated on {S["full_sample"]["triggered"]} trades + hostile-window check</span></h2>
<div class="card">
<ol style="margin:4px 0 4px 18px;padding:0">
<li><strong>Change exits:</strong> target 1.5R; once a trade reaches +0.5R, move the stop-loss to the entry price
(Groww GTT orders can be modified — this is one manual adjustment per trade).</li>
<li><strong>Drop the base-breakout pattern</strong> from the conservative engine (negative in every test).</li>
<li><strong>Keep entries unchanged</strong> — tighter entry filters were tested and made results worse.</li>
</ol>
<div class="sub">Definitions kept honest: "success" = trades ending in profit or breakeven (capital preserved) —
{round(rec_win["success_rate"]*100)}% in the hostile window, 69% over 14 months. The strict hit-the-target rate is
{round(rec_win["win_rate"]*100)}% / 44% respectively; no exit scheme reaches a 60% strict win rate with meaningful
profit after costs. Scratches assume entry-price fills; real fills may slip slightly.</div></div>

<div class="disc"><strong>Disclaimer:</strong> simulated results on historical data; automated personal study tool;
not investment advice, not SEBI-registered research. Past patterns do not guarantee future results.</div>
</body></html>"""

path = os.path.join(OUT, "study_report.html")
open(path, "w").write(html)
print(path)
