"""Offline tests for the world log, news rings, wipe scopes, visible strangeness and player reputation
(server/living_world/worldlog.py, news.py, strangeness.py, reputation.py). No model and no numpy needed.
Run with a Python 3.11: test_worldlog.py <repo server dir>"""
import json, os, sys, tempfile, time
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import embed, lw_state, memory, worldlog as W, news as N, strangeness as S, reputation as R
embed.use(None)

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


tmp = Path(tempfile.mkdtemp())
channel = tmp / 'channel'
(channel / 'npc').mkdir(parents=True)
lw_state.DATA_DIR = str(channel)
know = tmp / 'knowledge'
know.mkdir()
W.KNOWLEDGE_DIRS[:] = [str(know)]
(know / 'places.json').write_text(json.dumps({
    'Riverwood': {'hold': 'Whiterun Hold', 'kind': 'town'}, 'Whiterun': {'hold': 'Whiterun Hold', 'kind': 'city'},
    'Rorikstead': {'hold': 'Whiterun Hold', 'kind': 'town'}, 'Winterhold': {'hold': 'Winterhold', 'kind': 'town'},
    'Sleeping Giant Inn': {'hold': 'Whiterun Hold', 'kind': 'inn', 'town': 'Riverwood'},
    "Alvor and Sigrid's House": {'hold': 'Whiterun Hold', 'kind': 'house', 'town': 'Riverwood'}}), encoding='utf-8')
(know / 'profiles.json').write_text(json.dumps({'profiles': {
    'Lemkil|Nord|AAA001': {'base_id': 'AAA001', 'name': 'Lemkil', 'home': 'Rorikstead', 'hold': 'Whiterun Hold', 'profession': 'farmer'},
    'Brelyna|Dark Elf|AAA002': {'base_id': 'AAA002', 'name': 'Brelyna', 'home': 'Winterhold', 'hold': 'Winterhold', 'profession': 'mage'},
    'Dorthe|Nord|013BA2': {'base_id': '013BA2', 'name': 'Dorthe', 'home': 'Riverwood', 'hold': 'Whiterun Hold', 'profession': 'child'}}}),
    encoding='utf-8')
(channel / 'ties.json').write_text(json.dumps({
    '013BA1': {'name': 'Sigrid', 'home': "Alvor and Sigrid's House", 'day': 41,
               'ties': [{'kind': 'spouse', 'base': '013BA0', 'name': 'Alvor'}, {'kind': 'child', 'base': '013BA2', 'name': 'Dorthe'}]},
    '0BBB01': {'name': 'Hod', 'home': "Hod and Gerdur's House", 'day': 41, 'ties': []},
    '0BBB02': {'name': 'Gerdur', 'home': "Hod and Gerdur's House", 'day': 41, 'ties': []}}), encoding='utf-8')
(channel / 'conversation.json').write_text(json.dumps({'string': {'player': 'Dragonborn'}, 'int': {'day': 10}}), encoding='utf-8')

PLAYER = 'Dragonborn'
store = memory.MemoryStore(str(tmp / 'conv'), 'save1')


def npc(name, base, home='', hold='', **kw):
    d = {'name': name, 'ref_id': '00' + base, 'base_id': base, 'home': home, 'hold': hold, 'minor': 0}
    d.update(kw)
    return d

SIGRID = npc('Sigrid', '013BA1', "Alvor and Sigrid's House", 'Whiterun', sex='female')
ALVOR = npc('Alvor', '013BA0', "Alvor and Sigrid's House", 'Whiterun', sex='male')
DORTHE = npc('Dorthe', '013BA2', "Alvor and Sigrid's House", 'Whiterun', minor=1)
FAENDAL = npc('Faendal', '01A69E', 'Riverwood', 'Whiterun')
GERDUR = npc('Gerdur', '0BBB02', "Hod and Gerdur's House", 'Whiterun', home_town='Riverwood')
HOD = npc('Hod', '0BBB01', "Hod and Gerdur's House", 'Whiterun', home_town='Riverwood')
LYDIA = npc('Lydia', '0A2C94', 'Whiterun', 'Whiterun')
LEMKIL = npc('Lemkil', 'AAA001')  # place only from the Knowledge profile
BRELYNA = npc('Brelyna', 'AAA002')
NOWHERE = npc('Stranger', 'CCC001')  # nothing known about where they live


def ctx(*speakers):
    return {'speakers': list(speakers), 'people': [(s['name'], s['ref_id'][-6:]) for s in speakers], 'store': store}


def mem(s, st=None):
    st = st or store
    return memory._peek(st, s['name'], s['ref_id'][-6:])


def shown(s, st=None):
    return [e for e in mem(s, st)['recent'] if not e.get('hidden')]


def catch(s, day, *others, st=None, **extra):
    c = ctx(s, *others)
    c['with'] = [W.identify(o, c) for o in others]
    c.update(extra)
    return N.catch_up(st or store, s, day, c)

# --- helpers ------------------------------------------------------------------------------------------------------------
check('base key', [W.base_key('0x13ba1'), W.base_key('00013BA1'), W.base_key('zz')] == ['013BA1', '013BA1', ''])
check('ref key (light plugin)', [W.ref_key('FE00A802'), W.ref_key('000A2C94'), W.ref_key(0x14)] == ['000802', '0A2C94', '000014'])
check('hold names', [W.norm_hold('The Reach'), W.norm_hold('Whiterun Hold'), W.norm_hold('Rift'), W.norm_hold('Atlantis')] ==
      ['Reach', 'Whiterun', 'Rift', ''])
