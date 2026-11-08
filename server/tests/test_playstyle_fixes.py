"""Offline tests for the play-style break test fixes: the intimate gate and child rule, extra action gates, asked-before
noise, memories after loading an earlier save, children in prompts and memory, stale world.json, fact owners, light
plugin refs, deleting a memory with its promises, the basic bio away from home and the Settings helpers.
Run with a Python 3.11: test_playstyle_fixes.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import action_filter, asked_before, basic_bio, lw_state, memory, memory_ui, nearby, settings, ui_tab

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


class Char:
    def __init__(self, name, ref_id, bio='A person.', base_id=''):
        self.name, self.ref_id, self.bio, self.base_id = name, ref_id, bio, base_id


def names(actions):
    return [a['function']['name'] for a in actions]


# H1: intimate is its own gate; close is not enough
check('intimate gate opens for intimate 1', action_filter.may_use({'intimate': 1}, 'intimate'))
check('close alone does not open intimate', not action_filter.may_use({'close': 1}, 'intimate'))
check('intimate+unrated combines', action_filter.may_use({'intimate': 1, 'rated': 0}, 'intimate+unrated')
      and not action_filter.may_use({'intimate': 0, 'rated': 0}, 'intimate+unrated'))

# H1: a child among the speakers takes every close or intimate action out, for everyone
tools = [{'function': {'name': n}} for n in ('Sex', 'Hug', 'Wave', 'Join')]
gates = {'Sex': 'intimate', 'Hug': 'close+affection=1', 'Join': 'guard=0'}
adult = {'name': 'Lydia', 'close': 1, 'intimate': 1, 'affection': 1, 'guard': 0}
child = {'name': 'Lucia', 'minor': 1, 'guard': 0}
check('adult alone gets adult actions', names(action_filter.filter_actions(tools, [adult], gates)) == ['Hug', 'Join', 'Sex', 'Wave'])
check('child in the talk: no close or intimate action for anyone',
      names(action_filter.filter_actions(tools, [adult, child], gates)) == ['Join', 'Wave'])
check('speaker note sees no adult action with a child',
      'Sex' not in action_filter.speaker_note(action_filter.filter_actions(tools, [adult, child], gates), [adult, child], gates))

# T-4: settings gate stock actions that carry no lw_gate
check('settings default gates Inventory and Attack', settings.DEFAULTS['action_gates'] == {'Inventory': 'follower', 'Attack': 'follower'})
merged = action_filter.with_settings({'Sex': 'intimate'}, {'Inventory': 'follower', 'Bad': 3})
check('settings gates merged over file gates, bad entries ignored', merged == {'Sex': 'intimate', 'Inventory': 'follower'}, merged)
stock = [{'function': {'name': 'Inventory'}}, {'function': {'name': 'Attack'}}, {'function': {'name': 'Wave'}}]
check('stranger gets no Inventory or Attack', names(action_filter.filter_actions(stock, [{'name': 'Guard'}], merged | {'Attack': 'follower'})) == ['Wave'])
check('follower gets Inventory', 'Inventory' in names(action_filter.filter_actions(stock, [{'name': 'Lydia', 'follower': 1}], merged)))
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, 'settings.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'action_gates': {'Inventory': 'close', 'Attack': 5}}, f)
    check('settings load keeps only text gates', settings.load(path)['action_gates'] == {'Inventory': 'close'}, settings.load(path))
check('gates text round trip', ui_tab.gates_value(ui_tab.gates_text({'Inventory': 'follower', 'Attack': 'follower'})) == {'Inventory': 'follower', 'Attack': 'follower'})
check('gates text drops half entries', ui_tab.gates_value('Inventory: follower, Attack, : close') == {'Inventory': 'follower'})
check('lore budget has an upper bound (SCH-13)', ui_tab.MAX_LORE_BUDGET == 600)

# H6: one prompt line when a child is in a group talk
check('child line in a group', 'Lucia' in living_world.child_line([adult, child]) and 'nothing sexual or romantic' in living_world.child_line([adult, child]))
check('no child line one-on-one or without a child', living_world.child_line([child]) == '' and living_world.child_line([adult, {'name': 'Hulda'}]) == '')

# SCH-1 / T-6: asked-before noise
t = asked_before.topics("Thanks. Goodbye! I'm going. Honestly, Gods, Whiterun is big.", exclude=set())
check('greetings, fillers and apostrophe words are not topics', t == ['Whiterun'], t)
t = asked_before.topics('Riften is far. Have you been to Riften?', exclude=set())
check('sentence-start word kept when also mid-sentence', t == ['Riften'], t)
t = asked_before.topics('Interesting. Tell me about Markarth.', exclude=set())
check('a word after a popped starter stays a topic', t == ['Markarth'], t)

def msgs(*lines):
    return [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': line} for i, line in enumerate(lines)]

with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(str(Path(tmp) / 'conversations'), 'Player1')
    people = [('Lydia', '0A2C94'), ('Hulda', '013BA3')]
    tracker = asked_before.Tracker()
    tracker.notes(msgs('Hi.', 'Lydia: My thane.', 'What about Riverwood?'), people, store, 'Player', 10)
    check('SCH-2: only the NPC who answered last counts', store.load('Lydia', '0A2C94')['asked'].get('Riverwood') == 1
          and not store.load('Hulda', '013BA3').get('asked'), store.load('Hulda', '013BA3').get('asked'))
    check('SS-1: the day is stored with the topic', store.load('Lydia', '0A2C94')['asked_day'].get('Riverwood') == 10)
    lone = [('Lydia', '0A2C94')]
    note = asked_before.Tracker().notes(msgs('Riverwood again?'), lone, store, 'Player', 5)
    check('SS-1: a topic from a later day (earlier save loaded) is new', note == '', note)
    mem = store.load('Lydia', '0A2C94')
    mem['asked'] = {f'Place{i}': 1 for i in range(150)}
    store.save('Lydia', '0A2C94', mem)
    asked_before.Tracker().notes(msgs('And Falkreath?'), lone, store, 'Player', 6)
    asked = store.load('Lydia', '0A2C94')['asked']
    check('asked keeps the newest 100', len(asked) == asked_before.MAX_TOPICS and 'Falkreath' in asked and 'Place0' not in asked, len(asked))

# SS-1: memories after loading an earlier save
mem = memory.empty()
mem['recent'] = [{'day': 5, 'hour': 10, 'text': 'Met the player.'}, {'day': 40, 'hour': 10, 'text': 'Married the player.'}]
mem['feeling'], mem['feeling_day'] = 'adoring', 40
shown = memory.render(mem, 1500, today=10)
check('future entries and feeling hidden', 'Met the player.' in shown and 'Married' not in shown and 'adoring' not in shown, shown)
shown = memory.render(mem, 1500, today=40)
check('loading forward brings them back', 'Married' in shown and 'adoring' in shown, shown)
check('no today: everything shown', 'Married' in memory.render(mem, 1500))
mem['facts'] = [{'kind': 'promise', 'text': 'Bring wine', 'by': 'Player', 'day': 30, 'due_day': 43, 'status': 'open'},
                {'kind': 'promise', 'text': 'Find the sword', 'by': 'Player', 'day': 4, 'due_day': -1, 'status': 'kept', 'settled_day': 35},
                {'kind': 'promise', 'text': 'Old done deal', 'by': 'Player', 'day': 2, 'due_day': -1, 'status': 'kept', 'settled_day': 3}]
facts = memory.facts_text(mem, [], 10, 'Player', 'Lydia')
check('promise made later hidden, one kept later open again', 'Bring wine' not in facts and 'Find the sword' in facts and 'Old done deal' not in facts, facts)

# H6: no "what wins you over" for a child
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(str(Path(tmp) / 'conversations'), 'Player1')
    m = memory.empty()
    m['profile'] = {'talk': 1, 'deeds': 1, 'care': 1, 'gifts': 1, 'physical': 3}
    m['recent'] = [{'day': 3, 'hour': 9, 'text': 'Played tag.'}]
    store.save('Lucia', '01A6E4', m)
    seen = []
    ctx = {'characters': [Char('Lucia', '01A6E4')], 'today': 3, 'profile_seen': lambda c, p: seen.append(p),
           'is_minor': lambda c: c.name == 'Lucia'}
    out = memory.memory_text('', ctx, store)
    check('child: no profile line and none sent to the game', 'wins you over' not in out and not seen and 'Played tag' in out, out)

# SS-2: a stale world.json is not used
check('world while loading is stale', not lw_state.world_current({'loading': 1}, 'Ysolda', 3))
check('world of another character is stale', not lw_state.world_current({'player': 'Ulfric', 'loading': 0}, 'Ysolda', 3))
check('world from a later day is stale', not lw_state.world_current({'player': 'Ysolda', 'day': 40.5}, 'Ysolda', 3))
check('current world is used', lw_state.world_current({'player': 'Ysolda', 'day': 3.7, 'loading': 0}, 'Ysolda', 3))

# SS-3: facts of a module that is not installed are left out
npc = {'fact_saved': '1|-1|2|You were saved by the player.', 'fact_surv_cold': '1|-1|2|You are cold.',
       'fact_other_mod': '1|-1|1|Something else.', 'job': 'Clear the mine.', 'name': 'Hulda'}
texts = [f['text'] for f in lw_state.game_facts(npc, 3, {'Integration Hub', 'World'})]
check('owner installed: kept; owner missing: dropped; unknown owner: kept', texts == ['You were saved by the player.', 'Something else.'], texts)
check('no installed list: everything kept', len(lw_state.game_facts(npc, 3)) == 3)
check('jobs only with Missives', lw_state.jobs_text([npc], {'World'}) == '' and 'Clear the mine.' in lw_state.jobs_text([npc], {'Missives'}))

# ARMY-3: two light-plugin refs that cut to the same short id match nobody by ref; the name decides
check('light refs cut alike', living_world._ref('FE00A802') == living_world._ref('FE00B802'))

# SS-9: deleting a memory takes that talk's open promises with it
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(str(Path(tmp) / 'conversations'), 'Player1')
    m = memory.empty()
    m['recent'] = [{'day': 7, 'hour': 9, 'text': 'Promised to bring mead.'}, {'day': 8, 'hour': 9, 'text': 'Talked.'}]
    m['facts'] = [{'kind': 'promise', 'text': 'Bring mead', 'by': 'Player', 'day': 7, 'due_day': 9, 'status': 'open', 'source': 'ai'},
                  {'kind': 'promise', 'text': 'Visit', 'by': 'Player', 'day': 8, 'due_day': -1, 'status': 'open', 'source': 'ai'}]
    store.save('Hulda', '013BA3', m)
    label = next(l for l in memory_ui.memory_choices(store.load('Hulda', '013BA3')) if 'mead' in l)
    removed = memory_ui.delete_one(store, 'Hulda', '013BA3', label, backup_root=str(Path(tmp) / 'bk'))
    left = [f['text'] for f in store.load('Hulda', '013BA3')['facts']]
    check('promise of the deleted talk removed, others kept', left == ['Visit'] and '1 promise' in removed, (left, removed))

# EXP-11: away from home
bio = basic_bio.text({'name': 'Vigilant Tolan', 'hold': 'Pale', 'here_hold': 'Falkreath', 'location': 'Falkreath', 'race': 'Imperial', 'sex': 'male'})
check('away from home said plainly', 'You are at Falkreath, in Falkreath, far from your home in the Pale.' in bio, bio)
bio = basic_bio.text({'name': 'Ysolda', 'hold': 'Whiterun', 'here_hold': 'Whiterun', 'location': 'Whiterun', 'race': 'Nord', 'sex': 'female'})
check('at home: as before', 'far from' not in bio and 'You live in Whiterun.' in bio, bio)

# EXP-1: lines said nearby go stale after two minutes
check('said nearby kept 120 s', nearby.said_nearby([{'time': 0, 'speaker': 'Heimskr', 'text': 'Talos!'}], 150.0) == ''
      and 'Talos' in nearby.said_nearby([{'time': 0, 'speaker': 'Heimskr', 'text': 'Talos!'}], 100.0))

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
