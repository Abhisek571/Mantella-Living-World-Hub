"""Offline tests for absolute commands (server/living_world/command.py, command_ui.py and their hooks in
living_world/__init__.py). The game's file is shaped like PapyrusUtil writes it (MLW_Command.psc).
Run with a Python 3.11: test_command.py <repo server dir>"""
import json, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import command as C, command_ui, embed, lw_state, memory, settings

embed.use(None)  # keyword search
FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)

REF = living_world._ref
LYDIA, FAENDAL, CHILD = '000A2C94', '0001A69E', '00013BB5'
VALUES = dict(settings.DEFAULTS)
PEOPLE = [('Lydia', '0A2C94'), ('Faendal', '01A69E')]
SPEAKERS = [{'name': 'Lydia', 'ref_id': LYDIA, 'minor': 0}, {'name': 'Faendal', 'ref_id': FAENDAL, 'minor': 0}, {'name': 'Braith', 'ref_id': CHILD, 'minor': 1}]


def game_file(data_dir, entries):
    lists = {k: [] for k in ('key', 'text', 'refs', 'names', 'time', 'player')}
    for e in entries:
        for k in lists:
            lists[k].append(e[k])
    (Path(data_dir) / C.GAME_FILE).write_text(json.dumps({'stringList': lists}), encoding='utf-8')


def entry(key, text, refs=(LYDIA,), names=('Lydia',), time=41.5, player='Dragonborn'):
    return {'key': key, 'text': text, 'refs': ','.join(refs), 'names': '|'.join(names), 'time': f'{time:.6f}', 'player': player}


def lydia_memories(store):
    mem = dict(memory.empty(), recent=[
        {'day': 40, 'hour': 9, 'text': 'Player robbed the Bannered Mare and I helped carry the stolen gold.', 'witnesses': ['Lydia']},
        {'day': 40, 'hour': 14, 'text': 'We bought bread at the market in Whiterun.', 'witnesses': ['Lydia']},
        {'day': 41, 'hour': 8, 'text': 'Player sang a song by the campfire.', 'witnesses': ['Lydia']}])
    store.save('Lydia', '0A2C94', mem)


# --- reading the command's words --------------------------------------------------------------------------------
w = C.read_words('I cast a spell that makes you forget the robbery completely')
check('forget: the thing, without "completely"', w['forget'] == 'the robbery', w)
check('no hours, not aware', w['hours'] is None and not w['aware'], w)
w = C.read_words('You will follow me and obey without question')
check('no forget in an obey command', w['forget'] == '' and w['hours'] is None, w)
w = C.read_words('Forget everything about the Bannered Mare robbery for two days.')
check('forget with lead words and a duration cut off', w['forget'] == 'the Bannered Mare robbery' and w['hours'] == 48, w)
w = C.read_words('For 3 hours you no longer remember that I stole the amulet, and you will dance')
check('no longer remember + hours in digits', w['forget'] == 'I stole the amulet' and w['hours'] == 3, w)
w = C.read_words('You forget the duel, but you will know that I did this to you')
check('aware when the command says so', w['aware'] and w['forget'] == 'the duel', w)
check('"forget it" alone has nothing to look for', C.read_words('Forget it.')['forget'] == '')

check('model reply parsed', C.parse_check('Sure: {"forget": " the  robbery ", "hours": 2, "aware": true}\n\n')
      == {'forget': 'the robbery', 'hours': 2.0, 'aware': True})
check('model junk -> None', C.parse_check('no idea') is None and C.parse_check('[1, 2]') is None)
check('bad hours ignored', C.parse_check('{"forget": 3, "hours": "two", "aware": "yes"}') == {'forget': '', 'hours': None, 'aware': False})
read, how = C.read_command('Forget the duel', ['Lydia'], ask=lambda p, t: (_ for _ in ()).throw(RuntimeError('down')))
check('model failure falls back to words', how == 'words' and read['forget'] == 'the duel', (read, how))
asked = []
read, how = C.read_command('Forget the duel', ['Lydia'], ask=lambda p, t: asked.append((p, t)) or '{"forget": "the duel at dawn", "hours": null, "aware": false}')
check('model answer used, names in its prompt', how == 'model' and read['forget'] == 'the duel at dawn' and 'Lydia' in asked[0][0]
      and 'Command: Forget the duel' == asked[0][1], (read, asked))

