"""Offline tests for how the world log is wired into the rest of the Hub: the hooks in living_world/__init__.py (news
at talk start, reputation in the cached part and the same all talk, strangeness in the newest message), absolute
command scopes (kept on the record, given back when the command ends), the release choices in the world log, World's
crimes.json, the spell mark surviving a fold into the archive, Now paragraphs following the loaded save, and the
talk detection of the news. No model and no numpy needed.
Run with a Python 3.11: test_world_wiring.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world as LW
from living_world import (bio_evolve, characters, command, embed, lw_state, memory, news as N, npc_block, release,
                          settings, worldlog as W)
embed.use(None)

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


tmp = Path(tempfile.mkdtemp())
channel = tmp / 'channel'
(channel / 'npc').mkdir(parents=True)
lw_state.DATA_DIR = str(channel)
settings.PATH = str(tmp / 'settings.json')
characters.PATH = str(tmp / 'characters.json')
know = tmp / 'knowledge'
know.mkdir()
W.KNOWLEDGE_DIRS[:] = [str(know)]
(know / 'places.json').write_text(json.dumps({'Riverwood': {'hold': 'Whiterun Hold', 'kind': 'town'},
                                              'Whiterun': {'hold': 'Whiterun Hold', 'kind': 'city'}}), encoding='utf-8')
PLAYER = 'Vega'
TODAY = 40
conv = tmp / 'conv'
store = memory.MemoryStore(str(conv), 'Vega1')
LW._installed = lambda: {'Integration Hub', 'World', 'Relationships'}

# name: (base, Mantella ref, npc file values)
PEOPLE = {'Sigrid': ('013BA1', '013BA6', {'sex': 'female', 'home_town': 'Riverwood', 'hold': 'Whiterun'}),
          'Alvor': ('013BA0', '013BA5', {'sex': 'male', 'home_town': 'Riverwood', 'hold': 'Whiterun'}),
          'Dorthe': ('013BA2', '013BA7', {'sex': 'female', 'home_town': 'Riverwood', 'hold': 'Whiterun', 'minor': 1}),
          'Faendal': ('01A69E', '01A69F', {'sex': 'male', 'home_town': 'Riverwood', 'hold': 'Whiterun'}),
          'Lydia': ('0A2C94', '0A2C8E', {'sex': 'female', 'home_town': 'Whiterun', 'hold': 'Whiterun'})}
for name, (base, ref, extra) in PEOPLE.items():
    (channel / 'npc' / f'{base}.json').write_text(json.dumps({
        'string': {k: v for k, v in dict(extra, name=name, ref_id='00' + ref).items() if isinstance(v, str)},
        'int': {'minor': 0, **{k: v for k, v in extra.items() if isinstance(v, int)}}}), encoding='utf-8')
(channel / 'ties.json').write_text(json.dumps({'013BA1': {'name': 'Sigrid', 'home': "Alvor and Sigrid's House", 'ties': [
    {'kind': 'spouse', 'base': '013BA0', 'name': 'Alvor'}, {'kind': 'child', 'base': '013BA2', 'name': 'Dorthe'}]}}),
    encoding='utf-8')


def talk(*names, day=TODAY, talk_fields=None):
    """The game side's conversation.json for a talk with these NPCs."""
    data = {'string': {'player': PLAYER}, 'int': {'day': day}, 'stringList': {'speakers': [PEOPLE[n][0] for n in names]}}
    for k, v in (talk_fields or {}).items():
        data.setdefault('int' if isinstance(v, int) else 'float' if isinstance(v, float) else 'string', {})[k] = v
    (channel / 'conversation.json').write_text(json.dumps(data), encoding='utf-8')


class Char:
    def __init__(self, name):
        self.name, self.ref_id, self.bio = name, PEOPLE[name][1], ''


class Game:
    conversation_folder_path = str(conv)


class Summaries:
    _Summaries__game, _Summaries__language_name = Game(), 'English'

    def summarize_conversation(self, text, prompt):
        return ''


