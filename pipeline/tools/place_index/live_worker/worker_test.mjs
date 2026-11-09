// Desk test of the live Worker: node tools/place_index/live_worker/worker_test.mjs [--live <keys.env>]
// Fake providers + a fake D1 prove the rotation (free first, refusal → next, all free spent → the cheapest priced),
// the 3-character rule, details going to the row's own provider, the old /search shape, and a miss log that holds the
// normalised query + a cell only. With --live, one real HERE Autosuggest + Lookup through the same code (the key is read
// from the file and never printed).
import assert from "node:assert/strict";
import fs from "node:fs";
import worker, { _test } from "./worker.js";

const calls = [];
let script = {}; // host → status to answer (default 200)

function fakeFetch(url, init = {}) {
  const u = new URL(url);
  calls.push(u.host);
  const status = script[u.host] ?? 200;
  const body = (() => {
    if (u.host.startsWith("autosuggest.")) return { items: [
      { id: "H1", title: "كشري تومه", resultType: "place", position: { lat: 30.97, lng: 31.17 }, distance: 1100,
        address: { label: "المحلة الكبرى" }, categories: [{ name: "Restaurant" }] },
      { title: "كشري", resultType: "categoryQuery" }] };
    if (u.host.startsWith("lookup.")) return { id: "H1", title: "كشري تومه", resultType: "place",
      position: { lat: 30.97, lng: 31.17 }, contacts: [{ phone: [{ value: "+20100" }] }] };
    if (u.host === "api.tomtom.com") return u.pathname.includes("place.json")
      ? { results: [{ id: "T1", type: "POI", poi: { name: "Tomtom place" }, position: { lat: 30.1, lon: 31.2 } }] }
      : { results: [{ id: "T1", type: "POI", poi: { name: "Tomtom place" }, position: { lat: 30.1, lon: 31.2 }, dist: 50 }] };
    if (u.host === "siteapi.cloud.huawei.com") return { returnCode: "0",
      sites: [{ siteId: "W1", name: "Huawei place", location: { lat: 30.2, lng: 31.3 } }] };
    return {};
  })();
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

class FakeD1 {
  constructor() { this.usage = new Map(); this.misses = new Map(); }
  prepare(sql) {
    const db = this;
    return { sql, args: [], bind(...a) { this.args = a; return this; },
      async all() { return db.run1(this); }, async run() { return db.run1(this); } };
  }
  async batch(stmts) { for (const s of stmts) await this.run1(s); }
  run1(s) {
    if (s.sql.startsWith("CREATE")) return {};
    if (s.sql.startsWith("INSERT INTO usage")) {
      const k = s.args.slice(0, 3).join("|");
      this.usage.set(k, (this.usage.get(k) || 0) + 1);
      return {};
    }
    if (s.sql.startsWith("INSERT INTO misses")) {
      const k = s.args.slice(0, 5).join("|");
      const o = this.misses.get(k) || { n: 0, found: 0 };
      this.misses.set(k, { n: o.n + 1, found: o.found + (s.args[5] || 0) });
      return {};
    }
    if (s.sql.startsWith("SELECT provider")) {
      return { results: [...this.usage].filter(([k]) => k.startsWith(s.args[0] + "|"))
        .map(([k, n]) => ({ provider: k.split("|")[1], kind: k.split("|")[2], n })) };
    }
    if (s.sql.startsWith("SELECT q")) return { results: [...this.misses].map(([k, v]) => ({ q: k.split("|")[1], ...v })) };
    return { results: [] };
  }
}

function reset() {
  Object.assign(_test.mem, { month: "", counts: {}, at: 0, refused: {}, schema: false });
  calls.length = 0;
  script = {};
}

const ctx = { pending: [], waitUntil(p) { this.pending.push(p); } };
async function get(env, path, headers = {}) {
  const r = await worker.fetch(new Request("https://w.example" + path, { headers: { "x-routemind": "T", ...headers } }), env, ctx);
  await Promise.all(ctx.pending.splice(0));
  return { status: r.status, body: await r.json() };
}
const Q = "/suggest?q=" + encodeURIComponent("تومه") + "&lat=30.97&lon=31.17&lang=ar&reason=weak&surface=aa";

async function unit() {
  globalThis.fetch = fakeFetch;
  const env = { APP_TOKEN: "T", ADMIN_TOKEN: "A", HERE_API_KEY: "h", TOMTOM_API_KEY: "t", LIVE_DB: new FakeD1() };

  // order: huawei has no key → HERE (free) answers; the query suggestion without a position is dropped
  reset();
  let r = await get(env, Q);
  assert.equal(r.body.provider, "here");
  assert.equal(r.body.paid, false);
  assert.equal(r.body.results.length, 1);
  assert.equal(r.body.results[0].id, "here.H1");
  assert.equal(r.body.attribution.name, "HERE");
  assert.equal(r.body.cache_s, 600);

  // under 3 characters: refused before any provider is called
  reset();
  r = await get(env, "/suggest?q=" + encodeURIComponent("تو") + "&lat=30.97&lon=31.17");
  assert.equal(r.status, 400);
  assert.equal(calls.length, 0);

  // outside Egypt: nothing is asked
  reset();
  r = await get(env, "/suggest?q=abcd&lat=48.8&lon=2.3");
  assert.deepEqual(r.body.results, []);
  assert.equal(calls.length, 0);

  // HERE refuses (quota) → TomTom answers the SAME request, and HERE stays skipped this month
  reset();
  script["autosuggest.search.hereapi.com"] = 429;
  r = await get(env, Q);
  assert.equal(r.body.provider, "tomtom");
  assert.equal(r.body.results[0].id, "tomtom.T1");
  script = {};
  r = await get(env, Q);
  assert.equal(r.body.provider, "tomtom");

  // HERE's free quota spent → TomTom's free quota; both spent → the cheapest PRICED one (HERE; TomTom's price is unknown)
  reset();
  _test.rollMonth();
  _test.mem.counts = { "here:list": 30000 };
  _test.mem.at = Date.now();
  r = await get({ ...env, LIVE_DB: undefined }, Q);
  assert.equal(r.body.provider, "tomtom");
  assert.equal(r.body.paid, false);
  _test.mem.counts = { "here:list": 30000, "tomtom:list": 2500 };
  r = await get({ ...env, LIVE_DB: undefined }, Q);
  assert.equal(r.body.provider, "here");
  assert.equal(r.body.paid, true);

  // Huawei first once its key exists and its free quota is set; never chosen to PAY ahead of a cheaper provider
  reset();
  r = await get({ ...env, LIVE_DB: undefined, HUAWEI_API_KEY: "w", FREE_HUAWEI: "140000" }, Q);
  assert.equal(r.body.provider, "huawei");
  assert.equal(r.body.attribution.name, "Petal Maps");
  reset();
  r = await get({ ...env, LIVE_DB: undefined, HUAWEI_API_KEY: "w" }, Q);
  assert.equal(r.body.provider, "here");

  // details: the row's own provider, counted as details
  reset();
  const db = new FakeD1();
  r = await get({ ...env, LIVE_DB: db }, "/details?id=here.H1&lang=ar");
  assert.equal(r.body.provider, "here");
  assert.equal(r.body.place.phone, "+20100");
  assert.ok([...db.usage.keys()].some((k) => k.endsWith("|here|details")));
  r = await get({ ...env, LIVE_DB: db }, "/details?id=bogus");
  assert.equal(r.status, 400);

  // the old route keeps its shape (bare TomTom ids)
  reset();
  r = await get(env, "/search?q=abcd&lat=30.1&lon=31.2");
  assert.equal(r.body.results[0].id, "T1");
  assert.equal(r.body.provider, undefined);

  // the miss log: normalised query + cell + reason + surface + counts; never a provider's name or id
  reset();
  const db2 = new FakeD1();
  await get({ ...env, LIVE_DB: db2 }, "/suggest?q=" + encodeURIComponent("  كُشري  تومة!! ") + "&lat=30.97&lon=31.17&surface=aa");
  const [[k, v]] = [...db2.misses];
  const [, q, c, reason, surface] = k.split("|");
  assert.equal(q, "كشري تومه");
  assert.equal(c, "30.95,31.15");
  assert.equal(reason, "weak");
  assert.equal(surface, "aa");
  assert.deepEqual(v, { n: 1, found: 1 });
  assert.ok(!k.includes("H1") && !k.includes("here"));

  // admin routes need the admin token, never the app's
  reset();
  r = await get(env, "/usage");
  assert.equal(r.status, 403);
  r = await get({ ...env, LIVE_DB: db2 }, "/usage", { "x-admin": "A" });
  assert.equal(r.body.providers.here.list, 1);
  r = await get({ ...env, LIVE_DB: db2 }, "/misses", { "x-admin": "A" });
  assert.equal(r.body.misses.length, 1);

  // a request without the app's token is refused before anything else
  r = await worker.fetch(new Request("https://w.example" + Q), env, ctx);
  assert.equal(r.status, 403);
  console.log("worker_test: unit OK");
}

async function live(path) {
  const keys = Object.fromEntries(fs.readFileSync(path, "utf8").split(/\r?\n/).filter((l) => l.includes("="))
    .map((l) => [l.slice(0, l.indexOf("=")).trim(), l.slice(l.indexOf("=") + 1).trim()]));
  if (!keys.HERE_API_KEY) { console.log("worker_test: live SKIPPED (no HERE_API_KEY)"); return; }
  globalThis.fetch = globalThis.__realFetch;
  reset();
  const env = { APP_TOKEN: "T", HERE_API_KEY: keys.HERE_API_KEY };
  const r = await get(env, "/suggest?q=" + encodeURIComponent("كشري التحرير") + "&lat=30.0444&lon=31.2357&lang=ar&limit=5");
  assert.equal(r.body.provider, "here");
  assert.ok(r.body.results.length > 0, "HERE answered nothing");
  const d = await get(env, "/details?id=" + encodeURIComponent(r.body.results[0].id) + "&lang=ar");
  assert.ok(d.body.place && Number.isFinite(d.body.place.lat), "HERE lookup answered nothing");
  console.log(`worker_test: live OK (HERE autosuggest ${r.body.results.length} rows, lookup ok)`);
}

globalThis.__realFetch = globalThis.fetch;
await unit();
const i = process.argv.indexOf("--live");
if (i > 0) await live(process.argv[i + 1]);
