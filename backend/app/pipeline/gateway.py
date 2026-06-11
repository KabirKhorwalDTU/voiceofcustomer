import asyncio
import json
import random
import re
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

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
    progress_events: List[Dict[str, Any]] = None
    path: str = "sync"
    batch_probe: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.malformed_retries is None:
            self.malformed_retries = []
        if self.progress_events is None:
            self.progress_events = []
        if self.batch_probe is None:
            self.batch_probe = {}


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


GLOBAL_BUCKET = TokenBucket(rate_per_minute=13)
SECRET_PATTERNS = (
    re.compile(r"key=([^&\\s'\\\"]+)"),
    re.compile(r"AQ\\.[A-Za-z0-9_-]+"),
    re.compile(r"Bearer\\s+[A-Za-z0-9._-]+"),
)


def redact_llm_error(value: Union[Exception, str]) -> str:
    text = str(value)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(_redact_match, text)
    return text


def _redact_match(match: re.Match) -> str:
    if match.group(0).startswith("key="):
        return "key=[redacted]"
    if match.group(0).startswith("Bearer "):
        return "Bearer [redacted]"
    return "[redacted]"


def _format_response_error(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return redact_llm_error(f"HTTP {response.status_code} for {response.request.url}: {json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body}")


def _format_http_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return _format_response_error(exc.response)
    return str(exc)


ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]


