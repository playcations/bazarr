# coding=utf-8
# fmt: off

import ast
import logging

from datetime import datetime, timedelta

from app.config import settings


def is_search_active(desired_language, attempt_string):
    """
    Function to test if it's time to search again after a previous attempt matching the desired language. For 3 weeks,
    we search on a scheduled basis but after 3 weeks we start searching only once a week.

    @param desired_language: 2 letters language to search for in attempts
    @type desired_language: str
    @param attempt_string: string representation of a list of lists from database column failedAttempts
    @type attempt_string: str

    @return: return True if it's time to search again and False if not
    @rtype: bool
    """

    if settings.general.adaptive_searching:
        logging.debug("Adaptive searching is enable, we'll see if it's time to search again...")
        try:
            # let's try to get a list of lists from the string representation in database
            attempts = ast.literal_eval(attempt_string)
            if type(attempts) is not list:
                # attempts should be a list if not, it's malformed or None
                raise ValueError
        except ValueError:
            logging.debug("Adaptive searching: attempts is malformed. As a failsafe, search will run.")
            return True

        if not len(attempts):
            logging.debug("Adaptive searching: attempts list is empty, search will run.")
            return True

        # get attempts matching the desired language and sort them by timestamp ascending
        matching_attempts = sorted([x for x in attempts if x[0] == desired_language], key=lambda x: x[1])

        if not len(matching_attempts):
            logging.debug("Adaptive searching: there's no attempts matching desired language, search will run.")
            return True
        else:
            logging.debug(f"Adaptive searching: attempts matching language {desired_language}: {matching_attempts}")

        # try to get the initial and latest search timestamp from matching attempts
        initial_search_attempt = matching_attempts[0]
        latest_search_attempt = matching_attempts[-1]

        # try to parse the timestamps for those attempts
        try:
            initial_search_timestamp = datetime.fromtimestamp(initial_search_attempt[1])
            latest_search_timestamp = datetime.fromtimestamp(latest_search_attempt[1])
        except (OverflowError, ValueError, OSError):
            logging.debug("Adaptive searching: unable to parse initial and latest search timestamps, search will run.")
            return True
        else:
            logging.debug(f"Adaptive searching: initial search date for {desired_language} is "
                          f"{initial_search_timestamp}")
            logging.debug(f"Adaptive searching: latest search date for {desired_language} is {latest_search_timestamp}")

        # defining basic calculation variables
        now = datetime.now()
        if settings.general.adaptive_searching_delay.endswith('d'):
            extended_search_delay = timedelta(days=int(settings.general.adaptive_searching_delay[:1]))
        elif settings.general.adaptive_searching_delay.endswith('w'):
            extended_search_delay = timedelta(weeks=int(settings.general.adaptive_searching_delay[:1]))
        else:
            logging.debug(f"Adaptive searching: cannot parse adaptive_searching_delay from config file: "
                          f"{settings.general.adaptive_searching_delay}")
            return True
        logging.debug(f"Adaptive searching: delay after initial search value: {extended_search_delay}")

        if settings.general.adaptive_searching_delta.endswith('d'):
            extended_search_delta = timedelta(days=int(settings.general.adaptive_searching_delta[:1]))
        elif settings.general.adaptive_searching_delta.endswith('w'):
            extended_search_delta = timedelta(weeks=int(settings.general.adaptive_searching_delta[:1]))
        else:
            logging.debug(f"Adaptive searching: cannot parse adaptive_searching_delta from config file: "
                          f"{settings.general.adaptive_searching_delta}")
            return True
        logging.debug(f"Adaptive searching: delta between latest search and now value: {extended_search_delta}")

        if initial_search_timestamp + extended_search_delay > now:
            logging.debug(f"Adaptive searching: it's been less than {settings.general.adaptive_searching_delay} since "
                          f"initial search, search will run.")
            return True
        else:
            logging.debug(f"Adaptive searching: it's been more than {settings.general.adaptive_searching_delay} since "
                          f"initial search, let's check if it's time to search again.")
            if latest_search_timestamp + extended_search_delta <= now:
                logging.debug(
                    f"Adaptive searching: it's been more than {settings.general.adaptive_searching_delta} since "
                    f"latest search, search will run.")
                return True
            else:
                logging.debug(
                    f"Adaptive searching: it's been less than {settings.general.adaptive_searching_delta} since "
                    f"latest search, we're not ready to search yet.")
                return False

    logging.debug("adaptive searching is disabled, search will run.")
    return True


