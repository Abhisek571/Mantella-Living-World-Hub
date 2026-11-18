"""Offline tests for the defects found by live test 6 (2026-11-15), built from the files that test left behind (copied in
here as data where small): the player's own world.json and battles.json called "another character's", recognition
leaking the player's name through memories of talks with a hooded stranger, the greeting's tool block differing from
the first reply's at a first meeting, a forget command with no line in the true record, a name differing only in case
on the NPCs page, the page's summary line without the game's spouse and follower values, the short-bio checks, a
follower's outfit swap sent as thirty event lines, and the Console helper call that always timed out.
Run with a Python 3.11: test_live_test_6.py <repo server dir>"""
import json, logging, os, shutil, sys, tempfile, threading, time, types
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
import living_world as LW
from living_world import (action_filter as AF, bio_evolve as B, bio_optimise as BO, characters as C, command, console,
                          embed, lw_state, memory, npc_block, npc_page_ui as P, prompt_rules, release as R)
memory.SUMMARY_RETRY_SECONDS = 0
embed.use(None)
HUB = SERVER.parent

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:600]) if not cond else ''))
    if not cond:
        FAILS.append(name)


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(1)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


LOG = Lines()
logging.getLogger('Mantella').addHandler(LOG)
logging.getLogger('Mantella').setLevel(1)


class Char:
    def __init__(self, name, ref_id, bio='A person.'):
        self.name, self.ref_id, self.bio = name, ref_id, bio

class Thread(list):
    def get_talk_only(self):
        return list(self)
    def transform_to_dict_representation(self, messages):
        return '\n'.join(str(m) for m in messages)

class Params:
    def __init__(self, lines, chars):
        self.messages, self.characters = Thread(lines), chars

class People:
    def get_player_name(self):
        return 'Brom'

class FakeSummaries:
    def __init__(self, threads, reply):
        self.threads, self.reply, self.calls = threads, reply, []
    def get_threads_for_summarization(self, messages, npcs):
        return self.threads
    def group_shared_threads(self, threads):
        return [[n] for n in threads]
    def summarize_conversation(self, text, prompt):
        self.calls.append((text, prompt))
        return self.reply


# --- the live test's files (small ones as data) -------------------------------------------------------------------------
STALE_CONVERSATION = {"int": {"day": 1, "setup_done": 0}, "string": {"player": "Prisonerdax"}, "stringList": {}}  # 2026-11-13
WORLD = {"day": 2.67, "loading": 0, "player": "Brom", "hold": "Whiterun", "fame": {"Whiterun": 0}, "thane": [], "events": []}
BATTLES = {"fights": [{"active": 1, "end": 2.705, "fighters": [{"base_id": "000007", "name": "Brom", "role": "player"}]}], "player": "Brom"}
LUCAN_FINAL = {"int": {"affection": 1, "allow_intimacy": 0, "carry_gold": 138, "close": 0, "follower": 0, "guard": 0, "housecarl": 0,
                       "illusion": 15, "intimate": 1, "magic": 0, "maras": 0, "maras_on": 1, "maras_tracked": 0, "merchant": 0,
                       "minor": 0, "nff": 0, "rank": 0, "rated": 0, "scene": 0, "spouse": 0, "surv_warm": 0, "trades_free": 0},
               "string": {"name": "Lucan Valerius", "ref_id": "00013487", "race": "Imperial", "sex": "male", "hold": "Whiterun",
                          "home": "Riverwood Trader", "home_town": "Riverwood", "location": "Riverwood", "town": "Riverwood"}}
HUB_WRITES = ('close', 'intimate', 'minor', 'follower', 'guard', 'rank', 'housecarl', 'spouse', 'allow_intimacy', 'rated',
              'illusion', 'magic', 'trades_free')  # MLW_Channel.WriteNpc; the other ints come from the other modules
LUCAN_MEMORY = [  # conversations-Brom1/living_world/Lucan Valerius - 013487.json, before his third talk
    {"day": 1, "hour": 15, "witnesses": ["Lucan Valerius"], "importance": 0.55, "type": "relationship", "talk": "1-1912291474-651612", "seq": 1,
     "text": "A hooded stranger, Brom, came into the Riverwood Trader. Having heard about the break-in, they insisted on giving me 100 gold toward my losses, and I accepted with thanks."},
    {"day": 2, "hour": 12, "witnesses": ["Lucan Valerius"], "importance": 0.2, "talk": "6-118514373-1684923", "seq": 6,
     "text": "Spoke briefly with Brom: Hello, friend. I don't believe we've met, though I'm Lucan Valerius, of the Riverwood Trader, just down the road."},
    {"day": 2, "hour": 14, "witnesses": ["Lucan Valerius"], "source": "told", "type": "knowledge", "told_by": "Camilla Valerius",
     "importance": 0.65, "tags": ["news", "killing"], "talk": "7-642787397-1756477", "seq": 7, "key": "world:crime-murder-00013486-799",
     "text": "A hooded stranger murdered Orgnar at Sleeping Giant Inn."}]
