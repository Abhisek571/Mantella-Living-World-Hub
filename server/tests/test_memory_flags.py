"""Offline tests for the fixed "always important" memory flags (archive.FLAG_FLOORS): each flag's signal, the importance
floor it gives, that flagged memories stay in the memory list and are shown before ordinary older ones, and the cap with
merging.
Run with a Python 3.11: test_memory_flags.py <repo server dir>"""
import json, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
from living_world import archive, battle, memory, menu_dialogue as MD
memory.SUMMARY_RETRY_SECONDS = 0

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


def fight(me_side, rescued=False, struck=1):
    return {'id': '1', 'end': 1.5, 'fighters': [
        {'name': 'CHAD', 'ref_id': '00000014', 'role': 'player', 'side': 0, 'rescued_by': [], 'struck': 1},
        {'name': 'Lydia', 'ref_id': '000A2C94', 'role': 'party' if me_side == 0 else 'enemy', 'side': me_side, 'struck': struck,
         'rescued_by': [{'ref': '00000014', 'how': 'heal'}] if rescued else [], 'lowest': 0.1 if rescued else 1.0},
        {'name': 'Bandit', 'ref_id': '000BAD01', 'role': 'enemy' if me_side == 0 else 'ally', 'side': 1 - me_side}]}


def part_floors():
    check('a flag lifts importance to its floor; the model\'s higher value stays',
          archive.importance_of({'importance': 0.2, 'flags': ['intimacy']}) == 0.9
          and archive.importance_of({'importance': 1.0, 'flags': ['fought_beside']}) == 1.0
          and archive.importance_of({'importance': 0.3}) == 0.3 and archive.importance_of({'flags': ['unknown']}) == archive.DEFAULT_IMPORTANCE)
    check('a flagged memory fades far slower (retention after 100 days)',
          archive.retention(archive.importance_of({'importance': 0.2, 'flags': ['harmed']}), 100) > 0.5 > archive.retention(0.2, 100))


def part_battle():
    lydia = lambda f: next(x for x in battle.fighters(f) if x['name'] == 'Lydia')
    f = fight(1)
    check('2. the player fought against them: harmed', battle.fight_flags(f, lydia(f)) == ['harmed'])
    f = fight(0, rescued=True)
    check('3. the player saved them in a fight: rescue', battle.fight_flags(f, lydia(f)) == ['rescue'])
    f = fight(0)
    check('3. fought on the player\'s side: fought_beside', battle.fight_flags(f, lydia(f)) == ['fought_beside'])
    f = fight(0, struck=0)
    check('...caught in it without fighting: no flag', battle.fight_flags(f, lydia(f)) == [])


def part_promise_first(tmp: Path):
    store = memory.MemoryStore(str(tmp), 'w')
    mem = store.load('Lydia', '0A2C94')
    entry = {'day': 3, 'hour': 10, 'text': 'We talked.'}
    reply = json.dumps({'memory': 'x', 'promises': [{'text': 'CHAD will bring Lydia a sword', 'by': 'CHAD'}]})
    memory._link_promises(entry, mem, reply, 3)
    check('5. a promise made in the talk: promise flag', entry.get('flags') == ['promise'] and entry.get('promises'), entry)
    src = (SERVER / 'living_world' / 'memory.py').read_text(encoding='utf-8')
    check("11. their first talk with the player carries first_meeting (no earlier talk, no counted talks)",
          "archive.add_flag(added, 'first_meeting')" in src and "not memory.get('talks')" in src)


def part_news_menu(tmp: Path):
    store = memory.MemoryStore(str(tmp), 'w')
    memory.add_memory(store, 'Lydia', '0A2C94', 'Hod was killed at the mill.', day=5, key='news-1', flags={'death_close': True})
    memory.add_memory(store, 'Lydia', '0A2C94', 'A wedding in Solitude.', day=5, key='news-2', flags={'death_close': False})
    recent = store.load('Lydia', '0A2C94')['recent']
    check('10. a death they saw or a household member told them: death_close; other news none',
          recent[0].get('flags') == ['death_close'] and not recent[1].get('flags'), recent)
    src = (SERVER / 'living_world' / 'news.py').read_text(encoding='utf-8')
    check("...set by news from the ring (1 seen, 2 told by household) and the kind (a death or a murder)",
          "close_death = how['ring'] in (1, 2)" in src and "'death_close': close_death" in src)
    scene = ["Earlier (about 3 hours ago), with no conversation going on: Lydia and the player finished a scene together; nothing sexual happened."]
    MD.remember_scene_events(scene, [SimpleNamespace(name='Lydia', ref_id='0A2C94')], store, 6, None)
    check('1. intimacy: an earlier scene record is flagged (and, her earliest memory of the player, first_meeting)',
          store.load('Lydia', '0A2C94')['recent'][-1].get('flags') == ['intimacy', 'first_meeting'])


def part_kept_and_cap(tmp: Path):
    store = memory.MemoryStore(str(tmp), 'w')
    mem = memory.empty()
    mem['recent'] = [{'day': 1, 'hour': 9, 'text': 'We met at the gate.', 'witnesses': ['Lydia'], 'importance': 0.1, 'flags': ['first_meeting']}]
    mem['recent'] += [{'day': 2 + i, 'hour': 9, 'text': f'Small talk number {i}.', 'witnesses': ['Lydia'], 'importance': 0.1} for i in range(45)]
    folded = memory.fold_old(mem, None, None)
    check('a flagged memory never folds into the older-memories text; it stays in the list', folded['recent'][0]['text'] == 'We met at the gate.'
          and 'We met at the gate' not in folded['long_term'].get('earlier', ''), folded['recent'][0])
    text = memory.render(folded, 100, None, today=60)
    check('...and is shown right after the newest, before ordinary older memories', 'We met at the gate.' in text and 'Small talk number 44.' in text
          and 'Small talk number 30.' not in text, text)
    capped = memory.empty()
    capped['recent'] = [{'day': d, 'hour': 9, 'text': f'Fought beside them on day {d}.', 'witnesses': ['Lydia'], 'flags': ['fought_beside']} for d in range(1, 13)]
    memory.cap_flagged(capped)
    flagged = [e for e in capped['recent'] if e.get('flags')]
    check(f'at most {memory.ALWAYS_CAP} flagged memories; the oldest of the same flag merge into one line with the count and days',
          len(flagged) == memory.ALWAYS_CAP and '(and 4 earlier times: day 1, day 2, day 3, day 4)' in flagged[0]['text'], [e['text'] for e in flagged][:2])


with tempfile.TemporaryDirectory() as tmp:
    for name, part in (('floors', lambda t: part_floors()), ('battle', lambda t: part_battle()), ('promise', part_promise_first),
                       ('news', part_news_menu), ('kept', part_kept_and_cap)):
        try:
            sub = Path(tmp) / name
            sub.mkdir()
            part(sub)
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'part {name} ran without an error', False, e)

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
