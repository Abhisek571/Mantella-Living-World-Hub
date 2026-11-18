"""Offline tests for the defects found by live test 4 (2026-11-15), built from the files that test left behind
(releases.json, commands.json, Sigrid's and Camilla's npc files and memories, crimes.json, ties.json, the world log's
killing event), copied in here as data: a release that acts at once (also on the talk going on), the forget rewrite,
news passing along family ties, recognition, server lines that cannot be read as a speaker label, the greeting's
cached prefix, crimes inside an open fight and the status page's token table.
Run with a Python 3.11: test_live_test_4.py <repo server dir>"""
import json, logging, os, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world as LW
from living_world import (bio_evolve as B, command, embed, lw_state, memory, release as R)
memory.SUMMARY_RETRY_SECONDS = 0
embed.use(None)

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
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


# --- stand-ins for Mantella's classes (as in test_memory.py) ----------------------------------------------------------
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
    def __init__(self, player='Brom'):
        self.player = player
    def get_player_name(self):
        return self.player

class FakeSummaries:
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


# --- the live test's files ----------------------------------------------------------------------------------------------
SIGRID_NPC = {"int": {"affection": 1, "follower": 0, "illusion": 15, "intimate": 1, "minor": 0, "maras": 0, "maras_on": 1, "spouse": 0},
              "string": {"hold": "Whiterun", "home": "Alvor and Sigrid's House", "home_town": "Riverwood", "location": "Riverwood",
                         "maras_status": "Unknown", "name": "Sigrid", "race": "Nord", "ref_id": "00013483", "sex": "female",
                         "town": "Riverwood"}}
CAMILLA_NPC = {"int": {"follower": 0, "illusion": 15, "minor": 0, "maras_on": 1, "spouse": 0},
               "string": {"hold": "Whiterun", "home": "Riverwood Trader", "home_town": "Riverwood", "name": "Camilla Valerius",
                          "race": "Imperial", "ref_id": "00013488", "sex": "female", "town": "Riverwood"}}
SPELL = 'You are under my spell. You adore me and will do as I say.'
SIGRID_TALK = ("A stranger came to Riverwood and I greeted him, saying I was spoken for and that my husband Alvor runs the "
               "smithy. Then I felt a sudden pull toward him I couldn't explain, and when he asked, I told him plainly that I "
               "adore him and would do near anything he asked. I worried what Alvor would say, and when he asked what we'd been "
               "talking about I repeated it, calling myself foolish with a husband and daughter waiting at home.")
CAMILLA_TALK = ("A hooded stranger came to the Riverwood Trader and asked if I knew who they were; I didn't, and I said they "
                "made my heart race. They asked me to come to bed with them and I said yes, I'd follow them anywhere, but they "
                "decided to wait. When they asked if I still adore them, I admitted I got carried away.")


