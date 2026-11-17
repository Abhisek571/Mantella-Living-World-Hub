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
stranger = {'name': 'Knight of the Faith', 'minor': 0, 'close': 0, 'follower': 0, 'guard': 0, 'rated': 0}
mjoll = {'name': 'Mjoll', 'minor': 0, 'close': 2, 'follower': 1, 'guard': 0, 'rated': 1}
guard = {'name': 'Whiterun Guard', 'minor': 0, 'close': 0, 'follower': 0, 'guard': 1, 'rated': 1}

# test_stranger_gets_no_close_actions
out = action_filter.filter_actions(TOOLS, [stranger], GATES)
check('stranger gets no close or follower actions', 'NpcSex' not in names(out) and 'AttackTarget' not in names(out), names(out))
check('ungated actions always kept', {'Wave', 'Bow'} <= set(names(out)))
check('unrated gate open for an unrated NPC', 'RatePositions' in names(out))
check('combined gate needs every part', action_filter.may_use({'close': 1, 'rated': 0}, 'close+unrated')
      and not action_filter.may_use({'close': 0, 'rated': 0}, 'close+unrated') and not action_filter.may_use({'close': 1, 'rated': 3}, 'close+unrated'))
check('combined gate with an empty part stays closed', not action_filter.may_use({'close': 1}, 'close+'))
check('maras_on gate', action_filter.may_use({'maras_on': 1}, 'maras_on=1') and not action_filter.may_use({}, 'maras_on=1'))
# test_follower_gets_follower_actions
out = action_filter.filter_actions(TOOLS, [mjoll], GATES)
check('close follower keeps her actions', {'NpcSex', 'AttackTarget'} <= set(names(out)) and 'RatePositions' not in names(out), names(out))
check('guard action only for guards', 'SettleCrime' not in names(out) and 'SettleCrime' in names(action_filter.filter_actions(TOOLS, [guard], GATES)))
# test_group_union_per_speaker
out = action_filter.filter_actions(TOOLS, [stranger, mjoll], GATES)
check('group gets the union', {'NpcSex', 'AttackTarget', 'RatePositions'} <= set(names(out)), names(out))
note = action_filter.speaker_note(out, [stranger, mjoll], GATES)
check('group note names who may use what', 'Only Mjoll may use' in note and 'AttackTarget' in note and 'Knight of the Faith' in note and 'RatePositions' in note, note)
check('no note for one speaker', action_filter.speaker_note(out, [mjoll], GATES) == '')
check('no note when everyone may use everything', action_filter.speaker_note(action_filter.filter_actions(TOOLS, [stranger], GATES), [stranger, dict(stranger, name='Pilgrim')], GATES) == '')
# test_order_is_stable
a = action_filter.filter_actions(TOOLS, [mjoll], GATES)
b = action_filter.filter_actions(list(reversed(TOOLS)), [mjoll], GATES)
check('order is stable (by name)', names(a) == names(b) == sorted(names(a)), (names(a), names(b)))
# unknown speakers or gates: fail closed, only ungated actions
check('no speakers known: only ungated actions', names(action_filter.filter_actions(TOOLS, [], GATES)) == ['Bow', 'Wave'])
check('unknown gate value hides the action', 'Odd' not in names(action_filter.filter_actions([tool('Odd')], [mjoll], {'Odd': 'someday'})))
check('speaker with no state is a stranger', names(action_filter.filter_actions(TOOLS, [{'base_id': '01A2B3'}], GATES)) == ['Bow', 'RatePositions', 'Wave'])
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
    (d / 'list.json').write_text(json.dumps([{'name': 'Undress', 'lw_gate': 'close'}]), encoding='utf-8')
    check('gates read from a file holding a list', action_filter.load_gates(str(d)).get('Undress') == 'close')

# test_short_descriptions: only the first sentence of each action's description is kept; the input is not changed
long_tool = {'type': 'function', 'function': {'name': 'Flee', 'description': 'Make NPC(s) run away from a threat. Use when scared. Never when calm.',
                                              'parameters': {'type': 'object', 'properties': {'source': {'type': 'string', 'description': 'Who flees. Names only.'}}}}}
short = action_filter.shorten([long_tool])
check('first sentence only', short[0]['function']['description'] == 'Make NPC(s) run away from a threat.', short[0]['function']['description'])
check('parameters untouched', short[0]['function']['parameters'] == long_tool['function']['parameters'])
check('input not changed', long_tool['function']['description'].endswith('Never when calm.'))
check('no description is fine', action_filter.shorten([tool('Wait')])[0]['function']['description'] == 'Wait')
# adult gate: anyone but a child, and nobody while a child is in the talk (OStim Expansion's couple dance)
dance = {'type': 'function', 'function': {'name': 'Affection', 'description': 'A couple dance.'}}
DGATES = {'Affection': 'adult+affection=1'}
child = {'name': 'Dorthe', 'minor': 1, 'affection': 1}
check('adult gate: a stranger with the field may use it', names(action_filter.filter_actions([dance], [dict(stranger, affection=1)], DGATES)) == ['Affection'])
check('adult gate: without the field, not offered', names(action_filter.filter_actions([dance], [stranger], DGATES)) == [])
check('adult gate: a child never', names(action_filter.filter_actions([dance], [child], DGATES)) == [])
check('adult gate: nobody while a child is in the talk', names(action_filter.filter_actions([dance], [dict(stranger, affection=1), child], DGATES)) == [])
# a speaker the game has not confirmed as an adult (no npc file yet, a broken one, no minor key) is treated like a child
unknown = {'base_id': '01A2B3'}  # what load_conversation keeps for a speaker whose file is missing or broken
check('unknown age: not an adult', not action_filter.adult(unknown) and not action_filter.adult({'name': 'X', 'minor': 'junk'})
      and action_filter.adult({'minor': 0}) and not action_filter.adult({'minor': 1}) and not action_filter.adult(None))