def hook_talk(*names):
    """One talk start the way Direct AI Connect calls the hooks: memory_text, then system_parts and extra_user_text."""
    talk(*names)
    npc_block.talk_over()
    N._talks.clear()
    chars = [Char(n) for n in names]
    text = LW._memory_text('stock', {'characters': chars, 'world_id': 'Vega1', 'summaries': Summaries()})
    mantella = ('# Overview\nA talk.\n\n# Background\n' + '\n'.join(f'{n} lives in Skyrim.' for n in names)
                + f'\n\n# History\n{text}\n\n# Current Scene\nNoon.\nRespond as {names[0]}.')
    parts = LW._system_parts({'mantella': mantella}, {})
    newest = LW._extra_text({'messages': [{'role': 'system', 'content': mantella}, {'role': 'user', 'content': 'Hi'}]})
    return text, parts, newest, mantella


def shown(name, st=None):
    return [e for e in memory._peek(st or store, name, PEOPLE[name][1])['recent'] if not e.get('hidden')]


def person(name):
    base, ref, _ = PEOPLE[name]
    return W.person(name, base, ref)


for name in PEOPLE:
    store.save(name, PEOPLE[name][1], dict(memory.empty(), recent=[
        {'day': 20, 'hour': 9, 'text': f'{name} sold Vega some bread.', 'witnesses': [name]}]))

# --- 1. hooks: news at talk start, reputation cached all talk, strangeness in the newest message --------------------------
wed = W.log_event(store, 'marriage', 'Sigrid has married Vega.', 'Sigrid has married Vega.', day=30.5,
                  place={'town': 'Riverwood', 'hold': 'Whiterun'}, involved=[person('Sigrid'), W.player_person(PLAYER)],
                  present=[person('Sigrid')], event_id='wed-1', known=[person('Sigrid')])
kill = W.log_event(store, 'killing', 'Vega killed Sven at Riverwood, who was no threat.',
                   'Vega killed Sven at Riverwood, who was no threat.', day=35.0, place={'town': 'Riverwood', 'hold': 'Whiterun'},
                   involved=[W.player_person(PLAYER), W.person('Sven', '0BB0AA')], present=[person('Alvor')],
                   event_id='kill-1', flags={'player_named': True, 'by_player': True})
check('events logged', wed and kill)
text, parts, newest, mantella = hook_talk('Faendal')
check('news: a same-town rumour reached Faendal before his memories were shown', 'people in Riverwood are saying' in text, text)
check('reputation: in the cached world part', 'What people around Whiterun have come to believe about Vega' in parts.get('world', '')
      and 'no threat' in parts['world'], parts.get('world'))
first_world = parts['world']
W.log_event(store, 'killing', 'Vega killed Hod at Riverwood, who was no threat.', 'Vega killed Hod at Riverwood, who was no threat.',
            day=35.5, place={'town': 'Riverwood', 'hold': 'Whiterun'}, involved=[W.player_person(PLAYER), W.person('Hod', '0BBB01')],
            present=[person('Faendal')], event_id='kill-2', flags={'player_named': True, 'by_player': True})
again = LW._system_parts({'mantella': mantella}, {})
check('reputation: the same text all talk (cache), even after the log changed', again['world'] == first_world)
npc_block.talk_over()
later = LW._system_parts({'mantella': mantella}, {})
check('reputation: the next talk sees the change', 'people who were no threat' in later['world'], later['world'])
check('no strangeness without a command', 'acting like' not in newest)

# strangeness: Sigrid under an enchantment; Alvor (her spouse, a tie) in the talk with her
command.save(store, {'commands': [{'id': 'c-love', 'key': 'k-love', 'text': 'You love Vega above everyone.', 'given': 38.0,
                                   'npcs': [{'name': 'Sigrid', 'ref_id': PEOPLE['Sigrid'][1]}], 'forget': '', 'aware': False,
                                   'status': 'active', 'hidden': [], 'until': -1.0, 'hours': 0.0}], 'seen': ['k-love'], 'ended': []})
text, parts, newest, _ = hook_talk('Alvor', 'Sigrid')
check('strangeness: the spouse notices, in the newest message', 'Alvor knows Sigrid well, and Sigrid has not been acting like herself' in newest, newest)
check('strangeness: never in the cached part', 'acting like' not in ''.join(v for v in parts.values() if isinstance(v, str)))
_, _, child_newest, _ = hook_talk('Dorthe', 'Sigrid')
check('strangeness: a child notices nothing', 'Dorthe knows' not in child_newest, child_newest)
check('child: no wedding news for Dorthe', not any('married' in str(e.get('text')) for e in shown('Dorthe')))
command.save(store, {'commands': [], 'seen': ['k-love'], 'ended': []})

