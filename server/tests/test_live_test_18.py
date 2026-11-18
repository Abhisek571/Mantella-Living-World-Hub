"""Offline tests for live session 18 (2026-11-18), from the lines that session logged: adult words stored in a child's
memory, a name the player told replaced by "the hooded stranger", the after-scene memory without the intimacy flag, the
scene-end line sent behind out-of-date in-scene lines, the menu memory lost to a cut-off summary reply (shown again in
the next talk), the follower orders missing in the talk of the join, Survival's facts of right now never reaching the
model, food offered aloud that World's trade gate then refused, and the new lines for a child near the player.
Run with a Python 3.11: test_live_test_18.py <repo server dir>"""
import json, logging, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SERVER))
import living_world as LW
from living_world import embed, lw_state, memory, menu_dialogue as MD, trade
memory.SUMMARY_RETRY_SECONDS = 0
embed.use(None)

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)[:700]) if not cond else ''))
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
    def get_talk_only(self, include_system_generated_messages=False):
        return list(self)
    def transform_to_dict_representation(self, messages):
        return '\n'.join(str(m) for m in messages)

class Params:
    def __init__(self, lines, chars):
        self.messages, self.characters = Thread(lines), chars

class People:
    def get_player_name(self):
        return 'Brom'

class UserMessage:
    def __init__(self, text):
        self.text = text
    def get_formatted_content(self):
        return self.text
    def __str__(self):
        return self.text

class GroupSummaries:
    """Mantella's summaries with every NPC here on one shared thread (a group talk)."""
    def __init__(self, threads, reply):
        self.threads, self.reply, self.calls = threads, reply, []
    def get_threads_for_summarization(self, messages, npcs):
        return self.threads
    def group_shared_threads(self, threads):
        return [list(threads)]
    def summarize_conversation(self, text, prompt):
        self.calls.append((text, prompt))
        return self.reply


def write(base: Path, name: str, data):
    path = base / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


# --- K: a child's memory never keeps adult words -------------------------------------------------------------------------
VERBATIM = ('Spoke briefly with Brom, who said: "Brom: Haelga, come here you, let\'s go somewhere and make love again, right '
            'now." Dorthe answered: "Dorthe: Make love?"')  # Dorthe's memory as live test 18 stored it

def part_minor(tmp):
    check('the stored line counts as adult wording', memory.minor_unsafe(VERBATIM))
    check('...and nothing of it is kept for a child', memory.for_minor(VERBATIM) == memory.MINOR_NEUTRAL, memory.for_minor(VERBATIM))
    mixed = 'Talked with Brom about the mill. He asked Haelga to share her bed. Brom promised to bring sweets tomorrow.'
    check('only the adult sentence goes from a mixed memory', memory.for_minor(mixed) ==
          'Talked with Brom about the mill. Brom promised to bring sweets tomorrow.', memory.for_minor(mixed))
    check('harmless words stay', not memory.minor_unsafe('The bedrock of Bedlam; a lovely day at the forge.'))

    store = memory.MemoryStore(str(tmp / 'conversations'), 'Brom1')
    haelga, dorthe = Char('Haelga', '019DDA'), Char('Dorthe', '013484')
    reply = json.dumps({'memory': "Brom asked Haelga to go somewhere and make love again right now; Haelga refused with Dorthe "
                                  "standing there. Dorthe asked what making love was.",
                        'feelings': {'Haelga': 'fond but careful', 'Dorthe': 'curious about the grown-ups kissing'},
                        'promises': [{'text': 'Brom will meet Haelga tonight for more lovemaking', 'by': 'Brom', 'due_in_days': 0}],
                        'importance': 0.6})
    lines = [f'line {i}' for i in range(8)]
    summaries = GroupSummaries({'Haelga': Params(lines, [haelga, dorthe]), 'Dorthe': Params(lines, [haelga, dorthe])}, reply)
    ctx = {'messages': None, 'npcs_to_summarize': [haelga, dorthe], 'npcs_in_conversation': People(), 'is_reload': False,
           'end_timestamp': 0.6, 'is_radiant': False, 'summaries': summaries,
           'is_minor': lambda c: c.name == 'Dorthe', 'unrecognised': lambda c: False}
    memory.summarize(ctx, store)
    adult, child = store.load('Haelga', '019DDA'), store.load('Dorthe', '013484')
    h, d = adult['recent'][-1], child['recent'][-1]
    check("the adult keeps the talk as it was (the shared memory)", 'shared' in h and 'make love' in h.get('text', ''), h)
    check("the child gets her own memory, not the shared one", 'shared' not in d, d)
    check("...with no adult word in it", not memory.minor_unsafe(d.get('text')) and d.get('text') == memory.MINOR_NEUTRAL, d.get('text'))
    check("...no feeling with adult words either", not memory.minor_unsafe(child.get('feeling', '')), child.get('feeling'))
    check("...and no promise from that talk", not any(memory.minor_unsafe(f.get('text', '')) for f in child.get('facts', [])), child.get('facts'))
    check("the child still counts as having been there (witnesses)", d.get('witnesses') == ['Haelga', 'Dorthe'], d)
    check('logged', any("adult wording left out of Dorthe's memory" in l for l in LOG.lines))


