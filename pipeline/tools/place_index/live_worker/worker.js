// RouteMind live place search — a Cloudflare Worker in front of the live place providers
// (docs/place-search-2026-10.md §7, docs/search-goal.md "Smart live fallback").
//
// The app's own index answers first, on the phone. This is the ONLINE fallback the app asks only when its own answer
// is weak, or when the user kept typing past strong results without tapping one (the app's LiveGate decides — this
// Worker never does). Every provider key lives ONLY here, as a Worker secret; the phone never sees one.
//
//   GET /suggest?q=&lat=&lon=&lang=ar|en&limit=&reason=weak|kept&surface=phone|aa|carplay|sekka
//       → {provider, paid, attribution:{provider, name}, cache_s, results:[{id, name, address, lat, lng, category, type, dist}]}
//       the cheapest LIST endpoint of the provider the rotation picks (HERE Autosuggest, Huawei Place Suggestion,
//       TomTom typeahead search). `id` is "<provider>.<the provider's own id>".
//   GET /details?id=<provider>.<id>&lang=  → {provider, attribution, cache_s, place:{… + phone, url, hours}}
//       only when the user TAPS a provider row; always the provider that produced the row.
//   GET /search?…  the first version's route (TomTom, bare ids) — kept for the app builds already installed.
//   GET /usage    (header x-admin = ADMIN_TOKEN) → this month's calls per provider, the free quotas, the cost so far.
//   GET /misses   (header x-admin = ADMIN_TOKEN) → the miss log: a normalised query + a 0.05° cell + counts, and how
//       often a provider found anything. Never a provider's data, never a user or device id.
//
// ROTATION: the free quotas first, in LIVE_ORDER (default huawei, here, tomtom); a provider without a key is skipped.
// When every free quota of the month is spent, the CHEAPEST provider with a known price carries on (prices in
// PROVIDERS, the month's cost in /usage). A provider that refuses (401 / 403 / 429 / a quota code) is skipped by this
// isolate for the rest of the month, and the next one in line answers the same request.
//
// STORAGE: the D1 binding LIVE_DB (optional; Settings → Bindings → D1). Two tables, created on first use: `usage`
// (month, provider, kind, n) and `misses` (month, q, cell, reason, surface, n, found). Without the binding the rotation
// counts in each isolate's memory only. Provider answers are passed through and NEVER stored here.

const EG = { minLat: 21.5, maxLat: 31.9, minLon: 24.5, maxLon: 37.1 };
const SAFETY = 0.95;            // a free quota counts as spent at 95 % (isolates read the shared count with up to 30 s lag)
const COUNTS_TTL_MS = 30_000;   // how long an isolate trusts its last reading of the month's counts
const TIMEOUT_MS = 2_500;       // one provider's budget; a second provider may answer within the same request
const MIN_Q = 3;                // never before the 3rd typed character (the app holds the same rule)
const MISS_RETAIN_MONTHS = 3;

// Free calls a month, US$ per 1,000 beyond them (list / details; 0 = unknown, never chosen to PAY), the attribution the
// list shows, and how long the phone may keep a repeated query's answer in MEMORY (s; 0 = never). Sources and dates:
// docs/search-war-room.md "Live providers — terms and prices (2026-11-09)". Each is overridable per deployment with a
// variable FREE_<P> / PRICE_<P> / DPRICE_<P> / CACHE_<P> (e.g. FREE_HUAWEI = 140000 once the console shows the coupon).
//   huawei  Place Suggestion US$2 / 1,000, Place Details US$12 / 1,000; the US$300 monthly coupon is not assumed until
//           the owner sees it in the console (individual accounts: unconfirmed). Terms on caching: unconfirmed → 0.
//   here    30,000 / month (third-party 2026 readings; HERE's own rate table did not render), ~US$0.88 / 1,000 after
//           the 2026-04-01 +6 %; Platform Terms §6.4(j): results cached ≤ 30 days → a short memory is allowed.
//   tomtom  the previous-generation Search API: 2,500 / month free (docs.tomtom.com/pricing); the price per 1,000 did
//           not render → 0 (never chosen to pay); caching terms unconfirmed → 0.
const PROVIDERS = {
  huawei: { free: 0, price: 2.0, detailsPrice: 12.0, cache_s: 0, attribution: { ar: "Petal Maps", en: "Petal Maps" } },
  here: { free: 30000, price: 0.88, detailsPrice: 0.88, cache_s: 600, attribution: { ar: "HERE", en: "HERE" } },
  tomtom: { free: 2500, price: 0, detailsPrice: 0, cache_s: 0, attribution: { ar: "TomTom", en: "TomTom" } },
};
const KEY_OF = { huawei: "HUAWEI_API_KEY", here: "HERE_API_KEY", tomtom: "TOMTOM_API_KEY" };

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function month(now = new Date()) {
  return now.toISOString().slice(0, 7);
}