check('town of a place', [W.town_of_place('Sleeping Giant Inn'), W.town_of_place('Riverwood'), W.town_of_place('Bleak Falls')] ==
      ['Riverwood', 'Riverwood', ''])
me = W.identify(SIGRID, ctx(SIGRID))
check('identify: town from the home, hold from the file', (me['town'], me['hold'], me['base'], me['ref']) ==
      ('Riverwood', 'Whiterun', '013BA1', '013BA1'), me)
check('identify: Knowledge profile gives the place', (W.identify(LEMKIL, ctx(LEMKIL))['town'], W.identify(LEMKIL, ctx(LEMKIL))['hold']) == ('Rorikstead', 'Whiterun'))
check('identify: a child by profile or flag', W.identify(DORTHE, ctx(DORTHE)).get('minor') == 1)
check('jitter is fixed per npc and event', W.jitter('a', 'e1') == W.jitter('a', 'e1') and W.jitter('a', 'e1') != W.jitter('b', 'e1'))
ties = W.ties_for(W.identify(ALVOR, ctx(ALVOR)), W.load_ties())
check('ties: the other side of a tie (Alvor is Sigrid\'s spouse)', any(t['base'] == '013BA1' and t['kind'] == 'spouse' for t in ties), ties)
check('ties: same home makes a household without household ties', any(t['base'] == '0BBB01' for t in W.ties_for(W.identify(GERDUR, ctx(GERDUR)), W.load_ties())))
check('ties: none for the player', W.ties_for(W.player_person('x')) == [])

# --- size rules and classification -------------------------------------------------------------------------------------
check('classify: an outfit is not news', W.classify_text('Lydia now wears a blue dress') is None)
check('classify: a fire is big', W.classify_text("Faendal's house burned down") == ('custom', 'big'))
check('classify: a brawl is small', W.classify_text('Faendal and Sven had a brawl at the inn') == ('custom', 'small'))
check('classify: a kiss is intimate', W.classify_text('Camilla kissed the player') == ('intimate', 'small'))
check('size rules', [W.decide_size('marriage'), W.decide_size('fight', dragon=True), W.decide_size('fight', foes=2),
                     W.decide_size('death', unique=True), W.decide_size('release', came_to_light=True), W.decide_size('wipe')] ==
      ['big', 'big', 'small', 'big', 'big', 'small'])

# --- marriages.json -> log, per character ------------------------------------------------------------------------------
(channel / 'marriages.json').write_text(json.dumps({'marriages': [
    {'base': '013BA1', 'name': 'Sigrid', 'status': 'married', 'day': 10.0, 'commanded': 1, 'player': PLAYER},
    {'base': '0A2C94', 'name': 'Lydia', 'status': 'married', 'day': 9.0, 'commanded': 0, 'player': 'Someone Else'}]}), encoding='utf-8')
W.note_people(store, [W.identify(s, ctx(s)) for s in (SIGRID, ALVOR, DORTHE, FAENDAL, GERDUR, HOD, LYDIA, LEMKIL, BRELYNA)], 10)
W.ingest(store, PLAYER, [SIGRID])
evs = W.events(store)
check('marriage of this character logged once', len([e for e in evs if e['kind'] == 'marriage']) == 1, evs)
mar = next(e for e in evs if e['kind'] == 'marriage')
check('another character\'s marriage (shared file) is left out', 'Lydia' not in mar['public_text'])
check('marriage: big, strange, Riverwood, the spouse knows', (mar['size'], mar.get('strange'), mar['place']['town'], '013BA1' in mar['known']) ==
      ('big', True, 'Riverwood', True), mar)
check('marriage: true text has the command, public text not', 'Absolute Command' in mar['true_text'] and 'Command' not in mar['public_text'])
W.ingest(store, PLAYER, [SIGRID])
W._ingested.clear()
W.ingest(store, PLAYER, [SIGRID])
check('reading again adds nothing', len(W.events(store)) == len(evs))
store2 = memory.MemoryStore(str(tmp / 'conv'), 'save2')
W.ingest(store2, 'Someone Else', [])
check('per save: another save character has its own log', [e['public_text'] for e in W.events(store2)] == ['Lydia has married Someone Else.']
      and len(W.events(store)) == 1)
# an ingest that raised midway marked its file as read, so that version was never read again until it changed
store3 = memory.MemoryStore(str(tmp / 'conv'), 'save3')
real_from_marriages = W.from_marriages
W.from_marriages = lambda *a, **k: (_ for _ in ()).throw(OSError('the log is locked for a moment'))
try:
    W.ingest(store3, 'Someone Else', [])
finally:
    W.from_marriages = real_from_marriages
check('an ingest that failed midway adds nothing yet', W.events(store3) == [], W.events(store3))
W.ingest(store3, 'Someone Else', [])
check('...and the same file version is read again next time (the marriage reaches the log)',
      [e['public_text'] for e in W.events(store3)] == ['Lydia has married Someone Else.'], W.events(store3))

