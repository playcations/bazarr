# coding=utf-8
"""Per-provider limits shared by every search running in the process.

Each provider gets a lane allowing at most ``max_in_flight`` concurrent operations (listing or downloading) and
optionally a minimum interval between the start of two operations. Limits are disabled until configure() is called
with enabled=True, in which case every provider without an explicit override uses the default limit.
"""
import logging
import threading
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class _Lane:
    def __init__(self, max_in_flight, min_interval):
        self.max_in_flight = max(1, int(max_in_flight))
        self.min_interval = max(0.0, float(min_interval))
        self.in_flight = 0
        # items a scheduler has assigned to this provider, bounded like in-flight operations
        self.reserved = 0
        self.next_start = 0.0
        self.condition = threading.Condition()
        # statistics: operations, seconds spent in the provider, seconds spent waiting for the lane
        self.operations = 0
        self.busy_seconds = 0.0
        self.wait_seconds = 0.0

    def has_capacity(self):
        with self.condition:
            return self.in_flight < self.max_in_flight and time.monotonic() >= self.next_start

    def try_reserve(self):
        with self.condition:
            if self.reserved < self.max_in_flight and time.monotonic() >= self.next_start:
                self.reserved += 1
                return True
            return False

    def unreserve(self):
        with self.condition:
            self.reserved = max(0, self.reserved - 1)

    def acquire(self):
        with self.condition:
            while True:
                if self.in_flight < self.max_in_flight:
                    wait = self.next_start - time.monotonic()
                    if wait <= 0:
                        self.in_flight += 1
                        self.next_start = time.monotonic() + self.min_interval
                        return
                    self.condition.wait(wait)
                else:
                    self.condition.wait()

    def release(self):
        with self.condition:
            self.in_flight -= 1
            self.condition.notify_all()


class ProviderLimits:
    def __init__(self):
        self._lock = threading.Lock()
        self._enabled = False
        self._default = (1, 0.0)
        self._overrides = {}
        self._lanes = {}
        # a thread already holding a provider lane must not wait for a second slot of the same provider
        # (e.g. a provider downloading through its own list_subtitles code path)
        self._held = threading.local()

    @property
    def enabled(self):
        return self._enabled

    def configure(self, enabled, default_max_in_flight=1, overrides=None):
        """overrides: iterable of "provider:max_in_flight[:min_interval_ms]" strings."""
        parsed = {}
        for entry in overrides or []:
            try:
                parts = str(entry).strip().split(':')
                name = parts[0].strip().lower()
                max_in_flight = int(parts[1]) if len(parts) > 1 and parts[1].strip() else default_max_in_flight
                min_interval = float(parts[2]) / 1000 if len(parts) > 2 and parts[2].strip() else 0.0
            except (ValueError, IndexError):
                logger.warning("Ignoring invalid provider limit %r (expected provider:max_in_flight[:interval_ms])",
                               entry)
                continue
            if name:
                parsed[name] = (max_in_flight, min_interval)

        with self._lock:
            self._enabled = bool(enabled)
            self._default = (max(1, int(default_max_in_flight or 1)), 0.0)
            self._overrides = parsed
            # new lanes are created lazily with the new limits; in-flight operations finish on the old ones
            self._lanes = {}
        logger.debug("Provider limits %s (default %s, overrides %s)", "enabled" if enabled else "disabled",
                     self._default, parsed)

    def _lane(self, provider):
        with self._lock:
            lane = self._lanes.get(provider)
            if lane is None:
                lane = _Lane(*self._overrides.get(provider, self._default))
                self._lanes[provider] = lane
            return lane

    def has_capacity(self, provider):
        if not self._enabled:
            return True
        return self._lane(provider).has_capacity()

    def try_reserve(self, provider):
        """Claim the provider for one item without waiting. Returns a lane to pass to unreserve(), False if the
        provider is busy, or True when limits are disabled."""
        if not self._enabled:
            return True
        lane = self._lane(provider)
        return lane if lane.try_reserve() else False

    @staticmethod
    def unreserve(reservation):
        if isinstance(reservation, _Lane):
            reservation.unreserve()

    @contextmanager
    def slot(self, provider):
        held = getattr(self._held, 'providers', None)
        if held is None:
            held = self._held.providers = set()
        if not self._enabled or provider in held:
            yield
            return

        lane = self._lane(provider)
        waiting_since = time.monotonic()
        lane.acquire()
        started = time.monotonic()
        held.add(provider)
        try:
            yield
        finally:
            held.discard(provider)
            lane.release()
            with lane.condition:
                lane.operations += 1
                lane.busy_seconds += time.monotonic() - started
                lane.wait_seconds += started - waiting_since

    def stats(self):
        """Per provider: (operations, average seconds per operation, average seconds waiting for the lane)."""
        with self._lock:
            lanes = dict(self._lanes)
        result = {}
        for name, lane in sorted(lanes.items()):
            with lane.condition:
                if lane.operations:
                    result[name] = (lane.operations, round(lane.busy_seconds / lane.operations, 2),
                                    round(lane.wait_seconds / lane.operations, 2))
        return result


provider_limits = ProviderLimits()
