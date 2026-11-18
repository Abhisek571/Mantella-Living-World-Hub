"""Offline tests for battle accounts (server/living_world/battle.py, with lw_state.load_battles and the hooks in
living_world/__init__.py). The fights are shaped like World's battles.json.
Run with a Python 3.11: test_battle.py <repo server dir>"""
import copy, json, os, sys, tempfile, time
from pathlib import Path
from types import SimpleNamespace

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
import living_world
from living_world import battle as B, lw_state, memory

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)

REF = living_world._ref
PLAYER, LYDIA, FAENDAL, ATRONACH = '00000014', '000A2C94', '0001A69E', 'FF000801'
CHIEF, BANDIT1, BANDIT2, BANDIT3, MAGE, YSOLDA = 'FF000810', 'FF000811', 'FF000812', 'FF000813', 'FF000814', '00013BAB'


def fighter(name, ref, role, side, **kw):
    f = {'name': name, 'ref_id': ref, 'base_id': ref[-6:], 'role': role, 'side': side, 'unique': 0, 'dragon': 0, 'hostile': int(side == 1),
         'lowest': 1.0, 'health': 1.0, 'dealt': 0, 'taken': 0, 'down': 0, 'dead': 0, 'owner': '', 'killer': '', 'danger_by': '',
         'rescued_by': [], 'harm': {}, 'help': {}, 'kills': []}
    f.update(kw)
    return f


FIGHT = {'id': '1731560000000', 'active': 0, 'in_prompt': 1, 'start': 41.6, 'end': 41.625, 'seconds': 130, 'place': 'Riverwood',
         'fighters': [
             fighter('Dragonborn', PLAYER, 'player', 0, lowest=0.7, dealt=300, kills=[CHIEF]),
             fighter('Lydia', LYDIA, 'party', 0, lowest=0.0, down=1, dealt=100, danger_by=CHIEF, kills=[BANDIT1],
                     rescued_by=[{'ref': PLAYER, 'how': 'heal'}], harm={'fire': [MAGE], 'slow': [MAGE]}, help={'healing': [PLAYER]}),
             fighter('Faendal', FAENDAL, 'ally', 0, lowest=0.95, dealt=20, kills=[BANDIT2]),
             fighter('Flame Atronach', ATRONACH, 'summon', 0, owner=PLAYER, dealt=80, kills=[]),
             fighter('Bandit Chief', CHIEF, 'enemy', 1, unique=0, dead=1, lowest=0.0, killer=PLAYER, dealt=150),
             fighter('Bandit', BANDIT1, 'enemy', 1, dead=1, lowest=0.0, killer=LYDIA),
             fighter('Bandit', BANDIT2, 'enemy', 1, dead=1, lowest=0.0, killer=FAENDAL),
             fighter('Bandit', BANDIT3, 'enemy', 1, lowest=0.4, health=0.4),
             fighter('Bandit Mage', MAGE, 'enemy', 1, lowest=0.2, health=0.5),
         ]}
TODAY = 41
LYDIA_ME = B.find(FIGHT, REF(LYDIA), REF)

# --- words -----------------------------------------------------------------------------------------------------------
check('hurt words', [B.hurt({'dead': 1}), B.hurt({'down': 1}), B.hurt({'lowest': 0.1}), B.hurt({'lowest': 0.2}), B.hurt({'lowest': 0.5}),
                     B.hurt({'lowest': 0.8}), B.hurt({'lowest': 0.95}), B.hurt({})] ==
      ['killed', 'went down', 'nearly killed', 'badly hurt', 'hurt', 'lightly hurt', 'unhurt', 'unhurt'])
check('share words', [B.share(60, 100), B.share(30, 100), B.share(10, 100), B.share(1, 100), B.share(0, 100), B.share(5, 0)] ==
      ['most of the fighting', 'a good share of the fighting', 'some of the fighting', 'a little of the fighting', 'none of the fighting', ''])
check('length words', [B.length(5, False), B.length(40, False), B.length(80, False), B.length(130, False), B.length(40, True)] ==
      ['a few seconds', 'under a minute', 'about a minute', 'about 2 minutes', 'under a minute so far'])
check('when: same day, afternoon', B.when(FIGHT, TODAY) == 'earlier today, in the afternoon', B.when(FIGHT, TODAY))
check('when: yesterday', B.when(FIGHT, TODAY + 1) == 'yesterday in the afternoon')
check('when: going on now', B.when(dict(FIGHT, active=1), TODAY) == 'going on now')
check('a summon\'s damage counts for its owner', B.dealt(FIGHT)[PLAYER] == 380 and ATRONACH not in B.dealt(FIGHT), B.dealt(FIGHT))