# --- rings and delays --------------------------------------------------------------------------------------------------
check('the spouse herself gets no news memory (she was there)', catch(SIGRID, 10.2) == [])
check('ring 2 waits about a day', catch(ALVOR, 10.5) == [])
got = catch(ALVOR, 11.3)
check('ring 2: told by the nearest tie who knew', len(got) == 1 and got[0]['how'] == 'told' and got[0]['by'] == 'Sigrid', got)
entry = next(e for e in shown(ALVOR) if e.get('key') == 'world:' + mar['id'])
check('ring 2 memory reads as told by Sigrid', memory.sourced(entry, entry['text']).startswith('Sigrid told you: Sigrid has married Dragonborn'), entry)
check('ring 2 memory dated when it reached him (day 10/11 + 1)', entry['day'] in (11, 12), entry)
check('dedupe: the same call again adds nothing', catch(ALVOR, 11.4) == [] and catch(ALVOR, 15) == [])
check('dedupe: one memory in the file', len([e for e in mem(ALVOR)['recent'] if e.get('key') == 'world:' + mar['id']]) == 1)
check('ring 3 waits 2 to 3 days', catch(FAENDAL, 11.9) == [])
got = catch(FAENDAL, 13.1)
check('ring 3: same town gets a rumour', len(got) == 1 and got[0]['how'] == 'rumour', got)
entry = next(e for e in shown(FAENDAL) if e.get('key') == 'world:' + mar['id'])
check('ring 3 wording is vaguer', memory.sourced(entry, entry['text']).startswith('You heard a rumour: people in Riverwood are saying'), entry)
check('ring 4 waits about a week', catch(LEMKIL, 15.9) == [])
got = catch(LEMKIL, 18.1)
check('ring 4: same hold, big event, hearsay', len(got) == 1 and got[0]['how'] == 'hearsay' and 'word has come from Riverwood' in got[0]['text'], got)
check('another hold never hears it', catch(BRELYNA, 30) == [])
check('a child never gets marriage news', catch(DORTHE, 30) == [])
check('unknown town: no rumour (only rings 1 and 2)', catch(NOWHERE, 30) == [])
d1 = 10.0 + N.RING3_DAYS + N.RING3_SPREAD * W.jitter('0BBB02', mar['id'], 3)
d2 = 10.0 + N.RING3_DAYS + N.RING3_SPREAD * W.jitter('0BBB01', mar['id'], 3)
check('delays differ per NPC, fixed by hash', d1 != d2 and 12 <= min(d1, d2) and max(d1, d2) < 13)

# --- knows about -------------------------------------------------------------------------------------------------------
listed = N.known_events(store, ALVOR, context=ctx(ALVOR))
check('known_events: Alvor knows it, told by Sigrid', [(x['id'], x['how'], x['by']) for x in listed] == [(mar['id'], 'told', 'Sigrid')], listed)
who = {x['name']: x['how'] for x in N.who_knows(store, mar['id'])}
check('who_knows lists everyone it reached and how', who.get('Sigrid') == 'seen' and who.get('Alvor') == 'told' and who.get('Faendal') == 'rumour'
      and who.get('Lemkil') == 'hearsay', who)

# --- wipes and scopes --------------------------------------------------------------------------------------------------
rep = N.forget_event(store, ALVOR, mar['id'], context=ctx(ALVOR))
check('forget for one NPC hides his memory of it', rep['hidden'] == 1 and not any(e.get('key') == 'world:' + mar['id'] for e in shown(ALVOR)), rep)
check('...and it is not delivered again', catch(ALVOR, 20) == [])
check('...and shows as wiped on his page', N.known_events(store, ALVOR, context=ctx(ALVOR))[0]['wiped'] is True)
back = N.undo_wipe(store, rep['wipes'][0])
check('undo gives the memory back', back == 1 and any(e.get('key') == 'world:' + mar['id'] for e in shown(ALVOR)))

rep = N.apply_wipe(store, 'town', SIGRID, event_id=mar['id'], context=ctx(SIGRID), now_day=20)
check('town wipe reaches absent townsfolk through their files', 'Faendal' in rep['targets'] and 'Alvor' in rep['targets'], rep)
check('town wipe: Faendal\'s rumour is hidden', not any(e.get('key') == 'world:' + mar['id'] for e in shown(FAENDAL)))
check('town wipe: Lemkil (outside the town) still knows', any(e.get('key') == 'world:' + mar['id'] for e in shown(LEMKIL)))
check('town wipe: a new townsperson never gets it by rumour', catch(GERDUR, 21) == [])
check('town wipe: Sigrid herself is inside', N.blocked_for(store, SIGRID, W.find(store, mar['id']), ctx(SIGRID)))
# re-entry: Lydia (Whiterun) hears it by hold rumour, then talks with Gerdur
got_l = catch(LYDIA, 19)
check('Lydia (another town of the hold) hears it', len(got_l) == 1 and got_l[0]['how'] == 'hearsay', got_l)
got = catch(GERDUR, 21.5, LYDIA)
check('re-entry: only from an outsider in the same talk, told by her', len(got) == 1 and got[0]['by'] == 'Lydia' and got[0]['ring'] == 0, got)
check('re-entry does not spread inside the wiped town by itself', catch(HOD, 25) == [])
check('re-entry: not the same outsider twice', catch(GERDUR, 26, LYDIA) == [])