def write_channel(name, data):
    path = os.path.join(lw_state.DATA_DIR, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def spell_record(cid, key, name, ref, given):
    return {'id': cid, 'key': key, 'text': SPELL, 'given': given, 'npcs': [{'name': name, 'ref_id': ref}], 'forget': '',
            'aware': False, 'status': 'active', 'announced': True, 'hidden': [], 'read_by': 'model', 'hours': 0.0,
            'until': -1.0, 'bio_before': []}


def releases(rows):
    keys = ('key', 'ref', 'name', 'base', 'choice', 'time', 'player')
    return {'stringList': {k: [r[i] for r in rows] for i, k in enumerate(keys)}}


def summarize_talk(tmp, world, char, text):
    """The end of the talk, through the Hub's own summarize hook, with the model's memory answer from the live test."""
    reply = json.dumps({'memory': text, 'importance': 0.5, 'type': 'relationship'})
    summaries = FakeSummaries({char.name: Params([f'line {i}' for i in range(8)], [char])}, reply)
    summaries._Summaries__game = type('Game', (), {'conversation_folder_path': str(tmp / 'conversations')})()
    summaries._Summaries__language_name = 'English'
    ctx = {'messages': None, 'npcs_to_summarize': [char], 'npcs_in_conversation': People(), 'world_id': world,
           'is_reload': False, 'pending_shares': None, 'end_timestamp': 0.70, 'is_radiant': False, 'summaries': summaries}
    LW._summarize(ctx)


def talk_with(store, people, speakers_base):
    LW._last_store.update(store=store, people=people)
    write_channel('conversation.json', {'int': {'day': 0, 'talk_open': 1}, 'string': {'player': 'Brom'},
                                        'stringList': {'speakers': speakers_base}})
    B.talk_going_on()


# --- 2. a release acts at once, also on the talk going on -----------------------------------------------------------
def part_release(tmp):
    world = 'REL4'
    store = memory.MemoryStore(str(tmp / 'conversations'), world)
    write_channel('npc/013476.json', SIGRID_NPC)
    write_channel('npc/01347B.json', CAMILLA_NPC)
    command.save(store, {'commands': [spell_record('f731cd49555e', '0.677097-365215', 'Sigrid', '013483', 0.677097),
                                      spell_record('ce751b40b8da', '0.626906-177738', 'Camilla Valerius', '013488', 0.626906)],
                         'seen': ['0.677097-365215', '0.626906-177738'], 'ended': []})
    write_channel('commands.json', {'stringList': {'key': [], 'text': [], 'refs': [], 'names': [], 'time': [], 'player': []}})

    # Sigrid, mid-talk: Release(Sigrid, 1), forgets the whole period
    talk_with(store, [('Sigrid', '013483')], ['013476'])
    before = LW._commands(newest=True)
    check('release (setup): the command is in force before the release', 'in force for Sigrid' in before, before)
    write_channel('releases.json', releases([('0.686226-526144', '00013483', 'Sigrid', '013476', 'Forget', '0.686226', 'Brom')]))
    line = LW._commands(newest=True)
    check('release forget: the very next request says the spell lifted and she remembers nothing since that day',
          'The spell Brom had on Sigrid has just lifted.' in line and 'Sigrid has no memory of anything from day 1 until now.' in line, line)
    check('release forget, mid-talk: the lines already said in this talk are named as forgotten, not to be referred to',
          'said earlier in this talk' in line and 'must not refer to them' in line, line)
    check('release: the command reminder is gone from that same request', 'Absolute commands' not in line and 'in force' not in line, line)
    check('release: the ABSOLUTE COMMANDS part is gone from the system prompt', LW._commands(newest=False) == '')
    check('release: the line is given once', 'has just lifted' not in LW._commands(newest=True))
    summarize_talk(tmp, world, Char('Sigrid', '013483'), SIGRID_TALK)
    mem = store.load('Sigrid', '013483')['recent']
    shown = [e['text'] for e in mem if not e.get('hidden') and e.get('text')]
    check('release forget: the summary written at the end of that talk is not stored as a normal memory',
          not any('adore him' in t for t in shown), shown)
    gaps = [g['text'] for g in B.load(store, 'Sigrid', '013483')['gaps']]
    check('release forget: the gap line is written, with the right day and "her"', gaps == ['Sigrid has no memory of day 1, and it frightens her.'], gaps)
    rows = R.record_rows(store, 'Sigrid', '013483')
    check('release forget: the true record has the forget of the period', any(r['kind'] == 'forget' and r.get('command_id') == 'f731cd49555e'
                                                                             and r['days'] == [1, 1] for r in rows), rows)
    check('release forget: nothing is left waiting after the talk', R.released_in_talk(Char('Sigrid', '013483')) == '')

    # Camilla, mid-talk: Release(Camilla, 0), remembers and knows it was a spell
    talk_with(store, [('Camilla Valerius', '013488')], ['01347B'])
    write_channel('releases.json', releases([('0.650912-121381', '00013488', 'Camilla Valerius', '01347B', 'SPELL', '0.650912', 'Brom')]))
    line = LW._commands(newest=True)
    check('release spell: the next request says the spell lifted, she remembers all of it and knows it was a spell',
          'The spell Brom had on Camilla Valerius has just lifted.' in line and 'remembers all of it and knows it was a spell' in line, line)
    summarize_talk(tmp, world, Char('Camilla Valerius', '013488'), CAMILLA_TALK)
    newest = [e for e in store.load('Camilla Valerius', '013488')['recent'] if e.get('text') == CAMILLA_TALK]
    check("release spell: the memory written at the end of the running talk carries the spell mark",
          newest and newest[0].get('spell') == "while under Brom's spell" and newest[0].get('command') == 'ce751b40b8da', newest)
    db = store.archive_for('Camilla Valerius', '013488')
    marked = [r for r in (db.rows() if db.exists() else []) if r.get('text') == CAMILLA_TALK]
    check('release spell: ...also in the archive', all(r.get('spell') == "while under Brom's spell" for r in marked), marked)
    text = memory.entry_text(newest[0], store) if newest else ''
    rendered = memory.render(store.load('Camilla Valerius', '013488'), 3000)
    check('release spell: the mark is in what the model reads', "while under Brom's spell" in rendered, rendered[-400:])
    B.talk_over()

    # a release outside any talk: the line waits for their next talk; no "earlier in this talk"
    command.save(store, {'commands': [spell_record('aa11', 'k-x', 'Sigrid', '013483', 2.5)], 'seen': ['k-x'], 'ended': []})
    R.release_command(store, 'aa11', 'forget', player='Brom', today=3, speakers=[lw_state._flatten(SIGRID_NPC)], in_talk=[])
    later = R.newest_text([lw_state._flatten(SIGRID_NPC)])
    check('release outside a talk: told at the next talk, without the in-talk sentence',
          'has no memory of anything from day 3 until now.' in later and 'this talk' not in later, later)


# --- 11. the forget rewrite never names the forgotten thing ----------------------------------------------------------
def part_rewrite():
    asked = []
    command._rewrite(lambda prompt, text: asked.append(prompt) or 'NONE', 'Gerdur', 'A stranger asked whether I wear the necklace.',
                     'being given the necklace by the player')
    check('forget rewrite: told not to name the thing even as something asked about', asked and 'not even as something someone asked about' in asked[0], asked)


# --- 3. news passes from a witness to his own family, also in the next talk a minute later -------------------------
ART = Path(os.environ.get('MLW_EVIDENCE', ''), r'lw-live-test-4-2026-11-15\test-artifacts')
HILDE_NPC = {"int": {"follower": 0, "illusion": 15, "minor": 0}, "string": {"hold": "Whiterun", "home": "Sven's House",
             "home_town": "Riverwood", "name": "Hilde", "race": "Nord", "ref_id": "00035534", "sex": "female", "town": "Riverwood"}}
SVEN_NPC = {"int": {"follower": 0, "illusion": 15, "minor": 0}, "string": {"hold": "Whiterun", "home": "Sven's House",
            "home_town": "Riverwood", "name": "Sven", "race": "Nord", "ref_id": "00013491", "sex": "male", "town": "Riverwood"}}
TIES = {"01347F": {"day": 0, "home": "Sven's House", "name": "Sven", "ties": [{"base": "035533", "kind": "parent", "name": "Hilde"},
                                                                                {"base": "01347C", "kind": "works_for", "name": "Gerdur"}]},
        "035533": {"day": 3, "home": "Sven's House", "name": "Hilde", "ties": [{"base": "01347F", "kind": "Child", "name": "Sven"}]}}
KILLING = {"id": "crime-murder-00013486-623", "kind": "killing", "day": 0.623272,
           "place": {"location": "Sleeping Giant Inn", "town": "Riverwood", "hold": "Whiterun"},
           "involved": [{"key": "player", "base": "", "ref": "", "name": "Brom"}, {"key": "013479", "base": "013479", "ref": "013486", "name": "Orgnar"}],
           "present": [{"key": "01347F", "base": "01347F", "ref": "013491", "name": "Sven"}],
           "true_text": "Brom murdered Orgnar at Sleeping Giant Inn.", "public_text": "Brom murdered Orgnar at Sleeping Giant Inn.",
           "size": "big", "wipes": [], "retracted": False, "importance": 0.65, "crime": "murder", "player_named": True, "by_player": True,
           "known": {"r013491": {"how": "seen", "since": 0.623272, "by": "", "mem": "x", "name": "Sven", "ref": "013491", "base": "01347F",
                                 "town": "Riverwood", "text": "Brom murdered Orgnar at Sleeping Giant Inn."}}}


def fake_summaries(tmp, char, reply='{"memory": "Spoke briefly.", "importance": 0.2}'):
    summaries = FakeSummaries({char.name: Params([f'line {i}' for i in range(8)], [char])}, reply)
    summaries._Summaries__game = type('Game', (), {'conversation_folder_path': str(tmp / 'conversations')})()
    summaries._Summaries__language_name = 'English'
    return summaries


def news_store(tmp, world, events):
    from living_world import worldlog as W
    store = memory.MemoryStore(str(tmp / 'conversations'), world)
    W.change_log(store, lambda log: log['events'].extend(json.loads(json.dumps(events))) or True)
    return store


def part_news(tmp):
    from living_world import news as N, worldlog as W
    world = 'NEWS4'
    store = news_store(tmp, world, [KILLING])
    write_channel('ties.json', TIES)
    write_channel('npc/035533.json', HILDE_NPC)
    write_channel('npc/01347F.json', SVEN_NPC)
    hilde = Char('Hilde', '035534')
    LW._last_store.update(store=None, people=[])
    talks = []
    for game_days in (2.51, 3.51, 4.51):  # Mantella's time (game day 1.5, 2.5, 3.5); the day file still says day 1
        write_channel('conversation.json', {'int': {'day': 1, 'talk_open': 0}, 'string': {'player': 'Brom'}, 'stringList': {'speakers': ['035533']}})
        summaries = fake_summaries(tmp, hilde)
        LW._memory_text('', {'characters': [hilde], 'world_id': world, 'summaries': summaries, 'game_days': game_days})
        got = [e for e in store.load('Hilde', '035534')['recent'] if str(e.get('key', '')).startswith('world:')]
        talks.append(got)
        LW._summarize({'messages': None, 'npcs_to_summarize': [hilde], 'npcs_in_conversation': People(), 'world_id': world,
                       'is_reload': False, 'pending_shares': None, 'end_timestamp': game_days, 'is_radiant': False, 'summaries': summaries})
    check('news: at game day 1.5 Hilde has not heard yet (Sven tells her about a day after)', talks[0] == [], talks[0])
    check("news: at her next talk, a minute later at day 2.5, Sven has told his mother", talks[1] and talks[1][0].get('source') == 'told'
          and talks[1][0].get('told_by') == 'Sven', talks[1])
    known = next(e for e in W.read_log(store)['events'] if e['id'] == KILLING['id'])['known']
    check('news: the event now counts Hilde as knowing it, told by Sven', any(k.get('name') == 'Hilde' and k.get('how') == 'told'
                                                                            and k.get('by') == 'Sven' for k in known.values()), known)

    # every tie kind, listed on the witness's sheet and on the listener's sheet
    mirror = {'spouse': 'spouse', 'courting': 'courting', 'parent': 'child', 'child': 'parent', 'sibling': 'sibling', 'cousin': 'cousin',
              'works_for': 'employs', 'employs': 'works_for', 'household': 'household'}
    failed = []
    for i, kind in enumerate(W.TIE_ORDER):
        for side in ('witness', 'listener'):
            ties = ({'01347F': {'name': 'Sven', 'home': 'A', 'ties': [{'kind': kind, 'base': '0A0001', 'name': 'Kin'}]}} if side == 'witness'
                    else {'0A0001': {'name': 'Kin', 'home': 'B', 'ties': [{'kind': mirror[kind], 'base': '01347F', 'name': 'Sven'}]}})
            write_channel('ties.json', ties)
            s = news_store(tmp, f'TIE{i}{side}', [dict(KILLING, place={'location': 'Far', 'town': '', 'hold': ''})])
            kin = {'name': 'Kin', 'ref_id': '000A0002', 'base_id': '0A0001', 'home': 'B' if side == 'witness' else 'C', 'minor': 0}
            me = W.identify(kin, {'speakers': [kin], 'store': s})
            got = N.catch_up(s, me, 2.6, {'speakers': [kin], 'store': s})
            if not (got and got[0]['how'] == 'told' and got[0]['by'] == 'Sven'):
                failed.append((kind, side, got))
    check('news: every tie kind passes it on, in both directions', not failed, failed)
    write_channel('ties.json', TIES)


# --- 4. recognition --------------------------------------------------------------------------------------------------
def part_recognition(tmp):
    from living_world import timeline as T, worldlog as W, news as N
    write_channel('recognition.json', {'int': {'face_hidden': 1}})
    write_channel('world.json', {'hold': 'Whiterun', 'fame': {'Whiterun': 0}, 'thane': []})
    # (a) a command given during the talk, after the greeting said she does not recognise the hooded player
    store = memory.MemoryStore(str(tmp / 'conversations'), 'RECOG4')
    LW._last_store.update(store=store, people=[('Camilla Valerius', '013488')])
    write_channel('conversation.json', {'int': {'day': 0}, 'string': {'player': 'Brom'}, 'stringList': {'speakers': ['01347B']}})
    command.save(store, {'commands': [], 'seen': [], 'ended': []})
    greeting = LW._recognition([{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'hi'}])
    check('recognition (setup): at the greeting she does not recognise the hooded player', 'Camilla Valerius does not recognise the hooded stranger' in greeting and 'Brom' not in greeting, greeting)
    command.save(store, {'commands': [spell_record('ce751b40b8da', 'k', 'Camilla Valerius', '013488', 0.626906)], 'seen': ['k'], 'ended': []})
    later = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'Hello.'},
             {'role': 'user', 'content': 'Do you know who I am?'}]
    fix = LW._recognition(later)
    check('recognition: a command given during the talk corrects the greeting in the newest message, once',
          'Camilla Valerius now knows who Brom is, hood or not. That is no earlier acquaintance' in fix and LW._recognition(later) == '', fix)

    # (b) an older save loaded: the first request has only the newer save's counter; memories after now are set aside
    store = memory.MemoryStore(str(tmp / 'conversations'), 'RELOAD4')
    late = '2-110997587-421475'
    mem = store.load('Gerdur', '013489')
    mem['recent'] = [{'day': 1, 'hour': 13, 'talk': late, 'seq': 2, 'text': 'Brom gave me a silver necklace from Whiterun.'},
                     {'day': 1, 'hour': 14, 'talk': '3-649185773-554145', 'seq': 3, 'text': 'Brom came back asking about the necklace.'},
                     {'day': 1, 'hour': 15, 'talk': '4-460134315-685650', 'seq': 4, 'text': 'Brom and I talked about the mill again.'}]
    store.save('Gerdur', '013489', mem)
    T._save(store, {'links': {late: ['1-1488437483-187961', 2], '3-649185773-554145': [late, 3], '4-460134315-685650': ['3-649185773-554145', 4]},
                    'gone': {}, 'times': {late: 0.54, '3-649185773-554145': 0.58, '4-460134315-685650': 0.62}})
    B.save(store, 'Gerdur', '013489', dict(B.load(store, 'Gerdur', '013489'), text='A hooded stranger named Brom gave Gerdur a necklace.',
                                           talk='3-649185773-554145', seq=3, after=[1, 14]))
    # the counter in the day file still holds the newer save (its last talk began at 0.62); the save loaded is at 0.51
    write_channel('conversation.json', {'int': {'day': 0, 'talk_seq': 5, 'talk_open': 0}, 'float': {'talk_time': 0.62},
                                        'string': {'player': 'Brom', 'talk_id': '', 'talk_parent': '4-460134315-685650'},
                                        'stringList': {'speakers': ['01347C']}})
    write_channel('npc/01347C.json', {"int": {"minor": 0, "illusion": 15}, "string": {"name": "Gerdur", "ref_id": "00013489", "sex": "female",
                                                                                      "town": "Riverwood", "hold": "Whiterun"}})
    gerdur = Char('Gerdur', '013489')
    text = LW._memory_text('', {'characters': [gerdur], 'world_id': 'RELOAD4', 'summaries': fake_summaries(tmp, gerdur), 'game_days': 1.51})
    check('reload: memories from after the loaded save are not in the greeting', 'necklace' not in text and 'mill again' not in text, text[-600:])
    check('reload: the Now paragraph written after a later talk is not sent', 'necklace' not in B.now_text(store, 'Gerdur', '013489'),
          B.now_text(store, 'Gerdur', '013489'))
    LW._last_store.update(store=store, people=[('Gerdur', '013489')])
    hello = LW._recognition([{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'hi'}])
    check('reload: talks from the abandoned later save do not make her know the hooded player', 'Gerdur does not recognise the hooded stranger' in hello, hello)
    W.change_log(store, lambda log: log['events'].append(dict(KILLING, id='late-event', talk='4-460134315-685650', seq=4,
                                                               present=[{'key': '01347C', 'base': '01347C', 'ref': '013489', 'name': 'Gerdur'}],
                                                               known={})) or True)
    check('reload: an event logged in a later talk is not news to her', not any(p['e']['id'] == 'late-event' for p in N._prepare(store)))
    LW._summarize({'messages': None, 'npcs_to_summarize': [], 'npcs_in_conversation': People(), 'world_id': 'RELOAD4', 'is_reload': False,
                   'pending_shares': None, 'end_timestamp': 1.52, 'is_radiant': False, 'summaries': fake_summaries(tmp, gerdur)})

    # (c) a masked murder: "a hooded stranger" for the witness who does not know the player, the name for one who does
    store = memory.MemoryStore(str(tmp / 'conversations'), 'MASK4')
    row = {"by_player": True, "crime": "murder", "day": 0.623272, "hold": "Whiterun", "id": "murder-00013486-623", "masked": 1,
           "place": "Sleeping Giant Inn", "player": "Brom", "town": "Riverwood",
           "victim": {"base": "013479", "name": "Orgnar", "ref_id": "00013486", "thalmor": 0},
           "witnesses": [{"base": "01347F", "name": "Sven", "ref_id": "00013491"}, {"base": "01347B", "name": "Camilla Valerius", "ref_id": "00013488"}]}
    event = W.from_crime(store, row, 'Brom')
    check('masked murder: the public text names a hooded stranger', event and event['public_text'] == 'A hooded stranger murdered Orgnar at Sleeping Giant Inn.'
          and not event.get('player_named'), event)
    sven = W.identify(dict(lw_state._flatten(SVEN_NPC), base_id='01347F'), {'store': store})
    camilla = W.identify(dict(lw_state._flatten(CAMILLA_NPC), base_id='01347B'), {'store': store})
    knows = lambda name, ref: name == 'Camilla Valerius'
    got_s = N.catch_up(store, sven, 0.65, {'store': store, 'knows': knows})
    got_c = N.catch_up(store, camilla, 0.65, {'store': store, 'knows': knows})
    check('masked murder: the witness who does not know the player remembers a hooded stranger',
          got_s and got_s[0]['text'] == 'A hooded stranger murdered Orgnar at Sleeping Giant Inn.', got_s)
    check('masked murder: a witness who knows the player personally remembers the name',
          got_c and got_c[0]['text'] == 'Brom murdered Orgnar at Sleeping Giant Inn.', got_c)