# --- a fighter's account -------------------------------------------------------------------------------------------
text = B.account(FIGHT, LYDIA_ME, TODAY)
print(text)
lines = text.splitlines()
check('header: who, where, when, how long', lines[0] == "Lydia's own account of a fight at Riverwood (earlier today, in the afternoon, about 2 minutes); this is what really happened:", lines[0])
check('own side, player first, then you, with hurt and share in words',
      lines[1] == '- Your side: Dragonborn (lightly hurt; most of the fighting), you (went down; some of the fighting), Faendal (unhurt; a little of the fighting).', lines[1])
check('enemies grouped by name, killer named, survivors with how hurt',
      lines[2] == '- Against you: Bandit Chief (killed by Dragonborn), Bandit ×3 (2 killed, 1 survived), Bandit Mage (survived, badly hurt).', lines[2])
check('summons are not listed as fighters', 'Atronach' not in text)
check('kills: final blow, the player\'s set apart',
      '- Kills: Dragonborn killed Bandit Chief; others: you killed Bandit; Faendal killed Bandit.' in lines, lines)
check('close call with whose blows and the rescue',
      "- Close calls: you went down from Bandit Chief's blows; Dragonborn saved you with a heal." in lines, lines)
check('harmful magic by caster', '- Magic put on you: fire and slow from Bandit Mage.' in lines, lines)
check('help received', '- Help you got: healing from Dragonborn.' in lines, lines)
import re
check('no numbers in the account but head counts and minutes', not re.search(r'\d', re.sub(r'×\d+|\(\d+ killed|\d+ survived|about \d+ minutes', '', text)), text)
check('account stays short (one NPC, one fight)', memory.tokens(text) <= 180, memory.tokens(text))

# rescue by killing the attacker
killed = copy.deepcopy(FIGHT)
killed['fighters'][1]['rescued_by'] = [{'ref': FAENDAL, 'how': 'kill'}]
check('rescue by a kill names who was killed',
      "you went down from Bandit Chief's blows; Faendal saved you by killing Bandit Chief" in B.account(killed, B.find(killed, REF(LYDIA), REF), TODAY))

# the player's own close call, told to someone else
low = copy.deepcopy(FIGHT)
low['fighters'][0].update(lowest=0.1, danger_by=MAGE, rescued_by=[{'ref': LYDIA, 'how': 'kill'}])
check("the player's close call, and the listener's rescue of them",
      "Dragonborn nearly died from Bandit Mage's blows; you saved them by killing Bandit Mage" in B.account(low, B.find(low, REF(LYDIA), REF), TODAY))

# the other side's view: a surviving bandit
bandit = B.find(FIGHT, REF(BANDIT3), REF)
other = B.account(FIGHT, bandit, TODAY)
check('an enemy gets the fight from their side', '- Your side: you (hurt; none of the fighting), Bandit Chief (killed; most of the fighting), Bandit ×2 (2 killed)' in other, other)
check('...and the player is against them', '- Against you: Dragonborn' in other, other)

# a big fight stays bounded
big = copy.deepcopy(FIGHT)
big['fighters'] += [fighter(f'Draugr {i}', f'FF0009{i:02d}', 'enemy', 1, dead=1, killer=PLAYER, unique=1) for i in range(30)]
big['fighters'][0]['kills'] += [f'FF0009{i:02d}' for i in range(30)]
check('a big fight is cut, not endless', 'more' in B.account(big, B.find(big, REF(LYDIA), REF), TODAY))

# --- bystanders, the prompt ------------------------------------------------------------------------------------------
seen = copy.deepcopy(FIGHT)
seen['fighters'].append(fighter('Ysolda', YSOLDA, 'bystander', 0))
witness = B.witness_line(seen, B.find(seen, REF(YSOLDA), REF), TODAY)
check('bystander: one short line', witness == 'Ysolda saw a fight at Riverwood (earlier today, in the afternoon): Dragonborn, Lydia and Faendal against '
      'Bandit Chief, Bandit ×3, Bandit Mage. Dead: Bandit Chief, Bandit ×2.', witness)
check('bystanders named in a fighter\'s account', '- Also there, not fighting: Ysolda.' in B.account(seen, B.find(seen, REF(LYDIA), REF), TODAY))

