"""Offline tests for the memory system (server/living_world/memory.py), with stand-ins for Mantella's classes.
Run with a Python 3.11: test_memory.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import memory

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
    def get_talk_only(self):
        return list(self.lines)
    def transform_to_dict_representation(self, messages):
        return '\n'.join(messages)
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

class FakeSummaries:
    """What the hook uses from Mantella's Summaries: thread split, grouping, and the summary call."""
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
        return self.reply


mjoll, nyri, alvor = Char('Mjoll', 'FE1DD821'), Char('nyri', 'FE26080E'), Char('Alvor', '013482')
long_talk = [f'line {i}' for i in range(8)]

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / 'conversations'
    store = memory.MemoryStore(str(root), 'Player1')

    # test_day_header_from_game_not_model: the model writes "Day 99", the header comes from the game clock
    reply = json.dumps({'memory': 'On Day 99 we walked to Riverwood and talked about the dragon.', 'feelings': {'Mjoll': 'Fond of Player, a bit restless.'}})
    summaries = FakeSummaries({'Mjoll': Params(long_talk, [mjoll])}, reply)
    ctx = {'messages': None, 'npcs_to_summarize': [mjoll], 'npcs_in_conversation': People(), 'world_id': 'Player1',
           'is_reload': False, 'pending_shares': None, 'end_timestamp': 4.75, 'is_radiant': False, 'summaries': summaries}
    handled = memory.summarize(ctx, store)
    mem = store.load('Mjoll', 'FE1DD821')
    check('summarize handled the save', handled is True)
    check('entry dated from the game clock', mem['recent'][-1]['day'] == 4 and mem['recent'][-1]['hour'] == 18, mem['recent'])
    text = memory.render(mem, 1500)
    check('header from the game, not the model', text.startswith('[Day 4, 6 in the evening]'), text)
    check('feeling kept', mem['feeling'] == 'Fond of Player, a bit restless.' and 'Fond of Player' in text, mem)

    # test_short_talk_one_line_no_llm_call (< 5 messages)
    summaries = FakeSummaries({'Alvor': Params(['Player: Hello.', 'Alvor: Hello, friend.', 'Player: Bye.'], [alvor])}, 'unused')
    memory.summarize(dict(ctx, npcs_to_summarize=[alvor], summaries=summaries, end_timestamp=5.5), store)
    amem = store.load('Alvor', '013482')
    check('short talk: no model call', summaries.calls == [], summaries.calls)
    check('short talk: one line', len(amem['recent']) == 1 and '\n' not in amem['recent'][0]['text'] and 'Player' in amem['recent'][0]['text'], amem)

    # test_short_talk_uses_message_text: Mantella's messages are objects whose str() is "<...Message object at ...>"
    class Msg:
        def __init__(self, text):
            self.text = text
    summaries = FakeSummaries({'Alvor': Params([Msg('Player: Got any work?'), Msg('Alvor: Not today.')], [alvor])}, 'unused')
    memory.summarize(dict(ctx, npcs_to_summarize=[alvor], summaries=summaries, end_timestamp=5.75), store)
    last = store.load('Alvor', '013482')['recent'][-1]['text']
    check('short talk: message text, not object names', 'Got any work?' in last and 'object at' not in last, last)

    # test_group_talk_stored_once + test_point_of_view_only_witnessed
    reply = json.dumps({'memory': 'Mjoll and nyri teased Player at the inn.', 'feelings': {'Mjoll': 'Amused.', 'nyri': 'Smug.'}})
    summaries = FakeSummaries({'Mjoll': Params(long_talk, [mjoll, nyri]), 'nyri': Params(long_talk, [mjoll, nyri])}, reply)
    before_alvor = json.dumps(store.load('Alvor', '013482'))
    memory.summarize(dict(ctx, npcs_to_summarize=[mjoll, nyri], summaries=summaries, end_timestamp=6.0), store)
    check('group talk: one model call', len(summaries.calls) == 1, len(summaries.calls))
    shared = list((root / 'Player1' / 'living_world' / 'shared').glob('*.json'))
    check('group talk stored once', len(shared) == 1, shared)
    v, n = store.load('Mjoll', 'FE1DD821'), store.load('nyri', 'FE26080E')
    check('both witnesses reference it', v['recent'][-1].get('shared') and v['recent'][-1]['shared'] == n['recent'][-1]['shared'])
    check('each keeps their own feeling', v['feeling'] == 'Amused.' and n['feeling'] == 'Smug.', (v['feeling'], n['feeling']))
    check('shared entry renders for each', 'teased Player' in memory.render(v, 1500) and 'teased Player' in memory.render(n, 1500))
    check('absent NPC unchanged', json.dumps(store.load('Alvor', '013482')) == before_alvor)

    # test_budget_never_exceeded
    big = store.load('Mjoll', 'FE1DD821')
    for i in range(60):
        big['recent'].append({'day': 10 + i, 'hour': 12, 'text': 'A long walk and a longer talk about everything under the sky. ' * 4, 'witnesses': ['Mjoll']})
    for budget in (200, 800, 1500):
        out = memory.render(big, budget)
        check(f'render within {budget} tokens', memory.tokens(out) <= budget, memory.tokens(out))
    check('newest kept first when cutting', 'Day 69' in memory.render(big, 200))
    folded = memory.fold_old(big)
    check('old entries fold into earlier', len(folded['recent']) <= memory.MAX_RECENT and folded['long_term'].get('earlier'), len(folded['recent']))

    # plain text reply (no JSON) is kept as the memory
    summaries = FakeSummaries({'Mjoll': Params(long_talk, [mjoll])}, 'We fished by the river.')
    memory.summarize(dict(ctx, summaries=summaries, end_timestamp=7.25), store)
    check('plain text reply kept', store.load('Mjoll', 'FE1DD821')['recent'][-1]['text'] == 'We fished by the river.')

    # test_legacy_conversion_keeps_text (backup written first)
    legacy_dir = root / 'Player1' / 'Lydia - 0A2C94'; legacy_dir.mkdir(parents=True)
    (legacy_dir / 'Lydia_summary_1.txt').write_text('[Day 2, 9 in the morning]\nLydia swore to carry Player\'s burdens.\n', encoding='utf-8')
    lmem = store.load('Lydia', '0A2C94')
    check('legacy text kept', 'carry Player' in lmem['long_term'].get('earlier', ''), lmem)
    check('legacy backup written', any(p.name.startswith('Lydia_summary_1.txt') for p in (root / 'Player1' / 'living_world' / 'legacy_backup').glob('*')))
    check('legacy file untouched', (legacy_dir / 'Lydia_summary_1.txt').exists())

    # memory_text: our memory when we have one, Mantella's text otherwise
    text = memory.memory_text('stock text', {'characters': [mjoll], 'world_id': 'Player1'}, store)
    check('memory text from the store', text.startswith('Below is a summary of past events:') and 'fished' in text, text[:120])
    check('unknown NPC keeps Mantella text', memory.memory_text('stock text', {'characters': [Char('Nobody', '000001')], 'world_id': 'Player1'}, store) == 'stock text')
    multi = memory.memory_text('stock', {'characters': [mjoll, nyri], 'world_id': 'Player1'}, store)
    check('group memory marked per NPC', "[This is the beginning of Mjoll's memory" in multi and "[This is the beginning of nyri's memory" in multi)
    # test_group_blocks_keep_private_separate
    check('group blocks say who alone knows them', "Only Mjoll knows what is in this block" in multi and "Only nyri knows what is in this block" in multi, multi[:300])
    check('one-on-one has no private marker', 'Only Mjoll knows' not in memory.memory_text('stock', {'characters': [mjoll], 'world_id': 'Player1'}, store))
    # test_summary_prompt_only_what_was_said: no invented origins, names or reasons in memories
    check('summary prompt forbids adding facts', 'only what was actually said' in memory.SUMMARY_PROMPT and 'never add' in memory.SUMMARY_PROMPT.lower(), memory.SUMMARY_PROMPT)
    # test_stranger_budget: budget_for gives each NPC their own limit (close NPCs more, strangers less)
    full = memory.memory_text('stock', {'characters': [mjoll], 'world_id': 'Player1'}, store, 1500)
    small = memory.memory_text('stock', {'characters': [mjoll], 'world_id': 'Player1'}, store, 1500, budget_for=lambda c: 30)
    check('per-NPC budget cuts a stranger', memory.tokens(small) <= 30 + 12 < memory.tokens(full), (memory.tokens(small), memory.tokens(full)))
    check('broken memory file falls back', (store._path('Ghost', '1').parent.mkdir(parents=True, exist_ok=True), store._path('Ghost', '1').write_text('{', encoding='utf-8'), store.load('Ghost', '1'))[2] == memory.empty())