function conf(env, p) {
  const base = PROVIDERS[p];
  const num = (name, d) => {
    const raw = env[`${name}_${p.toUpperCase()}`];
    const v = Number(raw);
    return raw !== undefined && raw !== "" && Number.isFinite(v) ? v : d;
  };
  return { ...base, free: num("FREE", base.free), price: num("PRICE", base.price),
    detailsPrice: num("DPRICE", base.detailsPrice), cache_s: num("CACHE", base.cache_s) };
}

function order(env) {
  return String(env.LIVE_ORDER || "huawei,here,tomtom").split(",").map((s) => s.trim())
    .filter((p) => PROVIDERS[p] && env[KEY_OF[p]]);
}

// ── the month's counts: D1 when bound, else this isolate's memory ──────────────────────────────────────────────────
const mem = { month: "", counts: {}, at: 0, refused: {}, schema: false };

async function schema(env) {
  if (!env.LIVE_DB || mem.schema) return;
  await env.LIVE_DB.batch([
    env.LIVE_DB.prepare("CREATE TABLE IF NOT EXISTS usage (month TEXT, provider TEXT, kind TEXT, n INTEGER, " +
      "PRIMARY KEY (month, provider, kind))"),
    env.LIVE_DB.prepare("CREATE TABLE IF NOT EXISTS misses (month TEXT, q TEXT, cell TEXT, reason TEXT, surface TEXT, " +
      "n INTEGER, found INTEGER, PRIMARY KEY (month, q, cell, reason, surface))"),
  ]);
  mem.schema = true;
}

function rollMonth() {
  const m = month();
  if (mem.month !== m) Object.assign(mem, { month: m, counts: {}, at: 0, refused: {} });
  return m;
}

async function counts(env) {
  const m = rollMonth();
  if (!env.LIVE_DB || Date.now() - mem.at < COUNTS_TTL_MS) return mem.counts;
  try {
    await schema(env);
    const r = await env.LIVE_DB.prepare("SELECT provider, kind, n FROM usage WHERE month = ?").bind(m).all();
    const c = {};
    for (const row of r.results || []) c[`${row.provider}:${row.kind}`] = row.n;
    mem.counts = c;
    mem.at = Date.now();
  } catch (_) { /* fail-soft: keep the last reading */ }
  return mem.counts;
}

function missStmt(env, m, miss) {
  return env.LIVE_DB.prepare("INSERT INTO misses (month, q, cell, reason, surface, n, found) VALUES (?, ?, ?, ?, ?, 1, ?) " +
    "ON CONFLICT (month, q, cell, reason, surface) DO UPDATE SET n = n + 1, found = found + excluded.found")
    .bind(m, miss.q, miss.cell, miss.reason, miss.surface, miss.found ? 1 : 0);
}

/** Count one provider call (and log the miss that caused it). Never delays the answer: D1 is written after it. */
function note(env, ctx, provider, kind, miss) {
  const m = rollMonth();
  if (provider) {
    const key = `${provider}:${kind}`;
    mem.counts[key] = (mem.counts[key] || 0) + 1;
  }
  if (!env.LIVE_DB) return;
  const stmts = [];
  if (provider) {
    stmts.push(env.LIVE_DB.prepare("INSERT INTO usage (month, provider, kind, n) VALUES (?, ?, ?, 1) " +
      "ON CONFLICT (month, provider, kind) DO UPDATE SET n = n + 1").bind(m, provider, kind));
  }
  if (miss) {
    stmts.push(missStmt(env, m, miss));
    if (Math.random() < 0.001) {
      const d = new Date();
      d.setUTCMonth(d.getUTCMonth() - MISS_RETAIN_MONTHS);
      stmts.push(env.LIVE_DB.prepare("DELETE FROM misses WHERE month < ?").bind(month(d)));
    }
  }
  if (stmts.length) ctx.waitUntil(schema(env).then(() => env.LIVE_DB.batch(stmts)).catch(() => {}));
}

/** The provider for the next list call: the first in line with free calls left, else the cheapest with a known price. */
function pick(env, c, skip) {
  const line = order(env).filter((p) => !mem.refused[p] && !skip.has(p));
  for (const p of line) {
    const k = conf(env, p);
    if ((c[`${p}:list`] || 0) + (c[`${p}:details`] || 0) < k.free * SAFETY) return { p, paid: false };
  }
  const paid = line.filter((p) => conf(env, p).price > 0).sort((a, b) => conf(env, a).price - conf(env, b).price);
  return paid.length ? { p: paid[0], paid: true } : null;
}

