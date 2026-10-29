"""Offline tests for what NPCs know of the player's standing (server/living_world/world_note.py).
Run with a Python 3.11: test_world_note.py <repo server dir>"""
import sys
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import world_note as W

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)

world = {'hold': 'Whiterun', 'player': 'CHAD',
         'fame': {'Whiterun': 5, 'Reach': 0, 'Rift': 8}, 'bounty': {'Whiterun': 40, 'Reach': 1500}, 'bounty_violent': {'Whiterun': 0, 'Reach': 1000},
         'events': [{'id': 'thane_whiterun', 'text': 'CHAD is Thane of Whiterun.', 'holds': ['Whiterun'], 'factions': [], 'named': []},
                    {'id': 'tg01_thieves_guild', 'text': 'CHAD works for the Thieves Guild in Riften.', 'holds': [], 'factions': ['Thieves Guild'], 'named': []},
                    {'id': 'mq104_dragonborn', 'text': 'CHAD killed a dragon.', 'holds': ['all'], 'factions': [], 'named': []},
                    {'id': 'ms13_golden_claw', 'text': 'CHAD brought the claw back.', 'holds': [], 'factions': [], 'named': ['Lucan Valerius']}]}
guard = {'name': 'Whiterun Guard', 'hold': 'Whiterun', 'guard': 1}
items = W.known_items(guard, world, 'CHAD')
check('guard of the hold knows fame, bounty and thane', items[:3] == ['CHAD is well known in Whiterun.', 'CHAD has a bounty of 40 gold in Whiterun.', 'CHAD is Thane of Whiterun.'], items)
reach = {'name': 'Markarth Guard', 'hold': 'Reach', 'guard': 1}
items = W.known_items(reach, world, 'CHAD')
check('stranger from another hold: no Whiterun news', 'CHAD is Thane of Whiterun.' not in items and 'CHAD is well known in Whiterun.' not in items, items)
check('their own hold\'s violent bounty', 'CHAD has a bounty of 1500 gold in the Reach for violent crimes.' in items, items)
citizen = {'name': 'Ysolda', 'hold': 'Whiterun'}
check('small bounty: only guards know', not any('bounty' in i for i in W.known_items(citizen, world, 'CHAD')))
check('big bounty: everyone in the hold', 'CHAD is wanted for crimes in the Reach.' in W.known_items({'name': 'x', 'hold': 'Reach'}, world, 'CHAD'))
check('group news only to members', 'CHAD works for the Thieves Guild in Riften.' in W.known_items({'name': 'Brynjolf', 'hold': 'Rift', 'groups': ['Thieves Guild']}, world, 'CHAD')
      and 'CHAD works for the Thieves Guild in Riften.' not in W.known_items(citizen, world, 'CHAD'))
check('named news only to those named', 'CHAD brought the claw back.' in W.known_items({'name': 'Lucan Valerius', 'hold': 'Whiterun'}, world, 'CHAD')
      and 'CHAD brought the claw back.' not in W.known_items(citizen, world, 'CHAD'))
check('Dragonborn left to Knowledge', 'CHAD killed a dragon.' not in W.known_items(citizen, world, 'CHAD', skip_dragonborn=True)
      and 'CHAD killed a dragon.' in W.known_items(citizen, world, 'CHAD'))
check('no hold: falls back to where the talk is', 'CHAD is well known in Whiterun.' in W.known_items({'name': 'Lydia'}, world, 'CHAD'))
check('famous', 'CHAD is famous all over the Rift.' in W.known_items({'name': 'x', 'hold': 'Rift'}, world, 'CHAD'))
t = W.text([citizen, {'name': 'Hulda', 'hold': 'Whiterun'}], world, 'CHAD')
check('same knowledge: one block', t.startswith('What everyone here knows about CHAD:\n- CHAD is well known in Whiterun.'), t)
t = W.text([citizen, reach], world, 'CHAD')
check('different knowledge: a block each', 'What Ysolda knows about CHAD:' in t and 'What Markarth Guard knows about CHAD:' in t, t)
check('no world, no text', W.text([citizen], {}, 'CHAD') == '' and W.text([], world, 'CHAD') == '')
check('nothing known, no text', W.text([{'name': 'x', 'hold': 'Pale'}], {'hold': 'Pale', 'fame': {}, 'events': []}, 'CHAD') == '')
check('broken values ignored', W.known_items({'name': 'x', 'hold': 'Whiterun', 'groups': 'oops'}, {'fame': {'Whiterun': 'lots'}, 'events': [None, {'text': 5}]}, 'CHAD') == [])

print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all passed'}")
sys.exit(1 if FAILS else 0)