# --- 2. command scopes ---------------------------------------------------------------------------------------------------
N.catch_up(store, W.identify({'name': 'Faendal', 'ref_id': PEOPLE['Faendal'][1], 'base_id': '01A69E', 'home_town': 'Riverwood'},
                             {'store': store}), TODAY)
check('Faendal heard of the wedding', any('married' in str(e.get('text')) for e in shown('Faendal')))
talk('Sigrid')
values = dict(settings.DEFAULTS, command_model_check=False)
rec = {'id': 'c-scope', 'key': 'k-scope', 'text': 'Forget the wedding, and everyone in Riverwood too', 'given': 39.0,
       'npcs': [{'name': 'Sigrid', 'ref_id': PEOPLE['Sigrid'][1]}], 'forget': '', 'aware': False, 'status': 'checking',
       'hidden': [], 'until': -1.0, 'hours': 0.0}
command.save(store, {'commands': [rec], 'seen': ['k-scope'], 'ended': []})
command.finish(store, 'c-scope', values, None)
saved = next(c for c in command.load(store)['commands'] if c['id'] == 'c-scope')
check('scope: the wipes are kept on the record', saved.get('scope_wipes'), saved)
check('scope: Faendal (absent, same town) lost the wedding news', not any('married' in str(e.get('text')) for e in shown('Faendal')))
check('scope: forget mode stored for the world log (one thing: clean)', saved.get('forget_mode') == 'clean', saved.get('forget_mode'))
back = command.remove(store, 'c-scope')
check('scope: removing the command gives the wipes back', any('married' in str(e.get('text')) for e in shown('Faendal'))
      and not any(w.get('id') in saved['scope_wipes'] for e in W.events(store) for w in e.get('wipes') or []), back)

# a forget with no scope words: only the commanded NPC, and she stops passing it on
rec2 = dict(rec, id='c-plain', key='k-plain', text='Forget the wedding.')
command.save(store, {'commands': [rec2], 'seen': ['k-plain'], 'ended': []})
command.finish(store, 'c-plain', values, None)
saved = next(c for c in command.load(store)['commands'] if c['id'] == 'c-plain')
blocked = N.blocked_for(store, W.identify({'name': 'Sigrid', 'ref_id': PEOPLE['Sigrid'][1], 'base_id': '013BA1'}, {'store': store}),
                        W.find(store, 'wed-1'))
check('plain forget: wiped for her only (she no longer passes it on)', saved.get('scope_wipes') and blocked
      and any('married' in str(e.get('text')) for e in shown('Faendal')), saved.get('scope_wipes'))
command.remove(store, 'c-plain')

# an order with no forget: nothing is wiped, whatever its words
rec3 = dict(rec, id='c-obey', key='k-obey', text='Obey everyone who was there today')
command.save(store, {'commands': [rec3], 'seen': ['k-obey'], 'ended': []})
command.finish(store, 'c-obey', values, None)
check('an order to obey wipes nothing', not next(c for c in command.load(store)['commands'] if c['id'] == 'c-obey').get('scope_wipes'))
command.remove(store, 'c-obey')

# --- 3. release choices in the world log -------------------------------------------------------------------------------------
for cid, choice in (('r-spell', 'spell'), ('r-forget', 'forget'), ('r-believe', 'believe')):
    r = dict(rec, id=cid, key='k-' + cid, text='You adore Vega.', status='active', forget='')
    command.save(store, {'commands': [r], 'seen': [], 'ended': []})
    out = release.release_command(store, cid, choice, player=PLAYER, today=TODAY)
    check(f'release {choice}: done', out.get('ok'), out)
ev = {c: W.find(store, f'release-{c}') for c in ('r-spell', 'r-forget', 'r-believe')}
check('release spell: came to light, but never news (no public text)', ev['r-spell'] and ev['r-spell']['came_to_light']
      and ev['r-spell']['public_text'] == '', ev['r-spell'])
