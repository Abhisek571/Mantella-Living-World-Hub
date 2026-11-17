"""Offline regression tests for fixed Hub bugs: locked memory files, Memory tab saves, the action filter failing
closed, rule file encodings, radiant talks, deep JSON replies, dates, trims, shared files and retried summaries.
Run with a Python 3.11: test_regressions.py <repo server dir>"""
import json, logging, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import action_filter, memory, memory_ui, prompt_rules, settings
memory.SUMMARY_RETRY_SECONDS = 0  # retried summary calls without the real wait

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


class Char:
    def __init__(self, name, ref_id, bio='A person.'):
        self.name, self.ref_id, self.bio = name, ref_id, bio

class Thread:
    def __init__(self, lines):
        self.lines = lines
    def get_talk_only(self, **_):
        return list(self.lines)
    def transform_to_dict_representation(self, messages):
        return '\n'.join(messages)
    def __len__(self):
        return len(self.lines)

class Params:
    def __init__(self, lines, chars):
        self.messages, self.characters = Thread(lines), chars

class People:
    def get_player_name(self):
        return 'Player'

class Summaries:
    """Replies in turn; an Exception in the list is raised for that call."""
    def __init__(self, threads, replies):
        self.threads, self.replies, self.calls = threads, list(replies), []
    def get_threads_for_summarization(self, messages, npcs):
        return self.threads
    def group_shared_threads(self, threads):
        return [[name] for name in threads]
    def summarize_conversation(self, text, prompt):
        self.calls.append(text)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


class Warnings(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            self.lines.append(record.getMessage())
warned = Warnings()
logging.getLogger('Mantella').addHandler(warned)

mjoll = Char('Mjoll', 'FE1DD821')
long_talk = [f'line {i}' for i in range(8)]
good = json.dumps({'memory': 'We fought bandits.', 'feelings': {'Mjoll': 'trusting'}})
def hook(summaries, **extra):
    return dict({'messages': None, 'npcs_to_summarize': [mjoll], 'npcs_in_conversation': People(), 'world_id': 'Player1',
                 'is_reload': False, 'pending_shares': None, 'end_timestamp': 4.5, 'is_radiant': False, 'summaries': summaries}, **extra)

# HUB-1: a memory file locked past the retry is not read as empty and then overwritten with one entry
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'Player1')
    old = dict(memory.empty(), recent=[{'day': d, 'hour': 9, 'text': f'talk {d}', 'witnesses': ['Mjoll']} for d in range(12)], feeling='loyal')
    store.save('Mjoll', 'FE1DD821', old)
    path = store._path('Mjoll', 'FE1DD821')
    before = path.read_bytes()
    real_read = memory._read_text
    def locked(p):
        raise PermissionError(13, 'locked by another process')
    memory._read_text = locked
    try:
        try:
            store.load('Mjoll', 'FE1DD821')
            raised = False
        except OSError:
            raised = True
        check('locked file: load raises instead of starting empty', raised)
        summaries = Summaries({'Mjoll': Params(long_talk, [mjoll])}, [good])
        try:
            memory.summarize(hook(summaries), store)
            ok = True
        except OSError as e:
            ok = e
        check('locked file: summarize goes on without raising', ok is True, ok)
        check('locked file: nothing saved over it', path.read_bytes() == before)
        check('locked file: no aside copy made', not list(path.parent.glob('*.unreadable-*')))
        dialogue = 'Player: Did you find it?;\n Mjoll: ' + 'I never thought I would see it again. ' * 20 + 'Player: Here.;\n Mjoll: Thanks.'
        out = memory.compact_dialogue([dialogue], {'player': 'Player', 'characters': [mjoll], 'game_days': 3.5,
                                                   'summaries': Summaries({}, [good])}, store)
        check('locked file: earlier dialogue kept word for word, nothing saved', out == [dialogue] and path.read_bytes() == before, out)
        text = memory.memory_text('stock text', {'characters': [mjoll]}, store)
        check('locked file: memory_text leaves that NPC out', text == 'stock text', text)
    finally:
        memory._read_text = real_read
    check('unlocked again: the old memory is all there', len(store.load('Mjoll', 'FE1DD821')['recent']) == 12)
    path.write_text('{broken', encoding='utf-8')
    check('broken content still starts empty', store.load('Mjoll', 'FE1DD821')['recent'] == [])

# HUB-18: group talks are written through a temp file, and nothing of it is left behind
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'Player1')
    key = store.save_shared({'day': 1, 'hour': 2, 'text': 'We drank.', 'witnesses': ['A', 'B']})
    shared = Path(store.root) / 'shared'
    check('shared entry readable', store.shared_text(key) == 'We drank.')
    check('no temp file left', [f.name for f in shared.iterdir()] == [key + '.json'], list(shared.iterdir()))

# HUB-6: radiant talks are not talks with the player
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'Player1')
    summaries = Summaries({'Mjoll': Params(long_talk, [mjoll])}, [good])
    memory.summarize(hook(summaries, end_timestamp=2.5), store)
    summaries = Summaries({'Mjoll': Params(long_talk, [mjoll])}, [json.dumps({'memory': 'Talked with Aerin.'})])
    memory.summarize(hook(summaries, end_timestamp=9.5, is_radiant=True), store)
    got = store.load('Mjoll', 'FE1DD821')
    check('radiant entry marked', got['recent'][-1].get('radiant') is True and not got['recent'][0].get('radiant'), got['recent'])
    check('radiant talk not counted', got['talks'] == 1, got['talks'])
    line = memory.facts_text(got, [], 10, 'Player', 'Mjoll')
    check('"last talked" uses the player talk', 'You last talked with Player 8 days ago.' in line, line)
    many = dict(memory.empty(), recent=[{'day': 1, 'hour': 1, 'text': 'x', 'radiant': True}] * 25)
    check('radiant entries do not unlock the long-known bonus', memory.long_known_bonus(many, 1500) == 0)