// ── a query as the miss log keeps it: normalised words, nothing else ─────────────────────────────────────────────────
function normQuery(q) {
  return q.normalize("NFKC").toLowerCase()
    .replace(/[ً-ْـ]/g, "")
    .replace(/[أإآٱ]/g, "ا").replace(/ى/g, "ي").replace(/ة/g, "ه")
    .replace(/[^\p{L}\p{N}\s]/gu, " ").replace(/\s+/g, " ").trim().slice(0, 80);
}

function cell(lat, lon) {
  const f = (v) => (Math.floor(v / 0.05 + 1e-9) * 0.05).toFixed(2);
  return `${f(lat)},${f(lon)}`;
}

async function timed(url, init = {}) {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), TIMEOUT_MS);
  try {
    return await fetch(url, { ...init, signal: ac.signal });
  } finally {
    clearTimeout(t);
  }
}

function haversine(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const a = Math.sin((lat2 - lat1) * r / 2) ** 2 +
    Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin((lon2 - lon1) * r / 2) ** 2;
  return 2 * 6371008.8 * Math.asin(Math.sqrt(a));
}

// ── the providers: a list call (the cheapest endpoint) and a details call (on tap) each ─────────────────────────────
// Each answers {status, results} / {status, place}; status 0 = no answer (timeout / network).

const LIST = {
  async here(env, q, lat, lon, lang, limit) {
    const u = new URL("https://autosuggest.search.hereapi.com/v1/autosuggest");
    u.search = new URLSearchParams({ q, at: `${lat},${lon}`, in: "countryCode:EGY", limit: String(limit), lang,
      apiKey: env.HERE_API_KEY }).toString();
    const r = await timed(u.toString());
    if (!r.ok) return { status: r.status, results: [] };
    const d = await r.json();
    // query / chain suggestions carry no position: they are no place
    return { status: 200, results: (d.items || []).filter((x) => x.position).map(hereRow) };
  },
  async tomtom(env, q, lat, lon, lang, limit) {
    const u = new URL(`https://api.tomtom.com/search/2/search/${encodeURIComponent(q)}.json`);
    u.search = new URLSearchParams({ key: env.TOMTOM_API_KEY, lat: String(lat), lon: String(lon), radius: "60000",
      limit: String(limit), countrySet: "EG", language: lang === "en" ? "en-GB" : "ar", typeahead: "true",
      idxSet: "POI,Str,Geo,PAD,Addr" }).toString();
    const r = await timed(u.toString());
    if (!r.ok) return { status: r.status, results: [] };
    const d = await r.json();
    return { status: 200, results: (d.results || []).map(tomtomRow) };
  },
  async huawei(env, q, lat, lon, lang, limit) {
    const u = "https://siteapi.cloud.huawei.com/mapApi/v1/siteService/querySuggestion?key=" +
      encodeURIComponent(env.HUAWEI_API_KEY);
    const r = await timed(u, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: q, location: { lat, lng: lon }, radius: 50000, language: lang, countryCode: "EG" }) });
    if (!r.ok) return { status: r.status, results: [] };
    const d = await r.json();
    if (d.returnCode && d.returnCode !== "0" && d.returnCode !== "010001") return { status: huaweiStatus(d.returnCode), results: [] };
    return { status: 200, results: (d.sites || []).slice(0, limit).map((s) => huaweiRow(s, lat, lon)) };
  },
};

const DETAILS = {
  async here(env, id, lang) {
    const u = new URL("https://lookup.search.hereapi.com/v1/lookup");
    u.search = new URLSearchParams({ id, lang, apiKey: env.HERE_API_KEY }).toString();
    const r = await timed(u.toString());
    if (!r.ok) return { status: r.status };
    const x = await r.json();
    return x && x.position ? { status: 200, place: hereRow(x) } : { status: 404 };
  },
  async tomtom(env, id, lang) {
    const u = new URL("https://api.tomtom.com/search/2/place.json");
    u.search = new URLSearchParams({ entityId: id, key: env.TOMTOM_API_KEY, language: lang === "en" ? "en-GB" : "ar" })
      .toString();
    const r = await timed(u.toString());
    if (!r.ok) return { status: r.status };
    const d = await r.json();
    const x = (d.results || [])[0];
    return x ? { status: 200, place: tomtomRow(x) } : { status: 404 };
  },
  async huawei(env, id, lang) {
    const u = "https://siteapi.cloud.huawei.com/mapApi/v1/siteService/getDetailSearch?key=" +
      encodeURIComponent(env.HUAWEI_API_KEY);
    const r = await timed(u, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ siteId: id, language: lang }) });
    if (!r.ok) return { status: r.status };
    const d = await r.json();
    if (!d.site) return { status: d.returnCode ? huaweiStatus(d.returnCode) : 404 };
    return { status: 200, place: huaweiRow(d.site, null, null) };
  },
};

