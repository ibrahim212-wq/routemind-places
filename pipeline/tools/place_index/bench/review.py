"""The benchmark's review sheet: one self-contained HTML page to judge the answers by eye.

Summary first (every group × every index: Hit@1 / Hit@5 for named places and chains, P@5 for
category queries), then every query with each index's top five side by side, the judge's mark on
each row, and a link to the place on openstreetmap.org to check it. Filters: group, style,
misses only, free text.
"""
from __future__ import annotations

import html
import json

from .. import taxonomy as T

SRC_NAMES = [(1, "OSM"), (2, "ATP"), (4, "FSQ"), (8, "MS"), (16, "Meta"), (32, "Ovt"), (64, "Div"), (128, "WD"), (256, "GN")]

GROUP_LABELS = {
    "fuel": "Fuel (colloquial)", "pharmacy": "Pharmacy", "hospital": "Hospitals", "cafe": "Cafés",
    "restaurant": "Restaurants", "money": "Banks & ATMs", "worship": "Mosques & churches", "grocery": "Groceries",
    "services": "Services", "car": "Car services", "government": "Government", "education": "Education",
    "transport": "Transport", "mall": "Malls", "shopping": "Shops", "health": "Health", "lodging": "Hotels",
    "leisure": "Leisure", "along_route": "Along the route", "near_dest": "Near destination",
    "in_area": "In an area", "chain": "Chains", "landmark": "Landmarks", "small_local": "Small local places",
    "street": "Streets", "area": "Areas & villages", "far": "Far lookups",
}

CSS = """
:root{
  /* Layout: a sticky filter bar over a summary matrix, then one card per query with the indexes side by side. */
  --bg:#F4F6F9;--surface:#FFFFFF;--ink:#0A1428;--muted:#5A6478;--line:#DCE1E9;--accent:#0B7590;
  --good:#1D7448;--good-bg:#E3F3EA;--bad:#AF3329;--bad-bg:#FBE9E7;--chip:#EAF0F6;
  --f-body:"IBM Plex Sans Arabic","IBM Plex Sans","Segoe UI",Tahoma,sans-serif;
  --f-mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#0A1428;--surface:#101C34;--ink:#E7ECF5;--muted:#9AA4BA;--line:#24324F;--accent:#4BC0DD;
  --good:#5BCB91;--good-bg:#12352A;--bad:#F2847A;--bad-bg:#3A1C1F;--chip:#172645;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0A1428;--surface:#101C34;--ink:#E7ECF5;--muted:#9AA4BA;--line:#24324F;--accent:#4BC0DD;
  --good:#5BCB91;--good-bg:#12352A;--bad:#F2847A;--bad-bg:#3A1C1F;--chip:#172645;color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--f-body);font-size:14px;line-height:1.45;margin:0}
.wrap{max-width:1280px;margin:0 auto;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:20px 48px}
h1{font-size:24px;margin:0 0 4px;text-wrap:balance;font-weight:700}
h2{font-size:16px;margin:28px 0 10px;font-weight:600}
.sub{color:var(--muted);margin:0 0 16px;max-width:72ch}
.num{font-family:var(--f-mono);font-variant-numeric:tabular-nums}
.bar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);display:flex;flex-wrap:wrap;gap:8px;padding-block:10px;border-bottom:1px solid var(--line)}
.bar select,.bar input{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:6px 8px;min-width:0}
.bar input[type=search]{flex:1 1 180px}
.bar label{display:flex;align-items:center;gap:6px;color:var(--muted)}
.bar .count{margin-inline-start:auto;color:var(--muted);align-self:center}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.tablebox{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--surface)}
table{border-collapse:collapse;width:100%;min-width:560px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:start;white-space:nowrap}
th{font-weight:600;color:var(--muted);font-size:12px;letter-spacing:.02em}
tr:last-child td{border-bottom:0}
td.metric{font-family:var(--f-mono);font-variant-numeric:tabular-nums}
.lo{color:var(--bad)}.hi{color:var(--good)}
.cards{display:flex;flex-direction:column;gap:12px;margin-top:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px 14px;min-width:0}
.qhead{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 12px}
.qtext{font-size:18px;font-weight:600}
.chip{background:var(--chip);color:var(--muted);border-radius:999px;padding:1px 8px;font-size:12px}
.expect{color:var(--muted);font-size:13px;margin-top:4px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-top:10px}
.col{min-width:0}
.colhead{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:4px;margin-bottom:4px}
.verdict{font-weight:700}
.verdict.ok{color:var(--good)}.verdict.no{color:var(--bad)}
ol{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:3px}
li{display:grid;grid-template-columns:18px 1fr auto;gap:6px;align-items:start;padding:3px 4px;border-radius:5px}
li.ok{background:var(--good-bg)}
li .mark{font-weight:700;text-align:center}
li.ok .mark{color:var(--good)}
li .nm{min-width:0;overflow-wrap:anywhere}
li .nm a{color:inherit;text-decoration:none;border-bottom:1px dotted var(--line)}
li .nm a:hover{border-bottom-color:var(--accent)}
li .meta{color:var(--muted);font-size:12px}
li .d{font-family:var(--f-mono);font-variant-numeric:tabular-nums;color:var(--muted);font-size:12px}
.empty{color:var(--muted);font-style:italic;padding:4px}
a.map{color:var(--accent)}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
"""