# HUB-11: a trim mid-talk saves the memory but is not a new talk
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'Player1')
    summaries = Summaries({'Mjoll': Params(long_talk, [mjoll])}, [good])
    memory.summarize(hook(summaries, is_reload=True), store)
    got = store.load('Mjoll', 'FE1DD821')
    check('reload save kept, not counted as a talk', len(got['recent']) == 1 and got['talks'] == 0, got)
    memory.summarize(hook(summaries), store)
    check('the talk end counts once', store.load('Mjoll', 'FE1DD821')['talks'] == 1)

# HUB-7 / NEW-2: very deep JSON in a reply is handled like any odd reply
deep = '[' * 100000
check('deep reply: no summary data', memory._summary_data(deep) == {})
try:
    parsed = memory.parse_summary(deep, ['Mjoll'])
except RecursionError as e:
    parsed = e
check('deep reply: parse_summary does not raise', isinstance(parsed, tuple), type(parsed))
rows, feeling, problem = memory_ui.notes_to_rows(lambda *a: '{' + deep + '}', 'Mjoll', 'Player', 'we fought')
check('deep reply: Turn into memories says the model answered oddly', rows == [] and problem, problem)

# HUB-8: the hour is truncated like Mantella's own dates
check('23:46 of day 5 stays day 5, 11 at night', memory.day_hour(5.99) == (5, 23) and memory.header(*memory.day_hour(5.99)) == '[Day 5, 11 at night]',
      memory.day_hour(5.99))
check('midnight', memory.day_hour(6.0) == (6, 0))

# NEW-1: an empty or failed summary call is tried again before the talk is given up
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'Player1')
    summaries = Summaries({'Mjoll': Params(long_talk, [mjoll])}, ['', RuntimeError('overloaded'), good])
    memory.summarize(hook(summaries), store)
    got = store.load('Mjoll', 'FE1DD821')
    check('third try saves the talk', len(summaries.calls) == 3 and got['recent'] and got['recent'][0]['text'] == 'We fought bandits.', got['recent'])
    summaries = Summaries({'Mjoll': Params(long_talk, [mjoll])}, [''])
    memory.summarize(hook(summaries), store)
    check('always empty: tried 3 times, nothing new saved', len(summaries.calls) == memory.SUMMARY_TRIES and len(store.load('Mjoll', 'FE1DD821')['recent']) == 1)

# HUB-4: odd field values never open a gate, and a filter error offers only ungated actions
check('string close opens the gate', action_filter.may_use({'close': '1'}, 'close'))
check('list close stays shut', not action_filter.may_use({'close': [1]}, 'close'))
check('string field=N compares as a number', action_filter.may_use({'maras': '1'}, 'maras=1') and not action_filter.may_use({'maras': 'x'}, 'maras=1'))
tools = [{'function': {'name': 'Kiss'}}, {'function': {'name': 'Wave'}}]
gates = {'Kiss': 'close'}
real_load, real_gates = settings.load, action_filter.load_gates
def broken_settings():
    raise TypeError("'>' not supported between instances of 'str' and 'int'")
settings.load, action_filter.load_gates = broken_settings, lambda *a: gates
try:
    out = living_world._filter_tools(tools, {})
finally:
    settings.load, action_filter.load_gates = real_load, real_gates
check('a raising filter fails closed', [t['function']['name'] for t in out] == ['Wave'], out)
def raising_gate(npc):
    raise ValueError('bad gate')
action_filter.GATE_OPEN['broken'] = raising_gate
settings.load, action_filter.load_gates = (lambda: dict(real_load(), action_filter=True, short_actions=False)), (lambda *a: {'Kiss': 'broken'})
real_conv = living_world.lw_state.load_conversation
living_world.lw_state.load_conversation = lambda: [{'name': 'Mjoll', 'close': 1}]
try:
    out = living_world._filter_tools(tools, {'keyword_actions': True})
finally:
    settings.load, action_filter.load_gates = real_load, real_gates
    living_world.lw_state.load_conversation = real_conv
    del action_filter.GATE_OPEN['broken']
check('a raising gate fails closed', [t['function']['name'] for t in out] == ['Wave'], out)

# HUB-5 / HUB-13: a rule file saved as ANSI or with a BOM still loads; a long one warns once
with tempfile.TemporaryDirectory() as tmp:
    Path(tmp, '10_ansi.txt').write_bytes('Speak of the café “quietly”.'.encode('cp1252'))
    Path(tmp, '20_bom.txt').write_bytes('﻿Keep it short.'.encode('utf-8'))
    Path(tmp, '30_long.txt').write_text('x' * 700, encoding='utf-8')
    rules = prompt_rules.load_rules(tmp)
    check('ANSI rule file kept', 'Speak of the caf' in rules and 'quietly' in rules, rules[:80])
    check('BOM dropped', '﻿' not in rules and 'Keep it short.' in rules)
    check('token counts build', set(prompt_rules.rule_token_counts(tmp)) == {'10_ansi.txt', '20_bom.txt', '30_long.txt'})
    warned.lines.clear()
    for _ in range(3):
        prompt_rules.load_rules(tmp)
    check('long rule file warned at most once', sum('30_long.txt' in w for w in warned.lines) <= 1, warned.lines)

# HUB-2: editing a memory on the NPCs page keeps memories the game wrote while the page was open
from living_world import npc_page_ui
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'Player1')
    store.save('Ann', '0A0B0C', dict(memory.empty(), recent=[{'day': 1, 'hour': 9, 'text': 'first', 'witnesses': ['Ann']}]))

    class Page:  # the NPC the page has open
        name, ref, store_ = 'Ann', '0A0B0C', None
    page = Page()
    page.store = store
    label = npc_page_ui.memory_label(npc_page_ui.all_memories(store, 'Ann', '0A0B0C')[0])
    later = store.load('Ann', '0A0B0C')
    later['recent'].append({'day': 2, 'hour': 10, 'text': 'second, from the game', 'witnesses': ['Ann']})
    store.save('Ann', '0A0B0C', later)
    said = npc_page_ui.edit_memory(page, label, 'first, edited')
    texts = [e['text'] for e in store.load('Ann', '0A0B0C')['recent']]
    check('edit saved and the game memory kept', texts == ['first, edited', 'second, from the game'], (texts, said))
    check('editing again with the old pick changes nothing', 'pick it again' in npc_page_ui.edit_memory(page, label, 'other')
          and [e['text'] for e in store.load('Ann', '0A0B0C')['recent']] == texts)
    old_ids = {m['id'] for m in npc_page_ui.all_memories(store, 'Ann', '0A0B0C')}
    check('the old text left the archive', npc_page_ui._choice(label) not in old_ids, old_ids)

