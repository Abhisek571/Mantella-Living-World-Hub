"""Offline tests for live session 15 (2026-11-16), built from the real files it left: Gerdur's 11 menu dialogue lines,
the two kept scenes that reached the talk only with its second message (the real message order, read from Mantella's
own log while it still holds that session), her talk memory and Now paragraph with a stored "less than an hour ago",
Sigrid's small talk, and the hood lines. The session's files are read from its folder when it is on this PC (never
copied into the repository); a part that needs them is skipped without them.
Run with a Python 3.11: test_live_test_15.py <repo server dir>"""
import ast, json, os, re, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1]).resolve()
REPO = SERVER.parent
CODING = REPO.parent
sys.path.insert(0, str(SERVER))
from living_world import bio_evolve, memory, menu_dialogue as MD, news, npc_block, timeline
memory.SUMMARY_RETRY_SECONDS = 0

LIVE15 = os.path.join(os.environ.get('MLW_EVIDENCE', ''), r'lw-live-test-15-2026-11-16')
CREATED = os.path.join(LIVE15, 'session-created')
LOG = os.path.join(os.path.expanduser('~'), 'Documents', 'My Games', 'Mantella', 'logging.log')
FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


GERDUR = SimpleNamespace(name='Gerdur', ref_id='013489', base_id='01347C', bio='Owner of the Riverwood mill.')


def _json(*parts):
    try:
        return json.load(open(os.path.join(CREATED, *parts), encoding='utf-8'))
    except OSError:
        return None


def _messages():
    """The events of the redo talk's first two messages (14:24:31 and 14:26:17), as Mantella received them."""
    found = {}
    try:
        with open(LOG, encoding='utf-8', errors='replace') as f:
            for line in f:
                for stamp in ('2026-11-16 14:24:31,520', '2026-11-16 14:26:17,505'):
                    if line.startswith(stamp + ' INFO: Received in-game events: '):
                        found[stamp] = line.split('Received in-game events: ', 1)[1]
    except OSError:
        return None
    if len(found) < 2:
        return None
    try:  # the log line is the Python list as printed; its first message's event spans lines, so read the second one
        second = ast.literal_eval(found['2026-11-16 14:26:17,505'].strip())
    except (ValueError, SyntaxError):
        return None
    return found['2026-11-16 14:24:31,520'], second


class Summaries:
    _Summaries__language_name = 'English'

    def __init__(self):
        self.calls = []

    def summarize_conversation(self, text, prompt):
        self.calls.append((text, prompt))
        return json.dumps({'memory': 'First Brom asked for help and I gave in; later he asked twice and I said it was the last time.',
                           'feelings': {'Gerdur': 'ashamed'}, 'importance': 0.7})


