"""Faster polling for Playwright's waits (test harness only).

Playwright re-checks a waiting `expect(...)` or `locator.wait_for()` after 0, 20, 50,
100 and 100 ms, then only every 500 ms, unless the wait's timeout is at most 2.5 s
(then every 100 ms). Most of our waits end a little later than the first checks
(a camera starting, an upload, a lazy card), so each one lost up to half a second
seen by nobody: about a sixth of the suite's time.

`install()` cuts a longer wait into slices of SLICE_MS that run back to back until
the caller's own timeout is used up. Every slice polls every 100 ms; the condition,
the total timeout and the failure (the last slice's message and call log) stay the
same. Only these two calls are wrapped; actions (click, fill) keep Playwright's own
waiting. Set VB_E2E_SLOW_POLL=1 to turn it off (e.g. to compare).

Uses Playwright's private Frame class (playwright==1.63.0 is pinned in
pyproject.toml and run_webkit.sh): when it changes shape, install() does nothing and
the tests only get slower.
"""

from __future__ import annotations

import os
import time
from typing import Any

# below Playwright's 2.5 s limit for the 500 ms step (its backoff drops steps longer
# than a fifth of the timeout)
SLICE_MS = 2400.0


def install() -> bool:
    """Patch Playwright's Frame once per process. Returns whether it did."""
    if os.environ.get("VB_E2E_SLOW_POLL"):
        return False
    try:
        from playwright._impl._errors import TimeoutError as PlaywrightTimeout
        from playwright._impl._frame import Frame
    except ImportError:
        return False
    expect = getattr(Frame, "_expect", None)
    wait_for_selector = getattr(Frame, "wait_for_selector", None)
    if expect is None or wait_for_selector is None or getattr(Frame, "_vb_fastpoll", False):
        return False

    async def sliced_expect(
        self: Any, selector: Any, expression: str, options: Any, title: Any = None
    ) -> Any:
        total = options.get("timeout")
        if not total or total <= SLICE_MS:
            return await expect(self, selector, expression, options, title)
        deadline = time.monotonic() + total / 1000
        while True:
            left = (deadline - time.monotonic()) * 1000
            part = {**options, "timeout": max(1.0, min(SLICE_MS, left))}
            result = await expect(self, selector, expression, part, title)
            if not result.get("timedOut") or left <= SLICE_MS:
                return result

    async def sliced_wait_for_selector(
        self: Any,
        selector: str,
        strict: Any = None,
        timeout: Any = None,  # noqa: ASYNC109 (Playwright's own signature)
        state: Any = None,
    ) -> Any:
        total = self._timeout(timeout)
        if not total or total <= SLICE_MS:
            return await wait_for_selector(self, selector, strict, timeout, state)
        deadline = time.monotonic() + total / 1000
        while True:
            left = (deadline - time.monotonic()) * 1000
            try:
                return await wait_for_selector(
                    self, selector, strict, max(1.0, min(SLICE_MS, left)), state
                )
            except PlaywrightTimeout:
                if left <= SLICE_MS:
                    raise

    Frame._expect = sliced_expect  # type: ignore[method-assign]
    Frame.wait_for_selector = sliced_wait_for_selector  # type: ignore[method-assign]
    Frame._vb_fastpoll = True  # type: ignore[attr-defined]
    return True
