"""Offline tests for the character overrides editor (server/living_world/ui_overrides.py).
Run with a Python 3.11: test_ui_overrides.py <repo server dir>"""
import csv, json, sys, tempfile
from pathlib import Path

SERVER = Path(sys.argv[1])
sys.path.insert(0, str(SERVER))
from living_world import ui_overrides as U

FAILS = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  -> ' + str(detail)) if not cond else ''))
    if not cond:
        FAILS.append(name)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    base = tmp / 'skyrim_characters.csv'
    with open(base, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['name', 'voice_model', 'bio', 'race', 'base_id', 'ref_id'])
        w.writeheader()
        w.writerow({'name': 'Lucan Valerius', 'voice_model': 'MaleEvenToned', 'bio': 'Lucan runs the shop.', 'race': 'Imperial', 'base_id': '01347A', 'ref_id': '013487'})
        w.writerow({'name': 'Camilla Valerius', 'voice_model': 'FemaleYoungEager', 'bio': 'Camilla flirts.', 'race': 'Imperial', 'base_id': '01347B', 'ref_id': '013488'})
    before = base.read_bytes()
    overrides = tmp / 'character_overrides'

    # test_find: by part of the name, base CSV first, then the user's overrides on top
    found = U.find_characters('lucan', str(base), str(overrides))
    check('found by part of the name', [r['name'] for r in found] == ['Lucan Valerius'], found)
    check('fields from the base csv', found[0]['bio'] == 'Lucan runs the shop.' and found[0]['voice_model'] == 'MaleEvenToned', found[0])

    # test_writes_only_changed_fields
    path = U.save_override(str(overrides), found[0], {'bio': 'Lucan runs the shop and frets about the claw.', 'voice_model': 'MaleEvenToned'}, str(base))
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    check('only the changed field plus the match keys', data == {'name': 'Lucan Valerius', 'race': 'Imperial', 'base_id': '01347A', 'bio': 'Lucan runs the shop and frets about the claw.'}, data)
    check('the override is seen next time', U.find_characters('lucan', str(base), str(overrides))[0]['bio'].endswith('frets about the claw.'))

    # test_mod_npc_without_base_id: NPCs not in the base csv are matched by name and race only (short light-plugin
    # base ids made one override replace another NPC's row)
    mod_npc = {'name': 'Nyri', 'race': 'Nord', 'base_id': '000821', 'bio': '', 'voice_model': ''}
    data = json.loads(Path(U.save_override(str(overrides), mod_npc, {'bio': 'Nyri hunts.'}, str(base))).read_text(encoding='utf-8'))
    check('mod NPC: no base id written', 'base_id' not in data and data['name'] == 'Nyri', data)

    # test_never_touches_base_csv
    check('base csv untouched', base.read_bytes() == before)
    check('nothing changed = nothing written', U.save_override(str(overrides), found[0], {'bio': 'Lucan runs the shop.'}, str(base)) is None)
    # review fixes: Mantella reads overrides with the system codepage, so only ASCII on disk; same names kept apart;
    # the user's list files never replaced
    p = U.save_override(str(overrides), mod_npc, {'bio': 'Nyri’s café “friend”.'}, str(base))
    check('written as ASCII (escaped)', Path(p).read_bytes().isascii() and json.loads(Path(p).read_text(encoding='ascii'))['bio'] == 'Nyri’s café “friend”.')
    bandit_a, bandit_b = {'name': 'Bandit', 'race': 'Nord', 'bio': 'a'}, {'name': 'Bandit', 'race': 'Redguard', 'bio': 'b'}
    pa, pb = U.save_override(str(overrides), bandit_a, {'bio': 'A Nord bandit.'}), U.save_override(str(overrides), bandit_b, {'bio': 'A Redguard bandit.'})
    check('two NPCs with one name get two files', pa != pb and json.loads(Path(pa).read_text())['race'] == 'Nord', (pa, pb))
    (overrides / 'Gang.json').write_text(json.dumps([{'name': 'Gang', 'bio': 'x'}, {'name': 'Gang2', 'bio': 'y'}]), encoding='utf-8')
    pg = U.save_override(str(overrides), {'name': 'Gang', 'bio': 'x'}, {'bio': 'z'})
    check('a list override file is never replaced', json.loads((overrides / 'Gang.json').read_text())[1]['name'] == 'Gang2' and Path(pg).name != 'Gang.json', pg)
check('user folder follows custom_user_folder.ini', U.user_folder(ini_text='[UserFolder]\ncustom_user_folder = E:/MantellaUser\n') == 'E:/MantellaUser')

print('RESULT: ' + ('ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'))
sys.exit(1 if FAILS else 0)
