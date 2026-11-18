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
    (data / 'world.json').write_text(json.dumps({'fame': {'Whiterun': 3}, 'hold': 'Whiterun', 'events': []}), encoding='utf-8')
    check('plain world file read as it is', lw_state.load_world() == {'fame': {'Whiterun': 3}, 'hold': 'Whiterun', 'events': []}, lw_state.load_world())
    (data / 'npc' / '00BEEF.json').write_text(json.dumps({'string': {'name': 'Brynjolf', 'hold': 'Rift'}, 'stringList': {'groups': ['Thieves Guild']}}), encoding='utf-8')
    check('npc groups list read', lw_state.load_npc('00BEEF').get('groups') == ['Thieves Guild'], lw_state.load_npc('00BEEF'))
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

with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = tmp
    check('no day when the file is missing', lw_state.load_today() is None)
    (Path(tmp) / 'conversation.json').write_text(json.dumps({'int': {'day': 44}}), encoding='utf-8')
    check('today read from the conversation file', lw_state.load_today() == 44)
    (Path(tmp) / 'conversation.json').write_text(json.dumps({'int': {'day': True}}), encoding='utf-8')
    check('a day that is not a number is ignored', lw_state.load_today() is None)
facts = lw_state.game_facts({'name': 'Lydia', 'fact_healed': '40|-1|3|You healed Lydia', 'fact_food': '41|42|1|Ate stew',
                             'fact_old': '10|20|2|Gone by now', 'fact_broken': 'nonsense', 'fact_bad': 'a|b|c|text',
                             'FACT_UPPER': '42|-1|2|Key case does not matter', 'other': '1|2|3|not a fact', 'fact_num': 5}, 42)
check('expired, broken and other keys left out', [f['text'] for f in facts] == ['You healed Lydia', 'Key case does not matter', 'Ate stew'], facts)
check('no expiry check without a day', len(lw_state.game_facts({'fact_old': '10|20|2|Gone by now'}, None)) == 1)
check('a text may hold the separator', lw_state.game_facts({'fact_x': '1|-1|1|a|b'}, 5)[0]['text'] == 'a|b')
check('no npc means no facts', lw_state.game_facts(None, 5) == [])

check('data dir is next to the exe folder', lw_state.default_data_dir().replace('\\', '/').endswith('StorageUtilData/MantellaLivingWorld'))

# game words in any letter case (Papyrus reuses a spelling it already holds): keys, sections and names
import json as _json, tempfile as _tempfile, os as _os
from living_world import console as _console
with _tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = tmp
    _os.makedirs(_os.path.join(tmp, 'npc'))
    with open(_os.path.join(tmp, 'conversation.json'), 'w', encoding='utf-8') as f:
        _json.dump({'Int': {'DAY': 12, 'talk_open': 1}, 'STRING': {'Player': 'Player', 'Talk_ID': 't1'},
                    'StringList': {'Speakers': ['013489']}}, f)
    with open(_os.path.join(tmp, 'npc', '013489.json'), 'w', encoding='utf-8') as f:
        _json.dump({'int': {'Minor': 0}, 'string': {'Name': 'Gerdur'}}, f)
    check('case: day, player, talk id and speakers read whatever the letter case',
          lw_state.load_today() == 12 and lw_state.load_player_name() == 'Player' and _console._talk_id() == 't1'
          and [s.get('name') for s in lw_state.load_conversation()] == ['Gerdur'] and lw_state.load_npc('013489').get('minor') == 0)
    with open(_os.path.join(tmp, 'battles.json'), 'w', encoding='utf-8') as f:
        _json.dump({'player': 'PLAYER', 'fights': [{'id': 1}]}, f)
    check('case: the same character in other letters keeps its fights', lw_state.load_battles() == [{'id': 1}])
    check('case: the same character in other letters keeps world.json', lw_state.world_current({'player': 'PLAYER'}, 'Player', None))
    rows = _console.read_queue({'STRINGLIST': {'Key': ['k1', ''], 'Text': ['give me gold', 'x'], 'Refs': ['', ''],
                                               'Names': ['', ''], 'Time': ['12', ''], 'Player': ['PLAYER', ''], 'Tool': ['1', '']}})
    check('case: Console wishes read with keys in any case; a row without a key is left out (and logged)', [r['key'] for r in rows] == ['k1'], rows)
    check('case: a wish by the same character in other letters is answered',
          _console._refused(rows[0], {'console_actions': True}, 'Player', 12) == '', _console._refused(rows[0], {'console_actions': True}, 'Player', 12))

# tools/build.py finds Git Bash explicitly (a bare "bash" is WSL's on many PCs and cannot run the Spriggit wrapper)
import importlib.util as _ilu, shutil as _shutil
_spec = _ilu.spec_from_file_location('mlw_build_test', _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), '..', 'tools', 'build.py'))
_os.environ.setdefault('MLW_MO2', _os.getcwd()); _os.environ.setdefault('MLW_GAME', _os.getcwd())
_build = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_build)
with _tempfile.TemporaryDirectory() as tmp:
    fake = _os.path.join(tmp, 'Git', 'bin', 'bash.exe'); _os.makedirs(_os.path.dirname(fake)); open(fake, 'w').close()
    old = dict(_os.environ)
    try:
        _os.environ.pop('MLW_BASH', None)
        _os.environ['ProgramFiles'] = tmp
        check('build: Git Bash under Program Files is used, not a bare "bash"', _build.git_bash() == fake, _build.git_bash())
        _os.environ['MLW_BASH'] = fake
        check('build: MLW_BASH wins', _build.git_bash() == fake)
    finally:
        _os.environ.clear(); _os.environ.update(old)

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
