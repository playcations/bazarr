# coding=utf-8

import threading

from contextlib import contextmanager

_media_locks = {}
_media_locks_guard = threading.Lock()


@contextmanager
def media_lock(media_type, media_id, blocking=True):
    """Serialize subtitles searches for the same episode or movie across Wanted, webhooks and other paths.

    Yields whether the lock was acquired (always True when blocking)."""
    with _media_locks_guard:
        lock = _media_locks.setdefault((media_type, media_id), threading.RLock())
    acquired = lock.acquire(blocking)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()