# --- 1. the kept scenes arrive with the second message ------------------------------------------------------------------
def part_late_scenes(tmp):
    world = _json('SUD-MLW-final', 'menu_dialogue.json')
    order = _messages()
    if not world or not order:
        return print('SKIP the live session 15 files or that part of Mantella\'s log are not on this PC')
    first_raw, second = order
    check('the real order: no kept scene in the first message, both in the second (after the player\'s first line)',
          'with no conversation going on' not in first_raw and sum('{t=' in e for e in second) == 2, first_raw[:200])
    first = ["Brom: I need help with my problem again.;\n Gerdur: By Ysmir's beard... Do I look like a brothel? You've got the "
             "stones to ask twice. The river's still cold, friend. Brom: Just once more? I swear I'll never ask again! ...Probably.;\n"
             " Gerdur: Ugh. Fine. But this is the last time. Brom: ...;\n Gerdur:  "]
    check("(the first message's event, as logged)", first_raw.startswith('["Brom: I need help with my problem again.;\\n Gerdur:'))
    from menu_talk import end_talk
    store = memory.MemoryStore(str(tmp / 'late'), 'w')
    summaries = Summaries()
    entry = MD.prepare(store, GERDUR, 'Brom', data=world, knows=True)
    check('talk start: her 11 menu lines are in her memory block, no model call', entry is not None and summaries.calls == []
          and 'Ugh. Fine. But this is the last time.' in MD.talk_text('Gerdur', 'Brom'))
    events, scenes = MD.scene_records(first)
    MD.replace_events(events, 'Brom')  # message 1: Mantella's own copy, kept aside for the player's words
    paired = MD.pair_late_scenes(second, [GERDUR], store, 'Brom')
    check('message 2: both scenes go with that dialogue, nothing written yet (a talk that dies leaves them unacknowledged)',
          len(paired) == 2 and store.load('Gerdur', '013489')['recent'] == [])
    check('...and no memory of their own', MD.remember_scene_events(second, [GERDUR], store, 0, None, paired=paired, player='Brom') == 0)
    check('...nor paired twice when the scenes come again', MD.pair_late_scenes(second, [GERDUR], store, 'Brom') == paired
          and len(MD._talk_pending['Gerdur']['scenes']) == 2)
    talk = end_talk(store, [GERDUR], summaries, player='Brom', talk=('Brom: Hello.', 'Gerdur: Hm.'))
    text = talk.calls[0][0]
    check('end of the talk: one request for the talk and the menu memory', len(talk.calls) == 1)
    check("...the player's words from Mantella's own copy fill the topics World missed",
          'Brom: I need help with my problem again.' in text and "Brom: Just once more? I swear I'll never ask again! ...Probably." in text, text)
    menu = [e for e in store.load('Gerdur', '013489')['recent'] if e.get('dialogue')]
    entry = menu[0] if menu else {}
    check('both scenes are in that memory as "Then:" lines, in her own words, dated by their tags',
          len(menu) == 1 and entry['text'].count(' Then: Brom and I finished having sex in Riverwood') == 2
          and entry.get('scene_times') == [0.535128, 0.548903], entry)
    check('...with no tag, no stored relative time, and kept long (intimacy, at least 0.9)',
          '{t=' not in entry['text'] and 'ago' not in entry['text'] and 'intimacy' in entry['flags'] and entry['importance'] >= 0.9)
    MD.talk_over()
    check('...sent again at the next talk: no second memory, no second "Then:"', MD.pair_late_scenes(second, [GERDUR], store, 'Brom') == set()
          and MD.remember_scene_events(second, [GERDUR], store, 0, None, player='Brom') == 0
          and len([e for e in store.load('Gerdur', '013489')['recent'] if 'Then:' in e.get('text', '')]) == 1)
    MD.talk_over()
    other = memory.MemoryStore(str(tmp / 'alone'), 'w')
    check('kept scenes in a later message with no menu lines this talk: each its own memory then (dated, first person)',
          MD.pair_late_scenes(second, [GERDUR], other, 'Brom') == set()
          and MD.remember_scene_events(second, [GERDUR], other, 0, None, player='Brom') == 2
          and [(e['day'], e['hour']) for e in other.load('Gerdur', '013489')['recent']] == [(1, 12), (1, 13)])
    src = (SERVER / 'living_world' / '__init__.py').read_text(encoding='utf-8')
    body = src[src.index('def _menu_memories('):src.index('def _menu_before_prompt(')]
    check('the Hub does this on whichever message the scenes come with, and keeps the stock copy for the summary',
          body.count('menu_dialogue.pair_late_scenes(raw,') == 1 and 'menu_dialogue.remember_scene_events(raw,' in body
          and 'if scenes and store is not None:' in body and 'menu_dialogue.replace_events(events,' in body)
    MD.talk_over()


# --- 2. the talk that starts by itself after a scene ---------------------------------------------------------------------
def part_after_scene_talk():
    psc = CODING / 'Mantella-Living-World-Relationships' / 'Source' / 'Scripts' / 'MRB_Ledger.psc'
    if not psc.is_file():
        return print('SKIP the Relationships repository is not next to this one')
    src = psc.read_text(encoding='utf-8')
    start = src[src.index('Function StartTalk('):src.index('EndFunction', src.index('Function StartTalk('))]
    busy = src[src.index('bool Function PlayerBusy('):src.index('EndFunction', src.index('bool Function PlayerBusy('))]
    check("Relationships' after-scene talk (MRB_AfterSceneTalk, Lover's Ledger's scene end + 3 s) is what started the talks",
          'mantellaSpell.Cast(PlayerRef, akPartner)' in start and 'MRB_AfterSceneTalk.GetValueInt() == 1' in src)
    check('it waits for QUIET_SECONDS out of the dialogue menu, any scene and any talk, gives up after MAX_WAIT_SECONDS',
          'While quiet < QUIET_SECONDS && waited < MAX_WAIT_SECONDS' in start and 'If PlayerBusy()' in start
          and 'If quiet < QUIET_SECONDS' in start and start.index('PlayerBusy') < start.index('mantellaSpell.Cast')
          and 'UI.IsMenuOpen("Dialogue Menu")' in busy and '!Game.IsMovementControlsEnabled()' in busy and 'PlayerTalkRunning()' in busy)
    check('...10 s quiet, 90 s at most', 'QUIET_SECONDS = 10.0' in src and 'MAX_WAIT_SECONDS = 90.0' in src)