# --- custom events, absolute commands, bio notes, memory locks, recall, fights, Memory page, model load ------------------
import threading, time
from types import SimpleNamespace
from living_world import archive, battle, bio_evolve, command as C, embed, events as E, lw_state
embed.use(None)
REF = living_world._ref
LYDIA_REF = '000A2C94'
PEOPLE = [('Lydia', '0A2C94')]
SPEAKERS = [{'name': 'Lydia', 'ref_id': LYDIA_REF, 'minor': 0}]
VALUES = dict(settings.DEFAULTS)
lydia = Char('Lydia', '0A2C94')


def fresh(tmp, world='W1'):
    root = Path(tmp)
    (root / 'channel').mkdir(exist_ok=True)
    lw_state.DATA_DIR = str(root / 'channel')
    C._state.update(now=None, root=None)
    E.end_talk()
    return memory.MemoryStore(str(root / 'conv'), world)


def queue_file(entries):
    lists = {k: [] for k in ('key', 'text', 'refs', 'names', 'time', 'player')}
    for key, text, at, player in entries:
        for k, v in zip(('key', 'text', 'refs', 'names', 'time', 'player'), (key, text, LYDIA_REF, 'Lydia', f'{at:.6f}', player)):
            lists[k].append(v)
    (Path(lw_state.DATA_DIR) / C.GAME_FILE).write_text(json.dumps({'stringList': lists}), encoding='utf-8')


def wait_threads(prefix):
    for t in threading.enumerate():
        if t.name.startswith(prefix):
            t.join(10)


class AssistantMessage:
    def __init__(self, text):
        self.text = text


class UserMessage:
    def __init__(self, text, events=()):
        self.text = text
        self.__ingame_events = list(events)


class MsgThread:
    def __init__(self, messages):
        self.messages = messages
    def __len__(self):
        return len(self.messages)
    def __getitem__(self, i):
        return self.messages[i]


# 1: a taken-back event: the NPC's answer to it leaves the request and the talk that is summarized
with tempfile.TemporaryDirectory() as tmp:
    store = fresh(tmp)
    ctx = {'characters': [lydia], 'game_days': 41.5, 'is_first': False}
    sent = E.process(['Lydia trips into the river\n'], ctx, store)
    E.process(['undo\n'], ctx, store)
    msgs = [{'role': 'system', 'content': 'sys'}, {'role': 'user', 'content': f'*{sent[0].strip()}*'},
            {'role': 'assistant', 'content': 'Ha! Soaked through.'}, {'role': 'tool', 'content': 'done'},
            {'role': 'user', 'content': 'Are you all right?'}]
    E.fix_request(msgs, store)
    check('undo: the reply to the event and the emptied message leave the request',
          [m['content'] for m in msgs] == ['sys', 'Are you all right?'], msgs)
    thread = MsgThread([UserMessage('', [sent[0]]), AssistantMessage('Ha! Soaked through.'), UserMessage('Are you all right?'),
                        AssistantMessage('I am fine.')])
    E.fix_thread(thread, store)
    check('undo: the talk summarized holds neither the event nor the reply to it',
          [m.text for m in thread.messages] == ['Are you all right?', 'I am fine.'], [m.text for m in thread.messages])

# 2: a forget command hides only from the talk just saved, never more older memories after every talk
with tempfile.TemporaryDirectory() as tmp:
    store = fresh(tmp)
    recent = [{'day': 40 + i, 'hour': 9, 'text': f'The player and I talked about the robbery at the Bannered Mare, part {i}.',
               'witnesses': ['Lydia']} for i in range(8)]
    store.save('Lydia', '0A2C94', dict(memory.empty(), recent=recent))
    queue_file([('48.0-1', 'Forget the robbery at the Bannered Mare', 48.0, 'Dragonborn')])
    vals = dict(VALUES, command_model_check=False, command_forget_limit=2, command_hours=0)
    C.poll(store, PEOPLE, vals, None, REF, 48, 'Dragonborn', SPEAKERS, background=False)
    counts = [len(C.load(store)['commands'][0]['hidden'])]
    for talk in range(2):
        mem = store.load('Lydia', '0A2C94')
        mem['recent'].append({'day': 49 + talk, 'hour': 10, 'text': f'We went fishing, day {talk}.', 'witnesses': ['Lydia']})
        store.save('Lydia', '0A2C94', mem)
        C.after_summary(store, [SimpleNamespace(name='Lydia', ref_id='0A2C94')], REF, vals, talk_time=(49 + talk, 10))
        counts.append(len(C.load(store)['commands'][0]['hidden']))
    mem = store.load('Lydia', '0A2C94')
    mem['recent'].append({'day': 52, 'hour': 10, 'text': 'Someone brought up the robbery at the Bannered Mare again.', 'witnesses': ['Lydia']})
    store.save('Lydia', '0A2C94', mem)
    C.after_summary(store, [SimpleNamespace(name='Lydia', ref_id='0A2C94')], REF, vals, talk_time=(52, 10))
    counts.append(len(C.load(store)['commands'][0]['hidden']))
    check('forget: later talks hide only what they themselves said about it', counts == [2, 2, 2, 3], counts)

