"""Pacing for background provider calls: the sync and the stock rechecks.

TextVerified prices and checks stock one service per call, publishes no rate
limit, and says limits may change (swagger v2, "Rate Limits and Retries"). Our
customers' orders share that limit with background work. On 8 Oct 2026 the
21:15 catalogue sync burst into 46 consecutive 429s.

So background work:

* spaces its calls by an interval shared across processes and learned over
  time: doubled on a 429, eased back 10% after each success, kept between
  MIN_INTERVAL and MAX_INTERVAL - the next run starts at the pace that worked;
* stands aside for THROTTLE_SECONDS whenever *any* call to the provider,
  customer or background, is answered 429, so a customer's order is never
  queued behind a sync.

Customer calls are never delayed here; they only report a 429.
"""

from __future__ import annotations

import logging
import time

from django.core.cache import cache

logger = logging.getLogger("verifygh.provider.pacing")

# 0.25 s still drew 429s (4 in one sync on 27 Nov 2026), each costing a 10 s
# pause and risking a customer's order hitting the limit; 0.6 s prices about as
# many services per run without touching it.
START_INTERVAL = 0.6
MIN_INTERVAL = 0.6
MAX_INTERVAL = 8.0
#: After a 429, background calls wait this long before trying again.
THROTTLE_SECONDS = 10
_DAY = 24 * 3600


def _key(provider: str, name: str) -> str:
    return f"pacing:{provider}:{name}"


def _get(key: str, default):
    try:
        value = cache.get(key)
    except Exception:
        return default
    return default if value is None else value


def _set(key: str, value, seconds: int) -> None:
    try:
        cache.set(key, value, seconds)
    except Exception:
        pass


def interval(provider: str) -> float:
    return float(_get(_key(provider, "interval"), START_INTERVAL))


def throttled(provider: str) -> bool:
    # A wall-clock deadline, so every process and machine reads the same pause.
    return float(_get(_key(provider, "throttled"), 0)) > time.time()


def note_throttled(provider: str) -> None:
    """The provider answered 429: slow background work down and stand it aside."""
    _set(_key(provider, "throttled"), time.time() + THROTTLE_SECONDS, THROTTLE_SECONDS + 5)
    slower = min(max(interval(provider) * 2, START_INTERVAL), MAX_INTERVAL)
    _set(_key(provider, "interval"), slower, _DAY)


def note_ok(provider: str) -> None:
    current = interval(provider)
    eased = max(current * 0.9, MIN_INTERVAL)
    if eased != current:
        _set(_key(provider, "interval"), eased, _DAY)


def wait_turn(provider: str, deadline: float, *, clock=time.monotonic,
              sleep=time.sleep, since: float | None = None) -> bool:
    """Sleep until a background call may go out. False if the deadline passes first.

    `clock` and `sleep` come from the caller, so a test's fake clock applies.
    `since` is when the caller's previous call started (on `clock`): calls are
    spaced by the interval from start to start, so time already spent waiting
    for the last answer counts towards it. Without `since`, or just after a
    throttle, the whole interval is slept.
    """
    waited_out_throttle = False
    while throttled(provider):
        if clock() + 1 > deadline:
            return False
        sleep(1)
        waited_out_throttle = True
    pause = interval(provider)
    if since is not None and not waited_out_throttle:
        pause = max(0.0, since + pause - clock())
    if clock() + pause > deadline:
        return False
    if pause:
        sleep(pause)
    return True
