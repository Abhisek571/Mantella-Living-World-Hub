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

# HUB-2: Save memory keeps memories the game wrote while the tab was open
BOUND = {}
class Component:
    def __init__(self, kind, *args, **kwargs):
        self.kind, self.args, self.kwargs = kind, args, kwargs
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def __getattr__(self, event):  # click, change, focus, then, submit...
        def bind(fn=None, *args, **kwargs):
            BOUND.setdefault(getattr(fn, '__name__', ''), fn)
            return self
        return bind

class Gradio:
    def __init__(self):
        self.made = []
    def update(self, **kwargs):
        return kwargs
    def Info(self, text):
        pass
    def __getattr__(self, kind):
        def make(*args, **kwargs):
            component = Component(kind, *args, **kwargs)
            self.made.append(component)
            return component
        return make

with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'Player1')
    store.save('Ann', '0A0B0C', dict(memory.empty(), recent=[{'day': 1, 'hour': 9, 'text': 'first', 'witnesses': ['Ann']}]))
    gr = Gradio()
    memory_ui.build(gr, tmp)
    show, save = BOUND['show'], BOUND['save']
    label = 'Ann'
    _, feeling, rows, long_rows = show('Player1', label)[:4]
    later = store.load('Ann', '0A0B0C')
    later['recent'].append({'day': 2, 'hour': 10, 'text': 'second, from the game', 'witnesses': ['Ann']})
    store.save('Ann', '0A0B0C', later)
    rows = [list(r) for r in rows]
    rows[0][2] = 'first, edited'
    said = save('Player1', 'calm', rows, long_rows, label)[1]
    texts = [e['text'] for e in store.load('Ann', '0A0B0C')['recent']]
    check('edit saved and the game memory kept', texts == ['first, edited', 'second, from the game'], texts)
    check('the notice says so', 'newer memory' in said, said)
    said = save('Player1', 'calm', rows, long_rows, label)[1]
    texts = [e['text'] for e in store.load('Ann', '0A0B0C')['recent']]
    check('saving twice adds nothing twice', texts == ['first, edited', 'second, from the game'], texts)
    _, _, rows, long_rows = show('Player1', label)[:4]
    rows = [list(r) for r in rows][:1]  # the player deletes the second row
    said = save('Player1', 'calm', rows, long_rows, label)[1]
    texts = [e['text'] for e in store.load('Ann', '0A0B0C')['recent']]
    check('a row deleted in the table stays deleted', texts == ['first, edited'], texts)

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