speakers = [{'name': 'Lydia', 'ref_id': LYDIA}]
one = B.prompt_text(speakers, [FIGHT], TODAY, REF)
check('one NPC: their account, no group label', one == B.account(FIGHT, LYDIA_ME, TODAY), one)
group = B.prompt_text([{'name': 'Lydia', 'ref_id': LYDIA}, {'name': 'Ysolda', 'ref_id': YSOLDA}, {'name': 'Hod', 'ref_id': '00013BA3'}], [seen], TODAY, REF)
check('group: a block each, each said to be theirs alone', group.count('(Only ') == 2 and '(Only Lydia knows this' in group and 'Ysolda saw a fight' in group, group)
check('someone not in the fight gets nothing', 'Hod' not in group)
check('a fight out of the prompt is not told', B.prompt_text(speakers, [dict(FIGHT, in_prompt=0)], TODAY, REF) == '')
check('at most two fights per NPC', B.prompt_text(speakers, [FIGHT, dict(FIGHT, id='2'), dict(FIGHT, id='3')], TODAY, REF).count('own account') == 2)
check('in a group, one fight each', B.prompt_text(speakers + [{'name': 'Hod', 'ref_id': '00013BA3'}], [FIGHT, dict(FIGHT, id='2')], TODAY, REF).count('own account') == 1)
check('Mantella\'s short reference matches the game\'s full one', B.prompt_text([{'name': 'Lydia', 'ref_id': 'A2C94'}], [FIGHT], TODAY, REF) != '')
live = dict(FIGHT, active=1)
check('a fight going on is told as such', 'going on now, about 2 minutes so far' in B.prompt_text(speakers, [live], TODAY, REF))

# --- worth remembering --------------------------------------------------------------------------------------------
calm = copy.deepcopy(FIGHT)
calm['fighters'] = [fighter('Dragonborn', PLAYER, 'player', 0, lowest=0.8), fighter('Lydia', LYDIA, 'party', 0, lowest=0.9),
                    fighter('Wolf', 'FF000820', 'enemy', 1, dead=1, killer=PLAYER)]
calm['seconds'] = 8
check('a close call is memorable', B.memorable(FIGHT))
check('a quick fight against one wolf is not', not B.memorable(calm))
check('a named enemy is', B.memorable({**calm, 'fighters': calm['fighters'][:2] + [fighter('Hrothmund', 'FF000821', 'enemy', 1, unique=1)]}))
check('a dragon is', B.memorable({**calm, 'fighters': calm['fighters'][:2] + [fighter('Dragon', 'FF000822', 'enemy', 1, dragon=1)]}))
check('a long fight against three is', B.memorable({**calm, 'seconds': 40, 'fighters': calm['fighters'] + [fighter('Wolf', f'FF00083{i}', 'enemy', 1) for i in range(2)]}))
check('a fight still going on is not remembered yet', not B.memorable(live))
check('no enemy, no fight', not B.memorable({**FIGHT, 'fighters': FIGHT['fighters'][:3]}))

line = B.memory_line(FIGHT, LYDIA_ME)
print(line)
check('memory line: sides, deaths, own part, close call and kills, no date',
      line.startswith('Fight at Riverwood, about 2 minutes: you, Dragonborn and Faendal against Bandit Chief, Bandit ×3, Bandit Mage. Dead: Bandit Chief, Bandit ×2. '
                      'You: went down; some of the fighting.') and "Bandit Chief's blows; Dragonborn saved you with a heal." in line
      and 'Dragonborn killed Bandit Chief' in line and 'Day' not in line, line)
check('memory line for a bystander', B.memory_line(seen, B.find(seen, REF(YSOLDA), REF)).startswith('Saw a fight at Riverwood: Dragonborn, Lydia and Faendal against'))

