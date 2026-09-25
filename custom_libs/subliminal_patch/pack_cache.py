# coding=utf-8
"""Short-lived in-memory cache of downloaded subtitle archives (season/multi-episode packs).

One pack can hold the subtitles of many episodes: caching the archive lets every episode read its member without
downloading the pack again. Entries expire after a TTL and the cache is bounded in size; concurrent requests for the
same pack wait for a single download.
"""
import logging
import threading
import time
from collections import OrderedDict

logger = logging.getLogger(__name__)


class PackCache:
    def __init__(self, max_bytes=200 * 1024 * 1024, ttl=3600):
        self._lock = threading.Lock()
        self._entries = OrderedDict()  # key -> (content, expires)
        self._fetching = {}  # key -> Event set once the download is done
        self._size = 0
        self.enabled = False
        self.max_bytes = max_bytes
        self.ttl = ttl

    def configure(self, enabled, max_megabytes=200, ttl_minutes=60):
        with self._lock:
            self.enabled = bool(enabled)
            self.max_bytes = max(1, int(max_megabytes)) * 1024 * 1024
            self.ttl = max(1, int(ttl_minutes)) * 60
            if not self.enabled:
                self._entries.clear()
                self._size = 0
            else:
                self._evict()

    def _evict(self):
        now = time.monotonic()
        for key in [key for key, (_, expires) in self._entries.items() if expires <= now]:
            self._size -= len(self._entries.pop(key)[0])
        while self._size > self.max_bytes and self._entries:
            _, (content, _) = self._entries.popitem(last=False)
            self._size -= len(content)

    def get(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            content, expires = entry
            if expires <= time.monotonic():
                self._size -= len(self._entries.pop(key)[0])
                return None
            self._entries.move_to_end(key)
            return content

    def put(self, key, content):
        if not self.enabled or not content:
            return
        with self._lock:
            if len(content) > self.max_bytes:
                return
            if key in self._entries:
                self._size -= len(self._entries.pop(key)[0])
            self._entries[key] = (content, time.monotonic() + self.ttl)
            self._size += len(content)
            self._evict()

    def get_or_fetch(self, key, fetch):
        """Return the cached content for key, or call fetch() once (even when several threads ask at the same time)
        and cache its result. fetch() returning None isn't cached."""
        if not self.enabled:
            return fetch()

        while True:
            content = self.get(key)
            if content is not None:
                logger.debug("Pack cache hit for %s", key)
                return content
            with self._lock:
                event = self._fetching.get(key)
                if event is None:
                    event = self._fetching[key] = threading.Event()
                    owner = True
                else:
                    owner = False
            if owner:
                try:
                    content = fetch()
                    self.put(key, content)
                    return content
                finally:
                    with self._lock:
                        self._fetching.pop(key, None)
                    event.set()
            # another thread is downloading the same pack: wait for it, then read the cache (or fetch ourselves if it
            # failed)
            event.wait(120)
            content = self.get(key)
            if content is not None:
                return content
            return fetch()


pack_cache = PackCache()