def part_child_lines(tmp):
    speakers = [{'name': 'Haelga', 'minor': 0}, {'name': 'Dorthe', 'minor': 1}]
    line = LW.child_line(speakers)
    check('child in the talk: the child does not repeat or answer adult words', 'does not repeat it, ask about it or answer it' in line, line)
    ch = tmp / 'near'
    lw_state.DATA_DIR = str(ch)
    write(ch, 'children_near.json', {'string': {'names': 'Dorthe, Frodnar'}})
    lw_state._cache.clear() if hasattr(lw_state, '_cache') else None
    names = lw_state.load_children_near()
    check('the game side\'s list of children near the player is read', names == ['Dorthe', 'Frodnar'], names)
    near = LW.children_near_line(names, [{'name': 'Haelga'}])
    check('a child near but not in the talk: one line, no block', near.startswith('(A child, Dorthe, Frodnar, is near the player')
          and 'Almost under no circumstances' in near and 'another room or illusion magic' in near, near)
    check('a child who is in the talk is not named again', LW.children_near_line(['Dorthe'], [{'name': 'Dorthe'}]) == '')
    check('nobody near: nothing', LW.children_near_line([], [{'name': 'Haelga'}]) == '')


# --- B: a name the player told stays in the memory -----------------------------------------------------------------------
def part_told_name(tmp):
    check('"My name is Brom" tells the name (any case)', memory.told_name([UserMessage('My name is Brom.')], 'Brom'))
    check('"I\'m Brom Brightblade" tells it (first name of the player\'s name)', memory.told_name(['(an event) I\'m Brom, nice to meet you.'], 'Brom Brightblade'))
    check('"Brom\'s horse" does not', not memory.told_name(["It's Brom's horse."], 'Brom'))
    check('a line without the name does not', not memory.told_name(['Hello there.'], 'Brom'))
    store = memory.MemoryStore(str(tmp / 'told'), 'Brom1')
    camilla = Char('Camilla Valerius', '013488')
    reply = json.dumps({'memory': 'A man called Brom asked me to spend the night with him. I refused.', 'importance': 0.5})
    talk = [UserMessage('Hello. My name is Brom.')] + [f'line {i}' for i in range(7)]
    summaries = GroupSummaries({'Camilla Valerius': Params(talk, [camilla])}, reply)
    memory.summarize({'messages': None, 'npcs_to_summarize': [camilla], 'npcs_in_conversation': People(), 'is_reload': False,
                      'end_timestamp': 0.6, 'is_radiant': False, 'summaries': summaries, 'unrecognised': lambda c: True}, store)
    text = store.load('Camilla Valerius', '013488')['recent'][-1]['text']
    check('hooded, but the player said his name: the memory keeps the name, not "the hooded stranger"',
          'Brom' in text and 'hooded stranger' not in text, text)
    check('...and the summary was not told he never learned the name', 'never by name' not in summaries.calls[-1][1])


# --- D: the after-scene memory is an intimate one ------------------------------------------------------------------------
END = ('Haelga and the player finished having sex in Riverwood after about 15 minutes. They did a handjob and vaginal sex. '
       'Climaxes: The Player 4 times and Haelga 4 times.')

def part_intimacy_flag():
    check('a scene that ended in the talk flags it', memory.talk_flags([END], 'Haelga', 'Brom').get('intimacy') is True)
    check('also with two partners', memory.talk_flags(['Mjoll, Haelga and the player finished having sex.'], 'Mjoll', 'Brom').get('intimacy'))
    check('a kept scene from before the talk is its own memory: not flagged here',
          not memory.talk_flags(['Earlier (about 2 hours ago), with no conversation going on: ' + END], 'Haelga', 'Brom'))
    check('another NPC\'s scene is not hers', not memory.talk_flags([END], 'Camilla Valerius', 'Brom'))
    entry = {'text': 'x', 'importance': 0.6}
    memory.apply_talk_flags({'recent': []}, entry, {'intimacy': True}, 1)
    check('the memory gets the intimacy flag and its importance floor', 'intimacy' in entry.get('flags', [])
          and entry['importance'] >= 0.9, entry)


