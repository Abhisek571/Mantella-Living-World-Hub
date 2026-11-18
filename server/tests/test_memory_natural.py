"""Offline tests for the natural-NPC memory parts: how a memory is known (source), the mood carried between talks,
battle importance tiers, story arcs, save-and-reload safety (timeline.py) and the upgrade of old archives.
Run with a Python 3.11: test_memory_natural.py <repo server dir>
With numpy installed the arc tests by meaning run too."""
import json, os, sqlite3, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import archive, arcs, battle as B, embed, lw_state, memory, timeline
memory.SUMMARY_RETRY_SECONDS = 0
embed.use(None)

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


lydia = Char('Lydia', '0A2C94')
LINES = [f'line {i}' for i in range(8)]


def reply(text, **extra):
    return json.dumps({'memory': text, 'feelings': {'Lydia': 'Loyal.'}, **extra})


def talk(store, answer, when, chars=(lydia,)):
    summaries = FakeSummaries({c.name: Params(LINES, list(chars)) for c in chars}, answer)
    ctx = {'messages': None, 'npcs_to_summarize': list(chars), 'npcs_in_conversation': People(), 'world_id': 'P1',
           'is_reload': False, 'end_timestamp': when, 'is_radiant': False, 'summaries': summaries}
    memory.summarize(ctx, store)
    return summaries


def prompt(store, chars=(lydia,), today=None):
    return memory.memory_text('', {'characters': list(chars), 'today': today, 'player': 'Player'}, store)


def game(data_dir, day=None, **talk_keys):
    """conversation.json as the game side writes it (JsonUtil's typed shape)."""
    ints, strings, floats = {}, {}, {}
    if day is not None:
        ints['day'] = day
    for key, value in talk_keys.items():
        (floats if isinstance(value, float) else ints if isinstance(value, int) else strings)['talk_' + key] = value
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, 'conversation.json'), 'w', encoding='utf-8') as f:
        json.dump({'int': ints, 'string': strings, 'float': floats, 'stringList': {'speakers': []}}, f)


