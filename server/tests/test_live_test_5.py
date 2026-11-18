"""Offline tests for defects found by live test 5 (2026-11-15) that live in the module repos next to the Hub: the silent
bookkeeping actions (an NPC said "I'm rating her appetite quietly as a succubus, very high." while rating it) must say
what may not be spoken and that the spoken reply carries on the talk. Repos that are not checked out are skipped.
Run with a Python 3.11: test_live_test_5.py <repo server dir>"""
import json, re, sys
from pathlib import Path

SERVER = Path(sys.argv[1]).resolve()
CODING = SERVER.parent.parent

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


def repo(name):
    path = CODING / f'Mantella-Living-World-{name}'
    if not path.is_dir():
        print(f'SKIP {name} is not checked out next to the Hub')
        return None
    return path


def action(path, ident):
    return json.loads((path / 'SKSE' / 'Plugins' / 'MantellaSoftware' / 'data' / 'actions' / f'{ident}.json').read_text(encoding='utf-8'))


SILENT = {'Arousal': ['mantella_osla_rate_appetite', 'mantella_osla_arouse', 'mantella_osla_calm', 'mantella_osla_add_climaxes'],
          'OStim-Expansion': ['mantella_mae_rate_positions'], 'Relationships': ['mantella_maras_affection']}
for name, idents in SILENT.items():
    path = repo(name)
    if not path:
        continue
    for ident in idents:
        desc = action(path, ident).get('description', '')
        check(f'{ident}: the description says it is silent and what must not be spoken', 'Silent:' in desc and re.search(r'never (say|mention)', desc, re.I), desc)

arousal = repo('Arousal')
if arousal:
    src = (arousal / 'Source' / 'Scripts' / 'MantellaOSLA_Main.psc').read_text(encoding='utf-8')
    line = re.search(r'''SendLine\(npc\.GetDisplayName\(\) \+ "'s sexual appetite has not been rated yet\.([^"]*)"\)''', src)
    text = line.group(1) if line else ''
    check('appetite event: the rating is only the action number', 'only as the number in the RateAppetite action' in text, text)
    check('appetite event: says what must not be spoken', 'never say, hint at or describe it, or mention this note' in text, text)
    check('appetite event: the spoken reply carries on the talk', 'the spoken reply goes on with the talk' in text, text)
    check('appetite event: the old weak wording is gone', 'without a word about it' not in src)
ostim = repo('OStim-Expansion')
if ostim:
    src = (ostim / 'Source' / 'Scripts' / 'MAE_Positions.psc').read_text(encoding='utf-8')
    body = re.search(r'string Function UnratedLine\(.*?EndFunction', src, re.S)
    body = body.group(0) if body else ''
    check('positions event: still says "have not been rated yet." (the live test validator looks for it)', 'have not been rated yet.' in body)
    check('positions event: only in the action, never spoken, the reply carries on', 'only in the RateFavoritePositions action' in body
          and 'never say, hint at or list them' in body and 'the spoken reply goes on' in body, body)

print(f'\n{len(FAILS)} failed' if FAILS else '\nall passed')
sys.exit(1 if FAILS else 0)
