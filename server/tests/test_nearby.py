"""Offline tests for said-nearby lines and the banter reason (server/living_world/nearby.py).
Run with a Python 3.11: test_nearby.py <repo server dir>"""
import sys
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import nearby

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


NOW = 1_000_000.0
lines = [{'speaker': 'Serana', 'text': 'Old ruins always smell of dust and regret.', 'time': NOW - 30},
         {'speaker': 'Lydia', 'text': 'I am sworn to carry your burdens, as always.', 'time': NOW - 400},
         {'speaker': 'Serana', 'text': 'broken', 'time': 'soon'}, 'not a dict']

# test_said_nearby_only_recent: lines under 5 minutes old, with the don't-repeat rule
text = nearby.said_nearby(lines, NOW)
check('recent line kept', 'Serana: "Old ruins always smell of dust and regret."' in text, text)
check('old line dropped', 'Lydia' not in text, text)
check('broken entries skipped', 'broken' not in text, text)
check("don't-repeat rule added", 'do not repeat' in text.lower(), text)
check('nothing when all old', nearby.said_nearby(lines[1:2], NOW) == '')
check('nothing when empty', nearby.said_nearby([], NOW) == '')
many = [{'speaker': f'N{i}', 'text': f'line number {i} here', 'time': NOW - i} for i in range(8)]
check('at most three lines, newest', nearby.said_nearby(many, NOW).count(': "') == 3 and 'N0' in nearby.said_nearby(many, NOW))

# test_banter_seed_only_while_active
check('seed while active', nearby.seed({'seed': 'Mjoll heard Serana say that and reacts.', 'active': 1}) == '(Mjoll heard Serana say that and reacts.)')
check('no seed when inactive', nearby.seed({'seed': 'old', 'active': 0}) == '')
check('no seed when missing', nearby.seed({}) == '')

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
