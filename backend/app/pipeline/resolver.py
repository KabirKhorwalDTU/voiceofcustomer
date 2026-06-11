import re
from dataclasses import dataclass
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
    return ResolvedLinks(play_id=play_id, app_id=app_id, domain=domain, brand_keyword=brand_keyword)