# 3: game time is Mantella's clock or today, never a queued command's time
with tempfile.TemporaryDirectory() as tmp:
    store = fresh(tmp)
    queue_file([('100.0-1', 'Dance for me', 100.0, 'Other'), ('30.2-2', 'Dance for me for two hours', 30.2, 'Dragonborn'),
                ('95.0-3', 'Sing for me', 95.0, 'Dragonborn')])
    C.poll(store, PEOPLE, VALUES, None, REF, 30, 'Dragonborn', SPEAKERS, background=False)
    C.poll(store, PEOPLE, VALUES, None, REF, 30, 'Dragonborn', SPEAKERS, background=False)
    check('a later queued command (another save) does not end timed ones at once, and is never applied',
          [c['text'] for c in C.load(store)['commands']] == ['Dance for me for two hours'], C.load(store)['commands'])
    C.note_time(80.0 + memory.MANTELLA_DAY)  # another save's clock, noted before this one was loaded
    check("a clock that does not fit today's day is not used", C.current_time(30) == 30.0, C.current_time(30))
    C.note_time(30.1 + memory.MANTELLA_DAY)
    check('a clock that fits today is used', abs(C.current_time(30) - 30.1) < 1e-9)

# 4: the bio note and absolute commands
with tempfile.TemporaryDirectory() as tmp:
    store = fresh(tmp)
    queue_file([('41.5-1', 'Make love to me', 41.5, 'Dragonborn')])
    C.poll(store, PEOPLE, dict(VALUES, command_model_check=False), None, REF, 41, 'Dragonborn', SPEAKERS, background=False)
    record = C.load(store)['commands'][0]
    check('a command records the bio note it found', record.get('bio_before') and record['bio_before'][0]['name'] == 'Lydia')
    check('active_for names the command in force', C.active_for(store, lydia, REF) == record['id'])
    rec = [{'day': 42, 'hour': 13 + i, 'text': f'I could not keep my hands off the player ({i}).', 'witnesses': ['Lydia'],
            'importance': 0.9, 'command': record['id']} for i in range(3)]
    store.save('Lydia', '0A2C94', dict(memory.empty(), recent=rec, talks=9))
    check('memories saved under a command reach the Now writer', len(bio_evolve.new_memories(store.load('Lydia', '0A2C94'), bio_evolve.empty(), store)) == 3)
    asked = []
    ask = lambda text, prompt: asked.append(text) or 'Lydia now feels a strong pull toward the player.'
    bio_evolve.write(store, 'Lydia', '0A2C94', 'A housecarl.', ask, force=True, context={'labels': C.memory_labels(store, 'Dragonborn')})
    check('Now is written while a command is in force, its memories labelled as such',
          len(asked) == 1 and '(while under an absolute command from Dragonborn)' in asked[0], asked)
    bio_evolve.save(store, 'Lydia', '0A2C94', bio_evolve.empty())
    asked.clear()
    mem = store.load('Lydia', '0A2C94')
    for e in mem['recent']:
        e.pop('command')
    store.save('Lydia', '0A2C94', mem)
    bio_evolve.write(store, 'Lydia', '0A2C94', 'A housecarl.', ask, force=True)
    C.remove(store, record['id'])
    check('the note written while a command was in force goes back when it is removed',
          bio_evolve.load(store, 'Lydia', '0A2C94')['text'] == '', bio_evolve.load(store, 'Lydia', '0A2C94'))
    # a memory folded into the note is forgotten: the note goes back to before it
    state = dict(bio_evolve.empty(), text='Lydia trusts the player.', auto=True, day=50, after=[50, 9], version=3,
                 history=[{'text': 'Lydia is wary.', 'day': 30}])
    bio_evolve.save(store, 'Lydia', '0A2C94', state)
    bio_evolve.roll_back(store, 'Lydia', '0A2C94', 45)
    after = bio_evolve.load(store, 'Lydia', '0A2C94')
    check('a note built from a forgotten memory goes back to an older text', after['text'] == 'Lydia is wary.' and after['after'] == [30, -1], after)
    bio_evolve.edit(store, 'Lydia', '0A2C94', text='My own words.')
    check("the player's own note is never rolled back", not bio_evolve.roll_back(store, 'Lydia', '0A2C94', 0)
          and bio_evolve.load(store, 'Lydia', '0A2C94')['text'] == 'My own words.')

# 5: one lock per memory file: a slow hide on a background thread never saves over a talk saved meanwhile
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'W1')
    check('every store on a folder shares the lock of a memory file', store.lock('Lydia', '1') is memory.MemoryStore(tmp, 'W1').lock('Lydia', '1')
          and store.lock('Lydia', '1') is not store.lock('Lydia', '2'))
    store.save('Lydia', '1', dict(memory.empty(), recent=[{'day': 5, 'hour': 9, 'text': 'Lydia saw the player steal a sweetroll from Belethor.', 'witnesses': ['Lydia']}]))
    real = archive.rank
    archive.rank = lambda *a, **k: (time.sleep(0.4), real(*a, **k))[1]
    try:
        worker = threading.Thread(target=lambda: memory.hide_matching(store, 'Lydia', '1', 'steal sweetroll Belethor', by='cmd'))
        worker.start()
        time.sleep(0.1)
        with store.lock('Lydia', '1'):
            mem = store.load('Lydia', '1')
            mem['recent'].append({'day': 7, 'hour': 12, 'text': 'NEW TALK: the player promised Lydia a new sword.', 'witnesses': ['Lydia']})
            store.save('Lydia', '1', mem)
        worker.join()
    finally:
        archive.rank = real
    final = store.load('Lydia', '1')['recent']
    check('a hide and a talk saved at once: both kept', any('NEW TALK' in e['text'] for e in final) and final[0].get('hidden'), final)

# 6: undo after a trim mid-talk took the event into a memory: that memory is hidden too
with tempfile.TemporaryDirectory() as tmp:
    store = fresh(tmp)
    E.process(['Lydia finds a dragon egg\n'], {'characters': [lydia], 'game_days': 41.5, 'is_first': False}, store)
    store.save('Lydia', '0A2C94', dict(memory.empty(), recent=[{'day': 42, 'hour': 12, 'text': 'I found a dragon egg by the road.', 'witnesses': ['Lydia']}]))
    E.after_summary({'end_timestamp': 42.5, 'npcs_to_summarize': [lydia], 'is_reload': True}, store)
    E.process(['undo\n'], {'characters': [lydia], 'game_days': 41.6, 'is_first': False}, store)
    wait_threads('living-world-undo')
    shown = [e['text'] for e in store.load('Lydia', '0A2C94')['recent'] if not e.get('hidden')]
    check('undo after a trim: the memory the trim wrote is hidden', shown == [], shown)

