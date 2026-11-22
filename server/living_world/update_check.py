"""Tells the player when a newer version of an installed Living World module is on Nexus.

Each module ships data/living_world/versions/<key>.json ({"module", "version", "nexus_id"}). At most every few days
(the player's setting, 3 by default; 0 switches it off), in the background, the Hub asks Nexus's public API for those mods' current versions (one request, no key, only the mod
IDs are sent) and keeps the answer in update_check.json next to the settings. The Main Status tab compares the two.
No internet, a slow answer or a Nexus error changes nothing and is tried again at the next due check.

Living World is moving to one All in One download (Nexus mod AIO_NEXUS_ID). An install made from the separate downloads
also asks about that page in the same request and gets one line on Status (move_line): "not available yet" until the
page is public, then how to switch. An All in One install never gets it."""
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request

from . import net

VERSIONS_DIR = os.path.join('data', 'living_world', 'versions')
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'update_check.json')
API = 'https://api.nexusmods.com/v2/graphql'
GAME = 'skyrimspecialedition'
PAGE = 'https://www.nexusmods.com/skyrimspecialedition/mods/{}'
DAY = 24 * 3600
TIMEOUT = 10
AIO_NEXUS_ID = 198897  # the All in One page; its build gives the modules nexus_id 0 and adds versions/aio.json
AIO_MODULE = 'All in One'
REFUSED = {400, 403, 404}  # what Nexus may answer while the All in One page is still a draft
MOVE_NOT_YET = ("Living World is moving to a single All in One download. It is not available yet; keep using these "
                "modules for now. Your NPC overrides, memories and conversations will carry over when you switch.")
MOVE_NOW = (f"Living World now updates through the All in One download (Nexus mod {AIO_NEXUS_ID}). Switch to it: your "
            "NPC overrides, memories and conversations carry over. After switching, run Setup Backend.cmd again, re-tick "
            "the Living World plugins, and copy any settings files you edited by hand.")

logger = logging.getLogger(__name__)


def installed(versions_dir: str = VERSIONS_DIR) -> dict[str, dict]:
    """{module name: {'version', 'nexus_id'}} from the version files the modules ship. Modules without one (older
    builds) are left out."""
    found = {}
    try:
        names = sorted(os.listdir(versions_dir))
    except OSError:
        return found
    for name in names:
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(versions_dir, name), encoding='utf-8-sig') as f:  # a BOM from a hand edit is fine
                data = json.load(f)
            module, version, nexus_id = str(data['module']), str(data['version']), int(data['nexus_id'])
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            continue
        found[module] = {'version': version, 'nexus_id': nexus_id}
    return found


def version_key(text: str) -> tuple[int, ...]:
    """'1.10.0' -> (1, 10, 0), so 1.10 sorts above 1.9; trailing zeros do not count (1.0 == 1.0.0)."""
    numbers = [int(n) for n in re.findall(r'\d+', str(text))]
    while numbers and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers)


def load_cache(path: str = CACHE_PATH) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def fetch_latest(ids: list[int], timeout: float = TIMEOUT, opener=urllib.request.urlopen, sleep=time.sleep) -> dict[str, str]:
    """{mod id: version} of the published mods among ids, from one request to Nexus's public API (tried again after a
    short wait on a rate limit or a server error, net.open_url)."""
    query = '{ legacyModsByDomain(ids: [%s]) { nodes { modId version status } } }' % ', '.join(
        '{gameDomain: "%s", modId: %d}' % (GAME, i) for i in ids)
    request = urllib.request.Request(API, data=json.dumps({'query': query}).encode('utf-8'),
                                     headers={'Content-Type': 'application/json', 'User-Agent': 'Mantella-Living-World-Hub'})
    with net.open_url(request, timeout, opener=opener, sleep=sleep) as response:
        data = json.load(response)
    nodes = ((data.get('data') or {}).get('legacyModsByDomain') or {}).get('nodes') or []
    return {str(n['modId']): str(n['version']) for n in nodes
            if isinstance(n, dict) and n.get('status') == 'published' and n.get('modId') and n.get('version')}


