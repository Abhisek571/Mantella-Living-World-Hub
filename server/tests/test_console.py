"""Offline tests for the Console button (server/living_world/console.py and its hooks in living_world/__init__.py).
The game's file is shaped like PapyrusUtil writes it (MLW_Console.psc).
Run with a Python 3.11: test_console.py <repo server dir>"""
import json, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import console as K, lw_state, memory, settings

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)

LYDIA, FAENDAL = '000A2C94', '0001A69E'
VALUES = dict(settings.DEFAULTS)
TOOLS = [{'type': 'function', 'function': {'name': n, 'description': n + '.'}} for n in ('Attack', 'Console', 'Follow')]


def game_file(data_dir, entries, done=()):
    lists = {k: [] for k in ('key', 'text', 'refs', 'names', 'time', 'player', 'tool')}
    for e in entries:
        for k in lists:
            lists[k].append(e[k])
    lists['done_key'] = [d[0] for d in done]
    lists['done_text'] = [d[1] for d in done]
    (Path(data_dir) / K.GAME_FILE).write_text(json.dumps({'stringList': lists}), encoding='utf-8')


def entry(key, text, refs=(LYDIA,), names=('Lydia',), time=41.5, player='Dragonborn', tool=1):
    return {'key': key, 'text': text, 'refs': ','.join(refs), 'names': '|'.join(names), 'time': f'{time:.6f}',
            'player': player, 'tool': str(tool)}


def msgs(users):
    out = [{'role': 'system', 'content': 'sys'}]
    for i in range(users):
        out += [{'role': 'user', 'content': f'u{i}'}, {'role': 'assistant', 'content': f'a{i}'}]
    return out[:-1]


def names(tools):
    return [t['function']['name'] for t in tools]


def split(ctx, store=None, values=VALUES, now=1000.0):
    rest, extra = K.split(TOOLS, ctx, store, values, 'Dragonborn', 41, now)
    return names(rest), names(extra)


# --- cleaning ---------------------------------------------------------------------------------------------------
check('at most 5 commands', K.clean_commands([f'player.additem f {i}' for i in range(1, 9)]) ==
      [f'player.additem f {i}' for i in range(1, 6)])
check('newlines and control characters become spaces',
      K.clean_commands(['player.additem f 2000\nplayer.kill', 'fw\t81a\x00\x07', ' tgm\x7f']) ==
      ['player.additem f 2000 player.kill', 'fw 81a', 'tgm'], K.clean_commands(['player.additem f 2000\nplayer.kill', 'fw\t81a\x00\x07']))
check('an over-long command is dropped, never cut', K.clean_commands(['x' * (K.MAX_COMMAND + 1), 'tgm']) == ['tgm'])
check('a command of exactly the cap is kept', K.clean_commands(['y' * K.MAX_COMMAND]) == ['y' * K.MAX_COMMAND])
check('empty and non-text items dropped', K.clean_commands(['', '   ', None, 5, {'a': 1}, 'tcl']) == ['tcl'])
check('a single text is one command; junk is none', K.clean_commands('tgm') == ['tgm'] and K.clean_commands(None) == [] and K.clean_commands({'x': 1}) == [])
check('summary text: one line, capped', K.clean_text('a\nb\r\n c' + 'z' * 500, K.MAX_SUMMARY) == ('a b c' + 'z' * 500)[:K.MAX_SUMMARY])
check('clean_text of junk is empty', K.clean_text(None, 10) == '' and K.clean_text(12, 10) == '')

# --- reading the game's file ------------------------------------------------------------------------------------
data = {'stringList': {'key': ['k1', '', 'k3'], 'text': ['give me 2000 gold\n', 'x', ''], 'refs': ['000A2C94,../x,0001A69E', '', ''],
                       'names': ['Lydia|Faendal', '', ''], 'time': ['41.5', '', ''], 'player': ['Dragonborn', '', ''], 'tool': ['1', '', '']}}
q = K.read_queue(data)
check('queue: only rows with key and text', [e['key'] for e in q] == ['k1'], q)
check('queue: path tricks in refs dropped, names follow', q and q[0]['refs'] == ['000A2C94', '0001A69E'] and q[0]['text'] == 'give me 2000 gold', q)
check('queue: broken file reads empty', K.read_queue({'stringList': 5}) == [] and K.read_queue([]) == [] and K.read_done({}) == [])
check('queue: missing tool counts as missing', K.read_queue({'stringList': {'key': ['a'], 'text': ['t']}})[0]['tool'] == 0)

