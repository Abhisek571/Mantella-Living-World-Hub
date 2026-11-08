"""Robustness tests for the Hub's server side: fuzzed model replies and files, limits, invariants, threads and speed.
Everything is written under one temp folder; a guard records any write that goes anywhere else.
Run with a Python 3.11: test_robustness.py <repo server dir>   (LW_SEED=<n> repeats one random run)"""
import builtins, io, json, logging, os, random, shutil, sys, tempfile, threading, time
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import lw_state, memory, memory_ui, server_status, settings
memory.SUMMARY_RETRY_SECONDS = 0  # retried summary calls without the real wait

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:400]) if not cond else ''))
    if not cond:
        FAILS.append(name)

logging.getLogger('Mantella').addHandler(logging.NullHandler())  # the warnings are expected here; keep the output short
SEED = int(os.environ.get('LW_SEED', '20261106'))
rng = random.Random(SEED)
print(f'seed {SEED}')

# --- every write must land in the temp folder ---
TOP = tempfile.mkdtemp(prefix='lw-robust-')
TOP_REAL = os.path.normcase(os.path.abspath(TOP))
OUTSIDE = []
def _guard(*paths):
    for path in paths:
        if isinstance(path, int):
            continue
        real = os.path.normcase(os.path.abspath(os.fspath(path)))
        if not (real == TOP_REAL or real.startswith(TOP_REAL + os.sep)):
            OUTSIDE.append(real)
_real = {'open': builtins.open, 'replace': os.replace, 'rename': os.rename, 'mkdir': os.mkdir, 'remove': os.remove}
def _open(file, mode='r', *a, **k):
    if any(c in mode for c in 'wax+'):
        _guard(file)
    return _real['open'](file, mode, *a, **k)
builtins.open = io.open = _open
os.replace = lambda src, dst, *a, **k: (_guard(src, dst), _real['replace'](src, dst, *a, **k))[1]
os.rename = lambda src, dst, *a, **k: (_guard(src, dst), _real['rename'](src, dst, *a, **k))[1]
os.mkdir = lambda path, *a, **k: (_guard(path), _real['mkdir'](path, *a, **k))[1]
os.remove = lambda path, *a, **k: (_guard(path), _real['remove'](path, *a, **k))[1]

def folder(name):
    path = os.path.join(TOP, name)
    os.makedirs(path, exist_ok=True)
    return path

lw_state.DATA_DIR = folder('channel')
REAL_OVERRIDES, REAL_SETTINGS = settings.load_profile_overrides, settings.load
OVERRIDES = {}  # the real files sit next to the extension: the hooks read these stand-ins instead
settings.load_profile_overrides = lambda path=None: OVERRIDES
settings.load = lambda path=os.path.join(TOP, 'settings.json'): REAL_SETTINGS(path)


# --- stand-ins for Mantella's classes (as in test_memory.py) ---
class Char:
    def __init__(self, name, ref_id, bio='A person.'):
        self.name, self.ref_id, self.bio = name, ref_id, bio

class Thread:
    def __init__(self, lines):
        self.lines = lines
    def get_talk_only(self, include_system_generated_messages=False):
        return list(self.lines)
    def transform_to_dict_representation(self, messages):
        return '\n'.join(str(m) for m in messages)
    def __len__(self):
        return len(self.lines)

class Params:
    def __init__(self, lines, chars):
        self.messages, self.characters = Thread(lines), chars

class People:
    def __init__(self, player='Player'):
        self.player = player
    def get_player_name(self):
        return self.player

class Game:
    def __init__(self, path):
        self.conversation_folder_path = path

class FakeSummaries:
    """Thread split, grouping and the summary call; reply() gives each call's answer and may raise."""
    def __init__(self, threads, reply, game=None):
        self.threads, self.reply, self.calls = threads, reply, 0
        self._Summaries__game, self._Summaries__language_name = game, 'English'
    def get_threads_for_summarization(self, messages, npcs):
        return self.threads
    def group_shared_threads(self, threads):
        groups = {}
        for name, p in threads.items():
            groups.setdefault(tuple(p.messages.lines), []).append(name)
        return list(groups.values())
    def summarize_conversation(self, text, prompt):
        self.calls += 1
        reply = self.reply() if callable(self.reply) else self.reply
        if isinstance(reply, Exception):
            raise reply
        return reply


# --- random data ---
NAMES = ['Lydia', 'Mjoll', 'nyri', 'Whiterun Guard 2', 'Sóra', '你好', 'Jarl: Balgruuf', '..', 'CON', 'x' * 120]
STRS = ['', ' ', 'x', '{', '}', '{}', '[]', '{"memory": ', '```json', '```', '|', '1|2|3|', '\x00', '²', '٣',
        'Infinity', 'NaN', 'null', 'true', 'Player', 'the player', '<name>', 'Feelings: glad', 'Feelings:\nLydia: wary',
        '\n\n', '你好', '😀' * 30, 'a\ud83db', 'Take Lydia to Solitude', 'take lydia to solitude.', '../../escape', 'Ä' * 300]
KEYS = ['memory', 'feelings', 'promises', 'kept', 'values', 'text', 'by', 'due_in_days', 'day', 'hour', 'shared',
        'talk', 'deeds', 'care', 'gifts', 'physical', 'Lydia', 'Mjoll', '<name>', '']

ALPHABET = list(range(32, 127)) + list(range(160, 1200)) + list(range(0x4E00, 0x4E80)) + list(range(0x1F300, 0x1F340))
def rstr():
    r = rng.random()
    if r < 0.6:
        return rng.choice(STRS)
    if r < 0.9:
        return ''.join(map(chr, rng.choices(ALPHABET, k=rng.randint(0, 40))))
    return rng.choice('ab{}|"\\ ') * rng.choice([500, 5000, 60000])

SCALARS = [None, True, False, 0, 1, -1, 2, 3, 365, 366, -7, 10 ** 30, 2.5, 3.0, 1e308, float('inf'), float('-inf'), float('nan')]
def rscalar():
    r = rng.random()
    return rng.choice(SCALARS) if r < 0.7 else (rng.randint(-10 ** 6, 10 ** 6) if r < 0.8 else rstr())

def rvalue(depth=0):
    r = rng.random()
    if depth > 2 or r < 0.55:
        return rscalar()
    if r < 0.78:
        return [rvalue(depth + 1) for _ in range(rng.randint(0, 5))]
    return {rng.choice(KEYS) if rng.random() < 0.8 else rstr(): rvalue(depth + 1) for _ in range(rng.randint(0, 5))}

