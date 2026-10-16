// RouteMind live place search — a Cloudflare Worker in front of TomTom Search (docs/place-search-2026-10.md §7).
//
// The app's own index answers first, on the phone. This is the ONLINE fallback for what the index does
// not know yet (a shop opened last week, a tile not downloaded): GET /search?q=&lat=&lon=&lang=ar|en&limit=
// → {"results":[{id,name,address,lat,lng,category,phone,url,dist}]}.
//
// The TomTom key lives ONLY here (Settings → Variables → TOMTOM_API_KEY, type Secret); the phone never
// sees it. Requests outside Egypt, without the app's header, or malformed are refused before TomTom is
// called. Free plan: 100,000 requests/day, no card. TomTom's free tier answers 2,500 searches/day and
// then refuses — the app then shows its own results only; nothing is ever billed.
// Results are passed through, never stored (TomTom's terms).

const EG = { minLat: 21.5, maxLat: 31.9, minLon: 24.5, maxLon: 37.1 };

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "GET" || url.pathname !== "/search") return json({ error: "not found" }, 404);
    if (env.APP_TOKEN && request.headers.get("x-routemind") !== env.APP_TOKEN) return json({ error: "forbidden" }, 403);
    if (!env.TOMTOM_API_KEY) return json({ results: [], error: "no key" }, 503);
    const q = (url.searchParams.get("q") || "").trim().slice(0, 120);
    const lat = Number(url.searchParams.get("lat"));
    const lon = Number(url.searchParams.get("lon"));
    const limit = Math.max(1, Math.min(10, Number(url.searchParams.get("limit")) || 8));
    if (q.length < 2 || !Number.isFinite(lat) || !Number.isFinite(lon)) return json({ error: "bad request" }, 400);
    if (lat < EG.minLat || lat > EG.maxLat || lon < EG.minLon || lon > EG.maxLon) return json({ results: [] });
    const lang = url.searchParams.get("lang") === "en" ? "en-GB" : "ar";
    const tt = new URL(`https://api.tomtom.com/search/2/search/${encodeURIComponent(q)}.json`);
    tt.search = new URLSearchParams({
      key: env.TOMTOM_API_KEY, lat: String(lat), lon: String(lon), radius: "60000", limit: String(limit),
      countrySet: "EG", language: lang, typeahead: "true", idxSet: "POI,Str,Geo,PAD,Addr",
    }).toString();
    let up;
    try {
      up = await fetch(tt.toString(), { cf: { cacheTtl: 0 } });
    } catch (e) {
      return json({ results: [], error: "upstream" }, 502);
    }
    if (!up.ok) return json({ results: [], error: `upstream ${up.status}` }, 200);
    const data = await up.json();
    const results = (data.results || []).map((r) => ({
      id: r.id,
      name: (r.poi && r.poi.name) || (r.address && (r.address.streetName || r.address.municipalitySubdivision ||
        r.address.municipality)) || "",
      address: (r.address && r.address.freeformAddress) || "",
      lat: r.position && r.position.lat,
      lng: r.position && r.position.lon,
      category: (r.poi && r.poi.categories && r.poi.categories[0]) || r.type || "",
      phone: (r.poi && r.poi.phone) || null,
      url: (r.poi && r.poi.url) || null,
      dist: r.dist || null,
      type: r.type || "",
    })).filter((r) => r.name && Number.isFinite(r.lat) && Number.isFinite(r.lng));
    return json({ results });
  },
};