check('unknown age: no close or adult action for them', names(action_filter.filter_actions(TOOLS, [dict(unknown, close=1)], GATES)) ==
      ['Bow', 'RatePositions', 'Wave'],
      names(action_filter.filter_actions(TOOLS, [dict(unknown, close=1)], GATES)))
check('unknown age in a group: no close or adult action for anyone', 'NpcSex' not in names(action_filter.filter_actions(TOOLS, [mjoll, unknown], GATES))
      and names(action_filter.filter_actions([dance], [dict(stranger, affection=1), unknown], DGATES)) == [])
# scene gate: OStim Expansion's scene-only actions (change position, rate positions) only while the NPC is in a scene;
# no "scene" value means not in a scene; it only ever removes, never opens
SGATES = {'ChangePosition': 'intimate+scene', 'RateFavoritePositions': 'intimate+unrated+scene', 'SexWithPlayer': 'intimate'}
stools = [tool(n) for n in ('ChangePosition', 'RateFavoritePositions', 'SexWithPlayer', 'Wave')]
lover = dict(stranger, name='Ysolda', intimate=1, rated=0)
check('scene gate: in a scene, the scene actions are offered', names(action_filter.filter_actions(stools, [dict(lover, scene=1)], SGATES))
      == ['ChangePosition', 'RateFavoritePositions', 'SexWithPlayer', 'Wave'])
check('scene gate: not in a scene, only the start action', names(action_filter.filter_actions(stools, [dict(lover, scene=0)], SGATES))
      == ['SexWithPlayer', 'Wave'])
# diag 2026-11-15: at a first meeting the game writes "scene" 9 to 11 s after the greeting; a missing value is "not in a
# scene" (only action files that declare the gate read it, and their module writes the value)
check('scene gate: no value (first meeting, file not complete yet) offers no scene-only action', names(action_filter.filter_actions(stools, [lover], SGATES))
      == ['SexWithPlayer', 'Wave'])
check('scene gate: a junk value is no scene', 'ChangePosition' not in names(action_filter.filter_actions(stools, [dict(lover, scene='x')], SGATES)))
check('scene gate: a child in the talk still takes everything out', names(action_filter.filter_actions(
      stools, [dict(lover, scene=1), dict(child, intimate=1, scene=1)], SGATES)) == ['Wave'])
check('scene gate: an unknown age still takes everything out', names(action_filter.filter_actions(
      stools, [dict(lover, scene=1), dict(unknown, intimate=1, scene=1)], SGATES)) == ['Wave'])
check('scene gate: never opens what intimacy shuts', names(action_filter.filter_actions(stools, [dict(lover, intimate=0, scene=1)], SGATES)) == ['Wave'])
check('scene gate: rated NPC gets no rating even in a scene', names(action_filter.filter_actions(stools, [dict(lover, rated=1, scene=1)], SGATES))
      == ['ChangePosition', 'SexWithPlayer', 'Wave'])
group = [dict(lover, scene=1), dict(lover, name='Aela', scene=0)]
note = action_filter.speaker_note(action_filter.filter_actions(stools, group, SGATES), group, SGATES)
check('scene gate: in a group only the one in the scene may use them', note == '(Only Ysolda may use: ChangePosition, RateFavoritePositions.)', note)
# the real OStim Expansion action files (repository next to this one), when present: scene-only ones carry the gate
OSTIM_ACTIONS = SERVER.resolve().parent.parent / 'Mantella-Living-World-OStim-Expansion' / 'SKSE' / 'Plugins' / 'MantellaSoftware' / 'data' / 'actions'
if OSTIM_ACTIONS.is_dir():
    real = action_filter.load_gates(str(OSTIM_ACTIONS))
    scene_only = sorted(n for n, g in real.items() if 'scene' in g.split('+'))
    check('OStim Expansion: exactly the scene-only actions carry the scene gate', scene_only == ['ChangePosition', 'RateFavoritePositions'], scene_only)
    rtools = [tool(n) for n in real]
    outside = names(action_filter.filter_actions(rtools, [dict(lover, scene=0, close=1, affection=1)], real))
    check('OStim Expansion: outside a scene the start actions stay', {'SexWithPlayer', 'Undress', 'Redress', 'Affection'} <= set(outside)
          and not {'ChangePosition', 'RateFavoritePositions'} & set(outside), outside)
    inside = names(action_filter.filter_actions(rtools, [dict(lover, scene=1, close=1, affection=1)], real))
    check('OStim Expansion: in a scene every intimate action is offered', set(real) <= set(inside), inside)
else:
    print('SKIP OStim Expansion action files not found next to this repository')
gated_tool = {'type': 'function', 'function': {'name': 'NpcSex', 'description': 'Start a scene. Only when the player asked and she agrees.'}}
check('gated action keeps its whole description', action_filter.shorten([gated_tool], GATES)[0]['function']['description'].endswith('she agrees.'))

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
