"""Performance tests: opt-in (`VB_PERF=1`), never part of the default run."""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "perf: opt-in performance tests (VB_PERF=1)")
