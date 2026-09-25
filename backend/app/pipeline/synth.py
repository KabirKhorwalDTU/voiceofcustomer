from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timezone
from io import BytesIO, StringIO
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from openpyxl import Workbook

from app.models import Company, Review, Run, Theme
from app.pipeline.text_quality import (
    has_firsthand_experience,
    is_marketplace_listing,
    is_non_experiential_signal,
)


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


_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "is", "it",
    "of", "on", "or", "the", "this", "to", "with", "without", "their", "they", "your", "our", "i", "we",
}
_ISSUE_CONCEPTS = {
    "signal": {"signal", "coverage", "reception", "bars"},
    "network": {"network", "connectivity", "connection", "service", "signal", "coverage"},
    "speed": {"speed", "speeds", "slow", "slower", "sluggish", "lag", "laggy", "latency", "buffering", "throttling"},
    "internet": {"internet", "data", "broadband", "wifi", "wi-fi"},
    "fiber": {"fiber", "fibre", "airfiber", "airfibre"},
    "disconnect": {"disconnect", "disconnected", "disconnection", "disconnections", "outage", "outages", "down", "drops", "dropped", "los"},
    "unstable": {"unstable", "intermittent", "fluctuating", "fluctuates", "drops", "dropped"},
    "call": {"call", "calls", "calling", "voice"},
    "unavailable": {"unavailable", "inaccessible", "unreachable", "unable", "cannot", "missing", "absent", "dead"},
    "poor": {"poor", "weak", "bad", "worst", "terrible", "unusable", "unreliable", "lost", "missing"},
    "fail": {"fail", "fails", "failed", "failure", "failing", "error", "errors", "unsuccessful", "declined"},
    "broken": {"broken", "broke", "stopped", "notworking", "unusable"},
    "delay": {"delay", "delays", "delayed", "waiting", "wait", "pending", "late", "long"},
    "unresolved": {"unresolved", "unsolved"},
    "crash": {"crash", "crashes", "crashed", "freezes", "freeze", "hangs", "hanging", "glitch", "glitches"},
    "charge": {"charge", "charges", "charged", "overcharge", "overcharges", "overcharged", "deduct", "deducted", "debit", "debited"},
    "unauthorized": {"unauthorized", "unapproved", "without", "consent", "permission", "didn't", "never"},
    "hidden": {"hidden", "undisclosed", "unexpected", "surprise", "extra", "unknown"},
    "incorrect": {"incorrect", "wrong", "mismatch", "inaccurate", "invalid", "different"},
    "reflect": {"reflect", "reflecting", "reflected", "unposted", "unreflected"},
    "unresponsive": {"unresponsive", "ignored", "ignoring", "stuck", "loop", "loops"},
    "unprofessional": {"unprofessional", "rude", "impolite", "careless", "unhelpful", "misbehaved"},
    "confusing": {"confusing", "confused", "unclear", "difficult", "hard", "complicated"},
    "transparency": {"transparency", "unclear", "misleading", "undisclosed", "confusing"},
    "support": {"support", "customer", "care", "help"},
    "agent": {"agent", "agents", "human", "executive", "representative", "person"},
    "chatbot": {"chatbot", "chatbots", "bot", "bots", "chat"},
    "technician": {"technician", "technicians", "engineer", "engineers", "installer", "staff"},
    "ticket": {"ticket", "tickets", "complaint", "complaints", "request", "requests"},
    "recharge": {"recharge", "recharged", "topup", "top-up"},
    "payment": {"payment", "payments", "transaction", "transactions", "money"},
    "refund": {"refund", "refunded", "reversal", "reversed"},
    "billing": {"billing", "bill", "bills", "billed", "invoice"},
    "app": {"app", "application", "software"},
    "login": {"login", "log", "sign", "signin"},
    "otp": {"otp", "code", "verification"},
    "plan": {"plan", "plans", "pack", "subscription", "validity"},
    "installation": {"installation", "install", "installed", "setup", "activation"},
    "cancellation": {"cancel", "cancellation", "cancelled", "discontinue", "disconnected"},
    "router": {"router", "modem", "device"},
    "bank": {"bank", "banking", "account", "upi"},
}
_ISSUE_ANCHORS = {
    "speed", "disconnect", "unstable", "unavailable", "poor", "fail", "broken", "delay", "unresolved", "crash",
    "unauthorized", "hidden", "incorrect", "reflect", "unresponsive", "unprofessional", "confusing", "transparency",
}
_GENERIC_LABEL_WORDS = {
    "customer", "customers", "service", "services", "experience", "issues", "issue", "problem",
    "problems", "frequent", "lack", "of", "strength", "long", "poor", "unstable", "broken",
    "ai", "mobile", "request", "process", "difficulties", "difficulty", "and", "after", "zone", "zones",
    "not", "no", "never", "visit", "visits", "human", "payment", "payments",
}