# review fixes: unreadable files kept, bad shapes cleaned, long entries capped, names like Mantella's
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'W')
    p = store._path('Bom', '1'); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes('﻿{"feeling": "warm"}'.encode('utf-8'))
    check('BOM file still loads', store.load('Bom', '1')['feeling'] == 'warm')
    p = store._path('Broken', '1'); p.write_text('{', encoding='utf-8')
    store.load('Broken', '1')
    check('unreadable file copied aside before anything overwrites it', any(f.name.startswith('Broken - 1.json.unreadable') for f in p.parent.iterdir()))
    p = store._path('Odd', '1')
    p.write_text(json.dumps({'recent': [{'day': '3', 'hour': 'x', 'text': 'Met.'}, 'junk', None], 'long_term': None, 'feeling': 5}), encoding='utf-8')
    odd = store.load('Odd', '1')
    check('bad shapes cleaned', odd['long_term'] == {} and odd['feeling'] == '' and odd['recent'] == [{'day': 3, 'hour': -1, 'text': 'Met.'}], odd)
    check('render survives cleaned data', 'Met.' in memory.render(odd))
    big = {'recent': [{'day': 1, 'hour': 9, 'text': 'Old but short.'}, {'day': 2, 'hour': 9, 'text': 'x' * 9000}], 'long_term': {}, 'feeling': ''}
    check('one huge entry does not hide the others', 'Old but short.' in memory.render(big, 300))
    check('JSON after a preface is still parsed', memory.parse_summary('Here you go:\n{"memory": "We traded.", "feelings": {"Ann": "glad"}}', ['Ann']) == ('We traded.', {'Ann': 'glad'}))
    check('unparsed reply is capped', len(memory.parse_summary('word ' * 2000, [])[0]) <= memory.MAX_ENTRY_CHARS)
    check('numbered names share one file, like Mantella', store._path('Whiterun Guard 2', '9') == store._path('Whiterun Guard', '9'))