JS = """
const D = JSON.parse(document.getElementById('data').textContent);
const S = D.sources, CAT = D.cats, GL = D.groups;
const $ = s => document.querySelector(s);
function pct(x){ return x==null ? '–' : Math.round(x*100)+'%'; }
function cls(x){ return x==null ? '' : x>=0.8 ? 'hi' : x<0.5 ? 'lo' : ''; }
function srcs(b){ return D.srcnames.filter(([bit])=>b&bit).map(([,n])=>n).join('·'); }
function km(m){ return m==null ? '' : m<1000 ? m+' m' : (m/1000).toFixed(m<10000?1:0)+' km'; }
function summary(){
  const order = ['ALL','ALL:place','ALL:cat','ALL:brand'].concat(Object.keys(GL).filter(g=>D.summary[g]));
  const head = '<tr><th>Group</th><th>n</th>' + S.map(s=>`<th>${s} · Hit@1</th><th>${s} · Hit@5</th><th>${s} · P@5</th>`).join('') + '</tr>';
  const rows = order.map(g=>{
    const r = D.summary[g]; if(!r) return '';
    const label = g==='ALL'?'All queries':g==='ALL:place'?'Named places':g==='ALL:cat'?'Category queries':g==='ALL:brand'?'Chains':(GL[g]||g);
    return `<tr><td>${label}</td><td class="metric">${r[S[0]].n}</td>` + S.map(s=>{const v=r[s];
      return `<td class="metric ${cls(v.hit1)}">${pct(v.hit1)}</td><td class="metric ${cls(v.hit5)}">${pct(v.hit5)}</td><td class="metric ${cls(v.p5)}">${pct(v.p5)}</td>`}).join('') + '</tr>';
  }).join('');
  $('#summary').innerHTML = `<table><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  const styles = Object.keys(D.summary).filter(k=>k.startsWith('style:'));
  $('#styles').innerHTML = `<table><thead><tr><th>Spelling style</th><th>n</th>${S.map(s=>`<th>${s} · Hit@1</th><th>${s} · Hit@5</th>`).join('')}</tr></thead><tbody>` +
    styles.map(k=>{const r=D.summary[k]; return `<tr><td>${k.slice(6)}</td><td class="metric">${r[S[0]].n}</td>`+S.map(s=>`<td class="metric ${cls(r[s].hit1)}">${pct(r[s].hit1)}</td><td class="metric ${cls(r[s].hit5)}">${pct(r[s].hit5)}</td>`).join('')+'</tr>'}).join('') + '</tbody></table>';
}
function expectText(r){
  const e = r.expect;
  if(r.type==='place') return `Target: ${e.names.slice(0,3).join(' / ')} · within ${km(e.r)} of <a class="map" target="_blank" rel="noopener" href="https://www.openstreetmap.org/?mlat=${e.near[0]}&mlon=${e.near[1]}#map=15/${e.near[0]}/${e.near[1]}">${e.near[0].toFixed(4)}, ${e.near[1].toFixed(4)}</a>`;
  const where = r.route ? 'of the route '+r.route : r.dest ? 'of the destination' : 'of the user';
  const orc = r.oracle_m==null ? 'no index knows one in range' : 'nearest known: '+km(r.oracle_m);
  if(r.type==='cat') return `Category: ${(CAT[e.scat]||[e.scat])[1]||e.scat} within ${e.km} km ${where} · ${orc}`;
  return `Chain: ${e.names.slice(0,3).join(' / ')} within ${e.km} km · ${orc}`;
}
function card(r){
  const cols = S.map(s=>{
    const j = r.by[s], res = r.res[s];
    const ok = j.rank!=null;
    const v = r.type==='place' ? (ok ? 'hit at #'+j.rank : 'miss') : (ok ? `#${j.rank} right · ${j.ok.filter(Boolean).length}/5` : 'miss');
    const items = res.length ? res.map((x,k)=>{
      const nm = x.n_ar && x.n_en && x.n_ar!==x.n_en ? `${x.n_ar} <span class="meta">· ${x.n_en}</span>` : (x.n_ar||x.n_en||'—');
      const c = CAT[x.cat]; const lab = c ? (c[0]+' · '+c[1]) : x.cat;
      return `<li class="${x.ok?'ok':''}"><span class="mark">${x.ok?'✓':k+1}</span><span class="nm"><a target="_blank" rel="noopener" href="https://www.openstreetmap.org/?mlat=${x.lat}&mlon=${x.lng}#map=18/${x.lat}/${x.lng}" dir="auto">${nm}</a><br><span class="meta">${lab} · ${srcs(x.src)}</span></span><span class="d">${km(x.d)}</span></li>`;
    }).join('') : '<li class="empty">no results</li>';
    return `<div class="col"><div class="colhead"><span>${s} <span class="num">${j.ms} ms</span></span><span class="verdict ${ok?'ok':'no'}">${v}</span></div><ol>${items}</ol></div>`;
  }).join('');
  return `<article class="card" data-g="${r.g}" data-s="${r.s}"><div class="qhead"><span class="qtext" dir="auto">${r.q}</span><span class="chip">${GL[r.g]||r.g}</span><span class="chip">${r.s}</span><span class="chip">from ${r.at} · ${r.gov}</span></div><div class="expect">${expectText(r)}</div><div class="cols">${cols}</div></article>`;
}
function render(){
  const g = $('#fg').value, st = $('#fs').value, miss = $('#fm').value, t = $('#ft').value.trim().toLowerCase();
  const rows = D.rows.filter(r=>(!g||r.g===g)&&(!st||r.s===st)&&(!t||r.q.toLowerCase().includes(t)) &&
    (!miss || (miss==='any' ? S.some(s=>r.by[s].rank==null) : r.by[miss] && r.by[miss].rank==null)));
  $('#cards').innerHTML = rows.map(card).join('');
  $('#count').textContent = rows.length + ' of ' + D.rows.length + ' queries';
}
function init(){
  const gs = [...new Set(D.rows.map(r=>r.g))];
  $('#fg').innerHTML = '<option value="">All groups</option>' + gs.map(g=>`<option value="${g}">${GL[g]||g}</option>`).join('');
  const ss = [...new Set(D.rows.map(r=>r.s))];
  $('#fs').innerHTML = '<option value="">All styles</option>' + ss.map(s=>`<option value="${s}">${s}</option>`).join('');
  $('#fm').innerHTML = '<option value="">All answers</option><option value="any">Missed by any index</option>' + S.map(s=>`<option value="${s}">Missed by ${s}</option>`).join('');
  ['#fg','#fs','#fm'].forEach(id=>$(id).addEventListener('change',render));
  $('#ft').addEventListener('input',render);
  summary(); render();
}
init();
"""


