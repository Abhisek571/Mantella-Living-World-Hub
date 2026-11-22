"""Offline tests for live session 14 (2026-11-16), built from the real files it left: Gerdur's 11 menu dialogue lines
and the two scenes that ended between them, Faendal's short talk with a 600 gold gift, and the scan of a real
dialogue-mod list. The session's files are read from its folder when it is on this PC (never copied into the
repository); a part that needs them is skipped without them.
Run with a Python 3.11: test_live_test_14.py <repo server dir>"""
import json, os, re, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1]).resolve()
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
from living_world import archive, lw_state, memory, menu_dialogue as MD, mod_facts_gen as G, mod_facts_scan, npc_block, settings
memory.SUMMARY_RETRY_SECONDS = 0

LIVE14 = os.path.join(os.environ.get('MLW_EVIDENCE', ''), r'lw-live-test-14-2026-11-16')
CREATED = os.path.join(LIVE14, 'session-created')
FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
    if not cond:
        FAILS.append(name)


def _world():
    try:
        return json.loads(Path(os.path.join(CREATED, 'StorageUtilData-MLW', 'menu_dialogue.json')).read_text(encoding='utf-8'))
    except OSError:
        return None


# the two OStim scenes (OStim.log 11:54:54-11:55:24 and 11:55:31-11:55:37) as OStim Expansion now hands them over: its own
# wording, with the game time it ended. Their game times sit between the menu lines around them (11:54:52 / 11:55:26 and
# 11:55:30 / 11:55:39), read off those lines' own game times.
SCENE_1 = (0.5766, 'Gerdur and the player finished having sex in Riverwood. They did a blowjob and a handjob.')
SCENE_2 = (0.5792, 'Gerdur and the player finished having sex in Riverwood. They did a blowjob and Masturbation.')
GERDUR = SimpleNamespace(name='Gerdur', ref_id='013489', base_id='01347C', bio='Owner of the Riverwood mill.')


class Summaries:
    _Summaries__language_name = 'English'

    def __init__(self):
        self.calls = []

    def summarize_conversation(self, text, prompt):
        self.calls.append((text, prompt))
        return json.dumps({'memory': 'Brom asked me for a favour twice; each time I gave in, and then we had sex.',
                           'feelings': {'Gerdur': 'embarrassed'}, 'importance': 0.6})


def scene_event(t, text):
    return f"Earlier (less than an hour ago), with no conversation going on: {text} {{t={t}}}"


