"""`LlmService`: the one place that talks to a provider, and `LlmRuntime`, the
wall extension's lifecycle hook that starts its two background loops.

Every provider call goes through `LlmService.call()`: it needs the master
switch's key, passes the budget brake, writes the `llm_usage` row (also for
failures) and masks keys in error texts. The detection runner (detect.py) and
the poller (poller.py) each run in their own thread, one request at a time.
"""

from __future__ import annotations

import logging
import threading
import time
import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from ....core.clock import now_iso
from ....core.ratelimit import RateLimiter
from . import budget, crypto, redact
from .budget import Kind
from .config import LlmConfig, load_config
from .providers import BY_ID as PROVIDERS
from .providers import ProviderInfo, make_provider
from .providers.base import Provider, ProviderError, TokenUsage

if TYPE_CHECKING:
    from ....runtime import Core
    from .detect import DetectionRunner
    from .poller import Poller

log = logging.getLogger("virtubooth.llm")

T = TypeVar("T")
ProviderFactory = Callable[[str, str], Provider]

NOT_CONFIGURED = "Externe KI ist nicht eingerichtet: API-Schlüssel fehlt."
KEY_UNREADABLE = "Schlüssel ungültig, bitte neu eingeben."


class Unavailable(Exception):
    """No call possible: `code` is `llm_not_configured`, `llm_key_invalid` or
    `llm_budget_exhausted`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Ticker:
    """A daemon thread that runs `step()` (which returns the seconds until it
    wants to run again) until stopped; `poke()` runs it early."""

    def __init__(self, name: str, step: Callable[[], float]) -> None:
        self.name = name
        self._step = step
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.alive:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def poke(self) -> None:
        self._wake.set()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            # a provider call in flight ends by its own timeout (daemon thread)
            self._thread.join(timeout)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                delay = self._step()
            except Exception:
                log.exception("%s failed", self.name)
                delay = 30.0
            self._wake.wait(max(0.05, delay))
            self._wake.clear()


# the app's service per Core (weak: LlmRuntime holds the started ones)
_services: weakref.WeakValueDictionary[int, LlmService] = weakref.WeakValueDictionary()
_services_lock = threading.Lock()


class LlmService:
    def __init__(self, core: Core, provider_factory: ProviderFactory | None = None) -> None:
        from .detect import DetectionRunner
        from .poller import Poller

        self.core = core
        self.provider_factory: ProviderFactory = provider_factory or make_provider
        self.keys = crypto.KeyStore(
            core.repos.app_settings, core.settings.secret_key.get_secret_value()
        )
        self.test_limiter = RateLimiter(6, 60)
        self._cached: tuple[str, str, Provider] | None = None
        self._cache_lock = threading.Lock()
        self.poller: Poller = Poller(self)
        self.detector: DetectionRunner = DetectionRunner(self)
        with _services_lock:
            _services[id(core)] = self

    @classmethod
    def of(cls, core: Core) -> LlmService:
        """The app's service (the one LlmRuntime started), else a new, unstarted one."""
        with _services_lock:
            found = _services.get(id(core))
        if found is not None and found.core is core:
            return found
        return cls(core)

    # ---------------------------------------------------------- lifecycle

    def start(self) -> None:
        redact.install()
        self.poller.start()
        self.detector.start()

    def stop(self) -> None:
        self.detector.stop()
        self.poller.stop()

    def changed(self) -> None:
        """Config, key or properties changed: the loops look again now."""
        self.poller.poke()
        self.detector.poke()

    # ------------------------------------------------------------- state

    def config(self) -> LlmConfig:
        return load_config(self.core.repos.app_settings)

    @property
    def timezone(self) -> str:
        return self.core.settings.timezone

    def provider_info(self, config: LlmConfig) -> ProviderInfo:
        return PROVIDERS[config.provider]

    def provider(self, config: LlmConfig) -> Provider:
        """The configured provider with the stored key; Unavailable without one."""
        key = self.keys.load(config.provider)
        if key is None:
            status = self.keys.status()
            if status.set and not status.valid:
                raise Unavailable("llm_key_invalid", KEY_UNREADABLE)
            if status.set:
                raise Unavailable(
                    "llm_not_configured",
                    "Der gespeicherte Schlüssel gehört zu einem anderen Anbieter.",
                )
            raise Unavailable("llm_not_configured", NOT_CONFIGURED)
        with self._cache_lock:
            if (
                self._cached is not None
                and self._cached[0] == config.provider
                and self._cached[1] == key
            ):
                return self._cached[2]
            provider = self.provider_factory(config.provider, key)
            self._cached = (config.provider, key, provider)
            return provider

    def forget_provider(self) -> None:
        with self._cache_lock:
            self._cached = None

    def blocked_reason(self, config: LlmConfig | None = None) -> str | None:
        cfg = config or self.config()
        return budget.blocked(self.core.db, cfg.budget, self.timezone)

    # -------------------------------------------------------------- calls

    def call(
        self,
        kind: Kind,
        ref: str | None,
        fn: Callable[[Provider, str], tuple[T, TokenUsage]],
        *,
        config: LlmConfig | None = None,
    ) -> tuple[T, TokenUsage]:
        """One provider request, budget-gated and metered. Raises Unavailable
        (no key, budget reached) or ProviderError (message safe to show/store)."""
        cfg = config or self.config()
        provider = self.provider(cfg)
        reason = self.blocked_reason(cfg)
        if reason is not None:
            raise Unavailable("llm_budget_exhausted", reason)
        started = time.monotonic()
        try:
            result, usage = fn(provider, cfg.model)
        except ProviderError as exc:
            self._meter(kind, ref, cfg, exc.usage, ok=False)
            exc.message = redact.redact(exc.message)
            exc.args = (exc.message,)
            raise
        except Exception as exc:
            self._meter(kind, ref, cfg, TokenUsage(), ok=False)
            log.warning("llm %s call failed: %s", kind, redact.redact(repr(exc)))
            raise ProviderError("Unerwarteter Fehler beim KI-Aufruf.", kind="other") from None
        self._meter(kind, ref, cfg, usage, ok=True)
        log.info(
            "llm %s %s: %d in / %d out tokens, %.1f s",
            kind,
            cfg.model,
            usage.input_tokens,
            usage.output_tokens,
            time.monotonic() - started,
        )
        return result, usage

    def _meter(
        self, kind: Kind, ref: str | None, cfg: LlmConfig, usage: TokenUsage, *, ok: bool
    ) -> None:
        budget.record(
            self.core.db,
            kind=kind,
            ref=ref,
            provider=cfg.provider,
            model=cfg.model,
            usage=usage,
            ok=ok,
            timezone=self.timezone,
        )

    # ---------------------------------------------------------------- key

    def set_key(self, provider: str, key: str, *, actor: str) -> crypto.KeyStatus:
        at = now_iso()
        with self.core.db.tx():
            self.keys.put(provider, key, by=actor, at=at)
            self.core.repos.audit.log(
                actor, "llm.key", "", {"mode": "set", "provider": provider}, at=at
            )
        self.forget_provider()
        self.changed()
        return self.keys.status()

    def clear_key(self, *, actor: str) -> crypto.KeyStatus:
        at = now_iso()
        with self.core.db.tx():
            self.keys.clear()
            self.core.repos.audit.log(actor, "llm.key", "", {"mode": "clear"}, at=at)
        self.forget_provider()
        self.changed()
        return self.keys.status()

    def test_key(self) -> tuple[bool, str]:
        """Ask the provider whether key and model work (free: the models list).
        Raises Unavailable without a usable key; (False, message) on failure."""
        cfg = self.config()
        provider = self.provider(cfg)
        try:
            usage = provider.ping(cfg.model)
        except ProviderError as exc:
            self._meter("test", "key", cfg, exc.usage, ok=False)
            if exc.kind == "auth":
                raise Unavailable("llm_key_invalid", exc.message) from None
            return False, redact.redact(exc.message)
        self._meter("test", "key", cfg, usage, ok=True)
        return True, "Schlüssel funktioniert."


class LlmRuntime:
    """The wall extension's hook: starts and stops the service per app."""

    def __init__(self, provider_factory: ProviderFactory | None = None) -> None:
        self._provider_factory = provider_factory
        self._services: dict[int, LlmService] = {}
        self._lock = threading.Lock()

    def service(self, core: Core) -> LlmService:
        with self._lock:
            svc = self._services.get(id(core))
            if svc is None or svc.core is not core:
                svc = LlmService(core, self._provider_factory)
                self._services[id(core)] = svc
            return svc

    def on_start(self, core: Core) -> None:
        self.service(core).start()

    def on_stop(self, core: Core) -> None:
        with self._lock:
            svc = self._services.pop(id(core), None)
        if svc is not None:
            svc.stop()