# --- C: queued in-scene lines go once the scene's end line is there -----------------------------------------------------
BATCH = ['The pace slows down; it is now Very Slow.', 'The Player just climaxed.', 'The pace picks up; it is now slow and gentle.',
         'Haelga and the player have moved on to vaginal sex.',
         'Haelga is close to climax; Haelga reacts out loud in a sentence or two, breathless, only a few words, a little shy.',
         'The pace slows down; it is now Very Slow.', 'The pace picks up; it is now slow and gentle.', END]  # 03:25:26

def part_stale_scene():
    out = MD.drop_stale_scene_lines(BATCH + ['The location is now Riverwood.'])
    check('the live test\'s batch: only the end line is left of the scene (other events stay)',
          out == [END, 'The location is now Riverwood.'], out)
    check('without an end line nothing goes', MD.drop_stale_scene_lines(BATCH[:-1]) == BATCH[:-1])
    kept = ['Earlier (less than an hour ago), with no conversation going on: Haelga and the player finished having sex. {t=0.5}',
            'The pace picks up; it is now slow and gentle.']
    check('a kept scene from before the talk is no end of a running scene', MD.drop_stale_scene_lines(kept) == kept)
    check('lines after the end line stay (a new scene)', MD.drop_stale_scene_lines([END, BATCH[0]]) == [END, BATCH[0]])
    src = (SERVER / 'living_world' / '__init__.py').read_text(encoding='utf-8')
    body = src[src.index('def _dialogue_events('):src.index('def _menu_memories(')]
    check('the events hook drops them', 'menu_dialogue.drop_stale_scene_lines(events)' in body)


# --- I: the kept scene's time tag never reaches the model (already so: only Mantella's raw receive line has it) ----------
def part_time_tag():
    raw = ('Earlier (less than an hour ago), with no conversation going on: Haelga and the player finished having sex in '
           'Riverwood after about 2 minutes. They did a footjob. {t=0.597051}')  # 04:04:37 "Received in-game events"
    events, found = MD.scene_records([raw])
    check('the tag is taken out before the model (live test 18 log line 3128 shows the event without it)',
          '{t=' not in events[0] and found == [(0.597051, 'Haelga and the player finished having sex in Riverwood after about 2 minutes. They did a footjob.')],
          (events, found))


# --- G: a cut-off summary reply still makes the menu memory --------------------------------------------------------------
CUT = ('{"memory": "Brom came back to my forge and asked me again what I\'d said about the war.", "importance": 0.2, '
       '"story": null, "menu": {"Alvor": {"memory": "First Brom greeted me in Riverwood and I greeted him back as a friend. '
       'Then he asked what I thought of the war.", "importance": 0.3, "emotion": "calm')  # 03:48:43, cut by the token limit

def part_cut_menu():
    menu = MD.parse_menu(CUT, ['Alvor'])
    check('the whole menu memory is taken from the cut-off reply', list(menu) == ['Alvor']
          and menu['Alvor'][0].startswith('First Brom greeted me in Riverwood'), menu)
    check('a memory text cut off itself is not taken', MD.parse_menu('{"menu": {"Alvor": {"memory": "First Brom gre', ['Alvor']) == {})
    check('a whole reply parses as before', MD.parse_menu(json.dumps({'menu': {'Alvor': {'memory': 'x y z', 'importance': 0.4}}}),
                                                         ['Alvor'])['Alvor'][1].get('importance') == 0.4)


# --- F: follower orders in the talk of the join ---------------------------------------------------------------------------
def part_follower_lock(tmp):
    ch = tmp / 'follow'
    lw_state.DATA_DIR = str(ch)
    write(ch, 'conversation.json', {'string': {'player': 'Brom'}, 'int': {'day': 1}, 'stringList': {'speakers': ['01335E']}})
    npc = {'string': {'name': 'Faendal', 'ref_id': '0001335F'}, 'int': {'minor': 0, 'follower': 0, 'nff': 0}}
    write(ch / 'npc', '01335E.json', npc)
    saved = dict(LW._last_store)
    LW._last_store['store'] = None
    try:
        before = LW._action_key()
        npc['int'].update(follower=1, nff=1)  # the join rewrote her file (MLWF_Main.RefreshLivingWorldNpc)
        write(ch / 'npc', '01335E.json', npc)
        import time; time.sleep(lw_state.READ_MEMO_SECONDS + 0.1)
        after = LW._action_key()
        check('a join mid-talk changes the action lock, so the follower orders are offered in the same talk', before != after,
              (before, after))
        npc['string']['race'] = 'Wood Elf'  # anything else arriving late keeps the lock
        write(ch / 'npc', '01335E.json', npc)
        time.sleep(lw_state.READ_MEMO_SECONDS + 0.1)
        check('...a late value that is no party change keeps it', LW._action_key() == after)
    finally:
        LW._last_store.update(saved)