check('release forget: never news', ev['r-forget'] and ev['r-forget']['public_text'] == '', ev['r-forget'])
check('release believe: the Hub record only', ev['r-believe'] and not ev['r-believe']['public_text'])
# a spell release gives back what the command's scope wiped
r = dict(rec, id='r-scope', key='k-r-scope', status='checking', text='Forget the wedding, and everyone in Riverwood too')
command.save(store, {'commands': [r], 'seen': [], 'ended': []})
command.finish(store, 'r-scope', values, None)
check('scope before release: Faendal lost it', not any('married' in str(e.get('text')) for e in shown('Faendal')))
release.release_command(store, 'r-scope', 'spell', player=PLAYER, today=TODAY)
check('release spell: the scope wipes come back', any('married' in str(e.get('text')) for e in shown('Faendal')))

# --- 4. World's crimes.json ------------------------------------------------------------------------------------------------
crimes = {'player': PLAYER, 'crimes': [
    {'id': 'assault-0001A6B0-37000', 'crime': 'assault', 'day': 37.0, 'place': 'Riverwood', 'town': 'Riverwood', 'hold': 'Whiterun',
     'victim': {'base': '0BB0B0', 'ref_id': '0001A6B0', 'name': 'Embry', 'thalmor': 0},
     'witnesses': [{'base': '013BA0', 'ref_id': '00013BA5', 'name': 'Alvor'}], 'by_player': True, 'player': PLAYER},
    {'id': 'other-1', 'crime': 'murder', 'day': 37.1, 'place': 'Riverwood', 'town': 'Riverwood', 'hold': 'Whiterun',
     'victim': {'base': '0BB0B1', 'ref_id': '0001A6B1', 'name': 'Someone', 'thalmor': 0}, 'witnesses': [], 'by_player': True,
     'player': 'Another Character'}],
    'deaths': [{'id': 'death-0001A6C0-38000', 'base': '0BB0C0', 'ref_id': '0001A6C0', 'name': 'Hilde', 'day': 38.0,
                'place': 'Riverwood', 'town': 'Riverwood', 'hold': 'Whiterun', 'by_player': False, 'unique': True,
                'witnesses': [], 'player': PLAYER},
               {'id': 'death-0001A6C1-38100', 'base': '0BB0C1', 'ref_id': '0001A6C1', 'name': 'Orgnar', 'day': 38.1,
                'place': 'Riverwood', 'town': 'Riverwood', 'hold': 'Whiterun', 'by_player': False, 'unique': True,
                'witnesses': [], 'player': PLAYER}]}
(channel / 'crimes.json').write_text(json.dumps(crimes), encoding='utf-8')
(channel / 'battles.json').write_text(json.dumps({'player': PLAYER, 'fights': [{
    'id': 'f-9', 'active': 0, 'start': 38.05, 'end': 38.12, 'place': 'Riverwood', 'fighters': [
        {'name': 'Vega', 'ref_id': '00000014', 'role': 'player', 'side': 0},
        {'name': 'Orgnar', 'ref_id': '0001A6C1', 'base_id': '0BB0C1', 'role': 'ally', 'dead': 1, 'side': 0},
        {'name': 'Bandit', 'ref_id': '0001A6D0', 'role': 'enemy', 'hostile': 1, 'dead': 1, 'side': 1}]}]}), encoding='utf-8')
W.ingest(store, PLAYER, [])
assault = W.find(store, 'crime-assault-0001A6B0-37000')
check('crimes: an assault of this character is logged', assault and assault['kind'] == 'crime', assault)
check("crimes: another character's row is never read", not W.find(store, 'crime-other-1'))
check('crimes: a named death is logged', W.find(store, 'death-0001A6C0-38000'))
check('crimes: a death in a recorded fight is not logged twice', not W.find(store, 'death-0001A6C1-38100')
      and not any(e['kind'] == 'death' and 'Orgnar' in e['true_text'] for e in W.events(store)))
# the same day the assault becomes a murder, with a child among the witnesses
crimes['crimes'].append({'id': 'murder-0001A6B0-37200', 'crime': 'murder', 'day': 37.2, 'place': 'Riverwood', 'town': 'Riverwood',
                         'hold': 'Whiterun', 'victim': {'base': '0BB0B0', 'ref_id': '0001A6B0', 'name': 'Embry', 'thalmor': 0},
                         'witnesses': [{'base': '013BA0', 'ref_id': '00013BA5', 'name': 'Alvor'},
                                       {'base': '013BA2', 'ref_id': '00013BA7', 'minor': 1}], 'by_player': True, 'player': PLAYER})