rep = N.apply_wipe(store, 'everyone', LYDIA, event_id=mar['id'], context=ctx(LYDIA), now_day=27)
check('everyone who knows: all memories hidden', not any(e.get('key', '').startswith('world:' + mar['id']) for s in (LYDIA, LEMKIL, GERDUR) for e in shown(s)), rep)
OTHER = npc('Mralki', 'DDD001', 'Rorikstead', 'Whiterun', home_town='Rorikstead')
check('everyone wiped: nobody left to pass it on', catch(OTHER, 30) == [])
check('everyone wiped: Gerdur cannot get it back from Lydia', catch(GERDUR, 31, LYDIA) == [])

# --- custom events, battles, cap ----------------------------------------------------------------------------------------
from living_world import events as CE
rows = [{'id': f'r{i}', 'text': t, 'original': t, 'mode': 'narrated', 'shown': t, 'day': 41, 'hour': 9 + i, 'at': time.time() + i,
         'talk': 't', 'npcs': [{'name': 'Hod', 'ref_id': '0BBB01'}], 'status': 'active', 'remembered': []}
        for i, t in enumerate(["Faendal's house burned down", 'Hod got into a brawl with Sven', 'Hod now wears a hat',
                               'A dragon attacked Riverwood', 'Hod was robbed', 'Hod insulted the Jarl'])]
CE.save(store, rows)
W.ingest(store, PLAYER, [HOD])
logged = [e for e in W.events(store) if e['id'].startswith('ce-')]
check('custom events: news is logged, an outfit is not', len(logged) == 5 and not any('hat' in e['public_text'] for e in logged), [e['public_text'] for e in logged])
knows = lambda e, base: any(k == base or (isinstance(v, dict) and v.get('base') == base) for k, v in (e.get('known') or {}).items())
check('custom events: the people in that talk count as knowing', all(knows(e, '0BBB01') for e in logged), [list(e['known']) for e in logged])
check('custom events: place from Hod\'s file, game day from the memory day', logged[0]['place']['town'] in ('', 'Riverwood') and 40 <= logged[0]['day'] < 41)
first = catch(FAENDAL, 44)
check('cap: at most three news items per talk', len(first) == 3, first)
check('cap: the big ones first', all(W.find(store, x['id'])['size'] == 'big' for x in first[:2]), [W.find(store, x['id'])['size'] for x in first])
second = catch(FAENDAL, 44.2)
check('cap: the rest at the next talk', len(second) == 2 and not ({x['id'] for x in first} & {x['id'] for x in second}), second)
rows[4]['status'] = 'removed'
CE.save(store, rows)
W.ingest(store, PLAYER, [HOD])
check('a taken-back custom event is retracted and its news hidden', W.find(store, 'ce-r4')['retracted']
      and not any(e.get('key') == 'world:ce-r4' for e in shown(FAENDAL)))

PLAYER_REF = '00000014'
def fighter(name, ref, role, side, **kw):
    f = {'name': name, 'ref_id': ref, 'base_id': ref[-6:], 'role': role, 'side': side, 'unique': 0, 'dragon': 0, 'hostile': int(side == 1),
         'lowest': 1.0, 'dead': 0, 'down': 0, 'killer': '', 'rescued_by': [], 'kills': [], 'dealt': 10}
    f.update(kw)
    return f
fight = {'id': '777', 'active': 0, 'end': 45.5, 'seconds': 90, 'place': 'Riverwood', 'fighters': [
    fighter(PLAYER, PLAYER_REF, 'player', 0), fighter('Faendal', '0001A69E', 'ally', 0),
    fighter('Dragon', 'FF000900', 'enemy', 1, dragon=1, dead=1, killer=PLAYER_REF),
    fighter('Sven', '0001A6A1', 'bystander', 0, hostile=0, dead=1, killer=PLAYER_REF)]}
(channel / 'battles.json').write_text(json.dumps({'player': PLAYER, 'fights': [fight]}), encoding='utf-8')
W.ingest(store, PLAYER, [])
f_ev = W.find(store, 'fight-777')
k_ev = W.find(store, 'kill-777-01A6A1')
check('a dragon fight is a big fight event', f_ev is not None and f_ev['size'] == 'big' and f_ev.get('dragon'), f_ev)
check('a non-hostile killed by the player is a killing, witnessed', k_ev is not None and k_ev['size'] == 'big' and k_ev.get('player_named'), k_ev)
check('fighters count as knowing (battle.py gives their memory)', knows(f_ev, '01A69E'), f_ev['known'])

# --- reputation --------------------------------------------------------------------------------------------------------
line = R.reputation_line(LEMKIL, store, PLAYER, 60, ctx(LEMKIL))
check('reputation: built from what reached Lemkil (killing, dragon)', 'no threat' in line and 'dragon' in line and line.startswith('(What people around Whiterun'), line)
check('reputation: the wiped strange marriage does not leak to Lemkil', 'married' not in line, line)
check('reputation: nothing notable -> empty', R.reputation_line(BRELYNA, store, PLAYER, 60, ctx(BRELYNA)) == '')
SIGRID_P = W.person('Sigrid', '013BA1')
check('reputation beliefs: revealed spell and strange marriage', R.beliefs([
    {'kind': 'release', 'came_to_light': True, 'involved': [SIGRID_P, {'key': 'player'}]},
    {'kind': 'marriage', 'strange': True, 'involved': [SIGRID_P, {'key': 'player'}]}], PLAYER) ==
    ['is said to have put someone under a spell', 'has married in strange circumstances; some say the spouse was not themselves'])