# --- 1. the strict prompt, the real 11 lines and 2 scene records ------------------------------------------------------------
def part_prompt(tmp):
    world = _world()
    if not world:
        return print('SKIP the live session 14 menu dialogue is not on this PC')
    lines = world['npcs']['01347C']['lines']
    check('the real capture: 11 lines of Gerdur, 3 of them vanilla greetings', len(lines) == 11 and sum(l['vanilla'] for l in lines) == 3)
    groups = MD.exchanges(lines, [SCENE_1, SCENE_2])
    check('split into the real order: exchange 1 (6 lines), scene 1, exchange 2 (3 lines), scene 2, then 2 more lines',
          [len(g['lines']) for g in groups] == [6, 3, 2] and groups[0]['scenes'] == [SCENE_1[1]] and groups[1]['scenes'] == [SCENE_2[1]]
          and groups[2]['scenes'] == [], [(len(g['lines']), g['scenes']) for g in groups])
    check('without scene records a real gap (34 s) still splits the two asks', [len(g['lines']) for g in MD.exchanges(lines)] == [6, 5])
    store = memory.MemoryStore(str(tmp / 'prompt'), 'w')
    summaries = Summaries()
    made = MD.remember(store, GERDUR, 'Brom', summaries, data=world, scenes=[SCENE_1, SCENE_2], knows=False)
    check('one summary request (the background path) makes one memory', len(made) == 1 and len(summaries.calls) == 1, made)
    text, prompt = summaries.calls[0]
    check('the strict rules come first: only what the lines and records say, exchanges separate and in order, no act named '
          'that no line or record states', prompt.startswith(MD.MENU_RULES.format(name='Gerdur', player='Brom'))
          and 'Never name an act' in prompt and 'Keep every exchange separate and in its order' in prompt, prompt[:400])
    check('the end-of-talk request (the usual path now) asks the same: only what the lines say, exchanges in order, no act '
          'or feeling no line states, an unrecorded topic never invented', all(x in MD.MENU_ASK for x in (
              'Report only what those lines and records say', 'keep each exchange separate and in its order',
              'never name an act, a place, a reason or a feeling no line or record states', 'do not invent them')))
    order = [text.index(x) for x in ('Exchange 1:', "Shut your damn mouth", 'Then: ' + SCENE_1[1].replace('the player', 'Brom'), 'Exchange 2:',
                                     'But this is the last time.', 'Then: ' + SCENE_2[1].replace('the player', 'Brom'), 'Exchange 3:', "Come to my home when Hod's not there.")]
    check('the dialogue sent: each exchange numbered, followed by the scene record that ended after it (its wording, the name '
          'for "the player")', order == sorted(order), text)
    check("a blank player topic of the mod's own dialogue is shown as not recorded (never invented); a vanilla greeting has none",
          'Brom: (topic not recorded)' in text and 'Brom: Hello' in text and "Brom: I've tried the river. It doesn't work." in text)
    entry = store.load('Gerdur', '013489')['recent'][0]
    check('dated with the talk memories\' days (World day 0.571 -> day 1, 13:00), intimacy flag, importance at least 0.9',
          (entry['day'], entry['hour']) == (1, 13) and 'intimacy' in entry['flags'] and entry['importance'] >= 0.9, entry)
    check('the mod\'s own dialogue was face to face and intimate: she knows him (the name, never "the hooded stranger")',
          'unrecognised' not in entry and 'Brom: (topic' in text and 'hooded' not in prompt.split('Exchange')[0][-400:], entry)
    print('--- prompt sent with the menu dialogue (rules + the usual summary request, first 900 characters) ---\n'
          + prompt[:900] + '\n--- dialogue sent ---\n' + text + '\n---')


# --- 2. a line Mantella already showed in the talk is used --------------------------------------------------------------
def part_delivered(tmp):
    world = _world()
    if not world:
        return print('SKIP the live session 14 menu dialogue is not on this PC')
    first = json.loads(json.dumps(world))
    first['npcs']['01347C']['lines'] = first['npcs']['01347C']['lines'][:10]  # the 11th was spoken after the talk opened
    store = memory.MemoryStore(str(tmp / 'delivered'), 'w')
    MD.remember(store, GERDUR, 'Brom', Summaries(), data=first, sexual=lambda p: True)
    MD.talk_over()
    event = "Brom: I've tried the river. It doesn't work.;\n Gerdur: Don't talk about it here! Come to my home when Hod's not there."
    check('the 11th line, shown in talk 1 as an event, is marked used', MD.mark_delivered([event], [GERDUR], store, 'Brom', data=world) == 1)
    again = Summaries()
    check('talk 2 makes no second memory of it (no summary request, no wait)', MD.remember(store, GERDUR, 'Brom', again, data=world) == []
          and again.calls == [])
    MD.talk_over()
    store2 = memory.MemoryStore(str(tmp / 'other'), 'w')
    MD.remember(store2, GERDUR, 'Brom', Summaries(), data=first, sexual=lambda p: True)
    check('an event with other words marks nothing', MD.mark_delivered(['Gerdur equipped Axe', 'Brom: Hello.;\n Gerdur: Hm.'],
                                                                       [GERDUR], store2, 'Brom', data=world) == 0)
    MD.talk_over()