# 7: a new talk starts a new event talk even with no custom event in its first batch
with tempfile.TemporaryDirectory() as tmp:
    store = fresh(tmp)
    E.process(['first talk event\n'], {'characters': [lydia], 'game_days': 41.5, 'is_first': False}, store)
    E.process(['Lydia said hello'], {'characters': [lydia], 'game_days': 41.7, 'is_first': True}, store)
    E.process(['undo\n'], {'characters': [lydia], 'game_days': 41.7, 'is_first': False}, store)
    check("undo never takes back the last talk's event", E.load(store)[0]['status'] == 'active', E.load(store))

# 8: a command whose check never finished (Mantella closed during it) is read again
with tempfile.TemporaryDirectory() as tmp:
    store = fresh(tmp)
    queue_file([('41.5-1', 'Forget the robbery', 41.5, 'Dragonborn')])
    real_thread = C.threading.Thread
    C.threading.Thread = lambda *a, **k: SimpleNamespace(start=lambda: None)
    try:
        C.poll(store, PEOPLE, VALUES, lambda p, t: '{}', REF, 41, 'Dragonborn', SPEAKERS)
    finally:
        C.threading.Thread = real_thread
    C.poll(store, PEOPLE, VALUES, lambda p, t: '{}', REF, 41, 'Dragonborn', SPEAKERS, background=False)
    check('a check left unfinished is started again', C.load(store)['commands'][0]['status'] == 'active', C.load(store)['commands'][0])

# 9: bio notes wait while a conversation goes on, one waiting job per NPC
bio_evolve.talk_going_on()
check('a conversation going on: bio requests wait', bio_evolve.busy())
check('...unless it went quiet long ago (Mantella closed)', not bio_evolve.busy(time.time() + bio_evolve.TALK_IDLE_SECONDS + 1))
bio_evolve.talk_over()
check('the talk is over: they may run', not bio_evolve.busy())
before = bio_evolve._queue.qsize()
bio_evolve.talk_going_on()  # the worker is not running here: jobs only wait
bio_evolve._enqueue(('root', 'Lydia', '1'), lambda: None)
bio_evolve._enqueue(('root', 'Lydia', '1'), lambda: None)
check('at most one waiting job per NPC', bio_evolve._queue.qsize() - before == 1)
bio_evolve._pending.clear()
bio_evolve.talk_over()

# 10: the greeting gets the speakers Direct AI Connect is answering for, before the game has written them
with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = tmp
    os.makedirs(os.path.join(tmp, 'npc'))
    Path(tmp, 'npc', '0A2C94.json').write_text(json.dumps({'string': {'name': 'Lydia'}, 'int': {'close': 1}}), encoding='utf-8')
    Path(tmp, 'conversation.json').write_text(json.dumps({'stringList': {'speakers': []}}), encoding='utf-8')
    check('an older Direct AI Connect (no registry): the file decides', lw_state.load_conversation() == [])
    sys.modules['src.extensions'] = SimpleNamespace(_registry=SimpleNamespace(speaking_ids=['0A2C94']))
    try:
        greeting = lw_state.load_conversation()
        Path(tmp, 'conversation.json').write_text(json.dumps({'stringList': {'speakers': ['0A2C94']}}), encoding='utf-8')
        first_turn = lw_state.load_conversation()
    finally:
        sys.modules.pop('src.extensions', None)
    check('the greeting and the first turn get the same speakers', greeting == first_turn and greeting[0].get('name') == 'Lydia', (greeting, first_turn))

# 11: keyword ranking stays fast on a big archive; recall looks at a bounded number of rows
texts = [' '.join(f'word{(i * 7 + j) % 3000}' for j in range(45)) for i in range(2000)]
rows = [{'id': str(i), 'text': t, 'day': i // 5, 'hour': 10} for i, t in enumerate(texts)]
start = time.perf_counter()
archive.rank('word1 word2 word3 word77', rows, 400, (), None, 4)
check('keyword ranking of 2000 memories takes well under a second', time.perf_counter() - start < 1.0, time.perf_counter() - start)
capped = archive.search_rows([{'id': 'old', 'text': 'x', 'day': 0, 'importance': 1.0}] + rows)
check('recall looks at the newest and the most important only', len(capped) == archive.MAX_SEARCH_ROWS and capped[0]['id'] == 'old')

# 13: a hidden memory is never sent again when the same normal-menu dialogue comes back
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'w')
    class Sum:
        def summarize_conversation(self, text, prompt):
            return '{"memory": "The Dragonborn told me the secret location of the Thieves Guild cistern.", "feelings": {"Lydia": "wary"}}'
    event = 'Dragonborn: tell me;\n Lydia: ' + ('The cistern lies beneath Riften, under the ratway, where the guild hides. ' * 10)
    ctx = {'player': 'Dragonborn', 'is_first': True, 'game_days': 10.5, 'characters': [Char('Lydia', '0001')], 'summaries': Sum(), 'chatter_filter': False}
    memory.compact_dialogue([event], ctx, store)
    memory.wait_compactions(10)  # summarized on the background worker (B05)
    memory.hide_matching(store, 'Lydia', '0001', 'Thieves Guild cistern secret location', limit=1, by='test')
    out = memory.compact_dialogue([event], ctx, store)
    check('a hidden dialogue memory is not sent again', 'cistern' not in out[0], out)

# 13b: the background dialogue summary holds no lock on that NPC's memory while the model is asked
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'w')
    free = []
    class LockSum:
        def summarize_conversation(self, text, prompt):
            got = []
            def probe():
                lock = store.lock('Lydia', '0001')
                got.append(lock.acquire(timeout=2))
                if got[-1]:
                    lock.release()
            t = threading.Thread(target=probe)
            t.start(); t.join(5)
            free.append(bool(got and got[0]))
            return '{"memory": "The Dragonborn asked me about the cistern beneath Riften.", "feelings": {"Lydia": "curious"}}'
    event = 'Dragonborn: tell me;\n Lydia: ' + ('The cistern lies beneath Riften, under the ratway, where the guild hides. ' * 10)
    ctx = {'player': 'Dragonborn', 'is_first': True, 'game_days': 10.5, 'characters': [Char('Lydia', '0001')], 'summaries': LockSum(), 'chatter_filter': False}
    memory.compact_dialogue([event], ctx, store)
    memory.wait_compactions(15)
    saved = [e for e in store.load('Lydia', '0001')['recent'] if e.get('dialogue')]
    check('the dialogue summary is asked with no lock held on that memory, and still saved once', free == [True] and len(saved) == 1, (free, saved))

