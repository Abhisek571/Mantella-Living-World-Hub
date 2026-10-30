"""Tells the player when a newer version of an installed Living World module is on Nexus.

Each module ships data/living_world/versions/<key>.json ({"module", "version", "nexus_id"}). At most every few days
(the player's setting, 3 by default; 0 switches it off), in the background, the Hub asks Nexus's public API for those mods' current versions (one request, no key, only the mod
IDs are sent) and keeps the answer in update_check.json next to the settings. The Main Status tab compares the two.
No internet, a slow answer or a Nexus error changes nothing and is tried again at the next due check."""
import json
import logging
import os
import re
import threading
import time
import urllib.request

VERSIONS_DIR = os.path.join('data', 'living_world', 'versions')
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'update_check.json')
API = 'https://api.nexusmods.com/v2/graphql'
GAME = 'skyrimspecialedition'
PAGE = 'https://www.nexusmods.com/skyrimspecialedition/mods/{}'
DAY = 24 * 3600
TIMEOUT = 10

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
            module, version, nexus_id = data['module'], str(data['version']), int(data['nexus_id'])
        except (OSError, ValueError, KeyError, TypeError):
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


def fetch_latest(ids: list[int], timeout: float = TIMEOUT) -> dict[str, str]:
    """{mod id: version} of the published mods among ids, from one request to Nexus's public API."""
    query = '{ legacyModsByDomain(ids: [%s]) { nodes { modId version status } } }' % ', '.join(
        '{gameDomain: "%s", modId: %d}' % (GAME, i) for i in ids)
    request = urllib.request.Request(API, data=json.dumps({'query': query}).encode('utf-8'),
                                     headers={'Content-Type': 'application/json', 'User-Agent': 'Mantella-Living-World-Hub'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.load(response)
    nodes = ((data.get('data') or {}).get('legacyModsByDomain') or {}).get('nodes') or []
    return {str(n['modId']): str(n['version']) for n in nodes
            if isinstance(n, dict) and n.get('status') == 'published' and n.get('modId') and n.get('version')}


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
    try:
        latest.update(fetch(sorted({m['nexus_id'] for m in mods.values()})))
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
