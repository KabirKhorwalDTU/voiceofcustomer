import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import httpx

from app.config import AppConfig
from app.pipeline.types import BUCKETS, CleanReview, Tag, ThemeSet


@dataclass
class LLMUsage:
    cost_usd: float = 0
    calls: int = 0
    quarantined_batches: int = 0
    total_batches: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    malformed_retries: List[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.malformed_retries is None:
            self.malformed_retries = []


class TokenBucket:
    def __init__(self, rate_per_minute: int = 15) -> None:
        self.interval = 60 / rate_per_minute
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait_for = max(0, self._last + self.interval - now)
            if wait_for:
                await asyncio.sleep(wait_for)
            self._last = loop.time()


GLOBAL_BUCKET = TokenBucket(rate_per_minute=15)


class LLMGateway:
    def __init__(self, config: AppConfig, settings: Any) -> None:
        self.config = config
        self.provider = settings.provider
        self.model = settings.model
        self.batch_size = settings.batch_size
        self.usage = LLMUsage()

    async def discover_themes(self, sample: List[CleanReview]) -> ThemeSet:
        if self._dev_mode:
            return self._heuristic_theme_set(sample)
        prompt = {
            "task": "Discover up to 10 themes per bucket for voice-of-customer reviews.",
            "buckets": list(BUCKETS),
            "reviews": [{"text": r.text, "rating": r.rating, "source": r.source, "language": r.language} for r in sample],
            "schema": {"complaint": ["theme"], "feature_request": ["theme"], "praise": ["theme"]},
        }
        data = await self._json_call(prompt)
        return self._validate_theme_set(data)

    async def classify_batch(self, reviews: List[CleanReview], theme_set: ThemeSet) -> List[Tag]:
        if self._dev_mode:
            return [self._heuristic_tag(review, theme_set) for review in reviews]
        prompt = {
            "task": "Classify each review. Use only the supplied theme set or 'other'. Return strict JSON.",
            "severity_scale": {
                "1": "cosmetic/minor",
                "2": "blocks a task, workaround exists",
                "3": "churn, money lost, trust, or safety broken",
            },
            "theme_set": theme_set,
            "reviews": [
                {"review_hash": r.review_hash, "text": r.text, "rating": r.rating, "source": r.source, "language": r.language}
                for r in reviews
            ],
            "schema": [
                {
                    "review_hash": "string",
                    "language": "en|hi|hinglish|other",
                    "english_gloss": "string",
                    "bucket": "complaint|feature_request|praise",
                    "theme": "theme from set or other",
                    "severity": "1|2|3",
                }
            ],
        }
        for attempt in range(3):
            data = await self._json_call(prompt)
            try:
                return self._validate_tags(data, reviews, theme_set)
            except ValueError as exc:
                self.usage.malformed_retries.append({"attempt": attempt + 1, "reason": str(exc)})
                if attempt == 2:
                    self.usage.quarantined_batches += 1
                    return [self._heuristic_tag(review, theme_set, quarantine=True) for review in reviews]
        return []

    async def classify_all(self, reviews: List[CleanReview], theme_set: ThemeSet) -> Tuple[List[Tag], LLMUsage]:
        tags: List[Tag] = []
        for index in range(0, len(reviews), self.batch_size):
            batch = reviews[index : index + self.batch_size]
            self.usage.total_batches += 1
            tags.extend(await self.classify_batch(batch, theme_set))
        return tags, self.usage

    @property
    def _dev_mode(self) -> bool:
        if self.provider == "deepseek":
            return not self.config.deepseek_api_key and self.config.allow_dev_llm_fallback
        return not self.config.gemini_api_key and self.config.allow_dev_llm_fallback

    async def _json_call(self, payload: Dict[str, Any]) -> Any:
        if self.provider == "deepseek" and not self.config.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured.")
        if self.provider != "deepseek" and not self.config.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        await GLOBAL_BUCKET.wait()
        self.usage.calls += 1
        prompt = json.dumps(payload, ensure_ascii=False)
        if self.provider == "deepseek":
            return await self._deepseek_call(prompt)
        return await self._gemini_call(prompt)

    async def _gemini_call(self, prompt: str) -> Any:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        params = {"key": self.config.gemini_api_key}
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, params=params, json=body)
            response.raise_for_status()
            data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata") or {}
        self.usage.input_tokens += int(usage.get("promptTokenCount") or 0)
        self.usage.output_tokens += int(usage.get("candidatesTokenCount") or 0)
        self.usage.total_tokens += int(usage.get("totalTokenCount") or 0)
        self.usage.cost_usd += 0.0001
        return json.loads(text)

    async def _deepseek_call(self, prompt: str) -> Any:
        headers = {"Authorization": f"Bearer {self.config.deepseek_api_key}"}
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post("https://api.deepseek.com/chat/completions", headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        usage = data.get("usage") or {}
        self.usage.input_tokens += int(usage.get("prompt_tokens") or 0)
        self.usage.output_tokens += int(usage.get("completion_tokens") or 0)
        self.usage.total_tokens += int(usage.get("total_tokens") or 0)
        self.usage.cost_usd += 0.0002
        return json.loads(data["choices"][0]["message"]["content"])

    def _validate_theme_set(self, data: Any) -> ThemeSet:
        if not isinstance(data, dict):
            raise ValueError("theme set must be an object")
        result: ThemeSet = {}
        for bucket in BUCKETS:
            values = data.get(bucket, [])
            if not isinstance(values, list):
                values = []
            clean = [str(value).strip().lower().replace(" ", "_") for value in values if str(value).strip()]
            result[bucket] = (clean[:10] or ["other"]) + ([] if "other" in clean[:10] else ["other"])
        return result

    def _validate_tags(self, data: Any, reviews: List[CleanReview], theme_set: ThemeSet) -> List[Tag]:
        if isinstance(data, dict):
            data = data.get("tags") or data.get("items") or data.get("reviews")
        if not isinstance(data, list):
            raise ValueError("tags must be a list")
        by_hash = {str(item.get("review_hash")): item for item in data if isinstance(item, dict)}
        tags: List[Tag] = []
        for review in reviews:
            item = by_hash.get(review.review_hash)
            if not item:
                raise ValueError("missing review tag")
            bucket = item.get("bucket")
            if bucket not in BUCKETS:
                raise ValueError("bad bucket")
            theme = str(item.get("theme") or "other").strip().lower().replace(" ", "_")
            if theme not in theme_set[bucket]:
                theme = "other"
            severity = int(item.get("severity", 1))
            if severity not in (1, 2, 3):
                severity = 1
            tags.append(
                Tag(
                    review_hash=review.review_hash,
                    language=str(item.get("language") or review.language),
                    english_gloss=str(item.get("english_gloss") or review.text),
                    bucket=bucket,
                    theme=theme,
                    severity=severity,
                )
            )
        return tags

    def _heuristic_theme_set(self, sample: List[CleanReview]) -> ThemeSet:
        return {
            "complaint": [
                "payments_or_refunds",
                "login_or_kyc",
                "support_quality",
                "reliability",
                "pricing_or_fees",
                "other",
            ],
            "feature_request": ["analytics", "notifications", "workflow_improvement", "other"],
            "praise": ["speed_and_ease", "transparency", "support_helpfulness", "other"],
        }

    def _heuristic_tag(self, review: CleanReview, theme_set: ThemeSet, quarantine: bool = False) -> Tag:
        text = review.text.lower()
        if review.rating and review.rating >= 4:
            bucket = "praise"
        elif any(word in text for word in ["want", "need", "should", "please add", "feature", "better"]):
            bucket = "feature_request"
        elif any(word in text for word in ["love", "fast", "easy", "good", "quick", "transparent"]):
            bucket = "praise"
        else:
            bucket = "complaint"

        theme = "other"
        theme_rules = [
            ("payments_or_refunds", ["payment", "refund", "paise", "debit", "settlement"]),
            ("login_or_kyc", ["login", "kyc", "aadhaar", "otp"]),
            ("support_quality", ["support", "customer care", "ticket"]),
            ("analytics", ["analytics", "dashboard", "report"]),
            ("speed_and_ease", ["fast", "easy", "quick", "bahut easy"]),
            ("transparency", ["transparent", "fees"]),
        ]
        for candidate, words in theme_rules:
            if candidate in theme_set.get(bucket, []) and any(word in text for word in words):
                theme = candidate
                break
        if quarantine:
            theme = "other"

        severity = 1
        if bucket == "complaint":
            severity = 3 if any(word in text for word in ["money", "paise", "debit", "trust", "fraud", "churn"]) else 2
        return Tag(
            review_hash=review.review_hash,
            language=review.language,
            english_gloss=self._gloss(review.text),
            bucket=bucket,
            theme=theme,
            severity=severity,
        )

    def _gloss(self, text: str) -> str:
        replacements = {
            "nahi": "not",
            "nahin": "not",
            "paise": "money",
            "bahut": "very",
            "ho raha": "is happening",
            "kar diya": "did",
        }
        gloss = text
        for source, target in replacements.items():
            gloss = re.sub(source, target, gloss, flags=re.IGNORECASE)
        return gloss