# --- 3/4. one game day everywhere; scene memories dated, first person, no relative text ------------------------------------
def part_days(tmp):
    check("World's day fraction and OStim Expansion's time give the talk memories' day (GameDaysPassed + 1)",
          MD.game_day_hour(0.5709530115127563) == (1, 13) and MD.game_day_hour(SCENE_2[0]) == (1, 13) and memory.MANTELLA_DAY == 1)
    path = os.path.join(CREATED, 'conversations-Brom1', 'living_world', 'Gerdur - 013489.json')
    if os.path.isfile(path):
        talk = [e for e in json.loads(Path(path).read_text(encoding='utf-8'))['recent'] if 'first_meeting' in (e.get('flags') or [])][0]
        check("...the same day as talk 1's memory in the session (day 1), so talk 2 no longer says \"yesterday\"",
              talk['day'] == MD.game_day_hour(0.5822)[0], talk['day'])
    store = memory.MemoryStore(str(tmp / 'scenes'), 'w')
    raw = [scene_event(*SCENE_1)]
    clean, found = MD.scene_records(raw)
    check('the time tag is taken out before the model sees the event', '{t=' not in clean[0] and found == [SCENE_1], (clean, found))
    saved = MD.remember_scene_events(raw, [GERDUR], store, 0, None, knows=lambda c: False, player='Brom')
    entry = store.load('Gerdur', '013489')['recent'][-1]
    check('an unpaired scene: its own memory, at its absolute day and hour', saved == 1 and (entry['day'], entry['hour']) == (1, 13), entry)
    check('...in her own words ("Brom and I ... We did"), no stored relative time', entry['text'].startswith('Brom and I finished having sex')
          and 'We did a blowjob' in entry['text'] and 'ago' not in entry['text'] and 'before we talked' not in entry['text'], entry['text'])
    store2 = memory.MemoryStore(str(tmp / 'paired'), 'w')
    check('a scene paired with the menu dialogue before it is not saved a second time',
          MD.remember_scene_events(raw, [GERDUR], store2, 0, None, paired={SCENE_1[1]}) == 0)
    src = (SERVER / 'living_world' / '__init__.py').read_text(encoding='utf-8')
    body = src[src.index('def _menu_memories('):src.index('def _menu_before_prompt(')]
    check('the scenes are saved from the events that still carry their times', 'remember_scene_events(raw,' in body)
    mae = (REPO.parent / 'Mantella-Living-World-OStim-Expansion' / 'Source' / 'Scripts' / 'MAE_Live.psc')
    if mae.is_file():
        check('OStim Expansion hands the scene over with its game time', '" {t=" + StringUtil.Substring(entry, 0, bar) + "}"'
              in mae.read_text(encoding='utf-8'))


# --- 5. the fact lines are there for the first prompt -----------------------------------------------------------------------
def part_first_prompt():
    psc = (REPO / 'Source' / 'Scripts' / 'MLW_Channel.psc').read_text(encoding='utf-8')
    first = psc[psc.index('Function WriteMinorFirst('):psc.index('EndFunction', psc.index('Function WriteMinorFirst('))]
    # the child flag is saved first (the greeting waits on it), then the mod fact lines, then a second save
    check("the mod fact lines are written in the npc file's first step, after the child flag's early save",
          'MLW_ModFacts.WriteNpc(akNpc, path)' in first
          and first.index('"minor"') < first.index('JsonUtil.Save(path)') < first.index('MLW_ModFacts.WriteNpc'))
    check('...and saved right after', first.count('JsonUtil.Save(path)') == 2
          and first.rindex('JsonUtil.Save(path)') > first.index('MLW_ModFacts.WriteNpc'))


# --- 6/7. short talks; the gift ---------------------------------------------------------------------------------------------
class user_message(SimpleNamespace):
    pass


class assistant_message(SimpleNamespace):
    pass