LUCAN_REPLY = json.dumps({"memory": "A hooded stranger, Brom, came into the Riverwood Trader. Having heard about the break-in, they "
                                    "insisted on giving me 100 gold toward my losses, and I accepted with thanks.",
                          "feelings": {"Lucan Valerius": "grateful toward Brom, a little puzzled"}, "importance": 0.55})
ALVOR_GREETING = ["Well met, stranger. Ain't every day we get visitors in Riverwood, and you've picked a fine time for a drink at the "
                  "Sleeping Giant.", "If you need a blade mended or sharpened, my forge is just down by the river."]
GERDUR_COMMAND = {"id": "9ac72919d0e5", "key": "2.558723-281119", "text": "Forget that I gave you the necklace.", "given": 2.558723,
                  "npcs": [{"name": "Gerdur", "ref_id": "013489"}], "forget": "the player giving them the necklace", "aware": False,
                  "status": "active", "announced": True, "hidden": [], "read_by": "model", "hours": 0.0, "until": -1.0,
                  "bio_before": [], "forget_mode": "clean"}
GERDUR_TALK = ("Meeting a hooded stranger at the inn, I heard Orgnar had been murdered and the village is shaken. The stranger gave me "
               "a silver necklace they said they picked out in Whiterun, and I said I'd wear it with thanks.")
TIES = {"013475": {"day": 2, "home": "Alvor and Sigrid's House", "name": "Alvor",
                   "ties": [{"base": "013477", "kind": "child", "name": "Dorthe"}, {"base": "013476", "kind": "Spouse", "name": "Sigrid"}]}}
ALVOR_NPC = {"int": {"close": 1, "follower": 0, "rank": 1, "minor": 0, "spouse": 0, "guard": 0},
             "string": {"name": "Alvor", "race": "Nord", "ref_id": "00013482", "work": "Blacksmith", "hold": "Whiterun"}}
LIRA_NPC = {"int": {"close": 1, "follower": 0, "nff": 1, "rank": 3, "minor": 0}, "string": {"name": "lira", "race": "Dark Elf", "ref_id": "FE25C80E"}}
OUTFIT_BATCH = ["lira has joined the player's party.", "lira unequipped Nyxari's Earrings", 'lira unequipped Glass Dagger',
                "lira dropped/gave Nyxari's Earrings", 'lira picked up/took Silver Ring', 'lira equipped Silver Ring', 'lira equipped Glass Dagger',
                'lira unequipped Silver Ring', 'lira equipped Glass Dagger', 'lira dropped/gave Silver Ring',
                'lira equipped ColdHarbour BloodSpiller Suit', 'lira equipped ColdHarbour BloodSpiller Gloves',
                'lira equipped ColdHarbour BloodSpiller Heels', 'lira equipped ColdHarbour BloodSpiller Bracers',
                'lira unequipped ColdHarbour BloodSpiller Suit', 'lira dropped/gave ColdHarbour BloodSpiller Suit',
                'lira unequipped ColdHarbour BloodSpiller Gloves', 'lira unequipped ColdHarbour BloodSpiller Heels',
                'lira unequipped ColdHarbour BloodSpiller Bracers', "lira equipped Cosplay Gala Gown 'Saturnalia' - Amber",
                "lira equipped Cosplay Gala Necklace 'Rio de Plata'", 'lira equipped Cosplay Gala Shoes Stiletto Strapped - Noire',
                "lira equipped Nyxari's Earrings", 'lira now fights in Melee style.', 'lira follows the player.']
SECOND_BATCH = ['lira picked up/took 200 Gold', "lira equipped Cosplay Gala Gown 'Saturnalia' - Amber",
                "lira equipped Cosplay Gala Necklace 'Rio de Plata'", 'lira equipped Cosplay Gala Shoes Stiletto Strapped - Noire',
                'lira equipped Cosplay Gloves Full Long - Lace', 'lira equipped Glass Dagger']


def write(base: Path, name: str, data, when=None):
    path = base / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')
    if when is not None:
        os.utime(path, (when, when))


def fresh_live():
    lw_state._live.update(player='', time=None)


