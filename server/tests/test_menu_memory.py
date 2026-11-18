"""Offline tests for menu dialogue that becomes memory: lines from the game's own dialogue (World's capture, nothing
expires) are shown in the NPC's memory block at her next talk, however much later, dated and as they were said, with no
model call before the greeting; the talk's own end-of-talk summary makes them into one dated first-person memory (a
dialogue mod whose scripts start scenes gives a long-kept one); a talk that ends without it, or whose summary fails,
leaves them for the next talk; a restart never makes a second memory; a store nearly full is summarised in the
background; World's plugin is told which lines are stored (menu_ack.json); OStim Expansion's earlier scenes become
memories at once.
Run with a Python 3.11: test_menu_memory.py <repo server dir>"""
import json, sys, tempfile, time
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
from living_world import archive, bio_evolve, lw_state, memory, menu_dialogue as MD
from menu_talk import end_talk
memory.SUMMARY_RETRY_SECONDS = 0

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


class Summaries:
    def __init__(self):
        self.calls = []
        self._Summaries__language_name = 'English'
    def summarize_conversation(self, text, prompt):
        self.calls.append(text)
        return json.dumps({'memory': 'First the hooded stranger asked me an awkward question, then for help again, and I gave in.',
                           'feelings': {'Gerdur': 'embarrassed'}, 'importance': 0.4, 'emotion': 'shame', 'type': 'relationship',
                           'tags': ['secret']})


GERDUR = SimpleNamespace(name='Gerdur', ref_id='01347C', base_id='01347C', bio='The mill owner.')
# two days of the game's own dialogue (day 1 and day 2), then no talk for two weeks
WORLD = {'player': 'Player', 'npcs': {'01347C': {'name': 'Gerdur', 'dropped': 0, 'lines': [
    {'said': "I've got an awkward question.", 'line': 'Spit it out.', 'time': 1000.0, 'day': 1.55, 'plugin': 'shadowman_gerdur.esp', 'place': 'Riverwood', 'vanilla': 0},
    {'said': 'I need help with a problem.', 'line': "If you're that desperate, the river's cold enough.", 'time': 1010.0, 'day': 1.56, 'plugin': 'shadowman_gerdur.esp', 'place': 'Riverwood', 'vanilla': 0},
    {'said': 'I need help with my problem again.', 'line': 'Do I look like a brothel?', 'time': 2000.0, 'day': 2.41, 'plugin': 'shadowman_gerdur.esp', 'place': 'Riverwood', 'vanilla': 0},
    {'said': '', 'line': "Don't talk about it here!", 'time': 2010.0, 'day': 2.42, 'plugin': 'shadowman_gerdur.esp', 'place': 'Riverwood', 'vanilla': 0}]},
    # the plugin keeps other characters' lines under "others": never read
    }, 'others': {'Dragonborn': {'01347C': {'lines': [{'said': 'x', 'line': 'Not yours.', 'time': 5000.0, 'day': 3.0}]}}}}
SCENE_MOD = lambda p: p == 'shadowman_gerdur.esp'


def channel(tmp: Path) -> Path:
    data_dir = tmp / 'channel'
    (data_dir / 'npc').mkdir(parents=True, exist_ok=True)
    lw_state.DATA_DIR = str(data_dir)
    return data_dir


def ack(data_dir: Path) -> dict:
    try:
        return json.loads((data_dir / MD.ACK).read_text(encoding='utf-8'))
    except OSError:
        return {}


