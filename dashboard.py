#!/usr/bin/env python3
"""Build the interactive StockScan dashboard (self-contained HTML).

Reads whatever exists in output/: scan_*.json, paper_book_*.json,
replay_stats.json, miss_analysis.json, plus data/backtest_stats_india.json.
Usage: python3 dashboard.py [--date YYYY-MM-DD]
"""
import argparse
import json
import os
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")


def load(path):
    p = os.path.join(ROOT, path)
    return json.load(open(p)) if os.path.exists(p) else None


def build_payload(day):
    payload = {"date": day, "scans": {}, "papers": {}}
    for prof, suf in (("conservative", ""), ("balanced", "_balanced")):
        payload["scans"][prof] = {m: load(f"output/scan_{m}_{day}{suf}.json") for m in ("india", "us")}
        payload["papers"][prof] = {m: load(f"output/paper_book_{m}{suf}.json") for m in ("india", "us")}
    payload["replay"] = load("output/replay_stats.json") or load("data/replay_stats.json")
    payload["miss"] = load("output/miss_analysis.json") or load("data/miss_analysis.json")
    payload["timing"] = load("data/backtest_stats_india.json")
    return payload


TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StockScan Dashboard</title>
<style>
:root { color-scheme: light;
  --surface:#fcfcfb; --page:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --border:rgba(11,11,11,0.10); --series:#2a78d6;
  --good:#0ca30c; --goodtext:#006300; --serious:#ec835a; --critical:#d03b3b; --warning:#fab219; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark;
  --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --border:rgba(255,255,255,0.10); --series:#3987e5; --goodtext:#0ca30c; } }
*{box-sizing:border-box} body{margin:0;background:var(--page);color:var(--ink);
 font:14.5px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;padding:22px;}
h1{font-size:21px;margin:0} h2{font-size:16px;margin:26px 0 10px} h3{font-size:14px;margin:14px 0 6px;color:var(--ink2)}
.sub{color:var(--ink2);font-size:12.5px;margin:4px 0 16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.tile .v{font-size:24px;font-weight:650;margin-top:2px} .tile .l{font-size:12px;color:var(--ink2)}
.tile .s{font-size:11.5px;color:var(--muted)}
.seg{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden;margin:0 8px 0 0}
.seg button{border:0;background:var(--surface);color:var(--ink2);padding:6px 14px;font:600 12.5px system-ui;cursor:pointer}
.seg button.on{background:var(--series);color:#fff}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin-top:10px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--grid);font-variant-numeric:tabular-nums}
th:first-child,td:first-child{text-align:left} th{color:var(--ink2);font-weight:600}
td:first-child{font-weight:600}
.pos{color:var(--goodtext);font-weight:600}.neg{color:var(--critical);font-weight:600}
.chartrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px}
svg text{font:11.5px system-ui;fill:var(--ink2)} svg .val{font-weight:600;fill:var(--ink)}
.tip{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--border);
 border-radius:6px;padding:4px 8px;font-size:12px;color:var(--ink);display:none;z-index:9;box-shadow:0 2px 8px rgba(0,0,0,.15)}
.flash{animation:pulse 1.6s ease-in-out infinite;border-color:var(--critical)}
.flash-good{animation:pulseg 1.8s ease-in-out infinite;border-color:var(--good)}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(208,59,59,.35)}50%{box-shadow:0 0 0 6px rgba(208,59,59,0)}}
@keyframes pulseg{0%,100%{box-shadow:0 0 0 0 rgba(12,163,12,.35)}50%{box-shadow:0 0 0 6px rgba(12,163,12,0)}}
.badge{display:inline-block;font-size:11px;border-radius:99px;padding:2px 9px;margin-left:6px;border:1px solid var(--border);color:var(--ink2)}
.badge.ok{background:var(--good);color:#fff;border-color:var(--good)}
.badge.no{color:var(--muted)}
.disc{margin-top:24px;font-size:11.5px;color:var(--muted);max-width:920px}
.legend{font-size:11.5px;color:var(--ink2);margin:4px 0}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 10px;vertical-align:-1px}
</style></head><body>
<h1>StockScan — Advisory Dashboard</h1>
<div class="sub" id="sub"></div>
<div class="tiles" id="tiles"></div>

