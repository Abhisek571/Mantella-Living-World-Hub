"""Offline tests for custom events (server/living_world/events.py and its hooks in living_world/__init__.py): silent and
narrated events, undo, edits and take-backs in a live talk, in the talk's memory and in memories already written.
Run with a Python 3.11: test_events.py <repo server dir>"""
import json, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import embed, events as E, lw_state, memory
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


class UserMessage:
    """Shaped like Mantella's: the events sit in a name-mangled list."""
    def __init__(self, text, events=()):
        self.text = text
        self.__ingame_events = list(events)
    def events(self):
        return self.__ingame_events
    def __str__(self):
        return ' '.join(f"*{' '.join(e.split())}*" for e in self.__ingame_events) + ' ' + self.text


class Thread:
    def __init__(self, messages):
        self.messages = messages
    def __len__(self):
        return len(self.messages)
    def __getitem__(self, i):
        return self.messages[i]
    def get_talk_only(self, include_system_generated_messages=False):
        return list(self.messages)
    def transform_to_dict_representation(self, messages):
        return '\n'.join(str(m) for m in messages)


class Params:
    def __init__(self, thread, chars):
        self.messages, self.characters = thread, chars


class People:
    def get_player_name(self):
        return 'Player'


class FakeSummaries:
    def __init__(self, threads, reply, folder=None):
        self.threads, self.reply, self.calls = threads, reply, []
        self._Summaries__game = SimpleNamespace(conversation_folder_path=folder)
        self._Summaries__language_name = 'English'
    def get_threads_for_summarization(self, messages, npcs):
        return self.threads
    def group_shared_threads(self, threads):
        return [[name] for name in threads]
    def summarize_conversation(self, text, prompt):
        self.calls.append((text, prompt))
        return self.reply(text, prompt) if callable(self.reply) else self.reply


lydia = Char('Lydia', '0A2C94')

# --- what the player types --------------------------------------------------------------------------------------------
check('a typed event ends with a line break', E.is_custom('Lydia trips into the river\n') and not E.is_custom('Player equipped Iron Sword')
      and not E.is_custom('\n') and not E.is_custom(None))
check('narrated by default', E.parse('Lydia trips into the river\n') == (E.NARRATED, 'Lydia trips into the river'))
check('silent: prefix', E.parse('Silent:  Lydia trips\n') == (E.SILENT, 'Lydia trips'))
check('react: prefix wins over the silent setting', E.parse('react: Lydia trips\n', silent_default=True) == (E.NARRATED, 'Lydia trips'))
check('silent setting', E.parse('Lydia trips\n', silent_default=True) == (E.SILENT, 'Lydia trips'))
check('undo words', [E.parse(w)[0] for w in ('undo\n', 'Undo.\n', 'UNDO LAST\n', 'undo the dragon\n')] == ['undo', 'undo', 'undo', E.NARRATED])
check('a silent event tells the model nobody needs to answer', 'needs no answer' in E.sent_text('Lydia trips', E.SILENT)
      and E.sent_text('Lydia trips', E.NARRATED) == E.DONE_MARK + ' Lydia trips')

