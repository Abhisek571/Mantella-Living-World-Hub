"""Offline test for the first meeting with an NPC, through the Hub's real hooks (system_parts, filter_tools,
extra_user_text): on the greeting request the game has not written the new NPC's npc file yet, so nothing that needs
a confirmed adult is given for them (fail closed). Once the game has written the file (minor 0) the next request of the
same talk must have their Background and Now, the reputation line, the command reminder and the intimate action and
line; the NPC part is then built once and stays the same for the rest of the talk. An NPC met before (their npc file is
there from an earlier talk) gets everything at the greeting already.
Run with a Python 3.11: test_first_meeting.py <repo server dir>"""
import json, os, sys, tempfile, types
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import (bio_evolve as B, characters as C, command, embed, lw_state, memory, npc_block, worldlog as W)
memory.SUMMARY_RETRY_SECONDS = 0
embed.use(None)

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


LYDIA_BASE, LYDIA_REF = '0A2C94', '000A2C8E'  # met before
HROKI_BASE, HROKI_REF = '013BB5', '00013BB6'  # the first meeting
MANTELLA = ('# Overview\nYou are in Skyrim.\n\n# Background\nLydia is a housecarl.\nHroki is a barmaid.\n\n'
            '# History\nBelow is a summary of past events.\n\n# Current Scene\nIt is noon.\nRespond as Lydia and Hroki.')
TOOLS = [{'function': {'name': 'SexWithPlayer', 'description': 'x'}}, {'function': {'name': 'Wave', 'description': 'y'}}]