def part_flow(tmp: Path):
    data_dir = channel(tmp)
    store = memory.MemoryStore(str(tmp / 'mem'), 'w')
    summaries = Summaries()
    entry = MD.prepare(store, GERDUR, 'Player', data=WORLD, knows=False, sexual=SCENE_MOD)
    block = MD.talk_text('Gerdur', 'Player')
    check('talk start: no model call; all four lines of both days go into her memory block as said, under their dates',
          summaries.calls == [] and entry is not None and len(entry['lines']) == 4 and block.startswith('Said in the game\'s own dialogue')
          and '[Day 2' in block and '[Day 3' in block and 'Do I look like a brothel?' in block and 'Not yours.' not in block, block)
    check("...marked as said in the game's own dialogue, at the place; a scene-starting mod's dialogue means she knows him (the name)",
          "In the game's own dialogue, at Riverwood" in block and 'Player: I need help' in block, block)
    other = memory.MemoryStore(str(tmp / 'hooded'), 'w')
    MD.talk_over()
    MD.prepare(other, GERDUR, 'Player', data=WORLD, knows=False, sexual=lambda p: False)
    hooded = MD.talk_text('Gerdur', 'Player')
    check('...ordinary dialogue with an NPC who does not know the hooded player: "the hooded stranger", never the name',
          'the hooded stranger: I need help' in hooded and 'Player' not in hooded, hooded)
    MD.talk_over()
    entry = MD.prepare(store, GERDUR, 'Player', data=WORLD, knows=False, sexual=SCENE_MOD)
    check('...shown in her memory block by memory_text (after her memories), so the greeting knows it',
          block in memory.memory_text('', {'characters': [GERDUR], 'extra_for': lambda c: MD.talk_text(c.name, 'Player')}, store))
    check('...once per talk: asked again it is the same block, nothing read again',
          MD.prepare(store, GERDUR, 'Player', data={'player': 'Player', 'npcs': {}}) is entry and MD.talk_text('Gerdur', 'Player') == block)
    check('nothing is marked used yet', MD.load_seen(store) == {} and ack(data_dir) == {})
    talk = end_talk(store, [GERDUR], summaries)
    mem = store.load('Gerdur', '01347C')
    menu = [e for e in mem['recent'] if e.get('dialogue', '').startswith('menu-')]
    check('end of the talk: ONE summary request makes the talk memory and a separate menu memory',
          len(talk.calls) == 1 and len(menu) == 1 and len(mem['recent']) == 2 and '"menu"' in talk.calls[0][1], mem['recent'])
    m = menu[0] if menu else {}
    check("...the menu memory dated by its newest line (day 3, 10:00), first person, with the summary's own fields",
          (m.get('day'), m.get('hour')) == (3, 10) and m.get('emotion') == 'shame' and m.get('type') == 'relationship'
          and m.get('text', '').startswith('First the hooded stranger'), m)
    check('...lines of a mod whose scripts start scenes are kept long (importance at least 0.9, intimacy)',
          archive.importance_of(m) >= MD.INTIMATE_IMPORTANCE and 'intimacy' in (m.get('flags') or []), m)
    check('...saved before the talk memory, so it is how they met', 'first_meeting' in (m.get('flags') or [])
          and 'first_meeting' not in (mem['recent'][-1].get('flags') or []), mem['recent'])
    text = talk.calls[0][0]
    check('...the summary got both days dated, with the place, before the conversation', '[Day 2' in text and '[Day 3' in text
          and 'at Riverwood' in text and text.index('Do I look like a brothel?') < text.index('Then this conversation:'), text)
    check('...marked used, and World is told the newest real capture time stored for that player and NPC',
          MD.load_seen(store).get('01347C') == 2010.0 and ack(data_dir) == {'Player': {'01347C': 2010.0}}, (MD.load_seen(store), ack(data_dir)))
    MD.talk_over()
    check('a restart (the marker is on disk) or the next talk never shows or makes them again',
          MD.prepare(store, GERDUR, 'Player', data=WORLD) is None and len(store.load('Gerdur', '01347C')['recent']) == 2)
    MD.talk_over()
    newer = json.loads(json.dumps(WORLD))
    newer['npcs']['01347C']['lines'].append({'said': 'Hello.', 'line': 'Not here.', 'time': 3000.0, 'day': 16.2, 'plugin': 'shadowman_gerdur.esp'})
    later = MD.prepare(store, GERDUR, 'Player', data=newer, sexual=lambda p: False)
    end_talk(store, [GERDUR], Summaries())
    last = [e for e in store.load('Gerdur', '01347C')['recent'] if e.get('dialogue', '').startswith('menu-')][-1]
    check('a later line alone becomes one more memory, at its own day, kept as ordinary (no scene mod)',
          later and len(later['lines']) == 1 and last['day'] == 17 and archive.importance_of(last) < MD.INTIMATE_IMPORTANCE, last)
    check('...and World\'s acknowledgement moves on with it', ack(data_dir) == {'Player': {'01347C': 3000.0}}, ack(data_dir))
    MD.talk_over()
    check("another character's file is never used", MD.prepare(memory.MemoryStore(str(tmp / 'other'), 'w'), GERDUR, 'Dragonborn', data=WORLD) is None)
    MD.talk_over()