def _faendal():
    path = os.path.join(CREATED, 'conversations-Brom1', 'Faendal - 01348C', 'Faendal.json')
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))[0]
    except OSError:
        return None


def part_short():
    thread = _faendal()
    if not thread:
        return print("SKIP Faendal's talk of live session 14 is not on this PC")
    talk = [(user_message if m['role'] == 'user' else assistant_message)(text=m['content']) for m in thread]
    texts = [m['content'] for m in thread]
    # the events reach talk_flags twice: as the message's own events and inside its text (why 600 became 1200)
    events = re.findall(r'\(\(?[^()]*\)\)?', thread[1]['content'])
    found = memory.talk_flags(events + texts, 'Faendal', 'Brom')
    check("the real gift: 600 gold, counted once although the trade line is read twice", found.get('gift') == 600, found)
    check('a short talk with a flagged event is still summarised for real',
          memory.short_but_important(texts, memory._player_lines(talk), found, False))
    regret = [user_message(text='Do you regret what we did?'), assistant_message(text="Keep your voice down. No. Not the way you think.")]
    check('so is one where the player asks about the relationship (her answer to "Do you regret what we did?" was lost)',
          memory.short_but_important([m.text for m in regret], memory._player_lines(regret), {}, False))
    check('...and one that follows menu dialogue or scene memories made at its start', memory.short_but_important(['Hello.'], ['Hello.'], {}, True))
    check('small talk stays a stub', not memory.short_but_important(['Nice weather.', 'Aye.'], ['Nice weather.'], {}, False))
    stub = memory.one_line(regret, 'Brom', 'Gerdur')
    check("the stub keeps the player's line and her last reply, not just a greeting",
          'Do you regret what we did?' in stub and 'Not the way you think.' in stub, stub)
    entry = {'day': 1, 'hour': 18, 'text': memory.one_line(talk, memory.HOODED, 'Faendal'), 'importance': 0.2}
    memory.apply_talk_flags({'recent': [entry]}, entry, found, 1)
    check('a flagged gift is in the memory text and carries the 0.8 floor even in a stub',
          '600 gold' in entry['text'] and entry['importance'] >= archive.FLAG_FLOORS['gift'] == 0.8 and entry['gift_gold'] == 600, entry)
    src = (SERVER / 'living_world' / 'memory.py').read_text(encoding='utf-8')
    check('the short-talk branch asks short_but_important first', 'not \\\n                short_but_important(' in src
          or 'short_but_important(_thread_texts(params.messages)' in src)


# --- 8. the hooded stranger, the same words everywhere --------------------------------------------------------------------
def part_hood(tmp):
    world = {'player': 'Brom', 'npcs': {'01348C': {'name': 'Faendal', 'lines': [
        {'said': 'Hello', 'line': 'Camilla is lovely, isn\'t she?', 'time': 10.0, 'day': 1.5, 'plugin': 'Skyrim.esm', 'vanilla': 1}]}}}
    faendal = SimpleNamespace(name='Faendal', ref_id='01348C', base_id='01348C', bio='')
    store = memory.MemoryStore(str(tmp / 'hood'), 'w')
    summaries = Summaries()
    MD.remember(store, faendal, 'Brom', summaries, data=world, knows=False, sexual=lambda p: False)
    text, prompt = summaries.calls[0]
    check('menu dialogue of an NPC who does not know the hooded player: "the hooded stranger" in the lines and the rules',
          'the hooded stranger: Hello' in text and 'Brom' not in text and 'with the hooded stranger in the game' in prompt, text)
    MD.talk_over()
    event = "Brom: Keep it. That's a gift.;\n Faendal: Six hundred gold?"
    check("Mantella's own stored dialogue event names him only to those who know him",
          MD.mask_strangers([event], 'Brom', {'Faendal'})[0].startswith('The hooded stranger:')
          and MD.mask_strangers([event], 'Brom', set())[0] == event)
    speaker = {'name': 'Faendal', 'ref_id': '0001348C', 'modfact_1': 'Some Mod|Helped {player} with the bow.'}
    shown = npc_block.npc_text(None, speaker, [], 'Brom', knows=lambda s: False)
    check('a mod fact line says "the hooded stranger" to an NPC who does not know him, the name to one who does',
          'Helped the hooded stranger with the bow.' in shown and 'Helped Brom with the bow.' in npc_block.npc_text(None, speaker, [], 'Brom', knows=lambda s: True), shown)
    store2 = memory.MemoryStore(str(tmp / 'hood2'), 'w')
    MD.remember_scene_events([scene_event(*SCENE_1)], [GERDUR], store2, 0, None, knows=lambda c: False, player='Brom')
    check('an intimate scene record: she knows him (decision: intimacy means recognised), so the name',
          store2.load('Gerdur', '013489')['recent'][-1]['text'].startswith('Brom and I'))
    src = (SERVER / 'living_world' / '__init__.py').read_text(encoding='utf-8')
    knows = src[src.index('def _knows_player('):src.index('_unrecognised: dict')]
    check('...and from then on in every talk (an intimacy memory counts as knowing him)', "'intimacy' in (e.get('flags')" in knows)