# --- 1. "another character" for the player's own files -------------------------------------------------------------------
def part_player_name(tmp):
    ch = tmp / 'channel1'
    lw_state.DATA_DIR = str(ch)
    fresh_live()
    t = time.time() - 100
    write(ch, 'world.json', dict(WORLD, day=0.62), t)  # World rewrote them right after the load (Brom, day 0 at 19:29)
    write(ch, 'battles.json', BATTLES, t)
    write(ch, 'conversation.json', STALE_CONVERSATION, t + 50)  # saved by the talk counter at talk start, player line stale
    LOG.lines.clear()
    check('cause (reproduced): the expected name was the stale "Prisonerdax" from an older session in conversation.json',
          lw_state.load_player_name() == 'Prisonerdax' and not lw_state.load_battles(), lw_state.load_player_name())
    lw_state.note_live_player('Brom')  # Mantella's own name for the player in the talk going on
    LOG.lines.clear()
    check('with Mantella naming the player (newer than the stale file): the player is Brom', lw_state.load_player_name() == 'Brom')
    check("with Mantella naming the player: battles.json and world.json are Brom's own and kept",
          len(lw_state.load_battles()) == 1 and lw_state.load_world().get('player') == 'Brom')
    check('no "another character" warning for the player\'s own files', not any('another character' in l for l in LOG.lines), LOG.lines)
    fresh_live()
    write(ch, 'conversation.json', dict(STALE_CONVERSATION, string={'player': 'Brom'}), t + 60)  # the fixed game side's talk start
    check('the fixed game side writes the player line with the talk counter: Brom, files kept',
          lw_state.load_player_name() == 'Brom' and len(lw_state.load_battles()) == 1)
    src = (HUB / 'Source' / 'Scripts' / 'MLW_Channel.psc').read_text(encoding='utf-8')
    started = src[src.index('Event OnStarted()'):src.index('EndEvent', src.index('Event OnStarted()'))]
    ended = src[src.index('Event OnEnded()'):src.index('EndEvent', src.index('Event OnEnded()'))]
    check('game side: OnStarted writes the player line before the talk counter saves conversation.json',
          'SetStringValue(CONVERSATION, "player"' in started and started.index('"player"') < started.index('TalkStarted'), started[:400])
    check('game side: the day is written there too (a stale day hides a newer world.json)',
          'SetIntValue(CONVERSATION, "day"' in started and started.index('"day"') < started.index('TalkStarted')
          and 'SetIntValue(CONVERSATION, "day"' in ended)
    check('game side: OnEnded too', 'SetStringValue(CONVERSATION, "player"' in ended and ended.index('"player"') < ended.index('TalkEnded'))
    check('safe by design: another character only when both names are known, not empty, and differ',
          lw_state.other_character('Prisonerdax', 'Brom') and not lw_state.other_character(' brom ', 'Brom')
          and not lw_state.other_character('Brom', '') and not lw_state.other_character('', 'Brom')
          and not lw_state.other_character(None, 'Brom'))
    fresh_live()


