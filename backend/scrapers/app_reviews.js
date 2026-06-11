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
  const pageLimit = Number(input.page_limit || 10);
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