function hereRow(x) {
  const contact = (x.contacts || [])[0] || {};
  const first = (l) => ((l || [])[0] || {}).value || null;
  return {
    id: `here.${x.id}`, name: x.title || "", address: (x.address && x.address.label) || "",
    lat: x.position.lat, lng: x.position.lng,
    category: (x.categories && x.categories[0] && x.categories[0].name) || "",
    type: x.resultType === "street" ? "street" : x.resultType === "place" ? "POI" : x.resultType || "",
    dist: x.distance ?? null,
    phone: first(contact.phone) || first(contact.mobile), url: first(contact.www),
    hours: ((x.openingHours || [])[0] || {}).text || null,
  };
}

function tomtomRow(x) {
  const p = x.poi || {};
  const a = x.address || {};
  return {
    id: `tomtom.${x.id}`, name: p.name || a.streetName || a.municipalitySubdivision || a.municipality || "",
    address: a.freeformAddress || "", lat: x.position && x.position.lat, lng: x.position && x.position.lon,
    category: (p.categories && p.categories[0]) || x.type || "", type: x.type || "", dist: x.dist ?? null,
    phone: p.phone || null, url: p.url || null, hours: null,
  };
}

function huaweiRow(s, lat, lon) {
  const at = s.location || {};
  const poi = s.poi || {};
  return {
    id: `huawei.${s.siteId}`, name: s.name || "", address: s.formatAddress || "", lat: at.lat, lng: at.lng,
    category: (poi.poiTypes && poi.poiTypes[0]) || "", type: "POI",
    dist: lat == null || at.lat == null ? null : haversine(lat, lon, at.lat, at.lng),
    phone: poi.phone || poi.internationalPhone || null, url: poi.websiteUrl || null,
    hours: poi.openingHours && poi.openingHours.texts ? poi.openingHours.texts : null,
  };
}

/** Huawei answers HTTP 200 with a returnCode; key / quota / permission codes are refusals like a 403. */
function huaweiStatus(code) {
  return ["010002", "010003", "010004", "010005", "010012"].includes(String(code)) ? 403 : 502;
}

function attribution(env, p, lang) {
  const a = conf(env, p).attribution;
  return { provider: p, name: lang === "en" ? a.en : a.ar };
}

function valid(r) {
  return r && r.name && Number.isFinite(r.lat) && Number.isFinite(r.lng);
}

function parseCommon(url) {
  const q = (url.searchParams.get("q") || "").trim().slice(0, 120);
  const lat = Number(url.searchParams.get("lat"));
  const lon = Number(url.searchParams.get("lon"));
  const limit = Math.max(1, Math.min(10, Number(url.searchParams.get("limit")) || 8));
  const lang = url.searchParams.get("lang") === "en" ? "en" : "ar";
  return { q, lat, lon, limit, lang };
}

function inEgypt(lat, lon) {
  return lat >= EG.minLat && lat <= EG.maxLat && lon >= EG.minLon && lon <= EG.maxLon;
}

async function suggest(url, env, ctx) {
  const { q, lat, lon, limit, lang } = parseCommon(url);
  if ([...q].length < MIN_Q || !Number.isFinite(lat) || !Number.isFinite(lon)) return json({ error: "bad request" }, 400);
  if (!inEgypt(lat, lon)) return json({ provider: null, results: [] });
  const reason = url.searchParams.get("reason") === "kept" ? "kept" : "weak";
  const s = url.searchParams.get("surface");
  const surface = ["phone", "aa", "carplay", "sekka"].includes(s) ? s : "phone";
  const miss = { q: normQuery(q), cell: cell(lat, lon), reason, surface, found: false };
  const c = await counts(env);
  const tried = new Set();
  for (let attempt = 0; attempt < 2; attempt++) {
    const choice = pick(env, c, tried);
    if (!choice) break;
    const p = choice.p;
    tried.add(p);
    let out;
    try {
      out = await LIST[p](env, q, lat, lon, lang, limit);
    } catch (_) {
      out = { status: 0, results: [] };
    }
    if (out.status === 401 || out.status === 403 || out.status === 429) {
      mem.refused[p] = true;
      continue;
    }
    if (out.status !== 200) continue;
    const results = out.results.filter(valid);
    note(env, ctx, p, "list", { ...miss, found: results.length > 0 });
    return json({ provider: p, paid: choice.paid, attribution: attribution(env, p, lang), cache_s: conf(env, p).cache_s,
      results });
  }
  note(env, ctx, null, null, miss); // nothing answered: the miss still counts
  return json({ provider: null, results: [], error: "no provider" });
}

