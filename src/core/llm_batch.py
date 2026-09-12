"""Bounded-concurrency batching for per-clause LLM work.

A 120-clause contract must not become 120 LLM calls. Work is batched, and the
batches run under a semaphore sized to what the API actually tolerates.

The failure model matters more than the speed. `asyncio.gather` without
`return_exceptions=True` cancels sibling coroutines the moment one raises, so a
single rate-limit error would collapse an entire node to its rule engine for
every clause -- exactly the all-or-nothing failure that batching exists to
avoid. Each batch therefore degrades on its own, and the caller learns which.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Sequence

# A rate limit is transient; a bad API key is not. Retrying the first is worth a
# short wait, retrying the second is pure latency.
_TRANSIENT_MARKERS = ("429", "rate limit", "rate_limit", "too many requests", "overloaded")


def is_transient(error: BaseException) -> bool:
    text = f"{type(error).__name__} {error}".lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def chunk(items: Sequence[Any], size: int) -> List[List[Any]]:
    if size < 1:
        raise ValueError("batch size must be at least 1")
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


@dataclass
class BatchOutcome:
    """What a batched run produced, and what it lost."""

    results: List[Any] = field(default_factory=list)
    failed_batches: int = 0
    total_batches: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def all_failed(self) -> bool:
        """True only when nothing got through.

        A node sets llm_available=False on this, never on a partial failure --
        otherwise one rate-limited batch out of six would cap the confidence of
        an analysis that was mostly fine.
        """
        return self.total_batches > 0 and self.failed_batches == self.total_batches

    @property
    def degraded(self) -> bool:
        return self.failed_batches > 0


async def gather_batched(
    items: Sequence[Any],
    batch_size: int,
    worker: Callable[[List[Any]], Awaitable[Any]],
    limit: int,
    retry_transient: int = 1,
    retry_delay: float = 2.0,
) -> BatchOutcome:
    """Run `worker` over `items` in batches, at most `limit` in flight.

    Returns every successful batch result plus a count of what failed. Batches
    that fail are not retried beyond `retry_transient` attempts, and only when
    the error looks like a rate limit.
    """
    outcome = BatchOutcome()
    if not items:
        return outcome

    batches = chunk(items, batch_size)
    outcome.total_batches = len(batches)
    semaphore = asyncio.Semaphore(max(1, limit))

    async def guarded(batch: List[Any]) -> Any:
        async with semaphore:
            attempts = 0
            while True:
                try:
                    return await worker(batch)
                except Exception as error:
                    attempts += 1
                    if attempts > retry_transient or not is_transient(error):
                        raise
                    await asyncio.sleep(retry_delay * attempts)

    settled = await asyncio.gather(
        *(guarded(batch) for batch in batches), return_exceptions=True
    )

    for result in settled:
        if isinstance(result, BaseException):
            outcome.failed_batches += 1
            outcome.errors.append(f"{type(result).__name__}: {result}"[:200])
        else:
            outcome.results.append(result)
    return outcome
