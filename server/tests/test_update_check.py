"""Offline tests for the daily module update check (server/living_world/update_check.py); Nexus is faked.
Run with a Python 3.11: test_update_check.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import ui_tab, update_check as uc

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)

tmp = tempfile.mkdtemp()
versions = os.path.join(tmp, 'versions')
os.makedirs(versions)
def ship(key, module, version, nexus_id):
    with open(os.path.join(versions, key + '.json'), 'w', encoding='utf-8') as f:
        json.dump({'module': module, 'version': version, 'nexus_id': nexus_id}, f)
ship('hub', 'Integration Hub', '1.0.0', 196849)
ship('world', 'World', '1.0.0', 197309)
ship('followers', 'Followers', '1.1', 196878)
with open(os.path.join(versions, 'broken.json'), 'w') as f:
    f.write('{not json')
with open(os.path.join(versions, 'bom.json'), 'w', encoding='utf-8-sig') as f:
    json.dump({'module': 'Missives', 'version': '1.0.0', 'nexus_id': 197320}, f)
cache = os.path.join(tmp, 'update_check.json')

found = uc.installed(versions)
check('version files read (BOM too), broken one skipped', set(found) == {'Integration Hub', 'World', 'Followers', 'Missives'}, found)
check('missing folder = nothing installed', uc.installed(os.path.join(tmp, 'nope')) == {})
check('1.10 newer than 1.9', uc.version_key('1.10') > uc.version_key('1.9'))
check('1.0 equals 1.0.0', uc.version_key('1.0') == uc.version_key('1.0.0'))

calls = []
def fake(ids):
    calls.append(ids)
    return {'196849': '1.1.0', '196878': '1.1.0'}  # World is a draft: Nexus leaves it out
check('asks when never checked (separate install: the All in One page in the same request)',
      uc.check(1, versions, cache, now=1000.0, fetch=fake) and calls == [[196849, 196878, 197309, 197320, 198897]], calls)
out = uc.outdated(versions, cache)
check('hub outdated, followers same version, world unknown', set(out) == {'Integration Hub'} and out['Integration Hub']['latest'] == '1.1.0', out)
check('link to the Nexus page', out['Integration Hub']['url'].endswith('/mods/196849'))
check('not again within a day', not uc.check(1, versions, cache, now=1000.0 + 23 * 3600, fetch=fake) and len(calls) == 1)
check('again after a day', uc.check(1, versions, cache, now=1000.0 + 25 * 3600, fetch=fake) and len(calls) == 2)
check('clock set back: asks again', uc.check(1, versions, cache, now=10.0, fetch=fake) and len(calls) == 3)

def offline(ids):
    raise OSError('no network')
os.remove(cache)
uc.check(1, versions, cache, now=5000.0, fetch=fake)
check('offline keeps the old answer', uc.check(1, versions, cache, now=5000.0 + 2 * 86400, fetch=offline)
      and set(uc.outdated(versions, cache)) == {'Integration Hub'})
check('offline: no retry storm, waits a day', not uc.check(1, versions, cache, now=5000.0 + 2 * 86400 + 60, fetch=fake))

os.remove(cache)
calls.clear()
check('0 days: never asks', not uc.check(0, versions, cache, now=1.0, fetch=fake) and not calls and not os.path.exists(cache))
check('no version files: never asks', not uc.check(1, os.path.join(tmp, 'nope'), cache, now=1.0, fetch=fake) and not calls)

# Main Status: updates are listed under What needs attention and drawn on the map in their own colour
updates = {'Integration Hub': {'installed': '1.0.0', 'latest': '1.1.0', 'url': 'https://example/196849'},
           'Missives': {'installed': '1.0.0', 'latest': '1.1.0', 'url': 'u'}}
actions = os.path.join(tmp, 'data', 'actions')
os.makedirs(actions)
data_dir = os.path.join(tmp, 'gamedata')
os.makedirs(data_dir)
st = ui_tab.statuses(actions, os.path.join(tmp, 'ext'), {}, data_dir, None)
check('module status itself stays green', st['Integration Hub'][0] == 'ok', st['Integration Hub'])
page = ui_tab.start_here_html(actions, os.path.join(tmp, 'ext'), {}, data_dir, None, updates)
map_part = page[page.index('<svg'):page.index('</svg>')]
check('updated module drawn in the update colour', f'<title>Integration Hub: Update 1.1.0 on Nexus: you have 1.0.0</title><circle cx="335" cy="' in map_part and ui_tab.UPDATE_COLOR in map_part, map_part[-400:])
check('no links on the map', 'href' not in map_part)
check('legend names the update colour', 'Update available' in page)
problem = dict(st, **{'Integration Hub': ('bad', 'Missing PapyrusUtil: install it, then restart the game')})
orig = ui_tab.statuses
ui_tab.statuses = lambda *a, **k: problem
try:
    bad_page = ui_tab.start_here_html(actions, os.path.join(tmp, 'ext'), {}, data_dir, None, updates)
finally:
    ui_tab.statuses = orig
check('a problem keeps its own colour over an update', 'Integration Hub: Missing PapyrusUtil' in bad_page, bad_page[:200])
check('update listed under What needs attention', 'What needs attention' in page and 'Update 1.1.0 is on Nexus (you have 1.0.0)' in page)
check('update in its own colour', ui_tab.UPDATE_COLOR in page)
check('no links anywhere', '<a ' not in page and 'https://example' not in page)
check('not installed module: no update line', 'Missives</b>' not in page)
# the All in One download: one version file of its own on its Nexus page; the modules keep their versions, id 0
aio = os.path.join(tmp, 'aio_versions')
os.makedirs(aio)
for key, module, version, nid in [('aio', 'All in One', '1.0.0', 198897), ('hub', 'Integration Hub', '1.2.2', 0), ('world', 'World', '1.2.0', 0)]:
    with open(os.path.join(aio, key + '.json'), 'w', encoding='utf-8') as f:
        json.dump({'module': module, 'version': version, 'nexus_id': nid}, f)
aio_cache = os.path.join(tmp, 'aio_cache.json')
calls.clear()
uc.check(1, aio, aio_cache, now=1.0, fetch=lambda ids: calls.append(ids) or {'198897': '1.1.0'})
check('All in One: only its own page is asked', calls == [[198897]], calls)
aio_out = uc.outdated(aio, aio_cache)
check('All in One: one update, modules keep their own versions', set(aio_out) == {'All in One'} and aio_out['All in One']['url'].endswith('/mods/198897'), aio_out)
aio_page = ui_tab.start_here_html(actions, os.path.join(tmp, 'ext'), {}, data_dir, None, aio_out)
check('All in One update listed although it is not a box on the map', 'All in One</b>: Update 1.1.0 is on Nexus (you have 1.0.0)' in aio_page, aio_page[-600:])
check('no updates: no attention list when all is fine', 'Everything installed is working' in ui_tab.start_here_html(actions, os.path.join(tmp, 'ext'), {}, data_dir, None, None))

# Moving to the All in One: separate installs get one plain line; the All in One page may still be a draft on Nexus.
# Nexus is faked at the HTTP level (the opener fetch_latest hands to net.open_url), so the real request path runs.
import io, logging, re, socket, urllib.error
waits = []
def nexus(answer):
    """A fake urlopen. answer(asked ids) returns a status code, an exception, bytes, or {id: version}."""
    seen = []
    def opener(request, timeout):
        ids = [int(i) for i in re.findall(r'modId: (\d+)', json.loads(request.data)['query'])]
        seen.append(ids)
        result = answer(ids)
        if isinstance(result, int):
            raise urllib.error.HTTPError(request.full_url, result, 'refused', {}, io.BytesIO(b'{}'))
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, bytes):
            return io.BytesIO(result)
        nodes = [{'modId': int(k), 'version': v, 'status': 'published'} for k, v in result.items() if int(k) in ids]
        return io.BytesIO(json.dumps({'data': {'legacyModsByDomain': {'nodes': nodes}}}).encode())
    fetch = lambda ids: uc.fetch_latest(ids, opener=opener, sleep=waits.append)
    return fetch, seen
MODULES_ANSWER = {'196849': '1.1.0', '196878': '1.1.0'}
def draft_refused(code):
    return lambda ids: code if uc.AIO_NEXUS_ID in ids else MODULES_ANSWER

sep_cache = os.path.join(tmp, 'sep_cache.json')
def fresh():
    if os.path.exists(sep_cache):
        os.remove(sep_cache)

class Logs(logging.Handler):
    def __init__(self):
        super().__init__(level=0)
        self.records = []
    def emit(self, record):
        self.records.append(record)
logs = Logs()
uc.logger.addHandler(logs)
uc.logger.setLevel(logging.DEBUG)

def page_for(versions_dir, cache_path):
    return ui_tab.start_here_html(actions, os.path.join(tmp, 'ext'), {}, data_dir, None, uc.outdated(versions_dir, cache_path),
                                  move=uc.move_line(versions_dir, cache_path))

check('separate install detected', uc.separate_install(uc.installed(versions)))
check('All in One install is not separate', not uc.separate_install(uc.installed(aio)))
check('no modules: not separate', not uc.separate_install({}))
check('modules with no Nexus page yet (all 0) and no All in One file: not separate',
      not uc.separate_install({'Integration Hub': {'version': '1', 'nexus_id': 0}}))

for code in (403, 404, 400):
    fresh(); logs.records.clear(); waits.clear()
    fetch, seen = nexus(draft_refused(code))
    asked = uc.check(3, versions, sep_cache, now=1000.0, fetch=fetch)
    check(f'{code} for the draft: check still runs, module pages asked again without it',
          asked and seen == [[196849, 196878, 197309, 197320, 198897], [196849, 196878, 197309, 197320]], seen)
    check(f'{code}: module updates unaffected', set(uc.outdated(versions, sep_cache)) == {'Integration Hub'}, uc.outdated(versions, sep_cache))
    check(f'{code}: not available yet line', uc.move_line(versions, sep_cache) == uc.MOVE_NOT_YET)
    check(f'{code}: nothing logged above debug', not [r for r in logs.records if r.levelno > logging.DEBUG], [r.getMessage() for r in logs.records])
    check(f'{code}: no rate limit waits', not waits, waits)

fresh(); logs.records.clear()
fetch, seen = nexus(lambda ids: MODULES_ANSWER)  # the draft is left out of a normal answer
uc.check(3, versions, sep_cache, now=1000.0, fetch=fetch)
check('draft left out of the answer: one request only', len(seen) == 1, seen)
check('draft left out: not available yet line', uc.move_line(versions, sep_cache) == uc.MOVE_NOT_YET)

for name, failure in [('timeout', socket.timeout('timed out')), ('no network', urllib.error.URLError('offline')),
                      ('garbage JSON', b'<html>not json'), ('JSON that is not an object', b'[1, 2]')]:
    fresh(); logs.records.clear()
    fetch, seen = nexus(lambda ids, f=failure: f)
    check(f'{name}: no exception, the check counts as done', uc.check(3, versions, sep_cache, now=1000.0, fetch=fetch))
    check(f'{name}: one request, no second try', len(seen) == 1, seen)
    check(f'{name}: not available yet line', uc.move_line(versions, sep_cache) == uc.MOVE_NOT_YET)
    check(f'{name}: no warning or error logged', not [r for r in logs.records if r.levelno >= logging.WARNING], [r.getMessage() for r in logs.records])
    check(f'{name}: waits for the next due check', not uc.check(3, versions, sep_cache, now=1000.0 + 2 * 86400, fetch=fetch) and len(seen) == 1)

fresh(); waits.clear()
fetch, seen = nexus(lambda ids: 429)
uc.check(3, versions, sep_cache, now=1000.0, fetch=fetch)
check('rate limit: the existing retry (3 tries, growing wait), then given up quietly', len(seen) == 3 and waits == [1.0, 2.0], (seen, waits))
check('rate limit: not available yet line', uc.move_line(versions, sep_cache) == uc.MOVE_NOT_YET)

fresh()
fetch, seen = nexus(lambda ids: MODULES_ANSWER)
uc.check(3, versions, sep_cache, now=1000.0, fetch=fetch)
fetch, seen = nexus(lambda ids: socket.timeout('timed out'))
uc.check(3, versions, sep_cache, now=1000.0 + 4 * 86400, fetch=fetch)
check('failed check keeps the module updates found before', set(uc.outdated(versions, sep_cache)) == {'Integration Hub'})

# the page goes public
fresh()
fetch, seen = nexus(lambda ids: dict(MODULES_ANSWER, **{'198897': '1.0.0'}))
uc.check(3, versions, sep_cache, now=1000.0, fetch=fetch)
check('public page: now updates through line', uc.move_line(versions, sep_cache) == uc.MOVE_NOW)
check('public page: the All in One is not listed as a module update', 'All in One' not in uc.outdated(versions, sep_cache))
check('public page: module updates unaffected', set(uc.outdated(versions, sep_cache)) == {'Integration Hub'})
check('inside the interval: no request', not uc.check(3, versions, sep_cache, now=1000.0 + 2 * 86400, fetch=fetch) and len(seen) == 1, seen)
fetch, seen = nexus(draft_refused(404))
uc.check(3, versions, sep_cache, now=1000.0 + 4 * 86400, fetch=fetch)
check('page made a draft again: back to not available yet', uc.move_line(versions, sep_cache) == uc.MOVE_NOT_YET)
fetch, seen = nexus(lambda ids: dict(MODULES_ANSWER, **{'198897': '1.0.0'}))
uc.check(3, versions, sep_cache, now=1000.0 + 8 * 86400, fetch=fetch)
fetch, seen = nexus(lambda ids: socket.timeout('timed out'))
uc.check(3, versions, sep_cache, now=1000.0 + 12 * 86400, fetch=fetch)
check('offline after it went public: keeps the switch line', uc.move_line(versions, sep_cache) == uc.MOVE_NOW)

check('wording: plain, no link, mod number as text', 'https://' not in uc.MOVE_NOW + uc.MOVE_NOT_YET and '198897' in uc.MOVE_NOW
      and 'not available yet' in uc.MOVE_NOT_YET and 'overrides, memories and conversations' in uc.MOVE_NOT_YET + uc.MOVE_NOW)
check('wording: switch steps named', all(s in uc.MOVE_NOW for s in ('Setup Backend.cmd', 're-tick the Living World plugins', 'settings files')))

# All in One install: never the line, never asks about anything else
aio_cache2 = os.path.join(tmp, 'aio_cache2.json')
for answer in (lambda ids: {'198897': '1.1.0'}, draft_refused(403), lambda ids: socket.timeout('t')):
    if os.path.exists(aio_cache2):
        os.remove(aio_cache2)
    fetch, seen = nexus(answer)
    uc.check(3, aio, aio_cache2, now=1.0, fetch=fetch)
    check('All in One install: no move line', uc.move_line(aio, aio_cache2) is None and 'All in One download' not in page_for(aio, aio_cache2))
    check('All in One install: only its own page asked, once', seen == [[198897]], seen)
check('All in One install with no cache: no move line', uc.move_line(aio, os.path.join(tmp, 'none.json')) is None)
check('no version files: no move line', uc.move_line(os.path.join(tmp, 'nope'), sep_cache) is None)
with open(sep_cache, 'w', encoding='utf-8') as f:
    f.write('{"latest": [1]}')
check('corrupt cache: not available yet, no error', uc.move_line(versions, sep_cache) == uc.MOVE_NOT_YET)

# Main Status: the line sits under What needs attention, plain, in the update colour, not on the map, no link
fresh()
fetch, seen = nexus(draft_refused(403))
uc.check(3, versions, sep_cache, now=1000.0, fetch=fetch)
sep_page = page_for(versions, sep_cache)
sep_map = sep_page[sep_page.index('<svg'):sep_page.index('</svg>')]
line_html = f'<li style="margin:3px 0;color:{ui_tab.UPDATE_COLOR}">{uc.MOVE_NOT_YET}</li>'
check('Status: move line under What needs attention in the update colour, not bold', line_html in sep_page
      and sep_page.index('What needs attention') < sep_page.index(line_html), sep_page[-900:])
check('Status: module update still listed above it', 'Update 1.1.0 is on Nexus (you have 1.0.0)' in sep_page
      and sep_page.index('Update 1.1.0 is on Nexus (you have 1.0.0)') < sep_page.index(line_html))
check('Status: not on the map', 'All in One' not in sep_map)
check('Status: no link', '<a ' not in sep_page)
check('Status: move line alone still opens the attention list', 'What needs attention' in ui_tab.start_here_html(
    actions, os.path.join(tmp, 'ext'), {}, data_dir, None, None, move=uc.MOVE_NOT_YET))
public_page = ui_tab.start_here_html(actions, os.path.join(tmp, 'ext'), {}, data_dir, None, None, move=uc.MOVE_NOW)
check('Status: public wording shown, mod number as text, no link', 'Nexus mod 198897' in public_page and '<a ' not in public_page)
check('Status: no move argument keeps the old page', 'All in One download' not in ui_tab.start_here_html(
    actions, os.path.join(tmp, 'ext'), {}, data_dir, None, None))
uc.logger.removeHandler(logs)

print('\nRESULT:', 'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}')
sys.exit(1 if FAILS else 0)
