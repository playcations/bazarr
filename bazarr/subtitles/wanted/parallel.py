# coding=utf-8

"""Parallel Wanted searching.

Several episodes/movies are searched at the same time, each of them one provider at a time: an item is given any
enabled provider it hasn't tried yet that currently has free capacity (see subliminal_patch.provider_limits), and
stops as soon as a provider gives an acceptable subtitle for each missing language. Better subtitles found later are
the job of the upgrade task. Throttled providers are skipped without stopping the other ones.
"""

import logging
import threading
import time

from concurrent.futures import ThreadPoolExecutor

from subliminal_patch.provider_limits import provider_limits

from app.config import settings
from app.database import database
from app.get_providers import get_providers, apply_provider_limits
from app.jobs_queue import jobs_queue

from ..locks import media_lock

WHISPER_PROVIDER = 'whisperai'

# how long to wait before checking again for a provider with free capacity
_CAPACITY_POLL_SECONDS = 0.05


class ItemBusy(Exception):
    """The item is being searched by another job, it will be retried at the end of the run."""


def run_parallel_wanted(handler, rows, job_id):
    """Search every row with the handler of its media type. Returns True if it stopped because all providers are
    throttled."""
    apply_provider_limits()

    total = len(rows)
    state = {'done': 0}
    state_lock = threading.Lock()
    all_throttled = threading.Event()
    busy_rows = []

    def completed(row):
        with state_lock:
            state['done'] += 1
            jobs_queue.update_job_progress(job_id=job_id, progress_value=state['done'], progress_max=total,
                                           progress_message=handler.label(row))

    def work(row, retry_busy=True):
        if all_throttled.is_set():
            return
        try:
            if not get_providers():
                logging.info("BAZARR All providers are throttled")
                all_throttled.set()
                return
            # on the second chance, wait for the other job to be done with the item
            search_item(handler, handler.item_id(row), wait_if_busy=not retry_busy)
        except ItemBusy:
            if retry_busy:
                with state_lock:
                    busy_rows.append(row)
                return
        except Exception:
            logging.exception(f"BAZARR Error while searching subtitles for {handler.label(row)}")
        finally:
            database.remove()
        completed(row)

    workers = max(1, int(settings.general.wanted_max_active_items))
    logging.info(f"BAZARR Searching {total} {handler.media_type} items with up to {workers} at a time")
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f'wanted_{handler.media_type}') as executor:
        list(executor.map(work, rows))

        # items another job was already searching get one more chance once it's done
        if busy_rows and not all_throttled.is_set():
            list(executor.map(lambda row: work(row, retry_busy=False), busy_rows))

    return all_throttled.is_set()


def search_item(handler, item_id, wait_if_busy=False):
    """Search one item provider by provider until every due language is found or no provider is left."""
    with media_lock(handler.media_type, item_id, blocking=wait_if_busy) as acquired:
        if not acquired:
            raise ItemBusy()

        item = handler.load(item_id)
        if not item:
            return

        searched_languages = handler.due_languages(item)
        if not searched_languages:
            return

        use_fallback = settings.general.use_whisper_fallback
        providers_at_start = set(get_providers() or [])
        tried = set()
        video_cache = {}
        remaining = searched_languages

        while remaining:
            candidates = [name for name in (get_providers() or [])
                          if name not in tried and not (use_fallback and name == WHISPER_PROVIDER)]
            if not candidates:
                break
            provider, reservation = _reserve_provider(candidates)
            tried.add(provider)
            try:
                found = handler.search(item, remaining, only_providers={provider}, video_cache=video_cache)
            finally:
                provider_limits.unreserve(reservation)
            if found:
                item = handler.load(item_id, refresh_index=False)
                remaining = _still_missing(handler, item, searched_languages)

        # whisper only transcribes once the regular providers couldn't find anything
        if remaining and use_fallback and WHISPER_PROVIDER in (get_providers() or []):
            if handler.search(item, remaining, fallback_allowed=True, only_providers={WHISPER_PROVIDER},
                              video_cache=video_cache):
                item = handler.load(item_id, refresh_index=False)
                remaining = _still_missing(handler, item, searched_languages)

        if not remaining or not item:
            return

        # a provider throttled during the search didn't really search, so this isn't a definitive miss
        available = set(get_providers() or [])
        if not providers_at_start or any(name not in available for name in providers_at_start):
            logging.debug(f"BAZARR Not updating adaptive search attempts for {item.path} because some providers "
                          f"got throttled during the search")
            return
        handler.stamp(item, remaining)


def _still_missing(handler, item, searched_languages):
    if not item:
        return []
    missing = set(handler.due_languages(item))
    return [language for language in searched_languages if language in missing]


def _reserve_provider(candidates):
    """Claim the first candidate with free capacity, in the order of enabled providers. Waits until one is free."""
    while True:
        for name in candidates:
            reservation = provider_limits.try_reserve(name)
            if reservation:
                return name, reservation
        time.sleep(_CAPACITY_POLL_SECONDS)
