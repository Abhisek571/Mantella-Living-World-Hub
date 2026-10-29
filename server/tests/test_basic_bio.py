"""Offline tests for the basic bio of NPCs Mantella has no bio for (server/living_world/basic_bio.py).
Run with a Python 3.11: test_basic_bio.py <repo server dir>"""
import sys
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import basic_bio as B

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)

guard = {'name': 'Whiterun Guard', 'race': 'Nord', 'sex': 'male', 'guard': 1, 'hold': 'Whiterun', 'location': 'Dragonsreach', 'class': 'Warrior'}
t = B.text(guard)
check('who, where and the guidance', t.startswith('You are Whiterun Guard, a male Nord guard. You are at Dragonsreach, in Whiterun.') and 'ordinary guard of Whiterun' in t, t)
smith = {'name': 'Ysolda', 'race': 'Nord', 'sex': 'female', 'work': 'merchant', 'hold': 'Whiterun', 'location': 'Whiterun', 'class': 'Citizen'}
check('town name not repeated as the place', 'You live in Whiterun.' in B.text(smith) and 'at Whiterun' not in B.text(smith), B.text(smith))
check('a class that is no job is left out', B.text({'name': 'G', 'race': 'Nord', 'sex': 'male', 'class': 'dremora'}) .startswith('You are G, a male Nord.'), B.text({'name': 'G', 'race': 'Nord', 'sex': 'male', 'class': 'dremora'}))
check('a job class is used', 'a female Nord blacksmith.' in B.text({'name': 'H', 'race': 'Nord', 'sex': 'female', 'class': 'Blacksmith'}))
check('job beats class', 'a female Nord merchant.' in B.text(smith))
check('the Reach', 'in the Reach' in B.text({'name': 'X', 'hold': 'Reach'}), B.text({'name': 'X', 'hold': 'Reach'}))
check('an before a vowel', 'an Imperial' in B.text({'name': 'X', 'race': 'Imperial'}), B.text({'name': 'X', 'race': 'Imperial'}))
check('groups named', 'You belong to the Companions.' in B.text({'name': 'Aela', 'groups': ['Companions']}))
check('no name: nothing', B.text({'race': 'Nord'}) == '')
stock = "# Background\nYou are a male Nord Whiterun Guard.\n\n# History\nYou are a female  Ysolda."
out = B.replace(stock, [guard, smith])
check("Mantella's one-liners replaced", 'You are a male Nord Whiterun Guard.' not in out and 'You are Whiterun Guard, a male Nord guard.' in out and 'You are Ysolda, a female Nord merchant.' in out, out)
real = "# Background\nYsolda is a young Nord woman who dreams of becoming a merchant."
check('real bios left alone', B.replace(real, [smith]) == real)
group = "# Background\nYsolda: You are a female Nord Ysolda.\nLydia: Lydia is a housecarl."
check('group bios: only the stock one replaced', 'Ysolda: You are Ysolda, a female Nord merchant.' in B.replace(group, [smith, {'name': 'Lydia'}]) and 'Lydia is a housecarl.' in B.replace(group, [smith]))
check('names with regex characters are safe', B.replace('You are a male Nord Guard (Old).', [{'name': 'Guard (Old)', 'race': 'Nord'}]).startswith('You are Guard (Old), a Nord'))

print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all passed'}")
sys.exit(1 if FAILS else 0)