# --- 2. recognition: a hooded stranger is not named ------------------------------------------------------------------------
def part_recognition(tmp):
    ch = tmp / 'channel2'
    lw_state.DATA_DIR = str(ch)
    write(ch, 'conversation.json', {'string': {'player': 'Brom'}, 'int': {'day': 2}, 'stringList': {'speakers': []}})
    write(ch, 'recognition.json', {'int': {'face_hidden': 1}})
    write(ch, 'world.json', WORLD)
    fresh_live()
    store = memory.MemoryStore(str(tmp / 'conversations'), 'Brom1')
    lucan = {'recent': [dict(e) for e in LUCAN_MEMORY]}
    check('cause (reproduced on the old count): Lucan\'s two talks with a hooded stranger plus the news made 3 "talks"',
          len([e for e in lucan['recent'] if not e.get('radiant') and not e.get('reload') and not e.get('battle')]) == 3)
    check('news and things told are no talk: Lucan has 2 talks, so he does not "know the player well" at his third talk',
          memory._player_talks(lucan) == 2 and not npc_block.knows_player({'rank': 0}, False, memory._player_talks(lucan)))
    check('a talk flagged unrecognised does not count either', memory._player_talks({'recent': [{'text': 'x', 'unrecognised': True}]}) == 0)

    # the summary of a talk with a hooded stranger: no name, flagged
    lucan_char = Char('Lucan Valerius', '013487')
    summaries = FakeSummaries({'Lucan Valerius': Params([f'line {i}' for i in range(8)], [lucan_char])}, LUCAN_REPLY)
    ctx = {'messages': None, 'npcs_to_summarize': [lucan_char], 'npcs_in_conversation': People(), 'is_reload': False,
           'end_timestamp': 0.62, 'is_radiant': False, 'summaries': summaries, 'unrecognised': lambda c: True}
    memory.summarize(ctx, store)
    saved = store.load('Lucan Valerius', '013487')
    newest = saved['recent'][-1]
    check('memory of the hooded talk: the name is not in it ("A hooded stranger came into the Riverwood Trader")',
          'Brom' not in newest['text'] and newest['text'].startswith('A hooded stranger came into the Riverwood Trader'), newest['text'])
    check('memory of the hooded talk: flagged unrecognised', newest.get('unrecognised') is True)
    check('the feeling does not name the player either', 'Brom' not in saved.get('feeling', ''), saved.get('feeling'))
    check('the summary prompt says they never learned the name', 'never by name' in summaries.calls[-1][1], summaries.calls[-1][1][-300:])
    # Alvor's short first talk (the greeting only)
    alvor = Char('Alvor', '013482')
    summaries = FakeSummaries({'Alvor': Params(ALVOR_GREETING, [alvor])}, '')
    memory.summarize(dict(ctx, npcs_to_summarize=[alvor], summaries=summaries), store)
    line = store.load('Alvor', '013482')['recent'][-1]['text']
    check('a short talk with a hooded stranger: "Spoke briefly with a hooded stranger", not "with Brom"',
          line.startswith('Spoke briefly with a hooded stranger:') and 'Brom' not in line, line)

    # later: the NPC learns who it was (a command, a tie, the hood off): one line connects it
    class C2:
        name, ref_id = 'Lucan Valerius', '013487'
    text = memory.memory_text('', {'characters': [C2()], 'player': 'Brom', 'recall': False, 'knows_player': lambda c: True}, store)
    check('knows the player now: one line says the hooded stranger was Brom', 'The hooded stranger in these memories was Brom' in text, text[-300:])
    text = memory.memory_text('', {'characters': [C2()], 'player': 'Brom', 'recall': False, 'knows_player': lambda c: False}, store)
    check('still a stranger: no such line', 'was Brom' not in text, text[-300:])
    # a news memory of a masked event, not named to them, carries the flag too (the witness who later knows the player)
    mid = memory.add_memory(store, 'Camilla Valerius', '013488', 'A hooded stranger murdered Orgnar at Sleeping Giant Inn.',
                            source='seen', kind='knowledge', tags=['news', 'killing'], flags={'unrecognised': True})
    camilla = store.load('Camilla Valerius', '013488')['recent']
    check('a news memory of a hooded killer is flagged, so a witness who knows the player connects it', mid and camilla[-1].get('unrecognised') is True)
    news_src = (SERVER / 'living_world' / 'news.py').read_text(encoding='utf-8')
    check("news: a masked event delivered without the name is flagged", "flags={'unrecognised': bool(e.get('masked')) and not named" in news_src)

    # the greeting's line and World's event line say the name is not theirs to use
    text = npc_block.recognition_text([('Lucan Valerius', '013487')], [{'name': 'Lucan Valerius', 'ref_id': '00013487'}], 'Brom',
                                      lambda n, r, s: False, world=WORLD, hidden=True)
    check('greeting: "does not recognise", then that the name is not theirs and no earlier meeting',
          '(Lucan Valerius does not recognise the hooded stranger: a hood hides their face.)' in text
          and "does not know the player's name and never says it" in text and 'Brom' not in text, text)
    fixed = npc_block.fix_recognition_events(['Gerdur does not recognise Brom: a hood hides their face.'], lambda n: False, 'Brom')
    check("World's own event line gets the same note", len(fixed) == 2 and 'never says it' in fixed[1], fixed)
    rules = prompt_rules.load_rules(str(HUB / 'SKSE' / 'Plugins' / 'MantellaSoftware' / 'data' / 'prompt_rules'), 'Brom')
    check("the shared rules say Mantella's player name is not known to someone who does not recognise them",
          'does not recognise Brom (a line says so) does not know that name' in rules)

    # a command makes Gerdur know who it is mid-talk: no invented shared past
    real_knows, real_store = LW._knows_player, dict(LW._last_store)
    LW._knows_player = lambda *a, **k: True
    LW._last_store.update(store=store)
    LW._unrecognised.clear()
    LW._unrecognised['Gerdur'] = '013489'
    lw_state.note_live_player('Brom')
    try:
        line = LW._recognition([{'role': 'assistant', 'content': 'Hello, stranger.'}])
    finally:
        LW._knows_player = real_knows
        LW._last_store.clear()
        LW._last_store.update(real_store)
        fresh_live()
    check('a command mid-talk: "now knows who Brom is ... no earlier acquaintance", never "knows Brom well"',
          'Gerdur now knows who Brom is, hood or not. That is no earlier acquaintance' in line and 'well' not in line, line)

    # the talk's own unrecognised verdict: World's event in the thread, unless they know the player by the end
    class UserMsg:
        def __init__(self, events):
            self._UserMessage__ingame_events = events
    thread = [UserMsg(['Lucan Valerius does not recognise Brom: a hood hides their face.\n'])]
    LW._knows_player = lambda *a, **k: False
    try:
        unrec = LW._unrecognised_for(thread)
        flagged = unrec(Char('Lucan Valerius', '013487')), unrec(Char('Hod', '01348A'))
    finally:
        LW._knows_player = real_knows
    check("the talk's verdict comes from World's event in the thread (Lucan yes, Hod not named: no)", flagged == (True, False), flagged)

    # the Now paragraph of someone who never learned the name
    for e in LUCAN_MEMORY:
        memory.add_memory(store, 'Lucan Valerius', '013487', e['text'], day=e['day'])
    out = B.write(store, 'Lucan Valerius', '013487', 'A merchant.', lambda text, prompt: 'The stranger Brom gave him 100 gold toward his losses.',
                  force=True, context={'player': 'Brom', 'hooded': True})
    check('the Now paragraph of someone who only met the hooded stranger does not name the player',
          isinstance(out, str) and 'Brom' not in out and 'stranger' in out, out)


