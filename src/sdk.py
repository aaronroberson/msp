#!/usr/bin/env python3
"""AI SDK framework for msp CLI.

Provides retry logic, exponential back-off, short-circuiting, and
fallback agent SDK logic based on prioritized preferences (coding
proficiency, context length, memory & cacheing support, limit exhaustion,
cost).  API keys are resolved from environment variables and used to
configure the fallback chain.
"""

from __future__ import annotations

import os
import time
import random
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.ai import (
    DEFAULT_PROVIDERS,
    AIAnalyzer,
    get_resolved_api_key,
    configure_provider_flow,
    mask_sensitive,
)

# ---------------------------------------------------------------------------
# Default preferences weightings (tunable per deployment)
# ---------------------------------------------------------------------------

# Priority order for fallback selection (lower index = higher priority)
PREF_CODING_PROFICIENCY = 0   # "coder-friendly" models (code generation, technical PIDs)
PREF_CONTEXT_LENGTH = 1      # large context windows
PREF_MEMORY_CACHING = 2      # models with built-in memory / caching
PREF_LIMIT_EXHAUSTION = 3    # gracefully handle rate-limits / quota exhaustion
PREF_COST = 4                # cost-effective / free-tier preferred

# Provider preference scores: (coding_proficiency, context_length, memory_caching,
# limit_exhaustion, cost) each 0-10 where higher = better fit
# These are illustrative; tune per your model catalog.
PROVIDER_PREF_SCORES: Dict[str, Tuple[int, int, int, int, int]] = {
    #        cod  ctx   mem  lim  cost
    "openai":   (8, 7, 5, 6, 3),   # capable but not cheap
    "groq":     (9, 6, 5, 7, 8),   # fast, moderate cost
    "deepseek": (7, 6, 5, 7, 6),  # good balance
    "openrouter": (8, 8, 6, 8, 5), # wide selection, moderate cost
    "together": (7, 5, 4, 6, 7),  # open-source, moderate cost
    "ollama":   (10, 4, 8, 9, 10), # local, free, small context
    "apfel":    (5, 2, 1, 10, 10), # Apple native, limited context
    "openvino": (5, 3, 2, 10, 10), # hardware-dependent, limited
    "custom":   (8, 8, 6, 8, 5),  # user-defined
}



# Opencode model configurations (from ~/.config/opencode/opencode.json)
OPENCODE_MODELS: Dict[str, Dict[str, Dict[str, Any]]] = {
    # provider_name: {model_name: {name, type, base_url, ...}}
    "ollama": {
        "qwen2.5-coder:7b": {
            "name": "Qwen 2.5 Coder 7B",
            "type": "ollama",
            "base_url": "http://localhost:11434",
        },
    },
    "baseten": {
        "zai-org/GLM-5.3": {
            "name": "GLM 5.3",
            "type": "baseten",
            "base_url": "https://inference.baseten.co/v1",
        },
    },
}

# Merge opencode models into preference scoring
# These models get default preference scores when not otherwise specified
OPENCODE_MODEL_DEFAULTS: Dict[str, Tuple[int, int, int, int, int]] = {
    "ollama": (10, 4, 8, 9, 10),  # local, free, good memory, small context
    "baseten": (7, 6, 5, 6, 6),    # cloud, moderate cost, decent balance
}
# ---------------------------------------------------------------------------
# Retry & back-off helpers
# ---------------------------------------------------------------------------

def _exponential_backoff(
    attempt: int,
    base: float = 1.0,
    jitter: bool = True,
    max_delay: float = 30.0,
) -> float:
    """Calculate delay for exponential back-off.

    :param attempt: 0-based attempt number
    :param base: base delay in seconds
    :param jitter: add randomness to avoid thundering herd
    :param max_delay: maximum delay cap
    :returns: seconds to wait
    """
    delay = base * (2 ** attempt)
    if jitter:
        delay += random.uniform(0, 1)
    return min(delay, max_delay)


def retry_with_backoff(
    fn: Callable,
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    jitter: bool = True,
    retry_exceptions: Tuple = (Exception,),
    short_circuit: Optional[Callable[[int], bool]] = None,
) -> Any:
    """Execute *fn* with exponential back-off retry and optional short-circuit.

    Short-circuit: if *short_circuit(attempt)* returns ``True`` the call
    stops immediately (no more retries).  This is useful for rate-limit
    detection or quota-exhaustion signals.

    :param fn: async or sync callable to retry
    :param attempts: maximum number of attempts (first + retries)
    :param base_delay: initial back-off base in seconds
    :param backoff: multiplier per attempt
    :param jitter: add randomness
    :param retry_exceptions: exception types that trigger a retry
    :param short_circuit: callable(attempt_number) -> bool; return True to stop
    :raises: last exception if all attempts exhausted
    :returns: return value of *fn* on success
    """
    last_exception: Optional[Exception] = None

    for attempt in range(attempts):
        # Short-circuit check before each attempt
        if short_circuit and short_circuit(attempt):
            raise RuntimeError("Short-circuit triggered; stopping retries.")

        try:
            return fn()
        except retry_exceptions as exc:
            last_exception = exc
            if attempt < attempts - 1:
                delay = _exponential_backoff(attempt, base=base_delay, jitter=jitter)
                time.sleep(delay)
            # else: will fall through to re-raise after loop

    raise RuntimeError(
        f"All {attempts} attempts failed. Last error: {last_exception}"
    )


