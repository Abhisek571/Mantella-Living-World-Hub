"""Offline tests for the second set of fixed memory flags: bond and follower changes from the facts history, gifts and
theft from World's lines in the talk, recognition of the hooded stranger, and a broken promise.
Run with a Python 3.11: test_memory_flags2.py <repo server dir>"""
import json, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
from living_world import archive, memory, npc_block

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


def flags(store, name='Lydia', ref='0A2C94'):
    return [(e['text'], e.get('flags') or []) for e in store.load(name, ref)['recent']]


def part_bond_follower(tmp: Path):
    store = memory.MemoryStore(str(tmp), 'w')
    made = npc_block.fact_memories(store, 'Lydia', '0A2C94', [{'fact': 'partner', 'old': '', 'new': 'married to Player'}], 'Player')
    got = store.load('Lydia', '0A2C94')['recent'][-1]
    check('4. a partner change with the player: a dated memory with the bond flag (0.9, kept in the list)',
          made == ['Became married to Player.'] and got.get('flags') == ['bond'] and archive.importance_of(got) == 0.9
          and 'bond' in memory.KEEP_FLAGS, got)
    npc_block.fact_memories(store, 'Lydia', '0A2C94', [{'fact': 'partner', 'old': 'married to Player', 'new': ''}], 'Player')
    check('...and when it ends', store.load('Lydia', '0A2C94')['recent'][-1]['text'] == 'Is no longer married to Player.')
    other = memory.MemoryStore(str(tmp / 'f'), 'w')
    steps = [('', 'yes, travels with Player'), ('yes, travels with Player', 'no, not travelling with Player'),
             ('no, not travelling with Player', 'yes, travels with Player'), ('yes, travels with Player', 'no, not travelling with Player')]
    for i, (old, new) in enumerate(steps):
        memory.lw_state.load_today = (lambda d: (lambda: d))(10 + i)  # a different day each time
        npc_block.fact_memories(other, 'Lydia', '0A2C94', [{'fact': 'follower', 'old': old, 'new': new}], 'Player')
    got = flags(other)
    flagged = [t for t, f in got if 'follower' in f]
    check('7. follower changes: only the first joining and the latest change stay flagged; the rest merge into a count',
          len(got) == 4 and flagged == [got[0][0], got[-1][0]] and got[0][0].startswith('Started travelling with Player')
          and '(and 2 earlier times)' in got[-1][0], got)
    check('...the unflagged ones keep the floor as their importance', all(archive.importance_of(e) >= 0.6 for e in other.load('Lydia', '0A2C94')['recent']))


def part_gift_taken(tmp: Path):
    gift = ['(Player handed Lydia 600 gold; it was handed over.)']
    check('6. 500 gold or more from the player: gift', memory.talk_flags(gift, 'Lydia', 'Player') == {'gift': 600})
    small = ['(Player handed Lydia 100 gold; it was handed over.)']
    check('...a quarter of her purse or more: gift (100 of 200)', memory.talk_flags(small, 'Lydia', 'Player', purse=200) == {'gift': 100})
    check('...less, or her purse unknown: none', memory.talk_flags(small, 'Lydia', 'Player', purse=1000) == {}
          and memory.talk_flags(small, 'Lydia', 'Player') == {})
    check('...gold she gave the player is no gift to her', memory.talk_flags(['(Lydia handed Player 900 gold; it was handed over.)'], 'Lydia', 'Player') == {})
    caught = ['(Player was caught stealing from Lydia 2 days ago; Player just woke Lydia up.)']
    check('6. caught stealing from her (World\'s line on her): taken', memory.talk_flags(caught, 'Lydia', 'Player') == {'taken': True}
          and memory.talk_flags(['(Lydia caught Player picking their pocket today)'], 'Lydia', 'Player') == {'taken': True})
    mem = memory.empty()
    first, second = {'day': 5, 'text': 'A'}, {'day': 9, 'text': 'B'}
    memory.apply_talk_flags(mem, first, {'taken': True}, 5)
    mem['recent'].append(first)
    memory.apply_talk_flags(mem, second, {'taken': True}, 9)
    check('...once for the 30 days World repeats that line', first.get('flags') == ['taken'] and not second.get('flags'))
    gifts = memory.empty()
    for day, gold in ((1, 600), (2, 700), (3, 800)):
        e = {'day': day, 'text': f'Gift on day {day}.'}
        memory.apply_talk_flags(gifts, e, {'gift': gold}, day)
        gifts['recent'].append(e)
        memory.thin_flag(gifts, 'gift', keep_last=2, total_key='gift_gold')
    flagged = [e for e in gifts['recent'] if 'gift' in (e.get('flags') or [])]
    check('gifts: the latest two stay flagged; older ones merge into the latest with a count and the total',
          len(flagged) == 2 and '(and 1 earlier time, 1400 gold in all)' in flagged[-1]['text'], [e['text'] for e in gifts['recent']])


def part_recognised_broken(tmp: Path):
    mem = memory.empty()
    mem['recent'] = [{'day': 1, 'text': 'A hooded stranger asked for directions.', 'unrecognised': True}]
    e1, e2 = {'day': 4, 'text': 'Player came back.'}, {'day': 6, 'text': 'Player again.'}
    memory.apply_talk_flags(mem, e1, {}, 4, recognised=True)
    mem['recent'].append(e1)
    memory.apply_talk_flags(mem, e2, {}, 6, recognised=True)
    check('9. the talk in which the hooded stranger turned out to be the player: recognised, once', e1.get('flags') == ['recognised'] and not e2.get('flags'))
    src = (SERVER / 'living_world' / 'memory.py').read_text(encoding='utf-8')
    check('...set at the end of a talk where they knew the player and had hooded-stranger memories before',
          "recognised=known_before and not added.get('unrecognised')" in src)
    promises = memory.empty()
    promises['facts'] = [{'kind': 'promise', 'text': 'Player will bring Lydia a sword', 'by': 'Player', 'day': 1, 'due_day': 3, 'status': 'open'}]
    memory.add_promises(promises, '{}', 200)
    last = promises['recent'][-1] if promises['recent'] else {}
    check('5b. a promise that lapses unkept leaves a dated memory with broken_promise (0.8, kept)', last.get('flags') == ['broken_promise']
          and last.get('day') == 200 and 'Player will bring Lydia a sword' in last.get('text', '') and archive.importance_of(last) == 0.8, last)


with tempfile.TemporaryDirectory() as tmp:
    real_today = memory.lw_state.load_today
    for name, part in (('bond', part_bond_follower), ('gift', part_gift_taken), ('recognised', part_recognised_broken)):
        try:
            sub = Path(tmp) / name
            sub.mkdir()
            part(sub)
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'part {name} ran without an error', False, e)
        memory.lw_state.load_today = real_today

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
