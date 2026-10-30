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

world = {'hold': 'Whiterun', 'player': 'Player',
         'fame': {'Whiterun': 5, 'Reach': 0, 'Rift': 8}, 'bounty': {'Whiterun': 40, 'Reach': 1500}, 'bounty_violent': {'Whiterun': 0, 'Reach': 1000},
         'events': [{'id': 'thane_whiterun', 'text': 'Player is Thane of Whiterun.', 'holds': ['Whiterun'], 'factions': [], 'named': []},
                    {'id': 'tg01_thieves_guild', 'text': 'Player works for the Thieves Guild in Riften.', 'holds': [], 'factions': ['Thieves Guild'], 'named': []},
                    {'id': 'mq104_dragonborn', 'text': 'Player killed a dragon.', 'holds': ['all'], 'factions': [], 'named': []},
                    {'id': 'ms13_golden_claw', 'text': 'Player brought the claw back.', 'holds': [], 'factions': [], 'named': ['Lucan Valerius']}]}
guard = {'name': 'Whiterun Guard', 'hold': 'Whiterun', 'guard': 1}
items = W.known_items(guard, world, 'Player')
check('guard of the hold knows fame, bounty and thane', items[:3] == ['Player is well known in Whiterun.', 'Player has a bounty of 40 gold in Whiterun.', 'Player is Thane of Whiterun.'], items)
reach = {'name': 'Markarth Guard', 'hold': 'Reach', 'guard': 1}
items = W.known_items(reach, world, 'Player')
check('stranger from another hold: no Whiterun news', 'Player is Thane of Whiterun.' not in items and 'Player is well known in Whiterun.' not in items, items)
check('their own hold\'s violent bounty', 'Player has a bounty of 1500 gold in the Reach for violent crimes.' in items, items)
citizen = {'name': 'Ysolda', 'hold': 'Whiterun'}
check('small bounty: only guards know', not any('bounty' in i for i in W.known_items(citizen, world, 'Player')))
check('big bounty: everyone in the hold', 'Player is wanted for crimes in the Reach.' in W.known_items({'name': 'x', 'hold': 'Reach'}, world, 'Player'))
check('group news only to members', 'Player works for the Thieves Guild in Riften.' in W.known_items({'name': 'Brynjolf', 'hold': 'Rift', 'groups': ['Thieves Guild']}, world, 'Player')
      and 'Player works for the Thieves Guild in Riften.' not in W.known_items(citizen, world, 'Player'))
check('named news only to those named', 'Player brought the claw back.' in W.known_items({'name': 'Lucan Valerius', 'hold': 'Whiterun'}, world, 'Player')
      and 'Player brought the claw back.' not in W.known_items(citizen, world, 'Player'))
check('Dragonborn left to Knowledge', 'Player killed a dragon.' not in W.known_items(citizen, world, 'Player', skip_dragonborn=True)
      and 'Player killed a dragon.' in W.known_items(citizen, world, 'Player'))
check('no hold: falls back to where the talk is', 'Player is well known in Whiterun.' in W.known_items({'name': 'Lydia'}, world, 'Player'))
check('famous', 'Player is famous all over the Rift.' in W.known_items({'name': 'x', 'hold': 'Rift'}, world, 'Player'))
t = W.text([citizen, {'name': 'Hulda', 'hold': 'Whiterun'}], world, 'Player')
check('same knowledge: one block', t.startswith('What everyone here knows about Player:\n- Player is well known in Whiterun.'), t)
t = W.text([citizen, reach], world, 'Player')
check('different knowledge: a block each', 'What Ysolda knows about Player:' in t and 'What Markarth Guard knows about Player:' in t, t)
check('no world, no text', W.text([citizen], {}, 'Player') == '' and W.text([], world, 'Player') == '')
check('nothing known, no text', W.text([{'name': 'x', 'hold': 'Pale'}], {'hold': 'Pale', 'fame': {}, 'events': []}, 'Player') == '')
check('broken values ignored', W.known_items({'name': 'x', 'hold': 'Whiterun', 'groups': 'oops'}, {'fame': {'Whiterun': 'lots'}, 'events': [None, {'text': 5}]}, 'Player') == [])

print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all passed'}")
sys.exit(1 if FAILS else 0)
