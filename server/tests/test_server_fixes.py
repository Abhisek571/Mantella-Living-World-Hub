"""Offline tests for the server fixes of 2026-11-17: the keyword question never waits for an NPC file; the game's command,
release and settings files are polled once per request; channel files read once per request; the world note and the
jobs stay the same all talk; asked-before topics are not counted again after a trim; one NPC's failed save never costs
the others theirs, and the talk's cleanups run whatever failed; settings saved through a temp file of their own; stock
bios keep three example lines, short and hand-set bios none cut.
Run with a Python 3.11: test_server_fixes.py <repo server dir>"""
import builtins, json, os, sys, tempfile, time
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
import living_world as LW
from living_world import asked_before, bio_optimise, command, lw_state, memory, menu_dialogue, npc_block, release, settings, world_note
from menu_talk import EndOfTalk, Params, People
memory.SUMMARY_RETRY_SECONDS = 0

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:500]) if not cond else ''))
    if not cond:
        FAILS.append(name)


def part_keyword_wait():
    real = lw_state.load_conversation
    lw_state.load_conversation = lambda: [{'name': 'New NPC'}]  # the game has not written the minor flag yet
    try:
        start = time.time()
        LW._await_npc_files({'keyword_actions': True, 'messages': []})
        keyword = time.time() - start
        start = time.time()
        LW._await_npc_files({'messages': [{'role': 'user', 'content': 'Hi'}]})
        first = time.time() - start
    finally:
        lw_state.load_conversation = real
    check('the keyword question never waits for a new NPC file (it waited up to 1 s on every reply)', keyword < 0.1, keyword)
    check("...the talk's first request still waits for the minor flag", first >= LW.GREETING_WAIT * 0.9, first)


def part_poll_once(tmp: Path):
    store = memory.MemoryStore(str(tmp / 'mem'), 'w')
    calls = []
    real = (command.poll, release.poll_game, command.write_game_settings, lw_state.DATA_DIR)
    command.poll = lambda *a, **k: calls.append('command') or []
    release.poll_game = lambda *a, **k: calls.append('release') or []
    command.write_game_settings = lambda values: calls.append('settings')
    lw_state.DATA_DIR = str(tmp / 'channel')
    os.makedirs(lw_state.DATA_DIR, exist_ok=True)
    LW._last_store.update(store=store, people=[('Lydia', '0A2C94')])
    LW._polled.clear()
    try:
        for newest in (False, False, True, False):  # keyword actions, actions, newest message, system prompt
            LW._commands(newest=newest)
        check('one request: the command, release and settings files are polled once, not four times', calls == ['settings', 'command', 'release'], calls)
        (Path(lw_state.DATA_DIR) / release.GAME_FILE).write_text('{"stringList": {}}', encoding='utf-8')
        LW._commands(newest=True)
        check('...a release written by the game is read on the very next ask', calls.count('release') == 2, calls)
        LW._polled['at'] -= LW.POLL_SECONDS
        LW._commands(newest=True)
        check('...and unchanged files are polled again after POLL_SECONDS (commands that wear off)', calls.count('release') == 3, calls)
    finally:
        command.poll, release.poll_game, command.write_game_settings, lw_state.DATA_DIR = real
        LW._last_store.update(store=None, people=[])
        LW._polled.clear()


def part_read_memo(tmp: Path):
    real_dir = lw_state.DATA_DIR
    lw_state.DATA_DIR = str(tmp / 'memo')
    os.makedirs(lw_state.DATA_DIR, exist_ok=True)
    path = Path(lw_state.DATA_DIR) / 'conversation.json'
    path.write_text(json.dumps({'string': {'player': 'Player'}}), encoding='utf-8')
    opened = []
    real_open = builtins.open
    builtins.open = lambda p, *a, **k: (opened.append(str(p)) if str(p) == str(path) else None) or real_open(p, *a, **k)
    try:
        first = lw_state._read('conversation.json')
        first['changed'] = 1  # a caller changing its copy changes nothing for the next
        second = lw_state._read('conversation.json')
        check('a channel file read twice in one request is opened once; each caller gets its own copy',
              len(opened) == 1 and 'changed' not in second and second == {'string': {'player': 'Player'}}, (opened, second))
        path.write_text(json.dumps({'string': {'player': 'Dragonborn'}}), encoding='utf-8')
        check('...a file the game rewrote is read again at once', lw_state._read('conversation.json') == {'string': {'player': 'Dragonborn'}}
              and len(opened) == 2)
        lw_state._memo[str(path)] = (lw_state._memo[str(path)][0] - lw_state.READ_MEMO_SECONDS, *lw_state._memo[str(path)][1:])
        lw_state._read('conversation.json')
        check('...and an unchanged one again after READ_MEMO_SECONDS', len(opened) == 3)
    finally:
        builtins.open = real_open
        lw_state.DATA_DIR = real_dir
        lw_state._memo.clear()