# --- 3. first person, no stored relative time ----------------------------------------------------------------------------
def part_person_time():
    gerdur = _json('conversations-Brom1-final', 'living_world', 'Gerdur - 013489.json')
    now = _json('conversations-Brom1-final', 'living_world', 'bio_changes', 'Gerdur - 013489.json')
    if not gerdur or not now:
        return print('SKIP the live session 15 memories are not on this PC')
    talk = next(e for e in gerdur['recent'] if 'first_meeting' in (e.get('flags') or []))
    check('the real talk memory: third person with "less than an hour ago" stored', talk['text'].startswith('Brom asked Gerdur')
          and 'less than an hour ago' in talk['text'])
    clean = memory.strip_relative(talk['text'])
    check('...the relative time is taken out, the sentence kept', 'ago' not in clean
          and 'together twice in Riverwood, and said she counts the second as a mistake.' in clean, clean)
    check('the real Now paragraph too', 'ago' not in memory.strip_relative(now['text'])
          and 'twice in Riverwood, and she counts the second' in memory.strip_relative(now['text']), memory.strip_relative(now['text']))
    check('other times of day and real words stay', memory.strip_relative('Days ago I said hello to the hooded stranger.')
          == 'Days ago I said hello to the hooded stranger.')
    src = (SERVER / 'living_world' / 'memory.py').read_text(encoding='utf-8')
    summ = src[src.index('def summarize('):]
    check('the talk summary asks for the first person (one NPC) and no relative time, and cleans what comes back',
          "prompt += FIRST_PERSON.format(name=group[0])" in summ and 'prompt += NO_RELATIVE' in summ and 'text = strip_relative(text)' in summ)
    md = (SERVER / 'living_world' / 'menu_dialogue.py').read_text(encoding='utf-8')
    check('...so does the menu dialogue memory', 'memory.FIRST_PERSON.format(name=name) + memory.NO_RELATIVE' in md
          and 'line = memory.strip_relative(line)' in md)
    bio = (SERVER / 'living_world' / 'bio_evolve.py').read_text(encoding='utf-8')
    check('...and the Now paragraph', 'paragraph = memory.strip_relative(paragraph)' in bio and 'Never write how long ago' in bio)
    check("the menu rules stay out of the talk summary (not the cause)", 'MENU_RULES' not in summ)


# --- 4. first_meeting on the earliest memory of the player only ---------------------------------------------------------
def part_first_meeting(tmp):
    gerdur = _json('conversations-Brom1-final', 'living_world', 'Gerdur - 013489.json')
    if gerdur:
        menu = [e for e in gerdur['recent'] if e.get('dialogue')]
        check('the real case: her menu dialogue memory came first, so the talk memory is not their first meeting',
              menu and not memory.first_contact({'recent': menu}))
    world = _json('SUD-MLW-final', 'menu_dialogue.json')
    if not world:
        return
    store = memory.MemoryStore(str(tmp / 'first'), 'w')
    store.save('Gerdur', '013489', dict(memory.empty(), recent=[{'day': 1, 'hour': 12, 'text': 'Mercenary Archer has died.',
                                                                   'witnesses': ['Gerdur'], 'key': 'world:death-1'}]))
    from menu_talk import end_talk
    MD.prepare(store, GERDUR, 'Brom', data=world, knows=True)
    end_talk(store, [GERDUR], Summaries())
    recent = store.load('Gerdur', '013489')['recent']
    check('the menu memory, her earliest memory of the player (news does not count), is flagged first_meeting; the talk memory is not',
          'first_meeting' in (recent[1].get('flags') or []) and recent[1].get('dialogue') and not recent[0].get('flags')
          and 'first_meeting' not in (recent[2].get('flags') or []), recent)
    check('...and from then on nothing else is', not memory.first_contact(store.load('Gerdur', '013489')))
    MD.talk_over()


# --- 5. the stub keeps the player's words -------------------------------------------------------------------------------
class user_message(SimpleNamespace):
    pass


class assistant_message(SimpleNamespace):
    pass


