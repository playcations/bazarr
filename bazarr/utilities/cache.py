# coding=utf-8

import os
import logging
import datetime
import glob

from subliminal import region as subliminal_cache_region
from subliminal_patch.core import search_results_cache

from app.config import settings
from app.get_args import args
from app.jobs_queue import jobs_queue
from utilities.backup import sizeof_fmt


def apply_cache_settings():
    search_results_cache.configure(settings.cache.search_results_hours, settings.cache.archive_retention_days)


def get_cache_stats():
    files = list(subliminal_cache_region.backend.all_filenames) + \
        list(glob.iglob(os.path.join(args.config_dir, "*.archive")))
    size = 0
    for fn in files:
        try:
            size += os.path.getsize(fn)
        except OSError:
            pass
    return {'files': len(files), 'size': sizeof_fmt(size)}


def clear_search_results_cache():
    search_results_cache.clear()
    subliminal_cache_region.backend.sync()
    logging.info("BAZARR Cached search results have been cleared")


def clear_cache():
    subliminal_cache_region.backend.clear()
    for fn in glob.iglob(os.path.join(args.config_dir, "*.archive")):
        try:
            os.remove(fn)
        except (IOError, OSError):
            logging.debug("Couldn't remove cache file: %s", os.path.basename(fn))
    logging.info("BAZARR Cache has been cleared")


def cache_maintenance(job_id=None, wait_for_completion=False):
    if not job_id:
        jobs_queue.add_job_from_function("Performing Cache Maintenance", is_progress=False,
                                         wait_for_completion=wait_for_completion)
        return

    main_cache_validity = settings.cache.retention_days
    pack_cache_validity = settings.cache.archive_retention_days

    logging.debug("BAZARR Running cache maintenance")
    now = datetime.datetime.now()

    def remove_expired(path, expiry):
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
        if mtime + datetime.timedelta(days=expiry) < now:
            try:
                os.remove(path)
            except (IOError, OSError):
                logging.debug("Couldn't remove cache file: %s", os.path.basename(path))

    # main cache
    for fn in subliminal_cache_region.backend.all_filenames:
        remove_expired(fn, main_cache_validity)

    # archive cache
    for fn in glob.iglob(os.path.join(args.config_dir, "*.archive")):
        remove_expired(fn, pack_cache_validity)

    subliminal_cache_region.backend.sync()
    jobs_queue.update_job_name(job_id=job_id, new_job_name="Performed Cache Maintenance")


apply_cache_settings()