# --- 5. no server line can be read as a "Name: line" ------------------------------------------------------------------
def part_labels(tmp):
    import inspect, re
    label = re.compile(r"^\(?\s*[A-Z][^.:()\n]{0,40}:\s")
    store = memory.MemoryStore(str(tmp / 'conversations'), 'LABEL4')
    command.save(store, {'commands': [dict(spell_record('c1', 'k', 'Camilla Valerius', '013488', 0.6), announced=False)], 'seen': ['k'], 'ended': []})
    speakers = [{'name': 'Camilla Valerius', 'ref_id': '00013488', 'minor': 0}]
    lines = (command.system_text(store, speakers, 'Brom', LW._ref) + '\n' + command.newest_text(store, speakers, 'Brom', LW._ref) + '\n'
             + command.newest_text(store, speakers, 'Brom', LW._ref) + '\n' + R.lifted_text('Camilla Valerius', 'Brom', 'spell', 'her') + '\n'
             + R.lifted_text('Sigrid', 'Brom', 'forget', 'her', 1, True)).splitlines()
    bad = [l for l in lines if label.match(l.strip())]
    check('labels: no command or release line starts with a short phrase and a colon', not bad and len(lines) >= 5, bad)
    check('labels: the command lines say they are direction, never words to say', 'never words to say' in lines[0]
          and 'not words to say' in command.newest_text(store, speakers, 'Brom', LW._ref))
    check('labels: the scene line in the newest message is no "Current scene:" label', 'Current scene:' not in inspect.getsource(LW._extra_text))


