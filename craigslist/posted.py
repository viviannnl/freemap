"""The true 'posted' timestamp for one posting.

The search API carries no post time at all, which is why the map's freshness is
"spotted" (when this browser first saw a posting) rather than "posted". This fills
in the real thing for the one card you opened, by reading the detail page.

Called lazily, one posting at a time - never in bulk.
"""

import logging
import re
from urllib.parse import urlparse

import requests

from .sapi import UA

log = logging.getLogger(__name__)

_DATETIME_RE = re.compile(r'datetime="([^"]+)"')


def is_craigslist(url):
    """Guard for endpoints that take a URL from the client.

    Both /api/posted and /api/building fetch a URL the browser hands them, so this
    host check is the whole thing stopping them being used as an open proxy (SSRF).
    """
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return False
    return host == "craigslist.org" or host.endswith(".craigslist.org")


def fetch_posted(url):
    """ISO timestamp string for when a posting went up, or None.

    Reads the first <time datetime=...> element on the detail page, which is the
    "posted:" line.
    """
    if not is_craigslist(url):
        return None
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return None
        match = _DATETIME_RE.search(resp.text)
        return match.group(1) if match else None
    except requests.RequestException as exc:
        log.warning("could not read posted time from %s: %s", url, exc)
        return None
