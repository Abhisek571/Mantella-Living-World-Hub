"""Offline tests for kept, weighted and recalled memories (archive.py, embed.py and their use in memory.py and
memory_ui.py): the archive, importance from the summary call, fading, recall by meaning or words, hidden memories, the
chatter filter, the follower diary and the upgrade of old memory files.
Run with a Python 3.11: test_memory_recall.py <repo server dir> [folder with the memory search model files]
With the second argument (and onnxruntime, numpy and tokenizers installed) the real model is tested too."""
import hashlib, io, json, os, sqlite3, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import archive, embed, memory, memory_ui
memory.SUMMARY_RETRY_SECONDS = 0
embed.use(None)  # keyword search unless a test puts an engine in place

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


class Char:
    def __init__(self, name, ref_id, bio='A person.'):
        self.name, self.ref_id, self.bio = name, ref_id, bio

class Thread:
    def __init__(self, lines, greeting=None):
        self.lines, self.greeting = lines, greeting
    def get_talk_only(self, include_system_generated_messages=False):
        return ([self.greeting] if include_system_generated_messages and self.greeting else []) + list(self.lines)
    def transform_to_dict_representation(self, messages):
        return '\n'.join(str(m) for m in messages if not getattr(m, 'is_system_generated_message', False))
    def __len__(self):
        return len(self.lines)

class Greeting:
    is_system_generated_message = True
    def __init__(self, events):
        self._UserMessage__ingame_events = events

class Params:
    def __init__(self, lines, chars, greeting=None):
        self.messages, self.characters = Thread(lines, greeting), chars

class People:
    def get_player_name(self):
        return 'Player'

class FakeSummaries:
    def __init__(self, threads, reply):
        self.threads, self.reply, self.calls = threads, reply, []
    def get_threads_for_summarization(self, messages, npcs):
        return self.threads
    def group_shared_threads(self, threads):
        groups = {}
        for name, p in threads.items():
            groups.setdefault(tuple(p.messages.lines), []).append(name)
        return list(groups.values())
    def summarize_conversation(self, text, prompt):
        self.calls.append((text, prompt))
        return self.reply(text, prompt) if callable(self.reply) else self.reply


class TopicEngine:
    """A stand-in for the sentence model: one direction per topic word, so 'meaning' is predictable."""
    TOPICS = [('dragon', 'wyrm', 'claw'), ('ring', 'jewel', 'gift'), ('bread', 'food', 'sweetroll'), ('sword', 'blade', 'steel')]
    def __init__(self):
        import numpy
        self.np = numpy
        self.calls = 0
    def embed(self, texts):
        np = self.np
        self.calls += 1
        out = []
        for t in texts:
            v = np.array([sum(t.lower().count(w) for w in words) for words in self.TOPICS] + [0.05], dtype=np.float32)
            v = np.pad(v, (0, embed.DIM - len(v)))
            out.append(v / np.linalg.norm(v))
        return out


try:
    import numpy  # only the meaning tests need it
except ImportError:
    numpy = None

lydia = Char('Lydia', '0A2C94')
long_talk = [f'line {i}' for i in range(8)]


def summary(text, **meta):
    return json.dumps({'memory': text, 'feelings': {'Lydia': 'Loyal.'}, **meta})