# --- the game's file ---------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = tmp
    check('no file: no commands', C.read_queue() == [])
    (Path(tmp) / C.GAME_FILE).write_text('{"stringList": {"key": ["a"', encoding='utf-8')
    check('half-written file: no commands', C.read_queue() == [])
    game_file(tmp, [entry('41.5-1', '  Obey   me  ', refs=(LYDIA, FAENDAL), names=('Lydia', 'Faendal'))])
    q = C.read_queue()
    check('queue read', q == [{'key': '41.5-1', 'text': 'Obey me', 'refs': [LYDIA, FAENDAL], 'names': ['Lydia', 'Faendal'],
                              'time': 41.5, 'player': 'Dragonborn'}], q)
    (Path(tmp) / C.GAME_FILE).write_text(json.dumps({'stringList': {'key': ['k1', 'k2', ''], 'text': ['x'], 'refs': [None]}}), encoding='utf-8')
    check('ragged lists never raise; empty text skipped', [e['key'] for e in C.read_queue()] == ['k1'], C.read_queue())
    t = C.targets({'refs': [LYDIA, CHILD, 'zz', FAENDAL], 'names': ['Lydia', 'Braith', 'x', 'Faendal'], 'text': 'x'}, [('Lydia', '0A2C94')], SPEAKERS, REF)
    check('targets: Mantella name and ref, game ref converted, no child, junk ref dropped',
          t == [{'name': 'Lydia', 'ref_id': '0A2C94'}, {'name': 'Faendal', 'ref_id': '01A69E'}], t)