class LLMGateway:
    def __init__(self, config: AppConfig, settings: Any, progress_callback: Optional[ProgressCallback] = None) -> None:
        self.config = config
        self.provider = settings.provider
        self.model = settings.model
        self.batch_size = settings.batch_size
        self.usage = LLMUsage()
        self._progress_callback = progress_callback

    async def _emit_progress(self, event: str, **details: Any) -> None:
        payload = {"event": event, **details}
        self.usage.progress_events.append(payload)
        if self._progress_callback:
            await self._progress_callback(payload)

    async def discover_themes(self, sample: List[CleanReview]) -> ThemeSet:
        if self._dev_mode:
            return self._heuristic_theme_set(sample)
        prompt = {
            "task": "Discover up to 10 themes per bucket for voice-of-customer reviews.",
            "buckets": list(BUCKETS),
            "reviews": [{"text": r.text, "rating": r.rating, "source": r.source, "language": r.language} for r in sample],
            "schema": {"complaint": ["theme"], "feature_request": ["theme"], "praise": ["theme"]},
        }
        try:
            data = await self._json_call(prompt)
        except RuntimeError as exc:
            if "API_KEY is not configured" in str(exc):
                raise
            self.usage.quarantined_batches += 1
            self.usage.malformed_retries.append({"attempt": "theme_discovery_fallback", "reason": str(exc)})
            return self._heuristic_theme_set(sample)
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
            try:
                data = await self._json_call(prompt)
                return self._validate_tags(data, reviews, theme_set)
            except (RuntimeError, ValueError) as exc:
                self.usage.malformed_retries.append({"attempt": attempt + 1, "reason": str(exc)})
                if attempt == 2:
                    self.usage.quarantined_batches += 1
                    return [self._heuristic_tag(review, theme_set, quarantine=True) for review in reviews]
        return []

    async def classify_all(self, reviews: List[CleanReview], theme_set: ThemeSet) -> Tuple[List[Tag], LLMUsage]:
        if reviews and self.provider == "gemini" and not self._dev_mode and await self._batch_available():
            return await self._classify_all_batch(reviews, theme_set)
        tags: List[Tag] = []
        chunks = [reviews[index : index + self.batch_size] for index in range(0, len(reviews), self.batch_size)]
        for batch_index, batch in enumerate(chunks):
            await self._emit_progress("sync_batch_started", batch_index=batch_index, total_batches=len(chunks), batch_size=len(batch))
            self.usage.total_batches += 1
            before_quarantine = self.usage.quarantined_batches
            tags.extend(await self.classify_batch(batch, theme_set))
            await self._emit_progress(
                "sync_batch_completed",
                batch_index=batch_index,
                total_batches=len(chunks),
                batch_size=len(batch),
                quarantined=self.usage.quarantined_batches > before_quarantine,
                calls=self.usage.calls,
            )
        return tags, self.usage

    async def _batch_available(self) -> bool:
        self.usage.path = "sync"
        prompt = json.dumps({"task": "Return strict JSON.", "schema": {"ok": True}}, ensure_ascii=False)
        try:
            operation = await self._create_batch([self._generate_request(prompt, {"probe": True})], "voc-batch-probe")
            self.usage.batch_probe = {"status": "created", "operation": operation.get("name")}
            self.usage.path = "batch"
            return True
        except Exception as exc:
            self.usage.batch_probe = {"status": "sync_fallback", "reason": redact_llm_error(exc)}
            self.usage.path = "sync"
            return False

    async def _classify_all_batch(self, reviews: List[CleanReview], theme_set: ThemeSet) -> Tuple[List[Tag], LLMUsage]:
        chunks = [reviews[index : index + self.batch_size] for index in range(0, len(reviews), self.batch_size)]
        requests = []
        for index, batch in enumerate(chunks):
            prompt = self._classification_prompt(batch, theme_set)
            requests.append(self._generate_request(json.dumps(prompt, ensure_ascii=False), {"key": f"batch-{index}", "batch_index": index}))
        try:
            await self._emit_progress("batch_submit_started", total_batches=len(chunks), requests=len(requests))
            operation = await self._create_batch(requests, "voc-classification")
            self.usage.batch_probe = {
                **self.usage.batch_probe,
                "classification_operation": operation.get("name"),
                "classification_timeout_seconds": 300,
            }
            await self._emit_progress("batch_submit_completed", operation=operation.get("name"), total_batches=len(chunks))
            responses = await self._poll_batch(operation.get("name", ""), timeout_seconds=300)
            tags: List[Tag] = []
            self.usage.total_batches = len(chunks)
            for index, batch in enumerate(chunks):
                await self._emit_progress("batch_response_parse_started", batch_index=index, total_batches=len(chunks), batch_size=len(batch))
                try:
                    data = self._batch_response_json(responses[index])
                    tags.extend(self._validate_tags(data, batch, theme_set))
                    await self._emit_progress("batch_response_parse_completed", batch_index=index, total_batches=len(chunks), batch_size=len(batch), quarantined=False)
                except Exception as exc:
                    self.usage.quarantined_batches += 1
                    self.usage.malformed_retries.append({"attempt": f"batch_{index}", "reason": redact_llm_error(exc)})
                    tags.extend(self._heuristic_tag(review, theme_set, quarantine=True) for review in batch)
                    await self._emit_progress("batch_response_parse_completed", batch_index=index, total_batches=len(chunks), batch_size=len(batch), quarantined=True, error=redact_llm_error(exc))
            self.usage.path = "batch"
            return tags, self.usage
        except Exception as exc:
            self.usage.batch_probe = {**self.usage.batch_probe, "classification_fallback": redact_llm_error(exc)}
            self.usage.path = "sync"
            await self._emit_progress("batch_classification_fallback", error=redact_llm_error(exc), total_batches=len(chunks))
            tags: List[Tag] = []
            for batch_index, batch in enumerate(chunks):
                await self._emit_progress("sync_batch_started", batch_index=batch_index, total_batches=len(chunks), batch_size=len(batch))
                self.usage.total_batches += 1
                before_quarantine = self.usage.quarantined_batches
                tags.extend(await self.classify_batch(batch, theme_set))
                await self._emit_progress(
                    "sync_batch_completed",
                    batch_index=batch_index,
                    total_batches=len(chunks),
                    batch_size=len(batch),
                    quarantined=self.usage.quarantined_batches > before_quarantine,
                    calls=self.usage.calls,
                )
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
        prompt = json.dumps(payload, ensure_ascii=False)
        last_error = ""
        for attempt in range(1, 6):
            try:
                await GLOBAL_BUCKET.wait()
                self.usage.calls += 1
                if self.provider == "deepseek":
                    return await self._deepseek_call(prompt)
                return await self._gemini_call(prompt)
            except (httpx.HTTPError, JSONDecodeError, KeyError, ValueError) as exc:
                last_error = redact_llm_error(_format_http_error(exc))
                self.usage.malformed_retries.append({"attempt": attempt, "reason": last_error})
                if attempt == 5 or not self._should_retry(exc):
                    raise RuntimeError(last_error) from None
                await asyncio.sleep((2 ** (attempt - 1)) + random.uniform(0, 1.5))
        raise RuntimeError(last_error or "LLM call failed")

    def _should_retry(self, exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            return code in {429, 500, 502, 503, 504}
        return isinstance(exc, (httpx.TimeoutException, JSONDecodeError, KeyError, ValueError))

    def _classification_prompt(self, reviews: List[CleanReview], theme_set: ThemeSet) -> Dict[str, Any]:
        return {
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

    def _generate_request(self, prompt: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "request": {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
            "metadata": metadata,
        }

    async def _create_batch(self, requests: List[Dict[str, Any]], display_name: str) -> Dict[str, Any]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchGenerateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.config.gemini_api_key}
        body = {
            "batch": {
                "displayName": display_name,
                "inputConfig": {"requests": {"requests": requests}},
            }
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, json=body)
            if response.is_error:
                raise RuntimeError(_format_response_error(response))
            return response.json()

    async def _poll_batch(self, operation_name: str, timeout_seconds: int = 1800) -> List[Dict[str, Any]]:
        if not operation_name:
            raise RuntimeError("Batch operation name missing.")
        url = f"https://generativelanguage.googleapis.com/v1beta/{operation_name}"
        headers = {"x-goog-api-key": self.config.gemini_api_key}
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        async with httpx.AsyncClient(timeout=60) as client:
            while asyncio.get_running_loop().time() < deadline:
                response = await client.get(url, headers=headers)
                if response.is_error:
                    raise RuntimeError(_format_response_error(response))
                data = response.json()
                if data.get("done"):
                    if data.get("error"):
                        raise RuntimeError(json.dumps(data["error"]))
                    return self._extract_batch_responses(data)
                batch = data.get("response", {}).get("batch") or data.get("metadata", {}).get("batch") or {}
                await self._emit_progress("batch_poll", operation=operation_name, state=batch.get("state"), done=False)
                await asyncio.sleep(10)
        raise RuntimeError("Batch operation timed out.")

    def _extract_batch_responses(self, operation: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates = [
            operation.get("response", {}),
            operation.get("response", {}).get("batch", {}),
            operation.get("response", {}).get("batch", {}).get("output", {}),
            operation.get("response", {}).get("output", {}),
        ]
        for candidate in candidates:
            inline = candidate.get("output", {}).get("inlinedResponses") if isinstance(candidate.get("output"), dict) else candidate.get("inlinedResponses")
            if isinstance(inline, dict) and isinstance(inline.get("inlinedResponses"), list):
                return inline["inlinedResponses"]
            if isinstance(inline, list):
                return inline
        raise RuntimeError("Batch inline responses missing.")

    def _batch_response_json(self, item: Dict[str, Any]) -> Any:
        if item.get("error"):
            raise RuntimeError(json.dumps(item["error"]))
        response = item.get("response") or {}
        text = response["candidates"][0]["content"]["parts"][0]["text"]
        usage = response.get("usageMetadata") or {}
        self.usage.input_tokens += int(usage.get("promptTokenCount") or 0)
        self.usage.output_tokens += int(usage.get("candidatesTokenCount") or 0)
        self.usage.total_tokens += int(usage.get("totalTokenCount") or 0)
        return json.loads(text)

    async def _gemini_call(self, prompt: str) -> Any:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": self.config.gemini_api_key}
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, json=body)
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
            try:
                severity = int(item.get("severity") or 1)
            except (TypeError, ValueError):
                severity = 1
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
