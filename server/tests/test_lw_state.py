"""Offline tests for the file channel reader (server/living_world/lw_state.py).
Run with a Python 3.11: test_lw_state.py <repo server dir>"""
import json, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import lw_state

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)

with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)
    lw_state.DATA_DIR = str(data)
    # test_missing_file_returns_empty
    check('missing npc file is empty', lw_state.load_npc('000A2C94') == {})
    check('missing world file is empty', lw_state.load_world() == {})
    check('missing said-nearby is empty', lw_state.load_said_nearby() == [])
    check('missing conversation is empty', lw_state.load_conversation() == [])
    # test_reads_npc_by_base_id (JsonUtil writes ints under "int" and strings under "string")
    (data / 'npc').mkdir()
    # a name in the game's codepage (not UTF-8) must not blank the whole file
    (data / 'npc' / '0BADC0.json').write_bytes('{"string": {"name": "Sóra"}, "int": {"close": 1}}'.encode('cp1252'))
    check('non-UTF-8 file still read', lw_state.load_npc('0BADC0').get('close') == 1, lw_state.load_npc('0BADC0'))
    (data / 'npc' / '0001A67B.json').write_text(json.dumps({'int': {'close': 1, 'follower': 0, 'guard': 0, 'rated': 0},
                                                            'string': {'name': 'Alvor', 'ref_id': '00013482'}}), encoding='utf-8')
    npc = lw_state.load_npc('0001A67B')
    check('reads npc by base id', npc == {'close': 1, 'follower': 0, 'guard': 0, 'rated': 0, 'name': 'Alvor', 'ref_id': '00013482', 'base_id': '0001A67B'}, npc)
    check('base id case does not matter', lw_state.load_npc('0001a67b').get('name') == 'Alvor')
    # test_half_written_json_returns_empty
    (data / 'npc' / '00000BAD.json').write_text('{"int": {"close": 1', encoding='utf-8')
    check('half-written npc file is empty', lw_state.load_npc('00000BAD') == {})
    (data / 'world.json').write_text('not json at all', encoding='utf-8')
    check('broken world file is empty', lw_state.load_world() == {})
    check('path tricks refused', lw_state.load_npc('../world') == {} and lw_state.load_npc('') == {})
    # conversation: the list of speakers by base id, each with its npc file
    (data / 'conversation.json').write_text(json.dumps({'stringList': {'speakers': ['0001A67B', '00000BAD', '0000DEAD', '../x']}}), encoding='utf-8')
    speakers = lw_state.load_conversation()
    check('conversation lists speakers with their state', speakers[0].get('name') == 'Alvor' and speakers[0]['close'] == 1, speakers)
    check('speakers without a readable file are kept with no state (strangers)',
          speakers[1:] == [{'base_id': '00000BAD'}, {'base_id': '0000DEAD'}], speakers)
    # world.json and said_nearby.json in the same JsonUtil shape
    (data / 'world.json').write_text(json.dumps({'int': {'mq_stage': 10}, 'string': {'war_side': 'none'}}), encoding='utf-8')
    check('world flattened', lw_state.load_world() == {'mq_stage': 10, 'war_side': 'none'}, lw_state.load_world())
    (data / 'said_nearby.json').write_text(json.dumps({'lines': [{'speaker': 'Serana', 'text': 'Nice night.'}]}), encoding='utf-8')
    check('said nearby lines', lw_state.load_said_nearby() == [{'speaker': 'Serana', 'text': 'Nice night.'}])
    check('missing banter file is empty', lw_state.load_banter() == {})
    (data / 'banter.json').write_text(json.dumps({'int': {'active': 1}, 'string': {'seed': 'The fight just ended.'}}), encoding='utf-8')
    check('banter flattened', lw_state.load_banter() == {'active': 1, 'seed': 'The fight just ended.'}, lw_state.load_banter())
    # test_jobs_text: Missives board jobs from each speaker's file, one line per speaker that has one
    speakers = [{'name': 'Alvor', 'job': 'You need Iron Ore brought to you; you posted a notice on the job board for it.'},
                {'name': 'Hilde', 'job': ''}, {'name': 'Sigrid'}]
    text = lw_state.jobs_text(speakers)
    check('jobs text for givers only', text == 'Job board notices Alvor posted (Alvor knows this):\n- You need Iron Ore brought to you; you posted a notice on the job board for it.', text)
    check('no jobs, no text', lw_state.jobs_text([{'name': 'Hilde'}]) == '')

check('data dir is next to the exe folder', lw_state.default_data_dir().replace('\\', '/').endswith('StorageUtilData/MantellaLivingWorld'))

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