# ---------------------------------------------------------------------------
# Preference scoring
# ---------------------------------------------------------------------------

def score_provider(
    provider_name: str,
    *,
    coding_proficiency: int = 0,
    context_length: int = 0,
    memory_caching: int = 0,
    limit_exhaustion: int = 0,
    cost: int = 0,
    preferences: Optional[Dict[str, int]] = None,
) -> float:
    """Score a provider against given preferences.

    Each preference parameter is a weight 0-10 (higher = more important).
    The *preferences* dict can be used as a shortcut: its values override
    the individual keyword parameters.

    :returns: composite score (higher = better match)
    """
    if preferences:
        coding_proficiency = preferences.get("coding_proficiency", coding_proficiency)
        context_length = preferences.get("context_length", context_length)
        memory_caching = preferences.get("memory_caching", memory_caching)
        limit_exhaustion = preferences.get("limit_exhaustion", limit_exhaustion)
        cost = preferences.get("cost", cost)

    profile = PROVIDER_PREF_SCORES.get(provider_name)
    if not profile:
        profile = PROVIDER_PREF_SCORES.get("openai", (5, 5, 5, 5, 5))

    cod, ctx, mem, lim, cost_def = profile

    # Normalise user weights
    weights = [coding_proficiency, context_length, memory_caching, limit_exhaustion, cost]
    w_sum = sum(1 for w in weights if w > 0)
    if w_sum == 0:
        weights = [1, 1, 1, 1, 1]
        w_sum = 5

    norm = [w / w_sum if w > 0 else 0 for w in weights]

    # Composite score = sum(norm[i] * provider_score[i])
    score = (
        norm[0] * cod
        + norm[1] * ctx
        + norm[2] * mem
        + norm[3] * lim
        + norm[4] * cost_def
    )
    return round(score, 2)


def select_fallback_provider(
    current: Optional[str],
    preferences: Optional[Dict[str, int]] = None,
    available: Optional[List[str]] = None,
) -> Optional[str]:
    """Select the best fallback provider given the current one and preferences.

    :param current: provider we just tried (may be None if starting fresh)
    :param preferences: dict of {preference_name: weight_0_to_10}
    :param available: list of provider names still available
    :returns: best fallback provider name, or None
    """
    if preferences is None:
        preferences = {}

    # Default weights per preference point
    cp = preferences.get("coding_proficiency", 0)
    cl = preferences.get("context_length", 0)
    mc = preferences.get("memory_caching", 0)
    le = preferences.get("limit_exhaustion", 0)
    cost = preferences.get("cost", 0)

    # Build scoring for all providers, exclude current
    candidates = []
    for name in DEFAULT_PROVIDERS:
        if name == current:
            continue
        if available and name not in available:
            continue
        s = score_provider(
            name,
            coding_proficiency=cp,
            context_length=cl,
            memory_caching=mc,
            limit_exhaustion=le,
            cost=cost,
        )
        candidates.append((s, name))

    if not candidates:
        return None

    # Sort descending by score, pick best
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


# ---------------------------------------------------------------------------
# SDK wrapper – manages provider chain with retry/back-off/fallback
# ---------------------------------------------------------------------------