check('reputation beliefs: a commanded marriage looks ordinary until that spell comes to light', R.beliefs([
    {'kind': 'marriage', 'strange': True, 'involved': [SIGRID_P, {'key': 'player'}]}], PLAYER) == [])
check('reputation: an unwitnessed killing does not name the player', R.beliefs([{'kind': 'killing', 'player_named': False}], PLAYER) == [])

(channel / 'crimes.json').write_text(json.dumps({'player': PLAYER, 'crimes': [
    {'id': 'm777', 'player': PLAYER, 'crime': 'murder', 'victim': {'ref_id': '0001A6A1', 'base': '01A6A1', 'name': 'Sven'}, 'day': 44.5,
     'place': 'Riverwood', 'witnesses': [], 'masked': 1}], 'deaths': []}), encoding='utf-8')
W.from_crimes(store, PLAYER, fights=[fight])
k_ev = W.find(store, 'kill-777-01A6A1')
check('a killing the fight logged by name is told as a hooded stranger\'s once World\'s row says a hood hid the player',
      PLAYER not in k_ev['public_text'] and 'hooded stranger' in k_ev['public_text'] and not k_ev.get('player_named')
      and PLAYER in k_ev.get('named_text', ''), k_ev)

# --- command adapters --------------------------------------------------------------------------------------------------
record = {'id': 'cmd1', 'text': 'You love me and forget Alvor', 'given': 12.0, 'until': -1, 'status': 'active', 'forget': 'Alvor',
          'npcs': [{'name': 'Sigrid', 'ref_id': '013BA1'}]}
wipe_ev = W.from_command_wipe(store, record, PLAYER, 'clean')
check('clean wipe: Hub record only, never public', wipe_ev and wipe_ev['public_text'] == '' and wipe_ev['kind'] == 'wipe')
gap_ev = W.from_command_wipe(store, dict(record, id='cmd2'), PLAYER, 'gap')
check('gap wipe: never news either (nobody knows the player did it)', gap_ev['public_text'] == '' and gap_ev['mode'] == 'gap', gap_ev['public_text'])
rel = W.from_command_release(store, record, 'aware', PLAYER, day=30)
check('release aware: came to light, she knows it, never news', rel['came_to_light'] and rel['public_text'] == ''
      and any(k.get('how') == 'own' for k in rel['known'].values()), rel)
check('leak: her own spell and wipe never reach her reputation line', 'spell' not in R.reputation_line(SIGRID, store, PLAYER, 60, ctx(SIGRID)))
check('release keep: private', W.from_command_release(store, dict(record, id='cmd3'), 'keep', PLAYER, day=30)['public_text'] == '')

# --- children never named in marriage / intimate events ----------------------------------------------------------------
check('a child is never in a marriage event', W.from_marriage(store, {'base': '013BA2', 'name': 'Dorthe', 'status': 'married', 'day': 50}, PLAYER) is None)
child_row = {'id': 'kid', 'text': 'Dorthe kissed Hod', 'day': 51, 'hour': 9, 'npcs': [{'name': 'Dorthe', 'ref_id': '013BA2'}], 'status': 'active'}
check('an intimate custom event naming a child is not logged', W.from_custom_event(store, child_row, [DORTHE], PLAYER) is None)
crime = W.from_crime(store, {'id': 'c1', 'crime': 'murder', 'victim': {'base': '0EEE01', 'name': 'Nazeem'}, 'day': 52, 'place': 'Whiterun', 'witnesses': []}, PLAYER)
check('crime without witnesses: public text does not name the player', 'Dragonborn' not in crime['public_text'] and 'Dragonborn' in crime['true_text'])

# --- day-range wipe of everything about the player --------------------------------------------------------------------
memory.add_memory(store, 'Hod', '0BBB01', 'Dragonborn bought me a mead at the inn.', day=61, hour=10)
memory.add_memory(store, 'Hod', '0BBB01', 'Talked with Gerdur about the mill.', day=63, hour=10)
rep = N.apply_wipe(store, 'npc', HOD, day_from=60, day_to=60, context=ctx(HOD), player=PLAYER, now_day=70)
texts = [e['text'] for e in shown(HOD)]
check('day range: memories of those days hidden, others kept', 'Dragonborn bought me a mead at the inn.' not in texts
      and 'Talked with Gerdur about the mill.' in texts, (rep, texts))
check('day range wipe can be undone', N.undo_wipe(store, rep['wipes'][-1]) >= 1 and 'Dragonborn bought me a mead at the inn.' in [e['text'] for e in shown(HOD)])

# --- scope parsing -----------------------------------------------------------------------------------------------------
cases = [('Forget it, and everyone in Riverwood too', ('town', 'Riverwood')), ('make everyone who was there forget', ('present', '')),
         ('Forget the wedding. Her brother too.', ('circle', '')), ('you and your brother forget this', ('circle', '')),
         ('everyone who knows forgets it', ('everyone', '')), ('the whole town forgets', ('town', '')),
         ('Forget what you saw', ('unknown', '')), ('Everyone forgets the theft', ('everyone', '')),
         ('everyone in the room forgets', ('present', '')), ('everyone here forgets', ('present', ''))]