with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = str(Path(tmp) / 'data')
    conv = Path(tmp) / 'conversations'
    store = memory.MemoryStore(str(conv), 'P1')
    ctx = lambda first=False, day=3.5: {'player': 'Player', 'characters': [lydia], 'game_days': day, 'is_first': first}

    # --- the dialogue_events hook ------------------------------------------------------------------------------------
    E.end_talk()
    out = E.process(['The location is now Whiterun.', 'silent: Lydia trips into the river\n'], ctx(first=True), store)
    check('other events pass unchanged', out[0] == 'The location is now Whiterun.', out)
    check('a silent event goes on with its note', len(out) == 2 and out[1].startswith(E.DONE_MARK + ' Lydia trips into the river') and 'needs no answer' in out[1], out)
    rows = E.load(store)
    check('journal holds it', len(rows) == 1 and rows[0]['mode'] == E.SILENT and rows[0]['text'] == 'Lydia trips into the river'
          and rows[0]['npcs'] == [{'name': 'Lydia', 'ref_id': '0A2C94'}] and rows[0]['day'] == 3 and rows[0]['hour'] == 12, rows)
    check('journal file in the save folder', (Path(store.root) / 'custom_events.json').exists())
    talk1 = rows[0]['talk']

    out = E.process(['A wolf howls nearby\n', 'undo\n'], ctx(), store)
    check('undo in the same batch: neither reaches the model', out == [], out)
    rows = E.load(store)
    check('...and it is kept as taken back', rows[-1]['text'] == 'A wolf howls nearby' and rows[-1]['status'] == 'removed' and rows[-1]['gone'], rows[-1])

    out = E.process(['A guard waves at Lydia\n'], ctx(), store)
    out2 = E.process(['undo\n'], ctx(), store)
    rows = E.load(store)
    guard = next(r for r in rows if r['text'] == 'A guard waves at Lydia')
    check('undo in a later batch takes back the newest active one of this talk', out2 == [] and guard['status'] == 'removed'
          and guard['removed_by'] == 'undo' and not guard.get('gone'), guard)
    check('...and only that one', next(r for r in rows if r['text'] == 'Lydia trips into the river')['status'] == 'active')
    check('same talk until a new one starts', all(r['talk'] == talk1 for r in rows))

    # --- a live talk: every request is sent with the change ----------------------------------------------------------
    messages = [{'role': 'system', 'content': 'You are Lydia.'},
                {'role': 'user', 'content': '*' + E.sent_text('A guard waves at Lydia', E.NARRATED) + ' *  *'
                                            + E.sent_text('Lydia trips into the river', E.SILENT) + ' * Hello.'},
                {'role': 'assistant', 'content': 'Hello, my Thane.'}]
    E.fix_request(messages, store)
    check('a taken-back event is left out of the request, marks and all', messages[1]['content'].startswith('*' + E.DONE_MARK + ' Lydia trips') and 'guard' not in messages[1]['content'],
          messages[1]['content'])
    trips = next(r for r in rows if r['text'] == 'Lydia trips into the river')
    note = E.change(store, trips['id'], text='Lydia slips on the riverbank', mode=E.NARRATED)
    check('an edit in a live talk applies from the next reply', 'next reply' in note, note)
    E.fix_request(messages, store)
    check('an edited event is sent as edited', 'Lydia slips on the riverbank' in messages[1]['content'] and 'needs no answer' not in messages[1]['content']
          and messages[1]['content'].endswith('Hello.'), messages[1]['content'])
    check('the system message is never touched; the reply to the taken-back event is left out', messages[0]['content'] == 'You are Lydia.'
          and len(messages) == 2 and 'Hello, my Thane.' not in json.dumps(messages), messages)

    # --- the talk's end: the conversation is changed before it is summarized -----------------------------------------
    shown_trips = E.sent_text('Lydia trips into the river', E.SILENT)
    thread = Thread([UserMessage('Hello.', [E.sent_text('A guard waves at Lydia', E.NARRATED) + '\n', shown_trips + '\n']), UserMessage('Let us go to Riverwood.'),
                     UserMessage('I gave you a sword.'), UserMessage('Thank you.'), UserMessage('Farewell.')])
    replies = []
    summaries = FakeSummaries({'Lydia': Params(thread, [lydia])},
                              lambda text, prompt: replies.append(text) or json.dumps({'memory': 'We walked; I slipped on the riverbank; my Thane gave me a sword.',
                                                                                      'feelings': {'Lydia': 'Fond.'}, 'importance': 0.6}), str(conv))
    hook = {'messages': thread, 'npcs_to_summarize': [lydia], 'npcs_in_conversation': People(), 'world_id': 'P1', 'is_reload': False,
            'end_timestamp': 3.75, 'is_radiant': False, 'summaries': summaries}
    changed = E.fix_thread(thread, store)
    first = thread[0].events()
    check('taken-back and edited events changed in the conversation itself', changed == 2 and first == [E.sent_text('Lydia slips on the riverbank', E.NARRATED) + '\n'], first)
    memory.summarize(hook, store)
    check('the summary model never saw the taken-back or old text', replies and 'guard' not in replies[0] and 'trips' not in replies[0]
          and 'slips on the riverbank' in replies[0], replies)
    E.after_summary(hook, store)
    rows = E.load(store)
    slips = next(r for r in rows if r['id'] == trips['id'])
    entry = store.load('Lydia', '0A2C94')['recent'][-1]
    from living_world import archive
    check('the event notes the memory it went into', slips['remembered'] == [{'name': 'Lydia', 'ref_id': '0A2C94', 'memory_id': archive.entry_id(entry)}],
          slips['remembered'])
    check('the talk ended', E._talk['id'] is None)
    check('a removed event goes into no memory', not next(r for r in rows if r['text'] == 'A guard waves at Lydia').get('remembered'))

    # --- later: the memory already written is hidden and rewritten -------------------------------------------------
    asked = []
    def ask(system, text):
        asked.append((system, text))
        return 'We walked to Riverwood; my Thane gave me a sword.'
    note = E.change(store, slips['id'], remove=True, ask=ask)
    mem = store.load('Lydia', '0A2C94')
    hidden = memory.list_hidden(store, 'Lydia', '0A2C94')
    visible = [e for e in mem['recent'] if not e.get('hidden')]
    check('take back after the talk: the model rewrites the memory without it', asked and 'Lydia slips on the riverbank' in asked[0][0]
          and 'slipped on the riverbank' in asked[0][1], asked)
    check('...the old memory is hidden, not deleted', len(hidden) == 1 and 'slipped' in hidden[0]['text'] and hidden[0]['hidden']['by'] == E.HIDDEN_BY, hidden)
    check('...and the rewritten one is in its place with the same date and importance',
          visible and visible[-1]['text'] == 'We walked to Riverwood; my Thane gave me a sword.' and visible[-1]['day'] == 3
          and visible[-1]['hour'] == 18 and visible[-1]['importance'] == 0.6 and visible[-1]['custom_event'] == slips['id'], visible[-1:])
    check('...the note says what was done', 'rewritten' in note and 'Unhide' in note, note)
    rendered = memory.render(mem, 1500, store)
    check('the model no longer reads the event', 'slipped' not in rendered and 'We walked to Riverwood' in rendered, rendered)

    note = E.restore(store, slips['id'])
    mem = store.load('Lydia', '0A2C94')
    visible = [e for e in mem['recent'] if not e.get('hidden')]
    check('restore: the original memory is back and the rewrite hidden', len(visible) == 1 and 'slipped' in visible[0]['text']
          and E.find(store, slips['id'])['status'] == 'active', [e['text'] for e in visible])

    # an edit with no model reachable: a correction is added, nothing hidden
    note = E.change(store, slips['id'], text='Lydia fell into the river', ask=None)
    mem = store.load('Lydia', '0A2C94')
    visible = [e for e in mem['recent'] if not e.get('hidden')]
    check('edit without a model: a correction memory, the old one kept', len(visible) == 2 and 'slipped' in visible[0]['text']
          and visible[1]['text'].startswith('What really happened that day: Lydia fell into the river'), [e['text'] for e in visible])
    # a take-back with no model: the memory is hidden
    E.change(store, slips['id'], remove=True, ask=lambda s, t: '')
    hidden = memory.list_hidden(store, 'Lydia', '0A2C94')
    check('take back without a usable reply: the memory holding it is hidden', any('What really happened' in h['text'] for h in hidden), hidden)
    check('taking back twice is refused', 'already' in E.change(store, slips['id'], remove=True))
    check('editing an unknown event is refused', 'no longer' in E.change(store, 'nope', text='x'))

    # edit with the model, then take back, then restore: the edited memory comes back, not the first one
    faendal = Char('Faendal', '01A69E')
    E.end_talk()
    E.process(['Faendal finds a bear trap\n'], {'player': 'Player', 'characters': [faendal], 'game_days': 7.5, 'is_first': True}, store)
    bear = E.load(store)[-1]
    thread = Thread([UserMessage('Look out.', ['Faendal finds a bear trap\n'])] + [UserMessage(f'line {i}') for i in range(4)])
    hook = dict(hook, messages=thread, npcs_to_summarize=[faendal], end_timestamp=7.75,
                summaries=FakeSummaries({'Faendal': Params(thread, [faendal])}, json.dumps({'memory': 'I found a bear trap by the river.'}), str(conv)))
    E.fix_thread(thread, store)
    memory.summarize(hook, store)
    E.after_summary(hook, store)
    E.change(store, bear['id'], text='Faendal finds a wolf den', ask=lambda s, t: 'I found a wolf den by the river.')
    E.change(store, bear['id'], remove=True, ask=lambda s, t: 'I walked by the river.')
    shown = lambda: [e['text'] for e in store.load('Faendal', '01A69E')['recent'] if not e.get('hidden')]
    check('edit then take back: only the last rewrite shows', shown() == ['I walked by the river.'], shown())
    E.restore(store, bear['id'])
    check('restore after edit and take-back: the edited memory is back', shown() == ['I found a wolf den by the river.'], shown())
    check('...and a later edit works on it', 'rewritten' in E.change(store, bear['id'], text='Faendal finds a fox den',
                                                                     ask=lambda s, t: 'I found a fox den by the river.')
          and shown() == ['I found a fox den by the river.'], shown())

    # --- the list in the Memory tab --------------------------------------------------------------------------------
    listed = E.listing(store)
    check('newest first', listed[0]['at'] >= listed[-1]['at'])
    check('per NPC', [r['text'] for r in E.listing(store, 'Faendal')] == ['Faendal finds a fox den'] and E.npc_names(store) == ['Faendal', 'Lydia']
          and all(r['npcs'][0]['name'] == 'Lydia' for r in E.listing(store, 'Lydia')) and E.listing(store, 'Ysolda') == [])
    table = E.table(listed)
    check('table rows', all(len(r) == 5 for r in table) and any(r[3] == 'taken back' for r in table), table)
    check('labels carry the id', all(f"[{r['id']}]" in E.label(r) for r in listed))

    # --- the Hub's hooks --------------------------------------------------------------------------------------------
    hub = FakeSummaries({}, 'unused', str(conv))
    E.end_talk()
    out = living_world._dialogue_events(['Lydia sneezes\n'], {'player': 'Player', 'characters': [lydia], 'game_days': 5.5, 'world_id': 'P1',
                                                              'summaries': hub, 'is_first': False})
    check('the dialogue_events hook records custom events', out == [E.sent_text('Lydia sneezes', E.NARRATED) + '\n'] and E.load(store)[-1]['text'] == 'Lydia sneezes', out)
    real_load = living_world.settings.load
    living_world.settings.load = lambda *a: dict(real_load(*a), custom_events_silent=True)
    try:
        out = living_world._dialogue_events(['Lydia yawns\n'], {'player': 'Player', 'characters': [lydia], 'game_days': 5.5, 'world_id': 'P1',
                                                                'summaries': hub, 'is_first': False})
        check('the silent setting makes every custom event silent', 'needs no answer' in out[0], out)
    finally:
        living_world.settings.load = real_load
    E.change(store, E.load(store)[-2]['id'], remove=True)
    request = [{'role': 'user', 'content': '*' + E.sent_text('Lydia sneezes', E.NARRATED) + ' * What now?'}]
    living_world._extra_text({'messages': request})
    check('the extra_user_text hook sends the talk with the change', request[0]['content'] == 'What now?', request)
    check('without a store nothing breaks', E.process(['x\n'], {}, None) == [E.sent_text('x', E.NARRATED) + '\n'] and E.fix_thread(None, store) == 0)

    # --- a custom event already happened: marked so, never done again by an action, never undone by a cancelled one ----
    check('the mark is never added twice (an event handled again)', E.parse(E.sent_text('Lydia sneezes', E.NARRATED) + '\n') == (E.NARRATED, 'Lydia sneezes')
          and E.parse(E.sent_text('Lydia yawns', E.SILENT) + '\n') == (E.SILENT, 'Lydia yawns'))
    gift = '(' + E.sent_text('Player gave Lydia a silver necklace as a gift', E.NARRATED) + ')\nI hope you like it.'
    trade = [{'type': 'function', 'function': {'name': n}} for n in ('TakeGift', 'AskItem', 'GiveItem', 'OfferTrade', 'AskGold', 'GiveGold', 'Follow')]
    kept = lambda messages: [t['function']['name'] for t in E.filter_tools(trade, messages)]
    check('the reply after a custom event: no transfer action is offered', kept([{'role': 'user', 'content': gift}]) == ['Follow'],
          kept([{'role': 'user', 'content': gift}]))
    gold = '(' + E.sent_text('Player put 500 gold on the table', E.NARRATED) + ')'
    check('a custom event about gold: the real gold actions stay (gold is never made by text)',
          kept([{'role': 'user', 'content': gold}]) == ['AskGold', 'GiveGold', 'Follow'], kept([{'role': 'user', 'content': gold}]))
    check('the turn after that (no custom event in the newest message): everything is back',
          kept([{'role': 'user', 'content': gift}, {'role': 'assistant', 'content': 'Thank you.'}, {'role': 'user', 'content': 'Do you like it?'}])
          == [t['function']['name'] for t in trade])
    check('an answer after an action result in the same turn: still none', kept([{'role': 'user', 'content': gift}, {'role': 'assistant', 'content': ''},
          {'role': 'tool', 'content': 'done'}]) == ['Follow'])
    check('list content works too, junk never raises', kept([{'role': 'user', 'content': [{'type': 'text', 'text': gift}]}]) == ['Follow']
          and E.filter_tools(trade, None) == trade and E.blocked_actions([5, None]) == set())
    # World's one Trade action: the blocked kinds leave its "kind" choice, the action goes when no kind is left
    one = {'type': 'function', 'function': {'name': 'Trade', 'parameters': {'type': 'object', 'properties': {'kind': {'type': 'string',
           'enum': ['give_gold', 'ask_gold', 'give_item', 'ask_item', 'offer_trade', 'take_gift']}}}}}
    kinds = lambda messages: [(t['function']['name'], t['function']['parameters']['properties']['kind']['enum']) if t['function']['name'] == 'Trade'
                              else t['function']['name'] for t in E.filter_tools([one, {'type': 'function', 'function': {'name': 'Follow'}}], messages)]
    check('Trade after a custom event: not offered (every kind moves goods or gold)', kinds([{'role': 'user', 'content': gift}]) == ['Follow'],
          kinds([{'role': 'user', 'content': gift}]))
    check('Trade after a custom event about gold: only the gold kinds stay',
          kinds([{'role': 'user', 'content': gold}]) == [('Trade', ['give_gold', 'ask_gold']), 'Follow'], kinds([{'role': 'user', 'content': gold}]))
    check('Trade: the offered tool itself is not changed', one['function']['parameters']['properties']['kind']['enum'][-1] == 'take_gift')
    check('Trade with no custom event: every kind', kinds([{'role': 'user', 'content': 'Hello.'}])[0][1] == one['function']['parameters']['properties']['kind']['enum'])
    real_load = living_world.settings.load
    living_world.settings.load = lambda *a: dict(real_load(*a), action_filter=False, short_actions=False)
    try:
        hooked = [t['function']['name'] for t in living_world._filter_tools(list(trade), {'messages': [{'role': 'user', 'content': gift}]})]
        check('the filter_tools hook drops the transfer actions after a custom event', hooked == ['Follow'], hooked)
    finally:
        living_world.settings.load = real_load
    E.end_talk()
    E.process(['Player gave Lydia a silver necklace as a gift\n'], ctx(first=True), store)
    out = E.process(['(Player opened the gift menu but gave Lydia nothing.)', '(Nothing happened: Player chose not to hand over the 50 gold.)', 'Lydia waves'], ctx(), store)
    check('a trade that came to nothing after a custom event: told it undoes nothing', out[0].endswith(E.NOTHING_NOTE) and out[1].endswith(E.NOTHING_NOTE)
          and out[2] == 'Lydia waves', out)
    E.end_talk()
    E.process(['Lydia waves\n'], ctx(first=True), store)
    E.change(store, E.load(store)[-1]['id'], remove=True)
    out = E.process(['(Nothing happened: Player chose not to hand over the 50 gold.)'], ctx(), store)
    check('no active custom event in the talk: the line is left as it is', out == ['(Nothing happened: Player chose not to hand over the 50 gold.)'], out)
    E.process(['Player gave Lydia 300 gold\n', 'Player and Lydia got married\n', 'Lydia moved into the player\'s house\n'], ctx(), store)
    facts = E.established(store, 'Lydia')
    check('established facts: the necklace is one, gold and game-owned claims are not, a taken-back one is not',
          'Player gave Lydia a silver necklace as a gift' in facts and not any('gold' in f or 'married' in f or 'house' in f or f == 'Lydia waves' for f in facts), facts)
    block = E.established_text(store, 'Lydia')
    check('established text tells the writer never to undo them', 'silver necklace' in block and 'never write that they did not happen' in block, block)
    check('no events for someone else', E.established(store, 'Ysolda') == [] and E.established_text(store, 'Ysolda') == '' and E.established(None, 'Lydia') == [])
    E.end_talk()

    # --- the Memory page sections, with a stand-in for Gradio ---------------------------------------------------------
    from living_world import events_ui, bio_evolve
    class Comp:
        def __init__(self, kind, *a, **k):
            self.kind, self.args, self.kwargs, self.handlers = kind, a, k, {}
        def __enter__(self):
            return self
        def __exit__(self, *e):
            return False
        def __getattr__(self, event):
            def on(fn, inputs=None, outputs=None, **_):
                self.handlers[event] = fn
                return self
            return on
    class Gr:
        def __init__(self):
            self.made = []
        def __getattr__(self, kind):
            def make(*a, **k):
                c = Comp(kind, *a, **k)
                self.made.append(c)
                return c
            return make
    gr = Gr()
    events_ui.build(gr, str(conv))
    buttons = {c.args[0]: c for c in gr.made if c.kind == 'Button' and c.args}
    drops = [c for c in gr.made if c.kind == 'Dropdown']
    check('page sections built', {'Save edit', 'Take back', 'Restore'} <= set(buttons) and 'Save note' not in buttons, sorted(buttons))
    check('the event list starts filled', any(c.kind == 'Dataframe' and c.kwargs.get('value') for c in gr.made))
    E.end_talk()
    E.process(['Lydia hums a tune\n'], {'player': 'Player', 'characters': [lydia], 'game_days': 9.5, 'is_first': True}, store)
    hum = E.load(store)[-1]
    said = buttons['Save edit'].handlers['click']('P1', 'Everyone', E.label(hum), 'Lydia sings a song', 'Silent (known, no reply)')
    check('Save edit from the page', E.find(store, hum['id'])['text'] == 'Lydia sings a song' and E.find(store, hum['id'])['mode'] == E.SILENT
          and 'Saved' in said[-1], said[-1])
    buttons['Take back'].handlers['click']('P1', 'Everyone', E.label(hum), '', 'Narrated (NPCs react)')
    check('Take back from the page', E.find(store, hum['id'])['status'] == 'removed')
    buttons['Restore'].handlers['click']('P1', 'Everyone', E.label(hum))
    check('Restore from the page', E.find(store, hum['id'])['status'] == 'active')

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