# --- poll, forget, prompt, duration, remove ----------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    lw_state.DATA_DIR = str(root / 'channel'); (root / 'channel').mkdir()
    store = memory.MemoryStore(str(root / 'conversations'), 'Dragonborn1')
    lydia_memories(store)
    C._state['now'] = None
    # the check answers with JSON; asked to rewrite a memory without the robbery, nothing would be left of it
    answer = lambda p, t: 'NONE' if p.startswith('Below is one memory') else '{"forget": "the robbery at the Bannered Mare", "hours": null, "aware": false}'
    game_file(lw_state.DATA_DIR, [entry('41.5-1', 'I cast a spell that makes you forget the robbery completely')])
    added = C.poll(store, PEOPLE, VALUES, answer, REF, 41, 'Dragonborn', SPEAKERS, background=False)
    data = C.load(store)
    rec = data['commands'][0] if data['commands'] else {}
    check('one command stored, read by the model, in force', len(added) == 1 and rec.get('status') == 'active'
          and rec.get('read_by') == 'model' and rec.get('forget') == 'the robbery at the Bannered Mare', rec)
    check('the robbery memory is hidden, the others kept', [h['text'][:20] for h in rec.get('hidden', [])] == ['Player robbed the Ba']
          and 'robbed' not in memory.render(store.load('Lydia', '0A2C94'), 1500)
          and 'bread' in memory.render(store.load('Lydia', '0A2C94'), 1500), rec.get('hidden'))
    marks = memory.list_hidden(store, 'Lydia', '0A2C94')
    check('the hidden mark names the command', marks and marks[0]['hidden']['by'] == C.BY and 'forget the robbery' in marks[0]['hidden']['note']
          and marks[0]['hidden']['day'] == 42, marks)
    check('until removed by default', rec['until'] == -1 and rec['hours'] == 0, rec)
    check('read again: nothing new', C.poll(store, PEOPLE, VALUES, answer, REF, 41, 'Dragonborn', SPEAKERS, background=False) == []
          and len(C.load(store)['commands']) == 1)

    system = C.system_text(store, SPEAKERS, 'Dragonborn', REF)
    check('system part: header, the command, the forget line', system.startswith('ABSOLUTE COMMANDS from Dragonborn')
          and 'forget the robbery completely' in system and 'no memory at all of the robbery at the Bannered Mare' in system
          and 'overrides everything else' in system and 'not aware that it was given' in system, system)
    check('nobody here with a command: nothing', C.system_text(store, [{'name': 'Faendal', 'ref_id': FAENDAL}], 'Dragonborn', REF) == '')
    first = C.newest_text(store, SPEAKERS, 'Dragonborn', REF)
    second = C.newest_text(store, SPEAKERS, 'Dragonborn', REF)
    check('newest message: given just now once, then a reminder', 'has just given Lydia an absolute command' in first
          and 'are in force for Lydia' in second and 'just given' not in second, (first, second))

    # a talk saved after the command: what it said about the robbery is hidden too
    mem = store.load('Lydia', '0A2C94')
    mem['recent'].append({'day': 42, 'hour': 10, 'text': 'Player cast a spell so I would forget the robbery at the Bannered Mare.', 'witnesses': ['Lydia']})
    store.save('Lydia', '0A2C94', mem)
    n = C.after_summary(store, [SimpleNamespace(name='Lydia', ref_id='0A2C94')], REF, VALUES)
    check('after a summary the new memory of it is hidden', n == 1 and 'spell' not in memory.render(store.load('Lydia', '0A2C94'), 1500), n)
    check('after a summary of someone else: nothing', C.after_summary(store, [SimpleNamespace(name='Faendal', ref_id='01A69E')], REF, VALUES) == 0)

    # a group command with a duration, read from its words (model check off), given to two NPCs and a child
    rec_id = rec['id']
    game_file(lw_state.DATA_DIR, [entry('41.5-1', 'I cast a spell that makes you forget the robbery completely'),
                                   entry('41.6-2', 'You will follow me and obey without question for two hours',
                                         refs=(LYDIA, FAENDAL, CHILD), names=('Lydia', 'Faendal', 'Braith'), time=41.6)])
    never = lambda p, t: (_ for _ in ()).throw(AssertionError('asked'))
    added = C.poll(store, PEOPLE, dict(VALUES, command_model_check=False), never, REF, 41, 'Dragonborn', SPEAKERS, background=False)
    timed = C.load(store)['commands'][-1]
    check('model check off: read from words, not asked', added and timed['read_by'] == 'words' and timed['hours'] == 2
          and abs(timed['until'] - (41.6 + 2 / 24)) < 1e-9, timed)
    check('a child is never given a command', [n['name'] for n in timed['npcs']] == ['Lydia', 'Faendal'], timed['npcs'])
    group = C.system_text(store, SPEAKERS, 'Dragonborn', REF)
    check('group prompt names both, never the child', "Lydia, Faendal must obey Dragonborn's command \"You will follow me" in group and 'Braith' not in group.split('child.')[1], group)
    check('a child alone in a talk gets nothing', C.system_text(store, [SPEAKERS[2]], 'Dragonborn', REF) == '')

    # it wears off: game time passes (Mantella's clock is GameDaysPassed + 1)
    C.note_time(41.6 + 1 / 24 + memory.MANTELLA_DAY)
    C.poll(store, PEOPLE, VALUES, answer, REF, 41, 'Dragonborn', SPEAKERS, background=False)
    check('not over yet after one hour', any(c['id'] == timed['id'] for c in C.load(store)['commands']))
    C.note_time(41.6 + 3 / 24 + memory.MANTELLA_DAY)
    C.poll(store, PEOPLE, VALUES, answer, REF, 41, 'Dragonborn', SPEAKERS, background=False)
    check('over after its hours: dropped, the other stays', [c['id'] for c in C.load(store)['commands']] == [rec_id], C.load(store)['commands'])

    # a forget command with a duration gives its memories back when it ends
    game_file(lw_state.DATA_DIR, [entry('41.8-3', 'Forget the bread for one hour', time=41.8)])
    C.poll(store, PEOPLE, dict(VALUES, command_model_check=False), None, REF, 41, 'Dragonborn', SPEAKERS, background=False)
    check('bread hidden for now', 'bread' not in memory.render(store.load('Lydia', '0A2C94'), 1500))
    C.note_time(41.8 + 2 / 24 + memory.MANTELLA_DAY)
    C.poll(store, PEOPLE, VALUES, None, REF, 41, 'Dragonborn', SPEAKERS, background=False)
    check('bread back when the hour is over', 'bread' in memory.render(store.load('Lydia', '0A2C94'), 1500))

    # the settings default lasts when the command says nothing
    game_file(lw_state.DATA_DIR, [entry('42.0-4', 'You are terrified of chickens', time=42.0)])
    C.poll(store, PEOPLE, dict(VALUES, command_hours=5, command_model_check=False), None, REF, 41, 'Dragonborn', SPEAKERS, background=False)
    check('hours from the setting', C.load(store)['commands'][-1]['hours'] == 5)

    # another character's command, and one from long ago, are never applied
    game_file(lw_state.DATA_DIR, [entry('42.0-5', 'Dance', player='Someone Else', time=42.0), entry('10.0-6', 'Sing', time=10.0)])
    check('other character / stale: skipped', C.poll(store, PEOPLE, VALUES, None, REF, 41, 'Dragonborn', SPEAKERS, background=False) == []
          and {'42.0-5', '10.0-6'} <= set(C.load(store)['seen']))

    # remove gives everything back; unhide_one gives one back and keeps the command
    hidden_before = len(memory.list_hidden(store, 'Lydia', '0A2C94'))
    data = C.load(store)
    first_rec = data['commands'][0]
    one = first_rec['hidden'][0]
    check('unhide one memory, command stays', C.unhide_one(store, first_rec['id'], one['id'])
          and len(C.load(store)['commands'][0]['hidden']) == len(first_rec['hidden']) - 1
          and len(memory.list_hidden(store, 'Lydia', '0A2C94')) == hidden_before - 1)
    back = C.remove(store, first_rec['id'])
    check('remove gives back the rest', back == len(first_rec['hidden']) - 1 and memory.list_hidden(store, 'Lydia', '0A2C94') == []
          and 'robbed' in memory.render(store.load('Lydia', '0A2C94'), 1500), back)
    check('remove twice: None', C.remove(store, first_rec['id']) is None)
    check('no memory was ever deleted', len(store.archive_for('Lydia', '0A2C94').rows(hidden=None)) >= 4)

    # a broken store file never raises
    Path(C.store_path(store)).write_text('{"commands": [1, {"id": 2}], "seen": "x"', encoding='utf-8')
    check('broken store: empty', C.load(store) == {'commands': [], 'seen': [], 'ended': []})

    # the UI section
    html_text = command_ui.commands_html([{'id': 'a', 'text': '<b>Obey</b>', 'given': 41.5, 'until': -1, 'hours': 0, 'forget': 'x',
                                           'npcs': [{'name': 'Lydia', 'ref_id': '1'}], 'hidden': [{'name': 'Lydia', 'id': 'm', 'text': 'old'}]}])
    check('listing escapes text, shows what was hidden', '&lt;b&gt;Obey' in html_text and '<s>Lydia: old</s>' in html_text and 'day 42' in html_text, html_text)

