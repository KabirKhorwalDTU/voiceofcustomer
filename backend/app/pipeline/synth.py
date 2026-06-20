from collections import Counter, defaultdict
import csv
from datetime import date
from io import BytesIO, StringIO
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from openpyxl import Workbook

from app.models import Company, Review, Run, Theme


def recency_weight(review_date: Optional[date], window_days: int) -> float:
    if not review_date:
        return 0.5
    age = max(0, (date.today() - review_date).days)
    if age > window_days:
        return 0.25
    return max(0.25, 1 - (age / window_days) * 0.75)


def humanize_theme(theme: Optional[str]) -> str:
    if not theme:
        return "Other"
    exact = {
        "payments_or_refunds": "Payments & refunds.",
        "login_or_kyc": "Login & KYC.",
        "support_quality": "Support quality.",
        "app_reliability": "App reliability.",
        "delivery_or_service_fulfillment": "Delivery & service fulfillment.",
        "quality_or_professionalism": "Quality & professionalism.",
        "pricing_or_fees": "Pricing & fees.",
        "pricing_and_promotions": "Pricing & promotions.",
        "pricing_and_value": "Pricing & value.",
        "unfair_refund_policies_and_failure_to_process_refunds": "Refunds: unfair policies & failures to process.",
    }
    if theme in exact:
        return exact[theme]
    words = clean_theme_words(theme.replace("_", " ").strip())
    if not words:
        return "Other"
    lower_words = words.lower()
    if "overpriced" in lower_words and not lower_words.startswith("pricing"):
        return f"Pricing: {words}."
    topic_prefixes = {
        "refund": "Refunds",
        "payment": "Payments",
        "payments": "Payments",
        "booking": "Bookings",
        "login": "Login",
        "support": "Support",
        "delivery": "Delivery",
        "quality": "Quality",
        "app": "App",
        "order": "Orders",
        "pricing": "Pricing",
        "price": "Pricing",
    }
    for key, label in topic_prefixes.items():
        if words == key:
            return label
        if words.startswith(f"{key} "):
            remainder = words[len(key) :].replace("  ", " ").strip(" -:")
            if remainder:
                if remainder.startswith("and "):
                    return f"{label} & {remainder[4:]}."
                return f"{label}: {remainder}."
    return words[:1].upper() + words[1:] + ("." if not words.endswith(".") else "")


def clean_theme_words(words: str) -> str:
    replacements = {
        "overd products": "overpriced products",
        "poor ,": "poor,",
        "in- feedback": "in-app feedback",
        "behind /registration": "behind login/registration",
        "without mandatory.": "without mandatory registration.",
        "without mandatory ": "without mandatory registration ",
    }
    cleaned = words
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    return " ".join(cleaned.split())


def build_theme_rows(run: Run, reviews: List[Review], source_weights: Dict[str, float], recency_window_days: int) -> List[Theme]:
    source_totals = Counter(review.source for review in reviews if review.theme)
    grouped: Dict[str, List[Review]] = defaultdict(list)
    for review in reviews:
        if review.theme:
            grouped[review.theme].append(review)

    rows: List[Theme] = []
    total_reviews = len([review for review in reviews if review.theme]) or 1
    for theme_name, items in grouped.items():
        per_source_counts = Counter(review.source for review in items)
        weighted_shares = []
        active_weight_total = 0.0
        for source, total in source_totals.items():
            if total <= 0:
                continue
            weight = float(source_weights.get(source, 1))
            active_weight_total += weight
            weighted_shares.append((per_source_counts.get(source, 0) / total) * weight)
        source_normalized_frequency = sum(weighted_shares) / active_weight_total if active_weight_total else 0
        l1_share = len(items) / total_reviews
        avg_severity = 0
        avg_recency = sum(recency_weight(review.date, recency_window_days) for review in items) / len(items)
        score = source_normalized_frequency * avg_recency
        top_reviews = sorted(items, key=lambda item: recency_weight(item.date, recency_window_days), reverse=True)[:3]
        l2_subthemes = build_l2_subtheme_rows(items, recency_window_days)
        rows.append(
            Theme(
                run_id=run.id,
                company_id=run.company_id,
                theme=theme_name,
                count=len(items),
                normalized_frequency=round(l1_share, 6),
                avg_severity=round(avg_severity, 4),
                theme_score=round(score, 6),
                rank=0,
                l2_subthemes=l2_subthemes,
                top_quotes=[
                    {
                        "text": review.text,
                        "source": review.source,
                        "rating": review.rating,
                        "date": review.date.isoformat() if review.date else None,
                    }
                    for review in top_reviews
                ],
            )
        )

    rows.sort(key=lambda row: row.theme_score, reverse=True)
    for index, row in enumerate(rows, start=1):
        row.rank = index
    return rows


