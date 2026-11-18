"""Offline tests for the defects found by live test 3 (2026-11-15), built from the files that test left behind
(releases.json, crimes.json, Gerdur's memories and npc file, the world log's wipe event), copied in here as data:
releases chosen in game read without case, a forget that covers every memory of the thing, no gap line for one
forgotten thing, pronouns from the game's sex, wipes and releases never news, witnesses knowing the murder they saw at
their next talk, the home line naming the town, and memories never ending on a cut-off event line.
Run with a Python 3.11: test_live_test_3.py <repo server dir>"""
import json, logging, os, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import (bio_evolve as B, command, contracts, embed, facts_history as F, lw_state, memory, news as N,
                          release as R, worldlog as W)
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

# --- the live test's files (copied from the test's leftovers) --------------------------------------------------------
RELEASES = {"stringList": {"base": ["01347C", "01347C"], "choice": ["SPELL", "Forget"],
                           "key": ["0.854374-811565", "0.874352-970470"], "name": ["Gerdur", "Gerdur"],
                           "player": ["Brom", "Brom"], "ref": ["00013489", "00013489"], "time": ["0.854374", "0.874352"]}}
GERDUR_NPC = {"int": {"minor": 0, "illusion": 15, "magic": 0, "follower": 0, "spouse": 0, "maras": 0, "maras_on": 1},
              "string": {"hold": "Whiterun", "home": "Hod and Gerdur's House", "home_town": "Riverwood", "location": "Riverwood",
                         "name": "Gerdur", "race": "Nord", "ref_id": "00013489", "sex": "female", "town": "Riverwood",
                         "maras_status": "Unknown"}}
TALK1 = ("A hooded stranger I didn't recognise asked after the mill and after my brother Ralof, and seemed to know my "
         "family. I told them the soldiers buy every log we cut and that Ralof is with the Stormcloaks. They said they'd "
         "give me a silver necklace picked out in Whiterun, but nothing ever reached my hand. I told them plainly I'm a "
         "married woman and wanted to know why before I'd take it. I still don't know who they are or what they want.")
TALK2 = ("Spoke briefly with Brom: Well, you again. I'm still waiting to hear why a stranger would send me a silver "
         "necklace and ask after my brother. I'm a married woman, and I'd have your reasons plain before I trust you with "
         "anything of mine.")
CRIMES = {"crimes": [{"by_player": True, "crime": "murder", "day": 0.963414, "hold": "Whiterun", "id": "murder-0001348C-963",
                      "place": "Riverwood", "player": "Brom", "town": "Riverwood",
                      "victim": {"base": "013480", "name": "Faendal", "ref_id": "0001348C", "thalmor": 0},
                      "witnesses": [{"base": "01347F", "name": "Sven", "ref_id": "00013491"},
                                    {"base": "013477", "minor": 1, "ref_id": "00013484"},
                                    {"base": "035533", "name": "Hilde", "ref_id": "00035534"},
                                    {"base": "01347B", "name": "Camilla Valerius", "ref_id": "00013488"},
                                    {"base": "0012DB", "name": "Whiterun Guard", "ref_id": "550018CF"}]}],
          "player": "Brom"}
WIPE_EVENT = {"id": "wipe-8ee24e2618e8", "kind": "wipe", "day": 0.832691,
              "place": {"location": "Riverwood", "town": "Riverwood", "hold": "Whiterun"},
              "involved": [{"key": "r013489", "base": "", "ref": "013489", "name": "Gerdur"}, {"key": "player", "base": "", "ref": "", "name": "Brom"}],
              "present": [{"key": "r013489", "base": "", "ref": "013489", "name": "Gerdur"}, {"key": "player", "base": "", "ref": "", "name": "Brom"}],
              "true_text": "Brom made Gerdur forget the player giving them the necklace with an Absolute Command.",
              "public_text": "Gerdur has lost the memory of something, and is frightened by it.", "size": "small", "wipes": [],
              "known": {"r013489": {"how": "own", "since": 0.832691, "by": "", "mem": "", "name": "Gerdur", "ref": "013489"}},
              "retracted": False, "importance": 0.4, "came_to_light": False, "mode": "gap"}
LUCAN = {'name': 'Lucan Valerius', 'ref_id': '00013487', 'base_id': '01347A', 'home': "Lucan's Dry Goods", 'home_town': 'Riverwood',
         'hold': 'Whiterun', 'town': 'Riverwood', 'sex': 'male', 'minor': 0}
