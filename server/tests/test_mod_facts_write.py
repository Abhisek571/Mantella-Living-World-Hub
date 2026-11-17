"""Offline tests: the scanned mod fact files and the use_generated switch are replaced in one step. The game reads them
at every join and keeps what it read for the session, so a join during a scan used to read a half-written (or a just
removed) file and keep that plugin's facts wrong until a restart.
Run with a Python 3.11: test_mod_facts_write.py <repo server dir>"""
import builtins, json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
from living_world import mod_facts_gen, mod_facts_scan

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:500]) if not cond else ''))
    if not cond:
        FAILS.append(name)


real_open, real_remove = builtins.open, os.remove
opened, removed = [], []


def watch_open(path, *a, **k):
    mode = a[0] if a else k.get('mode', 'r')
    if 'w' in mode:
        opened.append(os.path.normcase(os.path.abspath(str(path))))
    return real_open(path, *a, **k)


def watch_remove(path, *a, **k):
    removed.append(os.path.normcase(os.path.abspath(str(path))))
    return real_remove(path, *a, **k)


with tempfile.TemporaryDirectory() as tmp:
    folder = os.path.join(tmp, 'modfacts', 'generated')
    os.makedirs(folder)
    for name in ('Kept.esp.json', 'Gone.esp.json'):
        with real_open(os.path.join(folder, name), 'w', encoding='utf-8') as f:
            json.dump({'source': 'generated', 'facts': ['old']}, f)
    with real_open(os.path.join(folder, 'Mine.esp.json'), 'w', encoding='utf-8') as f:
        json.dump({'facts': ['hand written']}, f)
    kept = os.path.normcase(os.path.abspath(os.path.join(folder, 'Kept.esp.json')))
    flag = os.path.normcase(os.path.abspath(os.path.join(tmp, 'modfacts', mod_facts_scan.USE_FLAG)))
    builtins.open, os.remove = watch_open, watch_remove
    try:
        written = mod_facts_gen.write({'Kept.esp': {'source': 'generated', 'facts': ['new']}}, folder)
        ok = mod_facts_scan.set_use_generated(folder, True)
    finally:
        builtins.open, os.remove = real_open, real_remove
    check('a generated file is never opened for writing in place (temp file, then replace)', kept not in opened, opened)
    check('...and a file the scan writes again is never removed first', kept not in removed, removed)
    check('...it holds the new facts', json.load(real_open(kept, encoding='utf-8'))['facts'] == ['new'])
    check('a stale generated file is still removed, a hand-written one kept',
          sorted(os.listdir(folder)) == ['Kept.esp.json', 'Mine.esp.json'], os.listdir(folder))
    check('no temp file is left behind', not [n for n in os.listdir(folder) if n.endswith('.tmp')], os.listdir(folder))
    check('use_generated.json is replaced in one step too', ok and flag not in opened
          and json.load(real_open(flag, encoding='utf-8')) == {'int': {'on': 1}}, opened)

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