async function details(url, env, ctx) {
  const raw = url.searchParams.get("id") || "";
  const dot = raw.indexOf(".");
  const p = dot > 0 ? raw.slice(0, dot) : "";
  const id = raw.slice(dot + 1);
  const lang = url.searchParams.get("lang") === "en" ? "en" : "ar";
  if (!DETAILS[p] || !id || !env[KEY_OF[p]]) return json({ error: "bad request" }, 400);
  let out;
  try {
    out = await DETAILS[p](env, id, lang);
  } catch (_) {
    out = { status: 0 };
  }
  if (out.status !== 200 || !valid(out.place)) return json({ provider: p, place: null, error: `upstream ${out.status}` });
  note(env, ctx, p, "details", null);
  return json({ provider: p, attribution: attribution(env, p, lang), cache_s: conf(env, p).cache_s, place: out.place });
}

/** The first version's route: TomTom in the old shape (bare TomTom ids, no provider field). */
async function legacySearch(url, env, ctx) {
  if (!env.TOMTOM_API_KEY) return json({ results: [], error: "no key" }, 503);
  const { q, lat, lon, limit, lang } = parseCommon(url);
  if (q.length < 2 || !Number.isFinite(lat) || !Number.isFinite(lon)) return json({ error: "bad request" }, 400);
  if (!inEgypt(lat, lon)) return json({ results: [] });
  let out;
  try {
    out = await LIST.tomtom(env, q, lat, lon, lang, limit);
  } catch (_) {
    return json({ results: [], error: "upstream" }, 502);
  }
  if (out.status !== 200) return json({ results: [], error: `upstream ${out.status}` }, 200);
  note(env, ctx, "tomtom", "list", null);
  return json({ results: out.results.filter(valid).map((r) => ({ ...r, id: r.id.slice("tomtom.".length) })) });
}

async function usage(env) {
  mem.at = 0; // read the shared count now
  const c = await counts(env);
  const providers = {};
  let cost = 0;
  for (const p of Object.keys(PROVIDERS)) {
    const k = conf(env, p);
    const list = c[`${p}:list`] || 0;
    const det = c[`${p}:details`] || 0;
    const over = Math.max(0, list + det - k.free);
    const overDet = Math.min(over, det);
    const usd = ((over - overDet) * k.price + overDet * (k.detailsPrice || k.price)) / 1000;
    cost += usd;
    providers[p] = { key: Boolean(env[KEY_OF[p]]), list, details: det, free: k.free, price_per_1k: k.price,
      details_price_per_1k: k.detailsPrice, refused: Boolean(mem.refused[p]), cost_usd: Math.round(usd * 100) / 100 };
  }
  return json({ month: month(), order: order(env), stored: Boolean(env.LIVE_DB), providers,
    cost_usd: Math.round(cost * 100) / 100 });
}

async function misses(env, url) {
  if (!env.LIVE_DB) return json({ misses: [], stored: false });
  await schema(env);
  const m = url.searchParams.get("month") || month();
  const r = await env.LIVE_DB.prepare("SELECT q, cell, reason, surface, n, found FROM misses WHERE month = ? " +
    "ORDER BY n DESC LIMIT 5000").bind(m).all();
  return json({ month: m, misses: r.results || [] });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method !== "GET") return json({ error: "not found" }, 404);
    if (url.pathname === "/usage" || url.pathname === "/misses") {
      if (!env.ADMIN_TOKEN || request.headers.get("x-admin") !== env.ADMIN_TOKEN) return json({ error: "forbidden" }, 403);
      return url.pathname === "/usage" ? usage(env) : misses(env, url);
    }
    if (env.APP_TOKEN && request.headers.get("x-routemind") !== env.APP_TOKEN) return json({ error: "forbidden" }, 403);
    if (url.pathname === "/suggest") return suggest(url, env, ctx);
    if (url.pathname === "/details") return details(url, env, ctx);
    if (url.pathname === "/search") return legacySearch(url, env, ctx);
    return json({ error: "not found" }, 404);
  },
};

// for the desk test (tools/place_index/live_worker/worker_test.mjs)
export const _test = { normQuery, cell, pick, PROVIDERS, mem, order, conf, rollMonth };