# --- 8 / 9. a killing inside a fight that goes on; followers are no witnesses; the witness has it on his mind ----------
def part_crimes(tmp):
    from living_world import news as N, worldlog as W
    if not (ART / 'overwrite-StorageUtilData-MLW' / 'battles.json').is_file():
        print('SKIP crimes: the live test 4 files are not here (MLW_EVIDENCE)')
        return
    store = memory.MemoryStore(str(tmp / 'conversations'), 'FIGHT4')
    fight = json.load(open(ART / 'overwrite-StorageUtilData-MLW' / 'battles.json', encoding='utf-8'))['fights'][0]
    fight['fighters'].append({'base_id': '01347F', 'name': 'Sven', 'ref_id': '00013491', 'role': 'bystander', 'side': 0, 'dead': 0,
                              'hostile': 0, 'kills': [], 'killer': ''})
    check('fight (setup): the fight from the live test is still open', fight['active'] == 1)
    W.from_battles(store, [fight], 'Brom')
    ev = next((e for e in W.read_log(store)['events'] if e['kind'] == 'killing'), None)
    check('fight still going on: the killing of someone who was no threat is logged at once', ev and 'Orgnar' in ev['true_text'], W.read_log(store)['events'])
    sven = W.identify(dict(lw_state._flatten(SVEN_NPC), base_id='01347F'), {'store': store})
    got = N.catch_up(store, sven, 0.63, {'store': store})
    check('fight still going on: the one who watched learns it at his next talk, as seen', got and got[0]['how'] == 'seen', got)
    fresh = N.fresh_text(['Sven'])
    check('a killing seen a short while ago is on his mind at the greeting (newest message)', 'saw this happen a short while ago' in fresh, fresh)
    check('...once', N.fresh_text(['Sven']) == '')
    # followers listed as witnesses by an older World are left out
    write_channel('npc/2A4808.json', {'int': {'follower': 1, 'minor': 0}, 'string': {'name': 'Mira'}})
    row = json.load(open(ART / 'overwrite-StorageUtilData-MLW' / 'crimes.json', encoding='utf-8'))['crimes'][0]
    store2 = memory.MemoryStore(str(tmp / 'conversations'), 'CRIME4')
    ev = W.from_crime(store2, row, 'Brom')
    names = [p['name'] for p in ev['present']]
    check('crimes: a follower is no witness who spreads it', 'Mira' not in names and 'Sven' in names, names)