def part_world_note(tmp: Path):
    store = memory.MemoryStore(str(tmp / 'mem'), 'w')
    worlds = [{'bounty': {'Whiterun': 100}}]
    built = []
    real = (world_note.text, lw_state.load_world, lw_state.load_conversation, LW._installed, lw_state.DATA_DIR)
    lw_state.DATA_DIR = str(tmp / 'channel')  # the game's channel files written meanwhile go here, never a real folder
    LW._installed = lambda: {'Missives', 'World'}
    world_note.text = lambda speakers, world, player, skip_dragonborn=False: built.append(dict(world)) or f"note {world}"
    lw_state.load_world = lambda: worlds[0]
    speaker = {'name': 'Lydia', 'base_id': 'A2C9E', 'hold': 'Whiterun', 'job': 'Clear the barrow.'}
    lw_state.load_conversation = lambda: [speaker]
    LW._last_store.update(store=store, people=[('Lydia', '0A2C94')], bios=[])
    npc_block.talk_over()
    try:
        first = LW._system_parts({'mantella': '# Overview\nYou are Lydia.\n\n# Background\nA housecarl.'}, {})
        worlds[0] = {'bounty': {'Whiterun': 900}}  # World rewrites world.json mid-talk
        speaker['job'] = 'Something else.'
        second = LW._system_parts({'mantella': '# Overview\nYou are Lydia.\n\n# Background\nA housecarl.'}, {})
        check('the world note and the jobs stay the same all talk (a world.json rewrite no longer rewrites the cache)',
              first.get('world') == second.get('world') and first.get('jobs') == second.get('jobs') and len(built) == 1
              and 'Clear the barrow.' in first.get('jobs', ''), (first.get('world'), second.get('world')))
        npc_block.talk_over()
        third = LW._system_parts({'mantella': '# Overview\nYou are Lydia.\n\n# Background\nA housecarl.'}, {})
        check('...the next talk has the new ones', '900' in third.get('world', '') and 'Something else.' in third.get('jobs', ''), third.get('world'))
    finally:
        world_note.text, lw_state.load_world, lw_state.load_conversation, LW._installed, lw_state.DATA_DIR = real
        LW._last_store.update(store=None, people=[], bios=[])
        npc_block.talk_over()


def part_asked_trim(tmp: Path):
    store = memory.MemoryStore(str(tmp / 'mem'), 'w')
    tracker = asked_before.Tracker()
    people = [('Lydia', '0A2C94')]
    long_talk = [{'role': 'system', 'content': 'x'}] + [{'role': 'user', 'content': f'line {i}'} for i in range(10)] + \
                [{'role': 'user', 'content': 'Tell me about the Companions.'}]
    tracker.notes(long_talk, people, store, 'Player', 5, talk=7)
    trimmed = [{'role': 'system', 'content': 'x'}, {'role': 'user', 'content': 'What about the Companions?'}]
    note = tracker.notes(trimmed, people, store, 'Player', 5, talk=7)
    asked = store.load('Lydia', '0A2C94').get('asked', {})
    check('a trim mid-talk (shorter message list, same talk): the topic is not counted again, no "brought up before" line',
          note == '' and all(v == 1 for v in asked.values()) and asked, (note, asked))
    note = tracker.notes(trimmed, people, store, 'Player', 6, talk=8)
    check('...the next talk counts it as asked before', 'brought up' in note, note)


def part_summarize_failures(tmp: Path):
    store = memory.MemoryStore(str(tmp / 'mem'), 'w')
    lydia, faendal = SimpleNamespace(name='Lydia', ref_id='0A2C94', bio=''), SimpleNamespace(name='Faendal', ref_id='01348C', bio='')
    real_save = store.save
    def save(name, ref_id, mem):
        if name == 'Lydia':
            raise PermissionError(13, 'locked')
        return real_save(name, ref_id, mem)
    store.save = save
    inner = SimpleNamespace(summarize_conversation=lambda text, prompt: json.dumps({'memory': 'We spoke of the war.', 'feelings': {}}))
    talk = [f'Player: line {i}' for i in range(8)]
    threads = {'Lydia': Params(talk, [lydia]), 'Faendal': Params(['Player: other'] * 8, [faendal])}
    summaries = EndOfTalk(inner, threads)
    summaries.group_shared_threads = lambda t: [['Lydia'], ['Faendal']]
    ctx = {'messages': None, 'npcs_to_summarize': [lydia, faendal], 'npcs_in_conversation': People('Player'), 'world_id': 'w',
           'is_reload': False, 'end_timestamp': 4.5, 'is_radiant': False, 'summaries': summaries}
    handled = memory.summarize(ctx, store)
    check("one NPC's file failing: the other NPC still gets this talk, and the save is still handled",
          handled is True and store.load('Faendal', '01348C')['recent'] and not store.load('Lydia', '0A2C94')['recent'])
    # _summarize: the talk's cleanups run even when saving fails
    real = (memory.summarize, LW._store)
    memory.summarize = lambda ctx, store: (_ for _ in ()).throw(RuntimeError('broken'))
    LW._store = lambda ctx: store
    menu_dialogue._talk_pending['Lydia'] = {'base': 'A2C9E'}
    try:
        result = LW._summarize(dict(ctx, npcs_in_conversation=People('Player')))
    finally:
        memory.summarize, LW._store = real
    check("...and when saving fails outright, the talk's cleanups still run and Mantella does not summarise a second time",
          result is True and menu_dialogue._talk_pending == {}, (result, menu_dialogue._talk_pending))


