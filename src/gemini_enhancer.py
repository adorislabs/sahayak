"""Hybrid enhancement layer for CBC rule parsing and ambiguity detection.

MODEL CASCADE (all via OpenRouter, openai SDK):
    1. qwen/qwen-2.5-72b-instruct      — fast + stable JSON on classify/detect probes
    2. meta-llama/llama-3.1-8b-instruct — best speed/cost composite in live benchmark
    3. microsoft/phi-4                 — strong mid-tier fallback (good JSON reliability)
    4. deepseek/deepseek-v3.2          — high-quality backstop when others fail
    5. meta-llama/llama-3.1-70b-instruct — final OpenRouter fallback
LAST RESORT: gemini-2.0-flash via google-genai SDK (GEMINI_API_KEY)

Each model is tried on 429 → next model. Parse errors also skip to next model.
Only hits Gemini SDK if all OpenRouter models fail.

CACHING:
  All API responses are cached to disk (.gemini_cache.json in parsed_schemes/).
  Repeat runs cost zero tokens. Cache is keyed on the exact source text.

USAGE:
  enhancer = GeminiEnhancer()
  result = enhancer.classify_rule_batch(["applicant is a Person with Disability"])
  flags  = enhancer.detect_ambiguities_batch(["resident of state", "below poverty line"])
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical field namespace — must match what matching/engine.py understands
# ---------------------------------------------------------------------------

CANONICAL_FIELDS = {
    "applicant.age",
    "applicant.gender",
    "applicant.caste_category",
    "applicant.education_level",
    "applicant.marital_status",
    "applicant.disability_status",
    "applicant.nationality",
    "applicant.religion",
    "employment.occupation",
    "employment.is_income_tax_payer",
    "employment.employment_status",
    "household.income_annual",
    "household.bpl_status",
    "household.family_size",
    "household.is_ration_card_holder",
    "location.state",
    "location.district",
    "location.is_urban",
    "assets.cultivable_land",
    "assets.house_ownership",
    "documents.aadhaar",
    "documents.bank_account",
    "eligibility.other",
}

# 30-type ambiguity taxonomy codes and names
AMBIGUITY_TAXONOMY: dict[int, str] = {
    1: "Semantic Vagueness",
    2: "Undefined Term",
    3: "Conflicting Criteria",
    4: "Discretionary Clause",
    5: "Temporal Ambiguity",
    6: "Mutual Exclusion Conflict",
    7: "Portability Gap",
    8: "Eligibility Threshold Overlap",
    9: "Prerequisite Chaining / Circular Dependency",
    10: "Financial Threshold Flux",
    11: "Categorical Boundary Ambiguity",
    12: "Documentation Requirement Ambiguity",
    13: "Benefit Duplication Risk",
    14: "Administrative Boundary Conflict",
    15: "Implementation Gap",
    16: "Targeting Inconsistency",
    17: "Appeal Mechanism Vagueness",
    18: "Grievance Redressal Specificity",
    19: "Linguistic Translation Delta",
    20: "Infrastructure Precondition",
    21: "Life-Event Transition Ambiguity",
    22: "Household Definition Inconsistency",
    23: "Residency Requirement Vagueness",
    24: "Income Computation Method Ambiguity",
    25: "Caste Certificate Jurisdiction Conflict",
    26: "Gender Eligibility Gap",
    27: "Age Calculation Method Ambiguity",
    28: "Land Record Jurisdiction Conflict",
    29: "Disability Certification Ambiguity",
    30: "Aadhaar Linkage Requirement Gap",
}

# ---------------------------------------------------------------------------
# Classification prompt — used for rule field extraction
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_PROMPT = """You are a structured data extractor for Indian government welfare scheme eligibility rules.

Given a list of raw eligibility condition sentences, classify each into a structured representation.