def part_stub():
    thread = _json('conversations-Brom1-final', 'Sigrid - 013483', 'Sigrid.json')
    if not thread:
        return print("SKIP Sigrid's talk of live session 15 is not on this PC")
    talk = [(user_message if m['role'] == 'user' else assistant_message)(text=m['content']) for m in thread[0]]
    stub = memory.one_line(talk, memory.HOODED, 'Sigrid')
    check("the stub keeps the player's own words and her last reply, never the event lines",
          "who said: \"Nice weather we're having, isn't it?\"" in stub and 'Look at those clouds' in stub
          and 'ties' not in stub and 'recognise' not in stub, stub)


# --- 6. hood: never the name to someone who does not know him ------------------------------------------------------------
def part_hood():
    raw = 'Sigrid does not recognise Brom: a hood hides their face.'  # the real event, 14:31:39
    fixed = npc_block.fix_recognition_events([raw], lambda n: False, 'Brom')
    check("World's real line for Sigrid: the hooded stranger, the name nowhere", fixed[0] == 'Sigrid does not recognise the hooded '
          'stranger: a hood hides their face.' and not any('Brom' in f for f in fixed), fixed)
    check('someone who knows him still gets the name', npc_block.fix_recognition_events([raw], lambda n: True, 'Brom')
          == ['Sigrid knows Brom well and recognises them, hood or not.'])
    text = npc_block.recognition_text([('Sigrid', '013483')], [{'name': 'Sigrid', 'ref_id': '013483'}], 'Brom',
                                      lambda n, r, s: False, {'hold': 'Whiterun'}, hidden=True)
    check("the Hub's own greeting line too", 'Sigrid does not recognise the hooded stranger' in text and 'Brom' not in text, text)
    psc = CODING / 'Mantella-Living-World-World' / 'Source' / 'Scripts' / 'MLWW_Recognition.psc'
    if psc.is_file():
        src = psc.read_text(encoding='utf-8')
        check("World's verdict line (the source) no longer carries the name",
              'npc + " does not recognise the hooded stranger: a hood hides their face."' in src
              and '" does not recognise " + player' not in src)


# --- 8. the Now paragraph uses the talks' timeline ----------------------------------------------------------------------
def part_now_timeline():
    store = SimpleNamespace(root='x')
    mem = {'recent': [{'day': 1, 'hour': 12, 'text': 'She agreed: the last time.', 'witnesses': ['Gerdur'], 'talk': 't-late', 'seq': 9},
                      {'day': 1, 'hour': 14, 'text': 'We spoke once.', 'witnesses': ['Gerdur']}]}
    real = timeline.current
    timeline.current = lambda s, game_days=None: timeline.Cut(1.65, {'times': {'t-late': 0.7}, 'links': {}, 'gone': []})  # that talk came after this save
    try:
        shown = [e['text'] for e in bio_evolve._shown(mem, store)]
    finally:
        timeline.current = real
    check('a memory of a talk set aside as another timeline is not written into the Now paragraph', shown == ['We spoke once.'], shown)


# --- 9. a stranger dying nearby is not a close death -------------------------------------------------------------------
def part_death_close():
    archer = {'kind': 'death', 'involved': [{'key': '6D00C3A5', 'base': '', 'ref': '6D00C3A5', 'name': 'Mercenary Archer'}]}
    hod = {'kind': 'death', 'involved': [{'key': '01347E', 'base': '01347E', 'ref': '', 'name': 'Hod'}]}
    ties = news._tie_ids([{'kind': 'spouse', 'base': '01347E', 'name': 'Hod'}])
    me = {'name': 'Faendal', 'base': '01348C'}
    check("Faendal seeing a hostile mercenary die: not death_close (the session's archer)", not news.close_to_dead(archer, me, ties))
    check('her husband dying: death_close', news.close_to_dead(hod, {'name': 'Gerdur', 'base': '01347C'}, ties))
    src = (SERVER / 'living_world' / 'news.py').read_text(encoding='utf-8')
    check('news uses it', "close_death = how['ring'] in (1, 2) and close_to_dead(e, me, ties)" in src)


with tempfile.TemporaryDirectory() as tmp:
    for part in (lambda: part_late_scenes(Path(tmp)), part_after_scene_talk, part_person_time, lambda: part_first_meeting(Path(tmp)),
                 part_stub, part_hood, part_now_timeline, part_death_close):
        try:
            part()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'{getattr(part, "__name__", "part")} ran without an error', False, e)
        MD.talk_over()

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