# --- 6. the greeting offers the same actions as the requests after it (one cached prefix) -------------------------
def part_cache(tmp):
    import threading, time as _time, types
    store = memory.MemoryStore(str(tmp / 'conversations'), 'CACHE4')
    command.save(store, {'commands': [], 'seen': [], 'ended': []})
    write_channel('commands.json', {'stringList': {'key': [], 'text': [], 'refs': [], 'names': [], 'time': [], 'player': []}})
    write_channel('releases.json', {'stringList': {}})
    LW._last_store.update(store=store, people=[('Hod', '01348A')], summaries=None)
    write_channel('conversation.json', {'int': {'day': 0}, 'string': {'player': 'Brom'}, 'stringList': {'speakers': []}})
    tools = [{'function': {'name': 'SexWithPlayer', 'description': 'x'}}, {'function': {'name': 'Wave', 'description': 'y'}}]
    real = (LW._gates, LW._installed, LW.characters.PATH)
    fake = types.ModuleType('src.extensions')
    fake._registry = types.SimpleNamespace(speaking_ids=['01347D'])
    real_ext = sys.modules.get('src.extensions')
    sys.modules['src.extensions'] = fake
    LW._gates = lambda: {'SexWithPlayer': 'intimate'}
    LW._installed = lambda: {'Integration Hub', 'OStim Expansion'}
    LW.characters.PATH = str(tmp / 'characters_cache.json')
    LW.characters.write_intimacy_mode('npc_decides')
    greeting = {'messages': [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'hi'}]}
    reply = {'messages': greeting['messages'] + [{'role': 'assistant', 'content': 'Hello.'}, {'role': 'user', 'content': 'How are you?'}]}
    names = lambda t: [x['function']['name'] for x in t]
    try:
        path = Path(lw_state.DATA_DIR) / 'npc' / '01347D.json'
        path.unlink(missing_ok=True)
        # the game writes Hod's minor flag a moment after Mantella's first request went out (MLW_Channel.WriteMinorFirst)
        later = threading.Timer(0.3, lambda: write_channel('npc/01347D.json', {'int': {'minor': 0}, 'string': {'name': 'Hod', 'ref_id': '0001348A'}}))
        later.start()
        first = names(LW._filter_tools(list(tools), greeting))
        later.join()
        second = names(LW._filter_tools(list(tools), reply))
        check('greeting of a newly met adult: the same actions as the next request (one cached prefix)', first == second == ['SexWithPlayer', 'Wave'], (first, second))
        path.unlink()
        started = _time.time()
        offered = names(LW._filter_tools(list(tools), greeting))
        check('greeting, the file never comes: after a short wait still nothing intimate (fail closed)', offered == ['Wave']
              and _time.time() - started < LW.GREETING_WAIT + 1.0, offered)
        write_channel('npc/01347D.json', {'int': {'minor': 1}, 'string': {'name': 'Hod', 'ref_id': '0001348A'}})
        check('greeting, the game says child: nothing intimate', names(LW._filter_tools(list(tools), greeting)) == ['Wave'])
        # an absolute command: the actions change on the request that reads it, with the prompt (not one request later)
        write_channel('npc/01347D.json', {'int': {'minor': 0, 'intimate': 0}, 'string': {'name': 'Hod', 'ref_id': '0001348A'}})
        LW.characters.write_intimacy_mode('lovers_only')
        before = names(LW._filter_tools(list(tools), reply))
        write_channel('commands.json', {'stringList': {'key': ['0.7-1'], 'text': ['You adore me.'], 'refs': ['0001348A'], 'names': ['Hod'],
                                                       'time': ['0.7'], 'player': ['Brom']}})
        with_command = names(LW._filter_tools(list(tools), reply))
        check('command: the actions change on the same request that first carries the command',
              before == ['Wave'] and with_command == ['SexWithPlayer', 'Wave'], (before, with_command))
    finally:
        LW._gates, LW._installed, LW.characters.PATH = real
        if real_ext is None:
            sys.modules.pop('src.extensions', None)
        else:
            sys.modules['src.extensions'] = real_ext