<h2>Today's signals</h2>
<div><span class="seg" id="segProf"></span><span class="seg" id="segMkt"></span></div>
<div class="card" id="signals"></div>

<h2>Paper-trading book</h2>
<div class="card" id="paper"></div>

<h2>Success ratio — simulated replay, last ~14 months, both markets</h2>
<div class="legend">Outcome share of closed trades:
 <i style="background:var(--good)"></i>target hit <i style="background:var(--grid)"></i>stale exit
 <i style="background:var(--critical)"></i>stopped</div>
<div class="chartrow"><div class="card" id="chOutcome"></div><div class="card" id="chFamily"></div></div>

<h2>Miss analysis <span class="badge" id="missBadge"></span></h2>
<div class="card" id="missSummary"></div>
<div class="chartrow"><div class="card" id="chBuckets"></div><div class="card" id="missRules"></div></div>

<div class="disc"><strong>How to read R:</strong> 1R = the amount risked on one trade (entry − stop). A +2.5R win
makes 2.5× what a full stop loses. <strong>Disclaimer:</strong> automated technical scanner for personal study;
simulated results; not investment advice, not SEBI-registered research.</div>
<div class="tip" id="tip"></div>
<script>
const DATA = __PAYLOAD__;
let prof = 'conservative', mkt = 'india';
const $ = id => document.getElementById(id);
const fmt = (v,c) => c + Number(v).toLocaleString();
const pct = v => Math.round(v*100) + '%';
const tip = $('tip');
function showTip(e, html){ tip.innerHTML = html; tip.style.display='block';
  tip.style.left = Math.min(e.clientX+12, innerWidth-180)+'px'; tip.style.top = (e.clientY+12)+'px'; }
function hideTip(){ tip.style.display='none'; }

function seg(el, opts, cur, cb){ el.innerHTML='';
  opts.forEach(([k,l])=>{ const b=document.createElement('button'); b.textContent=l;
    if(k===cur) b.className='on'; b.onclick=()=>cb(k); el.appendChild(b); }); }

function tiles(){
  const s = DATA.scans, t = [];
  const cnt = p => ['india','us'].reduce((a,m)=> a + ((s[p][m]||{}).signals||[]).filter(x=>!x.watch).length, 0);
  const watchCnt = ['india','us'].reduce((a,m)=> a + ((s.balanced[m]||{}).signals||[]).filter(x=>x.watch).length, 0);
  const pb = DATA.papers.conservative, agg = {pend:0, open:0, closed:0, r:0, wins:0};
  ['india','us'].forEach(m=>{ const b=pb[m]; if(!b) return; agg.pend+=b.pending.length;
    agg.open+=b.open.length; agg.closed+=b.closed.length;
    b.closed.forEach(c=>{ agg.r+=c.r_multiple; if(c.r_multiple>0) agg.wins++; }); });
  const rep = (DATA.replay||{}).profiles||{};
  t.push(['Conservative signals', cnt('conservative'), 'today, actionable']);
  t.push(['Balanced signals', cnt('balanced'), watchCnt + ' more on watch']);
  t.push(['Paper: awaiting entry', agg.pend, 'conservative book']);
  t.push(['Paper: open', agg.open, 'positions']);
  t.push(['Paper: closed', agg.closed, agg.closed? pct(agg.wins/agg.closed)+' wins, '+agg.r.toFixed(1)+'R total' : 'no trades closed yet']);
  if(rep.conservative) t.push(['Replay expectancy', (rep.conservative.avg_r>=0?'+':'')+rep.conservative.avg_r+'R', 'per trade, conservative']);
  $('tiles').innerHTML = t.map(x=>`<div class="tile"><div class="l">${x[0]}</div><div class="v">${x[1]}</div><div class="s">${x[2]}</div></div>`).join('');
}