# --- one turn only ------------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    lw_state.DATA_DIR = str(root / 'channel'); (root / 'channel').mkdir()
    store = memory.MemoryStore(str(root / 'conversations'), 'Dragonborn1')
    K.reset()

    rest, extra = split({'messages': msgs(3)}, store)
    check('no wish: the Console action is never offered', extra == [] and 'Console' not in rest and rest == ['Attack', 'Follow'], (rest, extra))

    game_file(lw_state.DATA_DIR, [entry('41.5-1', 'give me 2000 gold', refs=(LYDIA, FAENDAL), names=('Lydia', 'Faendal'))])
    check('keyword check: never offered as a "Console:" keyword', split({'keyword_actions': True}, store)[1] == [])
    rest, extra = split({'messages': msgs(4)}, store)
    check('the turn after the wish: offered', extra == ['Console'] and rest == ['Attack', 'Follow'], (rest, extra))
    note = K.newest_text(msgs(4), 'Dragonborn')
    check('note: has the wish and the ref ids', 'give me 2000 gold' in note and 'Lydia 000A2C94' in note and 'Faendal 0001A69E' in note, note)
    check('note: no command list, only the minimal facts', 'player.' in note and 'gold is f' in note and 'additem' not in note.lower(), note)
    check('note: said once', K.newest_text(msgs(4), 'Dragonborn') == '')
    # a child in the talk (the game marks the speaker minor): their ref id is never in the note; their name still is
    (root / 'channel' / 'npc').mkdir()
    (root / 'channel' / 'npc' / '01A69E.json').write_text(json.dumps({'string': {'name': 'Faendal', 'ref_id': FAENDAL},
                                                                       'int': {'minor': 1}}), encoding='utf-8')
    (root / 'channel' / 'conversation.json').write_text(json.dumps({'stringList': {'speakers': ['0A2C94', '01A69E']}}), encoding='utf-8')
    K._state['pending']['told'] = False
    child_note = K.newest_text(msgs(4), 'Dragonborn')
    check('note: a child ref id is left out', FAENDAL not in child_note and 'Lydia 000A2C94' in child_note
          and 'Faendal' in child_note, child_note)
    (root / 'channel' / 'npc' / '01A69E.json').unlink()
    (root / 'channel' / 'conversation.json').unlink()
    check('same turn again (an answer after an action result): still there, the tool list stays the same',
          split({'messages': msgs(4) + [{'role': 'assistant', 'content': ''}, {'role': 'tool', 'content': 'ok'}]}, store)[1] == ['Console'])
    check('the next turn: gone', split({'messages': msgs(5)}, store)[1] == [])
    check('and gone for good', split({'messages': msgs(4)}, store)[1] == [] and K.newest_text(msgs(4)) == '')
    log = K.load(store)['log']
    check('log written: the wish, offered', log and log[-1]['wish'] == 'give me 2000 gold' and log[-1]['status'] == 'offered', log)

    # a wish expires: one turn of the talk it was typed in, never another talk, never after the action came back once
    called = lambda base: base + [{'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'type': 'function',
                                  'function': {'name': 'Console', 'arguments': '{}'}}]}, {'role': 'tool', 'content': 'ok'}]
    def new_wish(key, now=1000.0):
        game_file(lw_state.DATA_DIR, [entry(key, 'make it rain')])
        return split({'keyword_actions': True}, store, now=now)  # read; its turn comes with the next request
    first_turn = msgs(1)
    new_wish('43.1-1')
    check('bound on the first request of a talk', split({'messages': first_turn}, store)[1] == ['Console'])
    K.talk_ended()
    check('the talk ended: never offered in the next talk (also turn 1)', split({'messages': msgs(1)}, store)[1] == [])
    new_wish('43.1-2')
    check('bound on turn 3', split({'messages': msgs(3)}, store)[1] == ['Console'])
    check('a talk with fewer messages (another talk, its end missed): dropped', split({'messages': msgs(1)}, store)[1] == []
          and split({'messages': msgs(3)}, store)[1] == [])
    new_wish('43.1-3')
    (root / 'channel' / 'conversation.json').write_text(json.dumps({'int': {'talk_open': 1}, 'string': {'talk_id': 'talkA'}}), encoding='utf-8')
    check('bound in talk A', split({'messages': msgs(2)}, store)[1] == ['Console'])
    (root / 'channel' / 'conversation.json').write_text(json.dumps({'int': {'talk_open': 1}, 'string': {'talk_id': 'talkB'}}), encoding='utf-8')
    check('another talk id with the same turn: dropped', split({'messages': msgs(2)}, store)[1] == [])
    (root / 'channel' / 'conversation.json').unlink()
    new_wish('43.1-4')
    check('bound', split({'messages': msgs(2)}, store, now=1000.0)[1] == ['Console'])
    check('its turn is over after a short time', split({'messages': msgs(2)}, store, now=1000.0 + K.TURN_SECONDS + 1)[1] == [])
    new_wish('43.1-5')
    check('bound for the call', split({'messages': msgs(2)}, store)[1] == ['Console'])
    check('the request answering the call keeps it (the call completes, same tool list)', split({'messages': called(msgs(2))}, store)[1] == ['Console'])
    check('the action came back once: never again in that turn', split({'messages': called(msgs(2)) + [{'role': 'assistant', 'content': 'x'}]}, store)[1] == []
          and split({'messages': called(msgs(2))}, store)[1] == [])
    new_wish('43.1-6')
    check('bound before the game result', split({'messages': msgs(2)}, store)[1] == ['Console'])
    game_file(lw_state.DATA_DIR, [entry('43.1-6', 'make it rain')], done=[('43.1-6', 'ran: fw 81a')])
    check('the game ran it: not offered again on that turn', split({'messages': msgs(2)}, store)[1] == [])

    # a wish read twice (a new process reading the same file) is not offered again
    K.reset()
    check('a wish already read (per save) is never offered again', split({'messages': msgs(6)}, store)[1] == [])

    # results the game writes after the confirm box go into the log
    game_file(lw_state.DATA_DIR, [entry('41.5-1', 'give me 2000 gold')], done=[('41.6-9', 'ran: player.additem f 2000 | The player now has 2000 more gold.')])
    split({'messages': msgs(6)}, store)
    log = K.load(store)['log']
    check('log written: what the game ran', log[-1].get('result', '').startswith('ran: player.additem f 2000'), log[-1])
    split({'messages': msgs(6)}, store)
    check('a result is logged once', sum(1 for e in K.load(store)['log'] if e.get('key') == '41.6-9') == 1)

    # gating
    K.reset()
    game_file(lw_state.DATA_DIR, [entry('41.7-2', 'make it rain', time=41.7)])
    check('setting off: never offered', split({'messages': msgs(2)}, store, dict(VALUES, console_actions=False))[1] == [])
    K.reset()
    game_file(lw_state.DATA_DIR, [entry('41.7-3', 'make it rain', time=41.7, tool=0)])
    check('ConsoleUtil missing: never offered', split({'messages': msgs(2)}, store)[1] == [])
    check('ConsoleUtil missing: logged with why', K.load(store)['log'][-1]['status'] == 'ConsoleUtil is missing', K.load(store)['log'][-1])
    K.reset()
    game_file(lw_state.DATA_DIR, [entry('41.7-4', 'make it rain', player='Someone Else'), entry('10.0-5', 'tgm', time=10.0)])
    check('another save character or another session: never offered', split({'messages': msgs(2)}, store)[1] == [])
    K.reset()
    game_file(lw_state.DATA_DIR, [entry('41.8-6', 'teleport me to Whiterun', time=41.8)])
    split({'keyword_actions': True}, store, now=1000.0)  # read, but no request of its turn yet
    check('waiting too long before its turn: dropped', split({'messages': msgs(2)}, store, now=1000.0 + K.WAIT_SECONDS + 1)[1] == [])
    check('...logged as dropped', K.load(store)['log'][-1]['status'].startswith('dropped'), K.load(store)['log'][-1])
    K.reset()
    game_file(lw_state.DATA_DIR, [entry('41.8-7', 'one', time=41.8), entry('41.8-8', 'two', time=41.8)])
    check('two new wishes: only the newest waits', split({'messages': msgs(2)}, store)[1] == ['Console'] and 'two' in K.newest_text(msgs(2), 'P'))

    # no Console action in the list at all (file removed): nothing added
    K.reset()
    game_file(lw_state.DATA_DIR, [entry('41.9-9', 'make it rain', time=41.9)])
    rest, extra = K.split([t for t in TOOLS if t['function']['name'] != 'Console'], {'messages': msgs(2)}, store, VALUES, 'Dragonborn', 41, 1000.0)
    check('action file missing: nothing to offer', extra == [] and names(rest) == ['Attack', 'Follow'])
    check('broken tools never raise', K.split([None, 5, 'x'], {'messages': msgs(2)}, store, VALUES, 'Dragonborn', 41, 1000.0) == ([None, 5, 'x'], []))

    # the hooks in living_world/__init__.py
    K.reset()
    real_store, real_load = dict(living_world._last_store), settings.load
    try:
        settings.load = lambda path=None: dict(VALUES, action_filter=False, short_actions=False)
        living_world._last_store.update(store=store, people=[('Lydia', '0A2C94')])
        (Path(lw_state.DATA_DIR) / 'conversation.json').write_text(json.dumps({'int': {'day': 41}, 'string': {'player': 'Dragonborn'}}), encoding='utf-8')
        game_file(lw_state.DATA_DIR, [])
        check('hook: no wish, the list is as before', names(living_world._filter_tools(list(TOOLS), {'messages': msgs(1)})) == ['Attack', 'Follow'])
        game_file(lw_state.DATA_DIR, [entry('41.95-10', 'set my one-handed skill to 50', time=41.95)])
        offered = names(living_world._filter_tools(list(TOOLS), {'messages': msgs(2)}))
        check('hook: on the wish turn the action is added', offered == ['Attack', 'Follow', 'Console'], offered)
        extra = living_world._extra_text({'messages': msgs(2)})
        check('hook: the note goes into the newest message', 'set my one-handed skill to 50' in extra, extra)
        check('hook: the next turn has the old list again', names(living_world._filter_tools(list(TOOLS), {'messages': msgs(3)})) == ['Attack', 'Follow'])
        game_file(lw_state.DATA_DIR, [entry('41.95-11', 'make it rain', time=41.95)])
        settings.load = lambda path=None: 1 / 0  # the action filter fails: fail closed, no Console action
        failed = names(living_world._filter_tools(list(TOOLS), {'messages': msgs(4)}))
        check('hook: a failing filter never offers the Console action', 'Console' not in failed, failed)
    finally:
        settings.load = real_load
        living_world._last_store.clear()
        living_world._last_store.update(real_store)

