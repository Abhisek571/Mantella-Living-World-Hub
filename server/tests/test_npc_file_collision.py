"""Offline tests: npc/<6 hex>.json is shared by NPCs of different plugins whose base ids end in the same 6 hex digits
(xx000801 and yy000801, or a light plugin's FE id). A file that holds another NPC (another name, or another full base
id) is treated as empty for this speaker, so a child never inherits an adult's minor 0 or standing.
Run with a Python 3.11: test_npc_file_collision.py <repo server dir>"""
import json, sys, tempfile, types
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import action_filter, lw_state

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


def npc_file(data, base, strings, ints):
    (data / 'npc' / f'{base}.json').write_text(json.dumps({'string': strings, 'int': ints}), encoding='utf-8')


def character(name, base_id, ref_id='0A000D62', hub_base_id=None):
    c = types.SimpleNamespace(name=name, base_id=base_id, ref_id=ref_id)
    if hub_base_id is not None:
        c.hub_base_id = hub_base_id
    return c


with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)
    lw_state.DATA_DIR = str(data)
    (data / 'npc').mkdir()
    (data / 'conversation.json').write_text(json.dumps({'string': {'player': 'Inga'}}), encoding='utf-8')
    # an adult of plugin A wrote the shared file; a child of plugin B has the same last 6 digits
    npc_file(data, '000801', {'name': 'Brenna', 'ref_id': '05000D70', 'base_full': '05000801', 'player': 'Inga',
                              'fact_wedding': 'Brenna married the player.'},
             {'minor': 0, 'close': 1, 'intimate': 1, 'allow_intimacy': 1})

    other = lw_state.load_npc('000801', 'Little Ina')
    check('a file holding another name is empty for this speaker', other == {}, other)
    check('...so the child is not known as an adult', not action_filter.adult(other))
    check('...and no other fields leak (fact lines, standing)', 'fact_wedding' not in other and 'intimate' not in other, other)
    check('the NPC the file belongs to still reads it', lw_state.load_npc('000801', 'Brenna').get('minor') == 0)
    check("Mantella's numbered name (two of the same name in a talk) still matches",
          lw_state.load_npc('000801', 'Brenna 2').get('minor') == 0)
    check('name case and spacing do not matter', lw_state.load_npc('000801', ' brenna ').get('minor') == 0)
    check('no speaker name known: read as before', lw_state.load_npc('000801').get('minor') == 0)
    check('another full base id is empty', lw_state.load_npc('000801', full_id='0A000801') == {})
    check('the same full base id reads it', lw_state.load_npc('000801', full_id='05000801').get('minor') == 0)
    check('a 0x full id compares by value', lw_state.load_npc('000801', full_id='0x05000801').get('minor') == 0)
    # a legacy file (no base_full) is still name-checked
    npc_file(data, '000802', {'name': 'Brenna'}, {'minor': 0})
    check('legacy file without base_full: other name is empty', lw_state.load_npc('000802', 'Little Ina') == {})
    check('legacy file without base_full: same name reads it', lw_state.load_npc('000802', 'Brenna').get('minor') == 0)
    # a file with no name yet (minor written first by an older build) is not dropped by the name check
    npc_file(data, '000803', {}, {'minor': 1})
    check('file without a name: kept', lw_state.load_npc('000803', 'Little Ina').get('minor') == 1)

    # missing file / missing minor still mean "maybe a child"
    check('missing file: not an adult', not action_filter.adult(lw_state.load_npc('0ABCDE', 'Someone')))
    npc_file(data, '000804', {'name': 'Hod'}, {'close': 1})
    check('file without minor: not an adult', not action_filter.adult(lw_state.load_npc('000804', 'Hod')))

    # the server's character check (_is_minor): the child of plugin B, not in the speaker list
    check('_is_minor: child whose base id collides with an adult file is a child',
          living_world._is_minor(character('Little Ina', '000801'), []) is True)
    check('_is_minor: the adult who owns the file is an adult',
          living_world._is_minor(character('Brenna', '000801', '05000D70'), []) is False)

    # a light plugin's NPC (FE012ABC): Mantella's base_id is cut to 000ABC, Direct AI Connect's hub_base_id keeps 012ABC
    npc_file(data, '012ABC', {'name': 'Lia', 'base_full': 'FE012ABC'}, {'minor': 0})
    npc_file(data, '000ABC', {'name': 'Hroki'}, {'minor': 1})
    check('_is_minor: a light-plugin adult is found by hub_base_id',
          living_world._is_minor(character('Lia', '000ABC', 'FE012001', hub_base_id='012ABC'), []) is False)
    check("_is_minor: with Mantella's cut id only, the other NPC's file is not used (name differs)",
          living_world._is_minor(character('Lia', '000ABC', 'FE012001'), []) is True)

    # the speakers of the talk: Direct AI Connect names who it answers for, so the colliding file is left out
    (data / 'conversation.json').write_text(json.dumps({'string': {'player': 'Inga'}, 'stringList': {'speakers': ['000801']}}),
                                            encoding='utf-8')
    registry = types.SimpleNamespace(speaking_ids=['000801'], speaking='Little Ina')
    fake = types.ModuleType('src.extensions')
    fake._registry = registry
    sys.modules['src.extensions'] = fake
    speakers = lw_state.load_conversation()
    check('talk speaker whose file holds another NPC has no state (minor unknown)', speakers == [{'base_id': '000801'}], speakers)
    registry.speaking = 'Brenna'
    speakers = lw_state.load_conversation()
    check('talk speaker who owns the file reads it', speakers and speakers[0].get('minor') == 0, speakers)
    registry.speaking_ids, registry.speaking = ['000801', '000804'], 'Brenna, Hod, Extra'
    speakers = lw_state.load_conversation()
    check('names that do not line up with the ids are not used (file read as before)',
          speakers and speakers[0].get('minor') == 0, speakers)
    registry.speaking_ids, registry.speaking = ['000801', '000804'], 'Little Ina, Hod'
    speakers = lw_state.load_conversation()
    check('two speakers: each checked against their own name', speakers[0] == {'base_id': '000801'}
          and speakers[1].get('name') == 'Hod', speakers)
    del sys.modules['src.extensions']

    # Missives' job line belongs to the character that was played when it was written
    npc_file(data, '000805', {'name': 'Alvor', 'player': 'Inga', 'job': 'Bring Iron Ore.'}, {'minor': 0})
    check("this character's job line is kept", lw_state.load_npc('000805').get('job') == 'Bring Iron Ore.')
    (data / 'conversation.json').write_text(json.dumps({'string': {'player': 'Mira'}}), encoding='utf-8')
    check("another character's job line is left out", 'job' not in lw_state.load_npc('000805'), lw_state.load_npc('000805'))

print(f"\n{len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