# 14: hiding a talk's memory hides the promise it made; unhiding brings it back
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'w')
    mem = memory.empty()
    entry = {'day': 5, 'hour': 9, 'text': 'The player swore to help me poison Nazeem at the Cloud District.', 'witnesses': ['Lydia']}
    mem['recent'].append(entry)
    memory._link_promises(entry, mem, '{"memory": "x", "promises": [{"text": "help Lydia poison Nazeem", "by": "Dragonborn", "due_in_days": 3}]}', 5)
    store.save('Lydia', '1', mem)
    hid = memory.hide_matching(store, 'Lydia', '1', 'poison Nazeem Cloud District', by='cmd')
    shown = lambda: memory.memory_text('', {'characters': [Char('Lydia', '1')], 'today': 5, 'player': 'Dragonborn', 'recall': False}, store)
    check('a hidden memory takes its promise out of the prompt', 'Nazeem' not in shown() and memory.open_promises(store.load('Lydia', '1')) == [])
    memory.unhide(store, 'Lydia', '1', hid[0]['id'])
    check('...and unhiding brings it back', 'poison Nazeem' in shown(), shown())

# 15: hiding needs a close fit near the best one; names are left out of the query
real = archive._meaning_scores
archive._meaning_scores = lambda q, rows, engine: [0.3, 0.55, 0.47, 0.42]
try:
    picked = archive.rank('the gift', [{'id': str(i), 'text': 't', 'day': 1} for i in range(4)], None, (), object(), 5, hiding=True)
    loose = archive.rank('the gift', [{'id': str(i), 'text': 't', 'day': 1} for i in range(4)], None, (), object(), 5)
finally:
    archive._meaning_scores = real
check('hiding by meaning takes only close fits near the best', [r['id'] for _, r in picked] == ['1', '2'], picked)
check('recall stays as loose as before', len(loose) == 4)
check("the NPC's and player's names leave the query", memory._strip_names("Lydia, forget the gift Lydia's Dragonborn gave", ['Lydia', 'Dragonborn']) == 'forget the gift gave')

# 16 + 17: a fight is remembered once, also after it folded away; remembering it never cuts old memories
fight = {'id': 'f1', 'end': 10.4, 'seconds': 90, 'active': 0, 'in_prompt': 0, 'place': 'Riverwood', 'fighters': [
    {'ref_id': '14', 'name': 'Dragonborn', 'role': 'player', 'side': 0, 'lowest': 0.1},
    {'ref_id': 'a1', 'name': 'Lydia', 'role': 'party', 'side': 0, 'lowest': 0.5},
    {'ref_id': 'b1', 'name': 'Bandit Chief', 'side': 1, 'unique': 1, 'dead': 1}]}
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'w')
    battle.remember(store, [Char('Lydia', 'a1')], [fight], lambda r: r, at_end=True)
    mem = store.load('Lydia', 'a1')
    mem['recent'] += [{'day': 11, 'hour': i % 24, 'text': f'talk {i}', 'witnesses': ['Lydia']} for i in range(30)]
    store.save('Lydia', 'a1', memory.fold_old(mem, store))
    check('a fight that folded away is not remembered again', battle.remember(store, [Char('Lydia', 'a1')], [fight], lambda r: r, at_end=False) == 0)
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'w')
    mem = memory.empty()
    mem['long_term']['earlier'] = 'HOW WE MET: Lydia was given to me as housecarl. ' + 'x' * 2300
    mem['recent'] = [{'day': 20, 'hour': i % 24, 'text': f'talk {i}', 'witnesses': ['Lydia']} for i in range(30)]
    store.save('Lydia', 'a1', mem)
    battle.remember(store, [Char('Lydia', 'a1')], [dict(fight, end=21.4)], lambda r: r, at_end=False)
    check('remembering a fight never cuts the oldest memories', 'HOW WE MET' in store.load('Lydia', 'a1')['long_term']['earlier'])

# 18: a huge battle's accounts stay bounded
big = [{'ref_id': 'p', 'name': 'Dragonborn', 'role': 'player', 'side': 0, 'lowest': 0.5, 'kills': [f'b{j}' for j in range(0, 40, 4)]}]
big += [{'ref_id': f'a{i}', 'name': f'Soldier {i}', 'unique': 1, 'side': 0, 'lowest': 0.1, 'danger_by': f'b{i}',
         'rescued_by': [{'ref': 'p', 'how': 'heal'}], 'harm': {'fire': [f'b{i}']}, 'kills': [f'b{i}']} for i in range(40)]
big += [{'ref_id': f'b{i}', 'name': f'Imperial {i}', 'unique': 1, 'side': 1, 'dead': 1, 'killer': 'p'} for i in range(40)]
fights = [{'id': i, 'in_prompt': 1, 'end': 10.2, 'seconds': 600, 'fighters': big} for i in range(2)]
one = battle.prompt_text([{'name': 'Soldier 0', 'ref_id': 'a0'}], fights, 10, lambda r: r)
group = battle.prompt_text([{'name': f'Soldier {i}', 'ref_id': f'a{i}'} for i in range(5)], fights, 10, lambda r: r)
check('a huge battle: one account stays short', 0 < len(one) <= battle.MAX_FIGHTS * (battle.MAX_ACCOUNT_CHARS + 10), len(one))
check('...and a group gets a bounded block', 0 < len(group) <= battle.MAX_GROUP_CHARS + 5 * 120, len(group))

