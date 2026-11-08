"""Offline tests for the memory system (server/living_world/memory.py), with stand-ins for Mantella's classes.
Run with a Python 3.11: test_memory.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import memory
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
    check('one NPC: a feeling under another label still counts', memory.parse_summary('{"memory": "We traded.", "feelings": {"<name>": "glad"}}', ['Ann']) == ('We traded.', {'Ann': 'glad'}))
    check('one NPC: a plain text feeling counts too', memory.parse_summary('{"memory": "We traded.", "feelings": "glad"}', ['Ann']) == ('We traded.', {'Ann': 'glad'}))
    check('plain text reply: the feeling line is split off', memory.parse_summary('We traded.\n\nFeelings: Ann: glad and tired', ['Ann']) == ('We traded.', {'Ann': 'glad and tired'}))
    check('plain text reply: feeling line without a name', memory.parse_summary('We traded.\nFeelings: glad', ['Ann']) == ('We traded.', {'Ann': 'glad'}))
    check('plain text reply, group: each named feeling kept', memory.parse_summary('We traded.\nFeelings:\nAnn: glad\nCid: wary', ['Ann', 'Cid']) == ('We traded.', {'Ann': 'glad', 'Cid': 'wary'}))
    check('group: a feeling for someone unknown is dropped', memory.parse_summary('{"memory": "We traded.", "feelings": {"Bob": "glad"}}', ['Ann', 'Cid']) == ('We traded.', {}))
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

# test_long_dialogue_compacted: a lot of lines from the normal dialogue menu are summarized as the talk starts, saved
# with how the NPC now feels, and replaced by the short version in the events
long_dialogue = 'Player: Did you find it?;\n Alvor: ' + 'I never thought I would see that claw again. ' * 20 + 'Player: Here it is.;\n Alvor: Thank you.'
class StartSummaries:
    def __init__(self, reply):
        self.reply, self.calls = reply, []
    def summarize_conversation(self, text, prompt):
        self.calls.append((text, prompt))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(str(Path(tmp) / 'conversations'), 'Player1')
    good = json.dumps({'memory': 'The player brought the claw back.', 'feelings': {'Alvor': 'grateful'}})
    start = {'player': 'Player', 'characters': [alvor], 'game_days': 3.5, 'language': 'English', 'is_first': True}
    # T-5: a later event shaped like dialogue (a typed custom event) is never summarized into memory
    summaries = StartSummaries(good)
    check('not the first message: dialogue left as it is', memory.compact_dialogue([long_dialogue], dict(start, is_first=False, summaries=summaries), store) == [long_dialogue] and summaries.calls == [] and not store.load('Alvor', '013482')['recent'])
    check('no is_first (older Direct AI Connect): left as it is', memory.compact_dialogue([long_dialogue], dict({k: v for k, v in start.items() if k != 'is_first'}, summaries=summaries), store) == [long_dialogue] and summaries.calls == [])
    summaries = StartSummaries(good)
    out = memory.compact_dialogue([long_dialogue, 'Player equipped Iron Sword'], dict(start, summaries=summaries), store)
    saved = store.load('Alvor', '013482')
    check('long dialogue: one model call with all of it', len(summaries.calls) == 1 and 'Thank you.' in summaries.calls[0][0] and 'Did you find it?' in summaries.calls[0][0], summaries.calls)
    check('long dialogue: raw lines replaced by the summary', out[0].startswith(memory.COMPACTED) and 'brought the claw back' in out[0] and 'never thought' not in out[0], out)
    check('long dialogue: she is told how she feels', 'grateful' in out[0], out)
    check('long dialogue: other events untouched', out[1] == 'Player equipped Iron Sword', out)
    check('long dialogue: saved with the game date and feeling', saved['recent'][-1]['text'] == 'The player brought the claw back.' and saved['recent'][-1]['day'] == 3 and saved['feeling'] == 'grateful', saved)
    check('long dialogue: not read again when the talk ends', memory.vanilla_dialogue(GreetThread(Greeting([out[0]]), []), 'Player') == [])
    count = len(saved['recent'])
    # a loaded save hands the same lines over again: no second entry and no second model call
    summaries = StartSummaries(json.dumps({'memory': 'A different wording.', 'feelings': {'Alvor': 'cold'}}))
    again = memory.compact_dialogue([long_dialogue], dict(start, summaries=summaries), store)
    check('same lines after a reload: no model call, no new entry', summaries.calls == [] and len(store.load('Alvor', '013482')['recent']) == count, summaries.calls)
    check('same lines after a reload: the saved summary is used', 'brought the claw back' in again[0] and 'grateful' in again[0] and store.load('Alvor', '013482')['feeling'] == 'grateful', again)
    short = 'Player: Any work for me?;\n Alvor: Hod needs logs.'
    summaries = StartSummaries(good)
    check('a few lines stay as they are', memory.compact_dialogue([short], dict(start, summaries=summaries), store) == [short] and summaries.calls == [])
    for name, reply in (('fails', RuntimeError('no model')), ('is empty', '')):
        newer = long_dialogue + ' Player: One more thing.;\n Alvor: Yes?'
        out = memory.compact_dialogue([newer], dict(start, summaries=StartSummaries(reply)), store)
        check(f'model {name}: raw lines kept, nothing saved', out == [newer] and len(store.load('Alvor', '013482')['recent']) == count, out)
    summaries = StartSummaries(good)
    check('unknown speaker: left as it is', memory.compact_dialogue([long_dialogue], dict(start, characters=[Char('Hilde', '1')], summaries=summaries), store) == [long_dialogue] and summaries.calls == [])
    numbered = long_dialogue.replace('Alvor:', 'Whiterun Guard:')
    out = memory.compact_dialogue([numbered], dict(start, characters=[Char('Whiterun Guard 2', '9')], summaries=StartSummaries(good)), store)
    check('numbered NPC found by name', out[0].startswith(memory.COMPACTED) and store.load('Whiterun Guard 2', '9')['recent'], out)
    hilde = Char('Hilde', '2')
    memory.compact_dialogue([long_dialogue], dict(start, characters=[hilde, alvor], summaries=StartSummaries(good)), store)
    check('group talk: only the speaker keeps it', store.load('Hilde', '2')['recent'] == [])
    # an older Direct AI Connect has no start hook: long lines still reach the model when the talk ends
    summaries = FakeSummaries({'Alvor': GreetParams(Greeting([long_dialogue]), [], [alvor])}, good)
    ctx = {'messages': None, 'npcs_to_summarize': [alvor], 'npcs_in_conversation': People(), 'world_id': 'Player1',
           'is_reload': False, 'pending_shares': None, 'end_timestamp': 4.5, 'is_radiant': False}
    before = len(store.load('Alvor', '013482')['recent'])
    memory.summarize(dict(ctx, summaries=summaries), store)
    after = store.load('Alvor', '013482')
    check('talk ended at once, long lines: summarized, not cut', summaries.calls and 'Thank you.' in summaries.calls[0][0] and 'Then this conversation' not in summaries.calls[0][0], summaries.calls)
    check('talk ended at once, long lines: saved with feeling', len(after['recent']) == before + 1 and after['feeling'] == 'grateful', after)

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

# definite memory: promises, facts, expiry, budget
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'Player1')
    lydia = Char('Lydia', '000A2C94')

    mem = memory.empty()
    memory.add_promises(mem, json.dumps({'memory': 'x', 'promises': [
        {'text': 'Take Lydia to Solitude', 'by': 'Player', 'due_in_days': 1},
        {'text': 'Someday visit Falkreath', 'by': 'Lydia', 'due_in_days': None},
        {'text': '', 'by': 'Player'}, 'junk', {'text': 'Bad due', 'due_in_days': 'soon'},
        {'text': 'True is no number', 'due_in_days': True}]}), 10)
    check('promises stored from the summary', [f['text'] for f in mem['facts']][:2] == ['Take Lydia to Solitude', 'Someday visit Falkreath'], mem['facts'])
    check('game clock sets the due day', mem['facts'][0]['due_day'] == 11 and mem['facts'][0]['source'] == 'ai')
    check('no date means no due day', [f['due_day'] for f in mem['facts'][1:]] == [-1, -1, -1], mem['facts'])
    store.save('Lydia', '000A2C94', mem)
    check('facts survive save and load', len(store.load('Lydia', '000A2C94')['facts']) == 4)
    check('old file without facts loads', memory.clean({'recent': []})['facts'] == [] and memory.clean({'facts': 'x', 'talks': 'y'})['talks'] == 0)
    check('broken fact rows dropped', [f['text'] for f in memory.clean({'facts': [{'text': ''}, 3, {'no': 'text'}, {'text': 'ok'}]})['facts']] == ['ok'])

    memory.add_promises(mem, json.dumps({'promises': [{'text': 'take lydia to solitude', 'due_in_days': 2}]}), 11)
    check('same promise not added twice', sum(f['text'].lower() == 'take lydia to solitude' for f in mem['facts']) == 1)
    memory.add_promises(mem, 'not json at all', 11)
    check('a reply without JSON changes nothing', len(mem['facts']) == 4)
    no_clock = memory.empty()
    memory.add_promises(no_clock, '{"promises":[{"text":"a"}]}', -1)
    check('without a game clock nothing is added', no_clock['facts'] == [])

    # the Lydia case: promised on day 10 for day 11, next talk on day 40
    mem['recent'] = [{'day': 10, 'hour': 9, 'text': 'She agreed to come.', 'witnesses': ['Lydia']}]
    text = memory.facts_text(mem, [], 40, 'Player', 'Lydia')
    check('days since the last talk shown', 'last talked with Player 30 days ago' in text, text)
    check('overdue promise shows how late', 'Player promised: Take Lydia to Solitude (overdue by 29 days)' in text, text)
    check('NPC promise worded as hers', 'You promised: Someday visit Falkreath' in text, text)
    check('overdue listed before others', text.index('overdue') < text.index('Falkreath'), text)
    soon = memory.facts_text(mem, [], 10, 'Player', 'Lydia')
    check('not late yet says when', '(due tomorrow)' in soon and 'last talked' not in soon, soon)
    check('without a game day no dates are shown', 'overdue' not in memory.facts_text(mem, [], None, 'Player', 'Lydia'))
    memory.add_promises(mem, json.dumps({'kept': ['Take Lydia to Solitude']}), 41)
    check('a kept promise stops showing', 'Solitude' not in memory.facts_text(mem, [], 41, 'Player', 'Lydia'))
    check('and is no longer open', 'Take Lydia to Solitude' not in memory.open_promises(mem))

    # promises are matched loosely, lapse in time, and sit under their own heading
    loose = memory.empty()
    memory.add_promises(loose, json.dumps({'promises': [{'text': 'Bring Ysolda a mammoth tusk', 'due_in_days': '2'}]}), 5)
    check('a due day given as text is read', loose['facts'][0]['due_day'] == 7, loose['facts'])
    memory.add_promises(loose, json.dumps({'promises': [{'text': 'bring ysolda a mammoth tusk.'}]}), 6)
    check('punctuation and case do not make a second promise', len(loose['facts']) == 1)
    memory.add_promises(loose, json.dumps({'kept': ['Bring Ysolda a mammoth tusk!']}), 7)
    check('a kept copy with other punctuation closes it', not memory.open_promises(loose))
    old = memory.empty()
    memory.add_promises(old, json.dumps({'promises': [{'text': 'Fix the gate', 'due_in_days': 1}, {'text': 'Visit sometime'}]}), 10)
    memory.add_promises(old, '{}', 70)
    check('not lapsed at 59 days late', 'Fix the gate' in memory.open_promises(old))
    memory.add_promises(old, '{}', 72)
    check('lapsed past 60 days late', 'Fix the gate' not in memory.open_promises(old) and 'Visit sometime' in memory.open_promises(old))
    memory.add_promises(old, '{}', 131)
    check('an undated promise lapses after 120 days', not memory.open_promises(old))
    lots = memory.empty()
    memory.add_promises(lots, json.dumps({'promises': [{'text': f'Errand number {i} for the town'} for i in range(14)]}), 3)
    check('only the newest ten stay open', len(memory.open_promises(lots)) == memory.MAX_OPEN and 'Errand number 13 for the town' in memory.open_promises(lots))
    shown = memory.facts_text(lots, [{'day': 2, 'priority': 3, 'text': 'You healed Lydia'}], 5, 'Player', 'Lydia')
    check('promises have their own heading', 'Promises as you remember them:' in shown and shown.index('What you know for certain') < shown.index('Promises as'), shown)
    tight = memory.facts_text(lots, [{'day': 2, 'priority': 3, 'text': 'You healed Lydia'}], 5, 'Player', 'Lydia', 40)
    check('a high-priority game fact beats ordinary promises for room', 'You healed Lydia' in tight, tight)
    check('ratings sent as text are accepted', memory.clean_profile({'talk': '1', 'deeds': 3.0, 'care': 2, 'gifts': 2, 'physical': 1}) != {})
    check('half ratings refused', memory.clean_profile({'talk': 1.5, 'deeds': 3, 'care': 2, 'gifts': 2, 'physical': 1}) == {})

    # game facts are dated GameDaysPassed; facts_text's today is Mantella's day (GameDaysPassed + 1)
    rows = [{'day': 38, 'priority': 3, 'text': 'You healed Lydia'}, {'day': -1, 'priority': 1, 'text': 'Favourite food: stew'}]
    text = memory.facts_text(memory.empty(), rows, 40, 'Player', 'Lydia')
    check('game facts dated', 'You healed Lydia (yesterday)' in text and 'Favourite food: stew' in text and 'stew (' not in text, text)

    # the game side writes today as GameDaysPassed; Mantella stamps talks GameDaysPassed + 1 (MantellaConversation.psc)
    dated = memory.empty()
    dated['recent'] = [{'day': 11, 'hour': 12, 'text': 'We met.', 'witnesses': ['Lydia']}]  # end_timestamp 11.5: GameDaysPassed 10.5
    memory.add_promises(dated, json.dumps({'promises': [{'text': 'Bring mead', 'by': 'Player', 'due_in_days': 1}]}), 11)
    store.save('Lydia', '000A2C94', dated)
    same_day = memory.memory_text('stock', {'characters': [lydia], 'world_id': 'Player1', 'today': 10, 'player': 'Player'}, store)
    check('same game day: no "last talked", due tomorrow', 'last talked' not in same_day and '(due tomorrow)' in same_day, same_day[:300])
    next_day = memory.memory_text('stock', {'characters': [lydia], 'world_id': 'Player1', 'today': 11, 'player': 'Player'}, store)
    check('next game day: yesterday, due today', 'last talked with Player yesterday' in next_day and '(due today)' in next_day, next_day[:300])
    later = memory.memory_text('stock', {'characters': [lydia], 'world_id': 'Player1', 'today': 13, 'player': 'Player',
                                         'facts_for': lambda c: [{'day': 12, 'priority': 3, 'text': 'You healed Lydia'}]}, store)
    check('two days late, game fact from the game day before', '(overdue by 2 days)' in later and 'You healed Lydia (yesterday)' in later, later[:400])
    check('a hand-edited promiser that is not text does not break', memory.clean({'facts': [{'text': 'x', 'by': 5}]})['facts'][0]['by'] == '5')
    many = [{'day': 1, 'priority': 1, 'text': f'Fact number {i} ' + 'x' * 60} for i in range(40)]
    check('facts stay inside their budget', memory.tokens(memory.facts_text(memory.empty(), many, 40, 'Player', 'Lydia')) <= memory.FACT_TOKENS + 5)
    check('no facts, no heading', memory.facts_text(memory.empty(), [], 40, 'Player', 'Lydia') == '')
    many_open = memory.empty()
    many_open['facts'] = [{'text': f's{i}', 'status': 'kept'} for i in range(40)] + [{'text': 'still open', 'status': 'open'}]
    memory.add_promises(many_open, '{"promises":[{"text":"new one"}]}', 5)
    check('stored facts capped, open ones kept', len(many_open['facts']) == memory.MAX_FACTS and {'still open', 'new one'} <= set(memory.open_promises(many_open)))

    # budget: more after 20 talks, with a hard cap
    fresh = memory.empty()
    check('no bonus before 20 talks', memory.long_known_bonus(dict(fresh, talks=19), 1500) == 0)
    check('bonus from 20 talks', memory.long_known_bonus(dict(fresh, talks=20), 1500) == 300)
    check('hard cap holds', 1500 + memory.long_known_bonus(dict(fresh, talks=500), 1500) + memory.FACT_TOKENS == 2000)
    check('a higher setting gets no bonus', memory.long_known_bonus(dict(fresh, talks=500), 1900) == 0)
    big = dict(memory.empty(), talks=25, recent=[{'day': i, 'hour': 9, 'text': f'Day {i} ' + 'y' * 300, 'witnesses': ['Lydia']} for i in range(30)])
    store.save('Lydia', '000A2C94', big)
    ctx = {'characters': [lydia], 'world_id': 'Player1', 'today': 40, 'player': 'Player',
           'facts_for': lambda c: [{'day': 39, 'priority': 3, 'text': 'You healed Lydia'}]}
    out = memory.memory_text('stock', ctx, store, 1500, lambda c: 1500)
    check('long-known NPC stays under the hard cap', memory.tokens(out) <= 2000 + 20, memory.tokens(out))
    check('long-known NPC gets past the old budget', memory.tokens(out) > 1500, memory.tokens(out))
    check('facts come first', out.index('What you know for certain') < out.index('Day 2'), out[:200])
    stranger = memory.memory_text('stock', ctx, store, 1500, lambda c: 400)
    check('strangers get no bonus', memory.tokens(stranger) <= 400 + memory.FACT_TOKENS + 20, memory.tokens(stranger))
    check('works without the new context', 'Day 29' in memory.memory_text('stock', {'characters': [lydia], 'world_id': 'Player1'}, store))

    # old memories are rewritten, not cut; a failure still cuts
    def long_memory():
        return dict(memory.empty(), recent=[{'day': i, 'hour': 9, 'text': f'Promise {i} ' + 'z' * 400, 'witnesses': ['Lydia']} for i in range(41)])
    calls = []
    memory.fold_old(dict(memory.empty(), recent=[{'day': i, 'hour': 9, 'text': 'short', 'witnesses': []} for i in range(31)]), store, lambda t: calls.append(t))
    check('no model call while it still fits', calls == [])
    done = memory.fold_old(long_memory(), store, lambda text: 'She remembers the short version.')
    check('over the limit it is rewritten', done['long_term']['earlier'] == 'She remembers the short version.', done['long_term']['earlier'][:80])
    def broken(text):
        raise RuntimeError('no model')
    kept = memory.fold_old(long_memory(), store, broken)
    check('a failed rewrite falls back to the cut', len(kept['long_term']['earlier']) == memory.EARLIER_CHARS)
    empty_reply = memory.fold_old(long_memory(), store, lambda t: '')
    check('an empty rewrite falls back to the cut', len(empty_reply['long_term']['earlier']) == memory.EARLIER_CHARS)

    # the summary hook stores promises and counts talks
    reply = json.dumps({'memory': 'We talked.', 'feelings': {'Mjoll': 'fine'},
                        'promises': [{'text': 'Bring fish', 'by': 'Player', 'due_in_days': 1}], 'kept': []})
    summaries = FakeSummaries({'Mjoll': Params(long_talk, [mjoll])}, reply)
    hook = {'messages': None, 'npcs_to_summarize': [mjoll], 'npcs_in_conversation': People(), 'world_id': 'Player1',
            'is_reload': False, 'pending_shares': None, 'end_timestamp': 4.75, 'is_radiant': False, 'summaries': summaries}
    memory.summarize(hook, store)
    got = store.load('Mjoll', 'FE1DD821')
    check('summary hook stores the promise', memory.open_promises(got) == ['Bring fish'] and got['facts'][0]['due_day'] == 5, got['facts'])
    check('summary hook counts the talk', got['talks'] == 1, got['talks'])
    memory.summarize(hook, store)
    got = store.load('Mjoll', 'FE1DD821')
    check('the model is shown open promises', 'Bring fish' in summaries.calls[-1][1])
    check('second talk counted, promise not doubled', got['talks'] == 2 and len(got['facts']) == 1, got)
    memory.summarize(dict(hook, is_radiant=True), store)
    check('talks among NPCs add no promises', len(store.load('Mjoll', 'FE1DD821')['facts']) == 1)

    # what wins them over: rated once, in the summary call that was happening anyway
    check('an unrated NPC is asked about', 'what wins each of them over' in summaries.calls[0][1])
    rating = {'talk': 1, 'deeds': 3, 'care': 2, 'gifts': 2, 'physical': 1}
    summaries = FakeSummaries({'Mjoll': Params(long_talk, [mjoll])}, json.dumps({'memory': 'We fought.', 'values': {'Mjoll': rating}}))
    hook = dict(hook, summaries=summaries)
    memory.summarize(hook, store)
    got = store.load('Mjoll', 'FE1DD821')
    check('profile stored', got['profile'] == rating, got['profile'])
    memory.summarize(hook, store)
    check('a rated NPC is not asked again', 'what wins each of them over' not in summaries.calls[-1][1])
    other = dict(got, profile={})
    memory.add_profile(other, json.dumps({'values': {'Mjoll': {'talk': 9}}}), 'Mjoll')
    check('a broken rating is ignored', other['profile'] == {})
    memory.add_profile(other, json.dumps({'values': rating}), 'Mjoll')
    check('a rating with no name is accepted', other['profile'] == rating)
    check('bool ratings refused', memory.clean_profile(dict(rating, talk=True)) == {})
    line = memory.facts_text(memory.empty(), [], 40, 'Player', 'Mjoll', profile=rating)
    check('what matters most is told', 'What wins you over most: brave deeds done together.' in line, line)
    seen = {}
    out = memory.memory_text('stock', {'characters': [mjoll], 'world_id': 'Player1', 'profile_seen': lambda c, p: seen.update(p),
                                       'profile_overrides': {'Mjoll': dict(rating, physical=3, deeds=1)}}, store)
    check('your override wins', seen.get('physical') == 3 and 'physical closeness' in out and 'brave deeds' not in out, out[:200])

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