def updateFailedAttempts(desired_language, attempt_string):
    """
    Function to parse attempts and make sure we only keep initial and latest search timestamp for each language.

    @param desired_language: 2 letters language to search for in attempts
    @type desired_language: str
    @param attempt_string: string representation of a list of lists from database column failedAttempts
    @type attempt_string: str

    @return: return a string representation of a list of lists like [str(language_code), str(attempts)]
    @rtype: str
    """

    try:
        # let's try to get a list of lists from the string representation in database
        attempts = ast.literal_eval(attempt_string)
        logging.debug(f"Adaptive searching: current attempts value is {attempts}")
        if type(attempts) is not list:
            # attempts should be a list if not, it's malformed or None
            raise ValueError
    except ValueError:
        logging.debug("Adaptive searching: failed to parse attempts value, we'll use an empty list.")
        attempts = []

    matching_attempts = sorted([x for x in attempts if x[0] == desired_language], key=lambda x: x[1])
    logging.debug(f"Adaptive searching: attempts matching language {desired_language}: {matching_attempts}")

    filtered_attempts = sorted([x for x in attempts if x[0] != desired_language], key=lambda x: x[1])
    logging.debug(f"Adaptive searching: attempts not matching language {desired_language}: {filtered_attempts}")

    # get the initial search from attempts if there's one
    if len(matching_attempts):
        filtered_attempts.append(matching_attempts[0])

    # append current attempt with language and timestamp to attempts
    filtered_attempts.append([desired_language, datetime.timestamp(datetime.now())])

    updated_attempts = sorted(filtered_attempts, key=lambda x: x[0])
    logging.debug(f"Adaptive searching: updated attempts that will be saved to database is {updated_attempts}")

    return str(updated_attempts)


def filter_forced_only_languages(languages, attempt_string):
    """Drop forced languages when they are the only ones left to search and one was searched recently.

    Forced subtitles are rare: searching every provider for them on every Wanted run keeps nearly the whole library
    busy. They are still searched whenever another language of the same media is searched (they come with the same
    provider results), and at least once for new media; on their own, only every general.forced_only_search_days
    days (0 searches every time, -1 only once).

    @param languages: language codes to search, like ['en:forced']
    @param attempt_string: string representation of the failedAttempts list of lists
    @return: the languages that should be searched now
    """
    days = settings.general.forced_only_search_days
    if not days or not languages or not all(language.endswith(':forced') for language in languages):
        return languages

    try:
        attempts = ast.literal_eval(attempt_string or '[]')
        if not isinstance(attempts, list):
            raise ValueError
    except (ValueError, SyntaxError):
        return languages

    now = datetime.now()
    due = []
    for language in languages:
        timestamps = [x[1] for x in attempts if isinstance(x, (list, tuple)) and len(x) > 1 and x[0] == language]
        if not timestamps:
            # never searched: new media gets one search
            due.append(language)
            continue
        if days < 0:
            continue
        try:
            latest = datetime.fromtimestamp(max(timestamps))
        except (OverflowError, ValueError, OSError, TypeError):
            due.append(language)
            continue
        if latest + timedelta(days=days) <= now:
            due.append(language)

    if len(due) != len(languages):
        logging.debug(f"BAZARR Forced subtitles {sorted(set(languages) - set(due))} were searched recently and are "
                      f"the only missing subtitles, skipping them for now")
    return due
