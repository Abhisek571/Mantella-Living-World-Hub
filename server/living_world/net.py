"""Opening a URL with a timeout and a few tries: a rate limit (429) or a server error (5xx) is tried again after a
growing wait (1 s, then 2 s); any other failure (no network, a timeout, 404) is raised at once to the caller."""
import time
import urllib.error
import urllib.request

TRIES = 3
FIRST_WAIT = 1.0


def retryable(error: Exception) -> bool:
    """A rate limit or a server error: worth another try."""
    return isinstance(error, urllib.error.HTTPError) and (error.code == 429 or 500 <= error.code < 600)


def open_url(target, timeout: float, opener=urllib.request.urlopen, tries: int = TRIES, first_wait: float = FIRST_WAIT,
             sleep=time.sleep):
    """opener(target, timeout=timeout) (a URL or a urllib Request), tried up to `tries` times on 429 and 5xx answers.
    Returns the open response; the caller closes it (use it in a with block)."""
    for attempt in range(tries):
        try:
            return opener(target, timeout=timeout)
        except Exception as error:
            if attempt + 1 >= tries or not retryable(error):
                raise
            error.close()
            sleep(first_wait * 2 ** attempt)