def part_failed(tmp: Path):
    data_dir = channel(tmp)
    store = memory.MemoryStore(str(tmp / 'mem'), 'w')
    MD.prepare(store, GERDUR, 'Player', data=WORLD)
    broken = Summaries()
    broken.summarize_conversation = lambda text, prompt: ''
    end_talk(store, [GERDUR], broken)
    check('a failed end-of-talk summary marks nothing and saves no menu memory', MD.load_seen(store) == {} and ack(data_dir) == {}
          and not any(e.get('dialogue') for e in store.load('Gerdur', '01347C')['recent']))
    MD.talk_over()
    check('...the next talk shows all the lines again', len((MD.prepare(store, GERDUR, 'Player', data=WORLD) or {}).get('lines') or []) == 4)
    no_menu = Summaries()
    no_menu.summarize_conversation = lambda text, prompt: json.dumps({'memory': 'We talked.'})
    from menu_talk import EndOfTalk
    real = EndOfTalk.summarize_conversation
    EndOfTalk.summarize_conversation = lambda self, text, prompt: no_menu.summarize_conversation(text, prompt)
    try:
        end_talk(store, [GERDUR], no_menu)
    finally:
        EndOfTalk.summarize_conversation = real
    check('a summary that leaves out the "menu" part marks nothing either', MD.load_seen(store) == {} and ack(data_dir) == {})
    MD.talk_over()
    MD.prepare(store, GERDUR, 'Player', data=WORLD)
    MD.talk_over()  # the talk ended with no summary at all (Mantella closed, the game crashed)
    check('a talk that ends with no summary leaves them pending', MD.load_seen(store) == {}
          and len((MD.prepare(store, GERDUR, 'Player', data=WORLD) or {}).get('lines') or []) == 4)
    MD.talk_over()
    MD.prepare(store, GERDUR, 'Player', data=WORLD)
    end_talk(store, [GERDUR], Summaries(), talk=())
    check('a talk with no line at all makes no memory and leaves them pending', MD.load_seen(store) == {})
    MD.talk_over()
    MD.prepare(store, GERDUR, 'Player', data=WORLD)
    end_talk(store, [GERDUR], Summaries(), is_reload=True)
    check('a trim mid-talk leaves them for the end of the talk', MD.load_seen(store) == {} and 'Gerdur' in MD._talk_pending)
    MD.talk_over()


def part_events(tmp: Path):
    channel(tmp)
    store = memory.MemoryStore(str(tmp / 'mem'), 'w')
    MD.prepare(store, GERDUR, 'Player', data=WORLD)
    mantella = ["Player: I need help with my problem again.;\n Gerdur: Do I look like a brothel?", 'Gerdur equipped Axe']
    out = MD.replace_events(mantella, 'Player')
    check("Mantella's own copy of the same dialogue becomes a short note (not shown twice, no second summary of it)",
          out[0].startswith(memory.COMPACTED) and "memories hold what was said" in out[0] and out[1] == 'Gerdur equipped Axe', out)
    check('...and the note is not summarised again as menu dialogue (vanilla_dialogue skips it)',
          out[0].startswith(memory.COMPACTED))
    summaries = Summaries()
    talk = end_talk(store, [GERDUR], summaries)
    check("...Mantella's copy still gives the end-of-talk summary the player's words World missed",
          'Player: I need help with my problem again.' in talk.calls[0][0] and talk.calls[0][0].count('Do I look like a brothel?') == 1, talk.calls[0][0])
    MD.talk_over()
    src = (SERVER / 'living_world' / '__init__.py').read_text(encoding='utf-8')
    text_hook = src[src.index('def _memory_text('):src.index('def _pages(')]
    before = src[src.index('def _menu_before_prompt('):src.index('def _ref(')]
    events_hook = src[src.index('def _dialogue_events('):src.index('def _menu_memories(')]
    check('shown from the memory_text hook with no model call (never on a reply: the freeze), never made at the first message',
          '_menu_before_prompt(store, ctx, speakers)' in text_hook and 'menu_dialogue.prepare(' in before
          and 'menu_dialogue.talk_text(' in text_hook and '_menu_first_request' not in src and 'menu_dialogue.remember(' not in src
          and '_menu_memories(events, ctx, store)' in events_hook)
    scene = ["Earlier (about 3 hours ago), with no conversation going on: Gerdur and the player finished a scene together; nothing sexual happened."]
    saved = MD.remember_scene_events(scene, [GERDUR], store, 17, None)
    last = store.load('Gerdur', '01347C')['recent'][-1]
    check("OStim Expansion's earlier scene becomes her memory at once, kept long", saved == 1 and last['importance'] >= MD.INTIMATE_IMPORTANCE
          and 'finished a scene together' in last['text'], last)
    check('...and only once', MD.remember_scene_events(scene, [GERDUR], store, 17, None) == 0)