# test_vanilla_dialogue_kept: Mantella hands over the vanilla dialogue it stored (lines said in the normal dialogue
# menu since the last talk) only once, as in-game events on the automatic greeting, which is a system-generated
# message and so missing from get_talk_only(); a talk ended at once still has to remember them
class Greeting:
    is_system_generated_message = True
    def __init__(self, events):
        self._UserMessage__ingame_events = events
    def get_formatted_content(self):
        return 'Hello Alvor.'
class GreetThread(Thread):
    def __init__(self, greeting, lines):
        super().__init__(lines)
        self.greeting = greeting
    def get_talk_only(self, include_system_generated_messages=False):
        return ([self.greeting] if include_system_generated_messages else []) + list(self.lines)
    def __len__(self):
        return len(self.lines) + 1
class GreetParams:
    def __init__(self, greeting, lines, chars):
        self.messages, self.characters = GreetThread(greeting, lines), chars
vanilla = ["Player: Any work for me?;\n Alvor: Hod needs logs. Talk to him at the mill.", 'The location is now Riverwood', 'Player equipped Iron Sword']
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(str(Path(tmp) / 'conversations'), 'Player1')
    ctx = {'messages': None, 'npcs_to_summarize': [alvor], 'npcs_in_conversation': People(), 'world_id': 'Player1',
           'is_reload': False, 'pending_shares': None, 'end_timestamp': 3.5, 'is_radiant': False}
    summaries = FakeSummaries({'Alvor': GreetParams(Greeting(vanilla), [], [alvor])}, 'unused')
    memory.summarize(dict(ctx, summaries=summaries), store)
    rec = store.load('Alvor', '013482')['recent']
    check('talk ended at once: vanilla lines remembered', len(rec) == 1 and 'Hod needs logs' in rec[0]['text'] and 'Any work for me?' in rec[0]['text'], rec)
    check('only dialogue, not other events', rec and 'location is now' not in rec[0]['text'] and 'equipped' not in rec[0]['text'], rec)
    check('no model call for it', summaries.calls == [])
    summaries = FakeSummaries({'Alvor': GreetParams(Greeting(['Player equipped Iron Sword']), [], [alvor])}, 'unused')
    memory.summarize(dict(ctx, summaries=summaries), store)
    check('nothing said anywhere: nothing saved', len(store.load('Alvor', '013482')['recent']) == len(rec))
    summaries = FakeSummaries({'Alvor': GreetParams(Greeting(vanilla), long_talk, [alvor])}, 'We talked about the mill.')
    memory.summarize(dict(ctx, summaries=summaries), store)
    check('long talk: vanilla lines go to the summary', summaries.calls and 'Hod needs logs' in summaries.calls[0][0] and 'line 0' in summaries.calls[0][0], summaries.calls)
    summaries = FakeSummaries({'Alvor': GreetParams(Greeting(vanilla), ['Player: Thanks.', 'Alvor: Anytime.'], [alvor])}, 'unused')
    memory.summarize(dict(ctx, summaries=summaries), store)
    last = store.load('Alvor', '013482')['recent'][-1]['text']
    check('short talk: vanilla lines and the talk both kept', 'Hod needs logs' in last and 'Anytime.' in last, last)