# --- server mode: the server builds the Console action (Direct AI Connect's server_actions hook) --------------------
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    lw_state.DATA_DIR = str(root / 'channel'); (root / 'channel').mkdir()
    store = memory.MemoryStore(str(root / 'conversations'), 'Dragonborn1')
    K.reset(); K.use_server()
    asked = []
    def ask(prompt, text):
        asked.append((prompt, text))
        return 'Sure:\n```json\n{"commands": ["player.additem f 2000", "x\\nkill"], "summary": "Dragonborn now has 2000 more gold."}\n```'
    act = lambda messages, a=ask, now=1000.0, values=VALUES, tools=TOOLS: K.server_actions(tools, {'messages': messages}, store, a, values, 'Dragonborn', 41, now)
    check('server mode, no wish: nothing built', act(msgs(3)) == [] and not asked)
    game_file(lw_state.DATA_DIR, [entry('50.1-1', 'give me 2000 gold', refs=(LYDIA,), names=('Lydia',))])
    turn = msgs(4) + [{'role': 'assistant', 'content': ''}, {'role': 'tool', 'content': 'done'}]  # the event turn after an action result
    check('server mode: the Console tool is never in the list, also on the wish turn', split({'messages': turn}, store) == (['Attack', 'Follow'], []))
    note = K.newest_text(turn, 'Dragonborn')
    check('server mode: the NPC only gets one neutral line, never the wish', note == K.SERVER_NOTE and 'gold' not in note, note)
    calls = act(turn)
    args = json.loads(calls[0]['function']['arguments']) if calls else {}
    check('server mode: the action is built on the wish turn', len(calls) == 1 and calls[0]['function']['name'] == 'Console'
          and calls[0]['type'] == 'function' and calls[0]['id'].startswith('toolu_'), calls)
    check('server mode: commands and summary from the helper JSON, cleaned', args == {'commands': ['player.additem f 2000', 'x kill'],
          'summary': 'Dragonborn now has 2000 more gold.'}, args)
    check('server mode: one helper call with the wish and the ref ids', len(asked) == 1 and 'give me 2000 gold' in asked[0][1]
          and 'Lydia 000A2C94' in asked[0][0] and 'JSON' in asked[0][0], asked)
    check('server mode: built once (the empty-reply retry or the next request gets nothing)', act(turn) == [] and act(msgs(5)) == [] and len(asked) == 1)
    log = K.load(store)['log']
    check('server mode: logged as sent to the game', log and log[-1]['status'].startswith('sent to the game'), log[-1:])
    game_file(lw_state.DATA_DIR, [entry('50.1-1', 'give me 2000 gold'), entry('50.1-2', 'make it rain')])
    calls = act(msgs(6), a=lambda p, t: 'I cannot help with that.')
    check('server mode: no JSON from the helper: an empty list whose summary says so', calls and json.loads(calls[0]['function']['arguments'])['commands'] == []
          and 'No safe' in json.loads(calls[0]['function']['arguments'])['summary'], calls)
    game_file(lw_state.DATA_DIR, [entry('50.1-3', 'make it snow')])
    calls = act(msgs(7), a=lambda p, t: 1 / 0)
    check('server mode: a failing helper call never raises, nothing runs', calls and json.loads(calls[0]['function']['arguments'])['commands'] == [], calls)
    game_file(lw_state.DATA_DIR, [entry('50.1-4', 'make it hail')])
    split({'keyword_actions': True}, store, now=1000.0)
    check('server mode: a wish whose turn never came still expires', act(msgs(8), now=1000.0 + K.WAIT_SECONDS + 1) == [])
    game_file(lw_state.DATA_DIR, [entry('50.1-5', 'make it hail')])
    check('server mode: Console setting off: nothing', act(msgs(9), values=dict(VALUES, console_actions=False)) == [])
    check('server mode: Console action not generated (action off in Mantella): nothing', act(msgs(9), tools=[t for t in TOOLS if t['function']['name'] != 'Console']) == [])
    # live test 4: the helper call hung inside the request and froze the whole server
    import asyncio, time as _time, threading as _threading
    game_file(lw_state.DATA_DIR, [entry('50.1-6', 'give me 9 gold')])
    old_limit, K.HELPER_SECONDS = K.HELPER_SECONDS, 0.3
    release = _threading.Event()
    started = _time.time()
    calls = act(msgs(10), a=lambda p, t: release.wait(30) and '{"commands": ["player.additem f 9"], "summary": "late"}')
    took = _time.time() - started
    release.set(); K.HELPER_SECONDS = old_limit
    hung = json.loads(calls[0]['function']['arguments']) if calls else {}
    check('console: a hanging helper call cannot block the reply (cut off, nothing runs, the player is told)',
          took < 2 and hung.get('commands') == [] and 'too long' in hung.get('summary', ''), (took, calls))
    game_file(lw_state.DATA_DIR, [entry('50.1-7', 'give me 8 gold')])
    asked_on_loop = []
    async def on_loop():  # an older Direct AI Connect calls the hook on its event loop, holding its lock
        return act(msgs(11), a=lambda p, t: asked_on_loop.append(1) or '{"commands": ["x"], "summary": "y"}')
    calls = asyncio.run(on_loop())
    refused = json.loads(calls[0]['function']['arguments']) if calls else {}
    check('console: called on the server event loop (older Direct AI Connect): refused at once, no helper call',
          not asked_on_loop and refused.get('commands') == [] and 'newer Direct AI Connect' in refused.get('summary', ''), calls)
    K.reset()
    class Api:
        def __init__(self, hooks): self.hooks, self.got = hooks, {}
        def on(self, hook, fn):
            if hook not in self.hooks:
                raise ValueError(hook)
            self.got[hook] = fn
    import living_world as LW
    real = (LW.update_check.check_in_background, LW.characters.write_game_flags, LW._start_memory_model, LW.server_status.start)
    try:
        LW.update_check.check_in_background = LW.characters.write_game_flags = LW._start_memory_model = LW.server_status.start = lambda *a, **k: None
        old = Api({'system_parts', 'filter_tools', 'extra_user_text', 'summarize', 'memory_text', 'conversation_limit', 'ui_page'})
        LW.register(old)
        check('register: an older Direct AI Connect keeps the model path', not K._state['server'] and 'server_actions' not in old.got)
        new = Api({'system_parts', 'filter_tools', 'extra_user_text', 'summarize', 'memory_text', 'conversation_limit', 'ui_page', 'server_actions'})
        LW.register(new)
        check('register: with the hook the server builds the action', K._state['server'] and 'server_actions' in new.got)
    finally:
        LW.update_check.check_in_background, LW.characters.write_game_flags, LW._start_memory_model, LW.server_status.start = real
        K.reset()

print(f'\n{len(FAILS)} failed' if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