# --- forgetting one part of a memory: the rest is kept as a rewrite ---------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    lw_state.DATA_DIR = str(root / 'channel'); (root / 'channel').mkdir()
    store = memory.MemoryStore(str(root / 'conversations'), 'Dragonborn1')
    meeting = ('I met the Dragonborn at the Riverwood gate. They told me about the gold hidden under the bridge, and we '
               'shared a meal at the Sleeping Giant Inn.')
    store.save('Gerdur', '01A6A0', dict(memory.empty(), recent=[
        {'day': 39, 'hour': 7, 'text': 'The mill saw broke again.', 'importance': 0.3, 'witnesses': ['Gerdur']},
        {'day': 40, 'hour': 18, 'text': meeting, 'importance': 0.8, 'emotion': 'warm', 'witnesses': ['Gerdur']}]))
    C._state['now'] = None
    asked = []
    def model(p, t):
        asked.append((p, t))
        if p.startswith('Below is one memory'):
            return 'I met the Dragonborn at the Riverwood gate, and we shared a meal at the Sleeping Giant Inn.'
        return '{"forget": "the gold under the bridge", "hours": null, "aware": false}'
    gerdur = [{'name': 'Gerdur', 'ref_id': '0001A6A0', 'minor': 0}]
    game_file(lw_state.DATA_DIR, [entry('40.9-1', 'Forget that I told you about the gold under the bridge',
                                        refs=('0001A6A0',), names=('Gerdur',), time=40.9)])
    C.poll(store, [('Gerdur', '01A6A0')], dict(VALUES, command_forget_limit=1), model, REF, 40, 'Dragonborn', gerdur, background=False)
    rec = C.load(store)['commands'][0]
    shown = memory.render(store.load('Gerdur', '01A6A0'), 1500)
    rewrite = [p for p, t in asked if p.startswith('Below is one memory')]
    check('forget: one rewrite request with the thing and the memory', len(rewrite) == 1 and 'the gold under the bridge' in rewrite[0]
          and 'Gerdur' in rewrite[0] and any(t == meeting for p, t in asked if p.startswith('Below is one memory')), asked)
    check('forget: the meeting is still remembered, the gold is not', 'Riverwood gate' in shown and 'Sleeping Giant' in shown
          and 'gold' not in shown and 'mill saw' in shown, shown)
    new = next((e for e in store.load('Gerdur', '01A6A0')['recent'] if 'Riverwood' in e['text'] and not e.get('hidden')), {})
    check('forget: the rewrite keeps day, hour, importance and emotion', (new.get('day'), new.get('hour'), new.get('importance'), new.get('emotion'))
          == (40, 18, 0.8, 'warm'), new)
    hid = rec['hidden']
    check('forget: the original is hidden and names its rewrite', len(hid) == 1 and hid[0].get('added') and hid[0]['text'] == meeting
          and memory.list_hidden(store, 'Gerdur', '01A6A0')[0]['hidden'].get('replaced_by') == hid[0]['added'], hid)
    # a later talk: the rewrite (it shares words with the forgotten thing) is never picked and rewritten again
    asked.clear()
    C.after_summary(store, [SimpleNamespace(name='Gerdur', ref_id='01A6A0')], REF, VALUES, model)
    check('after a summary the rewrite stays as it is', 'Riverwood gate' in memory.render(store.load('Gerdur', '01A6A0'), 1500)
          and not any(t == new['text'] for p, t in asked), asked)
    # Unhide on the Memory page: the original back, the rewrite out of mind; no double memory
    memory.unhide(store, 'Gerdur', '01A6A0', hid[0]['id'])
    shown = memory.render(store.load('Gerdur', '01A6A0'), 1500)
    check('unhide on the Memory page: original back, rewrite hidden', 'gold hidden under the bridge' in shown
          and shown.count('Riverwood gate') == 1, shown)
    memory.hide_matching(store, 'Gerdur', '01A6A0', meeting, limit=1)  # hidden again by hand, for the next check
    memory.add_rewrite(store, 'Gerdur', '01A6A0', hid[0]['id'], new['text'])
    # removing the command does the same
    C.remove(store, rec['id'])
    shown = memory.render(store.load('Gerdur', '01A6A0'), 1500)
    check('remove the command: original back, rewrite hidden', 'gold hidden under the bridge' in shown and shown.count('Riverwood gate') == 1, shown)
    # no model: the whole memory is hidden, as before
    game_file(lw_state.DATA_DIR, [entry('41.0-2', 'Forget the gold under the bridge', refs=('0001A6A0',), names=('Gerdur',), time=41.0)])
    C.poll(store, [('Gerdur', '01A6A0')], dict(VALUES, command_forget_limit=1, command_model_check=False), None, REF, 41, 'Dragonborn', gerdur, background=False)
    rec = C.load(store)['commands'][-1]
    shown = memory.render(store.load('Gerdur', '01A6A0'), 1500)
    check('no model: the whole memory hidden, no rewrite', rec['hidden'] and not rec['hidden'][0].get('added') and 'Riverwood' not in shown, (rec['hidden'], shown))
    C.remove(store, rec['id'])
    # a failing model: the same fallback
    game_file(lw_state.DATA_DIR, [entry('41.1-3', 'Forget the gold under the bridge', refs=('0001A6A0',), names=('Gerdur',), time=41.1)])
    def broken(p, t):
        if p.startswith('Below is one memory'):
            raise RuntimeError('down')
        return '{"forget": "the gold under the bridge", "hours": null, "aware": false}'
    C.poll(store, [('Gerdur', '01A6A0')], dict(VALUES, command_forget_limit=1), broken, REF, 41, 'Dragonborn', gerdur, background=False)
    rec = C.load(store)['commands'][-1]
    check('model failure: the whole memory hidden', rec['hidden'] and not rec['hidden'][0].get('added')
          and 'Riverwood' not in memory.render(store.load('Gerdur', '01A6A0'), 1500), rec['hidden'])
    C.remove(store, rec['id'])
    check('everything back at the end', 'gold hidden under the bridge' in memory.render(store.load('Gerdur', '01A6A0'), 1500)
          and memory.render(store.load('Gerdur', '01A6A0'), 1500).count('Riverwood gate') == 1)