function signalsTable(){
  const scan = (DATA.scans[prof]||{})[mkt];
  if(!scan){ $('signals').innerHTML = '<span class="sub">No scan for this selection.</span>'; return; }
  const rows = (scan.signals||[]);
  const act = rows.filter(r=>!r.watch), watch = rows.filter(r=>r.watch);
  const tbl = (list) => list.length ? '<table><thead><tr><th>Symbol</th><th>Pattern</th><th>Conf.</th><th>Entry</th><th>Stop</th><th>Target</th><th>R:R</th><th>Vol</th><th>RSI</th></tr></thead><tbody>' +
    list.map(r=>`<tr><td>${r.symbol}</td><td>${r.pattern}</td><td>${r.confidence}</td><td>${fmt(r.entry,r.currency)}</td><td>${fmt(r.stop_loss,r.currency)} (−${r.stop_pct}%)</td><td>${fmt(r.target,r.currency)} (+${r.target_pct}%)</td><td>1:${r.risk_reward}</td><td>${r.vol_ratio||''}×</td><td>${r.rsi}</td></tr>`).join('') +
    '</tbody></table>' : '<div class="sub">None today.</div>';
  $('signals').innerHTML =
    `<div class="sub">Scanned ${scan.universe_size} stocks · data through ${(rows[0]||{}).date||scan.scan_date} · profile: ${prof}</div>` +
    '<h3>Actionable — buy only above entry (GTT order)</h3>' + tbl(act) +
    (prof==='balanced' ? '<h3>Watchlist — forming, NOT yet a trade</h3>' + tbl(watch) : '');
}

function paperTable(){
  const b = (DATA.papers[prof]||{})[mkt];
  if(!b){ $('paper').innerHTML='<span class="sub">No paper book for this selection.</span>'; return; }
  const s = b.stats||{};
  const recentMiss = (b.closed||[]).filter(c=>c.result==='stopped').slice(-3);
  const head = `<div class="sub">Since ${b.since} · profile: ${prof} · ${mkt.toUpperCase()} · ` +
    (s.trades? `${s.trades} closed · ${pct(s.win_rate)} wins · total <span class="${s.total_r>=0?'pos':'neg'}">${s.total_r>=0?'+':''}${s.total_r}R</span>` : 'no closed trades yet') + '</div>';
  const tbl=(list,cols,labs)=> list.length? '<table><thead><tr>'+labs.map(l=>'<th>'+l+'</th>').join('')+'</tr></thead><tbody>'+
    list.map(r=>'<tr'+((r.result==='stopped' && recentMiss.includes(r))?' class="flash"':'')+'>'+cols.map(c=>{
      let v = r[c]===undefined?'':r[c];
      if(c==='r_multiple'||c==='unrealized_r') v = `<span class="${v>=0?'pos':'neg'}">${v>=0?'+':''}${v}R</span>`;
      return '<td>'+v+'</td>';}).join('')+'</tr>').join('')+'</tbody></table>' : '';
  $('paper').innerHTML = head +
    (b.pending.length? '<h3>Awaiting entry ('+b.pending.length+')</h3>'+tbl(b.pending,['symbol','pattern','signal_date','entry','stop_loss','target','sessions_left'],['Symbol','Pattern','Signal','Entry','Stop','Target','Sessions left']):'') +
    (b.open.length? '<h3>Open ('+b.open.length+')</h3>'+tbl(b.open,['symbol','entered','entry','current','unrealized_r','unrealized_pct','sessions_held'],['Symbol','Entered','Entry','Now','Unreal.','%','Sessions']):'') +
    (b.closed.length? '<h3>Closed ('+b.closed.length+')</h3>'+tbl(b.closed,['symbol','entered','exit_date','result','r_multiple','pnl_pct','sessions_held'],['Symbol','Entered','Exited','Result','R','P&L %','Sessions']):'') +
    (!b.pending.length && !b.open.length && !b.closed.length ? '<div class="sub">Book is empty.</div>':'');
}