# --- Survival: facts of right now in every request, and the debug log ----------------------------------------------------
def part_now_facts(tmp):
    gerdur = {'name': 'Gerdur', 'fact_surv_hunger': '-1|0|3|Brom is starving.', 'fact_surv_cold': '-1|0|3|Brom is freezing.',
              'fact_surv_wounded': '-1|0|3|You are badly wounded.', 'fact_surv_meal': '3|5|2|You and Brom shared a meal.'}
    line = LW.now_facts_line([gerdur], 0, {'Survival'})
    check("the npc file's needs reach the newest message (the live test's facts, written while the talk started)",
          line == '(Right now, as Gerdur can tell: Brom is starving. Brom is freezing. Gerdur is badly wounded.)', line)
    check('not without Survival installed', LW.now_facts_line([gerdur], 0, {'World'}) == '')
    ch = tmp / 'debug'
    lw_state.DATA_DIR = str(ch)
    write(ch, 'conversation.json', {'int': {'debug_log': 0}})
    check('debug log off by default', not lw_state.debug_log())
    write(ch, 'conversation.json', {'int': {'debug_log': 1}})
    import time; time.sleep(lw_state.READ_MEMO_SECONDS + 0.1)
    check('the MCM switch turns it on', lw_state.debug_log())
    LOG.lines.clear()
    LW._logged_now_facts(line)
    check('...and the right-now facts of a request are logged', any('right-now facts in this request' in l for l in LOG.lines))
    store = memory.MemoryStore(str(tmp / 'facts'), 'Brom1')
    seen = []
    memory.memory_text('', {'characters': [Char('Gerdur', '013489')], 'player': 'Brom', 'recall': False, 'today': 0,
                            'facts_for': lambda c: lw_state.game_facts(gerdur, 0, {'Survival'}),
                            'log_facts': lambda c, text: seen.append(text)}, store)
    check("the facts that went into the prompt are handed to the debug log", seen and 'Brom is starving.' in seen[0], seen)
    src = (SERVER.parent / 'Source' / 'Scripts' / 'MLW_Channel.psc').read_text(encoding='utf-8')
    check('the game writes the switch at each talk start', '"debug_log", debugLog.GetValueInt()' in src)


# --- J: the trade gate is told before the NPC offers anything -----------------------------------------------------------
def part_trade_gate():
    ask = [{'role': 'user', 'content': '(Brom is freezing.) Could you spare some food or something warm? I am starving.'}]
    gerdur = {'name': 'Gerdur', 'close': 0, 'follower': 0}
    line = trade.gate_text([gerdur], ask, 'Brom')
    check('a stranger asked for food: told she gives nothing away', line.startswith('(Gerdur does not know Brom well enough to give anything away')
          and 'does not offer it' in line, line)
    faendal = {'name': 'Faendal', 'close': 1, 'follower': 1}
    check('a follower with Survival on: food goes through ShareFood', trade.gate_text([faendal], ask, 'Brom', survival=True)
          == '(Food Faendal hands Brom to eat now goes through the ShareFood action, not Trade.)')
    check('a close friend gives freely: no line', trade.gate_text([{'name': 'Alvor', 'close': 1}], ask, 'Brom') == '')
    talk = [{'role': 'user', 'content': '(It is cold.) How is the mill doing?'}]
    check('a line asking for nothing: no line (event words do not count)', trade.gate_text([gerdur], talk, 'Brom') == '')


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    for part in (lambda: part_minor(tmp), lambda: part_child_lines(tmp), lambda: part_told_name(tmp), part_intimacy_flag,
                 part_stale_scene, part_time_tag, part_cut_menu, lambda: part_follower_lock(tmp), lambda: part_now_facts(tmp),
                 part_trade_gate):
        try:
            part()
        except Exception as e:
            import traceback; traceback.print_exc()
            check(f'part ran ({getattr(part, "__name__", "part")})', False, e)

print('\n' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: ' + ', '.join(FAILS)))
sys.exit(1 if FAILS else 0)