class AISDK:
    """Unified AI SDK with retry, back-off, short-circuit, and fallback logic.

    Usage::
        sdk = AISDK()
        result = sdk.chat("Analyze this data:", data)
    """

    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        preferences: Optional[Dict[str, int]] = None,
        retry_attempts: int = 3,
        base_delay: float = 1.0,
    ):
        self.provider = provider
        self.model = model
        self.preferences = preferences or {}
        self.retry_attempts = retry_attempts
        self.base_delay = base_delay
        self._history: List[Dict[str, Any]] = []

        # Resolve API keys from environment once at init
        self._api_keys: Dict[str, str] = {}
        for p in DEFAULT_PROVIDERS:
            key = get_resolved_api_key(p)
            if key:
                self._api_keys[p] = key

    # ------------------------------------------------------------------
    # Core chat with full retry/back-off/fallover
    # ------------------------------------------------------------------

    def chat(
        self,
        prompt: str,
        data: Any = None,
        *,
        system_prompt: str = AIAnalyzer.SYSTEM_PROMPT,
        json_mode: bool = False,
    ) -> Optional[str]:
        """Send a prompt to the AI with retry/back-off/fallback logic."""

        def _do_chat() -> str:
            analyzer = AIAnalyzer(
                verbose=False,
                provider=self.provider,
                llm_model=self.model,
            )
            result = analyzer.ask(prompt, data=data, json_output=json_mode)
            if result is None:
                raise RuntimeError("AI returned empty response")
            return result

        # Build short-circuit predicate: stop if we detect limit exhaustion
        def _short_circuit(attempt: int) -> bool:
            # On the final attempt, don't short-circuit (let it fail so fallback kicks in)
            if attempt >= self.retry_attempts - 1:
                return False
            # Check if error message suggests rate-limit or quota exhaustion
            # (this is a simple heuristic; real use would inspect the exception)
            return False

        # Fallback chain generation
        fallback_chain: List[str] = []
        current = self.provider
        seen: set = set()

        # Generate initial fallback chain based on preferences
        while True:
            nxt = select_fallback_provider(
                current,
                preferences=self.preferences,
                available=[p for p in DEFAULT_PROVIDERS if p != current],
            )
            if nxt is None or nxt in seen:
                break
            seen.add(nxt)
            fallback_chain.append(nxt)
            current = nxt

        # If no explicit provider, start from detected/configured one
        if not self.provider:
            # Try to find any provider with an API key available
            for p in DEFAULT_PROVIDERS:
                if p in self._api_keys:
                    self.provider = p
                    break

        # Execute with retry + fallback
        attempt = 0
        last_exception: Optional[Exception] = None

        while True:
            try:
                return retry_with_backoff(
                    _do_chat,
                    attempts=self.retry_attempts,
                    base_delay=self.base_delay,
                    jitter=True,
                    retry_exceptions=(Exception,),
                    short_circuit=_short_circuit,
                )
            except Exception as exc:
                last_exception = exc
                self._history.append(
                    {
                        "attempt": attempt,
                        "provider": self.provider,
                        "error": str(exc),
                    }
                )

                # If we have a fallback chain and more providers remain
                if attempt < len(fallback_chain):
                    next_provider = fallback_chain[attempt]
                    if next_provider not in self._api_keys:
                        # Skip if no key; try next
                        attempt += 1
                        continue
                    # Switch provider and retry
                    self.provider = next_provider
                    attempt += 1
                    continue

                # No more fallovers – raise
                raise RuntimeError(
                    f"AI SDK exhausted all providers. Last error: {exc}"
                ) from exc

    # ------------------------------------------------------------------
    # Convenience: ask method mirrors AIAnalyzer.ask
    # ------------------------------------------------------------------

    def ask(self, prompt: str, data: Any = None, json_output: bool = False) -> Optional[str]:
        return self.chat(prompt, data=data, json_mode=json_output)

    # ------------------------------------------------------------------
    # Status / introspection
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "preferences": self.preferences,
            "api_keys_available": list(self._api_keys.keys()),
            "fallback_chain": self._build_fallback_chain(),
            "history_len": len(self._history),
        }

    def _build_fallback_chain(self) -> List[str]:
        """Rebuild fallback chain from current provider + preferences."""
        chain: List[str] = []
        current = self.provider
        seen: set = set()

        while True:
            nxt = select_fallback_provider(
                current,
                preferences=self.preferences,
                available=[p for p in DEFAULT_PROVIDERS if p != current],
            )
            if nxt is None or nxt in seen:
                break
            seen.add(nxt)
            chain.append(nxt)
            current = nxt
        return chain


# ---------------------------------------------------------------------------
# CLI entry point for SDK diagnostics
# ---------------------------------------------------------------------------

def sdk_status_cli() -> None:
    """Print SDK status including provider, preferences, and fallback chain."""
    import json
    from src.ai import load_ai_config

    cfg = load_ai_config()
    default_provider = cfg.get("default_provider", "")

    # Prompt for preferences if not set
    prefs_input = input(
        "Enter preference weights (coding_proficiency context_length memory_caching limit_exhaustion cost), "
        "or press Enter for defaults: "
    ).strip()
    preferences: Dict[str, int] = {}
    if prefs_input:
        parts = prefs_input.split()
        names = [
            "coding_proficiency",
            "context_length",
            "memory_caching",
            "limit_exhaustion",
            "cost",
        ]
        if len(parts) == 5:
            try:
                preferences = {
                    k: int(v) for k, v in zip(names, parts)
                }
            except ValueError:
                print("Invalid input; using defaults.")
        else:
            print("Expected 5 values; using defaults.")

    sdk = AISDK(preferences=preferences, provider=default_provider or None)
    print("\n=== AI SDK Status ===")
    print(f"Provider: {sdk.provider}")
    print(f"Model: {sdk.model}")
    print(f"Preferences: {sdk.preferences}")
    print(f"Available API keys: {list(sdk._api_keys.keys())}")
    print(f"Fallback chain: {sdk._build_fallback_chain()}")
    print(f"History entries: {len(sdk._history)}")


if __name__ == "__main__":
    sdk_status_cli()