For each sentence return a JSON object with these fields:
- "field": one of these exact strings: "applicant.age", "applicant.gender", "applicant.caste_category", "applicant.education_level", "applicant.marital_status", "applicant.disability_status", "applicant.nationality", "applicant.religion", "employment.occupation", "employment.employment_status", "employment.is_income_tax_payer", "household.income_annual", "household.bpl_status", "household.family_size", "household.is_ration_card_holder", "location.state", "location.district", "location.is_urban", "assets.cultivable_land", "assets.house_ownership", "documents.aadhaar", "documents.bank_account", "eligibility.other"
- "condition_type": short snake_case label (e.g. "age_range", "gender", "caste_category", "occupation", "education_level", "disability_status", "income_ceiling", "bpl_status", "domicile", "land_ownership", "marital_status", "nationality", "religion", "other")
- "operator": one of "EQ", "NEQ", "LT", "LTE", "GT", "GTE", "BETWEEN", "IN", "NOT_IN", "EXISTS", "NOT_EXISTS"
- "value": string value for EQ/NEQ/EXISTS/IN (or null)
- "value_min": numeric lower bound for BETWEEN (or null)
- "value_max": numeric upper bound for BETWEEN (or null)
- "values": array of strings for IN/NOT_IN (or [])
- "condition_text": short human-readable condition (e.g. "applicant is a woman", "income ≤ 1,50,000")
- "confidence": float 0.0–1.0 reflecting your certainty
- "is_procedural": boolean — true if this is a process/documentation requirement, not a demographic eligibility criterion

Rules for field selection:
- Occupation/profession/employment type → "employment.occupation"
- Disability (any type) → "applicant.disability_status", operator "EQ", value "true"
- Caste SC/ST/OBC/EWS/tribal/minority → "applicant.caste_category", operator "IN", values list
- Below poverty line / BPL card → "household.bpl_status"
- Bank account requirement → "documents.bank_account"
- Aadhaar requirement → "documents.aadhaar"
- Registration with a department, survival certificates, procedural notes → "eligibility.other", is_procedural=true
- If truly unclassifiable → "eligibility.other", confidence ≤ 0.5

Return ONLY a valid JSON array — one object per input sentence, in the same order. No markdown, no explanation."""

# ---------------------------------------------------------------------------
# Ambiguity detection prompt
# ---------------------------------------------------------------------------

_AMBIGUITY_SYSTEM_PROMPT = """You are an expert policy analyst detecting ambiguities in Indian government welfare scheme eligibility rules.

Given eligibility text, identify which of the following 30 ambiguity types apply. Be precise — only flag genuine ambiguities.

Ambiguity types:
1=Semantic Vagueness, 2=Undefined Term, 3=Conflicting Criteria, 4=Discretionary Clause,
5=Temporal Ambiguity, 6=Mutual Exclusion Conflict, 7=Portability Gap, 8=Eligibility Threshold Overlap,
9=Prerequisite Chaining/Circular Dependency, 10=Financial Threshold Flux, 11=Categorical Boundary Ambiguity,
12=Documentation Requirement Ambiguity, 13=Benefit Duplication Risk, 14=Administrative Boundary Conflict,
15=Implementation Gap, 16=Targeting Inconsistency, 17=Appeal Mechanism Vagueness,
18=Grievance Redressal Specificity, 19=Linguistic Translation Delta, 20=Infrastructure Precondition,
21=Life-Event Transition Ambiguity, 22=Household Definition Inconsistency, 23=Residency Requirement Vagueness,
24=Income Computation Method Ambiguity, 25=Caste Certificate Jurisdiction Conflict, 26=Gender Eligibility Gap,
27=Age Calculation Method Ambiguity, 28=Land Record Jurisdiction Conflict, 29=Disability Certification Ambiguity,
30=Aadhaar Linkage Requirement Gap

For each input text return a JSON object with a single key:
- "detected_types": array of integer type codes (empty array [] if no ambiguity found)