def build_l2_subtheme_rows(reviews: List[Review], recency_window_days: int) -> List[Dict[str, Any]]:
    if not reviews:
        return []
    if len(reviews) < 5:
        return []
    grouped: Dict[str, List[Review]] = defaultdict(list)
    for review in reviews:
        if review.l2_theme:
            grouped[review.l2_theme].append(review)
    if not grouped:
        return []

    rows = []
    parent_total = len(reviews)
    for label, items in grouped.items():
        top_reviews = sorted(items, key=lambda item: recency_weight(item.date, recency_window_days), reverse=True)[:3]
        rows.append(
            {
                "label": label,
                "display_label": humanize_theme(label),
                "count": len(items),
                "score": round(len(items) / parent_total, 4),
                "top_quotes": [
                    {
                        "text": review.text,
                        "source": review.source,
                        "rating": review.rating,
                        "date": review.date.isoformat() if review.date else None,
                    }
                    for review in top_reviews
                ],
            }
        )
    return sorted(rows, key=lambda row: row["score"], reverse=True)[:10]


def build_summary(run: Run, reviews: List[Review], themes: List[Theme]) -> Dict[str, Any]:
    dates = [review.date for review in reviews if review.date]
    source_quality = []
    completeness = run.completeness or {}
    classified_reviews = [review for review in reviews if review.theme]
    other_count = sum(1 for review in classified_reviews if review.theme == "other")
    theme_split = {
        theme.theme: {
            "count": theme.count,
            "share": round(float(theme.normalized_frequency or 0), 4),
            "display_theme": humanize_theme(theme.theme),
        }
        for theme in themes
    }
    for source, count in Counter(review.source for review in reviews).items():
        source_reviews = [review for review in reviews if review.source == source]
        useful = sum(1 for review in source_reviews if review.theme and review.theme != "other")
        ratings = [review.rating for review in source_reviews if review.rating]
        cost = float((completeness.get(source) or {}).get("cost_usd") or 0)
        source_quality.append(
            {
                "source": source,
                "rows": count,
                "useful_rows": useful,
                "non_other_pct": round(useful / count, 4) if count else 0,
                "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
                "cost_usd": cost,
                "cost_per_useful_row": round(cost / useful, 6) if useful else None,
            }
        )
    source_quality.sort(key=lambda row: row["rows"], reverse=True)
    return {
        "total_reviews": len(reviews),
        "date_range": {
            "start": min(dates).isoformat() if dates else None,
            "end": max(dates).isoformat() if dates else None,
        },
        "source_mix": dict(Counter(review.source for review in reviews)),
        "theme_split": theme_split,
        "other_share": round(other_count / len(classified_reviews), 4) if classified_reviews else 0,
        "low_confidence": (other_count / len(classified_reviews)) > 0.15 if classified_reviews else False,
        "rating_distribution": dict(Counter(str(review.rating) for review in reviews if review.rating)),
        "volume_over_time": volume_over_time(reviews),
        "source_quality": source_quality,
        "top_themes": [
            {
                "theme": theme.theme,
                "display_theme": humanize_theme(theme.theme),
                "count": theme.count,
                "share": float(theme.normalized_frequency or 0),
                "theme_score": theme.theme_score,
                "rank": theme.rank,
                "l2_subthemes": theme.l2_subthemes,
            }
            for theme in themes[:10]
        ],
        "completeness": run.completeness,
        "cost_estimate": run.cost_estimate,
        "dedup_ratio": run.dedup_ratio,
        "quarantine_rate": run.quarantine_rate,
    }


def volume_over_time(reviews: Iterable[Review]) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for review in reviews:
        if review.date:
            counts[review.date.isoformat()[:7]] += 1
    return dict(sorted(counts.items()))