# --- 4. the greeting offers the same actions as the first reply -------------------------------------------------------------
def installed_gates():
    gates = {}
    for path in (HUB.parent).glob('Mantella-Living-World-*/SKSE/Plugins/MantellaSoftware/data/actions/*.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for a in data if isinstance(data, list) else [data]:
            if isinstance(a, dict) and a.get('lw_gate') and a.get('name'):
                gates[a['name']] = a['lw_gate']
    return gates


def part_first_meeting(tmp):
    ch = tmp / 'channel4'
    lw_state.DATA_DIR = str(ch)
    gates = installed_gates()
    tools = [{'function': {'name': n, 'description': 'x'}} for n in sorted(gates)] + [{'function': {'name': 'Wave', 'description': 'y'}}]
    fake = types.ModuleType('src.extensions')
    fake._registry = types.SimpleNamespace(speaking_ids=['01347A'])
    real_ext, real_gates, real_store = sys.modules.get('src.extensions'), LW._gates, dict(LW._last_store)
    sys.modules['src.extensions'] = fake
    LW._gates = lambda: gates
    LW._last_store.update(store=None, people=[('Lucan Valerius', '013487')])
    C.PATH = str(tmp / 'characters.json')
    write(ch, 'conversation.json', {'string': {'player': 'Brom'}, 'int': {'day': 1}, 'stringList': {'speakers': []}})
    names = lambda ts: [t['function']['name'] for t in ts]

    def game_side():  # MLW_Channel: the minor flag first, WriteNpc's values, then each module's own
        flat = {**LUCAN_FINAL['int']}
        write(ch, 'npc/01347A.json', {'string': LUCAN_FINAL['string'], 'int': {'minor': 0}})
        time.sleep(0.3)
        write(ch, 'npc/01347A.json', {'string': LUCAN_FINAL['string'], 'int': {k: v for k, v in flat.items() if k in HUB_WRITES}})
        time.sleep(0.4)
        write(ch, 'npc/01347A.json', LUCAN_FINAL)
    try:
        worker = threading.Thread(target=game_side)
        worker.start()
        time.sleep(0.05)
        t0 = time.time()
        greeting = names(LW._filter_tools(tools, {'messages': [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'hi'}]}))
        waited = time.time() - t0
        worker.join()
        reply = names(LW._filter_tools(tools, {'messages': [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'Welcome.'},
                                                            {'role': 'user', 'content': 'Thanks, Lucan.'}]}))
        # diag 2026-11-15: the rest of a new NPC's file comes 9 to 11 s later, after the greeting; only the minor flag
        # is waited for, missing values read as their safe ones, and a first-ever meeting may cost one cache rewrite
        check("first meeting: the greeting waits only for the minor flag, not for the whole file", waited < LW.GREETING_WAIT + 0.3, waited)
        check("first meeting: the greeting offers nothing the first reply does not (missing values are the safe ones)",
              set(greeting) <= set(reply), {'greeting only': sorted(set(greeting) - set(reply))})
        check('the values the gates read include the other modules\' (maras_on, affection, nff, surv_warm)',
              {'maras_on', 'affection', 'nff', 'surv_warm', 'minor', 'close'} <= AF.gate_keys(gates), sorted(AF.gate_keys(gates)))
        # unknown age still fails closed, and quickly
        fake._registry.speaking_ids = ['0BEEF0']
        start = time.time()
        offered = names(LW._filter_tools(tools, {'messages': []}))
        adult = [n for n in offered if set(gates.get(n, '').split('+')) & AF.ADULT_GATES]
        check('an NPC with no file at the greeting: nothing adult is offered (fail closed)', not adult, adult)
        check('...and the greeting waits at most a moment for it', time.time() - start < LW.GREETING_WAIT + 0.5, time.time() - start)
    finally:
        LW._gates = real_gates
        LW._last_store.clear()
        LW._last_store.update(real_store)
        if real_ext is None:
            sys.modules.pop('src.extensions', None)
        else:
            sys.modules['src.extensions'] = real_ext


