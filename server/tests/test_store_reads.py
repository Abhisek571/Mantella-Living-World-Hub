"""Offline tests: a save's JSON stores (custom events, absolute commands, the world log, the facts history, the release
record) are never saved over after a read that failed. One locked read (a sync tool, an antivirus or a backup holding
the file) used to read as "empty" and the next save replaced the whole store with the one row it added. A file that is
not JSON is copied aside before it is replaced. Read-only callers still get an empty value.
Run with a Python 3.11: test_store_reads.py <repo server dir>"""
import builtins, json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
from living_world import command, events, facts_history, lw_state, memory, release, worldlog

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:500]) if not cond else ''))
    if not cond:
        FAILS.append(name)


real_open = builtins.open
locked = {'path': None, 'n': 0}


def flaky(path, *a, **k):
    mode = a[0] if a else k.get('mode', 'r')
    if locked['n'] > 0 and 'w' not in mode and os.path.abspath(str(path)) == os.path.abspath(str(locked['path'])):
        locked['n'] -= 1
        raise PermissionError(13, 'locked by another process')
    return real_open(path, *a, **k)


def lock_once(path):
    locked.update(path=path, n=1)


builtins.open = flaky
try:
    with tempfile.TemporaryDirectory() as tmp:
        store = memory.MemoryStore(tmp, 'World1')
        os.makedirs(store.root, exist_ok=True)

        # custom events: the audit's repro (5 events became 1)
        rows = [{'id': f'e{i}', 'text': f'old event {i}', 'talk': 'x', 'status': 'active', 'at': i} for i in range(5)]
        events.save(store, rows)
        lock_once(events.journal_path(store))
        C = type('C', (), {'name': 'Lydia', 'ref_id': '0A2C94'})
        events.process(['A dragon lands nearby\n'], {'is_first': False, 'characters': [C()], 'game_days': 10.5}, store)
        check('custom events: one locked read never wipes the journal (5 kept)', len(events.load(store)) == 5, events.load(store))
        lock_once(events.journal_path(store))
        check('...a read-only caller still gets an empty list while it is locked', events.load(store) == [])
        events.load(store)  # read fine again
        events.save(store, rows[:4] + [dict(rows[4], text='changed')])
        check('...and once a read works again, saving works', [r['text'] for r in events.load(store)][-1] == 'changed')

        # world log: 7 events became 1
        worldlog.change_log(store, lambda log: log['events'].extend({'id': f'w{i}', 'kind': 'x'} for i in range(7)) or True)
        worldlog._cache.clear()
        lock_once(worldlog._path(store, worldlog.LOG_FILE))
        worldlog.change_log(store, lambda log: log['events'].append({'id': 'new', 'kind': 'x'}) or True)
        worldlog._cache.clear()
        check('world log: one locked read never wipes it (7 kept)', len(worldlog.events(store)) == 7, len(worldlog.events(store)))
        worldlog.change_log(store, lambda log: log['events'].append({'id': 'new', 'kind': 'x'}) or True)
        check('...the next change, read fine, is saved', len(worldlog.events(store)) == 8)

        # absolute commands: load returned 0 commands and poll saved that back
        data = {'commands': [{'id': 'c1', 'text': 'obey', 'npcs': [{'name': 'Lydia', 'ref_id': '0A2C94'}], 'status': 'active'}],
                'seen': ['k1'], 'ended': []}
        command.save(store, data)
        lock_once(command.store_path(store))
        empty = command.load(store)
        try:
            command.save(store, empty)
            refused = False
        except OSError:
            refused = True
        check('commands: after a locked read the empty copy is refused, the file keeps its command',
              refused and len(command.load(store)['commands']) == 1, command.load(store))

        # facts history and the release record
        facts_history.add_line(store, 'Lydia', '0A2C94', 'enchanted', 'under a spell', 'test', 3)
        lock_once(facts_history.path(store))
        try:
            facts_history.add_line(store, 'Lydia', '0A2C94', 'home', 'Breezehome', 'test', 4)
        except OSError:
            pass
        lines = facts_history.load(store)['npcs']
        check('facts history: a locked read never wipes the earlier line', any(l.get('value') == 'under a spell'
                                                                                 for e in lines.values() for l in e['lines']), lines)
        release.write_record(store, 'release', 'Lydia', '0A2C94', 'obey', 'you')
        lock_once(release.record_path(store))
        try:
            release.write_record(store, 'release', 'Lydia', '0A2C94', 'again', 'you')
        except OSError:
            pass
        check('release record: a locked read never wipes the earlier row', [r['what'] for r in release.load_record(store)['rows']][:1] == ['obey'],
              release.load_record(store))

        # a broken file: copied aside, then replaced
        with real_open(command.store_path(store), 'w', encoding='utf-8') as f:
            f.write('{"commands": [ broken')
        command.load(store)
        asides = [p for p in os.listdir(os.path.dirname(command.store_path(store))) if '.unreadable-' in p]
        command.save(store, {'commands': [], 'seen': [], 'ended': []})
        check('a file that is not JSON is copied aside, then may be replaced', asides and json.load(real_open(command.store_path(store)))['commands'] == [],
              asides)
finally:
    builtins.open = real_open

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