SVEN = {'name': 'Sven', 'ref_id': '00013491', 'base_id': '01347F', 'home': "Sven's House", 'home_town': 'Riverwood',
        'hold': 'Whiterun', 'town': 'Riverwood', 'sex': 'male', 'minor': 0}
HILDE = {'name': 'Hilde', 'ref_id': '00035534', 'base_id': '035533', 'home': "Sven's House", 'home_town': 'Riverwood',
         'hold': 'Whiterun', 'town': 'Riverwood', 'sex': 'female', 'minor': 0}
GERDUR = dict(lw_state._flatten(GERDUR_NPC), base_id='01347C')


def write_channel(name, data):
    path = os.path.join(lw_state.DATA_DIR, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def visible(store, name, ref):
    return [e['text'] for e in store.load(name, ref)['recent'] if not e.get('hidden')]


def new_store(tmp, world):
    return memory.MemoryStore(str(tmp / 'conversations'), world)


def command_record(cid, key, text, given, forget='', status='active'):
    return {'id': cid, 'key': key, 'text': text, 'given': given, 'npcs': [{'name': 'Gerdur', 'ref_id': '013489'}],
            'forget': forget, 'aware': False, 'status': status, 'announced': True, 'hidden': [], 'read_by': 'model',
            'hours': 0.0, 'until': -1.0, 'bio_before': []}


# --- 1. releases chosen in game: "SPELL" and "Forget" are read; nothing is dropped silently ------------------------
def part_1():
    store = new_store(tmp, 'REL')
    command.save(store, {'commands': [command_record('024810fbd116', '0.823170-612409', 'You are under my spell. You adore me and will do as I say.', 0.82317),
                                      command_record('8ee24e2618e8', '0.832691-209122', 'Forget that I gave you the necklace.', 0.832691,
                                                     forget='the player giving them the necklace')],
                         'seen': ['0.823170-612409', '0.832691-209122'], 'ended': []})
    write_channel('releases.json', RELEASES)
    rows = R.read_game()
    check('release: the game\'s "SPELL" and "Forget" are read as spell and forget', [r['choice'] for r in rows] == ['spell', 'forget'], rows)
    out = R.poll_game(store, 'Brom', 0, [GERDUR])
    left = [c['id'] for c in command.load(store)['commands']]
    check('release: the in-game release ends the commands on Gerdur', out and all(o.get('ok') for o in out) and left == [], (out, left))
    record = R.load_record(store)
    check('release: both releases are marked handled in the true record', record['seen'] == ['0.854374-811565', '0.874352-970470'], record['seen'])
    check('release: a release row of the true record says spell', any(r['kind'] == 'release' and r['choice'] == 'spell' for r in record['rows']), record['rows'])
    check('release: the second release, with nothing left to release, is logged, not dropped silently',
          any('no absolute command binds them' in l for l in LOG.lines), LOG.lines[-5:])
    LOG.lines.clear()
    write_channel('releases.json', {"stringList": {"KEY": ["9.0-1"], "Choice": ["maybe"], "name": ["Gerdur"], "ref": ["00013489"],
                                                   "base": ["01347C"], "time": ["9.0"], "player": ["Brom"]}})
    check('release: keys read without case, an unknown choice is logged, not dropped silently',
          R.read_game() == [] and any('was not used' in l and 'maybe' in l for l in LOG.lines), LOG.lines)
    queue = command.read_queue({"stringList": {"Key": ["1.0-1"], "TEXT": ["Follow me"], "refs": ["00013489"], "Names": ["Gerdur"],
                                               "time": ["1.0"], "player": ["brom"]}})
    check('commands.json: keys read without case', queue and queue[0]['text'] == 'Follow me' and queue[0]['names'] == ['Gerdur'], queue)
    check('ties.json: kinds read without case ("Child", "Spouse")',
          contracts.load_ties({'013475': {'name': 'Alvor', 'ties': [{'kind': 'Child', 'base': '013477', 'name': 'Dorthe'},
                                                                    {'Kind': 'Spouse', 'base': '013476', 'name': 'Sigrid'}]}})['013475']['ties']
          == [{'kind': 'child', 'base': '013477', 'name': 'Dorthe'}, {'kind': 'spouse', 'base': '013476', 'name': 'Sigrid'}])
    check('marriages / results: player and result without case',
          contracts.load_marriages({'marriages': [{'base': '013BA1', 'status': 'Married', 'player': 'brom'}]}, 'Brom')[0]['status'] == 'married')


# --- 2. forget covers every memory of the thing; one forgotten thing leaves no gap line -------------------------
def part_2():
    store = new_store(tmp, 'FORGET')
    mem = store.load('Gerdur', '013489')
    mem['recent'] = [{'day': 1, 'hour': 13, 'text': TALK1, 'witnesses': ['Gerdur'], 'importance': 0.4, 'seq': 2},
                     {'day': 1, 'hour': 14, 'text': TALK2, 'witnesses': ['Gerdur'], 'importance': 0.2, 'seq': 3}]
    store.save('Gerdur', '013489', mem)
    command.save(store, {'commands': [command_record('8ee24e2618e8', '0.832691-209122', 'Forget that I gave you the necklace.',
                                                     0.832691, status='checking')], 'seen': ['0.832691-209122'], 'ended': []})
    real_candidates = memory.archive.hide_candidates

    def live_candidates(query, rows, engine=None, limit=1):
        # what the meaning search gave in the live test: talk 2 a close fit, talk 1 only a looser one for the model
        return ([r for r in rows if 'Well, you again' in (r.get('text') or '')][:limit],
                [r for r in rows if 'They said they' in (r.get('text') or '')][:limit])

    def literal_model(prompt, text):
        """Answers like the model did: the check reads the forget; the confirm step says no to a memory where the
        necklace never arrived unless the question also counts memories that only talk about it."""
        if '"forget": if the command' in prompt:
            return '{"forget": "the player giving them the necklace", "hours": null, "aware": false}'
        if 'numbered memories' in prompt:
            items = [line for line in text.split('\n') if line.strip()]
            loose = 'mention or touch on' in prompt
            return json.dumps(['yes' if 'necklace' in t and (loose or 'ever reached' not in t) else 'no' for t in items])
        return 'NONE'
    memory.archive.hide_candidates = live_candidates
    try:
        command.finish(store, '8ee24e2618e8', {'command_model_check': True, 'command_forget_limit': 3, 'command_hours': 0}, literal_model)
    finally:
        memory.archive.hide_candidates = real_candidates
    shown = visible(store, 'Gerdur', '013489')
    check('forget: the talk-1 memory that names the necklace is hidden too', not any('necklace' in t for t in shown), shown)
    gaps = B.load(store, 'Gerdur', '013489')['gaps']
    check('forget of one thing: no gap line (she simply does not remember it)', gaps == [], gaps)
    rows = R.record_rows(store, 'Gerdur', '013489')
    check('forget of one thing: still written in the true record (clean)', rows and rows[0]['kind'] == 'forget' and rows[0]['mode'] == 'clean', rows)

    # a release that forgets the whole period: a gap line about that period, "her" from the game's sex
    store = new_store(tmp, 'PERIOD')
    mem = store.load('Gerdur', '013489')
    mem['recent'] = [{'day': 1, 'hour': 20, 'text': 'Brom and I talked by the mill; I adore him.', 'witnesses': ['Gerdur']}]
    store.save('Gerdur', '013489', mem)
    command.save(store, {'commands': [command_record('024810fbd116', 'k1', 'You adore me.', 0.82317)], 'seen': ['k1'], 'ended': []})
    R.release_command(store, '024810fbd116', 'forget', player='Brom', today=0, speakers=[GERDUR])
    gaps = [g['text'] for g in B.load(store, 'Gerdur', '013489')['gaps']]
    check('release forgets the period: the gap names the days and uses "her" for a woman',
          gaps == ['Gerdur has no memory of day 1, and it frightens her.'], gaps)
    check('pronouns: "them" only when the sex is unknown', R.pronouns(None, 'Someone', '0ABC01', []) == ('them', 'their')
          and R.pronouns(None, 'Gerdur', '013489', [dict(GERDUR, sex='FEMALE')]) == ('her', 'her'))
    check('a forget that asks her to notice gives a gap about something missing, not a whole day',
          R.gap_text('Gerdur', [1, 1], 'her', period=False) == 'Gerdur knows something is missing from her memory, and it frightens her.')


# --- 3. a wipe or a release is never news ------------------------------------------------------------------------
def part_3():
    store = new_store(tmp, 'WIPE')
    ev = W.from_command_wipe(store, command_record('cw', 'kw', 'Forget that I gave you the necklace.', 0.832691,
                                                   forget='the player giving them the necklace'), 'Brom', 'gap')
    check('wipe: logged for the Hub, with no public text', ev and ev['public_text'] == '' and ev['kind'] == 'wipe', ev)
    W.change_log(store, lambda log: log['events'].append(json.loads(json.dumps(WIPE_EVENT))) or True)  # the live test's old event
    lucan = W.identify(LUCAN, {'speakers': [LUCAN], 'store': store})
    got = N.catch_up(store, lucan, 5.5, {'speakers': [LUCAN], 'store': store})
    check('wipe: an old public wipe line is not passed on as village gossip', not any('memory' in d['text'] for d in got), got)
    W.note_people(store, [W.identify(GERDUR, {'speakers': [GERDUR], 'store': store})])  # her ids, as the live save had them
    hod_tie = {'kind': 'spouse', 'base': '01347C', 'name': 'Gerdur'}
    hod = W.identify({'name': 'Hod', 'ref_id': '0001348A', 'base_id': '01347D', 'home_town': 'Riverwood', 'hold': 'Whiterun'}, {'store': store})
    got = N.catch_up(store, hod, 5.5, {'store': store, 'ties': {'01347D': {'name': 'Hod', 'home': "Hod and Gerdur's House", 'ties': [hod_tie]}}})
    check('wipe: her husband, in the same village, does not hear of it either', got == [], got)
    rel = W.from_command_release(store, command_record('cr', 'kr', 'You adore me.', 0.8), 'aware', 'Brom', day=0.9)
    check('release (remembers, knows it was a spell): she knows, nobody else is told', rel and rel['public_text'] == ''
          and rel['came_to_light'] and list(rel['known']) == ['r013489'], rel)


# --- 4. witnesses know the murder they saw, at their next talk ---------------------------------------------------
def part_4():
    store = new_store(tmp, 'CRIME')
    write_channel('crimes.json', CRIMES)
    write_channel('battles.json', {'player': 'Brom', 'fights': [{
        'id': 'f-1', 'active': 1, 'start': 0.962, 'end': -1, 'place': 'Riverwood', 'fighters': [
            {'name': 'Brom', 'ref_id': '00000014', 'role': 'Player', 'side': 0},
            {'name': 'Faendal', 'ref_id': '0001348C', 'base_id': '013480', 'role': 'enemy', 'side': 1, 'dead': 1, 'killer': '00000014'},
            {'name': 'Camilla Valerius', 'ref_id': '00013488', 'base_id': '01347B', 'role': 'bystander', 'side': 0}]}]})
    # the talk running when it happened (it started before the kill): Lucan was in it
    write_channel('conversation.json', {'string': {'player': 'Brom', 'talk_id': '16-x'}, 'int': {'day': 0, 'talk_open': 1, 'talk_seq': 16},
                                        'float': {'talk_time': 0.95}})
    W.ingest(store, 'Brom', [LUCAN])
    killing = W.find(store, 'crime-murder-0001348C-963')
    check('murder: logged at once although the fight is still going on', killing is not None and killing['kind'] == 'killing', W.events(store))
    names = sorted(p.get('name') or '' for p in (killing or {}).get('present', []))
    check('murder: the named witnesses, the child (unnamed) and the people in the talk are there (ring 1)',
          {'Sven', 'Hilde', 'Camilla Valerius', 'Whiterun Guard', 'Lucan Valerius'} <= set(names)
          and any(p.get('minor') and not p.get('name') for p in killing['present']), names)
    # Sven's next talk, one game minute later: the game's day is still 0 (a whole number)
    write_channel('conversation.json', {'string': {'player': 'Brom', 'talk_parent': '16-x'}, 'int': {'day': 0, 'talk_open': 0, 'talk_seq': 17}})
    n = N.talk_start(store, [SimpleNamespace(name='Sven', ref_id='013491')], 0, {'speakers': [SVEN]}, force=True)
    sven = visible(store, 'Sven', '013491')
    check('murder: Sven, a witness, knows it as seen at his next talk', any('murdered Faendal' in t for t in sven), sven)
    entry = next((k for k in W.find(store, 'crime-murder-0001348C-963')['known'].values() if k.get('name') == 'Sven'), {})
    check('murder: Sven is in the known list as seen', entry.get('how') == 'seen', entry)
    # Hilde days later, while conversation.json still holds the last talk's day (the greeting comes before the game writes it)
    N.talk_start(store, [SimpleNamespace(name='Hilde', ref_id='035534')], 0, {'speakers': [HILDE]}, force=True)
    hilde = visible(store, 'Hilde', '035534')
    check('murder: Hilde, a witness, knows it at her next talk even with the old day in the file', any('murdered Faendal' in t for t in hilde), hilde)
    # the fight closes: no second killing, the fight's people are added to the one already logged
    write_channel('battles.json', {'player': 'Brom', 'fights': [{
        'id': 'f-1', 'active': 0, 'start': 0.962, 'end': 0.964, 'place': 'Riverwood', 'fighters': [
            {'name': 'Brom', 'ref_id': '00000014', 'role': 'player', 'side': 0},
            {'name': 'Faendal', 'ref_id': '0001348C', 'base_id': '013480', 'role': 'ally', 'side': 0, 'dead': 1, 'killer': '00000014'},
            {'name': 'Orgnar', 'ref_id': '00013486', 'base_id': '013479', 'role': 'ally', 'side': 0}]}]})
    W.from_battles(store, None, 'Brom')
    kills = [e for e in W.events(store) if e['kind'] == 'killing' and any(p.get('ref') == '01348C' for p in e['involved'])]
    check('murder: the closed fight adds no second killing', len(kills) == 1, [e['id'] for e in kills])
    check('murder: the fight\'s people are added to the killing', any(p.get('name') == 'Orgnar' for p in kills[0]['present']), kills[0]['present'])
    # a named death during a fight that is still going on is logged at once too, its witnesses there
    write_channel('battles.json', {'player': 'Brom', 'fights': [{'id': 'f-2', 'active': 1, 'start': 2.0, 'end': -1, 'place': 'Riverwood',
                                                                 'fighters': [{'name': 'Alvor', 'ref_id': '00013482', 'base_id': '013475', 'dead': 1}]}]})
    write_channel('crimes.json', dict(CRIMES, deaths=[{'id': 'death-00013482-2001', 'base': '013475', 'ref_id': '00013482', 'name': 'Alvor',
                                                       'day': 2.001, 'place': 'Riverwood', 'town': 'Riverwood', 'hold': 'Whiterun',
                                                       'unique': True, 'witnesses': [{'base': '01347F', 'name': 'Sven', 'ref_id': '00013491'}],
                                                       'player': 'Brom'}]))
    W.from_crimes(store, 'Brom')
    death = W.find(store, 'death-00013482-2001')
    check('death: logged at once during an open fight, its witness there; the player name read without case',
          death is not None and any(p.get('name') == 'Sven' for p in death['present']), death)


# --- 5. the home line names the town, or "Whiterun Hold" when only the hold is known ----------------------------
def part_5():
    check('home: "Hod and Gerdur\'s House, in Riverwood" from the game\'s npc file', F.game_values(GERDUR, 'Brom')['home'] == "Hod and Gerdur's House, in Riverwood",
          F.game_values(GERDUR, 'Brom')['home'])
    check('home: only the hold known -> "in Whiterun Hold"', F.home_text({'home': "Hod and Gerdur's House", 'hold': 'Whiterun'}) == "Hod and Gerdur's House, in Whiterun Hold")
    store = new_store(tmp, 'HOME')
    F.sync_talk(store, [dict(GERDUR, home_town='')], 'Brom', 1)
    F.sync_talk(store, [GERDUR], 'Brom', 2)
    lines = [l for l in F.history(store, 'Gerdur', '00013489')['lines'] if l['fact'] == 'home']
    check('home: the better wording replaces the old line, not a move on hold', len(lines) == 1 and lines[0]['status'] == 'current'
          and lines[0]['value'] == "Hod and Gerdur's House, in Riverwood", lines)


# --- 6. a memory never ends on a cut-off event line ---------------------------------------------------------------
def part_6():
    said = ["Well, you again. I'm still waiting to hear why a stranger would send me a silver necklace and ask after my brother.",
            "I'm a married woman, and I'd have your reasons plain before I trust you with anything of mine.",
            "(Gerdur does not recognise Brom: a hood hides their face.)", "Now then."]
    line = memory.one_line(said, 'Brom')
    check('memory: no cut-off "(Gerdur does not recognise CH" fragment', '(' not in line and line.endswith('mine.') and len(line) <= 270, line)
    check('memory: a long run of words is cut at a word, with "..."', memory.clip('word ' * 100, 40).endswith('word...'))


def run(part):
    try:
        part()
    except Exception as e:  # a part that breaks counts as failed; the others still run
        check(f'{part.__name__} ran without an error', False, repr(e))


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    lw_state.DATA_DIR = str(tmp / 'channel')
    os.makedirs(lw_state.DATA_DIR)
    write_channel('conversation.json', {'string': {'player': 'Brom'}, 'int': {'day': 0}})
    write_channel('npc/01347C.json', GERDUR_NPC)
    run(part_1)
    run(part_2)
    run(part_3)
    run(part_4)
    run(part_5)
    run(part_6)

print(f'\n{len(FAILS)} failed' if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
