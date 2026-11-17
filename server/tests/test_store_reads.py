"""Offline tests: a save's JSON stores (custom events, absolute commands, the world log, the facts history, the release
record) are never saved over after a read that failed. One locked read (a sync tool, an antivirus or a backup holding
the file) used to read as "empty" and the next save replaced the whole store with the one row it added. A file that is
not JSON is copied aside before it is replaced. Read-only callers still get an empty value.
Run with a Python 3.11: test_store_reads.py <repo server dir>"""
import builtins, json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
from living_world import bio_evolve, characters, command, console, events, facts_history, lw_state, memory, release, timeline, worldlog

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

        # the Characters page file: a locked read emptied it (and npc_flags.json) on the next save
        real_dir = lw_state.DATA_DIR
        lw_state.DATA_DIR = os.path.join(tmp, 'channel')
        try:
            cpath = os.path.join(tmp, 'characters.json')
            characters.save_entry('Lydia', 'Nord', {'flags': {'never_intimate': True}}, cpath)
            characters.save_entry('Aela', 'Nord', {'flags': {'ignore_commands': True}}, cpath)
            characters._cache.update(path=None, stamp=None, data=None)
            lock_once(cpath)
            characters.load(cpath)
            check('characters: a locked read is not cached as empty', len(characters.load(cpath)['npcs']) == 2, characters.load(cpath))
            lock_once(cpath)
            os.utime(cpath, (os.path.getmtime(cpath) + 5,) * 2)  # a new stamp: read again, and that read fails
            during = characters.load(cpath)
            check('...a locked read gives the last good read, not an empty file', len(during['npcs']) == 2, during)
            lock_once(cpath)
            os.utime(cpath, (os.path.getmtime(cpath) + 5,) * 2)
            wrote = characters.save_entry('Brynjolf', 'Nord', {'custom': 'thief'}, cpath)
            on_disk = json.load(real_open(cpath, encoding='utf-8'))
            check('...a save after a locked read is refused and every NPC is kept',
                  not wrote and len(on_disk['npcs']) == 2, (wrote, on_disk))
            flag_path = os.path.join(lw_state.DATA_DIR, characters.FLAGS_FILE)
            flags = json.load(real_open(flag_path, encoding='utf-8'))['int']
            lock_once(cpath)
            os.utime(cpath, (os.path.getmtime(cpath) + 5,) * 2)
            characters._cache.update(path=None, stamp=None, data=None)
            characters.write_game_flags(cpath)
            after = json.load(real_open(flag_path, encoding='utf-8'))['int']
            check('...and the game flag file is never rewritten from a failed read',
                  after == flags and after.get('lydia|never_intimate') == 1, after)
            # one worker thread's failed read must not block its later saves once the file reads fine again
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as worker:
                lock_once(cpath)
                os.utime(cpath, (os.path.getmtime(cpath) + 5,) * 2)
                worker.submit(characters.load, cpath).result()  # this worker's read fails
                characters.load(cpath)  # another thread reads it fine and caches it
                saved = worker.submit(characters.save_entry, 'Brynjolf', 'Nord', {'custom': 'thief'}, cpath).result()
            check('...a worker whose earlier read failed may save again once the file reads fine',
                  saved and len(json.load(real_open(cpath, encoding='utf-8'))['npcs']) == 3)
            timeline._save(store, {'links': {'t1': ['', 1]}, 'gone': {}, 'times': {}})
            with ThreadPoolExecutor(max_workers=1) as worker:
                lock_once(timeline._path(store))
                os.utime(timeline._path(store), (os.path.getmtime(timeline._path(store)) + 5,) * 2)
                worker.submit(timeline.load, store).result()
                timeline.load(store)
                def stamp_link():
                    with timeline._lock(timeline._path(store)):
                        old = timeline._load_now(store)
                        timeline._save(store, dict(old, links=dict(old['links'], t2=['t1', 2])))
                worker.submit(stamp_link).result()
            check('...the same for the timeline', len(timeline.load(store)['links']) == 2, timeline.load(store))
        finally:
            lw_state.DATA_DIR = real_dir

        # Now paragraphs: mark_due and add_gap saved an empty paragraph over a locked file
        bio_evolve.add_gap(store, 'Lydia', '0A2C94', 'has no memory of days 3 to 5')
        state = bio_evolve.load(store, 'Lydia', '0A2C94')
        bio_evolve.save(store, 'Lydia', '0A2C94', dict(state, text='She guards the hold.', locked=True))
        lock_once(bio_evolve._path(store, 'Lydia', '0A2C94'))
        bio_evolve.mark_due(store, 'Lydia', '0A2C94', 'a custom event')
        lock_once(bio_evolve._path(store, 'Lydia', '0A2C94'))
        try:
            bio_evolve.add_gap(store, 'Lydia', '0A2C94', 'another gap')
        except OSError:
            pass
        now = bio_evolve.load(store, 'Lydia', '0A2C94')
        check('Now paragraph: a locked read never wipes the text, lock and gaps',
              now['text'] == 'She guards the hold.' and now['locked'] and len(now['gaps']) == 1, now)

        # the timeline: a locked read was cached as no links, and the next stamp saved that over the file
        timeline._save(store, {'links': {'t1': ['', 1], 't2': ['t1', 2]}, 'gone': {}, 'times': {}})
        timeline._cache.clear()
        lock_once(timeline._path(store))
        timeline.load(store)
        check('timeline: a locked read is not cached as empty', len(timeline.load(store)['links']) == 2, timeline.load(store))
        lock_once(timeline._path(store))
        os.utime(timeline._path(store), (os.path.getmtime(timeline._path(store)) + 5,) * 2)
        during = timeline.load(store)
        try:
            timeline._save(store, {'links': dict(during['links'], t3=['t2', 3]), 'gone': {}, 'times': {}})
            refused = False
        except OSError:
            refused = True
        check('...a locked read gives the last good links and refuses the save', len(during['links']) == 2 and refused
              and len(timeline.load(store)['links']) == 2, (during, timeline.load(store)))

        # the Console log
        console.save(store, {'seen': ['k1', 'k2'], 'done': ['r1'], 'log': [{'key': 'k1'}]})
        lock_once(console.store_path(store))
        empty = console.load(store)
        try:
            console.save(store, dict(empty, seen=['k3']))
            refused = False
        except OSError:
            refused = True
        check('console: after a locked read the empty copy is refused, the log keeps its keys',
              refused and console.load(store)['seen'] == ['k1', 'k2'], console.load(store))

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