# --- 9. the scan's final result -----------------------------------------------------------------------------------------
def part_scan_result(tmp):
    out = tmp / 'modfacts' / 'generated'
    out.mkdir(parents=True)
    result = {'drafts': {'shadowman_gerdur.esp': {'npcs': [{'facts': [{}, {}]}]}, 'OStim.esp': 'a framework', 'x.esp': 'no dialogue'}, 'written': []}
    check('no scan yet: nothing to show', mod_facts_scan.last_result(str(out)) == '')
    mod_facts_scan.save_last(str(out), result)
    shown = mod_facts_scan.last_result(str(out))
    check('the final table is stored next to generated/ and read back (after a restart too)',
          '| shadowman_gerdur.esp | 1 | 2 |' in shown and '| OStim.esp | a framework |' in shown and shown.startswith('Last scan: '), shown)
    ui = (SERVER / 'living_world' / 'ui_overrides.py').read_text(encoding='utf-8')
    check("the page has a button for it, also an API call (lw_scan_result)", "api_name='lw_scan_result'" in ui and 'Show the last scan result' in ui)


# --- 10. scanned files off by default; the generator --------------------------------------------------------------------
def part_generated(tmp):
    check('"Use scanned mod facts (experimental)" is off by default', settings.DEFAULTS.get('mod_facts_generated') is False)
    psc = (REPO / 'Source' / 'Scripts' / 'MLW_ModFacts.psc').read_text(encoding='utf-8')
    check('the game reads generated/ only while the switch file says on (user and shipped always)',
          'JsonUtil.GetIntValue(Root() + "use_generated.json", "on", 0) != 1' in psc)
    out = tmp / 'switch' / 'generated'
    check('the switch file is written in the shape the game reads', mod_facts_scan.set_use_generated(str(out), True)
          and json.loads(Path(out.parent / 'use_generated.json').read_text()) == {'int': {'on': 1}})
    from living_world import ui_overrides
    spath = str(tmp / 'settings.json')
    real = ui_overrides.mod_facts_where
    ui_overrides.mod_facts_where = lambda values=None: {'out': str(out)}
    try:
        said = ui_overrides.use_scanned_facts(False, spath)
    finally:
        ui_overrides.mod_facts_where = real
    check('the page switch saves the setting and the switch file', settings.load(spath)['mod_facts_generated'] is False
          and json.loads(Path(out.parent / 'use_generated.json').read_text()) == {'int': {'on': 0}} and 'not used' in said, said)
    long = ("Look, Irelith and 8 other guards were out there. I knew all of them. Every guard that fought alongside you was "
            "just as much a hero as you were, and I won't forget it.")
    q = G._quote(long)
    check('a long quote ends at a sentence end, at most 120 characters', q == 'Look, Irelith and 8 other guards were out there. I knew all of them.', q)
    q = G._quote('one two three four five six seven eight nine ten eleven twelve thirteen fourteen', 40)
    check('...or at a whole word with "...", never inside a word', q == 'one two three four five six seven...', q)
    check('settings, SMP, voice, combat and speaking flags are skipped',
          all(G.CONFIG.search(x) for x in ('HasaraSMP', 'MM_SeranaCombatSpeaking', 'aaElisifCombatStyle', 'VoiceToggle', 'DebugMode'))
          and not G.CONFIG.search('gerdurfuckedstate') and not G.CONFIG.search('_ICBLydia'))
    check("follower frameworks' factions and framework plugins are skipped", G.FOLLOWER_FACTION.search('nwsFF_SparFac')
          and G.denied('OStim Lovers.esp') and G.denied('SexLab_Solutions.esp') and G.denied('nwsFollowerFramework.esp')
          and not G.denied('shadowman_gerdur.esp') and not G.denied('FDE Aela.esp'))
    gv, npc, q1, f1 = 0x01000800, 0x01000801, 0x01000802, 0x01000803
    def info(i, value, resp, faction=False):
        conds = [{'func': G.F_GETISID, 'op': '==', 'value': 1.0, 'p1': npc, 'p2': 0}]
        conds.append({'func': G.F_GETINFACTION, 'op': '==', 'value': 1.0, 'p1': f1, 'p2': 0} if faction else
                     {'func': G.F_GETGLOBALVALUE, 'op': '==', 'value': float(value), 'p1': gv, 'p2': 0})
        return {'id': i, 'topic': None, 'conds': conds, 'resp': resp, 'prompt': ''}
    parsed = {'masters': ['Skyrim.esm'], 'localized': False, 'light': False, 'glob': {gv: {'edid': 'LunchState', 'start': 0}},
              'qust': {}, 'fact': {f1: {'edid': 'nwsFollowerFaction'}}, 'npc': {npc: {'edid': 'Gyda', 'name': 'Gyda'}}, 'dial': {},
              'info': [info(1, 1, ['Back again? The stew is hot today.']), info(2, 1, ['Hot stew, friend.']), info(3, 1, ['Sit.']),
                       info(4, 2, ['']), info(5, 2, ['']), info(6, 2, ['']),  # no words at 2: label only, dropped
                       info(7, 3, ['Come here and suck it.']), info(8, 3, ['Get naked.']), info(9, 3, ['Fine, sit down.']),
                       info(10, 0, ['x'], faction=True), info(11, 0, ['y'], faction=True), info(12, 0, ['z'], faction=True)]}
    made = G.draft('Lunch.esp', parsed, 'Lunch Lady', sexual=False)
    texts = [l['text'] for f in made['npcs'][0]['facts'] for l in f['lines']]
    check('a line with no quoted text is dropped; the explicit-word rule holds for a plugin with no scenes too; no follower faction',
          texts == ['Lunch Lady: LunchState 1 (of 1-3). Said at this value: "Back again? The stew is hot today."']
          and all(f['kind'] != 'faction' for f in made['npcs'][0]['facts']), texts)


with tempfile.TemporaryDirectory() as tmp:
    lw_state.DATA_DIR = os.path.join(tmp, 'channel')  # World's acknowledgement (menu_ack.json) never goes to a real folder
    for part in (lambda: part_prompt(Path(tmp)), lambda: part_delivered(Path(tmp)), lambda: part_days(Path(tmp)),
                 part_first_prompt, part_short, lambda: part_hood(Path(tmp)), lambda: part_scan_result(Path(tmp)),
                 lambda: part_generated(Path(tmp))):
        try:
            part()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'{getattr(part, "__name__", "part")} ran without an error', False, e)
        MD.talk_over()

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