def _label_concepts(label: str) -> Tuple[set[str], set[str]]:
    label_tokens = set(re.findall(r"[a-z0-9]+", (label or "").replace("_", " ").lower())) - _STOP_WORDS
    matched = {concept for concept, variants in _ISSUE_CONCEPTS.items() if label_tokens & variants}
    anchors = matched & _ISSUE_ANCHORS
    remaining = label_tokens - _GENERIC_LABEL_WORDS - {word for variants in _ISSUE_CONCEPTS.values() for word in variants}
    return matched, anchors | remaining


def _issue_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    if re.search(r"\b(?:no|without|lost)\s+(?:mobile\s+)?(?:signal|coverage|network|internet|service|access|connection)\b", text, re.I):
        tokens.add("unavailable")
        tokens.add("poor")
    if re.search(r"\blost\s+(?:[a-z]+\s+){0,2}(?:signal|coverage|network|connection)\b", text, re.I):
        tokens.add("unavailable")
        tokens.add("poor")
    if re.search(r"\b(?:not|never|still not|hasn't|wasn't)\s+(?:been\s+)?(?:resolved|fixed|solved)\b", text, re.I):
        tokens.add("unresolved")
    if re.search(r"\b(?:not|never|still not|hasn't|wasn't)\s+(?:been\s+)?(?:reflected|credited|posted|received)\b", text, re.I):
        tokens.add("unposted")
    if re.search(r"\b(?:not|never|doesn't|didn't|won't)\s+(?:ever\s+)?(?:respond|reply|answer|resolve)\b|\bno (?:response|reply)\b", text, re.I):
        tokens.add("unresponsive")
    return tokens


def _supports_label(text: str, label: str) -> bool:
    if not text or (label or "").strip(" ._").casefold() in {"", "other", "general feedback"}:
        return False
    tokens = _issue_tokens(text)
    concepts, issue_terms = _label_concepts(label)
    matched = {concept for concept in concepts if tokens & _ISSUE_CONCEPTS[concept]}
    # A product noun alone (for example, "fiber") does not prove an outage.
    anchors = concepts & _ISSUE_ANCHORS
    if anchors and not (matched & anchors):
        return False
    domains = concepts - _ISSUE_ANCHORS
    if domains and not (matched & domains):
        return False
    unmatched_label_words = issue_terms - anchors
    if unmatched_label_words and not (tokens & unmatched_label_words):
        return False
    return bool(matched or tokens & issue_terms)


def _representative_score(review: Review, label: str, recency_window_days: int) -> float:
    text = " ".join((review.text or "").split())
    tokens = _issue_tokens(text)
    concepts, issue_terms = _label_concepts(label)
    relevance = (
        sum(bool(tokens & _ISSUE_CONCEPTS[concept]) for concept in concepts)
        + len(tokens & (issue_terms - concepts))
    ) / max(1, len(concepts) + len(issue_terms - concepts))
    word_count = len(tokens)
    informative = min(1.0, word_count / 24)
    too_short_penalty = 0.25 if word_count < 5 else 0
    first_person_bonus = 0.15 if has_firsthand_experience(text) else 0
    rating_bonus = 0.08 if review.rating in {1, 2} else 0
    recency_bonus = 0.05 * recency_weight(review.date, recency_window_days)
    return relevance * 2 + informative * 0.5 + first_person_bonus + rating_bonus + recency_bonus - too_short_penalty


def _representative_reviews(reviews: List[Review], label: str, recency_window_days: int, limit: int = 3) -> List[Review]:
    # Advice requests describe a possible need, not a customer's experienced failure.
    # Keep them out of the evidence quotes even if an older taxonomy placed them in an issue cluster.
    is_inquiry_label = any(term in (label or "").casefold() for term in ("inquiry", "question", "availability"))
    candidates = [
        review for review in reviews
        if not is_marketplace_listing(review.text)
        and (is_inquiry_label or not is_non_experiential_signal(review.text))
        and _supports_label(review.text, label)
    ]
    return sorted(
        candidates,
        key=lambda review: _representative_score(review, label, recency_window_days),
        reverse=True,
    )[:limit]