def names(tools):
    return [t['function']['name'] for t in tools]


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    channel = tmp / 'channel'
    (channel / 'npc').mkdir(parents=True)
    lw_state.DATA_DIR = str(channel)
    C.PATH = str(tmp / 'characters.json')
    W.KNOWLEDGE_DIRS[:] = [str(tmp / 'knowledge')]

    def npc_file(base, name, ref, **ints):
        (channel / 'npc' / f'{base}.json').write_text(json.dumps({
            'string': {'name': name, 'ref_id': ref, 'sex': 'female', 'home': 'Whiterun', 'hold': 'Whiterun', 'home_town': 'Whiterun'},
            'int': ints}), encoding='utf-8')

    npc_file(LYDIA_BASE, 'Lydia', LYDIA_REF, minor=0, follower=1)  # from an earlier talk
    (channel / 'conversation.json').write_text(json.dumps({'string': {'player': 'Inga'}, 'int': {'day': 41},
                                                           'stringList': {'speakers': [LYDIA_BASE]}}), encoding='utf-8')
    store = memory.MemoryStore(str(tmp / 'conversations'), 'Inga1')
    people = [('Lydia', LYDIA_REF[-6:]), ('Hroki', HROKI_REF[-6:])]
    for name, ref in people:
        memory.add_memory(store, name, ref, f'{name} and Inga talked about the weather.', day=30)
        B.edit(store, name, ref, text=f'{name} thinks well of Inga now.')
    # three weddings of the player that both saw: "has married several times" for those it reached
    for i, who in enumerate(('Ysolda', 'Carlotta', 'Camilla')):
        W.log_event(store, 'marriage', f'{who} has married Inga.', f'{who} has married Inga.', 35.0 + i,
                    {'town': 'Whiterun', 'hold': 'Whiterun'}, involved=[W.person(who, f'0B000{i}'), W.player_person('Inga')],
                    present=[W.person('Lydia', LYDIA_BASE, LYDIA_REF), W.person('Hroki', HROKI_BASE, HROKI_REF)], size='big')
    data = command.load(store)
    data['commands'].append({'id': 'c1', 'status': 'active', 'text': 'You will follow Inga everywhere.', 'given': 40.0,
                             'until': -1, 'npcs': [{'name': 'Hroki', 'ref_id': HROKI_REF[-6:]}, {'name': 'Lydia', 'ref_id': LYDIA_REF[-6:]}]})
    command.save(store, data)

    fake = types.ModuleType('src.extensions')
    fake._registry = types.SimpleNamespace(speaking_ids=[LYDIA_BASE, HROKI_BASE])
    real_ext = sys.modules.get('src.extensions')
    sys.modules['src.extensions'] = fake
    real_store, real_gates, real_installed = dict(living_world._last_store), living_world._gates, living_world._installed
    living_world._last_store.update(store=store, people=people, summaries=None)
    living_world._gates = lambda: {'SexWithPlayer': 'intimate'}
    living_world._installed = lambda: {'Integration Hub', 'OStim Expansion'}
    C.write_intimacy_mode('npc_decides')
    built = []
    real_npc_text = npc_block.npc_text
    npc_block.npc_text = lambda store_, s, *a, **k: (built.append(s.get('name')), real_npc_text(store_, s, *a, **k))[1]
    try:
        npc_block.talk_over()
        # --- the greeting: Hroki's file is not written yet ---------------------------------------------------------
        parts = living_world._system_parts({'mantella': MANTELLA}, {})
        bg, world, cmd = parts.get('background', ''), parts.get('world', ''), parts.get('command', '')
        check('greeting: Lydia (met before) has her Background and Now', 'Background facts about Lydia' in bg
              and 'Lydia thinks well of Inga now.' in bg, bg)
        check('greeting: Lydia has the reputation line', 'married several times' in world, world)
        check('greeting: no wedding news counted for Hroki yet (age not confirmed)', 'only Lydia has heard this' in world
              and 'Hroki' not in world, world)
        check('greeting: Lydia has the command reminder', 'Lydia' in cmd and 'follow Inga' in cmd, cmd)
        check('greeting: nothing for Hroki yet (no npc file)', 'Hroki thinks well' not in bg and 'Background facts about Hroki' not in bg, bg)
        check('greeting: no intimate action while Hroki is unconfirmed', names(living_world._filter_tools(TOOLS, {})) == ['Wave'])
        check('greeting: no intimacy line', 'own choice' not in living_world._extra_text({'messages': []}))
        first_bg = bg
        # --- the game writes Hroki's file (an adult): the next request of the same talk ----------------------------
        npc_file(HROKI_BASE, 'Hroki', HROKI_REF, minor=0)
        (channel / 'conversation.json').write_text(json.dumps({'string': {'player': 'Inga'}, 'int': {'day': 41},
                                                               'stringList': {'speakers': [LYDIA_BASE, HROKI_BASE]}}), encoding='utf-8')
        built.clear()
        parts = living_world._system_parts({'mantella': MANTELLA}, {})
        bg, world, cmd = parts.get('background', ''), parts.get('world', ''), parts.get('command', '')
        check('second request: Hroki has her Background and Now now', 'Background facts about Hroki' in bg
              and 'Hroki thinks well of Inga now.' in bg, bg)
        check("second request: Lydia's part is the same text as before", first_bg in bg or bg.startswith(first_bg.split('Background facts about Hroki')[0]), bg)
        check('second request: only Hroki is built (once)', built == ['Hroki'], built)
        check('second request: the reputation line covers Hroki too (one line for both)', 'married several times' in world
              and 'only Lydia' not in world, world)
        check('second request: the command reminder names Hroki', 'Hroki' in cmd, cmd)
        offered = names(living_world._filter_tools(TOOLS, {}))
        check('second request: the actions stay as at the greeting (one cached list; the file of Hroki came after it)',
              offered == ['Wave'], offered)
        extra = living_world._extra_text({'messages': []})
        check('...so no intimacy line about a scene this talk cannot offer', 'own choice' not in extra, extra)
        npc_block.talk_over()  # the next talk
        offered = names(living_world._filter_tools(TOOLS, {}))
        extra = living_world._extra_text({'messages': []})
        check('next talk: the intimate action is offered (the command opens it) and the intimacy line names Hroki',
              offered == ['SexWithPlayer', 'Wave'] and 'Hroki' in extra and 'absolute command' in extra, (offered, extra))
        npc_block.talk_over()
        living_world._system_parts({'mantella': MANTELLA}, {})
        living_world._system_parts({'mantella': MANTELLA}, {})
        parts = living_world._system_parts({'mantella': MANTELLA}, {})
        bg, world = parts.get('background', ''), parts.get('world', '')
        # --- the rest of the talk: frozen ---------------------------------------------------------------------------
        built.clear()
        again = living_world._system_parts({'mantella': MANTELLA}, {})
        check('third request: the same NPC part and reputation, nothing built again', again.get('background') == bg
              and again.get('world') == world and built == [], built)
    finally:
        npc_block.npc_text = real_npc_text
        living_world._gates, living_world._installed = real_gates, real_installed
        living_world._last_store.clear()
        living_world._last_store.update(real_store)
        if real_ext is None:
            sys.modules.pop('src.extensions', None)
        else:
            sys.modules['src.extensions'] = real_ext

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