# --- a command overrides the action gates (never for a child) ---------------------------------------------------------
from living_world import action_filter as AF
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    lw_state.DATA_DIR = str(root / 'channel'); (root / 'channel').mkdir()
    store = memory.MemoryStore(str(root / 'conversations'), 'Dragonborn1')
    C._state['now'] = None
    GERDUR = {'name': 'Gerdur', 'ref_id': '0001A6A0', 'close': 0, 'intimate': 0, 'minor': 0}
    BRAITH = {'name': 'Braith', 'ref_id': CHILD, 'close': 0, 'intimate': 0, 'minor': 1}
    gates = {'SexWithPlayer': 'intimate', 'Redress': 'close', 'Wave': ''}
    tools = [{'function': {'name': n}} for n in ('SexWithPlayer', 'Redress', 'Wave')]
    names = lambda ts: [t['function']['name'] for t in ts]
    check('no command: gated actions hidden', names(AF.filter_actions(tools, C.unlocked(store, [GERDUR], REF), gates)) == ['Wave'])
    check('no store: speakers unchanged', C.unlocked(None, [GERDUR], REF) == [GERDUR])
    game_file(lw_state.DATA_DIR, [entry('41.0-1', 'Make love to me', refs=('0001A6A0', CHILD), names=('Gerdur', 'Braith'), time=41.0)])
    C.poll(store, [('Gerdur', '01A6A0')], dict(VALUES, command_hours=2, command_model_check=False), None, REF, 41, 'Dragonborn', [GERDUR, BRAITH], background=False)
    seen = C.unlocked(store, [GERDUR], REF, 41.0)
    check('command in force: close and intimate, the file values untouched', seen[0]['intimate'] == 1 and seen[0]['close'] == 1
          and GERDUR['intimate'] == 0, seen)
    check('command in force: gated actions offered', names(AF.filter_actions(tools, seen, gates)) == ['Redress', 'SexWithPlayer', 'Wave'])
    check('ungated actions unchanged', 'Wave' in names(AF.filter_actions(tools, seen, gates)))
    # a child, even one named in the game's list or sharing the ref, is never unlocked
    store_rec = C.load(store)
    store_rec['commands'][0]['npcs'].append({'name': 'Braith', 'ref_id': '013BB5'})  # forced in by hand
    C.save(store, store_rec)
    kid = C.unlocked(store, [BRAITH], REF, 41.0)[0]
    check('a child is never unlocked', kid['intimate'] == 0 and kid['close'] == 0, kid)
    both = C.unlocked(store, [GERDUR, BRAITH], REF, 41.0)
    check('a child in the talk still takes every adult action out', names(AF.filter_actions(tools, both, gates)) == ['Wave'])
    check('over by game time: locked again', C.unlocked(store, [GERDUR], REF, 41.0 + 3 / 24)[0]['intimate'] == 0)
    rec_id = C.load(store)['commands'][0]['id']
    C.remove(store, rec_id)
    check('removed: locked again', C.unlocked(store, [GERDUR], REF, 41.0)[0]['intimate'] == 0)
    # the game side's setting file
    C.write_game_settings(dict(VALUES, command_hours=6))
    check('Commands last written for the game', json.loads((root / 'channel' / C.GAME_SETTINGS).read_text(encoding='utf-8')) == {'int': {'command_hours': 6}})
    C.write_game_settings(dict(VALUES, command_hours=-3))
    check('a negative setting is written as 0', json.loads((root / 'channel' / C.GAME_SETTINGS).read_text(encoding='utf-8'))['int']['command_hours'] == 0)

