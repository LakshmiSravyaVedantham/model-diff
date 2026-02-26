"""
retry_with_backoff.py

A production-grade retry utility with exponential backoff and optional jitter.
This is the exact function submitted to the PR review experiment documented in:
https://dev.to/lakshmisravyavedantham/i-put-gpt-4-and-claude-in-the-same-repo-and-made-them-review-each-others-prs-it-got-weird-148e
"""

import logging
import random
import time
from typing import Any, Callable, Optional, Tuple, Type, Union

logger = logging.getLogger(__name__)


def retry_with_backoff(
    func: Callable[..., Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
) -> Any:
    """
    Call `func` and retry up to `max_retries` times on failure, using
    exponential backoff with optional jitter.

    Args:
        func:         The callable to invoke. Must accept no arguments; use
                      functools.partial to bind arguments before passing.
        max_retries:  Maximum number of retry attempts after the initial call.
                      A value of 3 means up to 4 total attempts.
        base_delay:   Initial wait time in seconds between retries.
        max_delay:    Upper bound on wait time, regardless of exponential growth.
        jitter:       If True, adds uniform random noise in [0, base_delay) to
                      each sleep interval to spread retry storms.
        exceptions:   A tuple of exception types that should trigger a retry.
                      Any exception not in this tuple propagates immediately.

    Returns:
        The return value of `func` on success.

    Raises:
        The last exception raised by `func` if all retries are exhausted.

    Example:
        >>> import functools, requests
        >>> call = functools.partial(requests.get, "https://api.example.com/data")
        >>> response = retry_with_backoff(call, max_retries=5, base_delay=0.5)
    """
    last_exception: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            return func()
        except exceptions as exc:
            last_exception = exc

            if attempt == max_retries:
                logger.error(
                    "All %d retries exhausted. Last error: %s",
                    max_retries,
                    exc,
                )
                break

            delay = min(base_delay * (2 ** attempt), max_delay)
            if jitter:
                delay += random.uniform(0, base_delay)

            logger.warning(
                "Attempt %d/%d failed (%s). Retrying in %.2fs.",
                attempt + 1,
                max_retries,
                exc,
                delay,
            )
            time.sleep(delay)

    raise last_exception  # type: ignore[misc]