# --- 5. a forget command always writes its line in the true record -------------------------------------------------------
def part_true_record(tmp):
    ch = tmp / 'channel5'
    lw_state.DATA_DIR = str(ch)
    write(ch, 'conversation.json', {'string': {'player': 'Brom'}, 'int': {'day': 2}, 'stringList': {'speakers': []}})
    store = memory.MemoryStore(str(tmp / 'conversations'), 'Brom5')
    command.save(store, {'commands': [dict(GERDUR_COMMAND)], 'seen': [GERDUR_COMMAND['key']], 'ended': []})
    mem_id = memory.add_memory(store, 'Gerdur', '013489', GERDUR_TALK, source='seen', day=3, hour=13, kind='relationship')
    real_hide = command._hide
    hidden = [{'name': 'Gerdur', 'ref_id': '013489', 'id': mem_id, 'day': 3, 'hour': 13, 'text': GERDUR_TALK, 'added': 'r1'}]
    command._hide = lambda *a, **k: hidden  # what the talk said about the necklace, hidden and rewritten at the talk's end
    try:
        count = command.after_summary(store, [Char('Gerdur', '013489')], LW._ref, {'command_model_check': False}, None, (3, 13))
        rows = R.record_rows(store, 'Gerdur', '013489')
        check("a command given in the same talk as the thing it hides (Gerdur's necklace): the true record has her forget line",
              count == 1 and any(r['kind'] == 'forget' and r.get('command_id') == '9ac72919d0e5' for r in rows), rows)
        command.after_summary(store, [Char('Gerdur', '013489')], LW._ref, {'command_model_check': False}, None, (3, 14))
        rows = [r for r in R.record_rows(store, 'Gerdur', '013489') if r['kind'] == 'forget']
        check('a later talk hiding more for the same command writes no second line', len(rows) == 1, rows)
    finally:
        command._hide = real_hide


# --- 6, 7. the NPCs page: letter case, the summary line --------------------------------------------------------------------
def part_npc_page(tmp):
    conv = tmp / 'pageconv'
    (conv / 'Brom1' / 'lira - 00080E').mkdir(parents=True)
    (conv / 'Brom1' / 'lira - 00080E' / 'lira.json').write_text('[]', encoding='utf-8')
    (conv / 'Brom1' / 'living_world').mkdir()
    overrides = tmp / 'overrides'
    overrides.mkdir()
    (overrides / 'Lira.json').write_text(json.dumps({'name': 'Lira', 'race': 'Dark Elf', 'bio': 'A succubus.'}), encoding='utf-8')
    P.CSV, P.OVERRIDES = str(tmp / 'none.csv'), str(overrides)
    real_followers = P.ui_overrides.followers_seen
    P.ui_overrides.followers_seen = lambda: set()
    try:
        # the list the page had when Lira was picked: from before her first talk, her override's spelling, no reference id
        P._listed[(str(conv), 'Brom1')] = [{'name': 'Lira', 'ref_id': '', 'has': False, 'custom': True, 'follower': False, 'label': 'Lira'}]
        found = P.find_npc(str(conv), 'Brom1', 'Lira')
        check('"Lira" (override) is the game\'s "lira" (ref 00080E): talks, memories and commands are found',
              bool(found) and found.get('ref_id') == '00080E', found)
        check('the picker keeps the pick when only the letter case differs', P.same_label(['lira', 'Alvor'], 'Lira') == 'lira'
              and P.same_label(['Whiterun Guard', 'whiterun guard'], 'WHITERUN GUARD') is None)
        P._listed[(str(conv), 'X')] = [{'name': 'Whiterun Guard', 'ref_id': '', 'label': 'Whiterun Guard'},
                                       {'name': 'Whiterun Guard', 'ref_id': '0A1', 'label': 'Whiterun Guard 0A1'},
                                       {'name': 'Whiterun Guard', 'ref_id': '0B2', 'label': 'Whiterun Guard 0B2'}]
        real_list = P.npc_list
        P.npc_list = lambda c, w, *a, **k: P._listed[(c, w)]
        try:
            g = P.find_npc(str(conv), 'X', 'Whiterun Guard')
        finally:
            P.npc_list = real_list
        check('two different NPCs of one name are never merged', g is not None and g['ref_id'] == '', g)
    finally:
        P.ui_overrides.followers_seen = real_followers
    ch = tmp / 'channel7'
    lw_state.DATA_DIR = str(ch)
    write(ch, 'ties.json', TIES)
    write(ch, 'npc/013475.json', ALVOR_NPC)
    write(ch, 'npc/25C80A.json', LIRA_NPC)

    class Fake:
        store, player = None, 'Brom'
        def __init__(self, name, race):
            self.name, self.speaker = name, C.game_npc(name, race)
        def entry(self):
            return {}
    alvor = P.summary_parts(Fake('Alvor', 'Nord'))
    lira = P.summary_parts(Fake('Lira', 'Dark Elf'))
    check("summary line: Alvor's spouse from the game (ties.json): married to Sigrid", 'married to Sigrid' in alvor, alvor)
    check("summary line: Lira (in Nether's Follower Framework's party, nff 1) travels with the player", 'travels with Brom' in lira, lira)
    src = (SERVER / 'living_world' / 'npc_page_ui.py').read_text(encoding='utf-8')
    check('every section action (Release, Save, ...) refreshes the summary line too',
          "keys = [k for s in sections for k in SECTION[s]] + ['summary']" in src and "view = {'summary': summary_html(ctx)}" in src)