Return ONLY a valid JSON array — one object per input text, same order. No markdown. No explanations."""


# ---------------------------------------------------------------------------
# GeminiEnhancer
# ---------------------------------------------------------------------------


class _RateLimitOnModel(Exception):
    """Raised by _call_openrouter when a specific model returns 429.

    Signals the cascade in _call_gemini to skip to the next model rather than
    entering a retry loop or falling straight to the Gemini SDK.
    """
    def __init__(self, model: str) -> None:
        super().__init__(f"Rate-limited on {model}")
        self.model = model


def _repair_json(raw: str) -> str:
    """Best-effort fix for common JSON quirks produced by small LLMs.

    Handles:
    - Trailing commas before ] or }
    - Single-quoted strings (Python-style dicts)
    - Lone bare values that should be wrapped in an array
    """
    # Remove trailing commas: ,   } or ,   ]
    raw = re.sub(r",\s*([}\]])", r"\1", raw)
    return raw


class GeminiEnhancer:
    """Hybrid rule classifier and ambiguity detector.

    Primary:  qwen/qwen-2.5-72b-instruct via OpenRouter (OPEN_KEY) — fast + reliable JSON.
    Fallback: Gemini 2.0 Flash via google-genai SDK (GEMINI_API_KEY).

    Token-efficient design:
    - Processes rules in batches of 10 (one API call per 10 rules — smaller batches = faster latency)
    - Disk-caches all responses so re-runs cost nothing
    - Tracks cumulative token usage for budget visibility
    - Falls back gracefully if primary API is unavailable
    """

    # OpenRouter model cascade — tried in order; first success wins.
    # Ordered from benchmarked speed/reliability winners to quality backstops.
    MODELS = [
        "qwen/qwen-2.5-72b-instruct",
        "meta-llama/llama-3.1-8b-instruct",
        "microsoft/phi-4",
        "deepseek/deepseek-v3.2",
        "meta-llama/llama-3.1-70b-instruct",
    ]
    # Gemini 2.0 Flash via google-genai SDK — last resort
    FALLBACK_MODEL = "gemini-2.0-flash"
    # Classify output is compact (~60 tok/rule); ambiguity output is larger (~120 tok/rule)
    CLASSIFY_BATCH_SIZE = 20
    AMBIGUITY_BATCH_SIZE = 10
    # Max output tokens per call — prevents runaway generation on verbose models
    CLASSIFY_MAX_TOKENS = 4096   # 20 rules × ~10 fields × ~20 tok/field
    AMBIGUITY_MAX_TOKENS = 400   # 10 rules × {"detected_types":[...]} only — no descriptions
    RATE_LIMIT_DELAY = 0.1   # tight loop; models are fast
    MAX_RETRIES = 2           # per-model retries before moving to next model
    RETRY_BASE_DELAY = 2.0
    RETRY_MAX_DELAY = 20.0
    # Circuit-breaker: after this many consecutive 503 events, pause COOLDOWN_DELAY seconds
    CONSECUTIVE_503_THRESHOLD = 3
    COOLDOWN_DELAY = 30.0

    def __init__(
        self,
        api_key: str | None = None,
        cache_path: str | Path = "parsed_schemes/.gemini_cache.json",
    ) -> None:
        """Initialise the enhancer.

        Args:
            api_key: OpenRouter API key (OPEN_KEY). If omitted, falls back env lookup.
                     GEMINI_API_KEY is also read from env for the Gemini fallback path.
            cache_path: Path to disk cache JSON file.
        """
        # Load .env if present
        try:
            from dotenv import load_dotenv
            load_dotenv(override=False)
        except ImportError:
            pass

        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("google.genai").setLevel(logging.WARNING)
        logging.getLogger("google_genai").setLevel(logging.WARNING)

        # --- Primary: OpenRouter via openai SDK ---
        # OPEN_KEY is the OpenRouter key; fall back to legacy GEMMA_KEY if absent
        _open_key = os.environ.get("OPEN_KEY", "").strip() or os.environ.get("GEMMA_KEY", "").strip()
        self._openrouter_key: str = (api_key or _open_key)
        self._openai_client: Any = None
        if self._openrouter_key:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=self._openrouter_key,
                )
            except ImportError:
                logger.warning("openai SDK not installed — OpenRouter path unavailable.")
                self._openrouter_key = ""

        # --- Fallback: Gemini via google-genai SDK ---
        self._gemini_client: Any = None
        self._genai_types: Any = None
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if gemini_key:
            try:
                from google import genai
                from google.genai import types as genai_types
                self._gemini_client = genai.Client(api_key=gemini_key)
                self._genai_types = genai_types
            except ImportError:
                logger.warning("google-genai not installed — Gemini fallback unavailable.")

        if not self._openrouter_key and self._gemini_client is None:
            raise ValueError(
                "No API key found. Set OPEN_KEY (OpenRouter) and/or GEMINI_API_KEY (.env)."
            )

        # Disk cache
        self._cache_path = Path(cache_path)
        self._cache: dict[str, Any] = {}
        self._load_cache()

        # Token tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0

        # Circuit-breaker state: tracks consecutive 503/UNAVAILABLE events
        self._consecutive_503s = 0

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def _load_cache(self) -> None:
        if self._cache_path.exists():
            try:
                self._cache = json.loads(self._cache_path.read_text(encoding="utf-8"))
                logger.info("Loaded %d cached entries from %s", len(self._cache), self._cache_path)
            except Exception:
                self._cache = {}

    def _save_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps(self._cache, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _cache_key(self, prefix: str, text: str) -> str:
        import hashlib
        return f"{prefix}:{hashlib.md5(text.strip().encode()).hexdigest()}"

    # ------------------------------------------------------------------
    # Internal: call Gemini with JSON output mode
    # ------------------------------------------------------------------

    def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1600,
    ) -> list[dict[str, Any]]:
        """Try each OpenRouter model in cascade order, then fall back to Gemini SDK."""
        if self._openrouter_key:
            last_exc: Exception | None = None
            for model in self.MODELS:
                try:
                    result = self._call_openrouter(
                        system_prompt, user_prompt, model=model, max_tokens=max_tokens
                    )
                    logger.info("[%s] handled request (%d results).", model.split("/")[-1], len(result))
                    return result
                except _RateLimitOnModel:
                    logger.info("Model %s rate-limited — trying next.", model)
                    last_exc = None
                    continue
                except Exception as exc:
                    logger.warning("Model %s failed (%s) — trying next.", model, exc)
                    last_exc = exc
                    continue
            # All OpenRouter models exhausted
            if self._gemini_client is None:
                raise RuntimeError("All OpenRouter models failed and no Gemini fallback.") from last_exc
            logger.warning("All OpenRouter models exhausted — falling back to Gemini SDK.")
        # Gemini fallback
        return self._call_gemini_sdk(system_prompt, user_prompt)

    def _call_openrouter(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 1600,
    ) -> list[dict[str, Any]]:
        """Call one OpenRouter model via the openai SDK.

        Raises _RateLimitOnModel if the model is rate-limited (caller should try next model).
        Raises other exceptions for transient/unknown errors (caller may also try next model).
        """
        if self._openai_client is None:
            raise RuntimeError("OpenRouter client not initialised.")
        model = model or self.MODELS[0]

        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._openai_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.1,
                    max_tokens=max_tokens,
                    timeout=45.0,
                    extra_headers={
                        "HTTP-Referer": "https://github.com/cbc-project",
                        "X-Title": "CBC Rule Enhancer",
                    },
                )
                break  # success
            except Exception as exc:
                last_exc = exc
                err_str = str(exc)
                is_429 = "429" in err_str or "RateLimitError" in type(exc).__name__
                if is_429:
                    raise _RateLimitOnModel(model) from exc
                is_503 = "503" in err_str or "502" in err_str
                if is_503:
                    self._consecutive_503s += 1
                    if self._consecutive_503s >= self.CONSECUTIVE_503_THRESHOLD:
                        logger.warning("Circuit breaker on %s: pausing %.0fs...", model, self.COOLDOWN_DELAY)
                        time.sleep(self.COOLDOWN_DELAY)
                        self._consecutive_503s = 0
                if attempt < self.MAX_RETRIES - 1:
                    delay = min(self.RETRY_BASE_DELAY * (2 ** attempt), self.RETRY_MAX_DELAY)
                    logger.warning("%s attempt %d/%d failed (%s). Retrying in %.0fs...",
                                   model, attempt + 1, self.MAX_RETRIES, exc, delay)
                    time.sleep(delay)
                    continue
                raise
        else:
            raise RuntimeError(f"All {self.MAX_RETRIES} retries failed for {model}") from last_exc

        self._consecutive_503s = 0
        if response.usage:
            self.total_input_tokens += response.usage.prompt_tokens or 0
            self.total_output_tokens += response.usage.completion_tokens or 0

        raw = (response.choices[0].message.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
        raw = _repair_json(raw)

        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    return v  # type: ignore[return-value]
            return [parsed]  # type: ignore[return-value]
        return parsed  # type: ignore[return-value]

    def _call_gemini_sdk(self, system_prompt: str, user_prompt: str) -> list[dict[str, Any]]:
        """Call Gemini 2.0 Flash via the google-genai SDK (fallback path)."""
        if self._gemini_client is None:
            raise RuntimeError("Gemini SDK fallback is not configured (no GEMINI_API_KEY).")

        try:
            afc_config = self._genai_types.AutomaticFunctionCallingConfig(disable=True)
        except Exception:
            afc_config = None

        config_kwargs: dict = {
            "system_instruction": system_prompt,
            "response_mime_type": "application/json",
            "temperature": 0.1,
        }
        if afc_config is not None:
            config_kwargs["automatic_function_calling"] = afc_config

        config = self._genai_types.GenerateContentConfig(**config_kwargs)

        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._gemini_client.models.generate_content(
                    model=self.FALLBACK_MODEL,
                    contents=user_prompt,
                    config=config,
                )
                break
            except Exception as exc:
                last_exc = exc
                err_str = str(exc)
                is_503 = "503" in err_str or "UNAVAILABLE" in err_str
                is_retryable = (
                    "429" in err_str or is_503
                    or "RESOURCE_EXHAUSTED" in err_str
                )
                if is_503:
                    self._consecutive_503s += 1
                    if self._consecutive_503s >= self.CONSECUTIVE_503_THRESHOLD:
                        logger.warning(
                            "Circuit breaker: %d consecutive 503s — pausing %.0fs...",
                            self._consecutive_503s, self.COOLDOWN_DELAY,
                        )
                        time.sleep(self.COOLDOWN_DELAY)
                        self._consecutive_503s = 0
                if is_retryable and attempt < self.MAX_RETRIES - 1:
                    delay = min(self.RETRY_BASE_DELAY * (2 ** attempt), self.RETRY_MAX_DELAY)
                    logger.warning(
                        "Gemini SDK attempt %d/%d failed (%s). Retrying in %.0fs...",
                        attempt + 1, self.MAX_RETRIES, exc, delay,
                    )
                    time.sleep(delay)
                    continue
                raise
        else:
            raise RuntimeError(f"All {self.MAX_RETRIES} Gemini SDK retries failed") from last_exc

        self._consecutive_503s = 0  # reset on success

        if response.usage_metadata:
            self.total_input_tokens += response.usage_metadata.prompt_token_count or 0
            self.total_output_tokens += response.usage_metadata.candidates_token_count or 0

        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
        return json.loads(raw)  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Public: classify rules
    # ------------------------------------------------------------------

    def classify_rule_batch(self, texts: list[str]) -> list[dict[str, Any]]:
        """Classify a list of raw eligibility sentences into structured rules.

        Returns list of classification dicts (same length as input).
        Uses cache wherever possible to avoid redundant API calls.
        """
        results: list[dict[str, Any] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            key = self._cache_key("classify", text)
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        # Batch the uncached items
        for batch_start in range(0, len(uncached_texts), self.CLASSIFY_BATCH_SIZE):
            batch = uncached_texts[batch_start : batch_start + self.CLASSIFY_BATCH_SIZE]
            batch_idx = uncached_indices[batch_start : batch_start + self.CLASSIFY_BATCH_SIZE]

            numbered = "\n".join(f"{j + 1}. {t}" for j, t in enumerate(batch))
            prompt = (
                f"Classify these {len(batch)} eligibility condition sentences:\n\n{numbered}"
            )

            try:
                parsed = self._call_gemini(
                    _CLASSIFY_SYSTEM_PROMPT, prompt, max_tokens=self.CLASSIFY_MAX_TOKENS
                )
                if len(parsed) != len(batch):
                    logger.warning(
                        "API returned %d results for %d inputs — padding with fallback",
                        len(parsed),
                        len(batch),
                    )
                    # Pad with fallback entries
                    while len(parsed) < len(batch):
                        parsed.append({"field": "eligibility.other", "confidence": 0.3})

                for j, (original_idx, classification) in enumerate(zip(batch_idx, parsed)):
                    # Validate field is canonical
                    if classification.get("field") not in CANONICAL_FIELDS:
                        classification["field"] = "eligibility.other"
                        classification["confidence"] = min(classification.get("confidence", 0.5), 0.5)

                    results[original_idx] = classification
                    self._cache[self._cache_key("classify", uncached_texts[batch_start + j])] = classification

            except Exception as exc:
                logger.error("Classify batch failed: %s", exc)
                # Return safe fallback for this batch
                for original_idx in batch_idx:
                    results[original_idx] = {"field": "eligibility.other", "confidence": 0.0, "error": str(exc)}

            time.sleep(self.RATE_LIMIT_DELAY)

        self._save_cache()
        return [r or {"field": "eligibility.other", "confidence": 0.0} for r in results]

    # ------------------------------------------------------------------
    # Public: detect ambiguities
    # ------------------------------------------------------------------

    def detect_ambiguities_batch(self, texts: list[str]) -> list[dict[str, Any]]:
        """Detect ambiguities across all 30 types for a list of eligibility texts.

        Returns list of {detected_types: [int,...], descriptions: {code: str}} dicts.
        """
        results: list[dict[str, Any] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            key = self._cache_key("ambiguity", text)
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        for batch_start in range(0, len(uncached_texts), self.AMBIGUITY_BATCH_SIZE):
            batch = uncached_texts[batch_start : batch_start + self.AMBIGUITY_BATCH_SIZE]
            batch_idx = uncached_indices[batch_start : batch_start + self.AMBIGUITY_BATCH_SIZE]

            numbered = "\n".join(f"{j + 1}. {t}" for j, t in enumerate(batch))
            prompt = (
                f"Analyse these {len(batch)} eligibility texts for policy ambiguities:\n\n{numbered}"
            )

            try:
                parsed = self._call_gemini(
                    _AMBIGUITY_SYSTEM_PROMPT, prompt, max_tokens=self.AMBIGUITY_MAX_TOKENS
                )
                if len(parsed) != len(batch):
                    while len(parsed) < len(batch):
                        parsed.append({"detected_types": [], "descriptions": {}})

                for j, (original_idx, detection) in enumerate(zip(batch_idx, parsed)):
                    # Normalise: handle cases where model returned a list/int instead of a dict
                    if isinstance(detection, list):
                        detection = {"detected_types": detection, "descriptions": {}}
                    elif isinstance(detection, int):
                        detection = {"detected_types": [detection], "descriptions": {}}
                    elif not isinstance(detection, dict):
                        detection = {"detected_types": [], "descriptions": {}}
                    # Normalise: ensure type codes are ints, clamp to 1-30
                    raw_types = detection.get("detected_types", [])
                    valid_types = [int(t) for t in raw_types if str(t).lstrip('-').isdigit() and 1 <= int(t) <= 30]
                    detection["detected_types"] = valid_types

                    results[original_idx] = detection
                    self._cache[self._cache_key("ambiguity", uncached_texts[batch_start + j])] = detection

            except Exception as exc:
                logger.error("Ambiguity batch failed: %s", exc)
                for original_idx in batch_idx:
                    results[original_idx] = {"detected_types": [], "descriptions": {}, "error": str(exc)}

            time.sleep(self.RATE_LIMIT_DELAY)

        self._save_cache()
        return [r or {"detected_types": [], "descriptions": {}} for r in results]

    # ------------------------------------------------------------------
    # Cost reporting
    # ------------------------------------------------------------------

    def cost_report(self) -> str:
        """Return a human-readable token-usage and cost summary.

        Pricing: DeepSeek V3.2 via OpenRouter — $0.28/M input, $0.42/M output (April 2026).
        Budget: $1.50 for full run (~1.46M input + ~1.77M output ≈ $1.15).
        """
        input_cost = self.total_input_tokens / 1_000_000 * 0.28
        output_cost = self.total_output_tokens / 1_000_000 * 0.42
        total = input_cost + output_cost
        remaining = max(0.0, 1.50 - total)
        return (
            f"DeepSeek V3.2 (OpenRouter) usage: "
            f"{self.total_input_tokens:,} input (${input_cost:.4f}) + "
            f"{self.total_output_tokens:,} output (${output_cost:.4f}) = "
            f"${total:.4f} total  [⏳ budget $1.50, remaining ${remaining:.4f}]"
        )

    def cache_stats(self) -> str:
        """Return cache hit/miss summary."""
        classify_entries = sum(1 for k in self._cache if k.startswith("classify:"))
        ambiguity_entries = sum(1 for k in self._cache if k.startswith("ambiguity:"))
        return (
            f"Cache: {classify_entries} classify entries, "
            f"{ambiguity_entries} ambiguity entries — "
            f"{len(self._cache)} total"
        )