function stackedOutcomes(){
  const rep=(DATA.replay||{}).profiles; if(!rep){$('chOutcome').innerHTML='<span class="sub">Run analysis.py for replay stats.</span>';return;}
  const W=340,BH=26,G=48; let svg=`<svg viewBox="0 0 ${W} ${2*G+16}" width="100%">`;
  ['conservative','balanced'].forEach((p,i)=>{
    const o=rep[p].outcomes, n=o.target+o.stopped+o.stale; if(!n) return;
    const y=i*G+18; let x=0;
    svg+=`<text x="0" y="${y-5}">${p} · ${rep[p].closed} closed · ${pct(rep[p].win_rate)} wins · ${rep[p].total_r>=0?'+':''}${rep[p].total_r}R</text>`;
    [['target','var(--good)'],['stale','var(--grid)'],['stopped','var(--critical)']].forEach(([k,c])=>{
      const w=(W-2)*o[k]/n;
      svg+=`<rect x="${x}" y="${y}" width="${Math.max(w-2,0)}" height="${BH}" rx="3" fill="${c}"
        data-t="${p}: ${k} ${o[k]}/${n} (${pct(o[k]/n)})"></rect>`;
      if(w>34) svg+=`<text class="val" x="${x+5}" y="${y+17}" fill="${k==='stale'?'var(--ink)':'#fff'}" style="fill:${k==='stale'?'var(--ink)':'#fff'}">${pct(o[k]/n)}</text>`;
      x+=w;});
  });
  $('chOutcome').innerHTML='<h3>Outcomes by profile</h3>'+svg+'</svg>';
}

function familyChart(){
  const rep=(DATA.replay||{}).profiles; if(!rep){$('chFamily').innerHTML='';return;}
  const fams=Object.keys(rep.conservative.by_family||{});
  const rows=[]; fams.forEach(f=>{ ['conservative','balanced'].forEach(p=>{
    const s=(rep[p].by_family||{})[f]; if(s&&s.closed) rows.push({f,p,wr:s.win_rate,r:s.total_r,n:s.closed}); }); });
  const W=330,BH=15,GAP=4; const H=fams.length*(14+2*(BH+GAP)+8)+10;
  let y=4,svg=`<svg viewBox="0 0 ${W} ${H+6}" width="100%">`;
  fams.forEach(f=>{ svg+=`<text x="0" y="${y+10}">${f}</text>`; y+=14;
    ['conservative','balanced'].forEach(p=>{ const r=rows.find(x=>x.f===f&&x.p===p); if(!r) return;
      const w=(W-118)*r.wr; const col = p==='conservative'?'var(--series)':'#eb6834';
      svg+=`<rect x="100" y="${y}" width="${Math.max(w,2)}" height="${BH}" rx="3" fill="${col}" data-t="${f} · ${p}: win rate ${pct(r.wr)} over ${r.n} trades, total ${r.r>=0?'+':''}${r.r}R"></rect>
      <text x="${104+w}" y="${y+11}">${pct(r.wr)} · <tspan class="val" style="fill:${r.r>=0?'var(--goodtext)':'var(--critical)'}">${r.r>=0?'+':''}${r.r}R</tspan></text>`;
      y+=BH+GAP; }); y+=6; });
  $('chFamily').innerHTML='<h3>Win rate & total R by pattern</h3><div class="legend"><i style="background:var(--series)"></i>conservative <i style="background:#eb6834"></i>balanced</div>'+svg+'</svg>';
}