# --- 8. short bios ------------------------------------------------------------------------------------------------------------
def load_bios():
    """The real before/after side by side of live test 6 (bios-before-after.md in the evidence folder), when it is there."""
    path = Path(os.environ.get('MLW_EVIDENCE', ''), r'lw-live-test-6-2026-11-15\bios-before-after.md')
    if not path.is_file():
        return {}
    out = {}
    for part in path.read_text(encoding='utf-8').split('\n## ')[1:]:
        name = part.split(' (', 1)[0].strip()
        before = part.split('**Before**', 1)[1].split('**After**', 1)[0].strip() if '**Before**' in part else ''
        after = part.split('**After**', 1)[1].split('\n---', 1)[0].strip() if '**After**' in part else ''
        out[name] = (before, after)
    return out


def part_bios(tmp):
    check('the short-bio format is version 3 or later (4 since live test 8)', BO.FORMAT_VERSION >= 3)
    bios = load_bios()
    if not bios:
        print('SKIP the live test 6 bio file is not on this PC')
    else:
        before, after = bios['Aela the Huntress']
        explained = BO.explained_terms(before, after)
        check('Aela: the reversed "snowberries" (only in a spoken line) is caught', 'snowberries' in explained, explained)
        check('Aela: terms kept with their spoken lines among the sample lines pass (milk drinker, icebrain, whelps, new blood)',
              not ({'milk drinker', 'icebrain', 'whelps', 'new blood'} & set(explained)), explained)
        bad, _ = BO.problems(before, after)
        check('Aela: the check rejects that short bio', any('sheet only uses inside a spoken line' in b for b in bad), bad)
        note = BO.author_note(before)
        noted = BO.with_note(after, note)
        sample = next(l for l in noted.splitlines() if l.startswith('Sample lines'))
        check('the author note "[use as inspiration but avoid parroting]" stays with the sample lines',
              note == '[use as inspiration but avoid parroting]' and note in sample, sample[:120])
        beatrice = BO.rule_items(bios['Beatrice'][0])
        check('Beatrice: "When she first meets the player she owes them nothing; ..." is a rule (carried word for word)',
              any('she owes them nothing' in r for r in beatrice), beatrice)
        serana = BO.rule_items(bios['Serana'][0])
        check('Serana: "treats the player as a travelling companion rather than someone to worship or obey" is a rule',
              any('treats the player as a travelling companion' in r for r in serana), serana[:3])
        aela_rules = BO.rule_items(before)
        check('Aela: no line of her example dialogue is taken for a rule', not any(r.startswith(('Skjor:', 'Aela the Huntress:', 'Farkas:', 'Njada:'))
                                                                                 for r in aela_rules), aela_rules)
        faralda = bios['Faralda'][0]
        dropped = '\n'.join(l for l in faralda.splitlines() if '{player_name}' not in l)
        check('Faralda: {player_name} only in a dropped sentence that is not a rule is no reason to reject',
              '{player_name}' not in BO.missing(faralda, dropped), BO.missing(faralda, dropped))
        reworded = faralda.replace('{player_name}', 'the player')
        check('Faralda: kept where its sentence was kept', '{player_name}' in BO.missing(faralda, reworded))
        senna = bios['Senna'][0]
        check('Senna: the bare title "Goddess" beside a kept name follows the title rule',
              'Goddess' not in BO.missing(senna, senna.replace('Goddess', 'goddess-less').replace('goddess-less ', '')),
              BO.missing(senna, senna.replace('Goddess ', '')))
        annabelle = bios['Annabelle'][0]
        lines = BO.term_lines(annabelle)
        check('Annabelle: the sentence giving her nickname (Sanguine girl) is protected (copied word for word)',
              any('some call her "Sanguine' in l for l in lines), lines)
        check('Annabelle: her short bio of format 2 rewrote it, so the check now asks again',
              bool(BO.terms_missing(annabelle, bios['Annabelle'][1])), bios['Annabelle'][1][-300:])
    prompt = BO.PROMPT
    check('the prompt keeps qualifiers, conditions and stated reasons', '"merely"' in prompt and '"if they own one"' in prompt
          and 'stated reason' in prompt)
    check('the prompt: nickname lines word for word, never restate who a term refers to', 'never restate who or what a term refers to' in prompt)
    # the store keeps no older-format entries for the same NPC
    path = str(tmp / 'bios.json')
    old = {'version': 1, 'use_original': ['lydia'], 'bios': {'oldhash': {'name': 'Alvor', 'status': 'done', 'text': 'x', 'format': 2, 'at': 1},
                                                             'other': {'name': 'Hod', 'status': 'done', 'text': 'y', 'format': 2, 'at': 1}}}
    Path(path).write_text(json.dumps(old), encoding='utf-8')
    BO.remember('Alvor', 'An original bio ' * 50, {'status': 'done', 'text': 'Personality: short.'}, path=path)
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    # live test 7: every older-format entry is dropped on write (it is never used), the opt-out list stays
    check("storing Alvor's new short bio drops the older-format entries, keeps the opt-out list",
          'oldhash' not in data['bios'] and 'other' not in data['bios'] and data['use_original'] == ['lydia']
          and any(v['name'] == 'Alvor' and v['format'] == BO.FORMAT_VERSION for v in data['bios'].values()), data)