# --- remembering -----------------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    store = memory.MemoryStore(tmp, 'Dragonborn')
    lydia = SimpleNamespace(name='Lydia', ref_id='A2C94')
    old = memory.empty()
    old['recent'] = [{'day': 41, 'hour': 9, 'text': 'Talked about the weather.', 'witnesses': ['Lydia']},
                     {'day': 43, 'hour': 10, 'text': 'Talked about the fight.', 'witnesses': ['Lydia']}]
    store.save('Lydia', 'A2C94', old)
    check('still in the prompt: not remembered at a talk\'s start', B.remember(store, [lydia], [FIGHT], REF, at_end=False) == 0)
    check('a calm fight is never remembered', B.remember(store, [lydia], [dict(calm, in_prompt=0)], REF, at_end=True) == 0)
    check('at a talk\'s end it is', B.remember(store, [lydia], [FIGHT], REF, at_end=True) == 1)
    mem = store.load('Lydia', 'A2C94')
    entry = next(e for e in mem['recent'] if e.get('battle'))
    check('one entry, dated by the game clock (Mantella day = game day + 1), the fight\'s id kept',
          entry['day'] == 42 and entry['hour'] == 15 and entry['battle'] == FIGHT['id'] and entry['witnesses'] == ['Lydia'], entry)
    check('placed in time order, before a later talk', [e['text'][:12] for e in mem['recent']] == ['Talked about', 'Fight at Riv', 'Talked about'], mem['recent'])
    check('never twice', B.remember(store, [lydia], [FIGHT, dict(FIGHT, in_prompt=0)], REF, at_end=True) == 0)
    check('a fight is no talk', memory._player_talks(store.load('Lydia', 'A2C94')) == 2)
    rendered = memory.render(store.load('Lydia', 'A2C94'))
    check('shown in their memory with its date', '[Day 42, 3 in the afternoon] Fight at Riverwood' in rendered, rendered)
    hod = SimpleNamespace(name='Hod', ref_id='13BA3')
    check('someone who was not there gets nothing', B.remember(store, [hod], [FIGHT], REF, at_end=True) == 0 and not (Path(tmp) / 'Dragonborn' / 'living_world' / 'Hod - 13BA3.json').exists())
    check('out of the prompt: remembered at the next talk\'s start',
          B.remember(store, [SimpleNamespace(name='Faendal', ref_id='1A69E')], [dict(FIGHT, in_prompt=0)], REF, at_end=False) == 1)

# --- the file, and the hooks ----------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)
    lw_state.DATA_DIR = tmp
    check('no file: no fights', lw_state.load_battles() == [])
    (data / 'battles.json').write_text('{"fights": [', encoding='utf-8')
    check('half-written file: no fights', lw_state.load_battles() == [])
    (data / 'battles.json').write_text(json.dumps({'player': 'Dragonborn', 'fights': [FIGHT, 'junk', None]}), encoding='utf-8')
    (data / 'conversation.json').write_text(json.dumps({'string': {'player': 'Dragonborn'}, 'int': {'day': TODAY}, 'stringList': {'speakers': ['0A2C94']}}), encoding='utf-8')
    (data / 'npc').mkdir()
    (data / 'npc' / '0A2C94.json').write_text(json.dumps({'string': {'name': 'Lydia', 'ref_id': LYDIA}}), encoding='utf-8')
    check('fights read, junk dropped', lw_state.load_battles() == [FIGHT])
    (data / 'battles.json').write_text(json.dumps({'player': 'Someone Else', 'fights': [FIGHT]}), encoding='utf-8')
    _now = time.time()
    os.utime(data / 'battles.json', (_now - 60, _now - 60))
    os.utime(data / 'conversation.json', (_now, _now))  # the talk file was written after: this character is current
    check("another character's fights are not read", lw_state.load_battles() == [])
    # live test 5: the first talk after loading Brom's save; conversation.json still names the character of an earlier
    # session (written before the load), battles.json was rewritten for Brom right after the load
    (data / 'battles.json').write_text(json.dumps({'player': 'Brom', 'fights': [FIGHT]}), encoding='utf-8')
    (data / 'conversation.json').write_text(json.dumps({'string': {'player': 'Prisonerdax'}, 'int': {'day': TODAY}, 'stringList': {'speakers': ['0A2C94']}}), encoding='utf-8')
    os.utime(data / 'conversation.json', (_now - 3600, _now - 3600))
    os.utime(data / 'battles.json', (_now - 60, _now - 60))
    check('stale conversation file (earlier character): the newer battles file names the player, fights kept',
          lw_state.load_player_name() == 'Brom' and lw_state.load_battles() == [FIGHT], (lw_state.load_player_name(), lw_state.load_battles()))
    (data / 'world.json').write_text(json.dumps({'player': 'Brom', 'day': TODAY}), encoding='utf-8')
    os.utime(data / 'world.json', (_now - 30, _now - 30))
    check('stale conversation file: world.json of the current character is not left out', lw_state.load_world().get('player') == 'Brom')
    (data / 'world.json').write_text(json.dumps({'player': 'Prisonerdax', 'loading': 1}), encoding='utf-8')
    os.utime(data / 'world.json', (_now - 10, _now - 10))
    check('a newer world.json still loading (previous character in it) does not name the player', lw_state.load_player_name() == 'Brom'
          and lw_state.load_battles() == [FIGHT], lw_state.load_player_name())
    (data / 'world.json').unlink()
    (data / 'conversation.json').unlink()
    check('player not known at all: nothing is dropped', lw_state.load_player_name() == 'Brom' and lw_state.load_battles() == [FIGHT])
    (data / 'battles.json').write_text(json.dumps({'player': '', 'fights': [FIGHT]}), encoding='utf-8')
    check('no name anywhere: fights kept', lw_state.load_player_name() == '' and lw_state.load_battles() == [FIGHT])
    (data / 'conversation.json').write_text(json.dumps({'string': {'player': 'Dragonborn'}, 'int': {'day': TODAY}, 'stringList': {'speakers': ['0A2C94']}}), encoding='utf-8')
    os.utime(data / 'conversation.json', (_now, _now))
    (data / 'battles.json').write_text(json.dumps({'player': 'Dragonborn', 'fights': [FIGHT]}), encoding='utf-8')
    real_installed = living_world._installed
    try:
        living_world._installed = lambda: {'World'}
        extra = living_world._extra_text({'messages': []})
        check('newest message carries the account with World installed', "Lydia's own account of a fight at Riverwood" in extra, extra)
        living_world._installed = lambda: set()
        check('without World nothing is told (a stale file stays quiet)', 'account of a fight' not in living_world._extra_text({'messages': []}))
    finally:
        living_world._installed = real_installed
    # junk never raises
    for junk in (None, [], [None], [{'fighters': None, 'in_prompt': 1}], [{'fighters': [{'name': 1}], 'in_prompt': 1}],
                 [{'in_prompt': 1, 'fighters': [{'name': 'Lydia', 'ref_id': LYDIA, 'side': 'x', 'lowest': 'low', 'kills': 'all', 'harm': [], 'rescued_by': [None]}]}]):
        try:
            B.prompt_text(speakers, junk, TODAY, REF)
            B.remember(memory.MemoryStore(tmp, 'w'), [SimpleNamespace(name='Lydia', ref_id=LYDIA)], junk, REF, True)
            ok = True
        except Exception as e:
            ok = False
            print(e)
        check(f'junk fights never raise ({str(junk)[:40]})', ok)

