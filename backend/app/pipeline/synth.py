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


def build_theme_rows(run: Run, reviews: List[Review], source_weights: Dict[str, float], recency_window_days: int) -> List[Theme]:
    source_totals = Counter(review.source for review in reviews if review.bucket and review.theme)
    grouped: Dict[Tuple[str, str], List[Review]] = defaultdict(list)
    for review in reviews:
        if review.bucket and review.theme:
            grouped[(review.bucket, review.theme)].append(review)

    rows: List[Theme] = []
    for (bucket, theme_name), items in grouped.items():
        per_source_counts = Counter(review.source for review in items)
        weighted_shares = []
        active_weight_total = 0.0
        for source, total in source_totals.items():
            if total <= 0:
                continue
            weight = float(source_weights.get(source, 1))
            active_weight_total += weight
            weighted_shares.append((per_source_counts.get(source, 0) / total) * weight)
        normalized_frequency = sum(weighted_shares) / active_weight_total if active_weight_total else 0
        avg_severity = sum(float(review.severity or 1) for review in items) / len(items)
        avg_recency = sum(recency_weight(review.date, recency_window_days) for review in items) / len(items)
        score = normalized_frequency * avg_severity * avg_recency
        top_reviews = sorted(items, key=lambda item: ((item.severity or 1), recency_weight(item.date, recency_window_days)), reverse=True)[:3]
        rows.append(
            Theme(
                run_id=run.id,
                company_id=run.company_id,
                bucket=bucket,
                theme=theme_name,
                count=len(items),
                normalized_frequency=round(normalized_frequency, 6),
                avg_severity=round(avg_severity, 4),
                theme_score=round(score, 6),
                rank=0,
                top_quotes=[
                    {
                        "text": review.text,
                        "english_gloss": review.english_gloss,
                        "source": review.source,
                        "severity": review.severity,
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


def build_summary(run: Run, reviews: List[Review], themes: List[Theme]) -> Dict[str, Any]:
    dates = [review.date for review in reviews if review.date]
    return {
        "total_reviews": len(reviews),
        "date_range": {
            "start": min(dates).isoformat() if dates else None,
            "end": max(dates).isoformat() if dates else None,
        },
        "source_mix": dict(Counter(review.source for review in reviews)),
        "bucket_split": dict(Counter(review.bucket for review in reviews if review.bucket)),
        "severity_distribution": dict(Counter(str(review.severity) for review in reviews if review.severity)),
        "volume_over_time": volume_over_time(reviews),
        "top_themes": [
            {
                "theme": theme.theme,
                "bucket": theme.bucket,
                "count": theme.count,
                "theme_score": theme.theme_score,
                "rank": theme.rank,
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


def build_deck_spec(company: Company, run: Run, reviews: List[Review], themes: List[Theme]) -> str:
    summary = build_summary(run, reviews, themes)
    headline = "No classified themes yet."
    if themes:
        top = themes[0]
        headline = f"Top signal: {top.theme.replace('_', ' ')} in {top.bucket.replace('_', ' ')} with score {top.theme_score:.3f}."
    source_mix = ", ".join(f"{source}: {count}" for source, count in summary["source_mix"].items()) or "No data"
    bucket_split = ", ".join(f"{bucket}: {count}" for bucket, count in summary["bucket_split"].items()) or "No classified data"
    theme_lines = "\n".join(
        f"- {theme.rank}. {theme.theme.replace('_', ' ')} ({theme.bucket}): count={theme.count}, score={theme.theme_score:.3f}, avg severity={theme.avg_severity:.2f}"
        for theme in themes[:8]
    )
    quote_lines = []
    for theme in themes[:4]:
        if theme.top_quotes:
            quote = theme.top_quotes[0]
            quote_lines.append(
                f"- {theme.theme.replace('_', ' ')}: \"{quote.get('text')}\" Gloss: {quote.get('english_gloss')}"
            )
    quotes = "\n".join(quote_lines) or "- No representative quotes available."

    return f"""# Deck Spec - {company.name}

## Slide 1 - About the applicant + project + headline finding

Applicant/project: Voice of Customer analysis for {company.name}. Public app-store, Reddit, Google Maps, and MouthShut feedback was collected and classified into Complaint, Feature Request, and Praise buckets.

Headline finding: {headline}

## Slide 2 - The data

Total reviews: {summary["total_reviews"]}
Date range: {summary["date_range"]["start"]} to {summary["date_range"]["end"]}
Source mix: {source_mix}
Bucket split: {bucket_split}

Top themes by theme_score:
{theme_lines or "- No themes available."}

## Slide 3 - Representative voices

{quotes}

## Slide 4 - Prioritized problem + proposed solution

Prioritized problem: Operator to complete based on the highest-scoring complaint theme and supporting quotes.

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
            "language": review.language,
            "english_gloss": review.english_gloss,
            "bucket": review.bucket,
            "theme": review.theme,
            "severity": review.severity,
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
            "language",
            "english_gloss",
            "bucket",
            "theme",
            "severity",
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
            "language",
            "english_gloss",
            "bucket",
            "theme",
            "severity",
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