# --- 9. event spam ---------------------------------------------------------------------------------------------------------
def part_events():
    out = npc_block.collapse_outfit_events(OUTFIT_BATCH)
    changed = [e for e in out if 'changed outfit' in e]
    check("a follower's outfit swap (the live batch) becomes one line, where it started", len(changed) == 1
          and not any(' equipped ' in e or ' unequipped ' in e or 'dropped/gave' in e for e in out), out)
    check('the line says what she wears now', 'Cosplay Gala Gown' in changed[0] and 'BloodSpiller' not in changed[0], changed)
    check('the other events stay, in order', out[0] == "lira has joined the player's party." and out[-2:] == OUTFIT_BATCH[-2:], out)
    out2 = npc_block.collapse_outfit_events(SECOND_BATCH)
    # live test 7: a newly drawn weapon keeps its own line beside the outfit change
    check('picking up 200 gold stays beside the collapsed swap', out2[0] == 'lira picked up/took 200 Gold' and len(out2) == 3
          and out2[2] == 'lira equipped Glass Dagger', out2)
    single = ['lira equipped Glass Dagger', 'Lucan Valerius waves']
    check('a single meaningful equip stays as it is', npc_block.collapse_outfit_events(single) == single)
    src = (SERVER / 'living_world' / '__init__.py').read_text(encoding='utf-8')
    check('the event hook collapses them', 'npc_block.collapse_outfit_events(events)' in src)


# --- 10. the Console helper call is not queued behind the reply ------------------------------------------------------------
def part_console():
    fake = types.ModuleType('src.llm.client_base')
    fake._hook_thread = threading.local()
    lock = threading.Lock()
    had = sys.modules.get('src.llm.client_base')
    sys.modules['src.llm.client_base'] = fake

    def ask(prompt, text):  # Mantella's model call: a hook thread skips the generation lock, others wait for it
        if getattr(fake._hook_thread, 'active', False):
            return '{"commands": ["player.additem f 10"], "summary": "Gives 10 gold."}'
        with lock:
            return '{"commands": [], "summary": "late"}'
    result = {}

    def hook():  # Direct AI Connect's server-actions thread, while the reply in flight holds the lock
        fake._hook_thread.active = True
        result['answer'] = console._ask_bounded(ask, 'p', 't')
    old = console.HELPER_SECONDS
    console.HELPER_SECONDS = 1
    lock.acquire()
    try:
        worker = threading.Thread(target=hook)
        worker.start()
        worker.join(5)
    finally:
        lock.release()
        console.HELPER_SECONDS = old
        if had is None:
            sys.modules.pop('src.llm.client_base', None)
        else:
            sys.modules['src.llm.client_base'] = had
    check('the helper call made from the hook thread answers while the reply holds its lock (no 25 s queue, no timeout)',
          isinstance(result.get('answer'), str) and 'additem' in result['answer'], result)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    for part in (part_player_name, part_recognition, part_first_meeting, part_true_record, part_npc_page, part_bios):
        try:
            part(tmp)
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f'{part.__name__} ran without an error', False, e)
    part_events()
    part_console()

print(f"\n{len(FAILS)} failure(s)" if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