# live test 9: drain and slow from the player on Lira (party) were still in battles.json after the plugin's cast check.
# The player's magic on a member of their own party is never told to that follower as an attack, also when the record
# puts her on the other side (then the same-side check alone would tell it).
LIRA, WOLF, SKEL, NECRO = 'FE25C80E', 'FF002150', 'FF002151', 'FF002152'
off_sides = {'id': '1794746699717', 'active': 1, 'in_prompt': 1, 'start': 0.69, 'end': 0.76, 'seconds': 313,
             'place': "Alvor and Sigrid's House", 'fighters': [
                 fighter('Brom', PLAYER, 'player', 0, dealt=23, kills=[WOLF]),
                 fighter('Lira', LIRA, 'party', 1, harm={'drain': [PLAYER], 'slow': [PLAYER]}),
                 fighter('Wolf', WOLF, 'enemy', 1, dead=1, lowest=0.0, killer=PLAYER, taken=23, harm={'drain': [PLAYER]})]}
lira = next(f for f in B.fighters(off_sides) if f['name'] == 'Lira')
told = B.account(off_sides, lira, TODAY)
check('player magic on a follower recorded on the other side: not told to her as an attack', 'Magic put on you' not in told
      and 'from Brom' not in told, told)
check('...and the player counts as an area caster for that fight', PLAYER in B.area_casters(off_sides), B.area_casters(off_sides))
own_summon = {'fighters': [fighter('Brom', PLAYER, 'player', 0), fighter('Atronach', ATRONACH, 'summon', 1, owner=PLAYER, harm={'frost': [PLAYER]})]}
check("the player's own summon counts as party", PLAYER in B.area_casters(own_summon))
enemy_summon = {'fighters': [fighter('Brom', PLAYER, 'player', 0), fighter('Necromancer', NECRO, 'enemy', 1),
                             fighter('Skeleton', SKEL, 'summon', 1, owner=NECRO, harm={'frost': [PLAYER]})]}
check("an enemy's summon is no party: the player's frost on it is a real spell", PLAYER not in B.area_casters(enemy_summon))
real_9 = os.path.join(os.environ.get('MLW_EVIDENCE', ''), r'lw-live-test-9-2026-11-15\test-artifacts\overwrite-StorageUtilData-MLW\battles.json')
if os.path.isfile(real_9):
    fight9 = json.load(open(real_9, encoding='utf-8'))['fights'][0]
    lira9 = next(f for f in B.fighters(fight9) if f['name'] == 'Lira')
    check('real battles.json (live test 9): Lira is not told the player put drain and slow on her',
          'Magic put on you' not in B.account(fight9, lira9, None), B.account(fight9, lira9, None))
else:
    print(f'SKIP live test 9 battles.json: {real_9} not found')

print(f'\n{len(FAILS)} failed' if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