def rpromise():
    if rng.random() < 0.2:
        return rvalue(1)
    item = {'text': rng.choice([rstr(), f'Errand {rng.randint(0, 40)} for the town', rvalue(2)]),
            'by': rng.choice(['Player', 'Lydia', '', None, 5, rvalue(2)]),
            'due_in_days': rng.choice([None, 0, 1, 2, '3', '²', '٣', 365, 366, -1, 1.0, 1.5, True, 1e308, float('inf'), 'soon'])}
    return {k: v for k, v in item.items() if rng.random() < 0.9}

def rreply(names=('Lydia',)):
    data = {'memory': rng.choice([rstr(), rvalue(1), 'We walked to Riverwood.']),
            'feelings': rng.choice([{n: rng.choice([rstr(), rvalue(2)]) for n in names}, rvalue(1), rstr()]),
            'promises': rng.choice([[rpromise() for _ in range(rng.randint(0, 14))], rvalue(1)]),
            'kept': rng.choice([[rstr(), f'Errand {rng.randint(0, 40)} for the town'], rvalue(1)]),
            'values': rng.choice([{n: {c: rng.choice([1, 2, 3, '2', 3.0, 0, 4, True, '²', None]) for c in memory.CHANNELS}
                                   for n in names}, rvalue(1)])}
    data = {k: v for k, v in data.items() if rng.random() < 0.85}
    text = json.dumps(data, ensure_ascii=rng.random() < 0.5)
    form = rng.randint(0, 8)
    if form == 0:
        return '```json\n' + text + '\n```'
    if form == 1:
        return 'Here you go:\n' + text + '\nHope that helps }'
    if form == 2:
        return text[:rng.randint(0, len(text))]
    if form == 3:
        return text + '}}'
    if form == 4:
        return rstr()
    if form == 5:
        return rng.choice(['', None, 'We fished.\n\nFeelings: Lydia: glad', '[' * 5000])
    return text

def rmemory_file():
    """What a memory file may hold after hand edits and old versions."""
    if rng.random() < 0.15:
        return rvalue()
    recent = []
    for _ in range(rng.choice([0, 1, 5, 40])):
        e = {'day': rng.choice([rscalar(), rng.randint(-2, 500)]), 'hour': rng.choice([rscalar(), rng.randint(-1, 30)]),
             'text': rng.choice([rstr(), 'We met at the inn.', rvalue(1)]), 'witnesses': rvalue(1)}
        if rng.random() < 0.15:
            e = {'day': 3, 'hour': 9, 'shared': rng.choice(['0123456789abcdef', rstr(), 5])}
        if rng.random() < 0.1:
            e = rvalue(1)
        recent.append(e)
    data = {'recent': recent, 'long_term': rng.choice([{'earlier': rstr()}, rvalue(1)]), 'feeling': rng.choice([rstr(), rvalue(1)]),
            'asked': rvalue(1), 'facts': rng.choice([[{'text': rstr(), 'status': rng.choice(['open', 'kept', None, 5]),
                                                     'day': rscalar(), 'due_day': rscalar(), 'by': rscalar()} for _ in range(rng.randint(0, 40))], rvalue(1)]),
            'talks': rscalar(), 'profile': rng.choice([rvalue(1), {c: rng.choice([1, 2, 3, '²', 10 ** 30]) for c in memory.CHANNELS}])}
    return {k: v for k, v in data.items() if rng.random() < 0.9}

def valid_memory(m):
    return (set(m) >= set(memory.empty()) and isinstance(m['recent'], list) and all(isinstance(e, dict) and isinstance(e.get('day'), int)
            and isinstance(e.get('hour'), int) and isinstance(e.get('text', ''), str) for e in m['recent'])
            and isinstance(m['long_term'], dict) and all(isinstance(v, str) for v in m['long_term'].values())
            and isinstance(m['feeling'], str) and isinstance(m['facts'], list) and isinstance(m['talks'], int) and m['talks'] >= 0
            and all(isinstance(f['text'], str) and f['text'].strip() and len(f['text']) <= memory.MAX_FACT_CHARS for f in m['facts'])
            and (m['profile'] == {} or memory.clean_profile(m['profile']) == m['profile']))

def first_error(fn, *args):
    try:
        fn(*args)
        return None
    except Exception as e:
        return f'{type(e).__name__}: {e}'


# ======================= 1. model replies =======================
errors, bad = [], []
mem = memory.empty()
day = 0
for i in range(600):
    reply = rreply(('Lydia', 'Mjoll') if i % 3 else ('Lydia',))
    names = ['Lydia', 'Mjoll'] if i % 3 else ['Lydia']
    try:
        text, feelings = memory.parse_summary(reply, names)
        if not (isinstance(text, str) and len(text) <= memory.MAX_ENTRY_CHARS and isinstance(feelings, dict)
                and set(feelings) <= set(names) and all(isinstance(v, str) and len(v) <= memory.MAX_FEELING_CHARS for v in feelings.values())):
            bad.append(('parse', reply[:80] if isinstance(reply, str) else reply, text[:80], feelings))
        day = rng.choice([day, day + rng.randint(0, 40), -1, 0, 10 ** 6]) if i % 50 else day
        memory.add_promises(mem, reply, day)
        open_now = memory.open_promises(mem)
        if day >= 0 and len(open_now) > memory.MAX_OPEN or len(mem['facts']) > memory.MAX_FACTS:
            bad.append(('facts count', day, len(open_now), len(mem['facts'])))
        if not valid_memory(mem):
            bad.append(('facts shape', mem['facts'][-3:]))
        for f in mem['facts']:
            if f.get('status') == 'open' and day >= 0:
                due, made = f['due_day'], f['day']
                if (due >= 0 and day - due > memory.LAPSE_DAYS) or (due < 0 and made >= 0 and day - made > memory.UNDATED_LAPSE_DAYS):
                    bad.append(('not lapsed', day, f))
            if f.get('source') == 'ai' and not (f['due_day'] == -1 or f['day'] <= f['due_day'] <= f['day'] + 365):
                bad.append(('due day out of range', f))
        prof = dict(memory.empty())
        memory.add_profile(prof, reply, 'Lydia')
        if prof['profile'] and memory.clean_profile(prof['profile']) != prof['profile']:
            bad.append(('profile', prof['profile']))
    except Exception as e:
        errors.append(f'{type(e).__name__}: {e} <- {str(reply)[:120]!r}')
check('fuzzed replies: parse, promises and profile never raise', not errors, errors[:3])
check('fuzzed replies: invariants hold (sizes, open <= 10, lapsing, due days, profile)', not bad, bad[:3])
check('regression: a due day of "²" is no number, not a crash', first_error(memory.add_promises, memory.empty(),
      json.dumps({'promises': [{'text': 'Bring a sword back', 'due_in_days': '²'}]}), 5) is None)