(channel / 'crimes.json').write_text(json.dumps(crimes), encoding='utf-8')
W.ingest(store, PLAYER, [])
W.ingest(store, PLAYER, [])
murder = W.find(store, 'crime-murder-0001A6B0-37200')
check('crimes: the murder is logged once', murder and murder['kind'] == 'killing'
      and sum(1 for e in W.events(store) if e['id'] == murder['id']) == 1, murder)
check('crimes: the same-day attack is taken back for the killing',
      (W.find(store, 'crime-assault-0001A6B0-37000') or {}).get('retracted') is True)
child = next((p for p in murder['present'] if p.get('base') == '013BA2'), None)
check('crimes: a child witness keeps the minor flag and no name', child and child.get('minor') and not child.get('name'), murder['present'])
check('crimes: the child is remembered as a child', (W.lookup(W.read_people(store), child) or {}).get('minor') == 1)
d = N.catch_up(store, W.identify({'name': 'Alvor', 'ref_id': PEOPLE['Alvor'][1], 'base_id': '013BA0', 'home_town': 'Riverwood'},
                                 {'store': store}), TODAY)
check('crimes: a witness gets a "seen" memory at the next talk', any(x['id'] == murder['id'] and x['how'] == 'seen' for x in d), d)
# a murder row for a killing the fight record already has is not logged again
(channel / 'battles.json').write_text(json.dumps({'player': PLAYER, 'fights': [{
    'id': 'f-10', 'active': 0, 'start': 39.0, 'end': 39.05, 'place': 'Riverwood', 'fighters': [
        {'name': 'Vega', 'ref_id': '00000014', 'role': 'player'},
        {'name': 'Bram', 'ref_id': '0001A6E0', 'base_id': '0BB0E0', 'role': 'bystander', 'dead': 1, 'killer': '00000014'}]}]}),
    encoding='utf-8')
crimes['crimes'].append({'id': 'murder-0001A6E0-39010', 'crime': 'murder', 'day': 39.01, 'place': 'Riverwood', 'town': 'Riverwood',
                         'hold': 'Whiterun', 'victim': {'base': '0BB0E0', 'ref_id': '0001A6E0', 'name': 'Bram', 'thalmor': 0},
                         'witnesses': [], 'by_player': True, 'player': PLAYER})
(channel / 'crimes.json').write_text(json.dumps(crimes), encoding='utf-8')
W.ingest(store, PLAYER, [])
check('crimes: one killing for a fight record plus a murder row',
      sum(1 for e in W.events(store) if e['kind'] == 'killing' and 'Bram' in e['true_text']) == 1,
      [e['id'] for e in W.events(store) if 'Bram' in e['true_text']])
check('crimes: a missing file reads as nothing', W.from_crimes(store, PLAYER, data={}) == 0 and W.from_crimes(store, '', None) == 0)
check('crimes: a Thalmor victim is flagged', W.from_crime(store, {'id': 'x-th', 'crime': 'assault', 'day': 39.5,
      'victim': {'name': 'Ondolemar', 'base': '0BB0F0', 'ref_id': '0001A6F0', 'thalmor': 1}, 'witnesses': []}, PLAYER).get('thalmor'))

# --- 5. the spell mark survives a fold into the archive ------------------------------------------------------------------
st2 = memory.MemoryStore(str(tmp / 'conv2'), 'Vega2')
st2.save('Lydia', PEOPLE['Lydia'][1], dict(memory.empty(), recent=[
    {'day': 30, 'hour': 9, 'text': 'Vega told me I love her and I did.', 'witnesses': ['Lydia'], 'command': 'c-x'},
    {'day': 31, 'hour': 9, 'text': 'We walked to Riverwood.', 'witnesses': ['Lydia']}]))
data = st2.load('Lydia', PEOPLE['Lydia'][1])
data['recent'] = data['recent'][1:]  # the first memory was folded away: only the archive has it now
st2.save('Lydia', PEOPLE['Lydia'][1], data)
marked = release.mark_spell(st2, 'Lydia', PEOPLE['Lydia'][1], 'c-x', "while under Vega's spell")
rows = st2.archive_for('Lydia', PEOPLE['Lydia'][1]).rows()
row = next((r for r in rows if 'love her' in r['text']), None)
check('spell mark: an archived memory made under the command is marked', marked == 1 and row and row.get('spell') == "while under Vega's spell",
      (marked, row))