def part_group(tmp: Path):
    channel(tmp)
    store = memory.MemoryStore(str(tmp / 'mem'), 'w')
    hod = SimpleNamespace(name='Hod', ref_id='01347E', base_id='01347E', bio='')
    world = json.loads(json.dumps(WORLD))
    world['npcs']['01347E'] = {'name': 'Hod', 'lines': [{'said': 'Hi.', 'line': 'The mill needs work.', 'time': 900.0, 'day': 1.5}]}
    MD.prepare(store, GERDUR, 'Player', data=world, sexual=lambda p: False)
    MD.prepare(store, hod, 'Player', data=world, sexual=lambda p: False)
    check("each NPC's block holds only her own lines", 'mill needs work' not in MD.talk_text('Gerdur', 'Player')
          and 'brothel' not in MD.talk_text('Hod', 'Player') and 'mill needs work' in MD.talk_text('Hod', 'Player'))
    block = memory.memory_text('', {'characters': [GERDUR, hod], 'extra_for': lambda c: MD.talk_text(c.name, 'Player')}, store)
    gerdur_part = block[block.index("[This is the beginning of Gerdur's memory"):block.index("[This is the end of Gerdur's memory]")]
    check('...inside her private block in a group talk', 'brothel' in gerdur_part and 'mill needs work' not in gerdur_part, block)
    end_talk(store, [GERDUR, hod], Summaries())
    check('one end-of-talk request makes a separate menu memory for each, in her own file only',
          sum(bool(e.get('dialogue')) for e in store.load('Gerdur', '01347C')['recent']) == 1
          and sum(bool(e.get('dialogue')) for e in store.load('Hod', '01347E')['recent']) == 1 and MD._talk_pending == {})
    MD.talk_over()


def part_delivered(tmp: Path):
    channel(tmp)
    store = memory.MemoryStore(str(tmp / 'mem'), 'w')
    first = json.loads(json.dumps(WORLD))
    first['npcs']['01347C']['lines'] = first['npcs']['01347C']['lines'][:2]
    MD.prepare(store, GERDUR, 'Player', data=first)
    # during the talk the player opened the dialogue menu again: those lines reach the talk as events
    event = "Player: I need help with my problem again.;\n Gerdur: Do I look like a brothel? Don't talk about it here!"
    MD.mark_delivered([event], [GERDUR], store, 'Player', data=WORLD)
    check('lines spoken during the talk do not mark the earlier ones used before the summary', MD.load_seen(store) == {})
    MD.talk_over()
    MD.prepare(store, GERDUR, 'Player', data=WORLD)
    MD.mark_delivered([event], [GERDUR], store, 'Player', data=WORLD)
    end_talk(store, [GERDUR], Summaries())
    check('...they are marked with that memory (no second memory of them next talk)', MD.load_seen(store).get('01347C') == 2010.0)
    MD.talk_over()


