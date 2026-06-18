const gplayModule = require("google-play-scraper");
const gplay = gplayModule.default || gplayModule;
const astore = require("app-store-scraper");

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => {
      try {
        resolve(JSON.parse(data || "{}"));
      } catch (error) {
        reject(error);
      }
    });
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizePlay(item, lang) {
  return {
    source: "play",
    text: item.text || item.review || "",
    rating: item.score || null,
    date: item.date ? new Date(item.date).toISOString().slice(0, 10) : null,
    external_id: item.id || "",
    language_hint: lang,
  };
}

function normalizeAppStore(item) {
  return {
    source: "appstore",
    text: item.text || item.review || "",
    rating: item.score || item.rating || null,
    date: item.updated ? new Date(item.updated).toISOString().slice(0, 10) : null,
    external_id: item.id || "",
    language_hint: "store",
  };
}

function uniqueReviews(items) {
  const seen = new Set();
  const result = [];
  for (const item of items) {
    const key = `${item.source}:${item.external_id || ""}:${item.date || ""}:${item.text}`;
    if (!item.text || seen.has(key)) continue;
    seen.add(key);
    result.push(item);
  }
  return result;
}

function normalizeText(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function bestMatch(candidates, term, domainToken, idField) {
  const normalizedTerm = normalizeText(term);
  const normalizedDomain = normalizeText(domainToken);
  const scored = candidates
    .map((item) => {
      const title = item.title || item.app_name || item.name || "";
      const id = item[idField] || item.appId || item.id || "";
      const haystack = `${normalizeText(title)} ${normalizeText(id)} ${normalizeText(item.developer || item.developerName || "")}`;
      let score = 0;
      if (normalizedDomain && haystack.includes(normalizedDomain)) score += 5;
      if (normalizedTerm && haystack.includes(normalizedTerm)) score += 4;
      if (normalizedTerm && normalizeText(title).startsWith(normalizedTerm)) score += 2;
      return { item, score };
    })
    .sort((a, b) => b.score - a.score);
  return scored[0] && scored[0].score > 0 ? scored[0].item : candidates[0];
}

async function resolveApps(input) {
  const term = input.term || input.company_name || "";
  const domainToken = input.domain_token || "";
  const result = { play_id: "", app_id: "", play_candidates: [], appstore_candidates: [] };
  if (!term) return result;

  try {
    const playCandidates = await gplay.search({
      term,
      country: input.country || "in",
      lang: "en",
      num: 5,
    });
    result.play_candidates = playCandidates.map((item) => ({ title: item.title, appId: item.appId, developer: item.developer }));
    const play = bestMatch(playCandidates, term, domainToken, "appId");
    result.play_id = play && play.appId ? play.appId : "";
  } catch (error) {
    result.play_error = String(error && error.message ? error.message : error).slice(0, 300);
  }

  try {
    const appCandidates = await astore.search({
      term,
      country: input.country || "in",
      num: 5,
    });
    result.appstore_candidates = appCandidates.map((item) => ({ title: item.title, id: item.id, appId: item.appId, developer: item.developer }));
    const app = bestMatch(appCandidates, term, domainToken, "id");
    result.app_id = app && app.id ? String(app.id) : "";
  } catch (error) {
    result.appstore_error = String(error && error.message ? error.message : error).slice(0, 300);
  }

  return result;
}

async function scrapePlay(input) {
  const maxReviews = Number(input.max_reviews || 3000);
  const throttle = Number(input.throttle || 10);
  const langs = input.langs || ["hi", "en"];
  const all = [];
  const perLang = Math.ceil(maxReviews / langs.length);
  for (const lang of langs) {
    const reviews = await gplay.reviews({
      appId: input.app_id,
      sort: gplay.sort.NEWEST,
      num: perLang,
      lang,
      country: input.country || "in",
      throttle,
    });
    all.push(...reviews.data.map((item) => normalizePlay(item, lang)));
    await sleep(500);
  }
  return uniqueReviews(all).slice(0, maxReviews);
}

async function scrapeAppStore(input) {
  const maxReviews = Number(input.max_reviews || 3000);
  const pageSize = 50;
  const pageLimit = Number(input.page_limit || Math.ceil(maxReviews / pageSize));
  const pages = Math.max(1, Math.min(pageLimit, Math.ceil(maxReviews / pageSize)));
  const all = [];
  for (let page = 1; page <= pages && all.length < maxReviews; page += 1) {
    const reviews = await astore.reviews({
      id: input.app_id,
      country: input.country || "in",
      sort: astore.sort.RECENT,
      page,
    });
    all.push(...reviews.map(normalizeAppStore));
    if (!reviews.length) break;
    await sleep(Number(input.throttle_ms || 500));
  }
  return uniqueReviews(all).slice(0, maxReviews);
}

async function main() {
  const input = await readStdin();
  if (input.mode === "resolve") {
    process.stdout.write(JSON.stringify(await resolveApps(input)));
    return;
  }
  const source = input.source;
  if (source === "play") {
    process.stdout.write(JSON.stringify(await scrapePlay(input)));
    return;
  }
  if (source === "appstore") {
    process.stdout.write(JSON.stringify(await scrapeAppStore(input)));
    return;
  }
  throw new Error(`unsupported source: ${source}`);
}

main().catch((error) => {
  process.stderr.write(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