function missPanels(){
  const m=DATA.miss; if(!m){$('missSummary').innerHTML='<span class="sub">Run analysis.py.</span>';return;}
  const s=m.sample, vf=m.validated_feedback||[];
  $('missBadge').textContent = vf.length? vf.length+' validated finding'+(vf.length>1?'s':'') : 'no validated changes';
  $('missBadge').className = 'badge ' + (vf.length? 'ok':'no');
  const fc=m.factor_compare;
  const flat = Object.entries(fc).every(([k,v])=> v.missed!==null && Math.abs(v.missed-v.won) < Math.max(0.6, Math.abs(v.won)*0.06));
  $('missSummary').innerHTML =
    `<div class="sub">Sample: ${s.closed} closed simulated trades — ${s.stopped} stopped (misses), ${s.target} hit target, ${s.stale} stale exits. Generated ${m.generated}.</div>` +
    '<table><thead><tr><th>Factor at entry</th><th>Missed trades (avg)</th><th>Winning trades (avg)</th></tr></thead><tbody>' +
    Object.entries(fc).map(([k,v])=>`<tr><td>${k}</td><td>${v.missed}</td><td>${v.won}</td></tr>`).join('') +
    '</tbody></table>' +
    (flat? '<div class="sub" style="margin-top:8px"><strong>Honest reading:</strong> misses and winners look nearly identical at entry — no single entry factor predicts failure. The edge must come from pattern selection and exit rules, not tighter entry filters (the rule tests below confirm this).</div>':'');
  const b=m.buckets, W=330; let svg='',y=4;
  const H = Object.values(b).reduce((a,l)=>a+l.length,0)*19 + Object.keys(b).length*16+10;
  svg=`<svg viewBox="0 0 ${W} ${H}" width="100%">`;
  Object.entries(b).forEach(([k,list])=>{ if(!list.length) return;
    svg+=`<text x="0" y="${y+10}" class="val">${k}</text>`; y+=15;
    list.forEach(r=>{ const w=(W-210)*r.win_rate;
      svg+=`<text x="0" y="${y+10}">${r.bucket}</text><rect x="158" y="${y}" width="${Math.max(w,2)}" height="12" rx="3" fill="var(--series)" data-t="${r.bucket}: ${pct(r.win_rate)} wins, avg ${r.avg_r>=0?'+':''}${r.avg_r}R (${r.n} trades)"></rect><text x="${164+w}" y="${y+10}">${pct(r.win_rate)}</text>`;
      y+=19; }); y+=6; });
  $('chBuckets').innerHTML='<h3>Win rate by entry condition</h3>'+svg+'</svg>';
  $('missRules').innerHTML='<h3>Candidate rule changes — tested against history</h3>'+
    (m.rules||[]).map(r=>`<div class="card ${r.validated?'flash-good':''}" style="margin-top:8px">
      <strong>${r.description}</strong> <span class="badge ${r.validated?'ok':'no'}">${r.validated?'VALIDATED — adopt':'rejected'}</span>
      <div class="sub" style="margin:6px 0 0">Keeps ${r.filtered.trades}/${r.baseline.trades} trades · win rate ${pct(r.baseline.win_rate)} → ${pct(r.filtered.win_rate)} · total R ${r.baseline.total_r} → ${r.filtered.total_r} (<span class="${r.r_improvement>=0?'pos':'neg'}">${r.r_improvement>=0?'+':''}${r.r_improvement}R</span>)</div></div>`).join('');
}

function render(){
  $('sub').textContent = DATA.date + ' · conservative + balanced risk profiles · India (NSE) & US (S&P 500) · updated each trading morning';
  seg($('segProf'), [['conservative','Conservative'],['balanced','Balanced']], prof, k=>{prof=k;render();});
  seg($('segMkt'), [['india','India'],['us','US']], mkt, k=>{mkt=k;render();});
  tiles(); signalsTable(); paperTable(); stackedOutcomes(); familyChart(); missPanels();
  document.querySelectorAll('rect[data-t]').forEach(r=>{
    r.addEventListener('mousemove',e=>showTip(e,r.dataset.t));
    r.addEventListener('mouseleave',hideTip);});
}
render();
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=str(date.today()))
    args = ap.parse_args()
    payload = build_payload(args.date)
    html = TEMPLATE.replace("__PAYLOAD__", json.dumps(payload))
    out = os.path.join(OUT, "dashboard.html")
    with open(out, "w") as f:
        f.write(html)
    print(out)


if __name__ == "__main__":
    main()