def part_overflow(tmp: Path):
    data_dir = channel(tmp)
    (data_dir / 'npc' / '01347C.json').write_text(json.dumps({'string': {'name': 'Gerdur', 'ref_id': '0001347C'}}), encoding='utf-8')
    full = {'player': 'Player', 'npcs': {'01347C': {'name': 'Gerdur', 'lines': [
        {'said': f'Topic {i}', 'line': f'Line {i} of many.', 'time': 100.0 + i, 'day': 1.5 + i / 1000, 'plugin': 'shadowman_gerdur.esp'} for i in range(50)]}}}
    store = memory.MemoryStore(str(tmp / 'mem'), 'w')
    real_busy = bio_evolve.busy
    bio_evolve.busy = lambda now=None: True
    try:
        check('never during a talk', MD.overflow_check(store, Summaries(), 'Player', data=full, now=10_000.0, sexual=lambda p: False) == 0)
        bio_evolve.busy = lambda now=None: False
        MD.prepare(store, GERDUR, 'Player', data=full)
        check('never for lines a talk shows right now (its own summary makes them)', MD.overflow_check(
            store, Summaries(), 'Player', data=full, now=10_000.0, sexual=lambda p: False) == 0 and MD.load_seen(store) == {})
        MD.talk_over()
        summaries = Summaries()
        done = MD.overflow_check(store, summaries, 'Player', data=full, now=20_000.0, sexual=lambda p: False)
        check('a nearly full store (50 of 60): its oldest half becomes one memory in the background (one request)', done == 1
              and MD.load_seen(store).get('01347C') == 124.0 and len(summaries.calls) == 1, MD.load_seen(store))
        check('...World is told those 25 are stored', ack(data_dir) == {'Player': {'01347C': 124.0}}, ack(data_dir))
        check('...at most once an hour per NPC', MD.overflow_check(store, Summaries(), 'Player', data=full, now=20_100.0, sexual=lambda p: False) == 0)
        check('...and the next talk shows only the 25 newer lines', len(MD.prepare(store, GERDUR, 'Player', data=full)['lines']) == 25)
        MD.talk_over()
        mem = store.load('Gerdur', '01347C')
        check('...unless told she knows who the player is, that memory is of a hooded stranger, marked so',
              mem['recent'] and mem['recent'][0].get('unrecognised') is True and 'Player' not in mem['recent'][0]['text'], mem['recent'][:1])
        named = memory.MemoryStore(str(tmp / 'mem2'), 'w')
        class Named(Summaries):
            def summarize_conversation(self, text, prompt):
                self.calls.append(prompt)
                return json.dumps({'memory': 'Player asked me an awkward question.', 'feelings': {'Gerdur': 'embarrassed'}})
        asked = Named()
        MD.overflow_check(named, asked, 'Player', data=full, now=40_000.0, sexual=lambda p: False, knows=lambda c: False)
        got = named.load('Gerdur', '01347C')['recent']
        check('...and a name the model writes anyway is taken out', got and 'Player' not in got[0]['text'] and 'hooded stranger' in got[0]['text'], got[:1])
        MD.talk_over()
    finally:
        bio_evolve.busy = real_busy


def part_ack(tmp: Path):
    data_dir = channel(tmp)
    path = data_dir / MD.ACK
    lines = [{'time': 5000.0, 'day': 3.25}, {'time': 5010.0, 'day': 3.5}]
    check('the acknowledgement: {player: {npc key: real capture time ("time") of the newest stored line}}',
          MD.acknowledge_lines('Player', '01347C', lines) and json.loads(path.read_text(encoding='utf-8')) == {'Player': {'01347C': 5010.0}})
    path.write_text(json.dumps({'Player': {'01347C': 5010.0, '0A0001': 1.0}, 'Dragonborn': {'01347C': 9.0}}), encoding='utf-8')
    MD.acknowledge_lines('Player', '01347C', [{'time': 4000.0, 'day': 9.0}])
    check('never moved backwards', json.loads(path.read_text(encoding='utf-8'))['Player']['01347C'] == 5010.0)
    MD.acknowledge_lines('Player', '0A0002', [{'time': 40.0, 'day': 4.0}])
    check('merged with the other NPCs and players in the file',
          json.loads(path.read_text(encoding='utf-8')) == {'Player': {'01347C': 5010.0, '0A0001': 1.0, '0A0002': 40.0}, 'Dragonborn': {'01347C': 9.0}})
    check('nothing to say (no player, no lines, no real time): nothing written', not MD.acknowledge_lines('', '01347C', lines)
          and not MD.acknowledge_lines('Player', '01347C', []) and not MD.acknowledge_lines('Player', '01347C', [{'day': 3.0}]))
    path.write_text('{not json', encoding='utf-8')
    check('an unreadable file is never replaced by one NPC\'s mark (A12): left as it is, nothing written',
          not MD.acknowledge_lines('Player', '01347C', lines) and path.read_text(encoding='utf-8') == '{not json')
    path.write_text('["a list"]', encoding='utf-8')
    check('a file that is not an object is left as it is too',
          not MD.acknowledge_lines('Player', '01347C', lines) and path.read_text(encoding='utf-8') == '["a list"]')
    path.unlink()
    check('a missing file is started with this mark',
          MD.acknowledge_lines('Player', '01347C', lines) and json.loads(path.read_text(encoding='utf-8')) == {'Player': {'01347C': 5010.0}})
    check('written with a temp file and the retrying replace', 'lw_state.write_json(ACK, data)' in
          (SERVER / 'living_world' / 'menu_dialogue.py').read_text(encoding='utf-8') and not list(data_dir.glob('*.tmp')))
    # an older save loaded: game days lower than before, real capture times later
    path.unlink()
    store = memory.MemoryStore(str(tmp / 'older'), 'w')
    world = {'player': 'Player', 'npcs': {'01347C': {'name': 'Gerdur', 'lines': [
        {'said': 'Hi.', 'line': 'Day forty.', 'time': 1000.0, 'day': 40.5},
        {'said': 'Again.', 'line': 'Day forty, later.', 'time': 1010.0, 'day': 40.6}]}}}
    MD.prepare(store, GERDUR, 'Player', data=world, sexual=lambda p: False)
    end_talk(store, [GERDUR], Summaries())
    MD.talk_over()
    before = ack(data_dir).get('Player', {}).get('01347C')
    world['npcs']['01347C']['lines'] += [{'said': 'Back?', 'line': 'Day twelve, after a load.', 'time': 2000.0, 'day': 12.3},
                                         {'said': 'Yes.', 'line': 'Day twelve, later.', 'time': 2010.0, 'day': 12.4}]
    entry = MD.prepare(store, GERDUR, 'Player', data=world, sexual=lambda p: False) or {}
    check('older save loaded: the new lines (lower game days, later real times) are pending, none covered by the acknowledgement',
          before == 1010.0 and [l['time'] for l in entry.get('lines') or []] == [2000.0, 2010.0]
          and all(l['time'] > before for l in entry['lines']), (before, entry.get('lines')))
    end_talk(store, [GERDUR], Summaries())
    check('...once stored, the entry advances to their newest real time', ack(data_dir) == {'Player': {'01347C': 2010.0}}, ack(data_dir))
    MD.talk_over()