check('regression: a 30-digit rating is refused, not a crash', memory.clean_profile({c: 10 ** 30 for c in memory.CHANNELS}) == {})
check('regression: an essay-long feeling from the model is cut',
      len(memory.parse_summary(json.dumps({'memory': 'm', 'feelings': {'Ann': 'warm ' * 5000}}), ['Ann'])[1]['Ann']) <= memory.MAX_FEELING_CHARS
      and len(memory.parse_summary('m\nFeelings: ' + 'warm ' * 5000, ['Ann'])[1]['Ann']) <= memory.MAX_FEELING_CHARS)

# promises lapse exactly as designed
lap = memory.empty()
memory.add_promises(lap, json.dumps({'promises': [{'text': 'Fix the mill gate', 'due_in_days': 1}, {'text': 'Visit the shrine one day'}]}), 10)
memory.add_promises(lap, '{}', 71)
on71 = memory.open_promises(lap)
memory.add_promises(lap, '{}', 72)
on72 = memory.open_promises(lap)
memory.add_promises(lap, '{}', 130)
on130 = memory.open_promises(lap)
memory.add_promises(lap, '{}', 131)
check('promises lapse at 60 days late and 120 days undated, not a day sooner',
      len(on71) == 2 and on72 == ['Visit the shrine one day'] and on130 == on72 and memory.open_promises(lap) == [], (on71, on72, on130))
check('lapsed promises are kept as history', [f['status'] for f in lap['facts']] == ['lapsed', 'lapsed'], lap['facts'])
many = memory.empty()
for d in range(25):
    memory.add_promises(many, json.dumps({'promises': [{'text': f'Errand number {d} for the town', 'due_in_days': None}]}), d)
check('never more than 10 open promises, the newest stay', memory.open_promises(many) == [f'Errand number {d} for the town' for d in range(15, 25)], memory.open_promises(many))
check('stored facts capped', len(many['facts']) <= memory.MAX_FACTS)


# ======================= 2. hand-edited memory files =======================
store = memory.MemoryStore(folder('conv1'), 'Player1')
errors, bad = [], []
shared_dir = Path(store.root) / 'shared'
shared_dir.mkdir(parents=True, exist_ok=True)
for i in range(160):
    path = store._path('Odd', str(i % 7))
    path.parent.mkdir(parents=True, exist_ok=True)
    data = rmemory_file()
    form = rng.randint(0, 9)
    try:
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8', 'replace')
    except (ValueError, TypeError):
        raw = b'{}'
    if form == 0:
        raw = raw[:rng.randint(0, len(raw))]
    elif form == 1:
        raw = '﻿'.encode('utf-8') + raw
    elif form == 2:
        raw = bytes(rng.randint(0, 255) for _ in range(rng.randint(0, 300)))
    elif form == 3:
        raw = b'[' * 50000
    elif form == 4:
        raw = rng.choice([b'null', b'[]', b'"text"', b'5', b'{"recent": {"a": 1}}', b'{"recent": [{"day": Infinity, "text": "x"}], "talks": 1e999}'])
    (shared_dir / '0123456789abcdef.json').write_bytes(rng.choice([b'[1]', b'{"text": 5}', b'{"text": "Shared talk."}', b'{', b'[' * 50000]))
    path.write_bytes(raw)
    try:
        loaded = store.load('Odd', str(i % 7))
        if not valid_memory(loaded):
            bad.append(('shape', raw[:100]))
        for budget in (0, 1, 7, 400, 10 ** 6, -5):
            out = memory.render(loaded, budget, store)
            if memory.tokens(out) > max(budget, 0):
                bad.append(('render budget', budget, memory.tokens(out), raw[:80]))
        memory.facts_text(loaded, [], rng.choice([None, 0, 5, 10 ** 9]), 'Player', 'Odd', rng.choice([0, 1, 200, -3]))
        store.save('Odd', str(i % 7), memory.fold_old(loaded, store))
        again = store.load('Odd', str(i % 7))
        if not valid_memory(again) or len(again['recent']) > memory.MAX_RECENT:  # a hand-written long note may stay long
            bad.append(('after save', raw[:80]))
    except Exception as e:
        errors.append(f'{type(e).__name__}: {e} <- {raw[:120]!r}')
check('hand-edited memory files: load, render, fold and save never raise', not errors, errors[:3])
check('hand-edited memory files: always cleaned into shape and inside every budget', not bad, bad[:3])
for f in Path(store.root).glob('*.tmp'):
    check('no temp file left behind', False, f)

p = store._path('Keep', '1')
p.write_text(json.dumps({'recent': [{'day': 1, 'hour': 2, 'text': 'Keep this memory.'}],
                         'profile': {'talk': '²', 'deeds': 1, 'care': 1, 'gifts': 1, 'physical': 1}}), encoding='utf-8')
check('regression: an odd rating does not make a good file "unreadable" (starting empty)',
      store.load('Keep', '1')['recent'][0]['text'] == 'Keep this memory.' and not list(p.parent.glob('Keep - 1.json.unreadable*')))
p.write_text('{"recent": [{"day": Infinity, "hour": 1, "text": "Inf day."}], "talks": 1e999}', encoding='utf-8')
check('regression: Infinity in a hand-edited file is read as no date', first_error(store.load, 'Keep', '1') is None
      and store.load('Keep', '1')['recent'][0]['day'] == -1)
(shared_dir / 'fedcba9876543210.json').write_text('[1, 2]', encoding='utf-8')
p.write_text(json.dumps({'recent': [{'day': 1, 'hour': 2, 'shared': 'fedcba9876543210'}]}), encoding='utf-8')
check('regression: a shared file that is not a dict does not break the load', first_error(store.load, 'Keep', '1') is None
      and store.load('Keep', '1')['recent'][0]['text'] == '')
p.write_text('[' * 100000, encoding='utf-8')
check('regression: a deeply nested file is set aside, not a crash', first_error(store.load, 'Keep', '1') is None)
m = dict(memory.empty(), feeling='a\ud83db', recent=[{'day': 1, 'hour': 1, 'text': 'x\udc00y'}])
check('regression: a lone surrogate from a model reply still saves', first_error(store.save, 'Sur', '1', m) is None
      and store.load('Sur', '1')['feeling'] == 'a?b' and not list(Path(store.root).glob('*.tmp')))