check('spell mark: recalled, it reads with the mark', row and memory._line(row).find("(while under Vega's spell)") > 0, row and memory._line(row))
check('spell mark: other memories untouched', all(not r.get('spell') for r in rows if 'Riverwood' in r['text']))

# --- 6. the Now paragraph follows the loaded save -------------------------------------------------------------------------
st3 = memory.MemoryStore(str(tmp / 'conv3'), 'Vega3')
name, ref = 'Lydia', PEOPLE['Lydia'][1]
st3.save(name, ref, dict(memory.empty(), recent=[{'day': 30, 'hour': 9, 'text': 'We met.', 'witnesses': [name]}]))
talk('Lydia', talk_fields={'talk_seq': 1, 'talk_id': 'T1', 'talk_parent': '', 'talk_open': 1, 'talk_time': 30.0})
bio_evolve.write(st3, name, ref, 'bio', lambda text, prompt: 'Lydia has just met Vega.', force=True)
talk('Lydia', talk_fields={'talk_seq': 2, 'talk_id': 'T2', 'talk_parent': 'T1', 'talk_open': 1, 'talk_time': 31.0})
bio_evolve.write(st3, name, ref, 'bio', lambda text, prompt: 'Lydia is in love with Vega.', force=True)
check('Now: the newest paragraph in the newer save', 'in love' in bio_evolve.now_text(st3, name, ref))
talk('Lydia', talk_fields={'talk_seq': 2, 'talk_id': '', 'talk_parent': 'T1', 'talk_open': 0, 'talk_time': 31.0})
check('Now: loading the save from before that talk brings the older paragraph', 'just met' in bio_evolve.now_text(st3, name, ref),
      bio_evolve.now_text(st3, name, ref))
talk('Lydia', talk_fields={'talk_seq': 3, 'talk_id': '', 'talk_parent': 'T2', 'talk_open': 0, 'talk_time': 31.0})
check('Now: the newer save again: the newest paragraph', 'in love' in bio_evolve.now_text(st3, name, ref))
talk('Lydia')
check('Now: without the talk counter, the paragraph as written', 'in love' in bio_evolve.now_text(st3, name, ref))
bio_evolve.edit(st3, name, ref, text='Lydia is my own text.')
talk('Lydia', talk_fields={'talk_seq': 1, 'talk_id': '', 'talk_parent': '', 'talk_open': 0, 'talk_time': 29.0})
check("Now: the player's own text belongs to every save", 'my own text' in bio_evolve.now_text(st3, name, ref))

# world log events follow the loaded save too
st5 = memory.MemoryStore(str(tmp / 'conv5'), 'Vega5')
talk('Faendal', talk_fields={'talk_seq': 2, 'talk_id': 'T2', 'talk_parent': 'T1', 'talk_open': 1, 'talk_time': 31.0})
from living_world import timeline
timeline.current(st5)  # the game's talk T2 follows T1
talk('Faendal', talk_fields={'talk_seq': 1, 'talk_id': 'T1', 'talk_parent': '', 'talk_open': 1, 'talk_time': 30.0})
timeline.current(st5)
talk('Faendal', talk_fields={'talk_seq': 2, 'talk_id': 'T2', 'talk_parent': 'T1', 'talk_open': 1, 'talk_time': 31.0})
W.log_event(st5, 'killing', 'Vega killed Sven at Riverwood, who was no threat.', 'Vega killed Sven at Riverwood, who was no threat.',
            day=31.0, place={'town': 'Riverwood', 'hold': 'Whiterun'}, present=[person('Alvor')], event_id='kill-t2',
            flags={'player_named': True, 'by_player': True})
faendal = {'name': 'Faendal', 'ref_id': PEOPLE['Faendal'][1], 'base_id': '01A69E', 'home_town': 'Riverwood', 'hold': 'Whiterun'}
from living_world import reputation as R
check('reload: the event counts in the save it happened in', 'no threat' in R.reputation_line(faendal, st5, PLAYER, 40, {'store': st5}))
talk('Faendal', talk_fields={'talk_seq': 2, 'talk_id': '', 'talk_parent': 'T1', 'talk_open': 0, 'talk_time': 31.0})
check('reload: a save from before it: no reputation from it', R.reputation_line(faendal, st5, PLAYER, 40, {'store': st5}) == '')
check('reload: ...and no news of it', N.catch_up(st5, W.identify(faendal, {'store': st5}), 40) == [])
talk('Faendal')