def build_theme_rows(run: Run, reviews: List[Review], source_weights: Dict[str, float], recency_window_days: int) -> List[Theme]:
    grouped: Dict[str, List[Review]] = defaultdict(list)
    for review in reviews:
        if review.theme:
            grouped[review.theme].append(review)

    rows: List[Theme] = []
    total_reviews = len([review for review in reviews if review.theme]) or 1
    for theme_name, items in grouped.items():
        l1_share = len(items) / total_reviews
        avg_severity = 0
        # Theme rank and displayed score reflect the number of selected reviews.
        # Per-source prevalence gave small social sources the same vote as large
        # review sources and could invert the actual issue distribution.
        score = 0 if theme_name.casefold() == "other" else l1_share
        top_reviews = _representative_reviews(items, theme_name, recency_window_days)
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

    rows.sort(key=lambda row: (row.theme.casefold() == "other", -row.count, row.theme))
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
        top_reviews = _representative_reviews(items, label, recency_window_days)
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
    rated = [review.rating for review in reviews if review.rating is not None]
    # This is intentionally a feedback-risk score, not a universal business-health
    # claim: the product deliberately prioritizes selected low-rating feedback.
    rating_risk = sum((4 - rating) / 3 for rating in rated) / len(rated) if rated else 0.65
    lead_share = float(themes[0].normalized_frequency or 0) if themes else 0
    concentration_risk = min(1.0, lead_share / 0.5)
    feedback_risk = round(100 * ((rating_risk * 0.75) + (concentration_risk * 0.25)))
    evidence_grade = "strong" if len(reviews) >= 150 and len(source_quality) >= 2 else "directional" if len(reviews) >= 40 else "early"
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
            for theme in [item for item in themes if item.theme.casefold() != "other"][:10]
        ],
        "completeness": run.completeness,
        "cost_estimate": run.cost_estimate,
        "dedup_ratio": run.dedup_ratio,
        "quarantine_rate": run.quarantine_rate,
        "feedback_risk": {
            "score": feedback_risk,
            "label": "Customer feedback risk",
            "evidence_grade": evidence_grade,
            "method": "Weighted selected-review rating risk (75%) and concentration of the strongest recurring issue (25%).",
            "scope": "Based on selected public feedback, not a universal measure of business health.",
        },
        "insight_summary": run.insight_summary or {},
    }


def build_report_snapshot(
    company: Company,
    run: Run,
    themes: List[Theme],
    summary: Dict[str, Any],
    cost_rollup: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """Serialize report presentation data once, after synthesis has finished."""
    snapshot_summary = dict(summary)
    snapshot_summary["cost_rollup"] = cost_rollup or {}
    theme_rows = [
        {
            "id": theme.id,
            "theme": theme.theme,
            "count": int(theme.count or 0),
            "normalized_frequency": float(theme.normalized_frequency or 0),
            "share": float(theme.normalized_frequency or 0),
            "theme_score": float(theme.theme_score or 0),
            "rank": int(theme.rank or 0),
            "top_quotes": list(theme.top_quotes or []),
            "l2_subthemes": list(theme.l2_subthemes or []),
        }
        for theme in themes
    ]
    return {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": snapshot_summary,
        "themes": theme_rows,
        "deck_spec": build_deck_spec(company, run, [], themes, summary=snapshot_summary),
    }


def volume_over_time(reviews: Iterable[Review]) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for review in reviews:
        if review.date:
            counts[review.date.isoformat()[:7]] += 1
    return dict(sorted(counts.items()))


def build_deck_spec(company: Company, run: Run, reviews: List[Review], themes: List[Theme], summary: Optional[Dict[str, Any]] = None) -> str:
    summary = summary or build_summary(run, reviews, themes)
    goals = [str(goal) for goal in (company.analysis_goals or []) if str(goal).strip()]
    goal_sentence = "; ".join(goals) if goals else "Understand recurring customer feedback"
    headline = "No classified themes yet."
    issue_themes = [theme for theme in themes if theme.theme.casefold() != "other"]
    if issue_themes:
        top = issue_themes[0]
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
        for theme in issue_themes[:8]
    )
    l2_sections = []
    for theme in issue_themes[:2]:
        if not theme.l2_subthemes:
            continue
        lines = [
            f"- {humanize_theme(row.get('label'))}: {int(round(float(row.get('score') or 0) * 100))}% of parent ({row.get('count')} reviews)"
            for row in theme.l2_subthemes[:10]
        ]
        l2_sections.append(f"{humanize_theme(theme.theme)}\n" + "\n".join(lines))
    l2_breakdown = "\n\n".join(l2_sections) or "- No L2 sub-theme breakdown met the 5-review threshold."
    quote_lines = []
    for theme in issue_themes[:4]:
        if theme.top_quotes:
            quote = theme.top_quotes[0]
            quote_lines.append(f"- {humanize_theme(theme.theme)}: \"{quote.get('text')}\"")
    quotes = "\n".join(quote_lines) or "- No representative quotes available."

    return f"""# Deck Spec - {company.name}

## Slide 1 - About the applicant + project + headline finding

Applicant/project: Voice of Customer analysis for {company.name}. Public feedback from {source_sentence} was collected and classified into L1 issue themes and L2 sub-issues.

Listening objective: {goal_sentence}.

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