for text, want in cases:
    got = N.parse_scope(text)
    check(f'scope: "{text}"', (got['scope'], got['town']) == want, got)
check('scope: relation kinds', N.parse_scope('your husband forgets it')['kinds'] == ['spouse'])
check('days: between', N.parse_days('everything between day 12 and 40', 50) == (12, 40))
check('days: the last three days', N.parse_days('forget the last three days', 50) == (47, 50))
check('days: none', N.parse_days('forget the theft', 50) is None)

# --- strangeness -------------------------------------------------------------------------------------------------------
cmds = [{'id': 'c9', 'text': 'You adore me', 'status': 'active', 'given': 70, 'until': -1, 'npcs': [{'name': 'Sigrid', 'ref_id': '013BA1'}]}]
c = ctx(SIGRID, ALVOR, FAENDAL)
line = S.strangeness_line(ALVOR, SIGRID, PLAYER, store, None, cmds, 71, context=c)
check('strangeness: her husband notices, plain line', line == "(Alvor knows Sigrid well, and Sigrid has not been acting like herself lately.)", line)
check('strangeness: a stranger notices nothing', S.strangeness_line(FAENDAL, SIGRID, PLAYER, store, None, cmds, 71, context=c) == '')
check('strangeness: not about someone without a command', S.strangeness_line(SIGRID, ALVOR, PLAYER, store, None, cmds, 71, context=c) == '')
mage = dict(ALVOR, magic=1, illusion=40)
check('strangeness: weaker mage senses nothing magical', 'magic' not in S.strangeness_line(dict(mage, illusion=20), SIGRID, PLAYER, store, 50, cmds, 71, context=c))
check('strangeness: equal mage senses something magical', 'something magical is off' in S.strangeness_line(dict(mage, illusion=45), SIGRID, PLAYER, store, 50, cmds, 71, context=c))
check('strangeness: much stronger mage knows who cast it', 'Illusion magic, and that Dragonborn cast it' in S.strangeness_line(dict(mage, illusion=75), SIGRID, PLAYER, store, 50, cmds, 71, context=c))
check('strangeness: ...but not the name of a hooded caster she does not know', 'and that the hooded stranger cast it' in S.strangeness_line(
    dict(mage, illusion=75), SIGRID, PLAYER, store, 50, cmds, 71, context=c, knows=lambda o: False))
check('strangeness: no skill data -> plain line', S.strangeness_line(mage, SIGRID, PLAYER, store, None, cmds, 71, context=c) == line)
check('strangeness: a worn-off command is not seen', S.strangeness_line(ALVOR, SIGRID, PLAYER, store, None, [dict(cmds[0], until=70.5)], 71, context=c) == '')
check('strangeness: a plain task is not an enchantment', not S.is_enchantment({'text': 'Go to Whiterun and wait at the gate'}))
check('strangeness: a child observer gets nothing', S.strangeness_line(DORTHE, SIGRID, PLAYER, store, None, cmds, 71, context=ctx(DORTHE, SIGRID)) == '')
for i in range(5):
    memory.add_memory(store, 'Faendal', '01A69E', f'Sigrid and I talked about the river {i}.', day=60, hour=i)
check('strangeness: enough shared memories count as knowing her well', S.strangeness_line(FAENDAL, SIGRID, PLAYER, store, None, cmds, 71, context=c) != '')
check('strangeness: absent tie after a day', S.strangeness_line(ALVOR, SIGRID, PLAYER, store, None, cmds, 72, present=False, context=c) != ''
      and S.strangeness_line(ALVOR, SIGRID, PLAYER, store, None, cmds, 70.5, present=False, context=c) == '')
lines = S.text(store, [ALVOR, SIGRID], PLAYER, now=71, commands=cmds)
check('strangeness.text for a talk', 'Alvor knows Sigrid well' in lines, lines)

# --- more leak checks ---------------------------------------------------------------------------------------------------
rep = N.forget_event(store, LEMKIL, 'kill-777-01A6A1', context=ctx(LEMKIL))
line = R.reputation_line(LEMKIL, store, PLAYER, 60, ctx(LEMKIL))
check('leak: a killing wiped for Lemkil is gone from his reputation line', 'no threat' not in line and 'dragon' in line, line)
both = R.text(store, [SimpleNamespace(name='Lemkil', ref_id='AAA001'), SimpleNamespace(name='Brelyna', ref_id='AAA002')], PLAYER, 60, [LEMKIL, BRELYNA])
check('reputation.text: one NPC with a line in a group says it is theirs', 'only Lemkil has heard this.)' in both and 'Brelyna' not in both, both)
rep = N.apply_wipe(store, 'present', HOD, event_id='ce-r0', context=ctx(HOD), now_day=46)
check('present scope covers those named in it too (Faendal) and those there (Hod)', {'Faendal', 'Hod'} <= set(rep['targets']), rep)
check('...and neither is told again', not any(x['id'] == 'ce-r0' for x in catch(FAENDAL, 47) + catch(HOD, 47)))
check('known_events shows it as wiped for Faendal', next(x for x in N.known_events(store, FAENDAL, context=ctx(FAENDAL)) if x['id'] == 'ce-r0')['wiped'])
mid = N.tell_event(store, FAENDAL, 'ce-r0', told_by='Gerdur', now_day=48, context=ctx(FAENDAL))
check('the Hub user can tell him again (re-entry by hand)', bool(mid) and not next(x for x in N.known_events(store, FAENDAL, context=ctx(FAENDAL)) if x['id'] == 'ce-r0')['wiped'])
check('a retracted event is never told', N.tell_event(store, FAENDAL, 'ce-r4', now_day=48, context=ctx(FAENDAL)) == '')

