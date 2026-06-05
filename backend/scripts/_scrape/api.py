"""Low-level MediaWiki API client: rate limiting and retry logic."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

USER_AGENT = (
    "terra-mind-research/0.1 "
    "(Terraria AI companion, academic; https://github.com/bmislol/terra-mind)"
)

# Seconds to sleep between batch requests (1 req/s politeness budget).
RATE_SLEEP = 1.0

# Retry policy: base delay doubles each attempt.
_RETRY_BASE = 2.0
_RETRY_MAX_ATTEMPTS = 3

# Per-request timeout.
_TIMEOUT = httpx.Timeout(30.0)


class ApiError(RuntimeError):
    pass


def _should_retry(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def get_json(
    client: httpx.Client,
    url: str,
    params: dict[str, str | int],
) -> dict[str, Any]:
    """GET url with params, retry on 429/5xx, return parsed JSON."""
    last_exc: Exception | None = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError as exc:
            last_exc = exc
            _backoff(attempt)
            continue

        if response.status_code == 200:
            return response.json()  # type: ignore[no-any-return]

        if _should_retry(response.status_code):
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    time.sleep(float(retry_after))
                except ValueError:
                    _backoff(attempt)
            else:
                _backoff(attempt)
            last_exc = ApiError(f"HTTP {response.status_code} from {url}")
            continue

        raise ApiError(f"HTTP {response.status_code} from {url} (not retried)")

    raise ApiError(f"Exhausted {_RETRY_MAX_ATTEMPTS} attempts for {url}") from last_exc


def _backoff(attempt: int) -> None:
    time.sleep(_RETRY_BASE * (2**attempt))


@contextmanager
def make_client() -> Iterator[httpx.Client]:
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=_TIMEOUT,
        follow_redirects=True,
    ) as client:
        yield client