class Said:  # Mantella's AssistantMessage keeps the words in its sentences; .text is empty
    text = ''
    def get_formatted_content(self):
        return 'Lydia: I am sworn to carry your burdens.'
check('short talk keeps the NPC words', 'sworn to carry' in memory.one_line([Said()], 'Player'))
check('radiant talks get their own prompt', '{player}' not in memory.RADIANT_PROMPT and 'feel' not in memory.RADIANT_PROMPT.lower())

# test_safe_file_names: odd NPC names, ref ids and world ids stay inside living_world and still save
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, '../evil')
    living = Path(store.root).resolve()
    check('world id cannot leave the conversations folder', Path(tmp).resolve() in living.parents, store.root)
    for odd in ('../../escape', '..\\..\\escape2', 'a/b', 'Jarl: Balgruuf', 'Who?', 'CON', 'x' * 300, 'Name. '):
        try:
            store.save(odd, '../0001A2B3', memory.empty())
            ok = store._path(odd, '../0001A2B3').resolve().parent == living
        except OSError as e:
            ok = e
        check(f'odd name saved inside the store: {odd[:20]!r}', ok is True, ok)
    check('odd names that differ get different files', store._path('a/b', '1') != store._path('a:b', '1'))
    check('normal names keep their file name', store._path('Lydia', '000A2C94').name == 'Lydia - 000A2C94.json')
    check('shared key must be a hash', store.shared_text('../../secret') == '' and store.shared_text(5) == '')

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