def part_settings_save(tmp: Path):
    path = tmp / 'settings.json'
    settings.save(str(path), dict(settings.DEFAULTS, memory_budget=900))
    src = (SERVER / 'living_world' / 'settings.py').read_text(encoding='utf-8')
    check('settings are saved through a temp file of their own and the retrying replace',
          settings.load(str(path))['memory_budget'] == 900 and 'lw_state.temp_path(path)' in src and 'lw_state.replace_file(tmp, path)' in src
          and not list(tmp.glob('*.tmp')))


def part_examples():
    examples = 'Example dialogue:\n' + '\n'.join(f'"Line {i}."' for i in range(9))
    stock, kept = f"Gerdur runs the mill.\n{examples}", f"Lydia is a housecarl.\n{examples}"
    text = f"# Background\n{stock}\n\n{kept}"
    real = bio_optimise.uses_original
    bio_optimise.uses_original = lambda name, path=None: name == 'Lydia'  # kept as it is, by hand on the NPC page
    try:
        out = LW._trim_stock_examples(text, [('Gerdur', stock), ('Lydia', kept)], 3)
    finally:
        bio_optimise.uses_original = real
    check('a stock bio keeps the first three example lines', '"Line 2."' in out.split('Lydia')[0] and '"Line 3."' not in out.split('Lydia')[0], out)
    check('...a bio set by hand on the NPC page is not cut', kept in out)
    check('...three by default', settings.DEFAULTS['bio_examples'] == 3)


def part_action_lock():
    tools = lambda: [{'function': {'name': 'SexWithPlayer', 'description': 'x'}}, {'function': {'name': 'Wave', 'description': 'y'}}]
    state = {'speakers': [{'name': 'Lydia', 'base_id': 'A2C9E', 'minor': 0, 'intimate': 0}]}
    real = (LW._gates, LW._action_speakers, lw_state.load_conversation, LW._last_store.get('store'))
    LW._gates = lambda: {'SexWithPlayer': 'intimate'}
    LW._action_speakers = lambda: state['speakers']
    lw_state.load_conversation = lambda: state['speakers']
    real_dir = lw_state.DATA_DIR
    lw_state.DATA_DIR = tempfile.mkdtemp()
    LW._last_store['store'] = None
    names = lambda: [t['function']['name'] for t in LW._filter_tools(tools(), {'messages': []})]
    npc_block.talk_over()
    try:
        greeting = names()
        state['speakers'] = [dict(state['speakers'][0], intimate=1)]  # her file's late part: lovers after all
        reply = names()
        check('greeting and first reply send the same actions (one cached list); a late-allowed one waits for the next talk',
              greeting == reply == ['Wave'], (greeting, reply))
        npc_block.talk_over()
        check('...the next talk offers it', names() == ['SexWithPlayer', 'Wave'])
        state['speakers'] = [dict(state['speakers'][0], minor=1)]  # the game says child
        check('taking an action away (a child) applies on that same request, never the next talk', names() == ['Wave'])
        state['speakers'] = [dict(state['speakers'][0], minor=0), {'name': 'Braith', 'base_id': '13BB5', 'minor': 1}]
        check('...so does a child joining the talk', names() == ['Wave'])
    finally:
        LW._gates, LW._action_speakers, lw_state.load_conversation, LW._last_store['store'] = real
        lw_state.DATA_DIR = real_dir
        npc_block.talk_over()


with tempfile.TemporaryDirectory() as tmp:
    for name, part in (('keyword', lambda: part_keyword_wait()), ('poll', lambda: part_poll_once(Path(tmp) / 'poll')),
                       ('memo', lambda: part_read_memo(Path(tmp) / 'memo')), ('world', lambda: part_world_note(Path(tmp) / 'world')),
                       ('asked', lambda: part_asked_trim(Path(tmp) / 'asked')), ('summarize', lambda: part_summarize_failures(Path(tmp) / 'sum')),
                       ('settings', lambda: part_settings_save(Path(tmp) / 'set')), ('examples', part_examples), ('actions', part_action_lock)):
        try:
            sub = Path(tmp) / {'poll': 'poll', 'memo': 'memo', 'world': 'world', 'asked': 'asked', 'summarize': 'sum', 'settings': 'set'}.get(name, name)
            sub.mkdir(exist_ok=True)
            part()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'part {name} ran without an error', False, e)
        menu_dialogue.talk_over()

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
