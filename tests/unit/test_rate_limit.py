"""Tests for the per-host rate limiter timing."""

from __future__ import annotations

import time
from dataclasses import fields

from ews_ingest.core.http import RatePolicy, _HostLimiter


def test_limiter_no_wait_when_idle() -> None:
    lim = _HostLimiter(rps=10.0, burst=1)
    t0 = time.monotonic()
    lim.acquire()
    assert time.monotonic() - t0 < 0.05


def test_limiter_throttles_consecutive() -> None:
    lim = _HostLimiter(rps=20.0, burst=1)  # 50ms interval
    lim.acquire()  # first call consumes the token immediately
    t0 = time.monotonic()
    lim.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.03  # ~50ms expected, allow jitter


def test_large_burst_allows_initial_without_wait() -> None:
    lim = _HostLimiter(rps=5.0, burst=3)
    t0 = time.monotonic()
    for _ in range(3):
        lim.acquire()
    assert time.monotonic() - t0 < 0.05


def test_zero_rps_never_blocks() -> None:
    lim = _HostLimiter(rps=0.0, burst=1)
    t0 = time.monotonic()
    for _ in range(5):
        lim.acquire()
    assert time.monotonic() - t0 < 0.05


def test_rate_policy_is_frozen() -> None:
    # RatePolicy is a frozen dataclass; verify via its dataclass params rather
    # than triggering an assignment that the static checker would flag.
    params = getattr(RatePolicy, "__dataclass_params__", None)
    assert params is not None
    assert params.frozen is True
    # Sanity: the expected fields exist.
    assert {f.name for f in fields(RatePolicy)} >= {"host", "rps", "burst", "retries"}