# --- 7. news talk detection, private events, the Now paragraph after a wipe ------------------------------------------------
N._talks.clear()
talk('Faendal')
check('news: the greeting (no talk id yet) starts a talk', N._new_talk(store, [Char('Faendal')]))
talk('Faendal', talk_fields={'talk_seq': 5, 'talk_id': 'T9', 'talk_parent': '', 'talk_open': 1, 'talk_time': 40.0})
check('news: the talk id appearing is still the same talk', not N._new_talk(store, [Char('Faendal')]))
check('news: the same talk id again is the same talk', not N._new_talk(store, [Char('Faendal')]))
talk('Faendal', talk_fields={'talk_seq': 6, 'talk_id': 'T10', 'talk_parent': 'T9', 'talk_open': 1, 'talk_time': 40.2})
check('news: a new talk id is a new talk', N._new_talk(store, [Char('Faendal')]))
W.log_event(store, 'intimate', 'Sigrid kissed Vega behind the mill.', 'Sigrid kissed Vega behind the mill.', day=36.0,
            place={'town': 'Riverwood', 'hold': 'Whiterun'}, involved=[person('Sigrid')], present=[person('Alvor')],
            event_id='kiss-1')
d = N.catch_up(store, W.identify({'name': 'Faendal', 'ref_id': PEOPLE['Faendal'][1], 'base_id': '01A69E', 'home_town': 'Riverwood'},
                                 {'store': store}), TODAY + 5, {'max': 20})
check('news: what happens between two people never spreads as a rumour', not any(x['id'] == 'kiss-1' for x in d), d)
d = N.catch_up(store, W.identify({'name': 'Alvor', 'ref_id': PEOPLE['Alvor'][1], 'base_id': '013BA0', 'home_town': 'Riverwood'},
                                 {'store': store}), TODAY + 5, {'max': 20})
check('news: someone who was there still knows it', any(x['id'] == 'kiss-1' and x['how'] == 'seen' for x in d), d)
lydia_st = memory.MemoryStore(str(tmp / 'conv4'), 'Vega4')
lydia_st.save('Lydia', PEOPLE['Lydia'][1], dict(memory.empty(), recent=[
    {'day': 36, 'hour': 9, 'text': 'Vega killed Sven at Riverwood, who was no threat.', 'witnesses': ['Lydia']}]))
bio_evolve.save(lydia_st, 'Lydia', PEOPLE['Lydia'][1], dict(bio_evolve.empty(), text='Lydia is shaken by what Vega did to Sven.',
                                                           auto=True, day=37, after=[37, 9]))
W.log_event(lydia_st, 'killing', 'Vega killed Sven at Riverwood, who was no threat.', 'Vega killed Sven at Riverwood, who was no threat.',
            day=35.0, place={'town': 'Riverwood'}, present=[person('Lydia')], event_id='kill-x', flags={'player_named': True})
N.forget_event(lydia_st, {'name': 'Lydia', 'ref_id': PEOPLE['Lydia'][1], 'base_id': '0A2C94'}, 'kill-x')
check('wipe: the Now paragraph written from it goes back', 'Sven' not in bio_evolve.now_text(lydia_st, 'Lydia', PEOPLE['Lydia'][1]),
      bio_evolve.now_text(lydia_st, 'Lydia', PEOPLE['Lydia'][1]))

# --- 8. optional parts absent: no store, no channel files ---------------------------------------------------------------
LW._last_store.update(store=None, people=[])
check('no store: no reputation, no strangeness', LW._reputation([]) == '' and LW._strangeness(None) == '')
empty_dir = tmp / 'empty_channel'
empty_dir.mkdir()
lw_state.DATA_DIR = str(empty_dir)
check('no channel files: ingest and talk start run quietly', W.ingest(store, PLAYER, []) == 0
      and N.talk_start(store, [Char('Faendal')], None) == 0)

print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
