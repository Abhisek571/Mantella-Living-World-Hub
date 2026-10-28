"""Offline tests for the action filter (server/living_world/action_filter.py).
Run with a Python 3.11: test_action_filter.py <repo server dir>"""
import json, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import action_filter

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)

def tool(name):
    return {'type': 'function', 'function': {'name': name, 'description': name, 'parameters': {'type': 'object', 'properties': {}}}}

def names(tools):
    return [t['function']['name'] for t in tools]

GATES = {'NpcSex': 'close', 'AttackTarget': 'follower', 'RatePositions': 'unrated', 'SettleCrime': 'guard'}
TOOLS = [tool(n) for n in ('Wave', 'NpcSex', 'AttackTarget', 'RatePositions', 'SettleCrime', 'Bow')]
stranger = {'name': 'Knight of the Faith', 'close': 0, 'follower': 0, 'guard': 0, 'rated': 0}
vega = {'name': 'Vega', 'close': 2, 'follower': 1, 'guard': 0, 'rated': 1}
guard = {'name': 'Whiterun Guard', 'close': 0, 'follower': 0, 'guard': 1, 'rated': 1}

# test_stranger_gets_no_close_actions
out = action_filter.filter_actions(TOOLS, [stranger], GATES)
check('stranger gets no close or follower actions', 'NpcSex' not in names(out) and 'AttackTarget' not in names(out), names(out))
check('ungated actions always kept', {'Wave', 'Bow'} <= set(names(out)))
check('unrated gate open for an unrated NPC', 'RatePositions' in names(out))
# test_follower_gets_follower_actions
out = action_filter.filter_actions(TOOLS, [vega], GATES)
check('close follower keeps her actions', {'NpcSex', 'AttackTarget'} <= set(names(out)) and 'RatePositions' not in names(out), names(out))
check('guard action only for guards', 'SettleCrime' not in names(out) and 'SettleCrime' in names(action_filter.filter_actions(TOOLS, [guard], GATES)))
# test_group_union_per_speaker
out = action_filter.filter_actions(TOOLS, [stranger, vega], GATES)
check('group gets the union', {'NpcSex', 'AttackTarget', 'RatePositions'} <= set(names(out)), names(out))
note = action_filter.speaker_note(out, [stranger, vega], GATES)
check('group note names who may use what', 'Only Vega may use' in note and 'AttackTarget' in note and 'Knight of the Faith' in note and 'RatePositions' in note, note)
check('no note for one speaker', action_filter.speaker_note(out, [vega], GATES) == '')
check('no note when everyone may use everything', action_filter.speaker_note(action_filter.filter_actions(TOOLS, [stranger], GATES), [stranger, dict(stranger, name='Pilgrim')], GATES) == '')
# test_order_is_stable
a = action_filter.filter_actions(TOOLS, [vega], GATES)
b = action_filter.filter_actions(list(reversed(TOOLS)), [vega], GATES)
check('order is stable (by name)', names(a) == names(b) == sorted(names(a)), (names(a), names(b)))
# unknown speakers: no filtering, stock behaviour
check('no speakers known: nothing removed', names(action_filter.filter_actions(TOOLS, [], GATES)) == sorted(names(TOOLS)))
check('unknown gate value keeps the action', 'Odd' in names(action_filter.filter_actions([tool('Odd')], [stranger], {'Odd': 'someday'})))
# test_field_gate: "field=value" opens for NPCs whose file has that value (Relationships writes "maras")
mgates = {'AcceptProposal': 'maras=1', 'Divorce': 'maras=3'}
mtools = [tool('AcceptProposal'), tool('Divorce'), tool('Wave')]
check('field gate opens on the value', names(action_filter.filter_actions(mtools, [dict(stranger, maras=1)], mgates)) == ['AcceptProposal', 'Wave'])
check('field gate closed on another value', names(action_filter.filter_actions(mtools, [dict(stranger, maras=3)], mgates)) == ['Divorce', 'Wave'])
check('field gate closed when the field is missing', names(action_filter.filter_actions(mtools, [stranger], mgates)) == ['Wave'])
check('caller list untouched', names(TOOLS) == ['Wave', 'NpcSex', 'AttackTarget', 'RatePositions', 'SettleCrime', 'Bow'])

# gates read from the action files, by the tool name
with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    (d / 'mantella_npc_sex.json').write_text(json.dumps({'identifier': 'mantella_npc_sex', 'name': 'NpcSex', 'lw_gate': 'close'}), encoding='utf-8')
    (d / 'mantella_wave.json').write_text(json.dumps({'identifier': 'mantella_wave', 'name': 'Wave'}), encoding='utf-8')
    (d / 'broken.json').write_text('{"name": ', encoding='utf-8')
    gates = action_filter.load_gates(str(d))
    check('gates loaded by tool name', gates == {'NpcSex': 'close'}, gates)
    check('missing actions folder gives no gates', action_filter.load_gates(str(d / 'nope')) == {})

# test_short_descriptions: only the first sentence of each action's description is kept; the input is not changed
long_tool = {'type': 'function', 'function': {'name': 'Flee', 'description': 'Make NPC(s) run away from a threat. Use when scared. Never when calm.',
                                              'parameters': {'type': 'object', 'properties': {'source': {'type': 'string', 'description': 'Who flees. Names only.'}}}}}
short = action_filter.shorten([long_tool])
check('first sentence only', short[0]['function']['description'] == 'Make NPC(s) run away from a threat.', short[0]['function']['description'])
check('parameters untouched', short[0]['function']['parameters'] == long_tool['function']['parameters'])
check('input not changed', long_tool['function']['description'].endswith('Never when calm.'))
check('no description is fine', action_filter.shorten([tool('Wait')])[0]['function']['description'] == 'Wait')

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