def separate_install(mods: dict[str, dict]) -> bool:
    """Installed from the separate downloads: some module has its own Nexus page and the All in One's file is absent."""
    if AIO_MODULE in mods or any(m['nexus_id'] == AIO_NEXUS_ID for m in mods.values()):
        return False
    return any(m['nexus_id'] > 0 for m in mods.values())


def ids_to_ask(mods: dict[str, dict]) -> list[int]:
    """The installed modules' Nexus pages (0: no page yet), plus the All in One page for a separate install."""
    ids = {m['nexus_id'] for m in mods.values() if m['nexus_id'] > 0}
    if separate_install(mods):
        ids.add(AIO_NEXUS_ID)
    return sorted(ids)


def ask(fetch, ids: list[int]) -> dict[str, str]:
    """fetch(ids); when Nexus refuses a request that includes the All in One page (still a draft), asks once more
    without it, so the modules' own checks still work. Anything else is raised to the caller."""
    try:
        return fetch(ids)
    except urllib.error.HTTPError as error:
        others = [i for i in ids if i != AIO_NEXUS_ID]
        if error.code not in REFUSED or len(others) == len(ids):
            raise
        logger.debug(f'Living World: All in One page not public yet (HTTP {error.code})')
        return fetch(others) if others else {}


def due(cache: dict, now: float, days: int = 1) -> bool:
    checked = cache.get('checked')
    return not isinstance(checked, (int, float)) or not 0 <= now - checked < days * DAY


def check(days: int, versions_dir: str = VERSIONS_DIR, cache_path: str = CACHE_PATH, now: float | None = None,
          fetch=fetch_latest) -> bool:
    """Asks Nexus when the last check is `days` days old (0 or less: never). Returns whether it asked."""
    now = time.time() if now is None else now
    cache = load_cache(cache_path)
    mods = installed(versions_dir)
    if days <= 0 or not mods or not due(cache, now, days):
        return False
    latest = dict(cache.get('latest') or {})
    ids = ids_to_ask(mods)
    try:
        answer = ask(fetch, ids)
        if AIO_NEXUS_ID in ids:  # a page taken down again counts as not available
            latest.pop(str(AIO_NEXUS_ID), None)
        latest.update(answer)
    except Exception as error:  # offline, timeout, Nexus down: keep the old answer, try again tomorrow
        logger.info(f'Living World: update check skipped ({type(error).__name__}), next try at the next due check')
    tmp = cache_path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'checked': now, 'latest': latest}, f, indent=2)
        os.replace(tmp, cache_path)
    except OSError:
        pass
    return True


def check_in_background(days: int, **kw) -> threading.Thread:
    thread = threading.Thread(target=check, args=(days,), kwargs=kw, name='living-world-update-check', daemon=True)
    thread.start()
    return thread


def outdated(versions_dir: str = VERSIONS_DIR, cache_path: str = CACHE_PATH) -> dict[str, dict]:
    """{module name: {'installed', 'latest', 'url'}} for installed modules with a newer version on Nexus."""
    latest = load_cache(cache_path).get('latest') or {}
    out = {}
    for module, mine in installed(versions_dir).items():
        newest = latest.get(str(mine['nexus_id']))
        if newest and version_key(newest) > version_key(mine['version']):
            out[module] = {'installed': mine['version'], 'latest': newest, 'url': PAGE.format(mine['nexus_id'])}
    return out


def move_line(versions_dir: str = VERSIONS_DIR, cache_path: str = CACHE_PATH) -> str | None:
    """The move to the All in One notice for a separate install (None for an All in One install or no modules): how to
    switch once the last check found the page public, else that it is not available yet."""
    if not separate_install(installed(versions_dir)):
        return None
    latest = load_cache(cache_path).get('latest')
    public = isinstance(latest, dict) and latest.get(str(AIO_NEXUS_ID))
    return MOVE_NOW if public else MOVE_NOT_YET