# --- intimacy: facts and their own choice, never a verdict (intimacy.line) ----------------------------------------
from living_world import characters as CH, intimacy
gates = {'SexWithPlayer': 'intimate'}
NONE = {'npcs': {}}
line = intimacy.line([{'name': 'Gerdur', 'minor': 0, 'intimate': 0}], gates, 'Dragonborn', 'lovers_only', data=NONE)
check('lovers only, not offered: one game fact', line == '(Gerdur and Dragonborn are not lovers, so nothing intimate can start '
      'between them now.)', line)
GERDUR_FILE = {'name': 'Gerdur', 'minor': 0, 'intimate': 1, 'rank': 1, 'follower': 0, 'maras_status': 'dating'}
line = intimacy.line([GERDUR_FILE], gates, 'Dragonborn', 'npc_decides', lambda s: intimacy.known_text(4, 30, 41, 'Dragonborn'), data=NONE)
check('offered: their own choice, may refuse', "is Gerdur's own choice" in line and 'may refuse' in line, line)
check('offered: the facts that exist', 'friend' in line and 'dating Dragonborn' in line and '4 talks with Dragonborn remembered, the first 11 days ago' in line, line)
check('offered: the decision is asked for', 'decision accept or decline' in line, line)
check('offered: no verdict', 'does not agree' not in line and 'not intimate' not in line and 'is willing' not in line, line)
check('a known_for that fails is left out', 'remembered' not in intimacy.line([GERDUR_FILE], gates, 'Dragonborn', 'npc_decides', lambda s: 1 / 0, data=NONE))
line = intimacy.line([{'name': 'Lydia', 'minor': 0, 'intimate': 1, 'allow_intimacy': 1}], gates, 'Dragonborn', 'npc_decides', data=NONE)
check('always willing (hotkey): told they are willing', line.startswith('(Lydia is willing to be intimate with Dragonborn.'), line)
never = {'npcs': {CH.key('Mjoll', ''): CH.clean({'name': 'Mjoll', 'flags': {'never_intimate': True}})}}
line = intimacy.line([{'name': 'Mjoll', 'minor': 0, 'intimate': 0}], gates, 'Dragonborn', 'npc_decides', data=never)
check('Intimacy: never: nothing starts, whatever is said', line == '(Nothing intimate starts between Mjoll and Dragonborn: Mjoll will '
      'not, whatever is said.)', line)