# 19: the Memory page puts hidden memories back where they were, not at the end
recent = [{'day': 30, 'hour': 9, 'text': 'We walked to Whiterun.'}]
hidden = [{'day': 2, 'hour': 9, 'text': 'Old secret.', 'hidden': {'day': -1}}]
check('hidden memories keep their place by time', [e['day'] for e in memory_ui.with_hidden(recent, hidden)] == [2, 30])

# 20: the memory model: any failure is caught, and a load that never ended may start again
real_find = embed.find_folder
state = dict(embed._state)
try:
    embed.find_folder = lambda folders: (_ for _ in ()).throw(SystemExit('gone'))
    embed._state.update(engine=None, failed='', folders=['x'], started=False, started_at=0.0)
    embed._load()
    check('even a SystemExit while loading is caught and noted', 'SystemExit' in embed._state['failed'], embed._state['failed'])
    embed.find_folder = lambda folders: None
    embed._state.update(engine=None, failed='', started=True, started_at=time.time() - embed.LOAD_TIMEOUT - 5)
    thread = embed.start()
    if thread:
        thread.join(5)
    check('a load still not done after the timeout is started again', thread is not None and embed._state['failed'] == 'no model')
    embed._state.update(failed='', started=True, started_at=time.time())
    check('...but not while one is still young', embed.start() is None)
    embed._state.update(failed='', started=True, started_at=time.time() - embed.LOAD_TIMEOUT - 5, downloading=True)
    check('...nor while the first one is still downloading (a second would write into the same file)', embed.start() is None)
finally:
    embed.find_folder = real_find
    embed._state.clear()
    embed._state.update(state)
    embed.use(None)


# 15b: a looser fit (0.25-0.4) is hidden only when the summary model confirms it holds the thing
SIMS = {'The Dragonborn gave me a steel sword as a gift.': 0.33, 'We talked about the weather.': 0.28,
        'The Dragonborn stole a sweetroll from Belethor.': 0.26, 'We fought bandits near Riverwood.': 0.1}
real_scores = archive._meaning_scores
archive._meaning_scores = lambda q, rows, engine: [SIMS.get(r.get('text'), 0.0) for r in rows]
embed.use(SimpleNamespace())
try:
    def hide_with(forget, confirm, sims_text):
        with tempfile.TemporaryDirectory() as tmp:
            store = memory.MemoryStore(tmp, 'w')
            store.save('Lydia', '1', dict(memory.empty(), recent=[{'day': 5, 'hour': i, 'text': t, 'witnesses': ['Lydia']}
                                                                 for i, t in enumerate(sims_text)]))
            return [h['text'] for h in memory.hide_matching(store, 'Lydia', '1', forget, limit=3, by='cmd', confirm=confirm)]
    asked = []
    def model(prompt, text):
        asked.append((prompt, text))
        return json.dumps(['yes' if ('gift' in line and 'gift' in prompt) or ('sweetroll' in line and 'theft' in prompt) else 'no'
                           for line in text.split('\n')])
    texts = list(SIMS)
    got = hide_with('the gift', C._confirmer(model, 'Lydia', 'the gift'), texts)
    check('forget "the gift": the model confirms the gift memory, the unrelated one stays', got == [texts[0]], got)
    check('...in one request for all the uncertain ones', len(asked) == 1 and asked[0][1].count('\n') == 2, asked)
    got = hide_with('the theft', C._confirmer(model, 'Lydia', 'the theft'), texts)
    check('forget "the theft": the sweetroll memory is hidden once confirmed', got == [texts[2]], got)
    check('without the model nothing loose is hidden', hide_with('the gift', None, texts) == [])
    check('a failing model call hides nothing loose', hide_with('the gift', C._confirmer(lambda p, t: 1 / 0, 'Lydia', 'the gift'), texts) == [])
    check('a reply that is not a list of the right length hides nothing loose',
          hide_with('the gift', C._confirmer(lambda p, t: 'yes', 'Lydia', 'the gift'), texts) == [])
    SIMS['The Dragonborn gave me a steel sword as a gift.'] = 0.6
    check('a close fit is hidden without asking', hide_with('the gift', None, texts) == [texts[0]])
finally:
    archive._meaning_scores = real_scores
    embed.use(None)
check('parse_confirm reads yes/no lists', C.parse_confirm('["yes", "No"]', 2) == [True, False] and C.parse_confirm('["yes"]', 2) is None)


# D01: the talk's end waits briefly, once; dialogue whose summary is still running is taken by the talk (the worker
# drops it), and dialogue whose summary came back is left to the worker (the talk leaves it out): saved once either way
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'w')
    gate = threading.Event()
    class SlowSum:
        def summarize_conversation(self, text, prompt):
            gate.wait(10)
            return '{"memory": "The Dragonborn asked me about the cistern beneath Riften.", "feelings": {"Lydia": "curious"}}'
    event = 'Dragonborn: tell me;\n Lydia: ' + ('The cistern lies beneath Riften, under the ratway, where the guild hides. ' * 10)
    source = memory._dialogue_source(memory._flat_dialogue(event))
    ctx = {'player': 'Dragonborn', 'is_first': True, 'game_days': 10.5, 'characters': [Char('Lydia', '0001')], 'summaries': SlowSum(), 'chatter_filter': False}
    memory.compact_dialogue([event], ctx, store)
    time.sleep(0.3)
    skip = memory.compacted_sources(store, take=[source])
    gate.set()
    memory.wait_compactions(15)
    kept = [e for e in store.load('Lydia', '0001')['recent'] if e.get('dialogue')]
    check('talk end: a dialogue summary still running is taken by the talk, and the worker then drops it', source not in skip and not kept, (skip, kept))
    gate.clear()
    lock = store.lock('Lydia', '0002')
    lock.acquire()  # the worker gets its summary, then waits for the memory file
    try:
        memory.compact_dialogue([event], dict(ctx, characters=[Char('Lydia', '0002')], summaries=SlowSum()), store)
        gate.set()
        time.sleep(0.5)
        skip = memory.compacted_sources(store, take=[source])
    finally:
        lock.release()
    memory.wait_compactions(15)
    kept = [e for e in store.load('Lydia', '0002')['recent'] if e.get('dialogue')]
    check('...one whose summary came back is left out of the talk, and the worker saves it', source in skip and len(kept) == 1, (skip, kept))