def talk(store, reply, when, chars=(lydia,), lines=long_talk, greeting=None, **extra):
    summaries = FakeSummaries({c.name: Params(lines, list(chars), greeting) for c in chars}, reply)
    ctx = {'messages': None, 'npcs_to_summarize': list(chars), 'npcs_in_conversation': People(), 'world_id': 'P1',
           'is_reload': False, 'end_timestamp': when, 'is_radiant': False, 'summaries': summaries, **extra}
    memory.summarize(ctx, store)
    return summaries


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / 'conversations'
    store = memory.MemoryStore(str(root), 'P1')

    # importance, emotion, type and tags come from the same summary call
    s = talk(store, summary('Player gave me a silver ring and promised to marry me.', importance=0.9, emotion='Joy', type='joy',
                            tags=['ring', 'Player', 'ring', 7, None], promises=[{'text': 'marry Lydia', 'by': 'Player', 'due_in_days': None}]), 3.5)
    check('still one model call per talk', len(s.calls) == 1, len(s.calls))
    check('the prompt asks for importance, emotion, type and tags', all(w in s.calls[0][1] for w in ('"importance"', '"emotion"', '"type"', '"tags"')))
    entry = store.load('Lydia', '0A2C94')['recent'][-1]
    check('meta kept on the entry', entry.get('importance') == 0.9 and entry.get('emotion') == 'joy' and entry.get('type') == 'joy'
          and entry.get('tags') == ['ring', 'player', '7'], entry)
    check('the promise it made is noted on it', entry.get('promises') == ['marry Lydia'], entry)
    check('it was their first talk: first_meeting and promise flags', entry.get('flags') == ['first_meeting', 'promise'], entry)
    # below it plays an ordinary memory that folds out of the list (a first meeting would stay in it)
    _m = store.load('Lydia', '0A2C94'); _m['recent'][-1].pop('flags', None); store.save('Lydia', '0A2C94', _m)
    rows = store.archive_for('Lydia', '0A2C94').rows()
    check('saved into the archive too', len(rows) == 1 and rows[0]['importance'] == 0.9 and rows[0]['type'] == 'joy' and rows[0]['tags'] == ['ring', 'player', '7'], rows)
    check('archive file sits next to the memory file', store.archive_path('Lydia', '0A2C94').name == 'Lydia - 0A2C94.archive.sqlite')

    # parse_meta never trusts the reply
    check('meta: 0-10 rating scaled', memory.parse_meta('{"importance": 8}') == {'importance': 0.8})
    check('meta: text number read', memory.parse_meta('{"importance": "0.3"}') == {'importance': 0.3})
    check('meta: junk dropped', memory.parse_meta('{"importance": true, "emotion": "a whole long sentence of feelings here", "type": "diary", "tags": "x"}') == {})
    check('meta: out of range clamped', memory.parse_meta('{"importance": 50}')['importance'] == 1.0 and memory.parse_meta('{"importance": -2}')['importance'] == 0.0)
    check('meta: not JSON at all', memory.parse_meta('Lydia remembers the ring.') == {})
    check('meta: inside a code fence', memory.parse_meta('```json\n{"importance": 0.4, "type": "Trauma"}\n```') == {'importance': 0.4, 'type': 'trauma'})
    check('meta: NaN and Infinity refused', memory.parse_meta('{"importance": NaN}') == {} and memory.parse_meta('{"importance": Infinity}') == {})

    # a short talk is small talk
    talk(store, 'unused', 3.75, lines=['Player: Hi.', 'Lydia: Hello.'])
    check('short talk gets low importance', store.load('Lydia', '0A2C94')['recent'][-1].get('importance') == memory.SHORT_IMPORTANCE)

    # keep every memory: folding no longer loses details
    for d in range(4, 40):
        talk(store, summary(f'On a quiet day we walked past farm number {d}.', importance=0.2), d + 0.5)
    mem = store.load('Lydia', '0A2C94')
    kept = store.archive_for('Lydia', '0A2C94').rows()
    check('recent list still folds', len(mem['recent']) <= memory.MAX_RECENT and mem['long_term'].get('earlier'), len(mem['recent']))
    check('the archive keeps every memory', len(kept) == 38, len(kept))
    check('the ring memory is out of recent but kept', not any('silver ring' in memory.entry_text(e, store) for e in mem['recent'])
          and any('silver ring' in r['text'] for r in kept))

    # fading
    r = archive.retention
    check('fresh memories are whole', r(0.1, 0) == 1.0 and r(0.9, None) == 1.0)
    check('small talk fades within a week', r(0.1, 7) < 0.25, r(0.1, 7))
    check('important memories fade slowly', r(0.9, 30) > 0.8 and r(0.9, 30) > r(0.5, 30) > r(0.1, 30))
    check('a life-changing memory never quite goes', r(1.0, 10000) >= 0.4)
    check('an open promise never fades', r(0.1, 10000, promise_open=True) == 1.0)
    check('remembering again counts half', archive.age(10, 30, recalled_day=20) == 15 and archive.age(10, 30) == 20 and archive.age(-1, 30) is None)

    # recall by words (no model): the old ring memory comes back when the talk is about the ring
    mem['recent'].append({'day': 41, 'hour': 9, 'text': 'Player asked whether I still wear the silver ring.'})
    back = memory.recall(store, 'Lydia', '0A2C94', mem, memory.recall_query(mem, ['Player']), today=42)
    check('recalled by shared words', back and 'silver ring' in back[0]['text'], back)
    check('unrelated talk recalls nothing', memory.recall(store, 'Lydia', '0A2C94', mem, 'mead hall ale brawl', today=42) == [])
    check('a memory from a later day is not recalled (an earlier save was loaded)', memory.recall(store, 'Lydia', '0A2C94', mem, 'silver ring', today=2) == [])
    recalled_day = {row['id']: row['recalled_day'] for row in store.archive_for('Lydia', '0A2C94').rows()}
    check('a recalled memory counts as remembered again', recalled_day[back[0]['id']] == 42, recalled_day.get(back[0]['id']))
    text = memory.render(mem, 1500, store, 42, back)
    check('recalled memory is in the prompt, before the recent ones', 'silver ring and promised' in text
          and text.index('silver ring and promised') < text.index('farm number 39'), text[-400:])
    small = memory.render(mem, 120, store, 42, back * 10)
    check('recall stays inside its share of the budget', memory.tokens(small) <= 120, memory.tokens(small))

    # older recent entries compete by strength: an important one outlives newer small talk
    ranked = dict(memory.empty(), recent=[{'day': 1, 'hour': 9, 'text': 'The dragon burned my village.', 'importance': 1.0}]
                  + [{'day': 20 + i, 'hour': 9, 'text': f'Small talk number {i} about the weather and nothing else.', 'importance': 0.1} for i in range(12)])
    out = memory.render(ranked, 150, None, 40)
    check('an important old memory beats newer small talk', 'dragon burned' in out and 'Small talk number 11' in out and 'Small talk number 0 ' not in out, out)
    even = dict(memory.empty(), recent=[{'day': i, 'hour': 9, 'text': f'Talk {i} ' + 'x' * 80} for i in range(12)])
    check('equal importance: still newest first', 'Talk 11' in memory.render(even, 120) and 'Talk 0 ' not in memory.render(even, 120))
    promised = dict(memory.empty(), facts=[{'text': 'bring Lydia a sword', 'status': 'open', 'day': 1, 'due_day': -1, 'by': 'Player'}],
                    recent=[{'day': 1, 'hour': 9, 'text': 'Player promised me a sword.', 'importance': 0.1, 'promises': ['bring Lydia a sword']}]
                    + [{'day': 30 + i, 'hour': 9, 'text': f'Walked on, day {i}, ' + 'y' * 60, 'importance': 0.3} for i in range(10)])
    check('a memory with an open promise does not fade', 'promised me a sword' in memory.render(promised, 160, None, 300))

    # meaning search with a stand-in model
    if numpy is not None:
        engine = TopicEngine()
        embed.use(engine)
        talk(store, summary('We fought a great wyrm on the mountain together.', importance=0.8), 41.5)
        for d in range(42, 75):
            talk(store, summary(f'Ordinary errand {d} in town.', importance=0.2), d + 0.5)
        mem = store.load('Lydia', '0A2C94')
        rows = store.archive_for('Lydia', '0A2C94').rows()
        check('new memories get their numbers when saved', all(r['embedding'] and r['model'] == embed.MODEL_ID for r in rows), [r['text'] for r in rows if not r['embedding']][:3])
        back = memory.recall(store, 'Lydia', '0A2C94', mem, 'the dragon claw', today=80)
        check('recalled by meaning, no shared words', back and 'wyrm' in back[0]['text'], [b['text'] for b in back])
        check('meaning search finds both the ring and its jewel', any('silver ring' in b['text'] for b in
              memory.recall(store, 'Lydia', '0A2C94', mem, 'a jewel as a gift', today=80)))
        embed.use(None)
        check('without the model the same search falls back to words', memory.recall(store, 'Lydia', '0A2C94', mem, 'the dragon claw', today=80) == [])
        embed.use(engine)
        # rows stored without numbers (model not ready then) get them later
        db = sqlite3.connect(store.archive_path('Lydia', '0A2C94'))
        with db:
            db.execute('UPDATE memories SET embedding = NULL, model = NULL')
        db.close()
        store.save('Lydia', '0A2C94', mem)
        missing = [r for r in store.archive_for('Lydia', '0A2C94').rows() if not r['embedding']]
        check('saves fill in missing numbers a batch at a time', 0 < len(missing) < len(rows), len(missing))
        embed.use(None)
    else:
        print('SKIP meaning search with a stand-in model (no numpy here)')

    # hidden memories
    hstore = memory.MemoryStore(str(root), 'P2')
    hmem = dict(memory.empty(), recent=[{'day': d, 'hour': 9, 'text': t, 'witnesses': ['Lydia']} for d, t in
                                        ((1, 'Player stole the Jarl golden crown.'), (2, 'We bought bread at the market.'), (3, 'Player sang a song by the fire.'))])
    hmem['long_term']['earlier'] = '[Day 0, 9 in the morning] Player robbed the Jarl treasury vault.\n[Day 0, 10 in the morning] We met at Dragonsreach.'
    hstore.save('Lydia', '0A2C94', hmem)
    hstore.archive_for('Lydia', '0A2C94').add([({'day': 0, 'hour': 9, 'text': 'Player robbed the Jarl treasury vault.'}, 'Player robbed the Jarl treasury vault.')])
    gone = memory.hide_matching(hstore, 'Lydia', '0A2C94', 'the Jarl crown theft', limit=1, by='Absolute Command', note='Forget the crown', day=5)
    check('hide_matching hides the closest one', len(gone) == 1 and 'golden crown' in gone[0]['text'] and set(gone[0]) == {'id', 'day', 'hour', 'text'}, gone)
    hmem = hstore.load('Lydia', '0A2C94')
    check('hidden mark on the entry', hmem['recent'][0].get('hidden') == {'day': 5, 'by': 'Absolute Command', 'note': 'Forget the crown'}, hmem['recent'][0])
    check('a hidden memory is never in the prompt', 'golden crown' not in memory.render(hmem, 1500))
    check('nothing hidden when nothing fits', memory.hide_matching(hstore, 'Lydia', '0A2C94', 'zebra unicorn xylophone') == [])
    check('a hidden memory is never recalled', memory.recall(hstore, 'Lydia', '0A2C94', dict(hmem, recent=[]), 'golden crown Jarl', today=9) == []
          or all('golden crown' not in r['text'] for r in memory.recall(hstore, 'Lydia', '0A2C94', dict(hmem, recent=[]), 'golden crown Jarl', today=9)))
    gone = memory.hide_matching(hstore, 'Lydia', '0A2C94', 'treasury vault robbed', limit=1, by='Absolute Command')
    hmem = hstore.load('Lydia', '0A2C94')
    check('an archived memory can be hidden, and its line leaves earlier', gone and 'treasury' in gone[0]['text']
          and 'treasury' not in hmem['long_term']['earlier'] and 'Dragonsreach' in hmem['long_term']['earlier'], hmem['long_term'])
    listed = memory.list_hidden(hstore, 'Lydia', '0A2C94')
    check('list_hidden lists both, with their marks', len(listed) == 2 and all(h['hidden'].get('by') == 'Absolute Command' for h in listed), listed)
    stale = dict(hmem, recent=[{k: v for k, v in e.items() if k != 'hidden'} for e in hmem['recent']])
    hstore.save('Lydia', '0A2C94', stale)  # a copy loaded before the hide is saved after it
    check('a save from an older copy does not unhide', hstore.load('Lydia', '0A2C94')['recent'][0].get('hidden'))
    many = dict(hstore.load('Lydia', '0A2C94'))
    many['recent'] = many['recent'] + [{'day': 10 + i, 'hour': 9, 'text': f'Later day {i}.'} for i in range(memory.MAX_RECENT)]
    folded = memory.fold_old(many, hstore)
    check('a hidden memory is never folded into earlier', 'golden crown' not in folded['long_term'].get('earlier', '')
          and len([e for e in folded['recent'] if not e.get('hidden')]) <= memory.MAX_RECENT)
    many = dict(memory.empty(), recent=[{'day': i, 'hour': 9, 'text': f'h{i}', 'hidden': {'day': 1, 'by': '', 'note': ''}} for i in range(40)])
    check('only hidden entries: folding stops', len(memory.fold_old(many)['recent']) == 40)
    crown = next(h for h in listed if 'golden crown' in h['text'])
    check('unhide brings it back', memory.unhide(hstore, 'Lydia', '0A2C94', crown['id']) and 'golden crown' in memory.render(hstore.load('Lydia', '0A2C94'), 1500))
    check('unhide twice says nothing was hidden', not memory.unhide(hstore, 'Lydia', '0A2C94', crown['id']))
    check('facts: the last talk date ignores hidden talks', 'last talked' not in memory.facts_text(
        dict(memory.empty(), recent=[{'day': 3, 'hour': 9, 'text': 'x', 'hidden': {'day': 1}}]), [], 9, 'Player', 'Lydia'))

    # the memory page: hidden ones greyed out apart, never lost by a save, deleted ones leave the archive
    hmem = hstore.load('Lydia', '0A2C94')
    f, rows_table, l = memory_ui.to_tables(hmem)
    check('hidden memories stay out of the table', not any('treasury' in row[2] for row in rows_table))
    shown = memory.list_hidden(hstore, 'Lydia', '0A2C94')
    page = memory_ui.hidden_html(shown)
    check('hidden list is greyed out with who hid it', 'opacity' in page and 'Absolute Command' in page and 'treasury' in page)
    check('unhide list labels end with the id', all(c.rsplit('#', 1)[1] in {h['id'] for h in shown} for c in memory_ui.hidden_choices(shown)))
    check('status counts what is kept and hidden', 'hidden' in memory_ui.status_text(hmem, 'Lydia', *memory_ui.archive_counts(hstore, 'Lydia', '0A2C94')))
    check('hidden memories are not offered for deleting', not any('treasury' in c for c in memory_ui.memory_choices(hmem)))
    label = next(c for c in memory_ui.memory_choices(hmem) if 'bread' in c)
    memory_ui.delete_one(hstore, 'Lydia', '0A2C94', label, str(Path(tmp) / 'removed'))
    check('a deleted memory leaves the archive too', not any('bread' in r['text'] for r in hstore.archive_for('Lydia', '0A2C94').rows(hidden=None)))
    check('reset moves the archive with the memory file', memory_ui.reset_memory(hstore, 'Lydia', '0A2C94', str(Path(tmp) / 'removed'))
          and not hstore.archive_path('Lydia', '0A2C94').exists() and list((Path(tmp) / 'removed').rglob('*.archive.sqlite')))

    # chatter filter
    cstore = memory.MemoryStore(str(root), 'P3')
    bark = "Player: Hello.;\n Lydia: I used to be an adventurer like you, then I took an arrow in the knee."
    useful = "Player: Any work?;\n Lydia: Hod needs logs at the mill."
    out = memory.filter_chatter([bark + ' ' + useful], 'Player', cstore, 5)
    check('a stock bark goes, the useful line stays', 'adventurer' not in out[0] and 'Hod needs logs' in out[0], out)
    check('an event of only barks is empty', memory.filter_chatter([bark], 'Player', cstore, 5) == [''])
    greet = "Player: Hey.;\n Lydia: What do you need?"
    check('a bare greeting goes', memory.filter_chatter([greet], 'Player', cstore, 5) == [''])
    answer = "Player: Will you marry me?;\n Lydia: Yes."
    check('a short real answer stays', memory.filter_chatter([answer], 'Player', cstore, 5) == [answer])
    line = "Player: News?;\n Lydia: The Companions are hiring again in Jorrvaskr."
    for d in (6, 6, 7):
        first = memory.filter_chatter([line], 'Player', cstore, d)
    check('heard on two days: still kept (same day counted once)', first == [line], first)
    check('heard on a third day: chatter now', memory.filter_chatter([line], 'Player', cstore, 8) == [''])
    check('the count table is per save', json.loads(Path(memory.chatter_path(cstore)).read_text(encoding='utf-8')))
    check('the same exchange twice in one talk is kept once', memory.filter_chatter([useful + ' ' + useful], 'Player', cstore, 9)[0].count('Hod needs logs') == 1)
    s = talk(cstore, 'unused', 10.5, lines=[], greeting=Greeting([bark, 'The location is now Whiterun']))
    check('a talk of only barks leaves no memory', not cstore.load('Lydia', '0A2C94')['recent'])
    s = talk(cstore, 'unused', 10.6, lines=[], greeting=Greeting([bark]), chatter_filter=False)
    check('with the filter off barks are kept as before', 'adventurer' in ' '.join(e['text'] for e in cstore.load('Lydia', '0A2C94')['recent']))
    long_bark = ' '.join([bark] * 12) + ' ' + useful
    compact = memory.compact_dialogue([long_bark], {'player': 'Player', 'is_first': True, 'characters': [lydia], 'game_days': 11.5,
                                                    'summaries': FakeSummaries({}, summary('Lydia told me about the logs.'))}, cstore)
    check('normal-menu dialogue that is mostly chatter is not summarized, the event stays', compact == [long_bark], compact)

    # follower diary: off unless asked for, at most one a day, kept in the archive
    dstore = memory.MemoryStore(str(root), 'P4')
    s = talk(dstore, summary('We hunted deer near Riverwood.'), 2.5)
    s = talk(dstore, summary('We sold the pelts in Whiterun.'), 3.5)
    check('diary off by default: one call per talk', len(s.calls) == 1)
    s = talk(dstore, lambda text, prompt: 'Hunted with my Thane and sold the pelts.' if 'diary' in prompt else summary('We rested at the inn.'), 4.5,
             diary_for=lambda c: True)
    diary = [r for r in dstore.archive_for('Lydia', '0A2C94').rows() if r['type'] == 'diary']
    check('diary on: one extra call, one diary memory for the day before', len(s.calls) == 2 and len(diary) == 1 and diary[0]['day'] == 3, (len(s.calls), diary))
    check('the diary day is remembered', dstore.load('Lydia', '0A2C94').get('diary_day') == 3)
    s = talk(dstore, lambda text, prompt: 'Again.' if 'diary' in prompt else summary('Another talk the same day.'), 4.7, diary_for=lambda c: True)
    check('never two diary entries for one day', len(s.calls) == 1, len(s.calls))

    # upgrade: an old memory file keeps working; a backup is made first; old entries get the default importance
    ustore = memory.MemoryStore(str(root), 'P5')
    old_file = ustore._path('Mjoll', 'FE1DD821')
    old_file.parent.mkdir(parents=True, exist_ok=True)
    old = {'recent': [{'day': 2, 'hour': 9, 'text': 'Player helped me find Grimsever.'}], 'long_term': {'earlier': 'We met in Riften.'}, 'feeling': 'Proud.'}
    old_file.write_text(json.dumps(old), encoding='utf-8')
    before = old_file.read_bytes()
    loaded = ustore.load('Mjoll', 'FE1DD821')
    check('old file loads as before', loaded['recent'][0]['text'] == 'Player helped me find Grimsever.' and loaded['feeling'] == 'Proud.')
    check('backup copied before the upgrade', (old_file.parent / 'upgrade_backup' / old_file.name).read_bytes() == before)
    check('the memory file itself is unchanged', old_file.read_bytes() == before)
    rows = ustore.archive_for('Mjoll', 'FE1DD821').rows()
    check('old entries in the archive at the default importance', len(rows) == 1 and rows[0]['importance'] == archive.DEFAULT_IMPORTANCE, rows)
    (old_file.parent / 'upgrade_backup' / old_file.name).write_text('changed', encoding='utf-8')
    ustore.load('Mjoll', 'FE1DD821')
    check('the backup is made once', (old_file.parent / 'upgrade_backup' / old_file.name).read_text(encoding='utf-8') == 'changed')
    check('the memory page still lists the NPC once (archive files are not NPCs)', [p['name'] for p in memory_ui.people(str(root), 'P5', csv_path=str(Path(tmp) / 'none.csv'), followers=[])] == ['Mjoll'])

    # a broken archive never breaks memory
    bstore = memory.MemoryStore(str(root), 'P6')
    bstore.save('Ann', '0A0B0C', dict(memory.empty(), recent=[{'day': 1, 'hour': 9, 'text': 'first'}]))
    bstore.archive_path('Ann', '0A0B0C').write_bytes(b'not a database at all' * 20)
    bstore.save('Ann', '0A0B0C', dict(memory.empty(), recent=[{'day': 1, 'hour': 9, 'text': 'first'}, {'day': 2, 'hour': 9, 'text': 'second'}]))
    check('saving with a broken archive still saves the memory', len(bstore.load('Ann', '0A0B0C')['recent']) == 2)
    check('recall with a broken archive is empty, not an error', memory.recall(bstore, 'Ann', '0A0B0C', memory.empty(), 'first', 3) == [])
    check('hide with a broken archive hides nothing, never raises', memory.hide_matching(bstore, 'Ann', '0A0B0C', 'first') == [])
    check('list_hidden with a broken archive is empty', memory.list_hidden(bstore, 'Ann', '0A0B0C') == [])

    # the prompt: recalled memories reach the model through memory_text; recall off leaves them out
    mstore = memory.MemoryStore(str(root), 'P7')
    talk(mstore, summary('Player gave me an enchanted amulet of Mara.', importance=0.9), 1.5)
    _m = mstore.load('Lydia', '0A2C94'); _m['recent'][-1].pop('flags', None); mstore.save('Lydia', '0A2C94', _m)  # an ordinary memory here, not a first meeting
    for d in range(2, 36):
        talk(mstore, summary(f'Plain day {d}.', importance=0.1), d + 0.5)
    folded = mstore.load('Lydia', '0A2C94')
    folded['long_term'] = {}  # only recall can bring it back now
    mstore.save('Lydia', '0A2C94', folded)
    ctx = {'characters': [lydia], 'today': 40, 'player': 'Player', 'recall_query': lambda c: 'Player asks about the amulet of Mara'}
    check('memory_text brings the old memory back', 'amulet of Mara' in memory.memory_text('stock', ctx, mstore))
    check('recall off: it stays out', 'amulet of Mara' not in memory.memory_text('stock', dict(ctx, recall=False), mstore))

