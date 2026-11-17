"""Offline tests for how NPCs change (server/living_world/bio_evolve.py and its hooks in living_world/__init__.py): when
the note is written, what the model is asked, the cap, locks and edits that win, reset, and where it goes in the prompt.
Run with a Python 3.11: test_bio_evolve.py <repo server dir>"""
import json, os, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import bio_evolve as B, embed, lw_state, memory
memory.SUMMARY_RETRY_SECONDS = 0
embed.use(None)

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


class Char:
    def __init__(self, name, ref_id, bio='Lydia is a housecarl of Whiterun, loyal and dry-witted.'):
        self.name, self.ref_id, self.bio = name, ref_id, bio


class Summaries:
    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self._Summaries__language_name = 'English'
    def summarize_conversation(self, text, prompt):
        self.calls.append((text, prompt))
        return self.reply(text, prompt) if callable(self.reply) else self.reply


lydia = Char('Lydia', '0A2C94')


def remember(store, texts, start_day=1, importance=0.3, talks=None):
    mem = store.load('Lydia', '0A2C94')
    for i, text in enumerate(texts):
        mem['recent'].append({'day': start_day + i, 'hour': 12, 'text': text, 'witnesses': ['Lydia'], 'importance': importance})
    mem['talks'] = len(mem['recent']) if talks is None else talks
    store.save('Lydia', '0A2C94', mem)
    return mem


check('clip keeps whole sentences', B.clip('One. Two two. ' + 'x' * 500, 20) == 'One. Two two.', B.clip('One. Two two. ' + 'x' * 500, 20))
check('clip leaves short text alone', B.clip('  "Short note."  ') == 'Short note.')

