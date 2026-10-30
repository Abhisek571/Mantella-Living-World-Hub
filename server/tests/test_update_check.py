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
check('asks when never checked', uc.check(1, versions, cache, now=1000.0, fetch=fake) and calls == [[196849, 196878, 197309, 197320]], calls)
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

# Main Status: an outdated module turns yellow with the new version; a module with its own problem keeps it
updates = {'Integration Hub': {'installed': '1.0.0', 'latest': '1.1.0', 'url': 'https://example/196849'},
           'Missives': {'installed': '1.0.0', 'latest': '1.1.0', 'url': 'u'}}
actions = os.path.join(tmp, 'data', 'actions')
os.makedirs(actions)
data_dir = os.path.join(tmp, 'gamedata')
os.makedirs(data_dir)
st = ui_tab.statuses(actions, os.path.join(tmp, 'ext'), {}, data_dir, None, updates)
check('outdated hub is yellow with the version', st['Integration Hub'][0] == 'todo' and '1.1.0' in st['Integration Hub'][1], st['Integration Hub'])
check('not installed stays grey', st['Missives'][0] == 'off', st['Missives'])
html_page = ui_tab.start_here_html(actions, os.path.join(tmp, 'ext'), {}, data_dir, None, updates)
check('listed under What needs attention', 'Update 1.1.0 on Nexus' in html_page)
check('no updates: unchanged', ui_tab.statuses(actions, os.path.join(tmp, 'ext'), {}, data_dir, None, None)['Integration Hub'][0] == 'ok')

print('\nRESULT:', 'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}')
sys.exit(1 if FAILS else 0)