line = intimacy.line([{'name': 'Gerdur', 'minor': 0, 'intimate': 1, 'commanded': 1, 'allow_intimacy': 1}], gates, 'Dragonborn', 'npc_decides', data=NONE)
check('commanded: the command is a fact, not a verdict', 'absolute command from Dragonborn is in force' in line and 'is willing' not in line, line)
check('a child in the talk: nothing (the child rules cover it)',
      intimacy.line([{'name': 'Gerdur', 'minor': 0, 'intimate': 1}, {'name': 'Braith', 'minor': 1}], gates, 'Dragonborn', 'npc_decides', data=NONE) == '')
check('no scene action (OStim Expansion missing): nothing', intimacy.line([{'name': 'Gerdur', 'minor': 0}], {}, 'Dragonborn', 'npc_decides', data=NONE) == '')
group = intimacy.line([{'name': 'Lydia', 'minor': 0, 'intimate': 1}, {'name': 'Gerdur', 'minor': 0, 'intimate': 0}], gates, 'Dragonborn', 'lovers_only', data=NONE)
check('group: a line for each', "Lydia's own choice" in group and 'Gerdur and Dragonborn are not lovers' in group, group)
# a speaker the game has not confirmed as an adult (first talk: the greeting goes out before npc/<base>.json exists;
# a broken file; a file without the minor key) gets no intimacy line, and nobody does while one is in the talk
for label, who in (('no file', {'base_id': '01A2B3'}), ('named, no minor key', {'name': 'Braith', 'intimate': 1}),
                   ('broken minor', {'name': 'Braith', 'intimate': 1, 'minor': 'x'})):
    check(f'unknown age ({label}): no intimacy line', intimacy.line([who], gates, 'Dragonborn', 'npc_decides', data=NONE) == '')
check('unknown age in a group: no intimacy line for anyone', intimacy.line(
    [GERDUR_FILE, {'name': 'Braith', 'intimate': 1}], gates, 'Dragonborn', 'npc_decides', data=NONE) == '')
check('known: none remembered', intimacy.known_text(0, None, 41, 'Dragonborn') == 'no talks with Dragonborn remembered before this one')
check('known: one today', intimacy.known_text(1, 41, 41, 'Dragonborn') == '1 talk with Dragonborn remembered, the first today')