with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = str(Path(tmp) / 'data')
    store = memory.MemoryStore(str(Path(tmp) / 'conversations'), 'P1')

    state = B.load(store, 'Lydia', '0A2C94')
    check('no file: an empty note', state == B.empty())
    mem = remember(store, ['We met in Whiterun.', 'We fought a dragon together.'], talks=2)
    check('not due after 2 small talks', not B.due(state, mem, 5))
    mem = remember(store, ['Small talk about the weather.', 'She showed me her sword.', 'We ate at the Bannered Mare.'], start_day=3)
    check('due after 5 talks', B.due(state, mem, 5))
    check('never when locked', not B.due(dict(state, locked=True), mem, 5))
    check('never when off (every 0)', not B.due(state, mem, 0))
    big = dict(memory.empty(), talks=1, recent=[{'day': 1, 'hour': 1, 'text': 'I nearly died; my Thane saved me.', 'importance': 1.0},
                                                {'day': 2, 'hour': 1, 'text': 'My Thane married me.', 'importance': 1.0}])
    check('due sooner after important memories', B.due(B.empty(), big, 5))
    check('never from a single memory', not B.due(B.empty(), dict(big, recent=big['recent'][:1]), 5))

    # writing it
    s = Summaries('Lydia has come to trust her Thane with her life, and smiles more than she used to.')
    out = B.write(store, 'Lydia', '0A2C94', lydia.bio, s.summarize_conversation, every=5)
    state = B.load(store, 'Lydia', '0A2C94')
    check('one summary call', len(s.calls) == 1, len(s.calls))
    check('the model gets the bio, the note so far and the new memories', 'housecarl of Whiterun' in s.calls[0][0]
          and '(none yet)' in s.calls[0][0] and 'We fought a dragon together.' in s.calls[0][0] and '[Day 2' in s.calls[0][0], s.calls[0][0])
    check('the prompt caps the length and forbids rewriting the bio', str(B.MAX_CHARS) in s.calls[0][1] and 'Never repeat the bio' in s.calls[0][1] and 'Keep only what is still true' in s.calls[0][1])
    check('saved', out == state['text'] and state['auto'] and state['talks'] == 5 and state['after'] == [5, 12], state)
    check('not due again right away', not B.due(state, store.load('Lydia', '0A2C94'), 5))
    check('nothing asked when not due', B.write(store, 'Lydia', '0A2C94', lydia.bio, s.summarize_conversation) is None and len(s.calls) == 1)

    hood = memory.MemoryStore(os.path.join(tmp, 'hood'), 'P1')
    for i in range(6):
        mem = hood.load('Ysolda', '0A1B2C')
        mem['recent'].append({'day': 1 + i, 'hour': 12, 'text': f'Talked with a hooded stranger, time {i}.', 'witnesses': ['Ysolda']})
        mem['talks'] = len(mem['recent'])
        hood.save('Ysolda', '0A1B2C', mem)
    B.write(hood, 'Ysolda', '0A1B2C', 'A merchant.', lambda t, p: 'Ysolda thinks about Dovahkiin often.\nOTHERS: Ysolda wears the ring Dovahkiin gave her.',
            every=5, context={'player': 'Dovahkiin', 'hooded': True})
    hooded_state = B.load(hood, 'Ysolda', '0A1B2C')
    check('hooded: neither the Now paragraph nor the note for others names the player', 'Dovahkiin' not in hooded_state['text']
          and hooded_state['others'] and 'Dovahkiin' not in hooded_state['others'], hooded_state)

    # the next update builds on the note so far; old text goes to history
    remember(store, [f'Day {d} together.' for d in range(6, 11)], start_day=6)
    s2 = Summaries('x' * 900)
    B.write(store, 'Lydia', '0A2C94', lydia.bio, s2.summarize_conversation)
    state = B.load(store, 'Lydia', '0A2C94')
    check('the note so far goes to the model', 'trust her Thane' in s2.calls[0][0] and 'We met in Whiterun.' in s2.calls[0][0], s2.calls[0][0])
    check('capped', len(state['text']) <= B.MAX_CHARS + 3, len(state['text']))
    check('earlier text kept in history', state['history'][-1]['text'].startswith('Lydia has come to trust'), state['history'])

    # NONE: nothing lasting changed
    remember(store, [f'More days {d}.' for d in range(11, 16)], start_day=11)
    before = B.load(store, 'Lydia', '0A2C94')['text']
    check('NONE keeps the note', B.write(store, 'Lydia', '0A2C94', lydia.bio, lambda t, p: 'NONE') == ''
          and B.load(store, 'Lydia', '0A2C94')['text'] == before and B.load(store, 'Lydia', '0A2C94')['after'] == [15, 12])

    # the player's own text and lock win
    state = B.edit(store, 'Lydia', '0A2C94', text='Lydia now calls the player by name.')
    check('edit saved as the player\'s own', state['text'] == 'Lydia now calls the player by name.' and not state['auto'])
    remember(store, [f'Later {d}.' for d in range(16, 21)], start_day=16)
    def edited_meanwhile(text, prompt):
        B.edit(store, 'Lydia', '0A2C94', text='Typed while the request ran.')
        return 'The model text.'
    B.write(store, 'Lydia', '0A2C94', lydia.bio, edited_meanwhile)
    check('an edit made while the request ran wins', B.load(store, 'Lydia', '0A2C94')['text'] == 'Typed while the request ran.')
    B.edit(store, 'Lydia', '0A2C94', locked=True)
    check('locked: never asked', B.write(store, 'Lydia', '0A2C94', lydia.bio, lambda t, p: 'nope', force=True) is None
          and B.load(store, 'Lydia', '0A2C94')['text'] == 'Typed while the request ran.')
    state = B.reset(store, 'Lydia', '0A2C94')
    check('reset clears the note, keeps the lock and starts counting from now', state['text'] == '' and state['locked']
          and state['after'] == [20, 12] and not B.new_memories(store.load('Lydia', '0A2C94'), state))
    B.edit(store, 'Lydia', '0A2C94', text='Lydia is warmer now.', locked=False)
    check('people with a note', B.people_with(store) == [('Lydia', '0A2C94')], B.people_with(store))

    # in the prompt: after the bios, never instead of them
    text = B.prompt_text(store, [('Lydia', '0A2C94'), ('Faendal', '01A69E')])
    check('prompt text for those with a note', text.startswith('Now, as Lydia sees it:') and 'Lydia is warmer now.' in text
          and 'Faendal' not in text, text)
    parts = B.add_to_parts({'background': 'Lydia is a housecarl.', 'history': 'memories'}, text)
    check('goes at the end of the background part', parts['background'].startswith('Lydia is a housecarl.') and parts['background'].endswith('Lydia is warmer now.')
          and parts['history'] == 'memories', parts)
    check('no background part: the whole text', B.add_to_parts({'mantella': 'All of it.'}, text)['mantella'].endswith('warmer now.'))
    check('nothing to add: unchanged', B.add_to_parts({'background': 'b'}, '') == {'background': 'b'})

    # the summarize hook: after the memory is saved
    store2 = memory.MemoryStore(str(Path(tmp) / 'conversations'), 'P2')
    mem = remember(store2, [f'Talk {d}.' for d in range(1, 6)])
    s = Summaries('Lydia has grown fond of travelling.')
    ctx = {'npcs_to_summarize': [lydia], 'summaries': s, 'is_reload': False}
    check('off in the settings: nothing', B.after_summary(ctx, store2, {'bio_changes': False, 'bio_changes_talks': 5}, background=False) == [])
    check('a trim mid-talk: nothing', B.after_summary(dict(ctx, is_reload=True), store2, {'bio_changes': True, 'bio_changes_talks': 5}, background=False) == [])
    check('due: written', B.after_summary(ctx, store2, {'bio_changes': True, 'bio_changes_talks': 5}, background=False) == ['Lydia has grown fond of travelling.']
          and 'housecarl of Whiterun' in s.calls[0][0])
    check('not due again: nothing asked', B.after_summary(ctx, store2, {'bio_changes': True, 'bio_changes_talks': 1}, background=False) == []
          and len(s.calls) == 1)
    remember(store2, [f'Talk {d}.' for d in range(6, 11)], start_day=6)
    queued = B.after_summary(ctx, store2, {'bio_changes': True, 'bio_changes_talks': 5})
    B._queue.join()
    check('in the background: queued and written by the worker', queued == [lydia] and len(s.calls) == 2
          and B.load(store2, 'Lydia', '0A2C94')['after'] == [10, 12], (queued, len(s.calls)))

    # the Hub's system_parts hook puts it after the bios (the game has written Lydia's file: an adult)
    os.makedirs(os.path.join(lw_state.DATA_DIR, 'npc'), exist_ok=True)
    with open(os.path.join(lw_state.DATA_DIR, 'npc', '0A2C94.json'), 'w', encoding='utf-8') as f:
        json.dump({'string': {'name': 'Lydia', 'ref_id': '000A2C94'}, 'int': {'minor': 0}}, f)
    with open(os.path.join(lw_state.DATA_DIR, 'conversation.json'), 'w', encoding='utf-8') as f:
        json.dump({'stringList': {'speakers': ['0A2C94']}}, f)
    living_world._last_store.update(store=store, people=[('Lydia', '0A2C94')])
    mantella = ('# Overview\nYou are in Skyrim.\n\n# Background\nLydia is a housecarl.\n\n# History\nBelow is a summary of past events.\n\n'
                '# Current Scene\nIt is noon.\nRespond as Lydia.')
    parts = living_world._system_parts({'mantella': mantella}, {})
    bg = parts.get('background', '')
    check('system_parts: Now follows the bio', 'Lydia is a housecarl.' in bg and 'Now, as Lydia sees it: Lydia is warmer now.' in bg
          and bg.index('Lydia is a housecarl.') < bg.index('Now, as Lydia sees it'), bg)
    real_load = living_world.settings.load
    living_world.settings.load = lambda *a: dict(real_load(*a), bio_changes=False)
    try:
        parts = living_world._system_parts({'mantella': mantella}, {})
        check('system_parts: the setting turns it off', 'Now, as Lydia' not in json.dumps(parts), parts.get('background'))
    finally:
        living_world.settings.load = real_load

    # one lock per Now file: a reason marked due while the background writer saves is never lost
    import threading
    race = memory.MemoryStore(str(Path(tmp) / 'race'), 'P1')
    remember(race, [f'Race talk {d}.' for d in range(1, 8)])
    real_load, armed, marker = B.load, {'on': False}, {}

    def racing_load(*args):
        state = real_load(*args)
        if armed['on']:  # the writer's second read: another caller marks a reason right now
            armed['on'] = False
            marker['t'] = threading.Thread(target=B.mark_due, args=(race, 'Lydia', '0A2C94', 'partner changed in the game'))
            marker['t'].start()
            marker['t'].join(0.3)  # without the lock it finished here, then the writer saved over it
        return state

    def ask(text, prompt):
        armed['on'] = True
        return 'Lydia is calm today.'
    B.load = racing_load
    try:
        B.write(race, 'Lydia', '0A2C94', 'bio', ask, force=True)
    finally:
        B.load = real_load
    marker['t'].join(5)
    state = B.load(race, 'Lydia', '0A2C94')
    check('lock: the reason marked during the save is kept', 'partner changed in the game' in state['due']
          and state['text'] == 'Lydia is calm today.', state)
    for fn, args in ((B.add_gap, ('a gap',)), (B.edit, ()), (B.clear_gaps, ()), (B.reset, ()), (B.roll_back, (1,))):
        lock = B.file_lock(race, 'Lydia', '0A2C94')
        done = threading.Event()
        lock.acquire()
        try:
            worker = threading.Thread(target=lambda: (fn(race, 'Lydia', '0A2C94', *args), done.set()))
            worker.start()
            check(f'lock: {fn.__name__} waits for the file lock', not done.wait(0.2))
        finally:
            lock.release()
        worker.join(5)
        check(f'lock: {fn.__name__} then runs', done.is_set())

    # custom events reach the Now writer as true (live test 3: a cancelled gift menu rewrote "given a necklace" away)
    remember(race, [f'Necklace day {d}.' for d in range(16, 21)], start_day=16)
    s4 = Summaries('Lydia wears the silver necklace her Thane gave her.')
    events_block = 'Custom events that really happened to Lydia (true and complete; never write that they did not happen):\n- Player gave Lydia a silver necklace'
    B.write(race, 'Lydia', '0A2C94', lydia.bio, s4.summarize_conversation, force=True, context={'events': events_block})
    check('the Now writer gets the custom events and is told they are never undone', s4.calls and 'silver necklace' in s4.calls[0][0]
          and 'does not undo them' in s4.calls[0][1], s4.calls[:1])
    s5 = Summaries('Unchanged.')
    B.write(race, 'Lydia', '0A2C94', lydia.bio, s5.summarize_conversation, force=True, context={})
    check('without custom events the input has no such block', s5.calls and 'Custom events that really happened' not in s5.calls[0][0])
    check('the memory writer is told a custom event stays true', 'Already happened, and complete:' in memory.SUMMARY_PROMPT
          and 'never write that it did not happen' in memory.SUMMARY_PROMPT)


print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