# save and load round-trip
rt_bad = []
for i in range(120):
    data = memory.clean(rmemory_file())
    data['recent'] = [e for e in data['recent'] if 'shared' not in e]
    try:
        text = json.dumps(data, ensure_ascii=False, allow_nan=False)
    except ValueError:
        continue  # NaN never equals itself: nothing to compare
    if any(0xD800 <= ord(c) <= 0xDFFF for c in text):
        continue  # saved as '?' on purpose (see above)
    store.save('Round', str(i), data)
    if store.load('Round', str(i)) != data:
        rt_bad.append(i)
check('save then load gives back the same memory', not rt_bad, rt_bad[:5])


# ======================= 3. game facts, npc files, channel files =======================
FACT_FORMS = ['', '|', '||', '|||', '1|2|3', '1|2|3|', '1|2|3| ', 'a|b|c|text', '1.5|2|3|x', '9' * 5000 + '|1|1|x', ' 1 | 2 | 3 |padded',
              '٣|-1|2|arabic digit day', '-1|-1|2|undated', '1|2|3|a|b|c', None, 5, ['1|2|3|x'], {'a': 1}, '1|-5|3|odd expiry',
              '1_0|1|1|underscore', '+1|+2|+3|signs', '1|2|9999999999999999999|big priority']
bad, errors = [], []
for i in range(300):
    today = rng.choice([None, -1, 0, 1, 5, 40, 10 ** 9])
    npc, expected = {}, []
    for k in range(rng.randint(0, 12)):
        if rng.random() < 0.5:
            d, e, pr = rng.randint(-1, 60), rng.choice([-1, rng.randint(0, 80)]), rng.randint(1, 3)
            text = rng.choice(['You healed me', 'Fav food: stew', 'Gave a ring', '你好', 'x' * 400])
            npc[f'fact_{k}'] = f'{d}|{e}|{pr}|{text}'
            if e < 0 or today is None or today <= e:
                expected.append((d, pr, text))
        else:
            npc[rng.choice([f'fact_bad{k}', f'FACT_{k}x', f'note_{k}'])] = rng.choice(FACT_FORMS)
    try:
        rows = lw_state.game_facts(npc, today)
    except Exception as e:
        errors.append(f'{type(e).__name__}: {e}')
        continue
    got = {(r['day'], r['priority'], r['text']) for r in rows}
    if not set(expected) <= got:
        bad.append(('missing', set(expected) - got))
    for key, value in npc.items():  # nothing expired is shown
        if isinstance(value, str) and value.count('|') >= 3:
            parts = value.split('|', 3)
            try:
                exp = int(parts[1])
            except ValueError:
                continue
            if exp >= 0 and today is not None and today > exp and any(r['text'] == parts[3].strip() and r['text'] not in {t for _, _, t in expected} for r in rows):
                bad.append(('expired shown', value, today))
    if [r['priority'] for r in rows] != sorted((r['priority'] for r in rows), reverse=True):
        bad.append(('order', rows))
    if any(not isinstance(r['text'], str) or not r['text'] or not isinstance(r['day'], int) for r in rows):
        bad.append(('shape', rows))
    memory.facts_text(memory.empty(), rows, None if today is None else today + 1, 'Player', 'Lydia', rng.choice([0, 1, 90, 200, 10 ** 6]))
check('game facts: malformed ones never raise', not errors, errors[:3])
check('game facts: every valid unexpired fact kept, expired ones dropped, highest priority first', not bad, bad[:3])
check('a fact expires the day after its expiry day', [r['text'] for r in lw_state.game_facts({'fact_a': '1|10|1|seen'}, 10)] == ['seen']
      and lw_state.game_facts({'fact_a': '1|10|1|seen'}, 11) == [] and lw_state.game_facts({'fact_a': '1|10|1|seen'}, None) != [])

npc_dir = Path(lw_state.DATA_DIR) / 'npc'
npc_dir.mkdir(parents=True, exist_ok=True)
NPC_FILES = [b'', b'{', b'null', b'[]', b'"x"', b'{"int": [1, 2]}', b'{"string": "x"}', b'{"int": {"close": "yes"}, "string": {"name": 5}}',
             b'[' * 100000, b'{"string": {"name": "S\xf3ra"}}', bytes(range(256)), b'{"int": null, "float": {"a": 1e999}}',
             json.dumps({'string': {'name': 'x' * 200000, 'fact_a': '1|2|3|' + 'y' * 100000}}).encode()]
errors = []
for i, raw in enumerate(NPC_FILES):
    (npc_dir / f'00000{i:03X}.json').write_bytes(raw)
    (Path(lw_state.DATA_DIR) / 'conversation.json').write_bytes(raw)
    try:
        npc = lw_state.load_npc(f'00000{i:03X}')
        assert isinstance(npc, dict)
        lw_state.game_facts(npc, 5)
        assert lw_state.load_today() is None or isinstance(lw_state.load_today(), int)
        assert isinstance(lw_state.load_conversation(), list) and isinstance(lw_state.load_player_name(), str)
        assert isinstance(lw_state.load_world(), dict) and isinstance(lw_state.load_banter(), dict)
        lw_state.jobs_text(lw_state.load_conversation())
    except Exception as e:
        errors.append(f'{i}: {type(e).__name__}: {e}')
check('npc and channel files with wrong types or broken bytes read as empty, never raise', not errors, errors[:3])
conv = {'int': {'day': True}, 'stringList': {'speakers': ['0001A67B', 5, None, '../world', 'ABC\n', 'fffffffff', '00000000']}}
(Path(lw_state.DATA_DIR) / 'conversation.json').write_text(json.dumps(conv), encoding='utf-8')
ids = [s['base_id'] for s in lw_state.load_conversation()]
check('speaker list: only real base ids, no path tricks or line breaks', ids == ['0001A67B', '5', '00000000'], ids)
check('today: true is not a day', lw_state.load_today() is None)
for value, want in ((-1, None), (0, 0), (10 ** 30, 10 ** 30), (1.5, None), ('3', None)):
    (Path(lw_state.DATA_DIR) / 'conversation.json').write_text(json.dumps({'int': {'day': value}}), encoding='utf-8')
    check(f'today from {value!r}', lw_state.load_today() == want, lw_state.load_today())
check('regression: a base id with a line break is refused', not lw_state.BASE_ID.match('0001A67B\n'))

overrides_path = os.path.join(TOP, 'overrides.json')
errors = []
for raw in (b'', b'[]', b'null', b'{"Lydia": 5}', b'{"memory_budget": true}', b'{"a":' * 50000, '﻿{"Lydia": {}}'.encode('utf-8'), bytes(range(256))):
    Path(overrides_path).write_bytes(raw)
    try:
        assert isinstance(REAL_OVERRIDES(overrides_path), dict)
        assert set(REAL_SETTINGS(overrides_path)) == set(settings.DEFAULTS)
    except Exception as e:
        errors.append(f'{raw[:20]!r}: {type(e).__name__}: {e}')
