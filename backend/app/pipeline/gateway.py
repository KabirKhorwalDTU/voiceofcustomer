import asyncio
import json
import random
import re
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

import httpx

from app.config import AppConfig
from app.pipeline.types import CleanReview, MAX_L1_THEMES, MAX_L2_THEMES, Tag, ThemeSet


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


GEMINI_PRICING_PER_MILLION = {
    "gemini-3.1-flash-lite": {
        "sync": {"input": 0.25, "output": 1.50},
        "batch": {"input": 0.125, "output": 0.75},
    }
}
BATCH_POLL_TIMEOUT_SECONDS = 8 * 60 * 60
MAX_PROMPT_REVIEW_CHARS = 600
DISCOVERY_CHUNK_SIZE = 1000


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
        if len(sample) > DISCOVERY_CHUNK_SIZE:
            proposals: List[ThemeSet] = []
            chunks = [sample[index : index + DISCOVERY_CHUNK_SIZE] for index in range(0, len(sample), DISCOVERY_CHUNK_SIZE)]
            await self._emit_progress("taxonomy_chunking_started", chunks=len(chunks), review_count=len(sample))
            for index, chunk in enumerate(chunks):
                await self._emit_progress("taxonomy_chunk_started", chunk_index=index, chunks=len(chunks), review_count=len(chunk))
                proposals.append(await self._discover_themes_single(chunk, f"voc-theme-discovery-{index}", {"key": f"theme-discovery-{index}"}))
                await self._emit_progress("taxonomy_chunk_completed", chunk_index=index, chunks=len(chunks))
            return await self._consolidate_theme_sets(proposals)
        return await self._discover_themes_single(sample, "voc-theme-discovery", {"key": "theme-discovery"})

    async def _discover_themes_single(self, sample: List[CleanReview], display_name: str, metadata: Dict[str, Any]) -> ThemeSet:
        prompt = self._theme_discovery_prompt(sample)
        try:
            if self.provider == "gemini":
                data = await self._json_call_batch(prompt, display_name, metadata)
            else:
                data = await self._json_call(prompt)
        except RuntimeError as exc:
            if "API_KEY is not configured" in str(exc):
                raise
            self.usage.quarantined_batches += 1
            self.usage.malformed_retries.append({"attempt": "theme_discovery_fallback", "reason": str(exc)})
            return self._heuristic_theme_set(sample)
        return self._validate_theme_set(data)

    async def _consolidate_theme_sets(self, proposals: List[ThemeSet]) -> ThemeSet:
        if not proposals:
            return {"other": ["other"]}
        if self._dev_mode:
            merged: ThemeSet = {}
            for proposal in proposals:
                for theme, l2_values in proposal.items():
                    merged.setdefault(theme, [])
                    for value in l2_values:
                        if value not in merged[theme]:
                            merged[theme].append(value)
            return self._limit_theme_set(merged)
        prompt = {
            "task": "consolidate_l1_l2_taxonomy",
            "rules": [
                f"Merge duplicate L1 themes into at most {MAX_L1_THEMES} specific issue themes.",
                f"Each L1 must keep up to {MAX_L2_THEMES} concrete L2 sub-issues.",
                "Do not use complaint/feature_request/praise buckets.",
                "Keep labels concise snake_case.",
                "Return strict JSON only.",
            ],
            "proposed_theme_sets": [self._theme_set_payload(proposal) for proposal in proposals],
            "output": {"themes": [{"l1_theme": "snake_case_label", "l2_subthemes": ["snake_case_label"]}]},
        }
        try:
            if self.provider == "gemini":
                data = await self._json_call_batch(prompt, "voc-theme-consolidation", {"key": "theme-consolidation"})
            else:
                data = await self._json_call(prompt)
            return self._validate_theme_set(data)
        except RuntimeError as exc:
            self.usage.malformed_retries.append({"attempt": "theme_consolidation_fallback", "reason": redact_llm_error(exc)})
            merged: ThemeSet = {}
            for proposal in proposals:
                for theme, l2_values in proposal.items():
                    merged.setdefault(theme, [])
                    for value in l2_values:
                        if value not in merged[theme]:
                            merged[theme].append(value)
            return self._limit_theme_set(merged)

    async def repair_theme_set(self, other_reviews: List[CleanReview], theme_set: ThemeSet) -> ThemeSet:
        if not other_reviews:
            return theme_set
        if self._dev_mode:
            repaired = dict(theme_set)
            for theme, subthemes in self._heuristic_theme_set(other_reviews).items():
                repaired.setdefault(theme, subthemes)
            return self._limit_theme_set(repaired)
        prompt = self._theme_repair_prompt(other_reviews, theme_set)
        try:
            if self.provider == "gemini":
                data = await self._json_call_batch(prompt, "voc-theme-repair", {"key": "theme-repair"})
            else:
                data = await self._json_call(prompt)
            return self._validate_theme_set(data)
        except RuntimeError as exc:
            self.usage.malformed_retries.append({"attempt": "theme_repair_failed", "reason": redact_llm_error(exc)})
            return theme_set

    async def synthesize_mission(self, goals: List[str], focus: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
        """Create a compact, mission-aware executive readout from ranked evidence only."""
        prompt = {
            "task": "mission_aware_feedback_synthesis",
            "mission": {"goals": goals[:3], "focus": (focus or "")[:600]},
            "evidence": evidence,
            "rules": [
                "Use only the supplied evidence; do not invent facts or metrics.",
                "Answer the selected mission and optional focus directly.",
                "Keep every string concise and owner-readable.",
                "Return strict JSON only.",
            ],
            "output": {
                "headline": "max 110 characters",
                "executive_pulse": "max 420 characters",
                "recommended_actions": [{"title": "max 60 characters", "rationale": "max 150 characters"}],
            },
        }
        if self._dev_mode:
            return self._deterministic_mission_synthesis(goals, focus, evidence)
        try:
            if self.provider == "gemini":
                data = await self._json_call_batch(prompt, "voc-mission-synthesis", {"key": "mission-synthesis"})
            else:
                data = await self._json_call(prompt)
            return self._validate_mission_synthesis(data, goals, focus, evidence)
        except RuntimeError as exc:
            self.usage.malformed_retries.append({"attempt": "mission_synthesis_fallback", "reason": redact_llm_error(exc)})
            return self._deterministic_mission_synthesis(goals, focus, evidence)

    async def classify_batch(self, reviews: List[CleanReview], theme_set: ThemeSet) -> List[Tag]:
        if self._dev_mode:
            return [self._heuristic_tag(review, theme_set) for review in reviews]
        prompt = self._classification_prompt(reviews, theme_set)
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
        if reviews and self.provider == "gemini" and not self._dev_mode:
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

    async def _classify_all_batch(self, reviews: List[CleanReview], theme_set: ThemeSet) -> Tuple[List[Tag], LLMUsage]:
        self.usage.path = "batch"
        chunks = [reviews[index : index + self.batch_size] for index in range(0, len(reviews), self.batch_size)]
        requests = []
        for index, batch in enumerate(chunks):
            prompt = self._classification_prompt(batch, theme_set)
            requests.append(self._generate_request(json.dumps(prompt, ensure_ascii=False), {"key": f"batch-{index}", "batch_index": index}))
        await self._emit_progress("batch_submit_started", total_batches=len(chunks), requests=len(requests))
        operation = await self._create_batch(requests, "voc-classification")
        self.usage.batch_probe = {
            **self.usage.batch_probe,
            "classification_operation": operation.get("name"),
            "classification_timeout_seconds": BATCH_POLL_TIMEOUT_SECONDS,
            "sync_fallback": False,
        }
        await self._emit_progress("batch_submit_completed", operation=operation.get("name"), total_batches=len(chunks))
        responses = await self._poll_batch(operation.get("name", ""), timeout_seconds=BATCH_POLL_TIMEOUT_SECONDS)
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

    async def _json_call_batch(self, payload: Dict[str, Any], display_name: str, metadata: Dict[str, Any]) -> Any:
        if not self.config.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        prompt = json.dumps(payload, ensure_ascii=False)
        await self._emit_progress("batch_json_submit_started", display_name=display_name)
        operation = await self._create_batch([self._generate_request(prompt, metadata)], display_name)
        await self._emit_progress("batch_json_submit_completed", display_name=display_name, operation=operation.get("name"))
        responses = await self._poll_batch(operation.get("name", ""), timeout_seconds=BATCH_POLL_TIMEOUT_SECONDS)
        if not responses:
            raise RuntimeError("Batch JSON response missing.")
        return self._batch_response_json(responses[0])

    def _should_retry(self, exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            return code in {429, 500, 502, 503, 504}
        return isinstance(exc, (httpx.TimeoutException, JSONDecodeError, KeyError, ValueError))

    def _theme_discovery_prompt(self, sample: List[CleanReview]) -> Dict[str, Any]:
        return {
            "task": "discover_l1_l2_taxonomy",
            "max_l1_themes": MAX_L1_THEMES,
            "max_l2_subthemes_per_l1": MAX_L2_THEMES,
            "language": "Hindi/Hinglish/English allowed",
            "rules": [
                "Do not use complaint/feature_request/praise buckets.",
                "Create specific, human-meaningful L1 issue themes for low-rated customer feedback.",
                "For each L1, create concrete L2 sub-issues users are describing.",
                "Prefer a specific nearest L1 over other; reserve other for isolated or unclear feedback.",
                "Keep labels concise snake_case.",
                "Return strict JSON only.",
            ],
            "reviews": [self._review_prompt_row(index, review) for index, review in enumerate(sample, start=1)],
            "row_format": "[row_id, rating, text]",
            "output": {"themes": [{"l1_theme": "snake_case_label", "l2_subthemes": ["snake_case_label"]}]},
        }

    def _validate_mission_synthesis(self, data: Any, goals: List[str], focus: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return self._deterministic_mission_synthesis(goals, focus, evidence)
        actions = []
        for item in (data.get("recommended_actions") or [])[:3]:
            if not isinstance(item, dict):
                continue
            title = " ".join(str(item.get("title") or "").split())[:60]
            rationale = " ".join(str(item.get("rationale") or "").split())[:150]
            if title:
                actions.append({"title": title, "rationale": rationale})
        fallback = self._deterministic_mission_synthesis(goals, focus, evidence)
        return {
            "headline": " ".join(str(data.get("headline") or fallback["headline"]).split())[:110],
            "executive_pulse": " ".join(str(data.get("executive_pulse") or fallback["executive_pulse"]).split())[:420],
            "recommended_actions": actions or fallback["recommended_actions"],
            "mission": {"goals": goals[:3], "focus": (focus or "")[:600]},
        }

    def _deterministic_mission_synthesis(self, goals: List[str], focus: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
        themes = evidence.get("top_themes") or []
        lead = themes[0] if themes else {}
        label = str(lead.get("display_theme") or lead.get("theme") or "Customer feedback")
        share = round(float(lead.get("share") or 0) * 100)
        mission = goals[0] if goals else "Customer feedback review"
        focus_line = f" Focus requested: {focus.strip()[:160]}." if focus and focus.strip() else ""
        return {
            "headline": f"{label} is the strongest signal ({share}% of selected feedback).",
            "executive_pulse": f"For {mission.lower()}, start with the recurring issue behind {label.lower()} and validate it against the supporting customer quotes.{focus_line}",
            "recommended_actions": [{"title": f"Investigate {label}", "rationale": "Review the supporting quotes, isolate the repeated failure point, and assign one owner for a concrete fix."}],
            "mission": {"goals": goals[:3], "focus": (focus or "")[:600]},
        }

    def _classification_prompt(self, reviews: List[CleanReview], theme_set: ThemeSet) -> Dict[str, Any]:
        return {
            "task": "classify_reviews_l1_l2",
            "rules": [
                "Use only the supplied L1 themes and their L2 sub-issues.",
                "Prefer the nearest specific L1 theme over other.",
                "Use other only if no supplied L1 reasonably fits.",
                "Return strict JSON only.",
                "Return one row per input row.",
                "Output compact arrays in this exact order: [row_id, l1_theme, l2_theme].",
            ],
            "theme_set": self._theme_set_payload(theme_set),
            "reviews": [self._review_prompt_row(index, review) for index, review in enumerate(reviews, start=1)],
            "row_format": "[row_id, rating, text]",
            "output_format": "[row_id, l1_theme, l2_theme]",
        }

    def _theme_repair_prompt(self, other_reviews: List[CleanReview], theme_set: ThemeSet) -> Dict[str, Any]:
        return {
            "task": "repair_l1_l2_taxonomy_for_other_rows",
            "max_l1_themes": MAX_L1_THEMES,
            "max_l2_subthemes_per_l1": MAX_L2_THEMES,
            "current_theme_set": self._theme_set_payload(theme_set),
            "rules": [
                "The current classifier put these rows into other; find missing specific L1 themes or L2 sub-issues.",
                "Preserve useful existing labels, merge duplicates, and stay within the limits.",
                "Prefer adding a specific L1 only when several rows share the same issue pattern.",
                "Keep labels concise snake_case.",
                "Return strict JSON only.",
            ],
            "reviews": [self._review_prompt_row(index, review) for index, review in enumerate(other_reviews, start=1)],
            "row_format": "[row_id, rating, text]",
            "output": {"themes": [{"l1_theme": "snake_case_label", "l2_subthemes": ["snake_case_label"]}]},
        }

    def _review_prompt_row(self, row_id: int, review: CleanReview) -> List[Any]:
        return [row_id, review.rating, self._trim_prompt_text(review.text)]

    def _theme_set_payload(self, theme_set: ThemeSet) -> List[Dict[str, Any]]:
        return [
            {"l1_theme": theme, "l2_subthemes": subthemes[:MAX_L2_THEMES]}
            for theme, subthemes in theme_set.items()
        ]

    def _trim_prompt_text(self, text: str) -> str:
        compact = " ".join((text or "").split())
        if len(compact) <= MAX_PROMPT_REVIEW_CHARS:
            return compact
        return compact[:MAX_PROMPT_REVIEW_CHARS].rsplit(" ", 1)[0]

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
        transient_errors = 0
        async with httpx.AsyncClient(timeout=60) as client:
            while asyncio.get_running_loop().time() < deadline:
                try:
                    response = await client.get(url, headers=headers)
                except httpx.HTTPError as exc:
                    transient_errors += 1
                    error = redact_llm_error(_format_http_error(exc))
                    await self._emit_progress("batch_poll_retry", operation=operation_name, error=error, transient_errors=transient_errors)
                    await asyncio.sleep(min(60, 5 * transient_errors))
                    continue
                if response.is_error:
                    if response.status_code in {429, 500, 502, 503, 504}:
                        transient_errors += 1
                        error = _format_response_error(response)
                        await self._emit_progress(
                            "batch_poll_retry",
                            operation=operation_name,
                            status_code=response.status_code,
                            error=error,
                            transient_errors=transient_errors,
                        )
                        await asyncio.sleep(min(60, 5 * transient_errors))
                        continue
                    raise RuntimeError(_format_response_error(response))
                transient_errors = 0
                data = response.json()
                # The Gemini Batch API has returned both a long-running Operation
                # (`done` + `response.batch`) and a direct batch resource (`state`
                # + `output`) across API revisions. Accept either shape so a
                # completed direct batch cannot be polled forever.
                metadata = data.get("metadata") or {}
                batch = data.get("response", {}).get("batch") or metadata.get("batch") or (data if data.get("state") else metadata)
                state = str(batch.get("state") or "")
                normalized_state = state.upper()
                if normalized_state.endswith("SUCCEEDED"):
                    return self._extract_batch_responses(batch)
                if normalized_state.endswith(("FAILED", "CANCELLED", "EXPIRED")):
                    error = batch.get("error") or data.get("error") or {"state": state}
                    raise RuntimeError(json.dumps(error))
                if data.get("done"):
                    if data.get("error"):
                        raise RuntimeError(json.dumps(data["error"]))
                    return self._extract_batch_responses(data)
                await self._emit_progress(
                    "batch_poll",
                    operation=operation_name,
                    state=state or None,
                    batch_stats=batch.get("batchStats") or {},
                    done=False,
                )
                await asyncio.sleep(10)
        raise RuntimeError("Batch operation timed out.")

    def _extract_batch_responses(self, operation: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates = [
            operation,
            operation.get("batch", {}),
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
        input_tokens = int(usage.get("promptTokenCount") or 0)
        output_tokens = int(usage.get("candidatesTokenCount") or 0)
        self._record_token_usage(input_tokens, output_tokens, int(usage.get("totalTokenCount") or 0), "batch")
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
        input_tokens = int(usage.get("promptTokenCount") or 0)
        output_tokens = int(usage.get("candidatesTokenCount") or 0)
        self._record_token_usage(input_tokens, output_tokens, int(usage.get("totalTokenCount") or 0), "sync")
        return json.loads(text)

    def _record_token_usage(self, input_tokens: int, output_tokens: int, total_tokens: int, path: str) -> None:
        self.usage.input_tokens += input_tokens
        self.usage.output_tokens += output_tokens
        self.usage.total_tokens += total_tokens
        pricing = GEMINI_PRICING_PER_MILLION.get(self.model, {}).get(path)
        if pricing:
            self.usage.cost_usd += (
                (input_tokens / 1_000_000) * pricing["input"]
                + (output_tokens / 1_000_000) * pricing["output"]
            )

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
        raw_themes = data.get("themes") or data.get("theme_set") or data.get("items")
        result: ThemeSet = {}
        if isinstance(raw_themes, dict):
            for theme, subthemes in raw_themes.items():
                label = self._normalize_theme_label(theme)
                values = subthemes if isinstance(subthemes, list) else []
                result[label] = [self._normalize_theme_label(value) for value in values if str(value).strip()]
        elif isinstance(raw_themes, list):
            for item in raw_themes:
                if isinstance(item, str):
                    label = self._normalize_theme_label(item)
                    result[label] = []
                elif isinstance(item, dict):
                    label = self._normalize_theme_label(item.get("l1_theme") or item.get("theme") or item.get("label"))
                    values = item.get("l2_subthemes") or item.get("subthemes") or item.get("l2") or []
                    result[label] = [self._normalize_theme_label(value) for value in values if str(value).strip()]
        else:
            for theme, subthemes in data.items():
                if isinstance(subthemes, list):
                    label = self._normalize_theme_label(theme)
                    result[label] = [self._normalize_theme_label(value) for value in subthemes if str(value).strip()]
        return self._limit_theme_set(result)

    def _limit_theme_set(self, theme_set: ThemeSet) -> ThemeSet:
        result: ThemeSet = {}
        for theme, subthemes in theme_set.items():
            label = self._normalize_theme_label(theme)
            if not label or label == "other":
                continue
            clean_l2: List[str] = []
            for value in subthemes:
                normalized = self._normalize_theme_label(value)
                if normalized and normalized != "other" and normalized not in clean_l2:
                    clean_l2.append(normalized)
            if not clean_l2:
                clean_l2 = [label]
            result[label] = clean_l2[:MAX_L2_THEMES]
            if len(result) >= MAX_L1_THEMES - 1:
                break
        result["other"] = ["other"]
        return result

    def _validate_tags(self, data: Any, reviews: List[CleanReview], theme_set: ThemeSet) -> List[Tag]:
        if isinstance(data, dict):
            data = data.get("tags") or data.get("items") or data.get("reviews")
        if not isinstance(data, list):
            raise ValueError("tags must be a list")
        by_hash: Dict[str, Dict[str, Any]] = {}
        by_row_id: Dict[int, Dict[str, Any]] = {}
        for item in data:
            parsed = self._parse_tag_item(item)
            if not parsed:
                continue
            if parsed.get("review_hash"):
                by_hash[str(parsed["review_hash"])] = parsed
            if parsed.get("row_id") is not None:
                try:
                    by_row_id[int(parsed["row_id"])] = parsed
                except (TypeError, ValueError):
                    continue
        tags: List[Tag] = []
        for index, review in enumerate(reviews, start=1):
            item = by_hash.get(review.review_hash) or by_row_id.get(index)
            if not item:
                self.usage.malformed_retries.append({"attempt": "row_fallback", "reason": "missing review tag", "review_hash": review.review_hash})
                tags.append(self._heuristic_tag(review, theme_set))
                continue
            theme = self._normalize_theme_label(item.get("theme") or item.get("l1_theme") or "other")
            if theme not in theme_set:
                theme = "other"
            l2_theme = self._normalize_theme_label(item.get("l2_theme") or item.get("subtheme") or item.get("l2") or "")
            allowed_l2 = theme_set.get(theme, [])
            if not l2_theme or l2_theme not in set(allowed_l2):
                l2_theme = allowed_l2[0] if allowed_l2 else "other"
            tags.append(
                Tag(
                    review_hash=review.review_hash,
                    theme=theme,
                    l2_theme=l2_theme,
                )
            )
        return tags

    def _normalize_theme_label(self, value: Any) -> str:
        label = str(value or "").strip().lower()
        label = re.sub(r"[^a-z0-9]+", "_", label)
        label = re.sub(r"_+", "_", label).strip("_")
        return label or "other"

    def _parse_tag_item(self, item: Any) -> Optional[Dict[str, Any]]:
        if isinstance(item, dict):
            row_id = item.get("row_id", item.get("id", item.get("i")))
            return {
                "row_id": row_id,
                "review_hash": item.get("review_hash"),
                "theme": item.get("l1_theme", item.get("theme")),
                "l2_theme": item.get("l2_theme", item.get("subtheme", item.get("l2"))),
            }
        if isinstance(item, list) and len(item) >= 3:
            return {"row_id": item[0], "theme": item[1], "l2_theme": item[2]}
        return None

    def _heuristic_theme_set(self, sample: List[CleanReview]) -> ThemeSet:
        return {
            "payments_or_refunds": ["refund_not_processed", "payment_debited_without_service", "cashback_or_offer_missing"],
            "login_or_kyc": ["otp_or_login_failure", "kyc_upload_or_verification_failure"],
            "support_quality": ["support_unresponsive", "ticket_closed_without_resolution", "call_or_chat_quality"],
            "app_reliability": ["crash_or_freeze", "slow_loading", "feature_not_working"],
            "pricing_or_fees": ["overpriced_products", "hidden_charges", "promotions_not_applied"],
            "delivery_or_service_fulfillment": ["late_delivery_or_arrival", "slot_or_booking_failure", "service_not_delivered"],
            "quality_or_professionalism": ["poor_product_quality", "staff_unprofessional", "incomplete_or_wrong_work"],
            "other": ["other"],
        }

    def _heuristic_tag(self, review: CleanReview, theme_set: ThemeSet, quarantine: bool = False) -> Tag:
        text = review.text.lower()
        theme = "other"
        l2_theme = "other"
        theme_rules = [
            ("payments_or_refunds", "payment_debited_without_service", ["payment", "refund", "paise", "debit", "cashback", "settlement"]),
            ("login_or_kyc", "otp_or_login_failure", ["login", "kyc", "aadhaar", "otp"]),
            ("support_quality", "support_unresponsive", ["support", "customer care", "ticket", "call", "chat"]),
            ("app_reliability", "crash_or_freeze", ["crash", "hang", "freeze", "slow", "bug", "error"]),
            ("pricing_or_fees", "hidden_charges", ["price", "fee", "charge", "expensive", "cost"]),
            ("delivery_or_service_fulfillment", "late_delivery_or_arrival", ["delivery", "service", "booking", "slot", "late", "delay"]),
            ("quality_or_professionalism", "poor_product_quality", ["quality", "professional", "staff", "rotten", "wrong", "missing"]),
        ]
        for candidate, subtheme, words in theme_rules:
            if candidate in theme_set and any(word in text for word in words):
                theme = candidate
                l2_theme = subtheme if subtheme in theme_set.get(candidate, []) else next(iter(theme_set.get(candidate, [])), candidate)
                break
        if quarantine:
            theme = "other"
            l2_theme = "other"

        return Tag(
            review_hash=review.review_hash,
            theme=theme,
            l2_theme=l2_theme,
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