old_dir = lw_state.DATA_DIR
try:
    with tempfile.TemporaryDirectory() as tmp:
        for name, part in (('flow', part_flow), ('failed', part_failed), ('events', part_events), ('group', part_group),
                           ('delivered', part_delivered), ('overflow', part_overflow), ('ack', part_ack)):
            try:
                sub = Path(tmp) / name
                sub.mkdir()
                part(sub)
            except Exception as e:
                import traceback
                traceback.print_exc()
                check(f'part {name} ran without an error', False, e)
            MD.talk_over()
finally:
    lw_state.DATA_DIR = old_dir

# B09: a menu dialogue memory that makes 'earlier' too long is shortened by the summary model with no lock on her file
# held (a talk start reading or saving her memory never waits on that call); the shorter text is saved after it
import threading
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(str(Path(tmp) / 'conversations'), 'P1')
    full = memory.empty()
    full['recent'] = [{'day': 1, 'hour': 9, 'text': f'Old talk number {i} about the mill and the river.', 'witnesses': ['Gerdur']}
                      for i in range(memory.MAX_RECENT)]
    full['long_term']['earlier'] = 'x' * (memory.EARLIER_CHARS - 50)
    store.save('Gerdur', GERDUR.ref_id, full)
    seen = []

    class LockSpy(Summaries):
        def summarize_conversation(self, text, prompt):
            free = []
            def probe_lock():
                lock = store.lock('Gerdur', GERDUR.ref_id)
                got = lock.acquire(timeout=1)
                if got:
                    lock.release()
                free.append(got)
            probe = threading.Thread(target=probe_lock)
            probe.start()
            probe.join()
            short = 'as one shorter text' in prompt
            seen.append(('compress' if short else 'summary', bool(free and free[0])))
            if short:
                return 'Long ago Gerdur and the player knew each other a little.'
            return super().summarize_conversation(text, prompt)
    group = [dict(l, time=l['time'] + 9000) for l in WORLD['npcs']['01347C']['lines'][:2]]
    line = MD._remember_day(store, GERDUR, 'Gerdur', 'Player', LockSpy(), 'English', 1, group, lambda p: False)
    memory.wait_compactions(10)
    after = store.load('Gerdur', GERDUR.ref_id)
    check('menu memory: saved', bool(line) and any(str(e.get('dialogue', '')).startswith('menu-') for e in after['recent']), line)
    check('menu memory: the long earlier part was shortened by the model', ('compress', True) in seen
          and after['long_term']['earlier'] == 'Long ago Gerdur and the player knew each other a little.', (seen, after['long_term']['earlier'][:80]))
    check('menu memory: no model call ran with her memory lock held (B09)', seen and all(free for _, free in seen), seen)

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