src = (SERVER / 'living_world' / 'memory.py').read_text(encoding='utf-8')
check('talk end: one short wait per talk end, none on a departure (reload)', 'wait_compactions(TALK_END_WAIT_SECONDS)' in src
      and memory.TALK_END_WAIT_SECONDS <= 10 and 'wait_compactions()' not in src)

# E-HR02: how long an NPC has known the player counts only memories still in mind (not forgotten)
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'w')
    mem = memory.empty()
    mem['recent'] = [{'day': d, 'hour': 9, 'text': f'Talk {d}.', 'witnesses': ['Lydia']} for d in (2, 5, 9)]
    for e in mem['recent'][:2]:
        e['hidden'] = {'day': 10, 'by': 'command', 'note': 'forget you ever met me'}
    store.save('Lydia', '0A2C94', mem)
    real = dict(living_world._last_store)
    living_world._last_store.update(store=store, people=[('Lydia', '0A2C94')])
    try:
        said = living_world._known_for('Player')({'name': 'Lydia'})
    finally:
        living_world._last_store.clear()
        living_world._last_store.update(real)
    check('known-for line: forgotten talks are not counted', said.startswith('1 talk with Player remembered'), said)

# D06: the npc file is shared by every save; standing written for another character is not used until it is rewritten
real_dir = lw_state.DATA_DIR
with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = tmp
    os.makedirs(os.path.join(tmp, 'npc'))
    Path(tmp, 'conversation.json').write_text(json.dumps({'string': {'player': 'Dovahkiin'}}), encoding='utf-8')
    def npc_file(owner):
        Path(tmp, 'npc', '000A2C94.json').write_text(json.dumps({'string': dict({'name': 'Lydia', 'maras_status': 'married'}, **({'player': owner} if owner else {})),
                                                                  'int': {'minor': 0, 'close': 1, 'intimate': 1, 'spouse': 1, 'nff': 1}}), encoding='utf-8')
        lw_state._memo.clear()
        return lw_state.load_npc('000A2C94')
    try:
        other, mine, old = npc_file('Talos'), npc_file('Dovahkiin'), npc_file('')
        check('npc file of another character: no standing (close, intimate, spouse, M.A.R.A.S, NFF), age kept',
              not any(k in other for k in ('close', 'intimate', 'spouse', 'nff', 'maras_status')) and other.get('minor') == 0, other)
        check('...the same character, or an older file with no player: all kept', mine.get('close') == 1 and mine.get('maras_status') == 'married'
              and old.get('intimate') == 1, (mine, old))
    finally:
        lw_state.DATA_DIR = real_dir
        lw_state._memo.clear()
src = (SERVER.parent / 'Source' / 'Scripts' / 'MLW_Channel.psc').read_text(encoding='utf-8')
home_fn = src.split('string Function NpcHome', 1)[1].split('EndFunction', 1)[0]
check('a lover (rank 4) is not taken as married, so a visit to a player house is not saved as their home',
      'GetRelationshipRank' not in home_fn and '0x0C6472' in home_fn and '"maras", 0) >= 3' in home_fn)
check('the game writes whose standing it is, on both write paths', src.count('JsonUtil.SetStringValue(path, "player", PlayerRef.GetDisplayName())') == 2)

# E-HM07: dialogue goes to the NPC whose whole name speaks in it ("Captain Guard:" also holds " Guard:")
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'w')
    class CapSum:
        def summarize_conversation(self, text, prompt):
            return '{"memory": "The Dragonborn asked me about the watch rota.", "feelings": {"Captain Guard": "busy"}}'
    event = 'Dragonborn: who keeps watch;\n Captain Guard: ' + ('The night watch walks the walls from dusk until the bells ring at dawn. ' * 10)
    ctx = {'player': 'Dragonborn', 'is_first': True, 'game_days': 10.5, 'characters': [Char('Guard', '0003'), Char('Captain Guard', '0004')],
           'summaries': CapSum(), 'chatter_filter': False}
    memory.compact_dialogue([event], ctx, store)
    memory.wait_compactions(15)
    check('a group dialogue memory goes to Captain Guard, not to Guard', [e for e in store.load('Captain Guard', '0004')['recent'] if e.get('dialogue')]
          and not store.load('Guard', '0003')['recent'])

# E-HM08: recalling a memory again on the same day writes nothing, so the archive's cached rows stay
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'w')
    store.save('Lydia', '0A2C94', dict(memory.empty(), recent=[{'day': 3, 'hour': 9, 'text': 'We met.', 'witnesses': ['Lydia']}]))
    db = store.archive_for('Lydia', '0A2C94')
    row = db.rows()[0]
    db.mark_recalled([row['id']], 10)
    db.rows()
    cached = any(k[0] == db.path for k in archive._cache)
    db.mark_recalled([row['id']], 10)
    check('recalled again the same day: the cached rows are kept', cached and any(k[0] == db.path for k in archive._cache))
    db.mark_recalled([row['id']], 11)
    check('...a later day still updates it', db.rows()[0]['recalled_day'] == 11, db.rows()[0])

# D02: a ShareConversation recipient is told only when their npc file (found by reference id) says adult
real_dir = lw_state.DATA_DIR
with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = tmp
    os.makedirs(os.path.join(tmp, 'npc'))
    for base, name, ref, minor in (('00013482', 'Alvor', '00013482', 0), ('0001A6F1', 'Lucia', '0001A6F1', 1), ('00013BBF', 'Hilde', '00013BBF', None)):
        values = {'name': name, 'ref_id': ref}
        Path(tmp, 'npc', base + '.json').write_text(json.dumps({'string': values, 'int': {} if minor is None else {'minor': minor}}), encoding='utf-8')
    try:
        check('share recipient: an adult by the game is told; a child, one with no minor key or no file is not',
              living_world._share_adult('Alvor', '013482') and not living_world._share_adult('Lucia', '01A6F1')
              and not living_world._share_adult('Hilde', '013BBF') and not living_world._share_adult('Nobody', '0BEEF0'))
    finally:
        lw_state.DATA_DIR = real_dir


print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