with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = os.path.join(tmp, 'StorageUtilData', 'MantellaLivingWorld')
    game(lw_state.DATA_DIR, day=40)  # an older game side: no talk counter

    # ---------------------------------------------------------------- source
    store = memory.MemoryStore(os.path.join(tmp, 'conv'), 'P1')
    talk(store, reply('Player brought me a sword.'), 40.5)
    i_told = memory.add_memory(store, 'Lydia', '0A2C94', 'The Jarl has fallen ill.', source='told', told_by='Lucan', day=41, hour=9, key='ev1')
    i_rumour = memory.add_memory(store, 'Lydia', '0A2C94', 'a dragon was seen over Helgen.', source='rumour', day=41, hour=10)
    memory.add_memory(store, 'Lydia', '0A2C94', 'I should train harder.', source='own', day=41, hour=11)
    memory.add_memory(store, 'Lydia', '0A2C94', 'Odd source text.', source='bogus', day=41, hour=12)
    text = prompt(store)
    check('seen is plain', 'Player brought me a sword.' in text and 'told you: Player brought' not in text, text)
    check('told shows who told them', 'Lucan told you: The Jarl has fallen ill.' in text, text)
    check('rumour reads as a rumour', 'You heard a rumour: a dragon was seen over Helgen.' in text, text)
    check('own thought', 'Your own thought: I should train harder.' in text, text)
    check('an unknown source counts as seen', '] Odd source text.' in text, text)
    check('the same key is never added twice', memory.add_memory(store, 'Lydia', '0A2C94', 'The Jarl has fallen ill again.', source='told',
                                                               told_by='Lucan', key='ev1') == '')
    rows = {r['id']: r for r in store.archive_for('Lydia', '0A2C94').rows()}
    check('source kept in the archive', rows[i_told]['source'] == 'told' and rows[i_told]['told_by'] == 'Lucan'
          and rows[i_rumour]['source'] == 'rumour', rows.get(i_told))
    check('kept in time order', [e['text'][:8] for e in store.load('Lydia', '0A2C94')['recent']][1:3] == ['The Jarl', 'a dragon'])
    # an NPC who is not in any talk gets a memory file of their own
    check('a memory for someone not in the talk', memory.add_memory(store, 'Lucan Valerius', '01325F', 'Lydia asked about the Jarl.',
                                                                   source='seen', day=41) != ''
          and store.load('Lucan Valerius', '01325F')['recent'][0]['text'] == 'Lydia asked about the Jarl.')
    check('empty text adds nothing', memory.add_memory(store, 'Lydia', '0A2C94', '   ') == '')
    check('told without a name', memory.sourced({'source': 'told'}, 'x') == 'You were told: x')

    # ---------------------------------------------------------------- mood
    store = memory.MemoryStore(os.path.join(tmp, 'mood'), 'P1')
    s = talk(store, reply('We argued about the Thalmor.', moods={'Lydia': 'angry and hurt'}, importance=0.5), 40.5)
    check('the summary prompt asks for moods (same call)', '"moods"' in s.calls[0][1] and len(s.calls) == 1)
    # ctx today is the game side's day; the memories are dated a day on (memory.MANTELLA_DAY): 39 is the talk's own day
    check('mood right after the talk', 'Your mood since your last talk: angry and hurt.' in prompt(store, today=39), prompt(store, today=39))
    check('mood fading a day or two later', 'Your mood lately, slowly fading: angry and hurt.' in prompt(store, today=41))
    check('mood gone after a few days (0.5 importance: 3 days)', 'mood' not in prompt(store, today=43).lower())
    check('mood_line for anyone by name and ref', memory.mood_line(('Lydia', '0A2C94'), store, 39) == 'Your mood since your last talk: angry and hurt.'
          and memory.mood_line(lydia, store, 45) == '')
    check('mood_line reads today from the game side', memory.mood_line(lydia, store) == 'Your mood lately, slowly fading: angry and hurt.')
    talk(store, reply('We made up over mead.', moods={'Someone': 'cheerful'}), 41.5)
    check('one NPC: a single mood is theirs whatever its label', 'cheerful' in prompt(store, today=40))
    check('a mood from a later day is not shown (earlier save)', 'cheerful' not in prompt(store, today=39)
          or 'angry' in prompt(store, today=39))
    check('parse_moods ignores junk', memory.parse_moods('{"moods": {"Lydia": 5}}', ['Lydia', 'Hod']) == {}
          and memory.parse_moods('not json', ['Lydia']) == {})
    talk(store, reply('Short words.'), 42.5)  # no mood in the reply: the last one carries on
    check('no mood given: the last one carries on', 'cheerful' in prompt(store, today=41))

    # ---------------------------------------------------------------- battle tiers
    def fighter(name, ref, role, side, **kw):
        f = {'name': name, 'ref_id': ref, 'role': role, 'side': side, 'unique': 0, 'dragon': 0, 'lowest': 1.0, 'down': 0, 'dead': 0,
             'rescued_by': [], 'kills': [], 'dealt': 0}
        f.update(kw)
        return f
    P, L = fighter('Dragonborn', '00000014', 'player', 0), fighter('Lydia', '000A2C94', 'party', 0)
    def fight(enemies, *ours, seconds=30):
        return {'id': '1', 'active': 0, 'seconds': seconds, 'end': 40.5, 'fighters': [*(ours or (P, L)), *enemies]}
    wolf = [fighter('Wolf', 'FF01', 'enemy', 1, dead=1)]
    pack = [fighter('Wolf', f'FF0{i}', 'enemy', 1) for i in range(4)]
    horde = [fighter('Draugr', f'FF1{i}', 'enemy', 1) for i in range(7)]
    named = [fighter('Hrothmund', 'FF21', 'enemy', 1, unique=1)]
    dragon = [fighter('Dragon', 'FF31', 'enemy', 1, dragon=1)]
    imp = lambda f, me=L: B.importance(f, me)
    check('a dragon > a named foe > a horde > a pack > a wolf',
          imp(fight(dragon)) > imp(fight(named)) > imp(fight(horde)) > imp(fight(pack)) > imp(fight(wolf)),
          [imp(fight(x)) for x in (dragon, named, horde, pack, wolf)])
    check('a long fight counts a little more', imp(fight(pack, seconds=150)) > imp(fight(pack)))
    hurt_l = fighter('Lydia', '000A2C94', 'party', 0, down=1)
    check('nearly dying makes it matter more', imp(fight(wolf, P, hurt_l), hurt_l) > imp(fight(wolf)))
    saved = dict(hurt_l, rescued_by=[{'ref': '00000014', 'how': 'heal'}])
    check('the player saving them matters more still', imp(fight(wolf, P, saved), saved) > imp(fight(wolf, P, hurt_l), hurt_l))
    p_low = dict(P, lowest=0.05, rescued_by=[{'ref': '000A2C94', 'how': 'kill'}])
    check('the player nearly dying, and them saving the player', imp(fight(wolf, p_low, L)) >= imp(fight(wolf)) + 0.2 - 1e-9)
    dead_ally = fighter('Faendal', '0001A69E', 'ally', 0, dead=1)
    check('someone on their side died: at least the death floor', imp(fight(wolf, P, L, dead_ally)) >= B.DEATH_FLOOR)
    by = fighter('Ysolda', '00013BAB', 'bystander', 2)
    check('a bystander remembers it less', imp(fight(dragon, P, L, by), by) < imp(fight(dragon)) and imp(fight(wolf, P, L, by), by) >= B.BYSTANDER_MIN)
    check('never above 1', imp(fight(dragon, p_low, saved, dead_ally, seconds=300), saved) <= 1.0)
    store = memory.MemoryStore(os.path.join(tmp, 'battle'), 'P1')
    ref = lambda v: int(str(v), 16) & 0xFFFFFF
    B.remember(store, [SimpleNamespace(name='Lydia', ref_id='0A2C94')], [dict(fight(dragon), in_prompt=0)], ref, at_end=True)
    entry = store.load('Lydia', '0A2C94')['recent'][-1]
    check('a remembered fight carries its tier', entry.get('battle') == '1' and entry.get('importance') == imp(fight(dragon)), entry)

    # ---------------------------------------------------------------- story arcs (from the summary call)
    store = memory.MemoryStore(os.path.join(tmp, 'arcs'), 'P1')
    story = {'label': 'Courting Player', 'so_far': 'Player has been courting me with gifts.'}
    s = talk(store, reply('Player gave me flowers by the river.', story=story, tags=['flowers']), 10.5)
    check('the summary prompt asks for a story (same call)', '"story"' in s.calls[0][1] and 'none yet' in s.calls[0][1] and len(s.calls) == 1)
    talk(store, reply('We spoke of the Jarl and the taxes.'), 11.5)
    s = talk(store, reply('Player gave me an amulet of Mara.', story={'label': 'courting player', 'so_far': 'Player courts me; now an amulet of Mara.'}), 12.5)
    check('the next prompt lists the ongoing story', 'Courting Player' in s.calls[0][1], s.calls[0][1][-300:])
    listed = arcs.list_arcs(store, 'Lydia', '0A2C94')
    check('one arc, both memories in it, newest summary', len(listed) == 1 and len(listed[0]['memories']) == 2
          and listed[0]['summary'] == 'Player courts me; now an amulet of Mara.', listed)
    # push both out of recent so they can only come back by recall
    for d in range(13, 13 + memory.MAX_RECENT + 2):
        talk(store, reply(f'Ordinary day {d} at the hall.'), d + 0.5)
    mem = store.load('Lydia', '0A2C94')
    rec = memory.recall(store, 'Lydia', '0A2C94', mem, 'flowers amulet courting gifts Mara', 60)
    lines = [r for r in rec if r.get('arc_line')]
    check('recall brings the story once, with its line', len(lines) == 1 and sum(1 for r in rec if r.get('arc')) == 1
          and 'Courting Player' in lines[0]['arc_line'], [(r['text'], r.get('arc_line')) for r in rec])
    text = memory.render(mem, 1500, store, 60, rec)
    check('the arc line is in the prompt', '(Part of an ongoing story, Courting Player: Player courts me; now an amulet of Mara.)' in text)
    arc_id = listed[0]['id']
    check('rename by hand', arcs.rename_arc(store, 'Lydia', '0A2C94', arc_id, 'Her courtship', 'Player is courting her.')
          and arcs.list_arcs(store, 'Lydia', '0A2C94')[0]['label'] == 'Her courtship')
    talk(store, reply('More flowers.', story={'label': 'Her courtship', 'so_far': 'Model text.'}), 50.5)
    check('a hand-edited summary is kept', arcs.list_arcs(store, 'Lydia', '0A2C94')[0]['summary'] == 'Player is courting her.')
    other = arcs.new_arc(store, 'Lydia', '0A2C94', 'A feud with Nazeem')
    check('merge arcs', other and arcs.merge_arcs(store, 'Lydia', '0A2C94', arc_id, [other]) and len(arcs.list_arcs(store, 'Lydia', '0A2C94')) == 1)
    member = arcs.list_arcs(store, 'Lydia', '0A2C94')[0]['memories'][0]['id']
    check('remove from an arc and add back', arcs.remove_from_arc(store, 'Lydia', '0A2C94', member)
          and arcs.add_to_arc(store, 'Lydia', '0A2C94', member, arc_id))
    # a hidden member: the story line could tell what was forgotten, so it is not sent
    hidden = memory.hide_matching(store, 'Lydia', '0A2C94', 'flowers by the river', by='Player', day=60)
    rec = memory.recall(store, 'Lydia', '0A2C94', store.load('Lydia', '0A2C94'), 'flowers amulet courting gifts Mara', 61)
    check('an arc with a hidden memory sends no story line', hidden and not any(r.get('arc_line') for r in rec), rec)
    check('delete an arc keeps its memories', arcs.delete_arc(store, 'Lydia', '0A2C94', arc_id) and not arcs.list_arcs(store, 'Lydia', '0A2C94')
          and len(store.archive_for('Lydia', '0A2C94').rows(hidden=None)) > 30)
    check('broken story replies give nothing', memory.parse_story('{"story": "yes"}') == {} and memory.parse_story('{"story": {"label": 5}}') == {})

    try:
        import numpy
    except ImportError:
        numpy = None
    if numpy is not None:
        class TopicEngine:
            np = numpy
            TOPICS = [('dragon', 'wyrm'), ('ring', 'jewel'), ('bread', 'food')]
            def embed(self, texts):
                out = []
                for t in texts:
                    v = numpy.array([sum(t.lower().count(w) for w in ws) for ws in self.TOPICS] + [0.05], dtype=numpy.float32)
                    v = numpy.pad(v, (0, embed.DIM - len(v)))
                    out.append(v / numpy.linalg.norm(v))
                return out
        embed.use(TopicEngine())
        store = memory.MemoryStore(os.path.join(tmp, 'arcs2'), 'P1')
        talk(store, reply('A dragon burned the farm.', tags=['dragon']), 20.5)
        talk(store, reply('The dragon came back, a wyrm of fire.', tags=['dragon']), 22.5)
        listed = arcs.list_arcs(store, 'Lydia', '0A2C94')
        check('two close memories days apart start an arc (meaning)', len(listed) == 1 and len(listed[0]['memories']) == 2
              and listed[0]['label'] == 'dragon', listed)
        talk(store, reply('We ate bread.'), 23.5)
        talk(store, reply('Another dragon, the wyrm again.'), 30.5)
        listed = arcs.list_arcs(store, 'Lydia', '0A2C94')
        check('a close memory joins the arc; another subject does not', len(listed) == 1 and len(listed[0]['memories']) == 3, listed)
        talk(store, reply('A dragon, far later.'), 90.5)
        check('too far apart in time: not joined', len(arcs.list_arcs(store, 'Lydia', '0A2C94')[0]['memories']) == 3)
        embed.use(None)
    else:
        print('SKIP arc tests by meaning (no numpy)')

    # ---------------------------------------------------------------- save-and-reload safety
    store = memory.MemoryStore(os.path.join(tmp, 'timeline'), 'P1')
    data = lw_state.DATA_DIR
    game(data, day=40)  # no counter: nothing stamped
    talk(store, reply('Before the counter: we met in Whiterun.'), 40.5)
    check('no counter: nothing stamped', 'talk' not in store.load('Lydia', '0A2C94')['recent'][-1])
    game(data, day=41, seq=1, id='a1', parent='', open=1, time=40.9)
    talk(store, reply('Talk one on the first line.', moods={'Lydia': 'calm'}, promises=[{'text': 'bring Lydia a shield', 'by': 'Player'}]), 41.95)
    e1 = store.load('Lydia', '0A2C94')['recent'][-1]
    check('a memory carries its talk', e1.get('talk') == 'a1' and e1.get('seq') == 1, e1)
    game(data, day=42, seq=2, id='a2', parent='a1', open=1, time=41.95)
    talk(store, reply('Talk two: Player struck me.', moods={'Lydia': 'furious'}, kept=['bring Lydia a shield']), 42.95)
    game(data, day=42, seq=3, id='', parent='a2', open=0, time=41.95)
    text = prompt(store)
    check('the newer save shows both talks', 'Talk one' in text and 'Talk two' in text and 'furious' in text, text)
    # the player loads the older save (after talk one) and starts a talk
    game(data, day=42, seq=2, id='b2', parent='a1', open=1, time=41.96)
    text = prompt(store)
    check('older save: talk two is set aside', 'Talk one' in text and 'Talk two' not in text, text)
    check('older save: its mood is gone too, the earlier one is back', 'furious' not in text and 'calm' in text, text)
    check('older save: the promise kept in talk two is open again', 'bring Lydia a shield' in text, text)
    check('listed as set aside', [r['state'] for r in memory.list_other_timeline(store, 'Lydia', '0A2C94')] == ['aside'])
    check('set aside is never forgotten by a command', memory.hide_matching(store, 'Lydia', '0A2C94', 'Player struck me', by='x') == [])
    # back to the newer save: talk two comes back
    game(data, day=43, seq=3, id='a3', parent='a2', open=1, time=42.96)
    check('newer save again: talk two is back', 'Talk two' in prompt(store) and memory.list_other_timeline(store, 'Lydia', '0A2C94') == [])
    # the older save again, and this time a memory is made there
    game(data, day=42, seq=2, id='c2', parent='a1', open=1, time=41.97)
    talk(store, reply('Talk two again, a new line: we went fishing.'), 42.99)
    text = prompt(store)
    check('new line: its own memory, not the old talk two', 'fishing' in text and 'Talk two:' not in text, text)
    rows = store.archive_for('Lydia', '0A2C94').rows(hidden=None)
    gone = [r for r in rows if 'struck' in r['text']]
    check('talk two now another timeline for good (kept, not deleted)', len(gone) == 1 and gone[0]['branch'] == 'other', gone)
    # the reviewer's case: one talk on the older save, then the newer save is loaded again: its line holds talk two,
    # so talk two is back (the 'other timeline' mark only stands for saves whose line does not hold it)
    game(data, day=43, seq=3, id='a3', parent='a2', open=1, time=42.96)
    text = prompt(store)
    check('loading the newer save again brings its talk back, even after a talk on the older one', 'struck' in text
          and 'fishing' not in text, text)
    listed = {r['text'][:9]: r['state'] for r in memory.list_other_timeline(store, 'Lydia', '0A2C94')}
    check("listed: only the older save's new line is set aside now", listed == {'Talk two ': 'aside'}, listed)
    talk(store, reply('Talk three on the newer save: we sparred.'), 43.97)
    text = prompt(store)
    check('a talk on the newer save keeps talk two and marks the abandoned line', 'struck' in text and 'sparred' in text
          and 'fishing' not in text, text)
    e2 = next(e for e in store.load('Lydia', '0A2C94')['recent'] if 'struck' in e.get('text', ''))
    check('the stale mark on talk two is taken off', e2.get('timeline') != 'other', e2)
    listed = {r['text'][:9]: r['state'] for r in memory.list_other_timeline(store, 'Lydia', '0A2C94')}
    check("listed: the older save's line is now another timeline", listed == {'Talk two ': 'other'}, listed)
    game(data, day=42, seq=3, id='c3', parent='c2', open=1, time=42.995)
    text = prompt(store)
    check('and the older save loaded once more has its own line back', 'fishing' in text and 'struck' not in text
          and 'sparred' not in text, text)
    check('memories from before the counter always count', 'we met in Whiterun' in prompt(store))
    check('timeline.json keeps the links', set(timeline.load(store)['links']) >= {'a1', 'a2', 'b2', 'a3', 'c2'}
          and set(timeline.load(store)['gone']) >= {'a2'})
    # a file still holding a newer save's talk (started later than the request's own time) is not trusted
    game(data, day=50, seq=9, id='z9', parent='z8', open=1, time=49.5)
    check('a talk counter from a later game time is ignored', timeline.read_game(45.0) is None and timeline.read_game(50.6) is not None)
    check('no counter: read_game gives None', (game(data, day=50), timeline.read_game())[1] is None)

    # a forgotten memory leaves 'earlier' even after the summary model compressed it (the reviewer's case)
    fst = memory.MemoryStore(os.path.join(tmp, 'forget_earlier'), 'P1')
    many = memory.empty()
    many['recent'] = [{'day': d, 'hour': 9, 'text': f'Day {d}: we walked to the market and talked about the weather.',
                       'witnesses': ['Ysolda']} for d in range(1, 41)]
    many['recent'][2]['text'] = 'Ysolda helped Inga hide gold stolen from the Bannered Mare under the bridge.'
    many['long_term']['earlier'] = 'x' * (memory.EARLIER_CHARS - 300)
    fst.save('Ysolda', '0A1B2C', many)
    loaded = fst.load('Ysolda', '0A1B2C')
    summary = lambda text: 'Ysolda remembers helping Inga hide gold stolen from the Bannered Mare, and many walks to market.'
    memory.fold_old(loaded, fst, summary)
    fst.save('Ysolda', '0A1B2C', loaded)
    check('setup: the robbery is folded and compressed into earlier', 'Bannered Mare' in fst.load('Ysolda', '0A1B2C')['long_term']['earlier']
          and not any('Bannered' in e['text'] for e in fst.load('Ysolda', '0A1B2C')['recent']))
    gone = memory.hide_matching(fst, 'Ysolda', '0A1B2C', 'hide gold stolen from the Bannered Mare under the bridge', limit=1, by='test')
    check('the robbery is hidden', len(gone) == 1 and 'Bannered' in gone[0]['text'], gone)
    after = fst.load('Ysolda', '0A1B2C')
    check('forgotten: no longer in earlier', 'Bannered Mare' not in after['long_term'].get('earlier', ''), after['long_term'])
    check('forgotten: no longer in the memory text', 'Bannered Mare' not in memory.render(after, 4000, fst))
    check('earlier made again from what is still remembered', 'Day 1: we walked' in after['long_term'].get('earlier', ''),
          after['long_term'].get('earlier', '')[:200])
    big = memory.MemoryStore(os.path.join(tmp, 'forget_earlier_big'), 'P1')
    lots = memory.empty()
    lots['recent'] = [{'day': d, 'hour': 9, 'text': f'Day {d}: ' + 'a long walk along the river with stories ' * 4, 'witnesses': ['Ysolda']}
                      for d in range(1, 121)]
    lots['recent'][5]['text'] = 'Ysolda helped Inga hide gold stolen from the Bannered Mare under the bridge.'
    big.save('Ysolda', '0A1B2C', lots)
    loaded = big.load('Ysolda', '0A1B2C')
    memory.fold_old(loaded, big, summary)
    big.save('Ysolda', '0A1B2C', loaded)
    memory.hide_matching(big, 'Ysolda', '0A1B2C', 'hide gold stolen from the Bannered Mare under the bridge', limit=1, by='test')
    after = big.load('Ysolda', '0A1B2C')
    check('too long when made again: cut to the limit, marked to shorten after the talk', len(after['long_term']['earlier']) <= memory.EARLIER_CHARS
          and after.get('earlier_redo') is True and 'Bannered' not in after['long_term']['earlier'])
    asked = []
    memory._fold_and_save(big, 'Ysolda', '0A1B2C', after, SimpleNamespace(summarize_conversation=lambda text, prompt: asked.append(text) or 'Short again.'))
    after = big.load('Ysolda', '0A1B2C')
    check('after the talk: shortened once by the summary model, without the forgotten memory', len(asked) == 1 and 'Bannered' not in asked[0]
          and after['long_term']['earlier'] == 'Short again.' and not after.get('earlier_redo'), (len(asked), after['long_term']))
    check('...with only the newest part of a big archive sent', asked and len(asked[0]) <= 4 * memory.EARLIER_CHARS and 'Day 90: a long' in asked[0]
          and 'Day 2: a long' not in asked[0],
          len(asked[0]) if asked else None)

    # set-aside memories are never folded into 'earlier'
    st2 = memory.MemoryStore(os.path.join(tmp, 'fold'), 'P1')
    mem = memory.empty()
    mem['recent'] = [{'day': d, 'hour': 1, 'text': f'Day {d} memory.', 'talk': f't{d}', 'seq': d} for d in range(1, memory.MAX_RECENT + 6)]
    br = timeline.Branch({'seq': 10, 'id': 't9', 'parent': 't8', 'open': True}, {'links': {f't{d}': [f't{d - 1}', d] for d in range(1, 40)}, 'gone': {}})
    memory.fold_old(mem, st2, None, br)
    check('set-aside memories are not folded', all(f'Day {d} memory.' not in mem['long_term'].get('earlier', '') for d in range(10, 40))
          and len([e for e in mem['recent'] if e['seq'] >= 10]) == memory.MAX_RECENT - 4, len(mem['recent']))
    # set-aside promises neither take open places nor lapse the loaded save's own
    pm = memory.empty()
    pm['facts'] = [{'kind': 'promise', 'text': f'Promise number {d}', 'by': 'P', 'day': d, 'due_day': -1, 'status': 'open',
                    'talk': f't{d}', 'seq': d} for d in [1, 2] + list(range(20, 32))]
    memory.lapse_old_promises(pm, 33, br)
    check('set-aside promises do not lapse the loaded save\'s own by the open cap',
          [f['status'] for f in pm['facts'][:2]] == ['open', 'open'], [f['status'] for f in pm['facts']])

    # the same memory without any counter renders exactly as before
    plain = memory.empty()
    plain['recent'] = [{'day': 3, 'hour': 9, 'text': 'A plain memory.'}]
    plain['feeling'] = 'Fond.'
    check('without a counter the text is as before', memory.render(plain, 1500) == '[Day 3, 9 in the morning] A plain memory.\nHow you feel now: Fond.',
          memory.render(plain, 1500))

    # ---------------------------------------------------------------- upgrade of an old archive
    up = Path(tmp) / 'upgrade' / 'P1' / 'living_world'
    up.mkdir(parents=True)
    old_schema = """CREATE TABLE memories (
        id TEXT PRIMARY KEY, day INTEGER, hour INTEGER, text TEXT, witnesses TEXT, importance REAL, emotion TEXT, type TEXT,
        tags TEXT, promises TEXT, shared TEXT, radiant INTEGER, hidden TEXT, recalled_day INTEGER DEFAULT -1, added REAL,
        embedding BLOB, model TEXT)"""
    db_path = up / 'Lydia - 0A2C94.archive.sqlite'
    db = sqlite3.connect(db_path)
    db.execute(old_schema)
    olds = [(f'id{i}', i, 10, f'Old memory {i} about the river.', '["Lydia"]', 0.5 + i / 100, 'calm', 'experience', '["river"]', '[]',
             None, 0, '{"day": 3, "by": "Player", "note": ""}' if i == 2 else None, -1, 1.0 + i, b'\x00' * (embed.DIM * 4), 'other-model')
            for i in range(5)]
    db.executemany(f"INSERT INTO memories VALUES ({', '.join('?' * 17)})", olds)
    db.commit()
    db.close()
    (up / 'Lydia - 0A2C94.json').write_text(json.dumps({'recent': [{'day': 4, 'hour': 10, 'text': 'Old memory 4 about the river.'}],
                                                         'long_term': {}, 'feeling': 'Warm.'}), encoding='utf-8')
    store = memory.MemoryStore(str(Path(tmp) / 'upgrade'), 'P1')
    loaded = store.load('Lydia', '0A2C94')
    rows = store.archive_for('Lydia', '0A2C94').rows(hidden=None)
    check('old archive opens with every row', len(rows) == 5 and {r['id'] for r in rows} == {f'id{i}' for i in range(5)}, len(rows))
    check('old rows read as seen, no talk, no arc', all(r['source'] == 'seen' and r['talk'] is None and r['seq'] is None and r['arc'] is None
                                                       for r in rows), rows[0])
    check('old values kept', [r['importance'] for r in rows] == [0.5 + i / 100 for i in range(5)] and rows[0]['text'] == 'Old memory 0 about the river.'
          and rows[0]['tags'] == ['river'] and rows[0]['embedding'] == b'\x00' * (embed.DIM * 4))
    check('a hidden old row stays hidden', [r['id'] for r in store.archive_for('Lydia', '0A2C94').rows(hidden=True)] == ['id2'])
    db = sqlite3.connect(db_path)
    cols = {row[1] for row in db.execute('PRAGMA table_info(memories)')}
    has_arcs = db.execute("SELECT name FROM sqlite_master WHERE name='arcs'").fetchone() is not None
    db.close()
    check('new columns added', {'source', 'told_by', 'talk', 'seq', 'branch', 'arc'} <= cols, cols)
    check('arcs table added', has_arcs)
    check('the memory file still loads', loaded['recent'][0]['text'] == 'Old memory 4 about the river.' and loaded['feeling'] == 'Warm.')
    check('new memories go into the upgraded archive', memory.add_memory(store, 'Lydia', '0A2C94', 'Lucan said the river flooded.', source='told',
                                                                        told_by='Lucan', day=6) != ''
          and len(store.archive_for('Lydia', '0A2C94').rows(hidden=None)) == 7)  # + the file's memory, + the new one
    check('opening it again changes nothing', len(store.archive_for('Lydia', '0A2C94').rows(hidden=None)) == 7)

print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
