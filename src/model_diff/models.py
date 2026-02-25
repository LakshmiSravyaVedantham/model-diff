"""API calls to each LLM provider, run concurrently via threading."""

from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Cost table  (USD per 1 million tokens)
# ---------------------------------------------------------------------------
COST_TABLE: Dict[str, Tuple[float, float]] = {
    # model-id            input $/1M   output $/1M
    "gpt-4o":             (5.00,       15.00),
    "gpt-4o-mini":        (0.15,        0.60),
    "claude-opus-4-6":    (15.00,      75.00),
    "claude-sonnet-4-6":  (3.00,       15.00),
    "claude-haiku-4-5-20251001": (0.25,  1.25),
}

# Models that require which API key
OPENAI_MODELS = {"gpt-4o", "gpt-4o-mini"}
ANTHROPIC_MODELS = {
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-opus-4-6",
}

ALL_SUPPORTED_MODELS = OPENAI_MODELS | ANTHROPIC_MODELS

# Default model pair used when --models is not specified
DEFAULT_MODELS = ["gpt-4o", "claude-sonnet-4-6"]


@dataclass
class ModelResult:
    """Holds the result (or error) from a single model call."""

    model: str
    text: str = ""
    error: Optional[str] = None
    elapsed: float = 0.0
    # token counts (may be None if API doesn't return them)
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    # estimated cost in USD
    estimated_cost: Optional[float] = None

    @property
    def display_name(self) -> str:
        return self.model.upper().replace("-", "-")

    @property
    def token_count(self) -> int:
        """Return output tokens if available, else rough estimate from text."""
        if self.output_tokens is not None:
            return self.output_tokens
        return max(1, int(len(self.text.split()) * 1.3))

    def compute_cost(self, prompt: str) -> None:
        """Estimate USD cost based on token counts or approximations."""
        if self.model not in COST_TABLE:
            return
        input_price, output_price = COST_TABLE[self.model]

        # Use actual token counts if we have them, else estimate
        in_tok = self.input_tokens if self.input_tokens is not None else int(
            len(prompt.split()) * 1.3
        )
        out_tok = self.output_tokens if self.output_tokens is not None else int(
            len(self.text.split()) * 1.3
        )

        self.estimated_cost = (in_tok / 1_000_000 * input_price) + (
            out_tok / 1_000_000 * output_price
        )


# ---------------------------------------------------------------------------
# Provider-specific callers
# ---------------------------------------------------------------------------

def _call_openai(
    model: str,
    prompt: str,
    temperature: float,
    result: ModelResult,
) -> None:
    """Call OpenAI chat completions and populate *result* in place."""
    try:
        import openai  # noqa: PLC0415
    except ImportError:
        result.error = "openai package not installed. Run: pip install openai"
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        result.error = "OPENAI_API_KEY environment variable is not set."
        return

    client = openai.OpenAI(api_key=api_key)
    t0 = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        result.elapsed = time.monotonic() - t0
        choice = response.choices[0]
        result.text = choice.message.content or ""
        if response.usage:
            result.input_tokens = response.usage.prompt_tokens
            result.output_tokens = response.usage.completion_tokens
    except openai.AuthenticationError:
        result.elapsed = time.monotonic() - t0
        result.error = "OpenAI authentication failed. Check your OPENAI_API_KEY."
    except openai.RateLimitError:
        result.elapsed = time.monotonic() - t0
        result.error = "OpenAI rate limit exceeded. Try again later."
    except openai.APIConnectionError as exc:
        result.elapsed = time.monotonic() - t0
        result.error = f"OpenAI connection error: {exc}"
    except Exception as exc:  # noqa: BLE001
        result.elapsed = time.monotonic() - t0
        result.error = f"OpenAI error: {exc}"


def _call_anthropic(
    model: str,
    prompt: str,
    temperature: float,
    result: ModelResult,
) -> None:
    """Call Anthropic messages API and populate *result* in place."""
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        result.error = "anthropic package not installed. Run: pip install anthropic"
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        result.error = "ANTHROPIC_API_KEY environment variable is not set."
        return

    client = anthropic.Anthropic(api_key=api_key)
    t0 = time.monotonic()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        result.elapsed = time.monotonic() - t0
        result.text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
        result.input_tokens = response.usage.input_tokens
        result.output_tokens = response.usage.output_tokens
    except anthropic.AuthenticationError:
        result.elapsed = time.monotonic() - t0
        result.error = "Anthropic authentication failed. Check your ANTHROPIC_API_KEY."
    except anthropic.RateLimitError:
        result.elapsed = time.monotonic() - t0
        result.error = "Anthropic rate limit exceeded. Try again later."
    except anthropic.APIConnectionError as exc:
        result.elapsed = time.monotonic() - t0
        result.error = f"Anthropic connection error: {exc}"
    except Exception as exc:  # noqa: BLE001
        result.elapsed = time.monotonic() - t0
        result.error = f"Anthropic error: {exc}"


# ---------------------------------------------------------------------------
# ModelRunner: dispatches to providers concurrently
# ---------------------------------------------------------------------------

class ModelRunner:
    """Runs a prompt against multiple models concurrently and returns results."""

    def __init__(self, models: List[str], temperature: float = 0.7) -> None:
        self.models = models
        self.temperature = temperature

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, prompt: str) -> List[ModelResult]:
        """
        Execute the prompt on every requested model (concurrently) and return
        a list of :class:`ModelResult` objects in the same order as self.models.
        """
        results: List[ModelResult] = [ModelResult(model=m) for m in self.models]
        threads: List[threading.Thread] = []

        for idx, model in enumerate(self.models):
            target = self._get_caller(model)
            t = threading.Thread(
                target=target,
                args=(model, prompt, self.temperature, results[idx]),
                daemon=True,
            )
            threads.append(t)

        # Fire them all simultaneously
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Post-process: compute costs for successful calls
        for result in results:
            if not result.error:
                result.compute_cost(prompt)

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_caller(model: str):  # type: ignore[return]
        if model in OPENAI_MODELS:
            return _call_openai
        if model in ANTHROPIC_MODELS:
            return _call_anthropic
        raise ValueError(
            f"Unknown model '{model}'. Supported models: "
            + ", ".join(sorted(ALL_SUPPORTED_MODELS))
        )

    @staticmethod
    def validate_models(models: List[str]) -> Tuple[List[str], List[str]]:
        """
        Return (valid_models, warnings).

        Warnings are generated for unknown models.  API-key checks are
        deferred until runtime so we can give per-model feedback.
        """
        valid: List[str] = []
        warnings: List[str] = []

        for model in models:
            if model not in ALL_SUPPORTED_MODELS:
                warnings.append(
                    f"'{model}' is not a recognised model — skipping. "
                    f"Supported: {', '.join(sorted(ALL_SUPPORTED_MODELS))}"
                )
            else:
                valid.append(model)

        return valid, warnings