# the model files: found only with the right checksum; a download is checked before it is used
with tempfile.TemporaryDirectory() as tmp:
    blob = b'model bytes'
    real = dict(embed.FILES)
    embed.FILES = {'model.onnx': (hashlib.sha256(blob).hexdigest(), 'https://example.invalid/model.onnx'),
                   'tokenizer.json': (hashlib.sha256(b'{}').hexdigest(), 'https://example.invalid/tokenizer.json')}
    served = {'https://example.invalid/model.onnx': blob, 'https://example.invalid/tokenizer.json': b'{}'}
    opener = lambda url, timeout: io.BytesIO(served[url])
    check('no files, no folder', embed.find_folder([tmp]) is None)
    check('download writes checked files', embed.download(tmp, opener) and embed.find_folder([tmp]) == tmp)
    served['https://example.invalid/model.onnx'] = b'tampered'
    os.remove(os.path.join(tmp, 'model.onnx'))
    check('a download with the wrong checksum is refused and removed', not embed.download(tmp, opener)
          and not os.path.exists(os.path.join(tmp, 'model.onnx')) and not os.path.exists(os.path.join(tmp, 'model.onnx.download')))
    def offline(url, timeout):
        raise OSError('no network')
    check('no network: no files, no error', not embed.download(tmp, offline))
    embed.FILES = real
    check('the pinned model is the 8-bit MiniLM, checksums pinned', embed.MODEL_FILE in embed.FILES and all(len(sha) == 64 for sha, _ in embed.FILES.values())
          and all(embed.REVISION in url for _, url in embed.FILES.values()))

