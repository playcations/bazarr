# coding=utf-8
from __future__ import absolute_import
import atexit
import threading
import time

from dogpile.cache.api import CacheBackend, NO_VALUE
from fcache.cache import FileCache


# buffered writes are flushed to disk once this many are waiting or this long after the last flush
FLUSH_EVERY_ENTRIES = 100
FLUSH_EVERY_SECONDS = 60


class SZFileBackend(CacheBackend):
    def __init__(self, arguments):
        self._cache = FileCache(arguments.pop("appname", None), flag=arguments.pop("flag", "c"),
                                serialize=arguments.pop("serialize", True),
                                app_cache_dir=arguments.pop("app_cache_dir", None),
                                mode=False)
        # the cache is used by searches running in parallel threads; FileCache's write buffer isn't thread-safe
        # (sync() iterates it while other threads add to it)
        self._lock = threading.RLock()
        self._last_sync = time.monotonic()
        # don't lose the last buffered writes when Bazarr stops
        atexit.register(self.sync)

    def get(self, key):
        with self._lock:
            return self._cache.get(key, NO_VALUE)

    def get_multi(self, keys):
        with self._lock:
            return [self._cache.get(key, NO_VALUE) for key in keys]

    def set(self, key, value):
        with self._lock:
            self._cache[key] = value
            self._flush_if_due()

    def set_multi(self, mapping):
        with self._lock:
            for key, value in mapping.items():
                self._cache[key] = value
            self._flush_if_due()

    def _flush_if_due(self):
        # writes are buffered in memory until sync(): flush regularly so they aren't only written when a caller
        # happens to sync (and aren't lost on restart)
        buffer = getattr(self._cache, "_buffer", None)
        if buffer and (len(buffer) >= FLUSH_EVERY_ENTRIES or
                       time.monotonic() - self._last_sync >= FLUSH_EVERY_SECONDS):
            self._sync()

    def delete(self, key):
        with self._lock:
            self._cache.pop(key, None)

    def delete_multi(self, keys):
        with self._lock:
            for key in keys:
                self._cache.pop(key, None)

    @property
    def all_filenames(self):
        return self._cache._all_filenames()

    def sync(self, force=False):
        with self._lock:
            if (hasattr(self._cache, "_buffer") and self._cache._buffer) or force:
                self._sync()

    def _sync(self):
        self._cache.sync()
        self._last_sync = time.monotonic()

    def clear(self):
        with self._lock:
            self._clear()

    def _clear(self):
        self._cache.clear()
        if not hasattr(self._cache, "_buffer") or self._cache._sync:
            self._cache._sync = False
            self._cache._buffer = {}