check('regression: settings and profile overrides that are broken or deeply nested fall back, never raise', not errors, errors[:3])


# ======================= 4. limits and token budgets =======================
HEAD = memory.tokens('Below is a summary of past events:\n')
def marker(name):
    return memory.tokens(f"[This is the beginning of {name}'s memory. Only {name} knows what is in this block; the others here learn it "
                         f"only if {name} says it aloud.]\n\n[This is the end of {name}'s memory]") + 1

def memory_bound(chars, store, budget, budget_for=None):
    """The most memory_text may give: per NPC their facts share and memory share, plus the fixed wrapper text."""
    n = max(1, len(chars))
    total = HEAD
    for c in chars:
        mem = store.load(c.name, c.ref_id)
        b = min(budget_for(c) if budget_for else budget, budget)
        if b >= budget:
            b += memory.long_known_bonus(mem, budget)
        total += max(memory.FACT_TOKENS // n, memory.MIN_GROUP_FACT_TOKENS) + 1 + max(b // n, 0) + 2 + (marker(c.name) if n > 1 else 0)
    return total

store = memory.MemoryStore(folder('conv2'), 'Player1')
pool = [Char(f'Person {i}', f'{i:06X}') for i in range(40)]
for i, c in enumerate(pool):
    mem = memory.clean(rmemory_file()) if i % 4 else memory.empty()
    mem['recent'] += [{'day': d, 'hour': 9, 'text': f'Day {d}: ' + 'a long talk about everything ' * rng.randint(1, 30)} for d in range(rng.choice([0, 1, 30]))]
    mem['talks'] = rng.choice([0, 19, 20, 500])
    mem['feeling'] = rng.choice(['', 'warm', 'warm ' * 5000])
    memory.add_promises(mem, json.dumps({'promises': [{'text': f'Errand {k} for the jarl of the hold', 'due_in_days': k} for k in range(12)]}), 3)
    store.save(c.name, c.ref_id, mem)
facts = lambda c: [{'day': 1, 'priority': rng.randint(1, 3), 'text': 'You healed me ' + 'x' * rng.randint(0, 300)} for _ in range(8)]
bad, errors = [], []
for i in range(120):
    chars = rng.sample(pool, rng.choice([0, 1, 1, 2, 3, 7, 40]))
    budget = rng.choice([0, 1, 2, 20, 90, 400, 1500, 1999, 2000, 10 ** 6, -5])
    budget_for = rng.choice([None, lambda c: 400, lambda c: 0, lambda c: 10 ** 9, lambda c: -1])
    ctx = {'characters': chars, 'world_id': 'Player1', 'today': rng.choice([None, -1, 0, 3, 40, 10 ** 9]), 'player': 'Player',
           'facts_for': facts, 'profile_overrides': {c.name: rng.choice([rvalue(1), {ch: 3 for ch in memory.CHANNELS}]) for c in chars[:2]},
           'profile_seen': lambda c, p: None}
    try:
        out = memory.memory_text('stock', ctx, store, budget, budget_for)
    except Exception as e:
        errors.append(f'{type(e).__name__}: {e}')
        continue
    if not chars and out != 'stock':
        bad.append(('no NPC', out[:80]))
    if out != 'stock' and memory.tokens(out) > memory_bound(chars, store, budget, budget_for):
        bad.append((len(chars), budget, memory.tokens(out), memory_bound(chars, store, budget, budget_for)))
check('memory text: 0, 1 and 40 NPCs, every budget and day edge, never raises', not errors, errors[:3])
check('memory text: each NPC stays inside their memory share plus their facts share', not bad, bad[:3])
for budget in (0, 1, 2, 3, 50):
    out = memory.facts_text(store.load('Person 1', '000001'), facts(None), 5, 'Player', 'Person 1', budget)
    check(f'facts within a budget of {budget}', memory.tokens(out) <= budget + 1, (memory.tokens(out), out[:100]))
check('regression: a hand-edited essay of a feeling stays inside the budget',
      memory.tokens(memory.render(dict(memory.empty(), feeling='warm ' * 5000), 100)) <= 100)
check('empty memory, no facts: Mantella text kept', memory.memory_text('stock', {'characters': [Char('Nobody', '0000AA')], 'world_id': 'Player1'}, store) == 'stock')
huge = dict(memory.empty(), recent=[{'day': d, 'hour': 9, 'text': 'x' * 1200} for d in range(5000)], long_term={'earlier': 'y' * 100000})
t0 = time.perf_counter()
out = memory.render(huge, 1500)
check('a huge memory renders inside the budget, quickly', memory.tokens(out) <= 1500 and time.perf_counter() - t0 < 1, (memory.tokens(out), time.perf_counter() - t0))


# ======================= 5. the hooks, as Mantella calls them =======================
conv_dir = folder('conv3')
GAME = Game(conv_dir)
def write_npc(base_id, name, ref_id, **values):
    ints = {k: v for k, v in values.items() if isinstance(v, int)}
    strings = {'name': name, 'ref_id': ref_id, **{k: v for k, v in values.items() if isinstance(v, str)}}
    (Path(lw_state.DATA_DIR) / 'npc').mkdir(parents=True, exist_ok=True)
    (Path(lw_state.DATA_DIR) / 'npc' / f'{base_id}.json').write_text(json.dumps({'int': ints, 'string': strings}), encoding='utf-8')
def write_conversation(base_ids, day=5, player='Player'):
    (Path(lw_state.DATA_DIR) / 'conversation.json').write_text(json.dumps(
        {'int': {'day': day}, 'string': {'player': player}, 'stringList': {'speakers': base_ids}}), encoding='utf-8')
def blocks(text):
    """{name: that NPC's block} from a group memory text."""
    out = {}
    for part in text.split("[This is the beginning of ")[1:]:
        out[part.split("'s memory.")[0]] = part
    return out

# the game writes all 8 hex digits of a reference; Mantella keeps the last 6 (a light plugin's FE id its last 3)
check('ref ids compared the way Mantella keeps them', living_world._ref('FE1DD821') == living_world._ref('000821')
      and living_world._ref('0A01A2B3') == living_world._ref('01A2B3') and living_world._ref('0xfe1dd821') == living_world._ref('000821')
      and living_world._ref(0xFE1DD821 - (1 << 32)) == living_world._ref('FE1DD821') and living_world._ref('00013482') == living_world._ref('013482'))
check('odd ref ids are no ref', [living_world._ref(v) for v in (None, '', 'zz', True, 1.5, [])] == [None] * 6)
write_npc('000AAAA1', 'Bandit', '0A012345', fact_a='-1|-1|3|First bandit fact')
write_npc('000AAAA2', 'Bandit', 'FE000999', fact_a='-1|-1|3|Second bandit fact')
write_conversation(['000AAAA1', '000AAAA2'])
OVERRIDES.clear()
OVERRIDES['Bandit 2'] = {'talk': 1, 'deeds': 1, 'care': 1, 'gifts': 1, 'physical': 3}
summ = FakeSummaries({}, '', GAME)
out = living_world._memory_text('stock', {'characters': [Char('Bandit', '012345'), Char('Bandit 2', '000999')], 'world_id': 'P1', 'summaries': summ})
got = blocks(out)
check('regression: same-named NPCs from mods and light plugins each get their own facts',
      'First bandit fact' in got.get('Bandit', '') and 'Second' not in got.get('Bandit', '') and 'Second bandit fact' in got.get('Bandit 2', ''), out[:600])
profiles = json.loads((Path(lw_state.DATA_DIR) / lw_state.PROFILES).read_text(encoding='utf-8'))['int']
check('regression: a profile goes to that NPC, not to one with the same name', profiles.get('000aaaa2_physical') == 3
      and not any(k.startswith('000aaaa1') for k in profiles), profiles)
OVERRIDES.clear()

# a stranger Mantella calls by a follower's name gets a stranger's budget, the follower (numbered) a close one's
write_npc('000BBBB1', 'Lydia', '000A2C94', close=1, follower=1)
write_npc('000BBBB2', 'Lydia', '0A022222', close=0)
write_conversation(['000BBBB1', '000BBBB2'])
lstore = memory.MemoryStore(conv_dir, 'P1')
for c in (Char('Lydia', '022222'), Char('Lydia 2', '0A2C94')):
    lstore.save(c.name, c.ref_id, dict(memory.empty(), recent=[{'day': d, 'hour': 9, 'text': f'{c.name} day {d} ' + 'z' * 200} for d in range(60)]))
out = living_world._memory_text('stock', {'characters': [Char('Lydia', '022222'), Char('Lydia 2', '0A2C94')], 'world_id': 'P1', 'summaries': summ})
got = blocks(out)
stranger_cap = settings.DEFAULTS['memory_budget_stranger'] // 2 + memory.MIN_GROUP_FACT_TOKENS + marker('Lydia') + 5
check('regression: closeness follows the same speaker as the facts, not the name',
      memory.tokens(got.get('Lydia', '')) <= stranger_cap < memory.tokens(got.get('Lydia 2', '')), (memory.tokens(got.get('Lydia', '')), memory.tokens(got.get('Lydia 2', ''))))

# one close NPC known for a long time: never past the hard cap, facts and a long feeling included
write_npc('000CCCC1', 'Serana', '0200A2C9', close=1, follower=1, **{f'fact_{k}': f'3|-1|{1 + k % 3}|Fact {k} ' + 'q' * 120 for k in range(30)})
write_conversation(['000CCCC1'], day=40)
sstore = memory.MemoryStore(conv_dir, 'P1')
big = dict(memory.empty(), talks=500, feeling='devoted ' * 3000, long_term={'earlier': 'e' * 9000},
           recent=[{'day': d, 'hour': 9, 'text': f'Day {d} ' + 'w' * 900} for d in range(30)])
memory.add_promises(big, json.dumps({'promises': [{'text': f'Promise number {k} to Serana', 'due_in_days': k} for k in range(10)]}), 30)
sstore.save('Serana', '00A2C9', big)
out = living_world._memory_text('stock', {'characters': [Char('Serana', '00A2C9')], 'world_id': 'P1', 'summaries': summ})
check('one close NPC stays under the hard cap of 2000 tokens', memory.HARD_CAP_TOKENS - 300 < memory.tokens(out) <= memory.HARD_CAP_TOKENS + HEAD + 2, memory.tokens(out))
check('and the facts come first, the memories still fit beside a long feeling', out.index('What you know for certain') < out.index('Day ') and out.count('[Day ') >= 5, out[:300])

def hook_ctx(chars, reply, timestamp, radiant=False, lines=None):
    lines = lines if lines is not None else [f'line {k}' for k in range(rng.choice([0, 1, 3, 8]))]
    threads = {c.name: Params(lines, chars) for c in chars}
    return {'messages': None, 'npcs_to_summarize': chars, 'npcs_in_conversation': People(rng.choice(['Player', None, 'Ann'])),
            'world_id': 'P1', 'is_reload': False, 'pending_shares': None, 'end_timestamp': timestamp, 'is_radiant': radiant,
            'summaries': FakeSummaries(threads, reply, GAME)}

errors = []
TIMES = [None, -1, -0.5, 0, 0.999, 3.5, 1e6, 1e12]
odd_cast = pool[:6] + [Char(n, f'{k:06X}') for k, n in enumerate(NAMES)]
for i in range(150):
    chars = rng.sample(odd_cast, rng.randint(1, 3))
    reply = rng.choice([lambda: rreply(tuple(c.name for c in chars)), lambda: RuntimeError('model down'), lambda: None])
    try:
        handled = living_world._summarize(hook_ctx(chars, reply, rng.choice(TIMES), rng.random() < 0.2))
        assert handled is True, handled
        events = [rng.choice([rstr(), 'Player equipped Iron Sword', f"Player: Hello?;\n {chars[0].name}: " + 'I remember the old days. ' * rng.choice([1, 40])])
                  for _ in range(rng.randint(0, 4))]
        ctx = {'player': rng.choice(['Player', '']), 'characters': chars, 'game_days': rng.choice(TIMES), 'world_id': 'P1',
               'summaries': FakeSummaries({}, reply, GAME)}
        result = living_world._dialogue_events(list(events), ctx)
        assert len(result) == len(events) and all(r == e or r.startswith(memory.COMPACTED) for r, e in zip(result, events)), result
        living_world._memory_text('stock', {'characters': chars, 'world_id': 'P1', 'summaries': summ})
    except Exception as e:
        errors.append(f'{type(e).__name__}: {e}')
check('summarize, dialogue and memory hooks never raise (odd names, days, replies and failing models)', not errors, errors[:3])
bad = []
for c in odd_cast:
    m = lstore.load(c.name, c.ref_id)
    if not valid_memory(m) or len(m['recent']) > memory.MAX_RECENT or len(m['long_term'].get('earlier', '')) > memory.EARLIER_CHARS \
            or len(memory.open_promises(m)) > memory.MAX_OPEN or any(len(e.get('text', '')) > memory.MAX_ENTRY_CHARS for e in m['recent']) \
            or len(m['feeling']) > memory.MAX_FEELING_CHARS:
        bad.append(c.name)
check('after the hooks every memory keeps its limits (30 entries, notes, 10 open promises, entry and feeling size)', not bad, bad)

# regression: a failing summary call for one group must not cost the others their memories
a, b = Char('Ann', '0000A1'), Char('Cid', '0000C1')
replies = iter([RuntimeError('model down')] * memory.SUMMARY_TRIES + [json.dumps({'memory': 'Cid and the player fished.'})])
ctx = hook_ctx([a, b], lambda: next(replies), 3.5)
ctx['summaries'].threads = {'Ann': Params([f'a{k}' for k in range(8)], [a]), 'Cid': Params([f'c{k}' for k in range(8)], [b])}
check('regression: one failed summary call does not stop the other groups', first_error(living_world._summarize, ctx) is None
      and [e['text'] for e in lstore.load('Cid', '0000C1')['recent']] == ['Cid and the player fished.'], lstore.load('Cid', '0000C1'))


# ======================= 6. the Memory tab =======================
ui_root = folder('ui')
ustore = memory.MemoryStore(os.path.join(ui_root, 'conversations'), 'Save1')
errors, bad = [], []
CELLS = [None, '', 'inf', '-inf', '1e999', 'nan', '3.7', '-0', 5, -1, 2.5, float('inf'), [1], {'a': 1}, 'Met at the inn.', '你好', 'x' * 5000]
def flaky_ask(prompt, text):
    if rng.random() < 0.2:
        raise RuntimeError('down')
    return rreply()
for i in range(200):
    current = memory.clean(rmemory_file())
    rows = [[rng.choice(CELLS) for _ in range(rng.randint(0, 5))] for _ in range(rng.randint(0, 6))]
    long_rows = [[rng.choice(CELLS) for _ in range(rng.randint(0, 3))] for _ in range(rng.randint(0, 4))]
    try:
        new = memory_ui.from_tables(current, rng.choice([None, '', ' warm ', 'x' * 500]), rows, long_rows)
        if any(not isinstance(e.get('day'), int) or not isinstance(e.get('hour'), int) or not str(e.get('text', '')).strip() for e in new['recent']):
            bad.append(new['recent'][:2])
        if any(new[k] != current[k] for k in ('facts', 'talks', 'profile', 'asked')):
            bad.append('lost facts, talks, profile or asked')
        memory_ui.status_text(current, 'Odd')
        memory_ui.memory_choices(current)
        memory_ui.to_tables(current)
        rows, _, _ = memory_ui.notes_to_rows(flaky_ask, 'Odd', 'Player', rng.choice(['', 'we met', rstr()]))
        if any(not isinstance(r[0], int) or not isinstance(r[1], int) or len(r[2]) > memory.MAX_ENTRY_CHARS for r in rows):
            bad.append(rows[:2])
    except Exception as e:
        errors.append(f'{type(e).__name__}: {e}')
check('memory tab: odd table cells, odd memories and model replies never raise', not errors, errors[:3])
check('memory tab: rows become valid memories, facts and the rest are kept', not bad, bad[:3])
check('regression: "inf" typed into a number cell is no date', memory_ui._num('inf') == -1 and memory_ui._num('1e999') == -1)
mem = dict(memory.empty(), feeling='warm', long_term={'earlier': 'Old.', 'Helgen': 'Fled.'},
           recent=[{'day': d, 'hour': 9, 'text': f'Memory {d}'} for d in range(5)], facts=[{'text': 'Promise', 'status': 'open', 'day': 1, 'due_day': -1, 'by': ''}])
ustore.save('Ann', '0000A1', mem)
loaded = ustore.load('Ann', '0000A1')
f, r, l = memory_ui.to_tables(loaded)
check('tables round-trip without changing the memory', memory_ui.from_tables(loaded, f, r, l) == loaded)
backups = os.path.join(ui_root, 'removed')
for _ in range(5):
    memory_ui.delete_one(ustore, 'Ann', '0000A1', memory_ui.memory_choices(ustore.load('Ann', '0000A1'))[0], backups)
kept = set()
for root, _, files in os.walk(backups):
    for name in files:
        kept |= {e['text'] for e in json.loads(Path(root, name).read_text(encoding='utf-8'))['recent']}
check('regression: deletes in the same second each keep their own backup', kept == {f'Memory {d}' for d in range(5)}, (kept, os.listdir(backups)))
for odd in ('', '..', '.', 'a/b', 'C:x', '../Save1', None):
    check(f'purging an odd save name moves nothing: {odd!r}', memory_ui.purge_save(os.path.join(ui_root, 'conversations'), odd, backups) == 0)


# ======================= 7. the bug report =======================
versions = Path(folder('versions'))
(versions / 'a.json').write_text(json.dumps({'module': 'Hub', 'version': '1.0', 'nexus_id': 1}), encoding='utf-8')
(versions / 'b.json').write_text(json.dumps({'module': {'odd': 1}, 'version': '1.0', 'nexus_id': 2}), encoding='utf-8')
(versions / 'c.json').write_text('[' * 50000, encoding='utf-8')
report = Path(lw_state.DATA_DIR) / server_status.FILE
if report.exists():
    report.unlink()
check('regression: an odd version file does not stop the report', first_error(server_status.write, [], str(versions)) is None and report.exists())
handler = server_status.RecentWarnings(str(versions))
log = logging.getLogger('robust-status')
log.propagate = False
log.addHandler(handler)
errors = []
def warn_many(k):
    for j in range(40):
        try:
            log.warning(f'Living World: warning {k}-{j} ' + 'x' * rng.choice([0, 5000]))
            log.warning('Living World %s %s', 'one arg only')  # a broken record: the handler must not care
        except Exception as e:
            errors.append(e)
logging.raiseExceptions, raise_before = False, logging.raiseExceptions  # the broken record is the handler's to swallow
threads = [threading.Thread(target=warn_many, args=(k,)) for k in range(2)]
[t.start() for t in threads]
[t.join() for t in threads]
logging.raiseExceptions = raise_before
lines = json.loads(report.read_text(encoding='utf-8'))['stringList']['errors']
check('bug report: warnings from two threads never raise; last 10 kept, each short', not errors and len(lines) == server_status.MAX_LINES
      and all(len(x) <= server_status.MAX_CHARS for x in lines), (errors[:2], len(lines)))
log.removeHandler(handler)


# ======================= 8. threads and files replaced while read =======================
def run_threads(*targets):
    threads = [threading.Thread(target=t) for t in targets]
    [t.start() for t in threads]
    [t.join() for t in threads]

errors, empty_reads = [], []
lw_state.write_json('race.json', {'n': -1})
def writer(k):
    def run():
        for j in range(120):
            try:
                lw_state.write_json('race.json', {'n': j, 'by': k, 'pad': 'p' * 3000})
            except Exception as e:
                errors.append(f'{type(e).__name__}: {e}')
    return run
def reader():
    for j in range(240):
        if lw_state._read('race.json') == {}:
            empty_reads.append(j)
run_threads(writer(1), writer(2), reader)
check('regression: two threads writing one channel file never fail', not errors, errors[:3])
check('regression: a reader never sees a missing or half-written channel file', not empty_reads, len(empty_reads))
check('no temp files left in the channel folder', not list(Path(lw_state.DATA_DIR).glob('*.tmp')), list(Path(lw_state.DATA_DIR).glob('*.tmp')))

errors = []
def profiles_from(k):
    def run():
        for j in range(80):
            try:
                lw_state.write_profile(f'00{k:02X}{j:04X}', {'talk': 2, 'physical': 3})
            except Exception as e:
                errors.append(f'{type(e).__name__}: {e}')
    return run
run_threads(profiles_from(1), profiles_from(2), reader)
values = lw_state._read(lw_state.PROFILES).get('int', {})
check('regression: two threads writing profiles lose no NPC', not errors and all(f'00{k:02x}{j:04x}_talk' in values for k in (1, 2) for j in range(80)),
      (errors[:2], len(values)))

rstore = memory.MemoryStore(folder('conv4'), 'P1')
rstore.save('Race', '1', dict(memory.empty(), feeling='start'))
errors, odd_loads = [], []
def saver(k):
    def run():
        for j in range(80):
            try:
                rstore.save('Race', '1', dict(memory.empty(), feeling=f'{k}-{j}', recent=[{'day': 1, 'hour': 1, 'text': 'p' * 2000}]))
            except Exception as e:
                errors.append(f'{type(e).__name__}: {e}')
    return run
def loader():
    for j in range(160):
        try:
            if not rstore.load('Race', '1')['feeling']:
                odd_loads.append(j)
        except Exception as e:
            errors.append(f'{type(e).__name__}: {e}')
run_threads(saver(1), saver(2), loader)
check('regression: two threads saving one memory and a reader never fail', not errors, errors[:3])
check('regression: a memory being saved is never read as empty (or set aside as unreadable)',
      not odd_loads and not list(Path(rstore.root).glob('*.unreadable*')), (len(odd_loads), [p.name for p in Path(rstore.root).glob('*')][:5]))
check('no temp files left in the memory folder', not list(Path(rstore.root).glob('*.tmp')))

# the game (or the Memory tab) holding a file open while it is replaced
for label, path, write in (('channel file', Path(lw_state.DATA_DIR) / 'held.json', lambda: lw_state.write_json('held.json', {'new': 1})),
                           ('memory file', rstore._path('Held', '1'), lambda: rstore.save('Held', '1', dict(memory.empty(), feeling='new')))):
    if label == 'channel file':
        lw_state.write_json('held.json', {'old': 1})
    else:
        rstore.save('Held', '1', dict(memory.empty(), feeling='old'))
    result = []
    with open(path, 'rb'):
        t = threading.Thread(target=lambda: result.append(first_error(write)))
        t.start()
        time.sleep(0.2)
    t.join()
    check(f'regression: a {label} held open by a reader is replaced once it is closed', result == [None] and b'new' in path.read_bytes(), result)


# ======================= 9. a thousand random cycles =======================
cstore = memory.MemoryStore(conv_dir, 'P1')
cast = [Char(f'Cycle {i}', f'{0x100 + i:06X}') for i in range(8)]
for i, c in enumerate(cast):
    write_npc(f'0010{i:04X}', c.name, f'FF{0x100 + i:06X}', close=i % 2, fact_x=f'{i}|{i + 50}|{1 + i % 3}|Cycle fact {i}')
errors = []
t0 = time.perf_counter()
for i in range(1000):
    chars = rng.sample(cast, rng.randint(1, 3))
    write_conversation([f'0010{cast.index(c):04X}' for c in chars], day=rng.choice([None, i // 10]))
    kind = rng.random()
    try:
        if kind < 0.35:
            living_world._summarize(hook_ctx(chars, lambda: rreply(tuple(c.name for c in chars)), i / 10 + 0.5))
        elif kind < 0.5:
            living_world._dialogue_events(["Player: Well?;\n " + chars[0].name + ': ' + 'Long story. ' * rng.choice([5, 80])],
                                          {'player': 'Player', 'characters': chars, 'game_days': i / 10, 'world_id': 'P1',
                                           'summaries': FakeSummaries({}, lambda: rreply((chars[0].name,)), GAME)})
        elif kind < 0.55:
            c = chars[0]
            m = cstore.load(c.name, c.ref_id)
            f, r, l = memory_ui.to_tables(m)
            cstore.save(c.name, c.ref_id, memory_ui.from_tables(m, f, r + [[i // 10, 12, f'Added by hand {i}']], l))
        else:
            out = living_world._memory_text('stock', {'characters': chars, 'world_id': 'P1', 'summaries': summ})
            if len(chars) == 1 and memory.tokens(out) > memory.HARD_CAP_TOKENS + HEAD + 2:
                errors.append(f'over the cap: {memory.tokens(out)}')
    except Exception as e:
        errors.append(f'{i}: {type(e).__name__}: {e}')
elapsed = time.perf_counter() - t0
print(f'1000 cycles in {elapsed:.1f} s')
check('1000 random cycles: no hook raises, no NPC over the cap', not errors, errors[:3])
check('1000 random cycles finish in a few seconds', elapsed < 15, f'{elapsed:.1f} s')
for c in cast:  # rows added by hand in the Memory tab fold away at the next talk
    living_world._summarize(hook_ctx([c], json.dumps({'memory': 'One more talk.'}), 200.5, lines=[f'l{k}' for k in range(8)]))
bad = [(c.name, len(memory.open_promises(m)), len(m['recent'])) for c in cast for m in [cstore.load(c.name, c.ref_id)]
       if len(memory.open_promises(m)) > memory.MAX_OPEN or len(m['recent']) > memory.MAX_RECENT]
check('after 1000 cycles and one more talk: open promises <= 10 and recent entries <= 30 for everyone', not bad, bad)


# ======================= the end =======================
builtins.open = io.open = _real['open']
os.replace, os.rename, os.mkdir, os.remove = _real['replace'], _real['rename'], _real['mkdir'], _real['remove']
check('nothing was written outside the temp folder', not OUTSIDE, sorted(set(OUTSIDE))[:5])
shutil.rmtree(TOP, ignore_errors=True)
print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