# --- a command's scope in one call --------------------------------------------------------------------------------------
check('find_events by the forget words', [e['id'] for e in N.find_events(store, 'the brawl with Sven')] == ['ce-r1'])
rec = {'id': 'cx', 'text': 'Forget the brawl with Sven, and everyone in Riverwood too', 'forget': 'the brawl with Sven',
       'npcs': [{'name': 'Hod', 'ref_id': '0BBB01'}]}
out = N.apply_command_scope(store, rec, PLAYER, [HOD], 50)
check('command scope: town wipe of the matching event', out and out['scope'] == 'town' and out['events'] == ['ce-r1'], out)
check('command scope: Faendal (absent, same town) lost it too', not any(e.get('key') == 'world:ce-r1' for e in shown(FAENDAL)))
check("command scope: plain words -> None (today's behaviour)", N.apply_command_scope(store, dict(rec, text='Forget the brawl'), PLAYER, [HOD], 50) is None)
N._talks.clear()
check('talk_start acts once per talk', N._new_talk(store, [HOD]) and not N._new_talk(store, [HOD]))

# --- talk_start wrapper, missing files ---------------------------------------------------------------------------------
os.remove(channel / 'ties.json')
check('ties missing: ring 2 falls back, nothing raises', isinstance(N.talk_start(store, [SimpleNamespace(name='Hod', ref_id='0BBB01', base_id='0BBB01')], 80,
                                                                                    {'speakers': [HOD]}, force=True), int))
empty = memory.MemoryStore(str(tmp / 'conv'), 'save3')
check('no log: catch_up returns nothing', N.catch_up(empty, HOD, 10, ctx(HOD)) == [])
check('no store: nothing', N.catch_up(None, HOD, 10) == [] and N.talk_start(None, [HOD]) == 0 and R.reputation_line(HOD, None) == '')
for junk in (None, {}, {'name': 1}, SimpleNamespace(name=None, ref_id=None)):
    try:
        N.catch_up(store, junk, 10, {})
        N.known_events(store, junk)
        S.strangeness_line(junk, junk, PLAYER, store, None, cmds, 10)
        ok = True
    except Exception as e:
        ok = False
        print(e)
    check(f'junk never raises ({str(junk)[:30]})', ok)
(Path(store.root) / 'world' / 'log.json').write_text('{broken', encoding='utf-8')
check('a broken log file reads as empty', W.events(store) == [] and N.catch_up(store, HOD, 90, ctx(HOD)) == [])

# --- same-named NPCs (guards): matched by reference id, then base id; a name only when one side has no id -------------
gst = memory.MemoryStore(str(tmp / 'conv'), 'guards')
GUARD_A = npc('Whiterun Guard', '0AAAAA', '', 'Whiterun', ref_id='000011AA')
GUARD_B = npc('Whiterun Guard', '0BBBBB', '', 'Whiterun', ref_id='000022BB')  # another post, another base
GUARD_C = npc('Whiterun Guard', '0AAAAA', '', 'Whiterun', ref_id='000033CC')  # the same base as A, another person
for g in (GUARD_A, GUARD_B, GUARD_C):
    g['home_town'] = 'Whiterun'
kill = W.log_event(gst, 'killing', 'Dragonborn killed Heimskr.', 'Someone killed Heimskr.', 30.0,
                   {'location': 'Whiterun', 'town': 'Whiterun', 'hold': 'Whiterun'},
                   present=[W.person(GUARD_A['name'], GUARD_A['base_id'], GUARD_A['ref_id'])], size='big')
got_b = N.catch_up(gst, GUARD_B, 30.1, ctx(GUARD_B))
check('guards: another same-named guard (other base, other ref) did not see it', not any(d['ring'] == 1 for d in got_b), got_b)
got_c = N.catch_up(gst, GUARD_C, 30.1, ctx(GUARD_C))
check('guards: a guard with the same base but another ref did not see it', not any(d['ring'] == 1 for d in got_c), got_c)
got_a = N.catch_up(gst, GUARD_A, 30.1, ctx(GUARD_A))
check('guards: the guard who was there saw it', any(d['ring'] == 1 and d['how'] == 'seen' for d in got_a), got_a)
known = W.find(gst, kill['id'])['known']
check('guards: the known mark is his alone (by reference id)', list(known) == ['r0011AA'], known)
check('guards: the same-base guard is not counted as knowing', N.known_events(gst, GUARD_C, context=ctx(GUARD_C)) == [])
check('ident_match: refs decide, then bases, a name only without ids',
      W.ident_match({'r:000001', 'b:0AAAAA', 'n:x'}, {'r:000001'}) and not W.ident_match({'r:000001', 'b:0AAAAA'}, {'r:000002', 'b:0AAAAA'})
      and W.ident_match({'b:0AAAAA', 'n:x'}, {'r:000002', 'b:0AAAAA'}) and not W.ident_match({'r:000001', 'n:x'}, {'b:0AAAAA', 'n:x'})
      and W.ident_match({'r:000001', 'n:x'}, {'n:x'}) and not W.same(W.person('G', '0AAAAA', '000001'), W.person('G', '0AAAAA', '000002')))