def build_deck_spec(company: Company, run: Run, reviews: List[Review], themes: List[Theme], summary: Optional[Dict[str, Any]] = None) -> str:
    summary = summary or build_summary(run, reviews, themes)
    headline = "No classified themes yet."
    if themes:
        top = themes[0]
        headline = f"Top signal: {humanize_theme(top.theme)} at {int(round(float(top.normalized_frequency or 0) * 100))}% of classified feedback."
    source_mix = ", ".join(f"{source}: {count}" for source, count in summary["source_mix"].items()) or "No data"
    source_names = {
        "play": "Google Play",
        "appstore": "App Store",
        "maps": "Google Maps",
        "reddit": "Reddit",
        "mouthshut": "MouthShut",
        "instagram": "Instagram",
        "twitter": "X / Twitter",
    }
    collected_sources = [
        f"{source_names.get(source, source)} ({count})"
        for source, count in summary["source_mix"].items()
        if int(count or 0) > 0
    ]
    source_sentence = ", ".join(collected_sources) if collected_sources else "no completed public sources"
    theme_lines = "\n".join(
        f"- {theme.rank}. {humanize_theme(theme.theme)}: count={theme.count}, share={int(round(float(theme.normalized_frequency or 0) * 100))}%, score={theme.theme_score:.3f}"
        for theme in themes[:8]
    )
    l2_sections = []
    for theme in themes[:2]:
        if not theme.l2_subthemes:
            continue
        lines = [
            f"- {humanize_theme(row.get('label'))}: {int(round(float(row.get('score') or 0) * 100))}% of parent ({row.get('count')} reviews)"
            for row in theme.l2_subthemes[:10]
        ]
        l2_sections.append(f"{humanize_theme(theme.theme)}\n" + "\n".join(lines))
    l2_breakdown = "\n\n".join(l2_sections) or "- No L2 sub-theme breakdown met the 5-review threshold."
    quote_lines = []
    for theme in themes[:4]:
        if theme.top_quotes:
            quote = theme.top_quotes[0]
            quote_lines.append(f"- {humanize_theme(theme.theme)}: \"{quote.get('text')}\"")
    quotes = "\n".join(quote_lines) or "- No representative quotes available."

    return f"""# Deck Spec - {company.name}

## Slide 1 - About the applicant + project + headline finding

Applicant/project: Voice of Customer analysis for {company.name}. Public feedback from {source_sentence} was collected and classified into L1 issue themes and L2 sub-issues.

Headline finding: {headline}

## Slide 2 - The data

Total reviews: {summary["total_reviews"]}
Date range: {summary["date_range"]["start"]} to {summary["date_range"]["end"]}
Source mix: {source_mix}
Other share: {int(round(float(summary["other_share"] or 0) * 100))}%

Top L1 themes:
{theme_lines or "- No themes available."}

L2 breakdown for top L1 themes:
{l2_breakdown}

## Slide 3 - Representative voices

{quotes}

## Slide 4 - Prioritized problem + proposed solution

Prioritized problem: Operator to complete based on the highest-scoring L1 theme and supporting L2 evidence.

Proposed solution: Operator to complete with target workflow, product intervention, and success metric.
"""


def reviews_to_records(reviews: List[Review]) -> List[Dict[str, Any]]:
    return [
        {
            "review_hash": review.review_hash,
            "source": review.source,
            "date": review.date.isoformat() if review.date else None,
            "rating": review.rating,
            "text": review.text,
            "l1_theme": review.theme,
            "l2_theme": review.l2_theme,
            "representative_flag": review.representative_flag,
        }
        for review in reviews
    ]


def export_reviews(reviews: List[Review], fmt: str) -> Tuple[bytes, str, str]:
    records = reviews_to_records(reviews)
    if fmt == "json":
        return json.dumps(records, indent=2).encode("utf-8"), "application/json", "tagged_reviews.json"
    if fmt == "csv":
        output = StringIO()
        fieldnames = list(records[0].keys()) if records else [
            "review_hash",
            "source",
            "date",
            "rating",
            "text",
            "l1_theme",
            "l2_theme",
            "representative_flag",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
        return output.getvalue().encode("utf-8"), "text/csv", "tagged_reviews.csv"
    if fmt == "xlsx":
        output = BytesIO()
        fieldnames = list(records[0].keys()) if records else [
            "review_hash",
            "source",
            "date",
            "rating",
            "text",
            "l1_theme",
            "l2_theme",
            "representative_flag",
        ]
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "reviews"
        sheet.append(fieldnames)
        for record in records:
            sheet.append([record.get(field) for field in fieldnames])
        workbook.save(output)
        return output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "tagged_reviews.xlsx"
    raise ValueError("Unsupported export format")