# the real model, when its folder is given and onnxruntime, numpy and tokenizers are installed
model_dir = sys.argv[2] if len(sys.argv) > 2 else ''
if model_dir:
    try:
        engine = embed.Engine(model_dir)
    except Exception as e:
        engine = None
        check('the real model loads', False, e)
    if engine is not None:
        check('the real model files pass their checksums', embed.find_folder([model_dir]) == model_dir)
        a, b, c = engine.embed(['Lydia remembers the dragon attack at the watchtower.', 'A huge winged beast burned the tower.',
                                'We bought bread and cheese at the market.'])
        check('real model: 384 numbers of length 1', a.shape == (384,) and abs(float((a * a).sum()) - 1) < 1e-3)
        check('real model: same subject closer than another', float(a @ b) > float(a @ c) + 0.15, (float(a @ b), float(a @ c)))
        with tempfile.TemporaryDirectory() as tmp:
            embed.use(engine)
            rstore = memory.MemoryStore(tmp, 'R')
            talk(rstore, summary('A dragon attacked the western watchtower and we barely survived.', importance=0.9), 1.5)
            for d in range(2, 36):
                talk(rstore, summary(f'We bought bread and cheese at stall {d}.', importance=0.1), d + 0.5)
            back = memory.recall(rstore, 'Lydia', '0A2C94', rstore.load('Lydia', '0A2C94'), 'Do you remember that winged beast?', today=40)
            check('real model: recalled by meaning', back and 'dragon' in back[0]['text'], [r['text'] for r in back])
            gone = memory.hide_matching(rstore, 'Lydia', '0A2C94', 'the fight with the winged beast', limit=1, by='test')
            check('real model: hide_matching by meaning', gone and 'dragon' in gone[0]['text'], gone)
            embed.use(None)
else:
    print('SKIP the real model (no model folder given)')

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