rep = N.forget_event(gst, GUARD_A, kill['id'], context=ctx(GUARD_A))
check('guards: a wipe for one guard does not block the same-base guard', not N.blocked_for(gst, GUARD_C, W.find(gst, kill['id']), context=ctx(GUARD_C))
      and N.blocked_for(gst, GUARD_A, W.find(gst, kill['id']), context=ctx(GUARD_A)), W.find(gst, kill['id']).get('wipes'))
W.note_people(gst, [W.identify(g, ctx(g)) for g in (GUARD_A, GUARD_C)], 30)
people = W.read_people(gst)
check('people: two guards with one base id keep two entries', sorted(e.get('ref') for e in people.values()) == ['0011AA', '0033CC'], people)
check('people: lookup finds each by reference id', W.lookup(people, W.person('Whiterun Guard', '0AAAAA', '000033CC'))['ref'] == '0033CC')
nameonly = W.log_event(gst, 'custom', 'Hulda slapped Ysolda.', 'Hulda slapped Ysolda.', 31.0, {'town': 'Whiterun', 'hold': 'Whiterun'},
                       present=[{'name': 'Whiterun Guard'}], size='small')
check('a person logged by name only still matches by name', any(d['id'] == nameonly['id'] and d['ring'] == 1 for d in N.catch_up(gst, GUARD_B, 31.1, ctx(GUARD_B))))

# --- a speaker the game has not confirmed as an adult gets no marriage news (fail closed) -----------------------------
ust = memory.MemoryStore(str(tmp / 'conv'), 'unknown_age')
wed = W.log_event(ust, 'marriage', 'Ysolda has married Dragonborn.', 'Ysolda has married Dragonborn.', 40.0,
                  {'town': 'Whiterun', 'hold': 'Whiterun'}, present=[W.person('Braith', '0CCCC1', '000CCCC1')], size='big')
nofile = {'name': 'Braith', 'ref_id': '000CCCC1', 'base_id': '0CCCC1'}  # in the talk, no minor key yet
check('unknown age: no marriage news while the game has not confirmed an adult', N.catch_up(ust, nofile, 40.1, ctx(nofile)) == [])
check('unknown age: not told by hand either', N.tell_event(ust, nofile, wed['id'], now_day=40.2, context=ctx(nofile)) == '')
check('unknown age: no strangeness line as observer', S.strangeness_line(nofile, SIGRID, PLAYER, ust, None, [], 40, context=ctx(nofile, SIGRID)) == '')
adult_now = dict(nofile, minor=0)
check('once the game says adult, the next talk has it', len(N.catch_up(ust, adult_now, 41.1, ctx(adult_now))) == 1)
check('the unknown flag is never stored', not any(e.get('unconfirmed') for e in W.read_people(ust).values()))

# --- performance: 500 events, 200 NPCs ---------------------------------------------------------------------------------
perf = memory.MemoryStore(str(tmp / 'conv'), 'perf')
towns = ['Riverwood', 'Whiterun', 'Rorikstead', 'Winterhold']
people = [npc(f'Person{i}', f'F{i:05X}', towns[i % 4], 'Whiterun' if i % 4 < 3 else 'Winterhold', home_town=towns[i % 4]) for i in range(200)]
def build(log):
    for i in range(500):
        p = people[i % 200]
        log['events'].append({'id': f'p{i}', 'kind': 'custom', 'day': float(i % 50), 'place': {'location': '', 'town': towns[i % 4],
                              'hold': 'Whiterun' if i % 4 < 3 else 'Winterhold'}, 'involved': [W.person(p['name'], p['base_id'])],
                              'present': [W.person(p['name'], p['base_id'])], 'true_text': f'Event {i} happened.',
                              'public_text': f'Event {i} happened.', 'size': 'big' if i % 10 == 0 else 'small', 'importance': 0.5,
                              'wipes': [], 'known': {p['base_id']: {'how': 'seen', 'since': float(i % 50), 'name': p['name'], 'ref': p['base_id']}},
                              'retracted': False})
    return True
W.change_log(perf, build)
W.note_people(perf, [W.identify(p, {'speakers': [p]}) for p in people], 50)
start = time.time()
total = 0
for p in people:
    total += len(N.catch_up(perf, p, 52, {'speakers': [p], 'people': [(p['name'], p['ref_id'][-6:])]}))
spent = time.time() - start
print(f'  perf: 200 NPCs x 500 events: {spent:.1f}s, {total} memories added')
check('performance: 200 NPCs caught up on 500 events in reasonable time', spent < 120 and total <= 600, spent)
start = time.time()
for p in people:
    N.catch_up(perf, p, 52, {'speakers': [p], 'people': [(p['name'], p['ref_id'][-6:])]})
check('performance: a second pass the same hour is near free', time.time() - start < 5, time.time() - start)
start = time.time()
R.reputation_line(people[0], perf, PLAYER, 52, {'speakers': [people[0]]})
check('performance: reputation for one NPC under a second', time.time() - start < 1.0, time.time() - start)

print(f'\n{len(FAILS)} failed' if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