def write(path: str, sources: list[str], rows: list[dict], summary: dict, meta: dict) -> None:
    cats = {c.id: [c.ar, c.en] for c in T.CATS}
    data = {"sources": sources, "rows": rows, "summary": summary, "cats": cats, "groups": GROUP_LABELS,
            "srcnames": SRC_NAMES, "meta": meta}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    n = len(rows)
    versions = ", ".join(f"{k} {v}" for k, v in meta.items())
    page = f"""<title>Egypt Place Search Review</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+Arabic:wght@400;600;700&display=swap">
<style>{CSS}</style>
<div class="wrap">
<h1>Egypt Place Search Review</h1>
<p class="sub">{n} real queries from all 27 governorates, answered by each index with the on-device engine. A ✓ marks an answer the judge accepted: the named place within its radius, or the right category or chain inside the query's distance. Tap a name to check it on OpenStreetMap. Indexes: {html.escape(versions)}.</p>
<h2>Results by group</h2>
<div class="tablebox" id="summary"></div>
<h2>Results by spelling style</h2>
<div class="tablebox" id="styles"></div>
<h2>Every query</h2>
<div class="bar">
<select id="fg" aria-label="Group"></select>
<select id="fs" aria-label="Style"></select>
<select id="fm" aria-label="Misses"></select>
<input id="ft" type="search" placeholder="Find a query" aria-label="Find a query">
<span class="count" id="count"></span>
</div>
<div class="cards" id="cards"></div>
</div>
<script id="data" type="application/json">{blob}</script>
<script>{JS}</script>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