# --- the hooks: system prompt part and newest-message line --------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    lw_state.DATA_DIR = str(root / 'channel'); (root / 'channel' / 'npc').mkdir(parents=True)
    (root / 'channel' / 'conversation.json').write_text(json.dumps({'string': {'player': 'Dragonborn'}, 'int': {'day': 41},
                                                                    'stringList': {'speakers': ['0A2C94']}}), encoding='utf-8')
    (root / 'channel' / 'npc' / '0A2C94.json').write_text(json.dumps({'string': {'name': 'Lydia', 'ref_id': LYDIA},
                                                                      'int': {'minor': 0}}), encoding='utf-8')
    store = memory.MemoryStore(str(root / 'conversations'), 'Dragonborn1')
    real = dict(living_world._last_store)
    try:
        living_world._last_store.update(store=store, people=PEOPLE, summaries=None)
        game_file(lw_state.DATA_DIR, [entry('41.5-1', 'You will follow me and obey without question')])
        extra = living_world._extra_text({'messages': []})
        check('newest message carries the new command', 'has just given Lydia an absolute command' in extra, extra)
        parts = living_world._system_parts({'mantella': '# Overview\nLydia is a housecarl.\n\n# Background\nShe is loyal.\n\nRespond as Lydia.'}, {})
        order = parts.get('__order__', [])
        check('system part added before the reply instruction', 'obey without question' in parts.get('command', '')
              and 'command' in order and order.index('command') == order.index('respond') - 1, order)
        # the hooks: Lydia (not intimate in her file) gets the scene action while the command is in force
        tools = [{'function': {'name': 'SexWithPlayer', 'description': 'x'}}, {'function': {'name': 'Wave', 'description': 'y'}}]
        real_gates, real_installed, real_chars = living_world._gates, living_world._installed, CH.PATH
        living_world._gates = lambda: {'SexWithPlayer': 'intimate'}
        living_world._installed = lambda: {'Integration Hub', 'OStim Expansion'}
        CH.PATH = str(root / 'characters.json')  # nobody has an Intimacy choice
        CH.write_intimacy_mode('lovers_only')
        try:
            offered = [t['function']['name'] for t in living_world._filter_tools(tools, {})]
            check('hook: a commanded NPC is offered the gated action', offered == ['SexWithPlayer', 'Wave'], offered)
            extra = living_world._extra_text({'messages': []})
            check('hook: commanded: the command is one of the facts', 'absolute command from Dragonborn is in force' in extra, extra)
            C.remove(store, C.load(store)['commands'][0]['id'])
            offered = [t['function']['name'] for t in living_world._filter_tools(tools, {})]
            check('hook: lovers only, command removed: the gated action is gone', offered == ['Wave'], offered)
            extra = living_world._extra_text({'messages': []})
            check('hook: lovers only: the not-lovers line', '(Lydia and Dragonborn are not lovers' in extra, extra)
            CH.write_intimacy_mode('npc_decides')
            offered = [t['function']['name'] for t in living_world._filter_tools(tools, {})]
            check('hook: NPC decides: an adult is offered the scene', offered == ['SexWithPlayer', 'Wave'], offered)
            extra = living_world._extra_text({'messages': []})
            check("hook: NPC decides: their own choice, with how long they have known the player", "Lydia's own choice" in extra
                  and 'talk' in extra and 'not lovers' not in extra, extra)
            # the greeting request of a first talk: Direct AI Connect names the speakers (speaking_ids) before the game
            # has written npc/<base>.json for the new one; until it has, nothing intimate is offered or said to anyone
            import types
            fake = types.ModuleType('src.extensions')
            fake._registry = types.SimpleNamespace(speaking_ids=['0A2C94', '013BB5'])
            real_ext = sys.modules.get('src.extensions')
            sys.modules['src.extensions'] = fake
            try:
                for label, content in (('no file yet', None), ('broken file', '{broken'),
                                       ('file without minor', json.dumps({'string': {'name': 'Braith', 'ref_id': CHILD}}))):
                    child_file = root / 'channel' / 'npc' / '013BB5.json'
                    if content is None:
                        child_file.unlink(missing_ok=True)
                    else:
                        child_file.write_text(content, encoding='utf-8')
                    offered = [t['function']['name'] for t in living_world._filter_tools(tools, {})]
                    check(f'hook, greeting with an unknown speaker ({label}): no scene offered', offered == ['Wave'], offered)
                    extra = living_world._extra_text({'messages': []})
                    check(f'hook, greeting with an unknown speaker ({label}): no intimacy line', 'own choice' not in extra
                          and 'willing' not in extra, extra)
                (root / 'channel' / 'npc' / '013BB5.json').write_text(json.dumps(
                    {'string': {'name': 'Braith', 'ref_id': CHILD}, 'int': {'minor': 1}}), encoding='utf-8')
                offered = [t['function']['name'] for t in living_world._filter_tools(tools, {})]
                check('hook: the game then says child: still nothing', offered == ['Wave'], offered)
                (root / 'channel' / 'npc' / '013BB5.json').write_text(json.dumps(
                    {'string': {'name': 'Hroki', 'ref_id': CHILD}, 'int': {'minor': 0}}), encoding='utf-8')
                offered = [t['function']['name'] for t in living_world._filter_tools(tools, {})]
                check('hook: the game then says adult: the same talk keeps the actions of its greeting (one cached list)',
                      offered == ['Wave'], offered)
                living_world.npc_block.talk_over()
                offered = [t['function']['name'] for t in living_world._filter_tools(tools, {})]
                check('...the next talk offers it', offered == ['SexWithPlayer', 'Wave'], offered)
            finally:
                (root / 'channel' / 'npc' / '013BB5.json').unlink(missing_ok=True)
                if real_ext is None:
                    sys.modules.pop('src.extensions', None)
                else:
                    sys.modules['src.extensions'] = real_ext
            check('hook: Commands last written for the game', (root / 'channel' / C.GAME_SETTINGS).is_file())
            living_world._installed = lambda: {'Integration Hub'}
            check('hook: no line without OStim Expansion', 'own choice' not in living_world._extra_text({'messages': []}))
        finally:
            living_world._gates, living_world._installed, CH.PATH = real_gates, real_installed, real_chars
        living_world._last_store.update(store=None)
        check('no store yet: nothing, no error', living_world._commands(newest=True) == '')
    finally:
        living_world._last_store.clear()
        living_world._last_store.update(real)

print(f'\n{len(FAILS)} failed' if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
