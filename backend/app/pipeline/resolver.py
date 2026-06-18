import re
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse


@dataclass
class ResolvedLinks:
    play_id: str
    app_id: str
    domain: str
    brand_keyword: str


def resolve_links(play_link: str, app_store_link: str, website: str, company_name: str) -> ResolvedLinks:
    play_id = ""
    app_id = ""

    if play_link:
        parsed = urlparse(play_link)
        query_id = parse_qs(parsed.query).get("id", [""])[0]
        play_id = query_id or parsed.path.strip("/").split("/")[-1]

    if app_store_link:
        match = re.search(r"/id(\d+)", app_store_link)
        if match:
            app_id = match.group(1)
        else:
            app_id = parse_qs(urlparse(app_store_link).query).get("id", [""])[0]

    domain = ""
    if website:
        parsed_site = urlparse(website if "://" in website else f"https://{website}")
        domain = parsed_site.netloc.lower().replace("www.", "")

    domain_token = domain.split(".")[0] if domain else ""
    name_slug = re.sub(r"[^a-z0-9]+", "", company_name.lower())
    brand_keyword = domain_token or company_name.strip()
    if name_slug and (domain_token == name_slug or domain_token.endswith(name_slug)):
        brand_keyword = name_slug
    if (not play_id or not app_id) and company_name:
        discovered = discover_store_ids(company_name, domain_token)
        play_id = play_id or discovered.get("play_id", "")
        app_id = app_id or discovered.get("app_id", "")
    return ResolvedLinks(play_id=play_id, app_id=app_id, domain=domain, brand_keyword=brand_keyword)


def discover_store_ids(company_name: str, domain_token: str) -> dict:
    script = Path(__file__).resolve().parents[2] / "scrapers" / "app_reviews.js"
    payload = {"mode": "resolve", "term": company_name, "domain_token": domain_token, "country": "in"}
    try:
        proc = subprocess.run(
            ["node", str(script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    return {"play_id": str(data.get("play_id") or ""), "app_id": str(data.get("app_id") or "")}