# --- 10. the status page's token table: one reply per row, money to 4 decimals -----------------------------------
def part_status():
    from living_world import ui_tab
    live = [{'time': 1794723545.0, 'model': 'test-model', 'cache_read': 0, 'cache_write': 5719, 'uncached': 620, 'output': 37,
             'cost': 0.0041083000000000005},
            {'time': 1794723559.0, 'model': 'test-model', 'cache_read': 2336, 'cache_write': 3641, 'uncached': 590, 'output': 53,
             'cost': 0.0179},
            {'time': 1794723691.0, 'model': 'test-model', 'cache_read': 0, 'cache_write': 8416, 'uncached': 1017, 'output': 56,
             'cost': 0.0355}]
    text = ui_tab.usage_markdown(live)
    rows = text.splitlines()[2:]
    check('status: the first row holds the numbers of that one reply (read 0, write 5,719, new 620)',
          '| 0 | 5,719 | 620 | 37 | 0.0041 |' in rows[0] and '2,336' not in rows[0] and '1,017' not in rows[0], rows[0])
    check('status: money to 4 decimals, no float noise', '0.0041083' not in text and ui_tab.usage_table(live)[0][-1] == 0.0041, text)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    lw_state.DATA_DIR = str(tmp / 'channel')
    os.makedirs(lw_state.DATA_DIR)
    LW.characters.PATH = str(tmp / 'living_world_characters.json')
    for part in (lambda: part_release(tmp), part_rewrite, lambda: part_news(tmp), lambda: part_recognition(tmp),
                 lambda: part_labels(tmp), lambda: part_crimes(tmp), lambda: part_cache(tmp), part_status):
        try:
            part()
        except Exception as e:
            import traceback; traceback.print_exc()
            check(f'part ran without an error ({e})', False)

print(f'\n{len(FAILS)} failed' if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
