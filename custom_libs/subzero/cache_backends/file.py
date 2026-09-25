# coding=utf-8
from __future__ import absolute_import
import threading

from dogpile.cache.api import CacheBackend, NO_VALUE
from fcache.cache import FileCache


class SZFileBackend(CacheBackend):
    def __init__(self, arguments):
        self._cache = FileCache(arguments.pop("appname", None), flag=arguments.pop("flag", "c"),
                                serialize=arguments.pop("serialize", True),
                                app_cache_dir=arguments.pop("app_cache_dir", None),
                                mode=False)
        # the cache is used by searches running in parallel threads; FileCache's write buffer isn't thread-safe
        # (sync() iterates it while other threads add to it)
        self._lock = threading.RLock()

    def get(self, key):
        with self._lock:
            return self._cache.get(key, NO_VALUE)

    def get_multi(self, keys):
        with self._lock:
            return [self._cache.get(key, NO_VALUE) for key in keys]

    def set(self, key, value):
        with self._lock:
            self._cache[key] = value

    def set_multi(self, mapping):
        with self._lock:
            for key, value in mapping.items():
                self._cache[key] = value

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
                self._cache.sync()

    def clear(self):
        with self._lock:
            self._clear()

    def _clear(self):
        self._cache.clear()
        if not hasattr(self._cache, "_buffer") or self._cache._sync:
            self._cache._sync = False
            self._cache._buffer = {}

